import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Final, Protocol

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosedOK

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

_CODEC: Final[dict[str, JsonValue]] = {
    "format": "L16",
    "clock_rate_hz": 16_000,
    "channels": 1,
    "payload_type": 96,
    "samples_per_frame": 320,
}

class UdpBinding(Protocol):
    @property
    def port(self) -> int: ...

    def set_packet_handler(self, handler: Callable[[bytes], None]) -> None: ...

    def close(self) -> None: ...


class UdpBinder(Protocol):
    async def bind(self, host: str, port: int) -> UdpBinding: ...


class ControlConnection(Protocol):
    async def send(self, message: str) -> None: ...

    async def recv(self) -> str | None: ...

    async def close(self) -> None: ...


class ControlConnector(Protocol):
    async def connect(self, url: str, headers: dict[str, str]) -> ControlConnection: ...


class _DatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self) -> None:
        self.handler: Callable[[bytes], None] | None = None

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
        socket_address = transport.get_extra_info("sockname")
        if not isinstance(socket_address, tuple) or len(socket_address) != 2:
            raise RuntimeError("UDP endpoint did not expose its bound port")
        bound_port = socket_address[1]
        if not isinstance(bound_port, int):
            raise TypeError("UDP endpoint exposed a non-integer port")
        return _AsyncioUdpBinding(
            transport=transport,
            protocol=protocol,
            bound_port=bound_port,
        )


class WebsocketsControlConnector:
    async def connect(self, url: str, headers: dict[str, str]) -> ControlConnection:
        return _WebsocketsControlConnection(await connect(url, additional_headers=headers))


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
        connection: ControlConnection | None = None
        active_stream_id: str | None = None
        active_cancel_target: str | None = None
        active_event: Mapping[str, JsonValue] | None = None

        def receive_packet(packet: bytes) -> None:
            state_count = len(receiver.playback_states)
            receiver.receive_packet(packet, stream_id=active_stream_id)
            if (
                connection is not None
                and active_event is not None
                and len(receiver.playback_states) > state_count
            ):
                _ = asyncio.create_task(connection.send(self._state_envelope(active_event, "playing")))

        binding.set_packet_handler(receive_packet)
        try:
            headers = _authorization_headers(self.config.trusted_lan_token)
            connection = await self.control_connector.connect(self.config.orchestrator_ws_url, headers)
            await connection.send(self._register_envelope(binding.port))
            while message := await connection.recv():
                await asyncio.sleep(0)
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
                            active_event = event
                            active_cancel_target = optional_str(event, "segment_id") or active_stream_id
                            await connection.send(self._ready_envelope(event))
                            await connection.send(self._state_envelope(event, "queued"))
                    case "cancel":
                        if (
                            active_stream_id is not None
                            and optional_str(event, "segment_id") == active_cancel_target
                        ):
                            receiver.cancel_stream(active_stream_id)
                            await connection.send(self._state_envelope(event, "cancelled"))
                            active_stream_id = None
                            active_cancel_target = None
                            active_event = None
                    case _:
                        continue
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
            data={
                "stream_id": self.config.stream_id,
                "codec": _CODEC,
                "rtp_endpoint": {"host": self.config.advertised_rtp_host, "port": bound_port},
            },
        )

    def _ready_envelope(self, event: Mapping[str, JsonValue]) -> str:
        return encode_envelope(
            event_type="media.rtp.sink.ready",
            trace_id=required_str(event, "trace_id"),
            session_id=required_str(event, "session_id"),
            data={"stream_id": self.config.stream_id},
        )

    def _state_envelope(self, event: Mapping[str, JsonValue], state: str) -> str:
        return encode_envelope(
            event_type="media.stream.state",
            trace_id=required_str(event, "trace_id"),
            session_id=required_str(event, "session_id"),
            turn_id=optional_str(event, "turn_id"),
            segment_id=optional_str(event, "segment_id"),
            data={"stream_id": self.config.stream_id, "state": state},
        )


def _authorization_headers(token: str | None) -> dict[str, str]:
    if token is None:
        return {}
    return {"authorization": f"Bearer {token}"}


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
    if stream_id != expected_stream_id or required_int(endpoint, "port") != expected_port:
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


def main() -> None:
    config = load_runtime_config()
    runtime = ReceiveRuntime(
        config=config,
        udp_binder=AsyncioUdpBinder(),
        control_connector=WebsocketsControlConnector(),
        playback_sink=PortAudioPlaybackSink(device=config.playback_device),
    )
    asyncio.run(runtime.run())
