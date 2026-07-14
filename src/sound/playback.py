from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal, NewType, Protocol, TypeAlias

SegmentId = NewType("SegmentId", str)
PlaybackTimestampMs = NewType("PlaybackTimestampMs", int)

JsonValue: TypeAlias = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject: TypeAlias = Mapping[str, JsonValue]


@dataclass(frozen=True, slots=True)
class ProtocolError(ValueError):
    field_name: str
    reason: str

    def __str__(self) -> str:
        return f"{self.field_name}: {self.reason}"


@dataclass(frozen=True, slots=True)
class AudioMetadata:
    sample_rate: int
    channels: int
    codec: str
    duration_ms: int
    byte_length: int


@dataclass(frozen=True, slots=True)
class PlaybackCommand:
    command_id: str
    segment_id: SegmentId
    uri: str
    audio: AudioMetadata


@dataclass(frozen=True, slots=True)
class PlaybackCancelCommand:
    segment_id: SegmentId
    reason: str


@dataclass(frozen=True, slots=True)
class SoundEvent:
    event_type: Literal["sound.queued", "sound.started", "sound.progress", "sound.done", "sound.cancelled"]
    command_id: str
    segment_id: SegmentId
    playback_timestamp_ms: PlaybackTimestampMs
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ActivePlayback:
    command: PlaybackCommand
    started_at_ms: PlaybackTimestampMs


class PlaybackClock(Protocol):
    @property
    def now_ms(self) -> PlaybackTimestampMs: ...


class SoundEventSink(Protocol):
    def receive_sound_event(self, event: SoundEvent) -> None: ...


class ManualPlaybackClock:
    def __init__(self) -> None:
        self._now_ms = PlaybackTimestampMs(0)

    @property
    def now_ms(self) -> PlaybackTimestampMs:
        return self._now_ms

    def advance(self, duration_ms: int) -> None:
        if duration_ms < 0:
            raise ProtocolError(field_name="duration_ms", reason="expected non-negative integer")
        self._now_ms = PlaybackTimestampMs(int(self._now_ms) + duration_ms)


class PlaybackService:
    def __init__(self, clock: PlaybackClock, sink: SoundEventSink) -> None:
        self._clock = clock
        self._sink = sink
        self._queue: deque[PlaybackCommand] = deque()
        self._active: ActivePlayback | None = None

    @property
    def queue_depth(self) -> int:
        active_count = 1 if self._active is not None else 0
        return active_count + len(self._queue)

    def enqueue(self, command: PlaybackCommand) -> None:
        self._queue.append(command)
        self._sink.receive_sound_event(_sound_event(command, "sound.queued", PlaybackTimestampMs(0)))
        self._start_next_when_idle()

    def tick(self) -> None:
        if self._active is None:
            self._start_next_when_idle()
            return
        active = self._active
        timestamp = PlaybackTimestampMs(int(self._clock.now_ms) - int(active.started_at_ms))
        if timestamp < active.command.audio.duration_ms:
            self._sink.receive_sound_event(_sound_event(active.command, "sound.progress", timestamp))
            return
        done_timestamp = PlaybackTimestampMs(active.command.audio.duration_ms)
        self._sink.receive_sound_event(_sound_event(active.command, "sound.done", done_timestamp))
        self._active = None
        self._start_next_when_idle()

    def cancel(self, command: PlaybackCancelCommand) -> None:
        active = self._active
        if active is None:
            return
        if active.command.segment_id != command.segment_id:
            return
        self._queue.clear()
        timestamp = PlaybackTimestampMs(int(self._clock.now_ms) - int(active.started_at_ms))
        self._active = None
        self._sink.receive_sound_event(_cancelled_event(active.command, timestamp, command.reason))

    def _start_next_when_idle(self) -> None:
        if self._active is not None or not self._queue:
            return
        command = self._queue.popleft()
        self._active = ActivePlayback(command=command, started_at_ms=self._clock.now_ms)
        self._sink.receive_sound_event(_sound_event(command, "sound.started", PlaybackTimestampMs(0)))


def parse_play_command(envelope: JsonObject) -> PlaybackCommand:
    _require_str(envelope, "source", expected="orchestrator")
    _require_str(envelope, "event_type", expected="sound.play.command")
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
    _require_str(envelope, "source", expected="orchestrator")
    _require_str(envelope, "event_type", expected="cancel")
    data = _require_object(envelope, "data")
    return PlaybackCancelCommand(
        segment_id=SegmentId(_require_str(envelope, "segment_id")),
        reason=_require_str(data, "reason"),
    )


def _sound_event(
    command: PlaybackCommand,
    event_type: Literal["sound.queued", "sound.started", "sound.progress", "sound.done"],
    timestamp: PlaybackTimestampMs,
) -> SoundEvent:
    return SoundEvent(
        event_type=event_type,
        command_id=command.command_id,
        segment_id=command.segment_id,
        playback_timestamp_ms=timestamp,
    )


def _cancelled_event(command: PlaybackCommand, timestamp: PlaybackTimestampMs, reason: str) -> SoundEvent:
    return SoundEvent(
        event_type="sound.cancelled",
        command_id=command.command_id,
        segment_id=command.segment_id,
        playback_timestamp_ms=timestamp,
        reason=reason,
    )


def _parse_audio_metadata(data: JsonObject) -> AudioMetadata:
    return AudioMetadata(
        sample_rate=_require_int(data, "sample_rate"),
        channels=_require_int(data, "channels"),
        codec=_require_str(data, "codec"),
        duration_ms=_require_int(data, "duration_ms"),
        byte_length=_require_int(data, "byte_length"),
    )


def _require_object(source: JsonObject, field_name: str) -> JsonObject:
    value = source.get(field_name)
    if isinstance(value, dict):
        return value
    raise ProtocolError(field_name=field_name, reason="expected object")


def _require_str(source: JsonObject, field_name: str, *, expected: str | None = None) -> str:
    value = source.get(field_name)
    if not isinstance(value, str) or value == "":
        raise ProtocolError(field_name=field_name, reason="expected non-empty string")
    if expected is not None and value != expected:
        raise ProtocolError(field_name=field_name, reason=f"expected {expected}")
    return value


def _require_int(source: JsonObject, field_name: str) -> int:
    value = source.get(field_name)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    raise ProtocolError(field_name=field_name, reason="expected integer")
