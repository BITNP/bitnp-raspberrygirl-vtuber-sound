import asyncio
import logging
import os
import random
import ssl
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal, Protocol, cast, override
from urllib.parse import urlparse

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosedError, ConnectionClosedOK

from sound.notification_writer import NotificationWriter, OutboundNotification
from sound.orchestrator_ws import (
    encode_envelope,
    parse_event,
)
from sound.playback_lifecycle import L16_CODEC, PlaybackLifecycle
from sound.portaudio_playback import PortAudioPlaybackSink
from sound.receive_config import SoundReceiveConfig, load_runtime_config
from sound.rtp_playback import L16PlaybackSink
from sound.tls import build_tls_context

_LOGGER = logging.getLogger(__name__)

_MINIMUM_DEPENDENCY_LOG_LEVEL = logging.INFO

_PROTOCOL_LOGGERS = ("websockets", "websockets.client", "websockets.server")
_RECONNECT_DELAYS: Final = (0.5, 1.0, 2.0, 4.0, 8.0, 10.0)


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
        connection: ControlConnection | None = None
        lifecycle: PlaybackLifecycle | None = None
        try:
            tls_context = (
                build_tls_context(self.config.tls_ca_path)
                if urlparse(self.config.orchestrator_ws_url).scheme == "wss" else None
            )
            connection = await self.control_connector.connect(
                self.config.orchestrator_ws_url,
                _authorization_headers(self.config.trusted_lan_token), tls_context,
            )
            writer = NotificationWriter(connection)
            lifecycle = PlaybackLifecycle(
                session_id=self.config.session_id, stream_id=self.config.stream_id,
                playback_sink=self.playback_sink, notifications=writer,
                jitter_target_ms=self.config.jitter_target_ms,
                jitter_max_ms=self.config.jitter_max_ms,
            )
            async with lifecycle.running():
                binding.set_packet_handler(lifecycle.receive_packet)
                await writer.send(OutboundNotification(self._register_envelope(binding.port)))
                self._registered = True
                while True:
                    try:
                        message = await connection.recv()
                    except ConnectionClosedOK:
                        break
                    if message is None:
                        break
                    await lifecycle.handle_control(parse_event(message))
                    # Yield to the packet consumer between consecutive control inputs.
                    await asyncio.sleep(0.001)
        finally:
            if lifecycle is None:
                self.playback_sink.close()
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
                "codec": L16_CODEC,
                "rtp_endpoint": {
                    "host": self.config.advertised_rtp_host,
                    "port": bound_port,
                },
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


def _configure_logging() -> None:
    configured_level = getattr(
        logging, os.environ.get("BITNP_LOG_LEVEL", "INFO").upper(), logging.INFO
    )
    logging.basicConfig(
        level=configured_level,
        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    dependency_level = max(configured_level, _MINIMUM_DEPENDENCY_LOG_LEVEL)
    for logger_name in _PROTOCOL_LOGGERS:
        logging.getLogger(logger_name).setLevel(dependency_level)


def main() -> None:
    _configure_logging()

    config = load_runtime_config()

    runtime = ReceiveRuntime(
        config=config,
        udp_binder=AsyncioUdpBinder(),
        control_connector=WebsocketsControlConnector(),
        playback_sink=PortAudioPlaybackSink(device=config.playback_device),
    )

    asyncio.run(runtime.run())
