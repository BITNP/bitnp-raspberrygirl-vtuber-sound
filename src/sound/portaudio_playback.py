
import sys
from threading import Lock
from typing import Final, Literal, Protocol, final

import sounddevice

from sound.rtp_playback import L16PlaybackFrame, StreamId

type PlaybackDevice = int | str | None

type NativeByteOrder = Literal["little", "big"]

# RTP remains fixed at 20 ms / 320 samples.  Hardware callbacks deliberately
# consume three RTP frames at a time: invoking Python every 20 ms leaves too
# little scheduling slack for a loaded desktop and manifests as rare clicks.
_CALLBACK_BLOCK_SAMPLES: Final = 960


class RawOutputStream(Protocol):

    def start(self) -> None:

        ...

    def write(self, data: bytes) -> bool:

        ...

    def abort(self) -> None:

        ...

    def stop(self) -> None:

        ...

    def close(self) -> None:

        ...


class RawOutputStreamFactory(Protocol):

    def open(
        self,
        *,
        device: PlaybackDevice,
        samplerate: int,
        channels: int,
        dtype: Literal["int16"],
    ) -> RawOutputStream:

        ...


@final
class SounddeviceRawOutputStreamFactory:

    def open(
        self,
        *,
        device: PlaybackDevice,
        samplerate: int,
        channels: int,
        dtype: Literal["int16"],
    ) -> RawOutputStream:

        return sounddevice.RawOutputStream(
            device=device,
            samplerate=samplerate,
            channels=channels,
            dtype=dtype,
            blocksize=_CALLBACK_BLOCK_SAMPLES,  # pyright: ignore[reportCallIssue]
            latency="high",  # pyright: ignore[reportCallIssue]
        )


@final
class PortAudioPlaybackSink:

    def __init__(
        self,
        *,
        device: PlaybackDevice,
        stream_factory: RawOutputStreamFactory | None = None,
    ) -> None:

        self._device = device

        self._stream_factory = stream_factory or SounddeviceRawOutputStreamFactory()

        self._streams: dict[StreamId, RawOutputStream] = {}

        self._callback_streams: dict[StreamId, _CallbackPlayback] = {}

    def write(self, frame: L16PlaybackFrame) -> None:

        stream = self._streams.get(frame.stream_id)

        callback_stream = self._callback_streams.get(frame.stream_id)

        if callback_stream is not None:
            callback_stream.push(l16_payload_to_native_int16(frame.payload, byteorder=sys.byteorder))
            return

        if stream is None:
            if isinstance(self._stream_factory, SounddeviceRawOutputStreamFactory):
                callback_stream = _CallbackPlayback(
                    device=self._device,
                    sample_rate=frame.sample_rate,
                    channels=frame.channels,
                )
                self._callback_streams[frame.stream_id] = callback_stream
                callback_stream.push(
                    l16_payload_to_native_int16(frame.payload, byteorder=sys.byteorder)
                )
                return
            stream = self._stream_factory.open(
                device=self._device,
                samplerate=frame.sample_rate,
                channels=frame.channels,
                dtype="int16",
            )

            stream.start()

            self._streams[frame.stream_id] = stream

        _ = stream.write(
            l16_payload_to_native_int16(frame.payload, byteorder=sys.byteorder)
        )

    def close_stream(self, stream_id: str) -> None:

        stream = self._streams.pop(StreamId(stream_id), None)
        callback_stream = self._callback_streams.pop(StreamId(stream_id), None)
        if callback_stream is not None:
            callback_stream.abort()
            return

        if stream is not None:
            try:
                stream.abort()

            finally:
                stream.close()

    def finish_stream(self, stream_id: str) -> None:

        stream = self._streams.pop(StreamId(stream_id), None)
        callback_stream = self._callback_streams.pop(StreamId(stream_id), None)
        if callback_stream is not None:
            # RTP reception may finish far ahead of device consumption.  Unlike
            # the blocking writer, a callback stream still owns queued PCM here;
            # request an orderly drain instead of cutting its whole tail off.
            callback_stream.finish()
            return

        if stream is not None:
            try:
                stream.stop()

            finally:
                stream.close()

    def close(self) -> None:

        streams = tuple(self._streams.values())

        self._streams.clear()
        callback_streams = tuple(self._callback_streams.values())
        self._callback_streams.clear()
        for callback_stream in callback_streams:
            callback_stream.stop()

        for stream in streams:
            try:
                stream.stop()

            finally:
                stream.close()


@final
class _CallbackPlayback:

    def __init__(self, *, device: PlaybackDevice, sample_rate: int, channels: int) -> None:
        self._lock = Lock()
        # Generated RTP arrives on the asyncio thread while PortAudio pulls from
        # its realtime callback.  Keep the callback free of deque operations,
        # bytes concatenation and per-block allocations: all three can cause a
        # short underrun that is heard as a click or a rapidly broken voice.
        # Ten seconds is deliberately far above the jitter reserve while still
        # bounding latency and memory if a producer misbehaves.
        self._capacity = sample_rate * channels * 2 * 10
        self._buffer = bytearray(self._capacity)
        self._silence = bytes(self._capacity)
        self._read_offset = 0
        self._write_offset = 0
        self._available = 0
        self._channels = channels
        self._finishing = False
        self._started = False
        self._stream = sounddevice.RawOutputStream(
            device=device, samplerate=sample_rate, channels=channels, dtype="int16",
            blocksize=_CALLBACK_BLOCK_SAMPLES,  # pyright: ignore[reportCallIssue]
            latency="high",  # pyright: ignore[reportCallIssue]
            callback=self._callback,  # pyright: ignore[reportCallIssue]
        )

    def start(self) -> None:
        self._stream.start()

    def push(self, data: bytes) -> None:
        should_start = False
        with self._lock:
            # A bounded buffer must never overwrite queued audio: doing so
            # creates a discontinuity.  The normal paced RTP producer remains
            # many orders below this limit, so overflow is an explicit failure.
            if len(data) > self._capacity - self._available:
                raise BufferError("PortAudio playback buffer overflow")
            first = min(len(data), self._capacity - self._write_offset)
            self._buffer[self._write_offset : self._write_offset + first] = data[:first]
            remaining = len(data) - first
            if remaining:
                self._buffer[:remaining] = data[first:]
            self._write_offset = (self._write_offset + len(data)) % self._capacity
            self._available += len(data)
            block_bytes = _CALLBACK_BLOCK_SAMPLES * 2 * self._channels
            if not self._started and self._available >= block_bytes:
                self._started = True
                should_start = True
        if should_start:
            self.start()

    def abort(self) -> None:
        self._stream.abort(); self._stream.close()

    def finish(self) -> None:
        should_start = False
        with self._lock:
            self._finishing = True
            if not self._started and self._available > 0:
                self._started = True
                should_start = True
        if should_start:
            self.start()

    def stop(self) -> None:
        self._stream.stop(); self._stream.close()

    def _callback(
        self, outdata: memoryview, frames: int, time_info: object, status: object
    ) -> None:
        _ = (time_info, status)
        needed = frames * 2 * self._channels
        output = memoryview(outdata).cast("B")
        if needed > self._capacity:
            raise RuntimeError("PortAudio callback block exceeds playback buffer")
        with self._lock:
            copied = min(needed, self._available)
            first = min(copied, self._capacity - self._read_offset)
            output[:first] = self._buffer[self._read_offset : self._read_offset + first]
            remaining = copied - first
            if remaining:
                output[first:copied] = self._buffer[:remaining]
            self._read_offset = (self._read_offset + copied) % self._capacity
            self._available -= copied
            # Stop on the callback *after* the final PCM block.  Requesting
            # CallbackStop in the block that consumes the tail is permitted by
            # PortAudio but can discard that very block on some backends.
            stop_after_silence = self._finishing and copied == 0 and self._available == 0
        if copied < needed:
            output[copied:needed] = self._silence[: needed - copied]
        if stop_after_silence:
            raise sounddevice.CallbackStop  # pyright: ignore[reportAttributeAccessIssue,reportUnknownMemberType]


def l16_payload_to_native_int16(payload: bytes, *, byteorder: NativeByteOrder) -> bytes:

    match byteorder:
        case "big":
            return payload

        case "little":
            native_payload = bytearray(payload)

            native_payload[0::2] = payload[1::2]

            native_payload[1::2] = payload[0::2]

            return bytes(native_payload)
