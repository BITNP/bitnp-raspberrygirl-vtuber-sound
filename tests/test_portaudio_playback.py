
# pyright: reportPrivateUsage=false

from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

import pytest

from sound.portaudio_playback import (
    PlaybackDevice,
    PortAudioPlaybackSink,
    _CallbackPlayback,
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
    ...



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


def test_portaudio_sink_aborts_and_closes_cancelled_streams_but_stops_normal_streams() -> (
    None
):
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

    receiver.announce_stream(
        stream_id="stream-failing-write", sample_rate=48_000, channels=1
    )

    packet = (
        bytes([0x80, 96, 0, 1])
        + (0).to_bytes(4, "big")
        + (7).to_bytes(4, "big")
        + b"\x00\x01"
        + bytes(638)
    )

    # When: a valid RTP packet reaches the failed device write boundary.

    with pytest.raises(_StreamWriteFailure):
        receiver.receive_packet(packet, stream_id="stream-failing-write")

    # Then: output failure leaves observable receiver progress unchanged.

    assert receiver.playback_states == []


def _callback_playback_for_test(
    *, capacity: int = 12, started: bool = True
) -> tuple[_CallbackPlayback, _RecordingRawOutputStream]:
    # The actual constructor opens a hardware stream.  Build only its already
    # allocated PCM queue so these tests can exercise the realtime callback
    # algorithm without requiring a PortAudio device.
    playback = object.__new__(_CallbackPlayback)
    playback._lock = Lock()
    playback._capacity = capacity
    playback._buffer = bytearray(capacity)
    playback._silence = bytes(capacity)
    playback._read_offset = 0
    playback._write_offset = 0
    playback._available = 0
    playback._channels = 1
    playback._finishing = False
    playback._started = started
    stream = _RecordingRawOutputStream()
    setattr(playback, "_stream", stream)  # noqa: B010 - test-only hardware seam.
    return playback, stream


def test_callback_playback_preserves_queue_order_across_ring_boundary() -> None:
    # Given: a small preallocated ring whose read/write position will wrap.


    playback, _ = _callback_playback_for_test()
    playback.push(b"abcdefgh")
    first = memoryview(bytearray(6))
    playback._callback(first, 3, None, None)
    playback.push(b"ijklmnop")

    # When: PortAudio asks for the remaining queued bytes.


    second = memoryview(bytearray(10))
    playback._callback(second, 5, None, None)

    # Then: it receives continuous PCM in FIFO order, not a wrapped glitch.


    assert bytes(first) == b"abcdef"
    assert bytes(second) == b"ghijklmnop"


def test_callback_playback_starts_only_after_a_full_hardware_block_is_queued() -> None:
    # Given: callback playback configured for its 60 ms hardware block.


    playback, stream = _callback_playback_for_test(capacity=3_000, started=False)

    # When: RTP's three 20 ms frames arrive in sequence.


    playback.push(bytes(640))
    playback.push(bytes(640))
    assert stream.started is False
    playback.push(bytes(640))

    # Then: device playback starts with a complete block, not padded silence.


    assert stream.started is True


def test_callback_playback_fills_only_an_underrun_tail_with_silence() -> None:
    # Given: less PCM than the hardware callback requests.


    playback, _ = _callback_playback_for_test()
    playback.push(b"\x01\x02\x03\x04")
    output = memoryview(bytearray(8))

    # When: the callback consumes the queue.


    playback._callback(output, 4, None, None)

    # Then: available audio is preserved and only the missing tail is silent.


    assert bytes(output) == b"\x01\x02\x03\x04\x00\x00\x00\x00"


def test_callback_playback_rejects_queue_overflow_without_overwriting_pcm() -> None:
    # Given: a full bounded realtime queue.


    playback, _ = _callback_playback_for_test(capacity=4)
    playback.push(b"abcd")

    # When: a producer attempts to overwrite queued audio.


    with pytest.raises(BufferError, match="buffer overflow"):
        playback.push(b"ef")

    # Then: the original audio is still exactly what PortAudio receives.


    output = memoryview(bytearray(4))
    playback._callback(output, 2, None, None)
    assert bytes(output) == b"abcd"


def test_callback_playback_drain_does_not_stop_the_final_pcm_block() -> None:
    # Given: a completed stream with exactly one hardware block left to play.


    playback, _ = _callback_playback_for_test(capacity=8)
    playback.push(b"abcd")
    playback.finish()

    # When: the final PCM block is consumed, it remains audible.


    final_pcm = memoryview(bytearray(4))
    playback._callback(final_pcm, 2, None, None)

    # Then: stop is deferred to the following silent callback, avoiding a
    # truncated final syllable.


    assert bytes(final_pcm) == b"abcd"
    with pytest.raises(Exception) as error:
        playback._callback(memoryview(bytearray(4)), 2, None, None)
    assert type(error.value).__name__ == "CallbackStop"


def test_close_stream_aborts_a_callback_already_draining() -> None:
    playback, stream = _callback_playback_for_test()
    playback._drained = None
    sink = PortAudioPlaybackSink(device=None)
    sink._callback_streams[StreamId("draining")] = playback
    sink.finish_stream("draining")
    sink.close_stream("draining")
    assert stream.aborted
    assert stream.closed
    assert not sink._draining_callbacks
