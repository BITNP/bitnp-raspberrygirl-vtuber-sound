
from collections.abc import Mapping

import pytest

from sound.config import ConfigError, load_config


def test_load_config_targets_orchestrator_when_required_url_present() -> None:

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"}

    config = load_config(env)

    assert config.orchestrator_ws_url == "ws://orchestrator.local/ws"


def test_load_config_rejects_peer_endpoint_when_asr_url_is_present() -> None:

    env: Mapping[str, str] = {
        "ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws",
        "ASR_WS_URL": "ws://asr.local/ws",
    }

    with pytest.raises(ConfigError, match="ASR_WS_URL"):
        _ = load_config(env)


def test_load_config_rejects_non_websocket_orchestrator_url() -> None:

    env: Mapping[str, str] = {"ORCHESTRATOR_WS_URL": "http://orchestrator.local/ws"}

    with pytest.raises(ConfigError, match="ORCHESTRATOR_WS_URL"):
        _ = load_config(env)
