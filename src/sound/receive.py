import asyncio
import logging
import os
import random
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from time import monotonic_ns
from typing import Final, Literal, Protocol, cast, override
from urllib.parse import urlparse

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from sound.notification_writer import NotificationWriter, OutboundNotification
from sound.orchestrator_ws import (
    JsonValue,
    encode_envelope,
    optional_str,
    parse_event,
    required_int,
    required_mapping,
    required_str,
)
from sound.portaudio_playback import PortAudioPlaybackSink
from sound.receive_config import SoundReceiveConfig, load_runtime_config
from sound.rtp_playback import L16PlaybackSink, RtpPlaybackReceiver
from sound.stream_flush import (
    FlushDisposition,
    StreamFlush,
    StreamFlushAck,
    StreamFlushController,
)
from sound.tls import build_tls_context

_CODEC: Final[dict[str, JsonValue]] = {
    "format": "L16",
    "clock_rate_hz": 16_000,
    "channels": 1,
    "payload_type": 96,
    "samples_per_frame": 320,
}

_LOGGER = logging.getLogger(__name__)
_RTP_NOMINAL_GAP_MS: Final = 20.0
_RTP_LATE_GAP_MS: Final = 40.0
_RECONNECT_DELAYS: Final = (0.5, 1.0, 2.0, 4.0, 8.0, 10.0)
_DRAIN_TIMEOUT_SECONDS: Final = 5.0


@dataclass(slots=True)
class _IngressTiming:
    """Per-output diagnostics that isolate upstream RTP delivery from playback."""

    packet_count: int = 0
    dropped_packets: int = 0
    late_gap_count: int = 0
    max_gap_ms: float = 0.0
    _last_arrival_ns: int | None = None

    def record_arrival(self) -> None:
        now_ns = monotonic_ns()
        previous_ns = self._last_arrival_ns
        self._last_arrival_ns = now_ns
        self.packet_count += 1
        if previous_ns is None:
            return
        gap_ms = (now_ns - previous_ns) / 1_000_000
        self.max_gap_ms = max(self.max_gap_ms, gap_ms)
        if gap_ms > _RTP_LATE_GAP_MS:
            self.late_gap_count += 1

    def record_drop(self) -> None:
        self.dropped_packets += 1

    def log(self, *, stream_id: str) -> None:
        _LOGGER.debug(
            "rtp_ingress_diagnostic stream=%s packets=%d drops=%d late_gaps=%d "
            + "max_gap_ms=%.3f nominal_gap_ms=%.1f",
            stream_id,
            self.packet_count,
            self.dropped_packets,
            self.late_gap_count,
            self.max_gap_ms,
            _RTP_NOMINAL_GAP_MS,
        )



@dataclass(frozen=True, slots=True)
class _ActiveCommand:
    command_id: str

    trace_id: str

    session_id: str

    seq: int

    turn_id: str | None

    segment_id: str | None

    cancellation_epoch: int

    rtp_sender_endpoint: tuple[str, int]


class UdpBinding(Protocol):
    @property
    def port(self) -> int: ...

    def set_packet_handler(
        self, handler: Callable[[bytes, tuple[str, int] | None], None]
    ) -> None: ...

    def close(self) -> None: ...


class UdpBinder(Protocol):
    async def bind(self, host: str, port: int) -> UdpBinding: ...


class _SocketAddressTransport(Protocol):
    def get_extra_info(
        self, name: Literal["sockname"], default: tuple[str, int]
    ) -> tuple[str, int]: ...


class ControlConnection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | None: ...

    async def close(self) -> None: ...


class ControlConnector(Protocol):
    async def connect(
        self,
        url: str,
        headers: dict[str, str],
        ssl_context: ssl.SSLContext | None,
    ) -> ControlConnection: ...


class _DatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:

        self.handler: Callable[[bytes, tuple[str, int] | None], None] | None = None

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:

        if self.handler is not None:
            self.handler(data, addr)


@dataclass(slots=True)
class _AsyncioUdpBinding:
    transport: asyncio.DatagramTransport

    protocol: _DatagramProtocol

    bound_port: int

    @property
    def port(self) -> int:

        return self.bound_port

    def set_packet_handler(
        self, handler: Callable[[bytes, tuple[str, int] | None], None]
    ) -> None:

        self.protocol.handler = handler

    def close(self) -> None:

        self.transport.close()


class AsyncioUdpBinder:
    async def bind(self, host: str, port: int) -> UdpBinding:

        loop = asyncio.get_running_loop()

        transport, protocol = await loop.create_datagram_endpoint(
            _DatagramProtocol,
            local_addr=(host, port),
        )

        return _AsyncioUdpBinding(
            transport=transport,
            protocol=protocol,
            bound_port=_bound_udp_port(transport),
        )


class WebsocketsControlConnector:
    async def connect(
        self,
        url: str,
        headers: dict[str, str],
        ssl_context: ssl.SSLContext | None,
    ) -> ControlConnection:

        if urlparse(url).scheme != "wss" or ssl_context is None:
            return _WebsocketsControlConnection(
                await connect(url, additional_headers=headers)
            )

        return _WebsocketsControlConnection(
            await connect(url, additional_headers=headers, ssl=ssl_context)
        )


@dataclass(frozen=True, slots=True)
class _WebsocketsControlConnection:
    connection: ClientConnection

    async def send(self, message: str) -> None:

        await self.connection.send(message)

    async def recv(self) -> str | None:

        message = await self.connection.recv()

        if not isinstance(message, str):
            raise TypeError("control frames must be text")

        return message

    async def close(self) -> None:

        await self.connection.close()


@dataclass(slots=True)
class ReceiveRuntime:
    config: SoundReceiveConfig

    udp_binder: UdpBinder

    control_connector: ControlConnector

    playback_sink: L16PlaybackSink

    _registered: bool = field(default=False, init=False, repr=False)

    async def run(self) -> None:
        attempt = 0
        while True:
            self._registered = False
            try:
                await self._run_once()
            except asyncio.CancelledError:
                raise
            except Exception as error:
                if not _is_reconnectable(error):
                    raise
                if self._registered:
                    attempt = 0
                delay = _RECONNECT_DELAYS[min(attempt, len(_RECONNECT_DELAYS) - 1)]
                attempt += 1
                _LOGGER.exception(
                    "sound_connection_failed session=%s outcome=reconnect delay=%.3f",
                    self.config.session_id,
                    delay,
                )
                await asyncio.sleep(delay * random.uniform(0.8, 1.2))
                continue
            return

    async def _run_once(self) -> None:

        binding = await self.udp_binder.bind(self.config.rtp_host, self.config.rtp_port)

        receiver = RtpPlaybackReceiver(
            playback_sink=self.playback_sink,
            jitter_target_ms=self.config.jitter_target_ms,
            jitter_max_ms=self.config.jitter_max_ms,
        )

        flushes = StreamFlushController(
            session_id=self.config.session_id, receiver=receiver
        )

        connection: ControlConnection | None = None

        notification_writer: NotificationWriter | None = None

        active_stream_id: str | None = None

        active_cancel_target: str | None = None

        active_command: _ActiveCommand | None = None

        playing_stream_id: str | None = None

        ingress_timing = _IngressTiming()

        playback_queue: asyncio.Queue[tuple[bytes, str | None]] = asyncio.Queue(
            maxsize=256
        )

        def receive_packet(
            packet: bytes, sender: tuple[str, int] | None = None
        ) -> None:
            # Datagram callbacks must stay bounded.  Playback is clocked below
            # by PortAudio, so short scheduler/network bursts cannot underflow
            # the device once the local reserve has been admitted.
            ingress_timing.record_arrival()
            if (
                sender is not None
                and active_command is not None
                and sender != active_command.rtp_sender_endpoint
            ):
                ingress_timing.record_drop()
                return
            if playback_queue.full():
                ingress_timing.record_drop()
                return
            playback_queue.put_nowait((packet, active_stream_id))

        async def play_buffered_packets() -> None:
            nonlocal playing_stream_id
            started = False
            while True:
                packet, stream_id = await playback_queue.get()
                try:
                    if not started:
                        started = True
                    # Do not use the asyncio task as a 20 ms media clock.  It
                    # can wake late under ordinary desktop load, turning one
                    # late timer into an audible hole.  The callback sink owns
                    # the hardware clock; feed its bounded local PCM reserve
                    # immediately so it can absorb scheduling/network bursts.
                    state_count = len(receiver.playback_states)
                    receiver.receive_packet(packet, stream_id=stream_id)
                    if (
                        notification_writer is not None
                        and active_command is not None
                        and stream_id is not None
                        and stream_id != playing_stream_id
                        and len(receiver.playback_states) > state_count
                    ):
                        notification_writer.enqueue(
                            OutboundNotification(
                                message=self._state_envelope(active_command, "playing"),
                                stream_id=stream_id,
                                is_playing=True,
                            )
                        )
                        # ``playing`` is a state transition, not per-frame
                        # telemetry.  Sending one WebSocket command for every
                        # 20 ms RTP frame makes the control path compete with
                        # the real-time playback path (50 sends/second).
                        playing_stream_id = stream_id
                finally:
                    playback_queue.task_done()

        binding.set_packet_handler(receive_packet)

        async def receive_control_message() -> str | None:
            assert connection is not None
            try:
                return await connection.recv()
            except ConnectionClosedOK:
                # A peer's normal close (for example 1001, going away) ends
                # the control loop. Handling it before TaskGroup exits avoids
                # wrapping it in an ExceptionGroup and allows graceful cleanup.
                return None

        try:
            headers = _authorization_headers(self.config.trusted_lan_token)

            tls_context = (
                build_tls_context(self.config.tls_ca_path)
                if urlparse(self.config.orchestrator_ws_url).scheme == "wss"
                else None
            )

            connection = await self.control_connector.connect(
                self.config.orchestrator_ws_url, headers, tls_context
            )

            notification_writer = NotificationWriter(connection)

            async with asyncio.TaskGroup() as task_group:
                _ = task_group.create_task(notification_writer.run())
                playback_task = task_group.create_task(play_buffered_packets())

                try:
                    await notification_writer.send(
                        OutboundNotification(
                            message=self._register_envelope(binding.port)
                        )
                    )
                    self._registered = True

                    while message := await receive_control_message():
                        event = parse_event(message)

                        event_type = required_str(event, "event_type")

                        match event_type:
                            case "media.stream.command":
                                candidate_command = _active_command(event)
                                if active_command is not None:
                                    if candidate_command == active_command:
                                        continue
                                    if (
                                        candidate_command.cancellation_epoch
                                        <= active_command.cancellation_epoch
                                    ):
                                        continue
                                active_stream_id = _announce_command(
                                    receiver=receiver,
                                    event=event,
                                    expected_stream_id=self.config.stream_id,
                                    expected_port=binding.port,
                                )

                                if active_stream_id is not None:
                                    active_command = candidate_command

                                    playing_stream_id = None

                                    ingress_timing = _IngressTiming()

                                    active_cancel_target = (
                                        active_command.segment_id or active_stream_id
                                    )

                                    await notification_writer.send(
                                        OutboundNotification(
                                            message=self._ready_envelope(event)
                                        )
                                    )

                                    await notification_writer.send(
                                        OutboundNotification(
                                            message=self._state_envelope(
                                                active_command, "queued"
                                            )
                                        )
                                    )

                            case "cancel":
                                if (
                                    active_stream_id is not None
                                    and optional_str(event, "segment_id")
                                    == active_cancel_target
                                ):
                                    _discard_queued_stream(
                                        playback_queue, active_stream_id
                                    )
                                    receiver.cancel_stream(active_stream_id)

                                    await notification_writer.invalidate_playing(
                                        active_stream_id
                                    )

                                    if active_command is not None:
                                        await notification_writer.send(
                                            OutboundNotification(
                                                message=self._state_envelope(
                                                    active_command, "cancelled"
                                                )
                                            )
                                        )

                                    active_stream_id = None

                                    playing_stream_id = None

                                    active_cancel_target = None

                                    active_command = None

                            case "media.stream.flush":
                                acknowledgement = flushes.apply(_flush(event))

                                if acknowledgement is not None:
                                    if (
                                        acknowledgement.disposition
                                        is FlushDisposition.APPLIED
                                    ):
                                        _discard_queued_stream(
                                            playback_queue,
                                            acknowledgement.stream_id,
                                        )
                                        await notification_writer.invalidate_playing(
                                            acknowledgement.stream_id
                                        )

                                    await notification_writer.send(
                                        OutboundNotification(
                                            message=self._flush_ack_envelope(
                                                event, acknowledgement
                                            )
                                        )
                                    )

                                    if (
                                        acknowledgement.disposition
                                        is FlushDisposition.APPLIED
                                        and acknowledgement.stream_id
                                        == active_stream_id
                                    ):
                                        active_stream_id = None

                                        playing_stream_id = None

                                        active_cancel_target = None

                                        active_command = None

                            case "media.stream.end":
                                if active_stream_id is None or active_command is None:
                                    continue
                                data = required_mapping(event, "data")
                                if required_str(
                                    data, "stream_id"
                                ) != active_stream_id or (
                                    required_str(data, "command_id")
                                    != active_command.command_id
                                    or required_int(data, "cancellation_epoch")
                                    != active_command.cancellation_epoch
                                ):
                                    continue
                                # The final RTP packet was paced before this WSS
                                # command. Allow it to reach UDP first, then drain
                                # the actual PortAudio queue before reporting done.
                                await asyncio.sleep(0.100)
                                ingress_timing.log(stream_id=active_stream_id)
                                if receiver.finish_stream(
                                    active_stream_id, required_int(data, "ssrc")
                                ):
                                    completed_command = _ActiveCommand(
                                        command_id=active_command.command_id,
                                        trace_id=active_command.trace_id,
                                        session_id=active_command.session_id,
                                        seq=active_command.seq,
                                        turn_id=active_command.turn_id,
                                        segment_id=active_command.segment_id,
                                        cancellation_epoch=required_int(
                                            data, "cancellation_epoch"
                                        ),
                                        rtp_sender_endpoint=(
                                            active_command.rtp_sender_endpoint
                                        ),
                                    )
                                    drain = getattr(
                                        self.playback_sink,
                                        "wait_stream_drained",
                                        None,
                                    )
                                    try:
                                        if drain is not None:
                                            async with asyncio.timeout(
                                                _DRAIN_TIMEOUT_SECONDS
                                            ):
                                                await drain(active_stream_id)
                                    except TimeoutError:
                                        self.playback_sink.close_stream(active_stream_id)
                                        await notification_writer.send(
                                            OutboundNotification(
                                                message=self._state_envelope(
                                                    completed_command, "error"
                                                )
                                            )
                                        )
                                    else:
                                        await notification_writer.send(
                                            OutboundNotification(
                                                message=self._state_envelope(
                                                    completed_command, "finished"
                                                )
                                            )
                                        )
                                    active_stream_id = None
                                    playing_stream_id = None
                                    active_cancel_target = None
                                    active_command = None

                            case _:
                                pass

                        # Let the clocked playback task consume an already
                        # buffered RTP frame before processing the next control
                        # frame (notably a cancellation in test or shutdown).
                        await asyncio.sleep(0.001)

                finally:
                    # The control peer may close immediately after its final
                    # media command while the RTP datagram is already in the
                    # local jitter buffer.  Do not cancel the clocked consumer
                    # first: that loses an authorized frame before Sound has
                    # had a chance to render it.
                    await playback_queue.join()
                    notification_writer.close()
                    _ = playback_task.cancel()

        finally:
            receiver.close()

            binding.close()

            if connection is not None:
                await connection.close()

    def _register_envelope(self, bound_port: int) -> str:

        return encode_envelope(
            event_type="media.rtp.sink.register",
            trace_id=self.config.trace_id,
            session_id=self.config.session_id,
            seq=0,
            data={
                "stream_id": self.config.stream_id,
                "codec": _CODEC,
                "rtp_endpoint": {
                    "host": self.config.advertised_rtp_host,
                    "port": bound_port,
                },
            },
        )

    def _ready_envelope(self, event: Mapping[str, JsonValue]) -> str:

        return encode_envelope(
            event_type="media.rtp.sink.ready",
            trace_id=required_str(event, "trace_id"),
            session_id=required_str(event, "session_id"),
            seq=required_int(event, "seq"),
            data={"stream_id": self.config.stream_id},
        )

    def _state_envelope(self, command: _ActiveCommand, state: str) -> str:

        data: dict[str, JsonValue] = {
            "command_id": command.command_id,
            "stream_id": self.config.stream_id,
            "state": state,
            "cancellation_epoch": command.cancellation_epoch,
        }

        return encode_envelope(
            event_type="media.stream.state",
            trace_id=command.trace_id,
            session_id=command.session_id,
            seq=command.seq,
            turn_id=command.turn_id,
            segment_id=command.segment_id,
            data=data,
        )

    def _flush_ack_envelope(
        self, event: Mapping[str, JsonValue], acknowledgement: StreamFlushAck
    ) -> str:

        return encode_envelope(
            event_type="media.stream.flush.ack",
            trace_id=required_str(event, "trace_id"),
            session_id=acknowledgement.session_id,
            seq=required_int(event, "seq"),
            turn_id=acknowledgement.turn_id,
            segment_id=acknowledgement.segment_id,
            data={
                "stream_id": acknowledgement.stream_id,
                "cancellation_epoch": acknowledgement.cancellation_epoch,
                "request_id": acknowledgement.request_id,
                "target_generated_ssrc": acknowledgement.target_generated_ssrc,
                "disposition": acknowledgement.disposition.value,
            },
        )


def _authorization_headers(token: str | None) -> dict[str, str]:

    if token is None:
        return {}

    return {"authorization": f"Bearer {token}"}


def _is_reconnectable(error: BaseException) -> bool:
    if isinstance(error, BaseExceptionGroup):
        grouped = cast("BaseExceptionGroup[BaseException]", error)
        return bool(grouped.exceptions) and all(
            _is_reconnectable(item) for item in grouped.exceptions
        )
    return isinstance(error, ConnectionClosedError | OSError | TimeoutError)


def _bound_udp_port(transport: _SocketAddressTransport) -> int:

    socket_address = transport.get_extra_info("sockname", ("", -1))

    bound_port = socket_address[1]

    if bound_port < 0:
        raise RuntimeError("UDP endpoint did not expose its bound port")

    return bound_port


def _announce_command(
    *,
    receiver: RtpPlaybackReceiver,
    event: Mapping[str, JsonValue],
    expected_stream_id: str,
    expected_port: int,
) -> str | None:

    data = required_mapping(event, "data")

    stream_id = required_str(data, "stream_id")

    _ = expected_port
    if stream_id != expected_stream_id:
        return None

    if required_mapping(data, "codec") != _CODEC:
        return None

    receiver.announce_stream(
        stream_id=stream_id,
        sample_rate=required_int(required_mapping(data, "codec"), "clock_rate_hz"),
        channels=required_int(required_mapping(data, "codec"), "channels"),
        expected_ssrc=required_int(data, "ssrc"),
    )

    return stream_id


def _flush(event: Mapping[str, JsonValue]) -> StreamFlush:

    data = required_mapping(event, "data")

    return StreamFlush(
        session_id=required_str(event, "session_id"),
        stream_id=required_str(data, "stream_id"),
        turn_id=required_str(event, "turn_id"),
        segment_id=required_str(event, "segment_id"),
        cancellation_epoch=required_int(data, "cancellation_epoch"),
        request_id=required_str(data, "request_id"),
        target_generated_ssrc=required_int(data, "target_generated_ssrc"),
    )


def _active_command(event: Mapping[str, JsonValue]) -> _ActiveCommand:

    data = required_mapping(event, "data")

    return _ActiveCommand(
        command_id=required_str(data, "command_id"),
        trace_id=required_str(event, "trace_id"),
        session_id=required_str(event, "session_id"),
        seq=required_int(event, "seq"),
        turn_id=optional_str(event, "turn_id"),
        segment_id=optional_str(event, "segment_id"),
        cancellation_epoch=required_int(data, "cancellation_epoch"),
        rtp_sender_endpoint=(
            required_str(required_mapping(data, "rtp_sender_endpoint"), "host"),
            required_int(required_mapping(data, "rtp_sender_endpoint"), "port"),
        ),
    )


def _discard_queued_stream(
    queue: asyncio.Queue[tuple[bytes, str | None]], stream_id: str
) -> None:
    retained: list[tuple[bytes, str | None]] = []
    while not queue.empty():
        packet = queue.get_nowait()
        if packet[1] != stream_id:
            retained.append(packet)
        queue.task_done()
    for packet in retained:
        _ = queue.put_nowait(packet)


def main() -> None:
    logging.basicConfig(
        level=getattr(
            logging, os.environ.get("BITNP_LOG_LEVEL", "INFO").upper(), logging.INFO
        ),
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    config = load_runtime_config()

    runtime = ReceiveRuntime(
        config=config,
        udp_binder=AsyncioUdpBinder(),
        control_connector=WebsocketsControlConnector(),
        playback_sink=PortAudioPlaybackSink(device=config.playback_device),
    )

    asyncio.run(runtime.run())
