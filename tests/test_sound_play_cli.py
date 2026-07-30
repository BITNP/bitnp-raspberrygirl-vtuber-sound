"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

from sound.play import run
from sound.portaudio_playback import PlaybackDevice


@dataclass
class _RecordingRawOutputStream:
    """类契约说明.

    职责: 保存 _RecordingRawOutputStream
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    writes、started、stopped、closed。 方法:
    start、write、abort、stop、close。
    """

    writes: list[bytes] = field(default_factory=list)

    started: bool = False

    stopped: bool = False

    closed: bool = False

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

        self.writes.append(data)

        return False

    def abort(self) -> None:
        """函数契约说明.

        功能: 执行 abort 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        return

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


@dataclass
class _RecordingFactory:
    """类契约说明.

    职责: 保存 _RecordingFactory
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: stream、configurations。 方法:
    open。
    """

    stream: _RecordingRawOutputStream = field(default_factory=_RecordingRawOutputStream)

    configurations: list[tuple[PlaybackDevice, int, int, Literal["int16"]]] = field(
        default_factory=list
    )

    def open(
        self,
        *,
        device: PlaybackDevice,
        samplerate: int,
        channels: int,
        dtype: Literal["int16"],
    ) -> _RecordingRawOutputStream:
        """函数契约说明.

        功能: 执行 open 的同步逻辑,并协调 append。
        参数: self 表示当前实例。 device:
        PlaybackDevice。 必填。 samplerate:
        int。 必填。 channels: int。 必填。
        dtype: Literal['int16']。 必填。
        契约: 同步调用。 返回
        `_RecordingRawOutputStream`。
        """

        self.configurations.append((device, samplerate, channels, dtype))

        return self.stream


def test_sound_play_composes_default_portaudio_device_without_hardware() -> None:
    # Given: one RTP packet and no explicit playback-device selection.

    """函数契约说明.

    功能: 验证 sound play composes default
    portaudio device without hardware
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    payload = b"\x00\x01\xff\xfe" + bytes(636)

    packet = (
        bytes([0x80, 96, 0, 1])
        + (960).to_bytes(4, "big")
        + (7).to_bytes(4, "big")
        + payload
    )

    environment = {
        "BITNP_SOUND_PLAY_STREAM_ID": "cli-stream",
        "BITNP_SOUND_PLAY_SAMPLE_RATE": "48000",
        "BITNP_SOUND_PLAY_CHANNELS": "1",
    }

    factory = _RecordingFactory()

    # When: the composition root reads the packet through an injected factory.

    receiver = run(
        input_stream=BytesIO(packet), environment=environment, stream_factory=factory
    )

    # Then: it uses the default output device and closes normal playback without hardware.

    assert factory.configurations == [(None, 48_000, 1, "int16")]

    assert factory.stream.started is True

    assert factory.stream.stopped is True

    assert factory.stream.closed is True

    assert receiver.playback_states[-1].playback_position_samples == 320


def test_playback_device_parser_maps_default_literal_to_portaudio_default() -> None:
    # Given: the portable default-device literal from runtime configuration.

    """函数契约说明.

    功能: 验证 playback device parser maps
    default literal to portaudio default
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    environment = {"BITNP_PLAYBACK_DEVICE": "default"}

    packet = (
        bytes([0x80, 96, 0, 1])
        + (0).to_bytes(4, "big")
        + (7).to_bytes(4, "big")
        + b"\x00\x01"
        + bytes(638)
    )

    factory = _RecordingFactory()

    # When: the public CLI composition resolves the default device literal.

    _ = run(
        input_stream=BytesIO(packet),
        environment={
            **environment,
            "BITNP_SOUND_PLAY_STREAM_ID": "default-device",
            "BITNP_SOUND_PLAY_SAMPLE_RATE": "48000",
            "BITNP_SOUND_PLAY_CHANNELS": "1",
        },
        stream_factory=factory,
    )

    # Then: PortAudio receives None to select its platform default output.

    assert factory.configurations == [(None, 48_000, 1, "int16")]


def test_sound_play_passes_numeric_and_named_playback_device_selections_to_portaudio() -> (
    None
):
    # Given: numeric and named neutral PortAudio device queries.

    """函数契约说明.

    功能: 验证 sound play passes numeric and
    named playback device selections to
    portaudio 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    packet = (
        bytes([0x80, 96, 0, 1])
        + (0).to_bytes(4, "big")
        + (7).to_bytes(4, "big")
        + b"\x00\x01"
        + bytes(638)
    )

    # When: the CLI composition runs with each selection.

    numeric_factory = _RecordingFactory()

    named_factory = _RecordingFactory()

    _ = run(
        input_stream=BytesIO(packet),
        environment={
            "BITNP_PLAYBACK_DEVICE": "3",
            "BITNP_SOUND_PLAY_STREAM_ID": "numeric-device",
            "BITNP_SOUND_PLAY_SAMPLE_RATE": "48000",
            "BITNP_SOUND_PLAY_CHANNELS": "1",
        },
        stream_factory=numeric_factory,
    )

    _ = run(
        input_stream=BytesIO(packet),
        environment={
            "BITNP_PLAYBACK_DEVICE": "room speakers",
            "BITNP_SOUND_PLAY_STREAM_ID": "named-device",
            "BITNP_SOUND_PLAY_SAMPLE_RATE": "48000",
            "BITNP_SOUND_PLAY_CHANNELS": "1",
        },
        stream_factory=named_factory,
    )

    # Then: PortAudio receives an index or name query rather than platform-specific syntax.

    assert numeric_factory.configurations[0][0] == 3

    assert named_factory.configurations[0][0] == "room speakers"
