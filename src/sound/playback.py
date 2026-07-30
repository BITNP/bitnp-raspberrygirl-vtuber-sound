"""模块契约说明.

职责: 提供 sound.playback
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NewType, Protocol, override

from sound.rtp_playback import RtpPlaybackReceiver, RtpPlaybackState

__all__ = ["RtpPlaybackReceiver", "RtpPlaybackState"]


SegmentId = NewType("SegmentId", str)

PlaybackTimestampMs = NewType("PlaybackTimestampMs", int)


type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)

type JsonObject = Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ProtocolError(ValueError):
    """类契约说明.

    职责: 保存 ProtocolError
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: field_name、reason。 方法:
    __str__。
    """

    field_name: str

    reason: str

    @override
    def __str__(self) -> str:
        """函数契约说明.

        功能: 生成面向日志、错误或调试输出的稳定文本表示。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return f"{self.field_name}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    """类契约说明.

    职责: 保存 AudioMetadata
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: sample_rate、channels、codec、d
    uration_ms、byte_length。
    """

    sample_rate: int

    channels: int

    codec: str

    duration_ms: int

    byte_length: int


@dataclass(frozen=True, slots=True)
class PlaybackCommand:
    """类契约说明.

    职责: 保存 PlaybackCommand
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    command_id、segment_id、uri、audio。
    """

    command_id: str

    segment_id: SegmentId

    uri: str

    audio: AudioMetadata


@dataclass(frozen=True, slots=True)
class PlaybackCancelCommand:
    """类契约说明.

    职责: 保存 PlaybackCancelCommand
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: segment_id、reason。
    """

    segment_id: SegmentId

    reason: str


@dataclass(frozen=True, slots=True)
class SoundEvent:
    """类契约说明.

    职责: 保存 SoundEvent
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: event_type、command_id、segmen
    t_id、playback_timestamp_ms、reason。
    """

    event_type: Literal[
        "sound.queued",
        "sound.started",
        "sound.progress",
        "sound.done",
        "sound.cancelled",
    ]

    command_id: str

    segment_id: SegmentId

    playback_timestamp_ms: PlaybackTimestampMs

    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ActivePlayback:
    """类契约说明.

    职责: 保存 ActivePlayback
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: command、started_at_ms。
    """

    command: PlaybackCommand

    started_at_ms: PlaybackTimestampMs


class PlaybackClock(Protocol):
    """类契约说明.

    职责: 声明 PlaybackClock
    协议接口,约束实现方必须提供的行为。
    契约: 方法: now_ms。
    """

    @property
    def now_ms(self) -> PlaybackTimestampMs:
        """函数契约说明.

        功能: 执行 now_ms 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回
        `PlaybackTimestampMs`。
        """

        ...


class SoundEventSink(Protocol):
    """类契约说明.

    职责: 声明 SoundEventSink
    协议接口,约束实现方必须提供的行为。
    契约: 方法: receive_sound_event。
    """

    def receive_sound_event(self, event: SoundEvent) -> None:
        """函数契约说明.

        功能: 执行 receive_sound_event
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 event:
        SoundEvent。 必填。
        契约: 同步调用。 返回 `None`。
        """

        ...


class ManualPlaybackClock:
    """类契约说明.

    职责: 定义 ManualPlaybackClock
    的状态、行为和对外协作边界。
    契约: 方法: __init__、now_ms、advance。
    """

    def __init__(self) -> None:
        """函数契约说明.

        功能: 初始化 ManualPlaybackClock
        的字段并建立实例不变式。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self._now_ms: PlaybackTimestampMs = PlaybackTimestampMs(0)

    @property
    def now_ms(self) -> PlaybackTimestampMs:
        """函数契约说明.

        功能: 执行 now_ms 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回
        `PlaybackTimestampMs`。
        """

        return self._now_ms

    def advance(self, duration_ms: int) -> None:
        """函数契约说明.

        功能: 执行 advance 的同步逻辑,并协调
        PlaybackTimestampMs,
        ProtocolError, int。
        参数: self 表示当前实例。 duration_ms:
        int。 必填。
        契约: 同步调用。 返回 `None`。 可能抛出
        ProtocolError。
        """

        if duration_ms < 0:
            raise ProtocolError(
                field_name="duration_ms", reason="expected non-negative integer"
            )

        self._now_ms = PlaybackTimestampMs(int(self._now_ms) + duration_ms)


class PlaybackService:
    """类契约说明.

    职责: 定义 PlaybackService
    的状态、行为和对外协作边界。
    契约: 方法: __init__、queue_depth、enqueue
    、tick、cancel、_start_next_when_idle。
    """

    def __init__(self, clock: PlaybackClock, sink: SoundEventSink) -> None:
        """函数契约说明.

        功能: 初始化 PlaybackService
        的字段并建立实例不变式。
        参数: self 表示当前实例。 clock:
        PlaybackClock。 必填。 sink:
        SoundEventSink。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._clock: PlaybackClock = clock

        self._sink: SoundEventSink = sink

        self._queue: deque[PlaybackCommand] = deque()

        self._active: ActivePlayback | None = None

    @property
    def queue_depth(self) -> int:
        """函数契约说明.

        功能: 执行 queue_depth 的同步逻辑,并协调
        len。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `int`。
        """

        active_count = 1 if self._active is not None else 0

        return active_count + len(self._queue)

    def enqueue(self, command: PlaybackCommand) -> None:
        """函数契约说明.

        功能: 执行 enqueue 的同步逻辑,并协调 append,
        receive_sound_event,
        _start_next_when_idle,
        _sound_event。
        参数: self 表示当前实例。 command:
        PlaybackCommand。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._queue.append(command)

        self._sink.receive_sound_event(
            _sound_event(command, "sound.queued", PlaybackTimestampMs(0))
        )

        self._start_next_when_idle()

    def tick(self) -> None:
        """函数契约说明.

        功能: 执行 tick 的同步逻辑,并协调
        PlaybackTimestampMs,
        receive_sound_event,
        _start_next_when_idle,
        _sound_event。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        if self._active is None:
            self._start_next_when_idle()

            return

        active = self._active

        timestamp = PlaybackTimestampMs(
            int(self._clock.now_ms) - int(active.started_at_ms)
        )

        if timestamp < active.command.audio.duration_ms:
            self._sink.receive_sound_event(
                _sound_event(active.command, "sound.progress", timestamp)
            )

            return

        done_timestamp = PlaybackTimestampMs(active.command.audio.duration_ms)

        self._sink.receive_sound_event(
            _sound_event(active.command, "sound.done", done_timestamp)
        )

        self._active = None

        self._start_next_when_idle()

    def cancel(self, command: PlaybackCancelCommand) -> None:
        """函数契约说明.

        功能: 执行 cancel 的同步逻辑,并协调 clear,
        PlaybackTimestampMs,
        receive_sound_event,
        _cancelled_event。
        参数: self 表示当前实例。 command:
        PlaybackCancelCommand。 必填。
        契约: 同步调用。 返回 `None`。
        """

        active = self._active

        if active is None:
            return

        if active.command.segment_id != command.segment_id:
            return

        self._queue.clear()

        timestamp = PlaybackTimestampMs(
            int(self._clock.now_ms) - int(active.started_at_ms)
        )

        self._active = None

        self._sink.receive_sound_event(
            _cancelled_event(active.command, timestamp, command.reason)
        )

    def _start_next_when_idle(self) -> None:
        """函数契约说明.

        功能: 执行 _start_next_when_idle
        的同步逻辑,并协调 popleft,
        ActivePlayback,
        receive_sound_event,
        _sound_event。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        if self._active is not None or not self._queue:
            return

        command = self._queue.popleft()

        self._active = ActivePlayback(command=command, started_at_ms=self._clock.now_ms)

        self._sink.receive_sound_event(
            _sound_event(command, "sound.started", PlaybackTimestampMs(0))
        )


def parse_play_command(envelope: JsonObject) -> PlaybackCommand:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: envelope: JsonObject。 必填。
    契约: 同步调用。 返回 `PlaybackCommand`。
    """

    _ = _require_str(envelope, "source", expected="orchestrator")

    _ = _require_str(envelope, "event_type", expected="sound.play.command")

    segment_id = SegmentId(_require_str(envelope, "segment_id"))

    data = _require_object(envelope, "data")

    audio = _parse_audio_metadata(_require_object(data, "audio"))

    return PlaybackCommand(
        command_id=_require_str(data, "command_id"),
        segment_id=segment_id,
        uri=_require_str(data, "uri"),
        audio=audio,
    )


def parse_cancel_command(envelope: JsonObject) -> PlaybackCancelCommand:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: envelope: JsonObject。 必填。
    契约: 同步调用。 返回
    `PlaybackCancelCommand`。
    """

    _ = _require_str(envelope, "source", expected="orchestrator")

    _ = _require_str(envelope, "event_type", expected="cancel")

    data = _require_object(envelope, "data")

    return PlaybackCancelCommand(
        segment_id=SegmentId(_require_str(envelope, "segment_id")),
        reason=_require_str(data, "reason"),
    )


def _sound_event(
    command: PlaybackCommand,
    event_type: Literal[
        "sound.queued", "sound.started", "sound.progress", "sound.done"
    ],
    timestamp: PlaybackTimestampMs,
) -> SoundEvent:
    """函数契约说明.

    功能: 执行 _sound_event 的同步逻辑,并协调
    SoundEvent。
    参数: command: PlaybackCommand。 必填。
    event_type: Literal['sound.queued',
    'sound.started', 'sound.progress',
    'sound.done']。 必填。 timestamp:
    PlaybackTimestampMs。 必填。
    契约: 同步调用。 返回 `SoundEvent`。
    """

    return SoundEvent(
        event_type=event_type,
        command_id=command.command_id,
        segment_id=command.segment_id,
        playback_timestamp_ms=timestamp,
    )


def _cancelled_event(
    command: PlaybackCommand, timestamp: PlaybackTimestampMs, reason: str
) -> SoundEvent:
    """函数契约说明.

    功能: 执行 _cancelled_event 的同步逻辑,并协调
    SoundEvent。
    参数: command: PlaybackCommand。 必填。
    timestamp: PlaybackTimestampMs。 必填。
    reason: str。 必填。
    契约: 同步调用。 返回 `SoundEvent`。
    """

    return SoundEvent(
        event_type="sound.cancelled",
        command_id=command.command_id,
        segment_id=command.segment_id,
        playback_timestamp_ms=timestamp,
        reason=reason,
    )


def _parse_audio_metadata(data: JsonObject) -> AudioMetadata:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: data: JsonObject。 必填。
    契约: 同步调用。 返回 `AudioMetadata`。
    """

    return AudioMetadata(
        sample_rate=_require_int(data, "sample_rate"),
        channels=_require_int(data, "channels"),
        codec=_require_str(data, "codec"),
        duration_ms=_require_int(data, "duration_ms"),
        byte_length=_require_int(data, "byte_length"),
    )


def _require_object(source: JsonObject, field_name: str) -> JsonObject:
    """函数契约说明.

    功能: 执行 _require_object 的同步逻辑,并协调
    get, isinstance, ProtocolError。
    参数: source: JsonObject。 必填。
    field_name: str。 必填。
    契约: 同步调用。 返回 `JsonObject`。 可能抛出
    ProtocolError。
    """

    value = source.get(field_name)

    if isinstance(value, dict):
        return value

    raise ProtocolError(field_name=field_name, reason="expected object")


def _require_str(
    source: JsonObject, field_name: str, *, expected: str | None = None
) -> str:
    """函数契约说明.

    功能: 执行 _require_str 的同步逻辑,并协调 get,
    ProtocolError, isinstance。
    参数: source: JsonObject。 必填。
    field_name: str。 必填。 expected: str |
    None。 可省略。
    契约: 同步调用。 返回 `str`。 可能抛出
    ProtocolError。
    """

    value = source.get(field_name)

    if not isinstance(value, str) or value == "":
        raise ProtocolError(field_name=field_name, reason="expected non-empty string")

    if expected is not None and value != expected:
        raise ProtocolError(field_name=field_name, reason=f"expected {expected}")

    return value


def _require_int(source: JsonObject, field_name: str) -> int:
    """函数契约说明.

    功能: 执行 _require_int 的同步逻辑,并协调 get,
    ProtocolError, isinstance。
    参数: source: JsonObject。 必填。
    field_name: str。 必填。
    契约: 同步调用。 返回 `int`。 可能抛出
    ProtocolError。
    """

    value = source.get(field_name)

    if isinstance(value, int) and not isinstance(value, bool):
        return value

    raise ProtocolError(field_name=field_name, reason="expected integer")
