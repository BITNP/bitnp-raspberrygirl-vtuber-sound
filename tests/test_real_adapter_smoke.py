import os

import pytest

from sound.portaudio_playback import PortAudioPlaybackSink
from sound.rtp_playback import RtpPlaybackReceiver

PLAYBACK_DEVICE_ENV = "BITNP_PLAYBACK_DEVICE"


@pytest.mark.real_adapter
def test_portaudio_playback_when_explicit_device_is_configured() -> None:
    # Given: an explicit cross-platform PortAudio device query and a real receiver.
    configured = os.environ.get(PLAYBACK_DEVICE_ENV, "").strip()
    if configured == "":
        pytest.skip(f"set {PLAYBACK_DEVICE_ENV} to run PortAudio playback smoke")
    receiver = RtpPlaybackReceiver(playback_sink=PortAudioPlaybackSink(device=configured))
    receiver.announce_stream(stream_id="portaudio-smoke", sample_rate=8_000, channels=1)
    packet = bytes([0x80, 96, 0, 1]) + (0).to_bytes(4, "big") + (7).to_bytes(4, "big") + (b"\x00\x00" * 160)

    # When: a short L16 RTP payload is sent to the configured hardware device.
    receiver.receive_packet(packet, stream_id="portaudio-smoke")
    receiver.close()

    # Then: valid playback reaches the PortAudio boundary and preserves receiver state.
    assert receiver.playback_states[-1].playback_position_samples == 160
