"""模块契约说明.

职责: 提供 sound.observability
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from dataclasses import dataclass
from typing import Literal, TypedDict

from sound import __version__
from sound.config import SERVICE_NAME, ServiceConfig


class JsonLogRecord(TypedDict):
    """类契约说明.

    职责: 定义 JsonLogRecord 的状态、行为和对外协作边界。
    契约: 字段: service、service_version、leve
    l、message、trace_id、session_id。
    """

    service: str

    service_version: str

    level: Literal["debug", "info", "warning", "error"]

    message: str

    trace_id: str

    session_id: str


@dataclass(frozen=True, slots=True)
class LatencyMetric:
    """类契约说明.

    职责: 保存 LatencyMetric
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    service、operation、latency_ms。
    """

    service: str

    operation: str

    latency_ms: float


@dataclass(frozen=True, slots=True)
class QueueMetric:
    """类契约说明.

    职责: 保存 QueueMetric
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: service、queue_name、depth。
    """

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
    """函数契约说明.

    功能: 执行 json_log_record 的同步逻辑,并产出 _。
    参数: config: ServiceConfig。 必填。
    level: Literal['debug', 'info',
    'warning', 'error']。 必填。 message:
    str。 必填。 trace_id: str。 必填。
    session_id: str。 必填。
    契约: 同步调用。 返回 `JsonLogRecord`。
    """

    _ = config

    return {
        "service": SERVICE_NAME,
        "service_version": __version__,
        "level": level,
        "message": message,
        "trace_id": trace_id,
        "session_id": session_id,
    }


def trace_headers(
    config: ServiceConfig, *, trace_id: str, session_id: str
) -> dict[str, str]:
    """函数契约说明.

    功能: 执行 trace_headers 的同步逻辑,并产出 _。
    参数: config: ServiceConfig。 必填。
    trace_id: str。 必填。 session_id: str。
    必填。
    契约: 同步调用。 返回 `dict[str, str]`。
    """

    _ = config

    return {"x-trace-id": trace_id, "x-session-id": session_id}


def latency_metric(
    config: ServiceConfig,
    *,
    operation: str,
    latency_ms: float,
) -> LatencyMetric:
    """函数契约说明.

    功能: 执行 latency_metric 的同步逻辑,并协调
    LatencyMetric。
    参数: config: ServiceConfig。 必填。
    operation: str。 必填。 latency_ms:
    float。 必填。
    契约: 同步调用。 返回 `LatencyMetric`。
    """

    _ = config

    return LatencyMetric(
        service=SERVICE_NAME, operation=operation, latency_ms=latency_ms
    )


def queue_metric(config: ServiceConfig, *, queue_name: str, depth: int) -> QueueMetric:
    """函数契约说明.

    功能: 执行 queue_metric 的同步逻辑,并协调
    QueueMetric。
    参数: config: ServiceConfig。 必填。
    queue_name: str。 必填。 depth: int。 必填。
    契约: 同步调用。 返回 `QueueMetric`。
    """

    _ = config

    return QueueMetric(service=SERVICE_NAME, queue_name=queue_name, depth=depth)
