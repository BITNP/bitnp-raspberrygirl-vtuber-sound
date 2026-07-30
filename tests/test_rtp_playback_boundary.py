from dataclasses import dataclass
from typing import Protocol

from sound import playback
from sound.rtp_playback import L16PlaybackFrame, StreamId


class PlaybackState(Protocol):
    stream_id: str
    rtp_timestamp: int
    playback_position_samples: int


class RtpPlaybackReceiver(Protocol):
    playback_states: list[PlaybackState]

    def announce_stream(self, *, stream_id: str, sample_rate: int, channels: int) -> None: ...

    def receive_packet(self, packet: bytes, *, stream_id: str | None = None) -> None: ...

    def cancel_stream(self, stream_id: str) -> None: ...

    def close(self) -> None: ...


@dataclass
class _RecordingPlaybackSink:
    frames: list[L16PlaybackFrame]
    closed_streams: list[str]
    closed: bool = False

    def write(self, frame: L16PlaybackFrame) -> None:
        self.frames.append(frame)

    def close_stream(self, stream_id: str) -> None:
        self.closed_streams.append(stream_id)

    def close(self) -> None:
        self.closed = True


class _FailingPlaybackSink:
    def write(self, frame: L16PlaybackFrame) -> None:
        raise _SinkWriteFailure

    def close_stream(self, stream_id: str) -> None:
        return None

    def close(self) -> None:
        return None


class _SinkWriteFailure(RuntimeError):
    pass


def _receiver(playback_sink: _RecordingPlaybackSink | None = None) -> RtpPlaybackReceiver:
    receiver_type = getattr(playback, "RtpPlaybackReceiver", None)
    assert receiver_type is not None, "Sound RTP receiver/playback boundary is not implemented"
    if playback_sink is None:
        return receiver_type()
    return receiver_type(playback_sink=playback_sink)


def _announce_stream(receiver: RtpPlaybackReceiver, stream_id: str) -> None:
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
    first_byte = version << 6
    second_byte = payload_type
    header = bytes([first_byte, second_byte, 0, 1]) + timestamp.to_bytes(4, "big") + ssrc.to_bytes(4, "big")
    resolved_payload = _frame(payload) if exact_frame else payload
    return header + resolved_payload


def _frame(payload: bytes) -> bytes:
    return payload + bytes(640 - len(payload))


def test_rtp_receiver_advances_stream_relative_playback_state_for_announced_l16_stream() -> None:
    # Given: an Orchestrator-announced stream and deterministic V2/PT96 L16 packets.
    receiver = _receiver()
    _announce_stream(receiver, "stream-sound-001")

    # When: the receiver accepts two packets whose RTP timestamps advance by their sample count.
    receiver.receive_packet(_l16_rtp_packet(960, b"\x00\x01\xff\xfe"))
    receiver.receive_packet(_l16_rtp_packet(962, b"\x00\x02\xff\xfd"))

    # Then: emitted playback state is stream-owned, URI-free, and monotonically advances with RTP.
    assert [state.stream_id for state in receiver.playback_states] == ["stream-sound-001"] * 2
    assert [state.rtp_timestamp for state in receiver.playback_states] == [960, 962]
    assert [state.playback_position_samples for state in receiver.playback_states] == [320, 640]
    assert all(not hasattr(state, "mode") for state in receiver.playback_states)


def test_rtp_receiver_delivers_accepted_l16_payload_unchanged_with_playback_state() -> None:
    # Given: an active announced stream with an injectable L16 playback sink.
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
    receiver = playback.RtpPlaybackReceiver(playback_sink=_FailingPlaybackSink())
    receiver.announce_stream(stream_id="stream-sound-failing-write", sample_rate=48_000, channels=1)

    # When: the receiver delivers a valid L16 RTP packet.
    try:
        receiver.receive_packet(_l16_rtp_packet(960, b"\x00\x01"))
    except _SinkWriteFailure:
        pass
    else:
        raise AssertionError("expected sink write failure")

    # Then: no unplayed packet advances observable playback state.
    assert receiver.playback_states == []


def test_rtp_receiver_rejects_invalid_or_unknown_packets_without_playback_state() -> None:
    # Given: a receiver with one announced stream and packets outside its L16 RTP contract.
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


def test_rtp_receiver_suppresses_cancelled_stream_packets_while_fresh_stream_remains_valid() -> None:
    # Given: an active stream that Orchestrator cancels before a new stream begins.
    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])
    receiver = _receiver(sink)
    _announce_stream(receiver, "stream-sound-stale")
    receiver.receive_packet(_l16_rtp_packet(0, b"\x00\x01"), stream_id="stream-sound-stale")
    receiver.cancel_stream("stream-sound-stale")
    _announce_stream(receiver, "stream-sound-fresh")

    # When: a stale packet arrives after cancellation and a fresh packet follows on the new stream.
    receiver.receive_packet(_l16_rtp_packet(2, b"\x00\x02"), stream_id="stream-sound-stale")
    receiver.receive_packet(_l16_rtp_packet(0, b"\x00\x03"), stream_id="stream-sound-fresh")

    # Then: cancellation prevents stale state/cue progression without invalidating the fresh stream.
    assert [state.stream_id for state in receiver.playback_states] == [
        "stream-sound-stale",
        "stream-sound-fresh",
    ]
    assert [state.playback_position_samples for state in receiver.playback_states] == [320, 320]
    assert [frame.stream_id for frame in sink.frames] == [
        StreamId("stream-sound-stale"),
        StreamId("stream-sound-fresh"),
    ]
    assert sink.closed_streams == ["stream-sound-stale"]


def test_rtp_receiver_rejects_delayed_flushed_epoch_ssrc_after_replacement_announcement() -> None:
    # Given: a generated epoch whose SSRC is flushed before its replacement is announced.
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
    receiver.receive_packet(_l16_rtp_packet(0, b"\x00\x01", ssrc=101), stream_id="stream-epoch")
    receiver.receive_packet(_l16_rtp_packet(0, b"\x00\x02", ssrc=202), stream_id="stream-epoch")

    # Then: only the announced replacement SSRC reaches playback.
    assert [frame.payload for frame in sink.frames] == [_frame(b"\x00\x02")]
    assert [state.playback_position_samples for state in receiver.playback_states] == [320]


def test_rtp_receiver_closes_playback_sink_on_shutdown() -> None:
    # Given: a receiver with a configured playback sink.
    sink = _RecordingPlaybackSink(frames=[], closed_streams=[])
    receiver = _receiver(sink)

    # When: the Sound runtime shuts down.
    receiver.close()

    # Then: playback resources are deterministically closed.
    assert sink.closed is True
