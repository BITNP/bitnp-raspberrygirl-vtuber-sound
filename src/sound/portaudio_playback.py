
import sys
from collections import deque
from threading import Lock
from typing import Literal, Protocol, final

import sounddevice

from sound.rtp_playback import L16PlaybackFrame, StreamId

type PlaybackDevice = int | str | None

type NativeByteOrder = Literal["little", "big"]


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
            blocksize=320,  # pyright: ignore[reportCallIssue]
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
                callback_stream.start()
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
            callback_stream.stop()
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
        self._chunks: deque[bytes] = deque()
        self._pending = b""
        self._stream = sounddevice.RawOutputStream(
            device=device, samplerate=sample_rate, channels=channels, dtype="int16",
            blocksize=320,  # pyright: ignore[reportCallIssue]
            latency="high",  # pyright: ignore[reportCallIssue]
            callback=self._callback,  # pyright: ignore[reportCallIssue]
        )

    def start(self) -> None:
        self._stream.start()

    def push(self, data: bytes) -> None:
        with self._lock:
            self._chunks.append(data)

    def abort(self) -> None:
        self._stream.abort(); self._stream.close()

    def stop(self) -> None:
        self._stream.stop(); self._stream.close()

    def _callback(
        self, outdata: memoryview, frames: int, time_info: object, status: object
    ) -> None:
        _ = (time_info, status)
        needed = frames * 2
        with self._lock:
            while len(self._pending) < needed and self._chunks:
                self._pending += self._chunks.popleft()
            output = self._pending[:needed]
            self._pending = self._pending[needed:]
        memoryview(outdata).cast("B")[:] = output + bytes(needed - len(output))


def l16_payload_to_native_int16(payload: bytes, *, byteorder: NativeByteOrder) -> bytes:

    match byteorder:
        case "big":
            return payload

        case "little":
            native_payload = bytearray(payload)

            native_payload[0::2] = payload[1::2]

            native_payload[1::2] = payload[0::2]

            return bytes(native_payload)
