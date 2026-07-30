"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sound.rtp_playback import RtpPlaybackReceiver
from sound.stream_flush import StreamFlush, StreamFlushAck, StreamFlushController


@dataclass
class _Receiver:
    """类契约说明.

    职责: 保存 _Receiver
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: flushed。 方法: flush_stream。
    """

    flushed: list[tuple[str, int]] = field(default_factory=list)

    def flush_stream(self, stream_id: str, target_generated_ssrc: int) -> bool:
        """函数契约说明.

        功能: 执行 flush_stream 的同步逻辑,并协调
        append。
        参数: self 表示当前实例。 stream_id: str。
        必填。 target_generated_ssrc: int。
        必填。
        契约: 同步调用。 返回 `bool`。
        """

        self.flushed.append((stream_id, target_generated_ssrc))

        return True


def _flush(
    *, session_id: str = "session-001", epoch: int = 3, request_id: str = "request-001"
) -> StreamFlush:
    """函数契约说明.

    功能: 执行 _flush 的同步逻辑,并协调 StreamFlush。
    参数: session_id: str。 可省略。 epoch:
    int。 可省略。 request_id: str。 可省略。
    契约: 同步调用。 返回 `StreamFlush`。
    """

    return StreamFlush(
        session_id=session_id,
        stream_id="stream-001",
        turn_id="turn-001",
        segment_id="segment-001",
        cancellation_epoch=epoch,
        request_id=request_id,
        target_generated_ssrc=305419896,
    )


def test_flush_clears_generated_playback_and_acknowledges_once_idempotently() -> None:
    # Given: Sound owns one stream with queued/current generated playback.

    """函数契约说明.

    功能: 验证 flush clears generated
    playback and acknowledges once
    idempotently 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    receiver = _Receiver()

    controller = StreamFlushController(session_id="session-001", receiver=receiver)

    flush = _flush()

    # When: the same canonical flush is received twice.

    first = controller.apply(flush)

    second = controller.apply(flush)

    # Then: generated playback is cleared once, its SSRC is rejected, and both replies correlate.

    assert receiver.flushed == [("stream-001", 305419896)]

    assert first == StreamFlushAck.from_flush(flush)

    assert second == first


def test_flush_rejects_stale_epoch_wrong_session_and_raw_mic_ssrc() -> None:
    # Given: Sound accepted one generated-SSRC flush at epoch three.

    """函数契约说明.

    功能: 验证 flush rejects stale epoch
    wrong session and raw mic ssrc
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    receiver = _Receiver()

    controller = StreamFlushController(session_id="session-001", receiver=receiver)

    _ = controller.apply(_flush())

    # When: stale, wrong-session, and raw-Mic SSRC flushes arrive.

    stale = controller.apply(_flush(epoch=2, request_id="request-002"))

    wrong_session = controller.apply(
        _flush(session_id="other-session", request_id="request-003")
    )

    raw_mic = controller.apply(
        _flush(request_id="request-004").with_target_generated_ssrc(0x0102_0304)
    )

    # Then: only the generated epoch is accepted; unsafe or stale requests have no acknowledgement.

    assert stale is None

    assert wrong_session is None

    assert raw_mic is None

    assert receiver.flushed == [("stream-001", 305419896)]


def test_flush_rejects_raw_mic_and_flushed_generated_rtp() -> None:
    # Given: Sound announced only generated SSRC 0x12345678 for a stream.

    """函数契约说明.

    功能: 验证 flush rejects raw mic and
    flushed generated rtp 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    receiver = RtpPlaybackReceiver()

    receiver.announce_stream(
        stream_id="stream-001",
        sample_rate=16_000,
        channels=1,
        expected_ssrc=0x1234_5678,
    )

    controller = StreamFlushController(session_id="session-001", receiver=receiver)

    # When: raw Mic media arrives and the announced generated SSRC is flushed.

    receiver.receive_packet(_rtp_packet(ssrc=0x0102_0304), stream_id="stream-001")

    acknowledgement = controller.apply(_flush())

    receiver.receive_packet(_rtp_packet(ssrc=0x1234_5678), stream_id="stream-001")

    # Then: neither raw Mic nor flushed generated media advances playback state.

    assert acknowledgement == StreamFlushAck.from_flush(_flush())

    assert receiver.playback_states == []


def test_playback_rejects_short_and_long_l16_frames() -> None:
    """函数契约说明.

    功能: 验证 playback rejects short and
    long l16 frames 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    receiver = RtpPlaybackReceiver()

    receiver.announce_stream(
        stream_id="stream-001",
        sample_rate=16_000,
        channels=1,
        expected_ssrc=0x1234_5678,
    )

    receiver.receive_packet(
        _rtp_packet(ssrc=0x1234_5678, payload=bytes(638)), stream_id="stream-001"
    )

    receiver.receive_packet(
        _rtp_packet(ssrc=0x1234_5678, payload=bytes(642)), stream_id="stream-001"
    )

    assert receiver.playback_states == []


def _rtp_packet(*, ssrc: int, payload: bytes | None = None) -> bytes:
    """函数契约说明.

    功能: 执行 _rtp_packet 的同步逻辑,并协调 bytes,
    to_bytes。
    参数: ssrc: int。 必填。 payload: bytes。
    可省略。
    契约: 同步调用。 返回 `bytes`。
    """

    resolved_payload = b"\x00\x01" + bytes(638) if payload is None else payload

    return (
        bytes([0x80, 96, 0, 1])
        + (320).to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + resolved_payload
    )
