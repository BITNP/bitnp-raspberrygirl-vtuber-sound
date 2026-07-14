from __future__ import annotations

import os
from pathlib import Path

import pytest

from sound.playback import ManualPlaybackClock, PlaybackService, SoundEvent, parse_play_command

SOUND_DEVICE_ENV = "BITNP_REAL_SOUND_DEVICE_PATH"
FAKE_LOCAL_ENV = "BITNP_REAL_ADAPTER_FAKE_LOCAL"
MALFORMED_ENV = "BITNP_REAL_ADAPTER_MALFORMED_CHECK"


class _RecordingSink:
    def __init__(self) -> None:
        self.events: list[SoundEvent] = []

    def receive_sound_event(self, event: SoundEvent) -> None:
        self.events.append(event)


@pytest.mark.real_adapter
def test_real_sound_device_smoke_when_explicitly_enabled() -> None:
    # Given: either fake local playback or an explicit sound device path.
    _sound_device_or_skip()
    clock = ManualPlaybackClock()
    sink = _RecordingSink()
    service = PlaybackService(clock=clock, sink=sink)

    # When: one short playback command traverses the sound boundary.
    service.enqueue(parse_play_command(_play_envelope()))
    clock.advance(20)
    service.tick()

    # Then: the sound surface reaches a done event without requiring default hardware.
    assert [event.event_type for event in sink.events] == ["sound.queued", "sound.started", "sound.done"]


@pytest.mark.real_adapter
def test_real_sound_device_malformed_path_reports_readiness_error() -> None:
    # Given: malformed endpoint checking is explicitly enabled.
    if os.environ.get(MALFORMED_ENV) != "1":
        pytest.skip(f"set {MALFORMED_ENV}=1 to run malformed sound device smoke")

    # When / Then: a missing sound device path is reported as a readiness failure.
    with pytest.raises(FileNotFoundError, match="sound device readiness failed"):
        _require_sound_device(Path("/tmp/bitnp-missing-sound-device"))


def _sound_device_or_skip() -> None:
    if os.environ.get(FAKE_LOCAL_ENV) == "1":
        return
    configured = os.environ.get(SOUND_DEVICE_ENV, "").strip()
    if configured == "":
        pytest.skip(f"set {SOUND_DEVICE_ENV} or {FAKE_LOCAL_ENV}=1 to run real sound device smoke")
    _require_sound_device(Path(configured))


def _require_sound_device(path: Path) -> None:
    if not path.exists():
        raise FileNotFoundError(f"sound device readiness failed: {path}")


def _play_envelope() -> dict[str, object]:
    return {
        "source": "orchestrator",
        "event_type": "sound.play.command",
        "segment_id": "seg-sound-smoke",
        "data": {
            "command_id": "sound-smoke-001",
            "uri": "segment://seg-sound-smoke",
            "audio": {
                "sample_rate": 24000,
                "channels": 1,
                "codec": "pcm_s16le",
                "duration_ms": 20,
                "byte_length": 960,
            },
        },
    }
