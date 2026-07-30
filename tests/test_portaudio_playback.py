"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

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
    """类契约说明.

    职责: 保存 _RecordingRawOutputStream
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: writes、started、aborted、stopp
    ed、closed、fail_writes。 方法:
    start、write、abort、stop、close。
    """

    writes: list[bytes] = field(default_factory=list)

    started: bool = False

    aborted: bool = False

    stopped: bool = False

    closed: bool = False

    fail_writes: bool = False

    def start(self) -> None:
        """函数契约说明.

        功能: 执行 start 的同步逻辑,并产出 started。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.started = True

    def write(self, data: bytes) -> bool:
        """函数契约说明.

        功能: 执行 write 的同步逻辑,并协调 append。
        参数: self 表示当前实例。 data: bytes。
        必填。
        契约: 同步调用。 返回 `bool`。
        """

        if self.fail_writes:
            raise _StreamWriteFailure

        self.writes.append(data)

        return False

    def abort(self) -> None:
        """函数契约说明.

        功能: 执行 abort 的同步逻辑,并产出 aborted。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.aborted = True

    def stop(self) -> None:
        """函数契约说明.

        功能: 执行 stop 的同步逻辑,并产出 stopped。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.stopped = True

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并产出 closed。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self.closed = True


class _StreamWriteFailure(RuntimeError):
    """类契约说明.

    职责: 定义 _StreamWriteFailure
    的状态、行为和对外协作边界。
    契约: 字段、不变式和资源归属由类体声明与类型标注共同约束。
    """



@dataclass
class _RecordingRawOutputStreamFactory:
    """类契约说明.

    职责: 保存
    _RecordingRawOutputStreamFactory
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: configurations、streams、prepa
    red_streams。 方法: open。
    """

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
        """函数契约说明.

        功能: 执行 open 的同步逻辑,并协调 append,
        pop, _RecordingRawOutputStream。
        参数: self 表示当前实例。 device:
        PlaybackDevice。 必填。 samplerate:
        int。 必填。 channels: int。 必填。
        dtype: Literal['int16']。 必填。
        契约: 同步调用。 返回
        `_RecordingRawOutputStream`。
        """

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
    """函数契约说明.

    功能: 执行 _frame 的同步逻辑,并协调
    L16PlaybackFrame, StreamId。
    参数: stream_id: str。 可省略。
    sample_rate: int。 可省略。 channels:
    int。 可省略。
    契约: 同步调用。 返回 `L16PlaybackFrame`。
    """

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

    """函数契约说明.

    功能: 验证 l16 payload converts to
    device native int16 for each
    byteorder 的回归场景和可观察结果。
    参数: byteorder: Literal['little',
    'big']。 必填。 expected: bytes。 必填。
    契约: 同步调用。 返回 `None`。
    """

    payload = b"\x00\x01\xff\xfe"

    # When: the output boundary selects a device byte order.

    native_payload = l16_payload_to_native_int16(payload, byteorder=byteorder)

    # Then: each int16 sample preserves its value in the requested native order.

    assert native_payload == expected


def test_portaudio_sink_starts_one_typed_stream_per_stream_id() -> None:
    # Given: two announced streams with distinct output formats.

    """函数契约说明.

    功能: 验证 portaudio sink starts one
    typed stream per stream id
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

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

    """函数契约说明.

    功能: 验证 portaudio sink aborts and
    closes cancelled streams but stops
    normal streams 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

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

    """函数契约说明.

    功能: 验证 receiver does not advance
    state when portaudio write fails
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

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
