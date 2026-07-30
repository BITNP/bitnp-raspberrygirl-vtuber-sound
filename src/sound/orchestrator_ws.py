"""模块契约说明.

职责: 提供 sound.orchestrator_ws
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

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

type JsonValue = (
    None | bool | int | float | str | list[JsonValue] | dict[str, JsonValue]
)


def parse_event(message: str) -> Mapping[str, JsonValue]:
    """函数契约说明.

    功能: 从边界输入解析类型化值。
    参数: message: str。 必填。
    契约: 同步调用。 返回 `Mapping[str,
    JsonValue]`。 可能抛出 TypeError。
    """

    decoded = _json_value(json.loads(message))

    if not isinstance(decoded, dict):
        raise TypeError("control envelope must be an object")

    return decoded


def _json_value(value: object) -> JsonValue:
    """函数契约说明.

    功能: 从 JSON 解码结果递归收窄为模块内 JsonValue 类型。
    参数: value: object。 必填。
    契约: 同步调用。 返回 `JsonValue`。 可能抛出 TypeError。
    """

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
    """函数契约说明.

    功能: 执行 required_mapping 的同步逻辑,并协调
    get, isinstance, TypeError。
    参数: source: Mapping[str, JsonValue]。
    必填。 field: str。 必填。
    契约: 同步调用。 返回 `Mapping[str,
    JsonValue]`。 可能抛出 TypeError。
    """

    value = source.get(field)

    if not isinstance(value, dict):
        raise TypeError(f"{field} must be an object")

    return value


def required_str(source: Mapping[str, JsonValue], field: str) -> str:
    """函数契约说明.

    功能: 执行 required_str 的同步逻辑,并协调 get,
    ValueError, isinstance。
    参数: source: Mapping[str, JsonValue]。
    必填。 field: str。 必填。
    契约: 同步调用。 返回 `str`。 可能抛出 ValueError。
    """

    value = source.get(field)

    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")

    return value


def optional_str(source: Mapping[str, JsonValue], field: str) -> str | None:
    """函数契约说明.

    功能: 执行 optional_str 的同步逻辑,并协调 get,
    ValueError, isinstance。
    参数: source: Mapping[str, JsonValue]。
    必填。 field: str。 必填。
    契约: 同步调用。 返回 `str | None`。 可能抛出
    ValueError。
    """

    value = source.get(field)

    if value is None:
        return None

    if not isinstance(value, str) or value == "":
        raise ValueError(f"{field} must be a non-empty string")

    return value


def required_int(source: Mapping[str, JsonValue], field: str) -> int:
    """函数契约说明.

    功能: 执行 required_int 的同步逻辑,并协调 get,
    isinstance, TypeError。
    参数: source: Mapping[str, JsonValue]。
    必填。 field: str。 必填。
    契约: 同步调用。 返回 `int`。 可能抛出 TypeError。
    """

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
    """函数契约说明.

    功能: 执行 encode_envelope 的同步逻辑,并协调
    dumps, str, replace, dict。
    参数: event_type: str。 必填。 trace_id:
    str。 必填。 session_id: str。 必填。 seq:
    int。 必填。 data: Mapping[str,
    JsonValue]。 必填。 turn_id: str | None。
    可省略。 segment_id: str | None。 可省略。
    契约: 同步调用。 返回 `str`。
    """

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


@dataclass(frozen=True, slots=True)
class OrchestratorWebSocketBoundary:
    """类契约说明.

    职责: 保存 OrchestratorWebSocketBoundary
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: config。 方法: target_url、descr
    ibe_placeholder、receive_play_command
    、receive_cancel_command、send_sound_e
    vent。
    """

    config: ServiceConfig

    def target_url(self) -> OrchestratorWsUrl:
        """函数契约说明.

        功能: 执行 target_url 的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回
        `OrchestratorWsUrl`。
        """

        return self.config.orchestrator_ws_url

    def describe_placeholder(self) -> str:
        """函数契约说明.

        功能: 执行 describe_placeholder
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        return "sound WebSocket boundary placeholder targets Orchestrator only"

    def receive_play_command(
        self, service: PlaybackService, command: PlaybackCommand
    ) -> None:
        """函数契约说明.

        功能: 执行 receive_play_command
        的同步逻辑,并协调 enqueue。
        参数: self 表示当前实例。 service:
        PlaybackService。 必填。 command:
        PlaybackCommand。 必填。
        契约: 同步调用。 返回 `None`。
        """

        service.enqueue(command)

    def receive_cancel_command(
        self, service: PlaybackService, command: PlaybackCancelCommand
    ) -> None:
        """函数契约说明.

        功能: 执行 receive_cancel_command
        的同步逻辑,并协调 cancel。
        参数: self 表示当前实例。 service:
        PlaybackService。 必填。 command:
        PlaybackCancelCommand。 必填。
        契约: 同步调用。 返回 `None`。
        """

        service.cancel(command)

    def send_sound_event(self, sink: SoundEventSink, event: SoundEvent) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 sink:
        SoundEventSink。 必填。 event:
        SoundEvent。 必填。
        契约: 同步调用。 返回 `None`。
        """

        sink.receive_sound_event(event)
