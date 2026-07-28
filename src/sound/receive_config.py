import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from sound.config import ConfigError, load_config
from sound.portaudio_playback import PlaybackDevice


@dataclass(frozen=True, slots=True)
class SoundReceiveConfig:
    orchestrator_ws_url: str
    trusted_lan_token: str | None
    stream_id: str
    rtp_host: str
    rtp_port: int
    advertised_rtp_host: str
    trace_id: str = "sound-receive"
    session_id: str = "sound-receive"
    playback_device: PlaybackDevice = None


def load_runtime_config(env: Mapping[str, str] | None = None) -> SoundReceiveConfig:
    source = os.environ if env is None else env
    service_config = load_config(source)
    parsed_url = urlparse(service_config.orchestrator_ws_url)
    loopback_ws = (
        parsed_url.scheme == "ws"
        and (parsed_url.hostname or "").lower() in {"127.0.0.1", "::1", "localhost"}
        and source.get("SOUND_ALLOW_LOOPBACK_WS", "false").strip().lower() == "true"
    )
    if parsed_url.scheme != "wss" and not loopback_ws:
        raise ConfigError(
            key="ORCHESTRATOR_WS_URL",
            reason="must use WSS outside explicit loopback test mode",
        )
    if parsed_url.scheme == "wss" and service_config.trusted_lan_token is None:
        raise ConfigError(key="TRUSTED_LAN_TOKEN", reason="must be set for sound-receive")
    return SoundReceiveConfig(
        orchestrator_ws_url=service_config.orchestrator_ws_url,
        trusted_lan_token=service_config.trusted_lan_token,
        stream_id=_required_value(source, "SOUND_RTP_STREAM_ID"),
        rtp_host=source.get("SOUND_RTP_BIND_HOST", "0.0.0.0").strip(),
        rtp_port=_port(source.get("SOUND_RTP_BIND_PORT")),
        advertised_rtp_host=_required_value(source, "SOUND_RTP_ADVERTISED_HOST"),
        trace_id=source.get("SOUND_TRACE_ID", "sound-receive").strip(),
        session_id=source.get("SOUND_SESSION_ID", "sound-receive").strip(),
        playback_device=_playback_device(source),
    )


def _required_value(source: Mapping[str, str], key: str) -> str:
    value = source.get(key, "").strip()
    if value == "":
        raise ConfigError(key=key, reason="must be set")
    return value


def _port(raw_port: str | None) -> int:
    if raw_port is None:
        raise ConfigError(key="SOUND_RTP_BIND_PORT", reason="must be set")
    try:
        port = int(raw_port)
    except ValueError as exc:
        raise ConfigError(key="SOUND_RTP_BIND_PORT", reason="must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise ConfigError(key="SOUND_RTP_BIND_PORT", reason="must be between 1 and 65535")
    return port


def _playback_device(source: Mapping[str, str]) -> PlaybackDevice:
    value = source.get("BITNP_PLAYBACK_DEVICE", "").strip()
    if value == "" or value == "default":
        return None
    if value.isdecimal():
        return int(value)
    return value
