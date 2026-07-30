"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from sound.playback import (
    AudioMetadata,
    JsonObject,
    ManualPlaybackClock,
    PlaybackService,
    SegmentId,
    SoundEvent,
    parse_cancel_command,
    parse_play_command,
)


class RecordingSink:
    """类契约说明.

    职责: 定义 RecordingSink 的状态、行为和对外协作边界。
    契约: 方法:
    __init__、receive_sound_event。
    """

    def __init__(self) -> None:
        """函数契约说明.

        功能: 初始化 RecordingSink
        的字段并建立实例不变式。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.events: list[SoundEvent] = []

    def receive_sound_event(self, event: SoundEvent) -> None:
        """函数契约说明.

        功能: 执行 receive_sound_event
        的同步逻辑,并协调 append。
        参数: self 表示当前实例。 event:
        SoundEvent。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.events.append(event)


def play_envelope(segment_id: str, command_id: str, duration_ms: int) -> JsonObject:
    """函数契约说明.

    功能: 执行 play_envelope 的同步逻辑,并维持签名契约。
    参数: segment_id: str。 必填。 command_id:
    str。 必填。 duration_ms: int。 必填。
    契约: 同步调用。 返回 `JsonObject`。
    """

    return {
        "schema_version": "1.0.0",
        "event_type": "sound.play.command",
        "event_id": "evt-play-001",
        "source": "orchestrator",
        "time": "2026-07-08T00:00:13Z",
        "trace_id": "trace-001",
        "session_id": "session-001",
        "turn_id": "turn-001",
        "segment_id": segment_id,
        "seq": 14,
        "data": {
            "command_id": command_id,
            "uri": f"segment://{segment_id}",
            "audio": {
                "sample_rate": 24000,
                "channels": 1,
                "codec": "pcm_s16le",
                "duration_ms": duration_ms,
                "byte_length": duration_ms * 48,
            },
        },
    }


def cancel_envelope(segment_id: str) -> JsonObject:
    """函数契约说明.

    功能: 执行 cancel_envelope
    的同步逻辑,并维持签名契约。
    参数: segment_id: str。 必填。
    契约: 同步调用。 返回 `JsonObject`。
    """

    return {
        "schema_version": "1.0.0",
        "event_type": "cancel",
        "event_id": "evt-cancel-001",
        "source": "orchestrator",
        "time": "2026-07-08T00:00:20Z",
        "trace_id": "trace-001",
        "session_id": "session-001",
        "turn_id": "turn-001",
        "segment_id": segment_id,
        "seq": 21,
        "data": {"reason": "newer_segment", "cancelled_event_ids": ["evt-play-001"]},
    }


def test_playback_service_emits_monotonic_queue_start_progress_done_events() -> None:
    # Given: a deterministic sound service receiving an Orchestrator play command.

    """函数契约说明.

    功能: 验证 playback service emits
    monotonic queue start progress done
    events 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    clock = ManualPlaybackClock()

    sink = RecordingSink()

    service = PlaybackService(clock=clock, sink=sink)

    command = parse_play_command(play_envelope("seg-sound-001", "sound-001", 120))

    # When: playback is queued and the fake clock advances past completion.

    service.enqueue(command)

    clock.advance(40)

    service.tick()

    clock.advance(80)

    service.tick()

    # Then: the Orchestrator sink observes the full playback lifecycle with monotonic timestamps.

    assert [event.event_type for event in sink.events] == [
        "sound.queued",
        "sound.started",
        "sound.progress",
        "sound.done",
    ]

    assert [event.playback_timestamp_ms for event in sink.events] == [0, 0, 40, 120]

    assert [event.segment_id for event in sink.events] == [
        SegmentId("seg-sound-001")
    ] * 4

    assert [event.command_id for event in sink.events] == ["sound-001"] * 4

    assert service.queue_depth == 0


def test_playback_service_cancel_mid_playback_clears_queue_and_emits_cancelled() -> (
    None
):
    # Given: one active segment and one queued segment.

    """函数契约说明.

    功能: 验证 playback service cancel mid
    playback clears queue and emits
    cancelled 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    clock = ManualPlaybackClock()

    sink = RecordingSink()

    service = PlaybackService(clock=clock, sink=sink)

    service.enqueue(
        parse_play_command(play_envelope("seg-sound-001", "sound-001", 200))
    )

    service.enqueue(
        parse_play_command(play_envelope("seg-sound-002", "sound-002", 200))
    )

    clock.advance(75)

    service.tick()

    # When: Orchestrator cancels the active segment mid-playback.

    cancel = parse_cancel_command(cancel_envelope("seg-sound-001"))

    service.cancel(cancel)

    # Then: the queue is cleared and the active segment reports cancellation at the current playback clock.

    assert service.queue_depth == 0

    assert [event.event_type for event in sink.events] == [
        "sound.queued",
        "sound.started",
        "sound.queued",
        "sound.progress",
        "sound.cancelled",
    ]

    assert sink.events[-1].segment_id == SegmentId("seg-sound-001")

    assert sink.events[-1].playback_timestamp_ms == 75

    assert sink.events[-1].reason == "newer_segment"


def test_parse_play_command_accepts_orchestrator_audio_shape() -> None:
    # Given: the Orchestrator play command shape with embedded deterministic audio metadata.

    """函数契约说明.

    功能: 验证 parse play command accepts
    orchestrator audio shape
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    envelope = play_envelope("seg-sound-003", "sound-003", 250)

    # When: the sound boundary parses the command.

    command = parse_play_command(envelope)

    # Then: sound owns a typed playback command without importing upstream module runtime.

    assert command.segment_id == SegmentId("seg-sound-003")

    assert command.command_id == "sound-003"

    assert command.audio == AudioMetadata(
        sample_rate=24000,
        channels=1,
        codec="pcm_s16le",
        duration_ms=250,
        byte_length=12000,
    )


def test_parse_cancel_command_accepts_orchestrator_cancel_shape() -> None:
    # Given: an Orchestrator cancel envelope naming a segment.

    """函数契约说明.

    功能: 验证 parse cancel command accepts
    orchestrator cancel shape
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    envelope = cancel_envelope("seg-sound-004")

    # When: the sound boundary parses the cancellation command.

    command = parse_cancel_command(envelope)

    # Then: the service receives typed cancel intent and reason only.

    assert command.segment_id == SegmentId("seg-sound-004")

    assert command.reason == "newer_segment"
