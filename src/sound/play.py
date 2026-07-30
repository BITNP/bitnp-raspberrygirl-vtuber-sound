
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

    def read(self) -> bytes:

        ...


@dataclass(frozen=True, slots=True)
class SoundPlayConfiguration:

    device: PlaybackDevice

    stream_id: str

    sample_rate: int

    channels: int


@dataclass(frozen=True, slots=True)
class SoundPlayConfigurationError(ValueError):

    variable: str

    reason: str

    @override
    def __str__(self) -> str:

        return f"{self.variable}: {self.reason}"


def main() -> None:

    _ = run(input_stream=sys.stdin.buffer, environment=os.environ)


def run(
    *,
    input_stream: BinaryInput,
    environment: Mapping[str, str],
    stream_factory: RawOutputStreamFactory | None = None,
) -> RtpPlaybackReceiver:

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

    return SoundPlayConfiguration(
        device=_playback_device(environment),
        stream_id=_required_value(environment, "BITNP_SOUND_PLAY_STREAM_ID"),
        sample_rate=_positive_integer(environment, "BITNP_SOUND_PLAY_SAMPLE_RATE"),
        channels=_positive_integer(environment, "BITNP_SOUND_PLAY_CHANNELS"),
    )


def _required_value(environment: Mapping[str, str], variable: str) -> str:

    value = environment.get(variable, "").strip()

    if value == "":
        raise SoundPlayConfigurationError(variable=variable, reason="must be set")

    return value


def _playback_device(environment: Mapping[str, str]) -> PlaybackDevice:

    value = environment.get("BITNP_PLAYBACK_DEVICE", "").strip()

    if value == "" or value == "default":
        return None

    if value.isdecimal():
        return int(value)

    return value


def _positive_integer(environment: Mapping[str, str], variable: str) -> int:

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
