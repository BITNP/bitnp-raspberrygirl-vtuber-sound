"""Playback lifecycle tests use controlled device completion, never live audio."""

import asyncio
import json
from dataclasses import dataclass, field

import pytest

from sound.notification_writer import NotificationWriter
from sound.orchestrator_ws import JsonValue, parse_event
from sound.playback_lifecycle import L16_CODEC, PlaybackLifecycle
from sound.rtp_playback import L16PlaybackFrame


@dataclass
class Drain:
    late_result: bool = False
    timeout_result: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)
    release: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    exited: asyncio.Event = field(default_factory=asyncio.Event)


@dataclass
class Device:
    drains: list[Drain] = field(default_factory=lambda: [Drain()])
    finishes: list[str] = field(default_factory=list)
    aborts: list[str] = field(default_factory=list)
    frames: list[L16PlaybackFrame] = field(default_factory=list)
    closed: bool = False

    def write(self, frame: L16PlaybackFrame) -> None:
        self.frames.append(frame)

    def finish_stream(self, stream_id: str) -> None:
        self.finishes.append(stream_id)

    async def wait_stream_drained(self, stream_id: str) -> None:
        drain = self.drains[len(self.finishes) - 1]
        drain.started.set()
        try:
            try:
                await drain.release.wait()
            except asyncio.CancelledError:
                drain.cancelled.set()
                if not drain.late_result:
                    raise
                await drain.release.wait()
            if drain.timeout_result:
                raise TimeoutError
        finally:
            drain.exited.set()

    def close_stream(self, stream_id: str) -> None:
        self.aborts.append(stream_id)

    def close(self) -> None:
        self.closed = True


@dataclass
class Output:
    messages: list[dict[str, JsonValue]] = field(default_factory=list)
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)

    async def send(self, message: str) -> None:
        async with self.changed:
            self.messages.append(dict(parse_event(message)))
            self.changed.notify_all()

    def states(self, state: str) -> list[dict[str, JsonValue]]:
        return [
            m
            for m in self.messages
            if isinstance(m["data"], dict) and m["data"].get("state") == state
        ]

    async def wait_state(self, state: str, count: int = 1) -> None:
        async with self.changed:
            await self.changed.wait_for(lambda: len(self.states(state)) >= count)


def event(kind: str, epoch: int = 1, **changes: JsonValue) -> dict[str, JsonValue]:
    data: dict[str, JsonValue]
    if kind == "cancel":
        data = {"reason": "替换"}
    elif kind == "media.stream.flush":
        data = {
            "stream_id": "stream",
            "cancellation_epoch": epoch,
            "request_id": f"flush-{epoch}",
            "target_generated_ssrc": epoch - 1,
        }
    else:
        data = {
            "command_id": f"command-{epoch}",
            "stream_id": "stream",
            "cancellation_epoch": epoch,
            "ssrc": epoch,
        }
        if kind == "media.stream.command":
            data.update(
                {
                    "start_rtp_timestamp": 320,
                    "codec": dict(L16_CODEC),
                    "rtp_sender_endpoint": {"host": "127.0.0.1", "port": 5004},
                }
            )
    data.update(changes)
    return dict(
        parse_event(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "event_type": kind,
                    "event_id": f"event-{epoch}",
                    "source": "orchestrator",
                    "time": "2026-09-14T00:00:00Z",
                    "trace_id": f"trace-{epoch}",
                    "session_id": "session",
                    "seq": epoch,
                    "turn_id": f"turn-{epoch}",
                    "segment_id": f"segment-{epoch}",
                    "data": data,
                }
            )
        )
    )


def packet(ssrc: int) -> bytes:
    return (
        bytes([0x80, 96, 0, 1])
        + (320).to_bytes(4, "big")
        + ssrc.to_bytes(4, "big")
        + bytes(640)
    )


def lifecycle(device: Device, output: Output) -> PlaybackLifecycle:
    return PlaybackLifecycle(
        session_id="session",
        stream_id="stream",
        playback_sink=device,
        notifications=NotificationWriter(output),
        jitter_target_ms=20,
        jitter_max_ms=200,
    )


@pytest.fixture(autouse=True)
def no_network_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    # In-process inputs have no UDP/WSS delivery skew. Device completion is explicit.
    monkeypatch.setattr("sound.playback_lifecycle._END_GRACE_SECONDS", 0)


@pytest.mark.asyncio
async def test_end_requires_physical_drain_and_emits_one_correlated_terminal() -> None:
    device, output = Device(), Output()
    runtime = lifecycle(device, output)
    async with asyncio.timeout(2), runtime.running():
        await runtime.handle_control(event("media.stream.command"))
        runtime.receive_packet(packet(1), ("127.0.0.1", 5004))
        await output.wait_state("playing")
        await runtime.handle_control(event("media.stream.end", ssrc=99))
        await runtime.handle_control(event("media.stream.end"))
        await runtime.handle_control(event("media.stream.end"))
        await device.drains[0].started.wait()
        assert not output.states("finished")
        device.drains[0].release.set()
        await output.wait_state("finished")
        await runtime.handle_control(event("media.stream.end"))
    assert device.finishes == ["stream"]
    assert device.closed
    finished = output.states("finished")
    assert len(finished) == 1
    assert finished[0]["trace_id"] == "trace-1"
    assert finished[0]["turn_id"] == "turn-1"
    assert finished[0]["segment_id"] == "segment-1"
    assert finished[0]["seq"] == 1
    assert finished[0]["data"] == {
        "stream_id": "stream",
        "command_id": "command-1",
        "cancellation_epoch": 1,
        "state": "finished",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout_result", [False, True])
async def test_superseded_drain_cannot_finish_or_abort_new_lease(
    timeout_result: bool,
) -> None:
    old = Drain(late_result=True, timeout_result=timeout_result)
    new = Drain()
    device, output = Device(drains=[old, new]), Output()
    runtime = lifecycle(device, output)
    async with asyncio.timeout(2), runtime.running():
        await runtime.handle_control(event("media.stream.command"))
        await runtime.handle_control(event("media.stream.end"))
        await old.started.wait()
        await runtime.handle_control(event("media.stream.command", 2))
        await old.cancelled.wait()
        await runtime.handle_control(event("media.stream.end", 2))
        await new.started.wait()
        aborts = list(device.aborts)
        old.release.set()
        await old.exited.wait()
        # The old operation resumed and returned before this continuation.
        assert device.aborts == aborts
        assert not output.states("finished")
        assert not output.states("error")
        new.release.set()
        await output.wait_state("finished")
    assert len(output.states("finished")) == 1
    assert output.states("finished")[0]["turn_id"] == "turn-2"


@pytest.mark.asyncio
async def test_flush_replay_does_not_cancel_new_drain_or_suppress_new_playing() -> None:
    old, new = Drain(), Drain()
    device, output = Device(drains=[old, new]), Output()
    runtime = lifecycle(device, output)
    async with asyncio.timeout(2), runtime.running():
        await runtime.handle_control(event("media.stream.command"))
        await runtime.handle_control(event("media.stream.end"))
        await old.started.wait()
        flush = event("media.stream.flush", 2)
        await runtime.handle_control(flush)
        await old.cancelled.wait()
        await runtime.handle_control(event("media.stream.command", 2))
        runtime.receive_packet(packet(2))
        await output.wait_state("playing")
        await runtime.handle_control(event("media.stream.end", 2))
        await new.started.wait()
        await runtime.handle_control(flush)
        assert not new.cancelled.is_set()
        new.release.set()
        await output.wait_state("finished")
    assert output.states("finished")[0]["turn_id"] == "turn-2"
    acknowledgements = [
        m["data"]
        for m in output.messages
        if m["event_type"] == "media.stream.flush.ack"
    ]
    assert [a["disposition"] for a in acknowledgements] == ["APPLIED", "REPLAYED"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid", [{"stream_id": "other"}, {"codec": {}}, {"ssrc": 0}]
)
async def test_rejected_command_preserves_current_playback(
    invalid: dict[str, JsonValue],
) -> None:
    device, output = Device(), Output()
    runtime = lifecycle(device, output)
    async with asyncio.timeout(2), runtime.running():
        await runtime.handle_control(event("media.stream.command"))
        await runtime.handle_control(event("media.stream.command", 2, **invalid))
        runtime.receive_packet(packet(1), ("127.0.0.1", 5004))
        await output.wait_state("playing")
        await runtime.handle_control(event("media.stream.end"))
        await device.drains[0].started.wait()
        device.drains[0].release.set()
        await output.wait_state("finished")
    assert len(output.states("queued")) == 1
    assert output.states("finished")[0]["turn_id"] == "turn-1"


@pytest.mark.asyncio
async def test_queued_packet_belongs_to_its_lease_and_sender() -> None:
    device, output = Device(), Output()
    runtime = lifecycle(device, output)
    async with asyncio.timeout(2), runtime.running():
        await runtime.handle_control(event("media.stream.command"))
        runtime.receive_packet(packet(1), ("127.0.0.1", 5004))
        # No await between enqueue and replacement, so the old packet is still queued.
        await runtime.handle_control(event("media.stream.command", 2))
        runtime.receive_packet(packet(2), ("127.0.0.1", 5005))
        runtime.receive_packet(packet(1), ("127.0.0.1", 5004))
        runtime.receive_packet(packet(2), ("127.0.0.1", 5004))
        await output.wait_state("playing")
        await runtime.handle_control(event("cancel", 2))
    assert len(device.frames) == 1
    assert len(output.states("playing")) == 1
    assert output.states("playing")[0]["turn_id"] == "turn-2"


@pytest.mark.asyncio
async def test_cancellation_joins_device_drain_before_connection_is_reused() -> None:
    device, output = Device(), Output()
    runtime = lifecycle(device, output)

    async def connection() -> None:
        async with runtime.running():
            await runtime.handle_control(event("media.stream.command"))
            await runtime.handle_control(event("media.stream.end"))
            await asyncio.Future[None]()

    async with asyncio.timeout(2):
        task = asyncio.create_task(connection())
        await device.drains[0].started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert device.drains[0].exited.is_set()
    assert device.closed
    assert not output.states("finished")
    assert not output.states("error")
    runtime.receive_packet(packet(1))
    assert not device.frames


@pytest.mark.asyncio
async def test_rtp_arriving_during_ready_delivery_reports_playing_after_queued() -> (
    None
):
    ready_started, ready_release = asyncio.Event(), asyncio.Event()

    class SlowReady(Output):
        async def send(self, message: str) -> None:
            if parse_event(message)["event_type"] == "media.rtp.sink.ready":
                ready_started.set()
                await ready_release.wait()
            await super().send(message)

    device, output = Device(), SlowReady()
    runtime = lifecycle(device, output)
    async with asyncio.timeout(2), runtime.running(), asyncio.TaskGroup() as group:
        command = group.create_task(
            runtime.handle_control(event("media.stream.command"))
        )
        await ready_started.wait()
        runtime.receive_packet(packet(1))
        ready_release.set()
        await command
        await output.wait_state("playing")
        await runtime.handle_control(event("cancel"))
    states = [
        m["data"]["state"]
        for m in output.messages
        if m["event_type"] == "media.stream.state"
    ]
    assert states == ["queued", "playing", "cancelled"]


@pytest.mark.asyncio
async def test_normal_control_close_preserves_udp_tail_during_end_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    grace_started, grace_release = asyncio.Event(), asyncio.Event()
    original_sleep = asyncio.sleep

    async def controlled_grace(delay: float) -> None:
        if delay == 0.1:
            grace_started.set()
            await grace_release.wait()
        else:
            await original_sleep(delay)

    monkeypatch.setattr("sound.playback_lifecycle._END_GRACE_SECONDS", 0.1)
    monkeypatch.setattr("sound.playback_lifecycle.asyncio.sleep", controlled_grace)
    device, output = Device(), Output()
    runtime = lifecycle(device, output)

    async def connection() -> None:
        async with runtime.running():
            await runtime.handle_control(event("media.stream.command"))
            await runtime.handle_control(event("media.stream.end"))
            # Normal WSS EOF: context cleanup starts before the final UDP packet.

    async with asyncio.timeout(2), asyncio.TaskGroup() as group:
        group.create_task(connection())
        await grace_started.wait()
        runtime.receive_packet(packet(1), ("127.0.0.1", 5004))
        await output.wait_state("playing")
        grace_release.set()
        await device.drains[0].started.wait()
        device.drains[0].release.set()
    assert len(device.frames) == 1
    assert len(output.states("finished")) == 1
    assert device.closed
