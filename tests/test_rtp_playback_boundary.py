from typing import Protocol

import sound.playback as playback


class PlaybackState(Protocol):
    stream_id: str
    rtp_timestamp: int
    playback_position_samples: int


class RtpPlaybackReceiver(Protocol):
    playback_states: list[PlaybackState]

    def announce_stream(self, *, stream_id: str, sample_rate: int, channels: int) -> None: ...

    def receive_packet(self, packet: bytes, *, stream_id: str | None = None) -> None: ...

    def cancel_stream(self, stream_id: str) -> None: ...


def _receiver() -> RtpPlaybackReceiver:
    receiver_type = getattr(playback, "RtpPlaybackReceiver", None)
    assert receiver_type is not None, "Sound RTP receiver/playback boundary is not implemented"
    return receiver_type()


def _announce_stream(receiver: RtpPlaybackReceiver, stream_id: str) -> None:
    receiver.announce_stream(stream_id=stream_id, sample_rate=48_000, channels=1)


def _l16_rtp_packet(
    timestamp: int,
    payload: bytes,
    *,
    version: int = 2,
    payload_type: int = 96,
) -> bytes:
    first_byte = version << 6
    second_byte = payload_type
    header = bytes([first_byte, second_byte, 0, 1]) + timestamp.to_bytes(4, "big") + (7).to_bytes(4, "big")
    return header + payload


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
    assert [state.playback_position_samples for state in receiver.playback_states] == [2, 4]


def test_rtp_receiver_rejects_invalid_or_unknown_packets_without_playback_state() -> None:
    # Given: a receiver with one announced stream and packets outside its L16 RTP contract.
    receiver = _receiver()
    _announce_stream(receiver, "stream-sound-002")
    unknown_stream_packet = _l16_rtp_packet(0, b"\x00\x01")
    bad_version_packet = _l16_rtp_packet(0, b"\x00\x01", version=1)
    bad_payload_type_packet = _l16_rtp_packet(0, b"\x00\x01", payload_type=97)
    odd_l16_packet = _l16_rtp_packet(0, b"\x00")

    # When: each packet is received without a matching stream or valid V2/PT96/even-sample payload.
    receiver.receive_packet(unknown_stream_packet, stream_id="stream-sound-unknown")
    receiver.receive_packet(bad_version_packet, stream_id="stream-sound-002")
    receiver.receive_packet(bad_payload_type_packet, stream_id="stream-sound-002")
    receiver.receive_packet(odd_l16_packet, stream_id="stream-sound-002")

    # Then: malformed or unannounced media produces no playback state.
    assert receiver.playback_states == []


def test_rtp_receiver_suppresses_cancelled_stream_packets_while_fresh_stream_remains_valid() -> None:
    # Given: an active stream that Orchestrator cancels before a new stream begins.
    receiver = _receiver()
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
    assert [state.playback_position_samples for state in receiver.playback_states] == [1, 1]
