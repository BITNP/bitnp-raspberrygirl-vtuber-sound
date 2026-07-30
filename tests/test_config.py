"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from collections.abc import Mapping

import pytest

from sound.config import ConfigError, load_config


def test_load_config_targets_orchestrator_when_required_url_present() -> None:
    """函数契约说明.

    功能: 验证 load config targets
    orchestrator when required url
    present 的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}

    config = load_config(env)

    assert config.orchestrator_ws_url == "ws://orchestrator.local/ws"


def test_load_config_rejects_peer_endpoint_when_asr_url_is_present() -> None:
    """函数契约说明.

    功能: 验证 load config rejects peer
    endpoint when asr url is present
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    env: Mapping[str, str] = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "ASR_WS_URL": "ws://asr.local/ws",
    }

    with pytest.raises(ConfigError, match="ASR_WS_URL"):
        _ = load_config(env)


def test_load_config_rejects_non_websocket_orchestrator_url() -> None:
    """函数契约说明.

    功能: 验证 load config rejects non
    websocket orchestrator url
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `None`。
    """

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "http://orchestrator.local/ws"}

    with pytest.raises(ConfigError, match="ORCHESTRATOR_WS_URL"):
        _ = load_config(env)
