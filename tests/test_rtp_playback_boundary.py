"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass
from typing import Protocol

from sound import playback
from sound.rtp_playback import (
    L16PlaybackFrame,
    RtpPlaybackReceiver as ConcreteRtpPlaybackReceiver,
    StreamId,
)


class PlaybackState(Protocol):
    """类契约说明.

    职责: 声明 PlaybackState
    协议接口,约束实现方必须提供的行为。
    契约: 字段: stream_id、rtp_timestamp、play
    back_position_samples。
    """

    stream_id: str

    rtp_timestamp: int

    playback_position_samples: int


class RtpPlaybackReceiver(Protocol):
    """类契约说明.

    职责: 声明 RtpPlaybackReceiver
    协议接口,约束实现方必须提供的行为。
    契约: 字段: playback_states。 方法: announc
    e_stream、receive_packet、cancel_strea
    m、close。
    """

    playback_states: list[PlaybackState]

    def announce_stream(
        self, *, stream_id: str, sample_rate: int, channels: int
    ) -> None:
        """函数契约说明.

        功能: 执行 announce_stream
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 stream_id: str。
        必填。 sample_rate: int。 必填。
        channels: int。 必填。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def receive_packet(self, packet: bytes, *, stream_id: str | None = None) -> None:
        """函数契约说明.

        功能: 执行 receive_packet
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 packet: bytes。
        必填。 stream_id: str | None。 可省略。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def cancel_stream(self, stream_id: str) -> None:
        """函数契约说明.

        功能: 执行 cancel_stream
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


@dataclass
class _RecordingPlaybackSink:
    """类契约说明.

    职责: 保存 _RecordingPlaybackSink
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    frames、closed_streams、closed。 方法:
    write、close_stream、close。
    """

    frames: list[L16PlaybackFrame]

    closed_streams: list[str]

    closed: bool = False

    def write(self, frame: L16PlaybackFrame) -> None:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并协调 append。
        参数: self 表示当前实例。 frame:
        L16PlaybackFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self.frames.append(frame)

    def close_stream(self, stream_id: str) -> None:
        """函数契约说明.

        功能: 执行 close_stream 的同步逻辑,并协调
        append。
        参数: self 表示当前实例。 stream_id: str。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        self.closed_streams.append(stream_id)

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并产出 closed。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.closed = True


class _FailingPlaybackSink:
    """类契约说明.

    职责: 定义 _FailingPlaybackSink
    的状态、行为和对外协作边界。
    契约: 方法: write、close_stream、close。
    """

    def write(self, frame: L16PlaybackFrame) -> None:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 frame:
        L16PlaybackFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

        _ = frame

        raise _SinkWriteFailure

    def close_stream(self, stream_id: str) -> None:
        """函数契约说明.

        功能: 执行 close_stream
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 stream_id: str。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        _ = stream_id

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        return


class _SinkWriteFailure(RuntimeError):
    """类契约说明.

    职责: 定义 _SinkWriteFailure
    的状态、行为和对外协作边界。
    契约: 字段、不变式和资源归属由类体声明与类型标注共同约束。
    """



def _receiver(
    playback_sink: _RecordingPlaybackSink | None = None,
) -> ConcreteRtpPlaybackReceiver:
    """函数契约说明.

    功能: 执行 _receiver 的同步逻辑,并协调 getattr,
    receiver_type。
    参数: playback_sink:
    _RecordingPlaybackSink | None。 可省略。
    契约: 同步调用。 返回 `RtpPlaybackReceiver`。
    """

    assert getattr(playback, "RtpPlaybackReceiver", None) is not None, (
        "Sound RTP receiver/playback boundary is not implemented"
    )

    if playback_sink is None:
        return ConcreteRtpPlaybackReceiver()

    return ConcreteRtpPlaybackReceiver(playback_sink=playback_sink)


def _announce_stream(receiver: ConcreteRtpPlaybackReceiver, stream_id: str) -> None:
    """函数契约说明.

    功能: 执行 _announce_stream 的同步逻辑,并协调
    announce_stream。
    参数: receiver: RtpPlaybackReceiver。
    必填。 stream_id: str。 必填。
    契约: 同步调用。 返回 `None`。
    """

    receiver.announce_stream(stream_id=stream_id, sample_rate=48_000, channels=1)


def _l16_rtp_packet(
    timestamp: int,
    payload: bytes,
    *,
    version: int = 2,
    payload_type: int = 96,
    ssrc: int = 7,
    exact_frame: bool = True,
) -> bytes:
    """函数契约说明.

    功能: 执行 _l16_rtp_packet 的同步逻辑,并协调
    to_bytes, _frame, bytes。
    参数: timestamp: int。 必填。 payload:
    bytes。 必填。 version: int。 可省略。
    payload_type: int。 可省略。 ssrc: int。
    可省略。 exact_frame: bool。 可省略。
    契约: 同步调用。 返回 `bytes`。
    """

    first_byte = version << 6

    second_byte = payload_type

    header = (
        bytes([first_byte, second_byte, 0, 1])
        + timestamp.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
    )

    resolved_payload = _frame(payload) if exact_frame else payload

    return header + resolved_payload


def _frame(payload: bytes) -> bytes:
    """函数契约说明.

    功能: 执行 _frame 的同步逻辑,并协调 bytes, len。
    参数: payload: bytes。 必填。
    契约: 同步调用。 返回 `bytes`。
    """

    return payload + bytes(640 - len(payload))


def test_rtp_receiver_advances_stream_relative_playback_state_for_announced_l16_stream() -> (
    None
):
    # Given: an Orchestrator-announced stream and deterministic V2/PT96 L16 packets.

    """函数契约说明.

    功能: 验证 rtp receiver advances stream
    relative playback state for
    announced l16 stream 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    receiver = _receiver()

    _announce_stream(receiver, "stream-sound-001")

    # When: the receiver accepts two packets whose RTP timestamps advance by their sample count.

    receiver.receive_packet(_l16_rtp_packet(960, b"\x00\x01\xff\xfe"))

    receiver.receive_packet(_l16_rtp_packet(962, b"\x00\x02\xff\xfd"))

    # Then: emitted playback state is stream-owned, URI-free, and monotonically advances with RTP.

    assert [state.stream_id for state in receiver.playback_states] == [
        "stream-sound-001"
    ] * 2

    assert [state.rtp_timestamp for state in receiver.playback_states] == [960, 962]

    assert [state.playback_position_samples for state in receiver.playback_states] == [
        320,
        640,
    ]

    assert all(not hasattr(state, "mode") for state in receiver.playback_states)


def test_rtp_receiver_delivers_accepted_l16_payload_unchanged_with_playback_state() -> (
    None
):
    # Given: an active announced stream with an injectable L16 playback sink.

    """函数契约说明.

    功能: 验证 rtp receiver delivers
    accepted l16 payload unchanged with
    playback state 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])

    receiver = _receiver(sink)

    _announce_stream(receiver, "stream-sound-delivery")

    payload = _frame(b"\x00\x01\xff\xfe")

    # When: the receiver accepts a valid V2/PT96 L16 RTP packet.

    receiver.receive_packet(_l16_rtp_packet(960, payload))

    # Then: the exact network-order bytes reach playback and existing state advances.

    assert sink.frames == [
        L16PlaybackFrame(
            stream_id=StreamId("stream-sound-delivery"),
            sample_rate=48_000,
            channels=1,
            payload=payload,
        )
    ]

    assert receiver.playback_states[-1].playback_position_samples == 320


def test_rtp_receiver_does_not_record_state_when_playback_sink_write_fails() -> None:
    # Given: an active stream whose playback sink rejects its accepted payload.

    """函数契约说明.

    功能: 验证 rtp receiver does not record
    state when playback sink write fails
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。 可能抛出
    AssertionError。
    """

    receiver = playback.RtpPlaybackReceiver(playback_sink=_FailingPlaybackSink())

    receiver.announce_stream(
        stream_id="stream-sound-failing-write", sample_rate=48_000, channels=1
    )

    # When: the receiver delivers a valid L16 RTP packet.

    try:
        receiver.receive_packet(_l16_rtp_packet(960, b"\x00\x01"))

    except _SinkWriteFailure:
        pass

    else:
        raise AssertionError("expected sink write failure")

    # Then: no unplayed packet advances observable playback state.

    assert receiver.playback_states == []


def test_rtp_receiver_rejects_invalid_or_unknown_packets_without_playback_state() -> (
    None
):
    # Given: a receiver with one announced stream and packets outside its L16 RTP contract.

    """函数契约说明.

    功能: 验证 rtp receiver rejects invalid
    or unknown packets without playback
    state 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])

    receiver = _receiver(sink)

    _announce_stream(receiver, "stream-sound-002")

    unknown_stream_packet = _l16_rtp_packet(0, b"\x00\x01")

    bad_version_packet = _l16_rtp_packet(0, b"\x00\x01", version=1)

    bad_payload_type_packet = _l16_rtp_packet(0, b"\x00\x01", payload_type=97)

    odd_l16_packet = _l16_rtp_packet(0, b"\x00", exact_frame=False)

    # When: each packet is received without a matching stream or valid V2/PT96/even-sample payload.

    receiver.receive_packet(unknown_stream_packet, stream_id="stream-sound-unknown")

    receiver.receive_packet(bad_version_packet, stream_id="stream-sound-002")

    receiver.receive_packet(bad_payload_type_packet, stream_id="stream-sound-002")

    receiver.receive_packet(odd_l16_packet, stream_id="stream-sound-002")

    # Then: malformed or unannounced media produces no playback state.

    assert receiver.playback_states == []

    assert sink.frames == []


def test_rtp_receiver_suppresses_cancelled_stream_packets_while_fresh_stream_remains_valid() -> (
    None
):
    # Given: an active stream that Orchestrator cancels before a new stream begins.

    """函数契约说明.

    功能: 验证 rtp receiver suppresses
    cancelled stream packets while fresh
    stream remains valid 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])

    receiver = _receiver(sink)

    _announce_stream(receiver, "stream-sound-stale")

    receiver.receive_packet(
        _l16_rtp_packet(0, b"\x00\x01"), stream_id="stream-sound-stale"
    )

    receiver.cancel_stream("stream-sound-stale")

    _announce_stream(receiver, "stream-sound-fresh")

    # When: a stale packet arrives after cancellation and a fresh packet follows on the new stream.

    receiver.receive_packet(
        _l16_rtp_packet(2, b"\x00\x02"), stream_id="stream-sound-stale"
    )

    receiver.receive_packet(
        _l16_rtp_packet(0, b"\x00\x03"), stream_id="stream-sound-fresh"
    )

    # Then: cancellation prevents stale state/cue progression without invalidating the fresh stream.

    assert [state.stream_id for state in receiver.playback_states] == [
        "stream-sound-stale",
        "stream-sound-fresh",
    ]

    assert [state.playback_position_samples for state in receiver.playback_states] == [
        320,
        320,
    ]

    assert [frame.stream_id for frame in sink.frames] == [
        StreamId("stream-sound-stale"),
        StreamId("stream-sound-fresh"),
    ]

    assert sink.closed_streams == ["stream-sound-stale"]


def test_rtp_receiver_rejects_delayed_flushed_epoch_ssrc_after_replacement_announcement() -> (
    None
):
    # Given: a generated epoch whose SSRC is flushed before its replacement is announced.

    """函数契约说明.

    功能: 验证 rtp receiver rejects delayed
    flushed epoch ssrc after replacement
    announcement 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])

    receiver = playback.RtpPlaybackReceiver(playback_sink=sink)

    receiver.announce_stream(
        stream_id="stream-epoch", sample_rate=16_000, channels=1, expected_ssrc=101
    )

    assert receiver.flush_stream("stream-epoch", 101) is True

    receiver.announce_stream(
        stream_id="stream-epoch", sample_rate=16_000, channels=1, expected_ssrc=202
    )

    # When: delayed media from the old epoch races valid media from the replacement epoch.

    receiver.receive_packet(
        _l16_rtp_packet(0, b"\x00\x01", ssrc=101), stream_id="stream-epoch"
    )

    receiver.receive_packet(
        _l16_rtp_packet(0, b"\x00\x02", ssrc=202), stream_id="stream-epoch"
    )

    # Then: only the announced replacement SSRC reaches playback.

    assert [frame.payload for frame in sink.frames] == [_frame(b"\x00\x02")]

    assert [state.playback_position_samples for state in receiver.playback_states] == [
        320
    ]


def test_rtp_receiver_closes_playback_sink_on_shutdown() -> None:
    # Given: a receiver with a configured playback sink.

    """函数契约说明.

    功能: 验证 rtp receiver closes playback
    sink on shutdown 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])

    receiver = _receiver(sink)

    # When: the Sound runtime shuts down.

    receiver.close()

    # Then: playback resources are deterministically closed.

    assert sink.closed is True
