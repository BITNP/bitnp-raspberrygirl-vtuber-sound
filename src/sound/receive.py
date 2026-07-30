"""模块契约说明.

职责: 提供 sound.receive
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

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
    """类契约说明.

    职责: 保存 _ActiveCommand
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: trace_id、session_id、seq、turn
    _id、segment_id、cancellation_epoch。
    """

    trace_id: str

    session_id: str

    seq: int

    turn_id: str | None

    segment_id: str | None

    cancellation_epoch: int | None


class UdpBinding(Protocol):
    """类契约说明.

    职责: 声明 UdpBinding 协议接口,约束实现方必须提供的行为。
    契约: 方法:
    port、set_packet_handler、close。
    """

    @property
    def port(self) -> int:
        """函数契约说明.

        功能: 执行 port 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `int`。
        """

        ...

    def set_packet_handler(self, handler: Callable[[bytes], None]) -> None:
        """函数契约说明.

        功能: 执行 set_packet_handler
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 handler:
        Callable[[bytes], None]。 必填。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        ...


class UdpBinder(Protocol):
    """类契约说明.

    职责: 声明 UdpBinder 协议接口,约束实现方必须提供的行为。
    契约: 方法: bind。
    """

    async def bind(self, host: str, port: int) -> UdpBinding:
        """函数契约说明.

        功能: 执行 bind 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。 host: str。 必填。
        port: int。 必填。
        契约: 异步调用。 返回 `UdpBinding`。
        """

        ...


class _SocketAddressTransport(Protocol):
    """类契约说明.

    职责: 声明 _SocketAddressTransport
    协议接口,约束实现方必须提供的行为。
    契约: 方法: get_extra_info。
    """

    def get_extra_info(
        self, name: Literal["sockname"], default: tuple[str, int]
    ) -> tuple[str, int]:
        """函数契约说明.

        功能: 执行 get_extra_info
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 name:
        Literal['sockname']。 必填。
        default: tuple[str, int]。 必填。
        契约: 同步调用。 返回 `tuple[str, int]`。
        """

        ...


class ControlConnection(Protocol):
    """类契约说明.

    职责: 声明 ControlConnection
    协议接口,约束实现方必须提供的行为。
    契约: 方法: send、recv、close。
    """

    async def send(self, message: str) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 message: str。
        必填。
        契约: 异步调用。 返回 `None`。
        """

        ...

    async def recv(self) -> str | None:
        """函数契约说明.

        功能: 执行 recv 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `str | None`。
        """

        ...

    async def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 异步调用。 返回 `None`。
        """

        ...


class ControlConnector(Protocol):
    """类契约说明.

    职责: 声明 ControlConnector
    协议接口,约束实现方必须提供的行为。
    契约: 方法: connect。
    """

    async def connect(self, url: str, headers: dict[str, str]) -> ControlConnection:
        """函数契约说明.

        功能: 执行 connect 的异步逻辑,并维持签名契约。
        参数: self 表示当前实例。 url: str。 必填。
        headers: dict[str, str]。 必填。
        契约: 异步调用。 返回
        `ControlConnection`。
        """

        ...


class _DatagramProtocol(asyncio.DatagramProtocol):
    """类契约说明.

    职责: 声明 _DatagramProtocol
    协议接口,约束实现方必须提供的行为。
    契约: 方法: __init__、datagram_received。
    """

    def __init__(self) -> None:
        """函数契约说明.

        功能: 初始化 _DatagramProtocol
        的字段并建立实例不变式。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.handler: Callable[[bytes], None] | None = None

    @override
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """函数契约说明.

        功能: 执行 datagram_received
        的同步逻辑,并协调 handler。
        参数: self 表示当前实例。 data: bytes。
        必填。 addr: tuple[str, int]。 必填。
        契约: 同步调用。 返回 `None`。
        """

        _ = addr

        if self.handler is not None:
            self.handler(data)


@dataclass(slots=True)
class _AsyncioUdpBinding:
    """类契约说明.

    职责: 保存 _AsyncioUdpBinding
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    transport、protocol、bound_port。 方法:
    port、set_packet_handler、close。
    """

    transport: asyncio.DatagramTransport

    protocol: _DatagramProtocol

    bound_port: int

    @property
    def port(self) -> int:
        """函数契约说明.

        功能: 执行 port 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `int`。
        """

        return self.bound_port

    def set_packet_handler(self, handler: Callable[[bytes], None]) -> None:
        """函数契约说明.

        功能: 执行 set_packet_handler
        的同步逻辑,并产出 handler。
        参数: self 表示当前实例。 handler:
        Callable[[bytes], None]。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.protocol.handler = handler

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并协调 close。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.transport.close()


class AsyncioUdpBinder:
    """类契约说明.

    职责: 定义 AsyncioUdpBinder
    的状态、行为和对外协作边界。
    契约: 方法: bind。
    """

    async def bind(self, host: str, port: int) -> UdpBinding:
        """函数契约说明.

        功能: 执行 bind 的异步逻辑,并协调
        get_running_loop,
        _AsyncioUdpBinding,
        create_datagram_endpoint,
        _bound_udp_port。
        参数: self 表示当前实例。 host: str。 必填。
        port: int。 必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `UdpBinding`。
        """

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
    """类契约说明.

    职责: 定义 WebsocketsControlConnector
    的状态、行为和对外协作边界。
    契约: 方法: connect。
    """

    async def connect(self, url: str, headers: dict[str, str]) -> ControlConnection:
        """函数契约说明.

        功能: 执行 connect 的异步逻辑,并协调
        _WebsocketsControlConnection,
        connect。
        参数: self 表示当前实例。 url: str。 必填。
        headers: dict[str, str]。 必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `ControlConnection`。
        """

        return _WebsocketsControlConnection(
            await connect(url, additional_headers=headers)
        )


@dataclass(frozen=True, slots=True)
class _WebsocketsControlConnection:
    """类契约说明.

    职责: 保存 _WebsocketsControlConnection
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: connection。 方法:
    send、recv、close。
    """

    connection: ClientConnection

    async def send(self, message: str) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 message: str。
        必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        await self.connection.send(message)

    async def recv(self) -> str | None:
        """函数契约说明.

        功能: 执行 recv 的异步逻辑,并协调 recv,
        isinstance, TypeError。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `str | None`。 可能抛出 TypeError。
        """

        message = await self.connection.recv()

        if not isinstance(message, str):
            raise TypeError("control frames must be text")

        return message

    async def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的异步逻辑,并协调 close。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        await self.connection.close()


@dataclass(slots=True)
class ReceiveRuntime:
    """类契约说明.

    职责: 保存 ReceiveRuntime
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: config、udp_binder、control_co
    nnector、playback_sink。 方法: run、_regi
    ster_envelope、_ready_envelope、_state
    _envelope、_flush_ack_envelope。
    """

    config: SoundReceiveConfig

    udp_binder: UdpBinder

    control_connector: ControlConnector

    playback_sink: L16PlaybackSink

    async def run(self) -> None:
        """函数契约说明.

        功能: 运行流程并协调其依赖步骤。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

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
            """函数契约说明.

            功能: 执行 receive_packet
            的同步逻辑,并协调 len,
            receive_packet, enqueue,
            OutboundNotification。
            参数: packet: bytes。 必填。
            契约: 同步调用。 返回 `None`。
            """

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
        """函数契约说明.

        功能: 执行 _register_envelope
        的同步逻辑,并协调 encode_envelope。
        参数: self 表示当前实例。 bound_port:
        int。 必填。
        契约: 同步调用。 返回 `str`。
        """

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
        """函数契约说明.

        功能: 执行 _ready_envelope 的同步逻辑,并协调
        encode_envelope, required_str,
        required_int。
        参数: self 表示当前实例。 event:
        Mapping[str, JsonValue]。 必填。
        契约: 同步调用。 返回 `str`。
        """

        return encode_envelope(
            event_type="media.rtp.sink.ready",
            trace_id=required_str(event, "trace_id"),
            session_id=required_str(event, "session_id"),
            seq=required_int(event, "seq"),
            data={"stream_id": self.config.stream_id},
        )

    def _state_envelope(self, command: _ActiveCommand, state: str) -> str:
        """函数契约说明.

        功能: 执行 _state_envelope 的同步逻辑,并协调
        encode_envelope。
        参数: self 表示当前实例。 command:
        _ActiveCommand。 必填。 state: str。
        必填。
        契约: 同步调用。 返回 `str`。
        """

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
        """函数契约说明.

        功能: 执行 _flush_ack_envelope
        的同步逻辑,并协调 encode_envelope,
        required_str, required_int。
        参数: self 表示当前实例。 event:
        Mapping[str, JsonValue]。 必填。
        acknowledgement: StreamFlushAck。
        必填。
        契约: 同步调用。 返回 `str`。
        """

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
    """函数契约说明.

    功能: 执行 _authorization_headers
    的同步逻辑,并维持签名契约。
    参数: token: str | None。 必填。
    契约: 同步调用。 返回 `dict[str, str]`。
    """

    if token is None:
        return {}

    return {"authorization": f"Bearer {token}"}


def _bound_udp_port(transport: _SocketAddressTransport) -> int:
    """函数契约说明.

    功能: 执行 _bound_udp_port 的同步逻辑,并协调
    get_extra_info, RuntimeError。
    参数: transport:
    _SocketAddressTransport。 必填。
    契约: 同步调用。 返回 `int`。 可能抛出
    RuntimeError。
    """

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
    """函数契约说明.

    功能: 执行 _announce_command 的同步逻辑,并协调
    required_mapping, required_str,
    announce_stream, required_int。
    参数: receiver: RtpPlaybackReceiver。
    必填。 event: Mapping[str, JsonValue]。
    必填。 expected_stream_id: str。 必填。
    expected_port: int。 必填。
    契约: 同步调用。 返回 `str | None`。
    """

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
    """函数契约说明.

    功能: 执行 _flush 的同步逻辑,并协调
    required_mapping, StreamFlush,
    required_str, required_int。
    参数: event: Mapping[str, JsonValue]。
    必填。
    契约: 同步调用。 返回 `StreamFlush`。
    """

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
    """函数契约说明.

    功能: 执行 _active_command 的同步逻辑,并协调
    required_mapping, _ActiveCommand,
    required_str, required_int。
    参数: event: Mapping[str, JsonValue]。
    必填。
    契约: 同步调用。 返回 `_ActiveCommand`。
    """

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
    """函数契约说明.

    功能: 执行 _optional_int 的同步逻辑,并协调
    required_int。
    参数: source: Mapping[str, JsonValue]。
    必填。 field: str。 必填。
    契约: 同步调用。 返回 `int | None`。
    """

    if field not in source:
        return None

    return required_int(source, field)


def main() -> None:
    """函数契约说明.

    功能: 执行命令行或服务入口流程并返回进程级结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    config = load_runtime_config()

    runtime = ReceiveRuntime(
        config=config,
        udp_binder=AsyncioUdpBinder(),
        control_connector=WebsocketsControlConnector(),
        playback_sink=PortAudioPlaybackSink(device=config.playback_device),
    )

    asyncio.run(runtime.run())
