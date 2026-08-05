
import asyncio
from dataclasses import dataclass
from typing import Protocol, final


class ControlSender(Protocol):

    async def send(self, message: str) -> None:

        ...


@dataclass(frozen=True, slots=True)
class OutboundNotification:

    message: str

    stream_id: str | None = None

    is_playing: bool = False


@dataclass(frozen=True, slots=True)
class _QueuedNotification:

    notification: OutboundNotification

    completion: asyncio.Future[None]


@dataclass(frozen=True, slots=True)
class _WriterBarrier:

    completion: asyncio.Future[None]


type _WriterItem = _QueuedNotification | _WriterBarrier | None


@final
class NotificationWriter:

    def __init__(self, connection: ControlSender) -> None:

        self._connection = connection

        self._queue: asyncio.Queue[_WriterItem] = asyncio.Queue(maxsize=128)

        self._invalidated_playing_streams: set[str] = set()

        self._pending_playing_streams: set[str] = set()

    def invalidate_playing(self, stream_id: str) -> asyncio.Future[None]:

        self._invalidated_playing_streams.add(stream_id)

        completion = asyncio.get_running_loop().create_future()

        if self._queue.full():
            completion.set_result(None)
        else:
            self._queue.put_nowait(_WriterBarrier(completion))

        return completion

    def enqueue(self, notification: OutboundNotification) -> None:

        completion = asyncio.get_running_loop().create_future()

        if (
            notification.is_playing
            and notification.stream_id in self._pending_playing_streams
        ):
            completion.set_result(None)
            return

        if self._queue.full():
            completion.set_result(None)
            return

        if notification.is_playing and notification.stream_id is not None:
            self._pending_playing_streams.add(notification.stream_id)

        self._queue.put_nowait(_QueuedNotification(notification, completion))

    async def send(self, notification: OutboundNotification) -> None:

        completion = asyncio.get_running_loop().create_future()

        await self._queue.put(_QueuedNotification(notification, completion))
        await completion

    def close(self) -> None:

        if not self._queue.full():
            self._queue.put_nowait(None)
        else:
            _ = asyncio.create_task(self._queue.put(None))

    async def run(self) -> None:

        while True:
            item = await self._queue.get()

            match item:
                case None:
                    return

                case _QueuedNotification(
                    notification=notification, completion=completion
                ):
                    if (
                        notification.is_playing
                        and notification.stream_id in self._invalidated_playing_streams
                    ):
                        completion.set_result(None)

                        self._pending_playing_streams.discard(notification.stream_id)

                        continue

                    await self._connection.send(notification.message)

                    if notification.is_playing and notification.stream_id is not None:
                        self._pending_playing_streams.discard(notification.stream_id)

                    completion.set_result(None)

                case _WriterBarrier(completion=completion):
                    completion.set_result(None)
