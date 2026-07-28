import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from sound.config import OrchestratorWsUrl, ServiceConfig
from sound.playback import (
    PlaybackCancelCommand,
    PlaybackCommand,
    PlaybackService,
    SoundEvent,
    SoundEventSink,
)

type JsonValue = None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]


def parse_event(message: str) -> Mapping[str, JsonValue]:
    decoded: JsonValue = json.loads(message)
    if not isinstance(decoded, dict):
        raise TypeError("control envelope must be an object")
    return decoded


def required_mapping(source: Mapping[str, JsonValue], field: str) -> Mapping[str, JsonValue]:
    value = source.get(field)
    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object")
    return value


def required_str(source: Mapping[str, JsonValue], field: str) -> str:
    value = source.get(field)
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")
    return value


def optional_str(source: Mapping[str, JsonValue], field: str) -> str | None:
    value = source.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")
    return value


def required_int(source: Mapping[str, JsonValue], field: str) -> int:
    value = source.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError(f"{field} must be an integer")
    return value


def encode_envelope(
    *,
    event_type: str,
    trace_id: str,
    session_id: str,
    data: Mapping[str, JsonValue],
    turn_id: str | None = None,
    segment_id: str | None = None,
) -> str:
    envelope: dict[str, JsonValue] = {
        "schema_version": "1.0.0",
        "event_type": event_type,
        "event_id": str(uuid4()),
        "source": "sound",
        "time": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "trace_id": trace_id,
        "session_id": session_id,
        "seq": 0,
        "data": dict(data),
    }
    if turn_id is not None:
        envelope["turn_id"] = turn_id
    if segment_id is not None:
        envelope["segment_id"] = segment_id
    return json.dumps(envelope, separators=(",", ":"))


@dataclass(frozen=True, slots=True)
class OrchestratorWebSocketBoundary:
    config: ServiceConfig

    def target_url(self) -> OrchestratorWsUrl:
        return self.config.orchestrator_ws_url

    def describe_placeholder(self) -> str:
        return "sound WebSocket boundary placeholder targets Orchestrator only"

    def receive_play_command(self, service: PlaybackService, command: PlaybackCommand) -> None:
        service.enqueue(command)

    def receive_cancel_command(self, service: PlaybackService, command: PlaybackCancelCommand) -> None:
        service.cancel(command)

    def send_sound_event(self, sink: SoundEventSink, event: SoundEvent) -> None:
        sink.receive_sound_event(event)
