
import json
from dataclasses import dataclass
from typing import Literal

from sound import __version__
from sound.config import SERVICE_NAME, OrchestratorWsUrl, ServiceConfig, load_config


@dataclass(frozen=True, slots=True)
class HealthStatus:

    service: str

    service_version: str

    status: Literal["ready"]

    orchestrator_ws_url: OrchestratorWsUrl

    def to_json(self) -> str:

        payload: dict[str, str] = {
            "service": self.service,
            "service_version": self.service_version,
            "status": self.status,
            "orchestrator_ws_url": self.orchestrator_ws_url,
        }

        return json.dumps(payload, sort_keys=True)


def health_status(config: ServiceConfig) -> HealthStatus:

    return HealthStatus(
        service=SERVICE_NAME,
        service_version=__version__,
        status="ready",
        orchestrator_ws_url=config.orchestrator_ws_url,
    )


def main() -> int:

    print(health_status(load_config()).to_json())

    return 0
