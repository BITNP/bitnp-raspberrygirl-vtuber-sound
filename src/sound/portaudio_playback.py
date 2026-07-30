"""模块契约说明.

职责: 提供 sound.portaudio_playback
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import sys
from typing import Literal, Protocol, final

import sounddevice

from sound.rtp_playback import L16PlaybackFrame, StreamId

type PlaybackDevice = int | str | None

type NativeByteOrder = Literal["little", "big"]


class RawOutputStream(Protocol):
    """类契约说明.

    职责: 声明 RawOutputStream
    协议接口,约束实现方必须提供的行为。
    契约: 方法:
    start、write、abort、stop、close。
    """

    def start(self) -> None:
        """函数契约说明.

        功能: 执行 start 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def write(self, data: bytes) -> bool:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 data: bytes。
        必填。
        契约: 同步调用。 返回 `bool`。
        """

        ...

    def abort(self) -> None:
        """函数契约说明.

        功能: 执行 abort 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        ...

    def stop(self) -> None:
        """函数契约说明.

        功能: 执行 stop 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
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


class RawOutputStreamFactory(Protocol):
    """类契约说明.

    职责: 声明 RawOutputStreamFactory
    协议接口,约束实现方必须提供的行为。
    契约: 方法: open。
    """

    def open(
        self,
        *,
        device: PlaybackDevice,
        samplerate: int,
        channels: int,
        dtype: Literal["int16"],
    ) -> RawOutputStream:
        """函数契约说明.

        功能: 执行 open 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 device:
        PlaybackDevice。 必填。 samplerate:
        int。 必填。 channels: int。 必填。
        dtype: Literal['int16']。 必填。
        契约: 同步调用。 返回 `RawOutputStream`。
        """

        ...


@final
class SounddeviceRawOutputStreamFactory:
    """类契约说明.

    职责: 定义
    SounddeviceRawOutputStreamFactory
    的状态、行为和对外协作边界。
    契约: 方法: open。
    """

    def open(
        self,
        *,
        device: PlaybackDevice,
        samplerate: int,
        channels: int,
        dtype: Literal["int16"],
    ) -> RawOutputStream:
        """函数契约说明.

        功能: 执行 open 的同步逻辑,并协调
        RawOutputStream。
        参数: self 表示当前实例。 device:
        PlaybackDevice。 必填。 samplerate:
        int。 必填。 channels: int。 必填。
        dtype: Literal['int16']。 必填。
        契约: 同步调用。 返回 `RawOutputStream`。
        """

        return sounddevice.RawOutputStream(
            device=device,
            samplerate=samplerate,
            channels=channels,
            dtype=dtype,
        )


@final
class PortAudioPlaybackSink:
    """类契约说明.

    职责: 定义 PortAudioPlaybackSink
    的状态、行为和对外协作边界。
    契约: 方法:
    __init__、write、close_stream、close。
    """

    def __init__(
        self,
        *,
        device: PlaybackDevice,
        stream_factory: RawOutputStreamFactory | None = None,
    ) -> None:
        """函数契约说明.

        功能: 初始化 PortAudioPlaybackSink
        的字段并建立实例不变式。
        参数: self 表示当前实例。 device:
        PlaybackDevice。 必填。
        stream_factory:
        RawOutputStreamFactory | None。
        可省略。
        契约: 同步调用。 返回 `None`。
        """

        self._device = device

        self._stream_factory = stream_factory or SounddeviceRawOutputStreamFactory()

        self._streams: dict[StreamId, RawOutputStream] = {}

    def write(self, frame: L16PlaybackFrame) -> None:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并协调 get,
        write, open, start。
        参数: self 表示当前实例。 frame:
        L16PlaybackFrame。 必填。
        契约: 同步调用。 返回 `None`。
        """

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
        """函数契约说明.

        功能: 执行 close_stream 的同步逻辑,并协调
        pop, StreamId, abort, close。
        参数: self 表示当前实例。 stream_id: str。
        必填。
        契约: 同步调用。 返回 `None`。
        """

        stream = self._streams.pop(StreamId(stream_id), None)

        if stream is not None:
            try:
                stream.abort()

            finally:
                stream.close()

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并协调 tuple,
        clear, values, stop。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        streams = tuple(self._streams.values())

        self._streams.clear()

        for stream in streams:
            try:
                stream.stop()

            finally:
                stream.close()


def l16_payload_to_native_int16(payload: bytes, *, byteorder: NativeByteOrder) -> bytes:
    """函数契约说明.

    功能: 执行 l16_payload_to_native_int16
    的同步逻辑,并协调 bytearray, bytes,
    assert_never。
    参数: payload: bytes。 必填。 byteorder:
    NativeByteOrder。 必填。
    契约: 同步调用。 返回 `bytes`。
    """

    match byteorder:
        case "big":
            return payload

        case "little":
            native_payload = bytearray(payload)

            native_payload[0::2] = payload[1::2]

            native_payload[1::2] = payload[0::2]

            return bytes(native_payload)
