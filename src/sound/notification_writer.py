"""模块契约说明.

职责: 提供 sound.notification_writer
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import asyncio
from dataclasses import dataclass
from typing import Protocol, final


class ControlSender(Protocol):
    """类契约说明.

    职责: 声明 ControlSender
    协议接口,约束实现方必须提供的行为。
    契约: 方法: send。
    """

    async def send(self, message: str) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 message: str。
        必填。
        契约: 异步调用。 返回 `None`。
        """

        ...


@dataclass(frozen=True, slots=True)
class OutboundNotification:
    """类契约说明.

    职责: 保存 OutboundNotification
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段:
    message、stream_id、is_playing。
    """

    message: str

    stream_id: str | None = None

    is_playing: bool = False


@dataclass(frozen=True, slots=True)
class _QueuedNotification:
    """类契约说明.

    职责: 保存 _QueuedNotification
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: notification、completion。
    """

    notification: OutboundNotification

    completion: asyncio.Future[None]


@dataclass(frozen=True, slots=True)
class _WriterBarrier:
    """类契约说明.

    职责: 保存 _WriterBarrier
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: completion。
    """

    completion: asyncio.Future[None]


type _WriterItem = _QueuedNotification | _WriterBarrier | None


@final
class NotificationWriter:
    """类契约说明.

    职责: 定义 NotificationWriter
    的状态、行为和对外协作边界。
    契约: 方法: __init__、invalidate_playing、
    enqueue、send、close、run。
    """

    def __init__(self, connection: ControlSender) -> None:
        """函数契约说明.

        功能: 初始化 NotificationWriter
        的字段并建立实例不变式。
        参数: self 表示当前实例。 connection:
        ControlSender。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._connection = connection

        self._queue: asyncio.Queue[_WriterItem] = asyncio.Queue()

        self._invalidated_playing_streams: set[str] = set()

    def invalidate_playing(self, stream_id: str) -> asyncio.Future[None]:
        """函数契约说明.

        功能: 执行 invalidate_playing
        的同步逻辑,并协调 add, create_future,
        put_nowait, _WriterBarrier。
        参数: self 表示当前实例。 stream_id: str。
        必填。
        契约: 同步调用。 返回
        `asyncio.Future[None]`。
        """

        self._invalidated_playing_streams.add(stream_id)

        completion = asyncio.get_running_loop().create_future()

        self._queue.put_nowait(_WriterBarrier(completion))

        return completion

    def enqueue(self, notification: OutboundNotification) -> None:
        """函数契约说明.

        功能: 执行 enqueue 的同步逻辑,并协调
        create_future, put_nowait,
        _QueuedNotification,
        get_running_loop。
        参数: self 表示当前实例。 notification:
        OutboundNotification。 必填。
        契约: 同步调用。 返回 `None`。
        """

        completion = asyncio.get_running_loop().create_future()

        self._queue.put_nowait(_QueuedNotification(notification, completion))

    async def send(self, notification: OutboundNotification) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 notification:
        OutboundNotification。 必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

        completion = asyncio.get_running_loop().create_future()

        self._queue.put_nowait(_QueuedNotification(notification, completion))

        await completion

    def close(self) -> None:
        """函数契约说明.

        功能: 执行 close 的同步逻辑,并协调
        put_nowait。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `None`。
        """

        self._queue.put_nowait(None)

    async def run(self) -> None:
        """函数契约说明.

        功能: 运行流程并协调其依赖步骤。
        参数: self 表示当前实例。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

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

                        continue

                    await self._connection.send(notification.message)

                    completion.set_result(None)

                case _WriterBarrier(completion=completion):
                    completion.set_result(None)
