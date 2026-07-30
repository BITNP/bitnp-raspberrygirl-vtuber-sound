
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, final


class GeneratedPlaybackReceiver(Protocol):

    def flush_stream(self, stream_id: str, target_generated_ssrc: int) -> bool:

        ...


@dataclass(frozen=True, slots=True)
class StreamFlush:

    session_id: str

    stream_id: str

    turn_id: str

    segment_id: str

    cancellation_epoch: int

    request_id: str

    target_generated_ssrc: int

@dataclass(frozen=True, slots=True)
class StreamFlushAck:

    session_id: str

    stream_id: str

    turn_id: str

    segment_id: str

    cancellation_epoch: int

    request_id: str

    target_generated_ssrc: int

    @classmethod
    def from_flush(cls, flush: StreamFlush) -> StreamFlushAck:

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

    def __init__(self, *, session_id: str, receiver: GeneratedPlaybackReceiver) -> None:

        self._session_id = session_id

        self._receiver = receiver

        self._epochs: dict[str, int] = {}

        self._acknowledgements: dict[tuple[str, int, str], StreamFlushAck] = {}

    def apply(self, flush: StreamFlush) -> StreamFlushAck | None:

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
