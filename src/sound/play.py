"""模块契约说明.

职责: 提供 sound.play 模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import os
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, override

from sound.portaudio_playback import (
    PlaybackDevice,
    PortAudioPlaybackSink,
    RawOutputStreamFactory,
)
from sound.rtp_playback import RtpPlaybackReceiver


class BinaryInput(Protocol):
    """类契约说明.

    职责: 声明 BinaryInput
    协议接口,约束实现方必须提供的行为。
    契约: 方法: read。
    """

    def read(self) -> bytes:
        """函数契约说明.

        功能: 执行 read 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `bytes`。
        """

        ...


@dataclass(frozen=True, slots=True)
class SoundPlayConfiguration:
    """类契约说明.

    职责: 保存 SoundPlayConfiguration
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: device、stream_id、sample_rate
    、channels。
    """

    device: PlaybackDevice

    stream_id: str

    sample_rate: int

    channels: int


@dataclass(frozen=True, slots=True)
class SoundPlayConfigurationError(ValueError):
    """类契约说明.

    职责: 保存 SoundPlayConfigurationError
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: variable、reason。 方法:
    __str__。
    """

    variable: str

    reason: str

    @override
    def __str__(self) -> str:
        """函数契约说明.

        功能: 生成面向日志、错误或调试输出的稳定文本表示。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return f"{self.variable}: {self.reason}"


def main() -> None:
    """函数契约说明.

    功能: 执行命令行或服务入口流程并返回进程级结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    _ = run(input_stream=sys.stdin.buffer, environment=os.environ)


def run(
    *,
    input_stream: BinaryInput,
    environment: Mapping[str, str],
    stream_factory: RawOutputStreamFactory | None = None,
) -> RtpPlaybackReceiver:
    """函数契约说明.

    功能: 运行流程并协调其依赖步骤。
    参数: input_stream: BinaryInput。 必填。
    environment: Mapping[str, str]。 必填。
    stream_factory:
    RawOutputStreamFactory | None。 可省略。
    契约: 同步调用。 返回 `RtpPlaybackReceiver`。
    """

    configuration = _parse_configuration(environment)

    receiver = RtpPlaybackReceiver(
        playback_sink=PortAudioPlaybackSink(
            device=configuration.device,
            stream_factory=stream_factory,
        )
    )

    receiver.announce_stream(
        stream_id=configuration.stream_id,
        sample_rate=configuration.sample_rate,
        channels=configuration.channels,
    )

    try:
        receiver.receive_packet(input_stream.read(), stream_id=configuration.stream_id)

    finally:
        receiver.close()

    return receiver


def _parse_configuration(environment: Mapping[str, str]) -> SoundPlayConfiguration:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: environment: Mapping[str, str]。
    必填。
    契约: 同步调用。 返回
    `SoundPlayConfiguration`。
    """

    return SoundPlayConfiguration(
        device=_playback_device(environment),
        stream_id=_required_value(environment, "BITNP_SOUND_PLAY_STREAM_ID"),
        sample_rate=_positive_integer(environment, "BITNP_SOUND_PLAY_SAMPLE_RATE"),
        channels=_positive_integer(environment, "BITNP_SOUND_PLAY_CHANNELS"),
    )


def _required_value(environment: Mapping[str, str], variable: str) -> str:
    """函数契约说明.

    功能: 执行 _required_value 的同步逻辑,并协调
    strip, SoundPlayConfigurationError,
    get。
    参数: environment: Mapping[str, str]。
    必填。 variable: str。 必填。
    契约: 同步调用。 返回 `str`。 可能抛出
    SoundPlayConfigurationError。
    """

    value = environment.get(variable, "").strip()

    if value == "":
        raise SoundPlayConfigurationError(variable=variable, reason="must be set")

    return value


def _playback_device(environment: Mapping[str, str]) -> PlaybackDevice:
    """函数契约说明.

    功能: 执行 _playback_device 的同步逻辑,并协调
    strip, isdecimal, int, get。
    参数: environment: Mapping[str, str]。
    必填。
    契约: 同步调用。 返回 `PlaybackDevice`。
    """

    value = environment.get("BITNP_PLAYBACK_DEVICE", "").strip()

    if value == "" or value == "default":
        return None

    if value.isdecimal():
        return int(value)

    return value


def _positive_integer(environment: Mapping[str, str], variable: str) -> int:
    """函数契约说明.

    功能: 执行 _positive_integer 的同步逻辑,并协调
    _required_value, int,
    SoundPlayConfigurationError。
    参数: environment: Mapping[str, str]。
    必填。 variable: str。 必填。
    契约: 同步调用。 返回 `int`。 可能抛出
    SoundPlayConfigurationError。
    """

    value = _required_value(environment, variable)

    try:
        parsed_value = int(value)

    except ValueError:
        raise SoundPlayConfigurationError(
            variable=variable, reason="must be an integer"
        ) from None

    if parsed_value <= 0:
        raise SoundPlayConfigurationError(variable=variable, reason="must be positive")

    return parsed_value
