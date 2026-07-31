
import sys
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
            blocksize=320,
            latency="high",
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

    def write(self, frame: L16PlaybackFrame) -> None:

        stream = self._streams.get(frame.stream_id)

        if stream is None:
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

        if stream is not None:
            try:
                stream.abort()

            finally:
                stream.close()

    def finish_stream(self, stream_id: str) -> None:

        stream = self._streams.pop(StreamId(stream_id), None)

        if stream is not None:
            try:
                stream.stop()

            finally:
                stream.close()

    def close(self) -> None:

        streams = tuple(self._streams.values())

        self._streams.clear()

        for stream in streams:
            try:
                stream.stop()

            finally:
                stream.close()


def l16_payload_to_native_int16(payload: bytes, *, byteorder: NativeByteOrder) -> bytes:

    match byteorder:
        case "big":
            return payload

        case "little":
            native_payload = bytearray(payload)

            native_payload[0::2] = payload[1::2]

            native_payload[1::2] = payload[0::2]

            return bytes(native_payload)
