
import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import override

import pytest

from sound.orchestrator_ws import parse_event, required_mapping, required_str
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
            self.binding.deliver(
                _rtp_packet(timestamp=320, ssrc=0x1234_5678, payload=b"\x00\x01")
            )

            return self.messages.pop(0)

        return message

    async def close(self) -> None:

        self.closed += 1


@dataclass
class _DelayedPlayingControlConnection(_FakeControlConnection):

    release_playing: asyncio.Event = field(default_factory=asyncio.Event)

    barrier_sent: asyncio.Event = field(default_factory=asyncio.Event)

    @override
    async def send(self, message: str) -> None:

        envelope = parse_event(message)

        event_type = required_str(envelope, "event_type")

        if (
            event_type == "media.stream.state"
            and required_str(required_mapping(envelope, "data"), "state") == "playing"
        ):
            _ = await self.release_playing.wait()

        if event_type == "media.stream.flush.ack" or (
            event_type == "media.stream.state"
            and required_str(required_mapping(envelope, "data"), "state") == "cancelled"
        ):
            _ = self.barrier_sent.set()

        await super().send(message)


@dataclass
class _FakeControlConnector:

    connection: _FakeControlConnection

    udp_binder: _FakeUdpBinder

    headers: dict[str, str] | None = None

    async def connect(
        self, url: str, headers: dict[str, str]
    ) -> _FakeControlConnection:

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
            "segment_id": "segment-001",
            "seq": 9,
            "data": {
                "command_id": "stream-command-001",
                "stream_id": "sound-stream-001",
                "start_rtp_timestamp": 320,
                "ssrc": 0x1234_5678,
                "cancellation_epoch": 3,
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
            "segment_id": "segment-001",
            "data": {"reason": "newer_stream"},
        }
    )


def _flush() -> str:

    return json.dumps(
        {
            "schema_version": "1.0.0",
            "event_type": "media.stream.flush",
            "event_id": "flush-001",
            "source": "orchestrator",
            "time": "2026-07-28T00:00:10Z",
            "trace_id": "trace-001",
            "session_id": "session-001",
            "turn_id": "turn-001",
            "segment_id": "sound-stream-001",
            "seq": 11,
            "data": {
                "stream_id": "sound-stream-001",
                "cancellation_epoch": 3,
                "request_id": "flush-request-001",
                "target_generated_ssrc": 0x1234_5678,
            },
        }
    )


def _rtp_packet(*, timestamp: int, ssrc: int, payload: bytes) -> bytes:

    return (
        bytes([0x80, 96, 0, 1])
        + timestamp.to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + payload
        + bytes(640 - len(payload))
    )


def _state_values(messages: list[str]) -> list[str]:

    return [
        required_str(required_mapping(event, "data"), "state")
        for message in messages
        if required_str((event := parse_event(message)), "event_type")
        == "media.stream.state"
    ]


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
async def test_receive_runtime_binds_registers_announces_delivers_cancels_and_closes_once() -> (
    None
):
    # Given: an authenticated Sound sink with a canonical command, one packet, and cancellation.


    binding = _FakeUdpBinding()

    binder = _FakeUdpBinder(binding=binding)

    connection = _FakeControlConnection(
        messages=[_command(), "deliver", _cancel()], binding=binding
    )

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
            session_id="session-001",
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

    envelopes = [parse_event(message) for message in connection.received]

    assert [envelope["event_type"] for envelope in envelopes] == [
        "media.rtp.sink.register",
        "media.rtp.sink.ready",
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

    assert [required_mapping(envelope, "data")["state"] for envelope in envelopes[2:]] == [
        "queued",
        "cancelled",
    ]

    assert [
        (envelope["trace_id"], envelope["session_id"], envelope["seq"])
        for envelope in envelopes[1:]
    ] == [("trace-001", "session-001", 9)] * 3

    assert [
        (
            envelope["turn_id"],
            envelope["segment_id"],
            required_mapping(envelope, "data")["cancellation_epoch"],
        )
        for envelope in envelopes[2:]
    ] == [("turn-001", "segment-001", 3)] * 2

    assert [frame.payload for frame in sink.frames] == [b"\x00\x01" + bytes(638)]

    assert binding.close_calls == 1

    assert connection.closed == 1

    assert sink.closed == 1


@pytest.mark.asyncio
async def test_receive_runtime_drops_queued_playing_after_cancel_before_writer_consumes_it() -> (
    None
):
    # Given: an RTP callback whose playing notification cannot be consumed before cancellation.


    binding = _FakeUdpBinding()

    binder = _FakeUdpBinder(binding=binding)

    connection = _DelayedPlayingControlConnection(
        messages=[_command(), "deliver", _cancel()],
        binding=binding,
    )

    runtime = ReceiveRuntime(
        config=SoundReceiveConfig(
            orchestrator_ws_url="wss://orchestrator.example.test/control",
            trusted_lan_token="trusted-token",
            stream_id="sound-stream-001",
            rtp_host="0.0.0.0",
            rtp_port=50_006,
            advertised_rtp_host="sound.example.test",
            session_id="session-001",
        ),
        udp_binder=binder,
        control_connector=_FakeControlConnector(
            connection=connection, udp_binder=binder
        ),
        playback_sink=_RecordingSink(),
    )

    # When: cancellation is acknowledged before the delayed playing send is released.

    task = asyncio.create_task(runtime.run())

    _ = await connection.barrier_sent.wait()

    _ = connection.release_playing.set()

    await task

    # Then: no stale playing state may follow the cancellation acknowledgement.

    states = _state_values(connection.received)

    assert states == ["queued", "cancelled"]


@pytest.mark.asyncio
async def test_receive_runtime_drops_queued_playing_after_flush_ack_before_writer_consumes_it() -> (
    None
):
    # Given: an RTP callback whose playing notification remains queued through a valid flush.


    binding = _FakeUdpBinding()

    binder = _FakeUdpBinder(binding=binding)

    connection = _DelayedPlayingControlConnection(
        messages=[_command(), "deliver", _flush()],
        binding=binding,
    )

    runtime = ReceiveRuntime(
        config=SoundReceiveConfig(
            orchestrator_ws_url="wss://orchestrator.example.test/control",
            trusted_lan_token="trusted-token",
            stream_id="sound-stream-001",
            rtp_host="0.0.0.0",
            rtp_port=50_006,
            advertised_rtp_host="sound.example.test",
            session_id="session-001",
        ),
        udp_binder=binder,
        control_connector=_FakeControlConnector(
            connection=connection, udp_binder=binder
        ),
        playback_sink=_RecordingSink(),
    )

    # When: Sound acknowledges the flush before the delayed playing send is released.

    task = asyncio.create_task(runtime.run())

    _ = await connection.barrier_sent.wait()

    _ = connection.release_playing.set()

    await task

    # Then: no stale playing state may follow the exact flush acknowledgement.

    event_types = [
        required_str(parse_event(message), "event_type")
        for message in connection.received
    ]

    states = _state_values(connection.received)

    assert event_types[-1] == "media.stream.flush.ack"

    assert states == ["queued"]


@pytest.mark.asyncio
async def test_receive_runtime_returns_correlated_flush_ack_for_announced_generated_ssrc() -> (
    None
):
    # Given: Sound has accepted one generated stream command before a correlated flush.


    binding = _FakeUdpBinding()

    binder = _FakeUdpBinder(binding=binding)

    connection = _FakeControlConnection(
        messages=[_command(), _flush()], binding=binding
    )

    runtime = ReceiveRuntime(
        config=SoundReceiveConfig(
            orchestrator_ws_url="wss://orchestrator.example.test/control",
            trusted_lan_token="trusted-token",
            stream_id="sound-stream-001",
            rtp_host="0.0.0.0",
            rtp_port=50_006,
            advertised_rtp_host="sound.example.test",
            session_id="session-001",
        ),
        udp_binder=binder,
        control_connector=_FakeControlConnector(
            connection=connection, udp_binder=binder
        ),
        playback_sink=_RecordingSink(),
    )

    # When: the WSS receive loop applies the flush.

    await runtime.run()

    # Then: Sound returns the canonical acknowledgement with every identity preserved.

    acknowledgement = parse_event(connection.received[-1])

    assert acknowledgement["event_type"] == "media.stream.flush.ack"

    assert acknowledgement["data"] == {
        "stream_id": "sound-stream-001",
        "cancellation_epoch": 3,
        "request_id": "flush-request-001",
        "target_generated_ssrc": 0x1234_5678,
    }

    assert (
        acknowledgement["trace_id"],
        acknowledgement["session_id"],
        acknowledgement["seq"],
        acknowledgement["turn_id"],
        acknowledgement["segment_id"],
    ) == ("trace-001", "session-001", 11, "turn-001", "sound-stream-001")
