import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, NewType
from urllib.parse import urlparse

HealthHost = NewType("HealthHost", str)
HealthPort = NewType("HealthPort", int)
OrchestratorWsUrl = NewType("OrchestratorWsUrl", str)
TrustedLanToken = NewType("TrustedLanToken", str)

SERVICE_NAME: Final = "sound"
ORCHESTRATOR_WS_URL_KEY: Final = "ORCHESTRATOR_WS_URL"
HEALTH_HOST_KEY: Final = "SERVICE_HEALTH_HOST"
HEALTH_PORT_KEY: Final = "SERVICE_HEALTH_PORT"
TRUSTED_LAN_TOKEN_KEY: Final = "TRUSTED_LAN_TOKEN"
PEER_WS_URL_KEYS: Final = (
    "MIC_WS_URL",
    "ASR_WS_URL",
    "COMMENTS_WS_URL",
    "TTS_WS_URL",
    "SOUND_WS_URL",
)
DEFAULT_HEALTH_HOST: Final = HealthHost("127.0.0.1")
DEFAULT_HEALTH_PORT: Final = HealthPort(8050)


@dataclass(frozen=True, slots=True)
class ConfigError(Exception):
    key: str
    reason: str

    def __str__(self) -> str:
        return f"{self.key}: {self.reason}"


@dataclass(frozen=True, slots=True)
class ServiceConfig:
    orchestrator_ws_url: OrchestratorWsUrl
    health_host: HealthHost = DEFAULT_HEALTH_HOST
    health_port: HealthPort = DEFAULT_HEALTH_PORT
    trusted_lan_token: TrustedLanToken | None = None


def load_config(env: Mapping[str, str] | None = None) -> ServiceConfig:
    source = os.environ if env is None else env
    _reject_peer_urls(source)
    raw_url = source.get(ORCHESTRATOR_WS_URL_KEY, "").strip()
    return ServiceConfig(
        orchestrator_ws_url=_parse_orchestrator_ws_url(raw_url),
        health_host=HealthHost(source.get(HEALTH_HOST_KEY, DEFAULT_HEALTH_HOST).strip()),
        health_port=_parse_health_port(source.get(HEALTH_PORT_KEY)),
        trusted_lan_token=_parse_trusted_lan_token(source.get(TRUSTED_LAN_TOKEN_KEY)),
    )


def _reject_peer_urls(env: Mapping[str, str]) -> None:
    for key in PEER_WS_URL_KEYS:
        if env.get(key, "").strip():
            raise ConfigError(key=key, reason="peer service WebSocket URLs are forbidden")


def _parse_orchestrator_ws_url(raw_url: str) -> OrchestratorWsUrl:
    parsed = urlparse(raw_url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc:
        raise ConfigError(
            key=ORCHESTRATOR_WS_URL_KEY,
            reason="must be a ws:// or wss:// URL with a host",
        )
    return OrchestratorWsUrl(raw_url)


def _parse_health_port(raw_port: str | None) -> HealthPort:
    if raw_port is None or raw_port.strip() == "":
        return DEFAULT_HEALTH_PORT
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ConfigError(key=HEALTH_PORT_KEY, reason="must be an integer") from exc
    if not 1 <= port <= 65535:
        raise ConfigError(key=HEALTH_PORT_KEY, reason="must be between 1 and 65535")
    return HealthPort(port)


def _parse_trusted_lan_token(raw_token: str | None) -> TrustedLanToken | None:
    if raw_token is None or raw_token.strip() == "":
        return None
    return TrustedLanToken(raw_token.strip())
