
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


def parse_event(message: str) -> Mapping[str, JsonValue]:

    decoded = _json_value(json.loads(message))

    if not isinstance(decoded, dict):
        raise TypeError("control envelope must be an object")

    return decoded


def _json_value(value: object) -> JsonValue:

    if value is None or isinstance(value, bool | int | float | str):
        return value

    if isinstance(value, list):
        return [_json_value(item) for item in value]

    if isinstance(value, dict):
        parsed: dict[str, JsonValue] = {}

        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("control envelope keys must be strings")

            parsed[key] = _json_value(item)

        return parsed

    raise TypeError("control envelope contains unsupported JSON value")


def required_mapping(
    source: Mapping[str, JsonValue], field: str
) -> Mapping[str, JsonValue]:

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
    seq: int,
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
        "seq": seq,
        "data": dict(data),
    }

    if turn_id is not None:
        envelope["turn_id"] = turn_id

    if segment_id is not None:
        envelope["segment_id"] = segment_id

    return json.dumps(envelope, separators=(",", ":"))
