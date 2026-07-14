from sound.config import load_config
from sound.orchestrator_ws import OrchestratorWebSocketBoundary


def test_websocket_boundary_targets_only_orchestrator() -> None:
    config = load_config({"ORCHESTRATOR_WS_URL": "wss://orchestrator.local/ws"})

    boundary = OrchestratorWebSocketBoundary(config)

    assert boundary.target_url() == "wss://orchestrator.local/ws"
    assert "Orchestrator" in boundary.describe_placeholder()
