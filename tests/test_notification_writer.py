
import asyncio
from dataclasses import dataclass, field

import pytest

from sound.notification_writer import NotificationWriter, OutboundNotification


@dataclass
class _BlockedSender:

    playing_started: asyncio.Event = field(default_factory=asyncio.Event)

    release_playing: asyncio.Event = field(default_factory=asyncio.Event)

    messages: list[str] = field(default_factory=list)

    async def send(self, message: str) -> None:

        match message:
            case "playing":
                _ = self.playing_started.set()

                _ = await self.release_playing.wait()

            case _:
                pass

        self.messages.append(message)


@pytest.mark.asyncio
async def test_notification_writer_waits_for_inflight_playing_before_cancelled() -> (
    None
):
    # Given: a playing notification whose connection send is already in flight.


    sender = _BlockedSender()

    writer = NotificationWriter(sender)

    async with asyncio.TaskGroup() as task_group:
        _ = task_group.create_task(writer.run())

        writer.enqueue(OutboundNotification("playing", "stream-001", is_playing=True))

        _ = await sender.playing_started.wait()

        # When: cancellation invalidates playing while that send remains blocked.

        barrier = writer.invalidate_playing("stream-001")

        assert barrier.done() is False

        _ = sender.release_playing.set()

        await barrier

        await writer.send(OutboundNotification("cancelled"))

        writer.close()

    # Then: the in-flight playing notification is externally ordered before cancellation.

    assert sender.messages == ["playing", "cancelled"]


@pytest.mark.asyncio
async def test_notification_writer_waits_for_inflight_playing_before_flush_ack() -> (
    None
):
    # Given: a playing notification whose connection send is already in flight.


    sender = _BlockedSender()

    writer = NotificationWriter(sender)

    async with asyncio.TaskGroup() as task_group:
        _ = task_group.create_task(writer.run())

        writer.enqueue(OutboundNotification("playing", "stream-001", is_playing=True))

        _ = await sender.playing_started.wait()

        # When: flush invalidates playing while that send remains blocked.

        barrier = writer.invalidate_playing("stream-001")

        assert barrier.done() is False

        _ = sender.release_playing.set()

        await barrier

        await writer.send(OutboundNotification("flush-ack"))

        writer.close()

    # Then: the in-flight playing notification is externally ordered before flush ack.

    assert sender.messages == ["playing", "flush-ack"]
