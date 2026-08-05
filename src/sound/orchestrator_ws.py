
import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from uuid import uuid4

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


def parse_event(message: str) -> Mapping[str, JsonValue]:
    if len(message.encode("utf-8")) > 64 * 1024:
        raise ValueError("control frame exceeds 64 KiB")
    decoded = _json_value(
        json.loads(
            message,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    )

    if not isinstance(decoded, dict):
        raise TypeError("control envelope must be an object")

    _validate_depth(decoded, 0)
    _validate_envelope(decoded)
    return decoded


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite number: {value}")


def _validate_depth(value: JsonValue, depth: int) -> None:
    if depth > 32:
        raise ValueError("control envelope nesting exceeds 32")
    if isinstance(value, dict):
        for child in value.values():
            _validate_depth(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            _validate_depth(child, depth + 1)


def _validate_envelope(event: dict[str, JsonValue]) -> None:
    required = {
        "schema_version",
        "event_type",
        "event_id",
        "source",
        "time",
        "trace_id",
        "session_id",
        "seq",
        "data",
    }
    if not required.issubset(event) or set(event) - (
        required | {"turn_id", "segment_id", "traceparent"}
    ):
        raise ValueError("control envelope fields are not canonical")
    if event["schema_version"] != "1.0.0" or event["source"] not in {
        "orchestrator",
        "sound",
    }:
        raise ValueError("unsupported control envelope identity")
    session_id = event["session_id"]
    if (
        not isinstance(session_id, str)
        or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", session_id) is None
    ):
        raise ValueError("invalid session_id")
    sequence = event["seq"]
    if type(sequence) is not int or sequence < 0:
        raise ValueError("invalid seq")
    data = event["data"]
    if not isinstance(data, dict):
        raise TypeError("data must be an object")
    event_type = event["event_type"]
    if not isinstance(event_type, str):
        raise TypeError("event_type must be a string")
    inbound_expected = {
        "media.stream.command": {
            "command_id",
            "stream_id",
            "start_rtp_timestamp",
            "ssrc",
            "codec",
            "cancellation_epoch",
            "rtp_sender_endpoint",
        },
        "media.stream.end": {
            "command_id",
            "stream_id",
            "cancellation_epoch",
            "ssrc",
        },
        "media.stream.flush": {
            "stream_id",
            "cancellation_epoch",
            "request_id",
            "target_generated_ssrc",
        },
        "cancel": {"reason"},
    }
    outbound_expected = {
        "media.rtp.sink.register": {"stream_id", "codec", "rtp_endpoint"},
        "media.rtp.sink.ready": {"stream_id"},
        "media.stream.state": {
            "command_id",
            "stream_id",
            "state",
            "cancellation_epoch",
        },
        "media.stream.flush.ack": {
            "stream_id",
            "cancellation_epoch",
            "request_id",
            "target_generated_ssrc",
            "disposition",
        },
    }
    expected = (
        inbound_expected.get(event_type)
        if event["source"] == "orchestrator"
        else outbound_expected.get(event_type)
    )
    if expected is None or set(data) != expected:
        raise ValueError("unsupported or noncanonical event data")


def _json_value(value: object) -> JsonValue:

    if value is None or isinstance(value, bool | int | str):
        return value

    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("control envelope contains a non-finite number")
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
