"""模块契约说明.

职责: 提供 sound.rtp_playback
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass, replace
from enum import Enum
from typing import Final, NewType, Protocol

StreamId = NewType("StreamId", str)

RtpTimestamp = NewType("RtpTimestamp", int)

PlaybackPositionSamples = NewType("PlaybackPositionSamples", int)


_RTP_HEADER_BYTES: Final = 12

_RTP_VERSION: Final = 2

_L16_PAYLOAD_TYPE: Final = 96

_L16_FRAME_BYTES: Final = 640


class StreamStatus(Enum):
    """类契约说明.

    职责: 定义 StreamStatus 的状态、行为和对外协作边界。
    契约: 字段、不变式和资源归属由类体声明与类型标注共同约束。
    """

    ACTIVE = "active"

    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RtpPlaybackState:
    """类契约说明.

    职责: 保存 RtpPlaybackState
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream_id、rtp_timestamp、play
    back_position_samples。
    """

    stream_id: StreamId

    rtp_timestamp: RtpTimestamp

    playback_position_samples: PlaybackPositionSamples


@dataclass(frozen=True, slots=True)
class L16PlaybackFrame:
    """类契约说明.

    职责: 保存 L16PlaybackFrame
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream_id、sample_rate、channe
    ls、payload。
    """

    stream_id: StreamId

    sample_rate: int

    channels: int

    payload: bytes


class L16PlaybackSink(Protocol):
    """类契约说明.

    职责: 声明 L16PlaybackSink
    协议接口,约束实现方必须提供的行为。
    契约: 方法: write、close_stream、close。
    """

    def write(self, frame: L16PlaybackFrame) -> None:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 frame:
        L16PlaybackFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def close_stream(self, stream_id: str) -> None:
        """函数契约说明.

        功能: 执行 close_stream
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 stream_id: str。
        必填。
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


@dataclass(frozen=True, slots=True)
class _AnnouncedStream:
    """类契约说明.

    职责: 保存 _AnnouncedStream
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: sample_rate、channels、expecte
    d_ssrc、status、playback_position_samp
    les。
    """

    sample_rate: int

    channels: int

    expected_ssrc: int | None

    status: StreamStatus

    playback_position_samples: PlaybackPositionSamples


@dataclass(frozen=True, slots=True)
class _L16RtpPacket:
    """类契约说明.

    职责: 保存 _L16RtpPacket
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: timestamp、ssrc、l16_sample_co
    unt、payload。
    """

    timestamp: RtpTimestamp

    ssrc: int

    l16_sample_count: int

    payload: bytes


class RtpPlaybackReceiver:
    """类契约说明.

    职责: 定义 RtpPlaybackReceiver
    的状态、行为和对外协作边界。
    契约: 方法: __init__、announce_stream、can
    cel_stream、flush_stream、receive_pack
    et、close。
    """

    def __init__(self, *, playback_sink: L16PlaybackSink | None = None) -> None:
        """函数契约说明.

        功能: 初始化 RtpPlaybackReceiver
        的字段并建立实例不变式。
        参数: self 表示当前实例。 playback_sink:
        L16PlaybackSink | None。 可省略。
        契约: 同步调用。 返回 `None`。
        """

        self._streams: dict[StreamId, _AnnouncedStream] = {}

        self._rejected_ssrcs: set[int] = set()

        self._playback_sink: L16PlaybackSink | None = playback_sink

        self.playback_states: list[RtpPlaybackState] = []

    def announce_stream(
        self,
        *,
        stream_id: str,
        sample_rate: int,
        channels: int,
        expected_ssrc: int | None = None,
    ) -> None:
        """函数契约说明.

        功能: 执行 announce_stream 的同步逻辑,并协调
        StreamId, get, _AnnouncedStream,
        close_stream。
        参数: self 表示当前实例。 stream_id: str。
        必填。 sample_rate: int。 必填。
        channels: int。 必填。
        expected_ssrc: int | None。 可省略。
        契约: 同步调用。 返回 `None`。
        """

        if (
            stream_id == ""
            or sample_rate <= 0
            or channels <= 0
            or (expected_ssrc is not None and not 0 < expected_ssrc <= 0xFFFF_FFFF)
        ):
            return

        resolved_stream_id = StreamId(stream_id)

        existing_stream = self._streams.get(resolved_stream_id)

        if existing_stream is not None and self._playback_sink is not None:
            self._playback_sink.close_stream(stream_id)

        self._streams[resolved_stream_id] = _AnnouncedStream(
            sample_rate=sample_rate,
            channels=channels,
            expected_ssrc=expected_ssrc,
            status=StreamStatus.ACTIVE,
            playback_position_samples=PlaybackPositionSamples(0),
        )

    def cancel_stream(self, stream_id: str) -> None:
        """函数契约说明.

        功能: 执行 cancel_stream 的同步逻辑,并协调
        StreamId, get, replace,
        close_stream。
        参数: self 表示当前实例。 stream_id: str。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        resolved_stream_id = StreamId(stream_id)

        stream = self._streams.get(resolved_stream_id)

        if stream is None:
            return

        self._streams[resolved_stream_id] = replace(
            stream, status=StreamStatus.CANCELLED
        )

        if self._playback_sink is not None:
            self._playback_sink.close_stream(stream_id)

    def flush_stream(self, stream_id: str, target_generated_ssrc: int) -> bool:
        """函数契约说明.

        功能: 执行 flush_stream 的同步逻辑,并协调
        get, add, cancel_stream,
        StreamId。
        参数: self 表示当前实例。 stream_id: str。
        必填。 target_generated_ssrc: int。
        必填。
        契约: 同步调用。 返回 `bool`。
        """

        stream = self._streams.get(StreamId(stream_id))

        if stream is None or stream.expected_ssrc != target_generated_ssrc:
            return False

        self._rejected_ssrcs.add(target_generated_ssrc)

        self.cancel_stream(stream_id)

        return True

    def receive_packet(self, packet: bytes, *, stream_id: str | None = None) -> None:
        """函数契约说明.

        功能: 执行 receive_packet 的同步逻辑,并协调
        _parse_l16_rtp_packet,
        _resolve_stream_id, get,
        replace。
        参数: self 表示当前实例。 packet: bytes。
        必填。 stream_id: str | None。 可省略。
        契约: 同步调用。 返回 `None`。
        """

        parsed_packet = _parse_l16_rtp_packet(packet)

        if parsed_packet is None:
            return

        if parsed_packet.ssrc in self._rejected_ssrcs:
            return

        resolved_stream_id = self._resolve_stream_id(stream_id)

        if resolved_stream_id is None:
            return

        stream = self._streams.get(resolved_stream_id)

        if stream is None:
            return

        if (
            stream.expected_ssrc is not None
            and parsed_packet.ssrc != stream.expected_ssrc
        ):
            return

        if parsed_packet.l16_sample_count % stream.channels != 0:
            return

        match stream.status:
            case StreamStatus.ACTIVE:
                playback_position = PlaybackPositionSamples(
                    int(stream.playback_position_samples)
                    + parsed_packet.l16_sample_count // stream.channels
                )

            case StreamStatus.CANCELLED:
                return


        if self._playback_sink is not None:
            self._playback_sink.write(
                L16PlaybackFrame(
                    stream_id=resolved_stream_id,
                    sample_rate=stream.sample_rate,
                    channels=stream.channels,
                    payload=parsed_packet.payload,
                )
            )

        self._streams[resolved_stream_id] = replace(
            stream,
            playback_position_samples=playback_position,
        )

        self.playback_states.append(
            RtpPlaybackState(
                stream_id=resolved_stream_id,
                rtp_timestamp=parsed_packet.timestamp,
                playback_position_samples=playback_position,
            )
        )

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并协调 close。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        if self._playback_sink is not None:
            self._playback_sink.close()

    def _resolve_stream_id(self, stream_id: str | None) -> StreamId | None:
        """函数契约说明.

        功能: 执行 _resolve_stream_id
        的同步逻辑,并协调 StreamId, len, items。
        参数: self 表示当前实例。 stream_id: str
        | None。 必填。
        契约: 同步调用。 返回 `StreamId | None`。
        """

        if stream_id is not None:
            return StreamId(stream_id)

        active_stream_ids = [
            candidate_stream_id
            for candidate_stream_id, stream in self._streams.items()
            if stream.status is StreamStatus.ACTIVE
        ]

        if len(active_stream_ids) != 1:
            return None

        return active_stream_ids[0]


def _parse_l16_rtp_packet(packet: bytes) -> _L16RtpPacket | None:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: packet: bytes。 必填。
    契约: 同步调用。 返回 `_L16RtpPacket | None`。
    """

    if len(packet) < _RTP_HEADER_BYTES:
        return None

    first_byte = packet[0]

    second_byte = packet[1]

    version = first_byte >> 6

    has_padding = bool(first_byte & 0b0010_0000)

    has_extension = bool(first_byte & 0b0001_0000)

    csrc_count = first_byte & 0b0000_1111

    payload_type = second_byte & 0b0111_1111

    ssrc = int.from_bytes(packet[8:12], byteorder="big")

    payload = packet[_RTP_HEADER_BYTES:]

    if (
        version != _RTP_VERSION
        or has_padding
        or has_extension
        or csrc_count != 0
        or payload_type != _L16_PAYLOAD_TYPE
        or ssrc == 0
        or len(payload) != _L16_FRAME_BYTES
    ):
        return None

    return _L16RtpPacket(
        timestamp=RtpTimestamp(int.from_bytes(packet[4:8], byteorder="big")),
        ssrc=ssrc,
        l16_sample_count=len(payload) // 2,
        payload=payload,
    )
