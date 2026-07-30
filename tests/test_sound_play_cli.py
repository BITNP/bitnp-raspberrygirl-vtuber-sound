from dataclasses import dataclass, field
from io import BytesIO
from typing import Literal

from sound.play import _playback_device, run
from sound.portaudio_playback import PlaybackDevice


@dataclass
class _RecordingRawOutputStream:
    writes: list[bytes] = field(default_factory=list)
    started: bool = False
    stopped: bool = False
    closed: bool = False

    def start(self) -> None:
        self.started = True

    def write(self, data: bytes) -> bool:
        self.writes.append(data)
        return False

    def abort(self) -> None:
        return None

    def stop(self) -> None:
        self.stopped = True

    def close(self) -> None:
        self.closed = True


@dataclass
class _RecordingFactory:
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
        self.configurations.append((device, samplerate, channels, dtype))
        return self.stream


def test_sound_play_composes_default_portaudio_device_without_hardware() -> None:
    # Given: one RTP packet and no explicit playback-device selection.
    payload = b"\x00\x01\xff\xfe" + bytes(636)
    packet = bytes([0x80, 96, 0, 1]) + (960).to_bytes(4, "big") + (7).to_bytes(4, "big") + payload
    environment = {
        "BITNP_SOUND_PLAY_STREAM_ID": "cli-stream",
        "BITNP_SOUND_PLAY_SAMPLE_RATE": "48000",
        "BITNP_SOUND_PLAY_CHANNELS": "1",
    }
    factory = _RecordingFactory()

    # When: the composition root reads the packet through an injected factory.
    receiver = run(input_stream=BytesIO(packet), environment=environment, stream_factory=factory)

    # Then: it uses the default output device and closes normal playback without hardware.
    assert factory.configurations == [(None, 48_000, 1, "int16")]
    assert factory.stream.started is True
    assert factory.stream.stopped is True
    assert factory.stream.closed is True
    assert receiver.playback_states[-1].playback_position_samples == 320


def test_playback_device_parser_maps_default_literal_to_portaudio_default() -> None:
    # Given: the portable default-device literal from runtime configuration.
    environment = {"BITNP_PLAYBACK_DEVICE": "default"}

    # When: the sound-play configuration parser resolves the device.
    device = _playback_device(environment)

    # Then: PortAudio receives None to select its platform default output.
    assert device is None


def test_sound_play_passes_numeric_and_named_playback_device_selections_to_portaudio() -> None:
    # Given: numeric and named neutral PortAudio device queries.
    packet = bytes([0x80, 96, 0, 1]) + (0).to_bytes(4, "big") + (7).to_bytes(4, "big") + b"\x00\x01" + bytes(638)

    # When: the CLI composition runs with each selection.
    numeric_factory = _RecordingFactory()
    named_factory = _RecordingFactory()
    run(
        input_stream=BytesIO(packet),
        environment={
            "BITNP_PLAYBACK_DEVICE": "3",
            "BITNP_SOUND_PLAY_STREAM_ID": "numeric-device",
            "BITNP_SOUND_PLAY_SAMPLE_RATE": "48000",
            "BITNP_SOUND_PLAY_CHANNELS": "1",
        },
        stream_factory=numeric_factory,
    )
    run(
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
