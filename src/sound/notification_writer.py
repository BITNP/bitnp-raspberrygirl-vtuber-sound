import asyncio
from dataclasses import dataclass
from typing import Protocol, assert_never, final


class ControlSender(Protocol):
    async def send(self, message: str) -> None: ...


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
        self._queue: asyncio.Queue[_WriterItem] = asyncio.Queue()
        self._invalidated_playing_streams: set[str] = set()

    def invalidate_playing(self, stream_id: str) -> asyncio.Future[None]:
        self._invalidated_playing_streams.add(stream_id)
        completion = asyncio.get_running_loop().create_future()
        self._queue.put_nowait(_WriterBarrier(completion))
        return completion

    def enqueue(self, notification: OutboundNotification) -> None:
        completion = asyncio.get_running_loop().create_future()
        self._queue.put_nowait(_QueuedNotification(notification, completion))

    async def send(self, notification: OutboundNotification) -> None:
        completion = asyncio.get_running_loop().create_future()
        self._queue.put_nowait(_QueuedNotification(notification, completion))
        await completion

    def close(self) -> None:
        self._queue.put_nowait(None)

    async def run(self) -> None:
        while True:
            item = await self._queue.get()
            match item:
                case None:
                    return
                case _QueuedNotification(notification=notification, completion=completion):
                    if (
                        notification.is_playing
                        and notification.stream_id in self._invalidated_playing_streams
                    ):
                        completion.set_result(None)
                        continue
                    await self._connection.send(notification.message)
                    completion.set_result(None)
                case _WriterBarrier(completion=completion):
                    completion.set_result(None)
                case unreachable:
                    assert_never(unreachable)
