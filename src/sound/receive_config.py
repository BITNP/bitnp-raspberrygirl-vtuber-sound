"""模块契约说明.

职责: 提供 sound.receive_config
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

from sound.config import ConfigError, load_config
from sound.portaudio_playback import PlaybackDevice


@dataclass(frozen=True, slots=True)
class SoundReceiveConfig:
    """类契约说明.

    职责: 保存 SoundReceiveConfig
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: orchestrator_ws_url、trusted_
    lan_token、stream_id、rtp_host、rtp_por
    t、advertised_rtp_host。
    """

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
    """函数契约说明.

    功能: 执行 load_runtime_config 的同步逻辑,并协调
    load_config, urlparse,
    SoundReceiveConfig, ConfigError。
    参数: env: Mapping[str, str] | None。
    可省略。
    契约: 同步调用。 返回 `SoundReceiveConfig`。
    可能抛出 ConfigError。
    """

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
        raise ConfigError(
            key="TRUSTED_LAN_TOKEN", reason="must be set for sound-receive"
        )

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
    """函数契约说明.

    功能: 执行 _required_value 的同步逻辑,并协调
    strip, ConfigError, get。
    参数: source: Mapping[str, str]。 必填。
    key: str。 必填。
    契约: 同步调用。 返回 `str`。 可能抛出
    ConfigError。
    """

    value = source.get(key, "").strip()

    if value == "":
        raise ConfigError(key=key, reason="must be set")

    return value


def _port(raw_port: str | None) -> int:
    """函数契约说明.

    功能: 执行 _port 的同步逻辑,并协调 ConfigError,
    int。
    参数: raw_port: str | None。 必填。
    契约: 同步调用。 返回 `int`。 可能抛出
    ConfigError。
    """

    if raw_port is None:
        raise ConfigError(key="SOUND_RTP_BIND_PORT", reason="must be set")

    try:
        port = int(raw_port)

    except ValueError as exc:
        raise ConfigError(
            key="SOUND_RTP_BIND_PORT", reason="must be an integer"
        ) from exc

    if not 1 <= port <= 65_535:
        raise ConfigError(
            key="SOUND_RTP_BIND_PORT", reason="must be between 1 and 65535"
        )

    return port


def _playback_device(source: Mapping[str, str]) -> PlaybackDevice:
    """函数契约说明.

    功能: 执行 _playback_device 的同步逻辑,并协调
    strip, isdecimal, int, get。
    参数: source: Mapping[str, str]。 必填。
    契约: 同步调用。 返回 `PlaybackDevice`。
    """

    value = source.get("BITNP_PLAYBACK_DEVICE", "").strip()

    if value == "" or value == "default":
        return None

    if value.isdecimal():
        return int(value)

    return value
