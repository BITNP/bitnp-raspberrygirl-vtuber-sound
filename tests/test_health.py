
from sound.config import load_config
from sound.health import health_status


def test_health_status_reports_ready_service() -> None:

    config = load_config({"ORCHESTRATOR_WS_URL": "ws://orchestrator.local/ws"})

    status = health_status(config)

    assert status.service == "sound"

    assert status.status == "ready"

    assert status.orchestrator_ws_url == "ws://orchestrator.local/ws"
