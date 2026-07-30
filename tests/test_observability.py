"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from sound.config import load_config
from sound.observability import latency_metric, queue_metric, trace_headers
from sound.security import trusted_lan_auth_header, trusted_lan_token_is_valid


def test_observability_helpers_emit_traceable_metrics() -> None:
    """函数契约说明.

    功能: 验证 observability helpers emit
    traceable metrics 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    config = load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"})

    headers = trace_headers(config, trace_id="trace-001", session_id="session-001")

    latency = latency_metric(config, operation="playback", latency_ms=9.5)

    queue = queue_metric(config, queue_name="sound_chunks", depth=5)

    assert headers == {"x-trace-id": "trace-001", "x-session-id": "session-001"}

    assert latency.service == "sound"

    assert latency.operation == "playback"

    assert latency.latency_ms == 9.5

    assert queue.service == "sound"

    assert queue.queue_name == "sound_chunks"

    assert queue.depth == 5


def test_trusted_lan_token_header_is_optional_and_validated() -> None:
    """函数契约说明.

    功能: 验证 trusted lan token header is
    optional and validated 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    config = load_config(
        {
            "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
            "TRUSTED_LAN_TOKEN": "placeholder-token-123",
        },
    )

    assert trusted_lan_auth_header(config) == {
        "authorization": "Bearer placeholder-token-123"
    }

    assert trusted_lan_token_is_valid(config, "Bearer placeholder-token-123")

    assert not trusted_lan_token_is_valid(config, "Bearer wrong-token")
