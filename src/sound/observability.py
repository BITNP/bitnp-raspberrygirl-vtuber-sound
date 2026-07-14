from dataclasses import dataclass
from typing import Literal, TypedDict

from sound import __version__
from sound.config import SERVICE_NAME, ServiceConfig


class JsonLogRecord(TypedDict):
    service: str
    service_version: str
    level: Literal["debug", "info", "warning", "error"]
    message: str
    trace_id: str
    session_id: str


@dataclass(frozen=True, slots=True)
class LatencyMetric:
    service: str
    operation: str
    latency_ms: float


@dataclass(frozen=True, slots=True)
class QueueMetric:
    service: str
    queue_name: str
    depth: int


def json_log_record(
    config: ServiceConfig,
    *,
    level: Literal["debug", "info", "warning", "error"],
    message: str,
    trace_id: str,
    session_id: str,
) -> JsonLogRecord:
    _ = config
    return {
        "service": SERVICE_NAME,
        "service_version": __version__,
        "level": level,
        "message": message,
        "trace_id": trace_id,
        "session_id": session_id,
    }


def trace_headers(config: ServiceConfig, *, trace_id: str, session_id: str) -> dict[str, str]:
    _ = config
    return {"x-trace-id": trace_id, "x-session-id": session_id}


def latency_metric(
    config: ServiceConfig,
    *,
    operation: str,
    latency_ms: float,
) -> LatencyMetric:
    _ = config
    return LatencyMetric(service=SERVICE_NAME, operation=operation, latency_ms=latency_ms)


def queue_metric(config: ServiceConfig, *, queue_name: str, depth: int) -> QueueMetric:
    _ = config
    return QueueMetric(service=SERVICE_NAME, queue_name=queue_name, depth=depth)
