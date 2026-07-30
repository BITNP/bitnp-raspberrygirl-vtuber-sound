from dataclasses import dataclass, field
from typing import Literal

import pytest

from sound.portaudio_playback import (
    PlaybackDevice,
    PortAudioPlaybackSink,
    l16_payload_to_native_int16,
)
from sound.rtp_playback import L16PlaybackFrame, RtpPlaybackReceiver, StreamId


@dataclass
class _RecordingRawOutputStream:
    writes: list[bytes] = field(default_factory=list)
    started: bool = False
    aborted: bool = False
    stopped: bool = False
    closed: bool = False
    fail_writes: bool = False

    def start(self) -> None:
        self.started = True

    def write(self, data: bytes) -> bool:
        if self.fail_writes:
            raise _StreamWriteFailure
        self.writes.append(data)
        return False

    def abort(self) -> None:
        self.aborted = True

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


class _StreamWriteFailure(RuntimeError):
    pass


@dataclass
class _RecordingRawOutputStreamFactory:
    configurations: list[tuple[PlaybackDevice, int, int, Literal["int16"]]] = field(
        default_factory=list
    )
    streams: list[_RecordingRawOutputStream] = field(default_factory=list)
    prepared_streams: list[_RecordingRawOutputStream] = field(default_factory=list)

    def open(
        self,
        *,
        device: PlaybackDevice,
        samplerate: int,
        channels: int,
        dtype: Literal["int16"],
    ) -> _RecordingRawOutputStream:
        stream = (
            self.prepared_streams.pop(0)
            if self.prepared_streams
            else _RecordingRawOutputStream()
        )
        self.configurations.append((device, samplerate, channels, dtype))
        self.streams.append(stream)
        return stream


def _frame(
    stream_id: str = "stream-portaudio", *, sample_rate: int = 48_000, channels: int = 2
) -> L16PlaybackFrame:
    return L16PlaybackFrame(
        stream_id=StreamId(stream_id),
        sample_rate=sample_rate,
        channels=channels,
        payload=b"\x00\x01\xff\xfe",
    )


@pytest.mark.parametrize(
    ("byteorder", "expected"),
    [("little", b"\x01\x00\xfe\xff"), ("big", b"\x00\x01\xff\xfe")],
)
def test_l16_payload_converts_to_device_native_int16_for_each_byteorder(
    byteorder: Literal["little", "big"], expected: bytes
) -> None:
    # Given: network-order positive and negative L16 samples.
    payload = b"\x00\x01\xff\xfe"

    # When: the output boundary selects a device byte order.
    native_payload = l16_payload_to_native_int16(payload, byteorder=byteorder)

    # Then: each int16 sample preserves its value in the requested native order.
    assert native_payload == expected


def test_portaudio_sink_starts_one_typed_stream_per_stream_id() -> None:
    # Given: two announced streams with distinct output formats.
    factory = _RecordingRawOutputStreamFactory()
    sink = PortAudioPlaybackSink(device="speaker query", stream_factory=factory)

    # When: each stream delivers one accepted L16 frame.
    sink.write(_frame("stream-one", sample_rate=48_000, channels=1))
    sink.write(_frame("stream-two", sample_rate=24_000, channels=2))
    sink.write(_frame("stream-one", sample_rate=48_000, channels=1))

    # Then: each gets its own started native-int16 RawOutputStream.
    assert factory.configurations == [
        ("speaker query", 48_000, 1, "int16"),
        ("speaker query", 24_000, 2, "int16"),
    ]
    assert [stream.started for stream in factory.streams] == [True, True]
    assert [len(stream.writes) for stream in factory.streams] == [2, 1]


def test_portaudio_sink_aborts_and_closes_cancelled_streams_but_stops_normal_streams() -> None:
    # Given: two active streams backed by distinct RawOutputStreams.
    factory = _RecordingRawOutputStreamFactory()
    sink = PortAudioPlaybackSink(device=None, stream_factory=factory)
    sink.write(_frame("stream-cancelled"))
    sink.write(_frame("stream-normal"))

    # When: one stream is cancelled and the remaining runtime closes normally.
    sink.close_stream("stream-cancelled")
    sink.close()

    # Then: cancellation aborts immediately, while normal shutdown stops then closes.
    assert [
        (stream.aborted, stream.stopped, stream.closed) for stream in factory.streams
    ] == [(True, False, True), (False, True, True)]


def test_receiver_does_not_advance_state_when_portaudio_write_fails() -> None:
    # Given: a receiver whose started native output stream rejects its first write.
    failing_stream = _RecordingRawOutputStream(fail_writes=True)
    factory = _RecordingRawOutputStreamFactory(prepared_streams=[failing_stream])
    receiver = RtpPlaybackReceiver(
        playback_sink=PortAudioPlaybackSink(device=None, stream_factory=factory)
    )
    receiver.announce_stream(stream_id="stream-failing-write", sample_rate=48_000, channels=1)
    packet = bytes([0x80, 96, 0, 1]) + (0).to_bytes(4, "big") + (7).to_bytes(4, "big") + b"\x00\x01" + bytes(638)

    # When: a valid RTP packet reaches the failed device write boundary.
    with pytest.raises(_StreamWriteFailure):
        receiver.receive_packet(packet, stream_id="stream-failing-write")

    # Then: output failure leaves observable receiver progress unchanged.
    assert receiver.playback_states == []
