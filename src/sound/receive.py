
import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Literal, Protocol, override

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosedOK

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
from sound.stream_flush import StreamFlush, StreamFlushAck, StreamFlushController

_CODEC: Final[dict[str, JsonValue]] = {
    "format": "L16",
    "clock_rate_hz": 16_000,
    "channels": 1,
    "payload_type": 96,
    "samples_per_frame": 320,
}


@dataclass(frozen=True, slots=True)
class _ActiveCommand:

    trace_id: str

    session_id: str

    seq: int

    turn_id: str | None

    segment_id: str | None

    cancellation_epoch: int | None


class UdpBinding(Protocol):

    @property
    def port(self) -> int:

        ...

    def set_packet_handler(self, handler: Callable[[bytes], None]) -> None:

        ...

    def close(self) -> None:

        ...


class UdpBinder(Protocol):

    async def bind(self, host: str, port: int) -> UdpBinding:

        ...


class _SocketAddressTransport(Protocol):

    def get_extra_info(
        self, name: Literal["sockname"], default: tuple[str, int]
    ) -> tuple[str, int]:

        ...


class ControlConnection(Protocol):

    async def send(self, message: str) -> None:

        ...

    async def recv(self) -> str | None:

        ...

    async def close(self) -> None:

        ...


class ControlConnector(Protocol):

    async def connect(self, url: str, headers: dict[str, str]) -> ControlConnection:

        ...


class _DatagramProtocol(asyncio.DatagramProtocol):

    def __init__(self) -> None:

        self.handler: Callable[[bytes], None] | None = None

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:

        _ = addr

        if self.handler is not None:
            self.handler(data)


@dataclass(slots=True)
class _AsyncioUdpBinding:

    transport: asyncio.DatagramTransport

    protocol: _DatagramProtocol

    bound_port: int

    @property
    def port(self) -> int:

        return self.bound_port

    def set_packet_handler(self, handler: Callable[[bytes], None]) -> None:

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

    async def connect(self, url: str, headers: dict[str, str]) -> ControlConnection:

        return _WebsocketsControlConnection(
            await connect(url, additional_headers=headers)
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

    async def run(self) -> None:

        binding = await self.udp_binder.bind(self.config.rtp_host, self.config.rtp_port)

        receiver = RtpPlaybackReceiver(playback_sink=self.playback_sink)

        flushes = StreamFlushController(
            session_id=self.config.session_id, receiver=receiver
        )

        connection: ControlConnection | None = None

        notification_writer: NotificationWriter | None = None

        active_stream_id: str | None = None

        active_cancel_target: str | None = None

        active_command: _ActiveCommand | None = None

        def receive_packet(packet: bytes) -> None:

            state_count = len(receiver.playback_states)

            receiver.receive_packet(packet, stream_id=active_stream_id)

            if (
                notification_writer is not None
                and active_command is not None
                and len(receiver.playback_states) > state_count
            ):
                notification_writer.enqueue(
                    OutboundNotification(
                        message=self._state_envelope(active_command, "playing"),
                        stream_id=active_stream_id,
                        is_playing=True,
                    )
                )

        binding.set_packet_handler(receive_packet)

        try:
            headers = _authorization_headers(self.config.trusted_lan_token)

            connection = await self.control_connector.connect(
                self.config.orchestrator_ws_url, headers
            )

            notification_writer = NotificationWriter(connection)

            async with asyncio.TaskGroup() as task_group:
                _ = task_group.create_task(notification_writer.run())

                try:
                    await notification_writer.send(
                        OutboundNotification(
                            message=self._register_envelope(binding.port)
                        )
                    )

                    while message := await connection.recv():
                        event = parse_event(message)

                        event_type = required_str(event, "event_type")

                        match event_type:
                            case "media.stream.command":
                                active_stream_id = _announce_command(
                                    receiver=receiver,
                                    event=event,
                                    expected_stream_id=self.config.stream_id,
                                    expected_port=binding.port,
                                )

                                if active_stream_id is not None:
                                    active_command = _active_command(event)

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

                                    active_cancel_target = None

                                    active_command = None

                            case "media.stream.flush":
                                acknowledgement = flushes.apply(_flush(event))

                                if acknowledgement is not None:
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

                                    if acknowledgement.stream_id == active_stream_id:
                                        active_stream_id = None

                                        active_cancel_target = None

                                        active_command = None

                            case _:
                                continue

                finally:
                    notification_writer.close()

        except ConnectionClosedOK:
            return

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
            "stream_id": self.config.stream_id,
            "state": state,
        }

        if command.cancellation_epoch is not None:
            data["cancellation_epoch"] = command.cancellation_epoch

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
            },
        )


def _authorization_headers(token: str | None) -> dict[str, str]:

    if token is None:
        return {}

    return {"authorization": f"Bearer {token}"}


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

    endpoint = required_mapping(data, "rtp_endpoint")

    if (
        stream_id != expected_stream_id
        or required_int(endpoint, "port") != expected_port
    ):
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
        trace_id=required_str(event, "trace_id"),
        session_id=required_str(event, "session_id"),
        seq=required_int(event, "seq"),
        turn_id=optional_str(event, "turn_id"),
        segment_id=optional_str(event, "segment_id"),
        cancellation_epoch=_optional_int(data, "cancellation_epoch"),
    )


def _optional_int(source: Mapping[str, JsonValue], field: str) -> int | None:

    if field not in source:
        return None

    return required_int(source, field)


def main() -> None:

    config = load_runtime_config()

    runtime = ReceiveRuntime(
        config=config,
        udp_binder=AsyncioUdpBinder(),
        control_connector=WebsocketsControlConnector(),
        playback_sink=PortAudioPlaybackSink(device=config.playback_device),
    )

    asyncio.run(runtime.run())
