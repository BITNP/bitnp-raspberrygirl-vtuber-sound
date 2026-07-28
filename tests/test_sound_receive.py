import json
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from sound.receive import ReceiveRuntime
from sound.receive_config import SoundReceiveConfig, load_runtime_config
from sound.rtp_playback import L16PlaybackFrame


@dataclass
class _FakeUdpBinding:
    port: int = 50_006
    handler: Callable[[bytes], None] | None = None
    close_calls: int = 0

    def set_packet_handler(self, handler: Callable[[bytes], None]) -> None:
        self.handler = handler

    def deliver(self, packet: bytes) -> None:
        assert self.handler is not None
        self.handler(packet)

    def close(self) -> None:
        self.close_calls += 1


@dataclass
class _FakeUdpBinder:
    binding: _FakeUdpBinding
    bound: bool = False

    async def bind(self, host: str, port: int) -> _FakeUdpBinding:
        assert (host, port) == ("0.0.0.0", 50_006)
        self.bound = True
        return self.binding


@dataclass
class _FakeControlConnection:
    messages: list[str]
    binding: _FakeUdpBinding
    received: list[str] = field(default_factory=list)
    closed: int = 0

    async def send(self, message: str) -> None:
        self.received.append(message)

    async def recv(self) -> str | None:
        if not self.messages:
            return None
        message = self.messages.pop(0)
        if message == "deliver":
            self.binding.deliver(_rtp_packet(timestamp=320, ssrc=0x1234_5678, payload=b"\x00\x01"))
            return self.messages.pop(0)
        return message

    async def close(self) -> None:
        self.closed += 1


@dataclass
class _FakeControlConnector:
    connection: _FakeControlConnection
    udp_binder: _FakeUdpBinder
    headers: dict[str, str] | None = None

    async def connect(self, url: str, headers: dict[str, str]) -> _FakeControlConnection:
        assert self.udp_binder.bound is True
        assert url == "wss://orchestrator.example.test/control"
        self.headers = headers
        return self.connection


@dataclass
class _RecordingSink:
    frames: list[L16PlaybackFrame] = field(default_factory=list)
    closed: int = 0

    def write(self, frame: L16PlaybackFrame) -> None:
        self.frames.append(frame)

    def close_stream(self, stream_id: str) -> None:
        _ = stream_id

    def close(self) -> None:
        self.closed += 1


def _command() -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "event_type": "media.stream.command",
            "event_id": "command-001",
            "source": "orchestrator",
            "time": "2026-07-08T00:00:08Z",
            "trace_id": "trace-001",
            "session_id": "session-001",
            "turn_id": "turn-001",
            "seq": 9,
            "data": {
                "command_id": "stream-command-001",
                "stream_id": "sound-stream-001",
                "start_rtp_timestamp": 320,
                "ssrc": 0x1234_5678,
                "codec": {
                    "format": "L16",
                    "clock_rate_hz": 16_000,
                    "channels": 1,
                    "payload_type": 96,
                    "samples_per_frame": 320,
                },
                "rtp_endpoint": {"host": "sound.example.test", "port": 50_006},
            },
        }
    )


def _cancel() -> str:
    return json.dumps(
        {
            "schema_version": "1.0.0",
            "event_type": "cancel",
            "event_id": "cancel-001",
            "source": "orchestrator",
            "time": "2026-07-08T00:00:09Z",
            "trace_id": "trace-001",
            "session_id": "session-001",
            "seq": 10,
            "segment_id": "sound-stream-001",
            "data": {"reason": "newer_stream"},
        }
    )


def _rtp_packet(*, timestamp: int, ssrc: int, payload: bytes) -> bytes:
    return bytes([0x80, 96, 0, 1]) + timestamp.to_bytes(4, "big") + ssrc.to_bytes(4, "big") + payload


def test_runtime_config_requires_authenticated_wss_and_udp_endpoint() -> None:
    # Given: deployment configuration for Sound's sole Orchestrator control and RTP routes.
    environment = {
        "ORCHESTRATOR_WS_URL": "wss://orchestrator.example.test/control",
        "TRUSTED_LAN_TOKEN": "trusted-token",
        "SOUND_RTP_STREAM_ID": "sound-stream-001",
        "SOUND_RTP_BIND_HOST": "0.0.0.0",
        "SOUND_RTP_BIND_PORT": "50006",
        "SOUND_RTP_ADVERTISED_HOST": "sound.example.test",
    }

    # When: the production command loads its environment.
    config = load_runtime_config(environment)

    # Then: only the configured WSS route and UDP sink endpoint become runtime inputs.
    assert config == SoundReceiveConfig(
        orchestrator_ws_url="wss://orchestrator.example.test/control",
        trusted_lan_token="trusted-token",
        stream_id="sound-stream-001",
        rtp_host="0.0.0.0",
        rtp_port=50_006,
        advertised_rtp_host="sound.example.test",
    )


@pytest.mark.asyncio
async def test_receive_runtime_binds_registers_announces_delivers_cancels_and_closes_once() -> None:
    # Given: an authenticated Sound sink with a canonical command, one packet, and cancellation.
    binding = _FakeUdpBinding()
    binder = _FakeUdpBinder(binding=binding)
    connection = _FakeControlConnection(messages=[_command(), "deliver", _cancel()], binding=binding)
    connector = _FakeControlConnector(connection=connection, udp_binder=binder)
    sink = _RecordingSink()
    runtime = ReceiveRuntime(
        config=SoundReceiveConfig(
            orchestrator_ws_url="wss://orchestrator.example.test/control",
            trusted_lan_token="trusted-token",
            stream_id="sound-stream-001",
            rtp_host="0.0.0.0",
            rtp_port=50_006,
            advertised_rtp_host="sound.example.test",
        ),
        udp_binder=binder,
        control_connector=connector,
        playback_sink=sink,
    )

    # When: the runtime consumes its WSS control route through normal shutdown.
    await runtime.run()
    binding.deliver(_rtp_packet(timestamp=640, ssrc=0x1234_5678, payload=b"\x00\x02"))

    # Then: UDP precedes authenticated registration, command activates L16 playback, and late RTP is suppressed.
    assert connector.headers == {"authorization": "Bearer trusted-token"}
    envelopes = [json.loads(message) for message in connection.received]
    assert [envelope["event_type"] for envelope in envelopes] == [
        "media.rtp.sink.register",
        "media.rtp.sink.ready",
        "media.stream.state",
        "media.stream.state",
        "media.stream.state",
    ]
    assert envelopes[0]["data"] == {
        "stream_id": "sound-stream-001",
        "codec": {
            "format": "L16",
            "clock_rate_hz": 16_000,
            "channels": 1,
            "payload_type": 96,
            "samples_per_frame": 320,
        },
        "rtp_endpoint": {"host": "sound.example.test", "port": 50_006},
    }
    assert [envelope["data"]["state"] for envelope in envelopes[2:]] == ["queued", "playing", "cancelled"]
    assert [frame.payload for frame in sink.frames] == [b"\x00\x01"]
    assert binding.close_calls == 1
    assert connection.closed == 1
    assert sink.closed == 1
