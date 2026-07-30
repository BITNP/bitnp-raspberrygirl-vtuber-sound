"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from sound.config import load_config
from sound.orchestrator_ws import OrchestratorWebSocketBoundary


def test_websocket_boundary_targets_only_orchestrator() -> None:
    """函数契约说明.

    功能: 验证 websocket boundary targets
    only orchestrator 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    config = load_config({"ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws"})

    boundary = OrchestratorWebSocketBoundary(config)

    assert boundary.target_url() == "wss://orchestrator.local/ws"

    assert "Orchestrator" in boundary.describe_placeholder()
