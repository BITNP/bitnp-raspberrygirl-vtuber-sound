"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from sound.config import load_config
from sound.health import health_status


def test_health_status_reports_ready_service() -> None:
    """函数契约说明.

    功能: 验证 health status reports ready
    service 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    config = load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"})

    status = health_status(config)

    assert status.service == "sound"

    assert status.status == "ready"

    assert status.orchestrator_ws_url == "ws://orchestrator.local/ws"
