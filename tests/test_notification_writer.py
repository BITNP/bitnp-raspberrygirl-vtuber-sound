"""模块契约说明.

职责: 为测试场景提供断言、夹具和回归用例。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import asyncio
from dataclasses import dataclass, field

import pytest

from sound.notification_writer import NotificationWriter, OutboundNotification


@dataclass
class _BlockedSender:
    """类契约说明.

    职责: 保存 _BlockedSender
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: playing_started、release_play
    ing、messages。 方法: send。
    """

    playing_started: asyncio.Event = field(default_factory=asyncio.Event)

    release_playing: asyncio.Event = field(default_factory=asyncio.Event)

    messages: list[str] = field(default_factory=list)

    async def send(self, message: str) -> None:
        """函数契约说明.

        功能: 发送协议消息或媒体数据。
        参数: self 表示当前实例。 message: str。
        必填。
        契约: 异步调用。 可能等待 I/O 或协程结果。 返回
        `None`。
        """

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

    """函数契约说明.

    功能: 验证 notification writer waits for
    inflight playing before cancelled
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

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

    """函数契约说明.

    功能: 验证 notification writer waits for
    inflight playing before flush ack
    的回归场景和可观察结果。
    参数: 无显式业务参数。
    契约: 异步调用。 可能等待 I/O 或协程结果。 返回 `None`。
    """

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
