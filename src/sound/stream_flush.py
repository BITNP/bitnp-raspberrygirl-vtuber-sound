"""模块契约说明.

职责: 提供 sound.stream_flush
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, final


class GeneratedPlaybackReceiver(Protocol):
    """类契约说明.

    职责: 声明 GeneratedPlaybackReceiver
    协议接口,约束实现方必须提供的行为。
    契约: 方法: flush_stream。
    """

    def flush_stream(self, stream_id: str, target_generated_ssrc: int) -> bool:
        """函数契约说明.

        功能: 执行 flush_stream
        的同步逻辑,并维持签名契约。
        参数: self 表示当前实例。 stream_id: str。
        必填。 target_generated_ssrc: int。
        必填。
        契约: 同步调用。 返回 `bool`。
        """

        ...


@dataclass(frozen=True, slots=True)
class StreamFlush:
    """类契约说明.

    职责: 保存 StreamFlush
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: session_id、stream_id、turn_id
    、segment_id、cancellation_epoch、reque
    st_id。 方法:
    with_target_generated_ssrc。
    """

    session_id: str

    stream_id: str

    turn_id: str

    segment_id: str

    cancellation_epoch: int

    request_id: str

    target_generated_ssrc: int

    def with_target_generated_ssrc(self, target_generated_ssrc: int) -> StreamFlush:
        """函数契约说明.

        功能: 执行
        with_target_generated_ssrc
        的同步逻辑,并协调 StreamFlush。
        参数: self 表示当前实例。
        target_generated_ssrc: int。 必填。
        契约: 同步调用。 返回 `StreamFlush`。
        """

        return StreamFlush(
            session_id=self.session_id,
            stream_id=self.stream_id,
            turn_id=self.turn_id,
            segment_id=self.segment_id,
            cancellation_epoch=self.cancellation_epoch,
            request_id=self.request_id,
            target_generated_ssrc=target_generated_ssrc,
        )


@dataclass(frozen=True, slots=True)
class StreamFlushAck:
    """类契约说明.

    职责: 保存 StreamFlushAck
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: session_id、stream_id、turn_id
    、segment_id、cancellation_epoch、reque
    st_id。 方法: from_flush。
    """

    session_id: str

    stream_id: str

    turn_id: str

    segment_id: str

    cancellation_epoch: int

    request_id: str

    target_generated_ssrc: int

    @classmethod
    def from_flush(cls, flush: StreamFlush) -> StreamFlushAck:
        """函数契约说明.

        功能: 执行 from_flush 的同步逻辑,并协调 cls。
        参数: cls 表示当前类。 flush:
        StreamFlush。 必填。
        契约: 同步调用。 返回 `StreamFlushAck`。
        """

        return cls(
            session_id=flush.session_id,
            stream_id=flush.stream_id,
            turn_id=flush.turn_id,
            segment_id=flush.segment_id,
            cancellation_epoch=flush.cancellation_epoch,
            request_id=flush.request_id,
            target_generated_ssrc=flush.target_generated_ssrc,
        )


@final
class StreamFlushController:
    """类契约说明.

    职责: 定义 StreamFlushController
    的状态、行为和对外协作边界。
    契约: 方法: __init__、apply。
    """

    def __init__(self, *, session_id: str, receiver: GeneratedPlaybackReceiver) -> None:
        """函数契约说明.

        功能: 初始化 StreamFlushController
        的字段并建立实例不变式。
        参数: self 表示当前实例。 session_id:
        str。 必填。 receiver:
        GeneratedPlaybackReceiver。 必填。
        契约: 同步调用。 返回 `None`。
        """

        self._session_id = session_id

        self._receiver = receiver

        self._epochs: dict[str, int] = {}

        self._acknowledgements: dict[tuple[str, int, str], StreamFlushAck] = {}

    def apply(self, flush: StreamFlush) -> StreamFlushAck | None:
        """函数契约说明.

        功能: 执行 apply 的同步逻辑,并协调 get,
        from_flush, flush_stream。
        参数: self 表示当前实例。 flush:
        StreamFlush。 必填。
        契约: 同步调用。 返回 `StreamFlushAck |
        None`。
        """

        if flush.session_id != self._session_id or flush.cancellation_epoch < 0:
            return None

        key = (flush.stream_id, flush.cancellation_epoch, flush.request_id)

        duplicate = self._acknowledgements.get(key)

        if duplicate is not None:
            return duplicate

        previous_epoch = self._epochs.get(flush.stream_id)

        if previous_epoch is not None and flush.cancellation_epoch <= previous_epoch:
            return None

        if (
            self._receiver.flush_stream(flush.stream_id, flush.target_generated_ssrc)
            is False
        ):
            return None

        acknowledgement = StreamFlushAck.from_flush(flush)

        self._epochs[flush.stream_id] = flush.cancellation_epoch

        self._acknowledgements[key] = acknowledgement

        return acknowledgement
