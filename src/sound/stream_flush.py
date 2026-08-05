
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from time import monotonic
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


class FlushDisposition(StrEnum):
    APPLIED = "APPLIED"
    REPLAYED = "REPLAYED"

@dataclass(frozen=True, slots=True)
class StreamFlushAck:

    session_id: str

    stream_id: str

    turn_id: str

    segment_id: str

    cancellation_epoch: int

    request_id: str

    target_generated_ssrc: int

    disposition: FlushDisposition

    @classmethod
    def from_flush(
        cls,
        flush: StreamFlush,
        disposition: FlushDisposition | None = None,
    ) -> StreamFlushAck:

        resolved = FlushDisposition.APPLIED if disposition is None else disposition

        return cls(
            session_id=flush.session_id,
            stream_id=flush.stream_id,
            turn_id=flush.turn_id,
            segment_id=flush.segment_id,
            cancellation_epoch=flush.cancellation_epoch,
            request_id=flush.request_id,
            target_generated_ssrc=flush.target_generated_ssrc,
            disposition=resolved,
        )


@final
class StreamFlushController:

    def __init__(self, *, session_id: str, receiver: GeneratedPlaybackReceiver) -> None:

        self._session_id = session_id

        self._receiver = receiver

        self._epochs: dict[str, int] = {}

        self._latest_acknowledgements: dict[
            str, tuple[tuple[str, int, str], StreamFlushAck, float]
        ] = {}

    def apply(self, flush: StreamFlush) -> StreamFlushAck | None:

        if flush.session_id != self._session_id or flush.cancellation_epoch < 0:
            return None

        key = (flush.stream_id, flush.cancellation_epoch, flush.request_id)

        latest = self._latest_acknowledgements.get(flush.stream_id)
        if latest is not None and latest[0] == key and monotonic() - latest[2] <= 5:
            return StreamFlushAck.from_flush(flush, FlushDisposition.REPLAYED)

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

        self._latest_acknowledgements[flush.stream_id] = (
            key,
            acknowledgement,
            monotonic(),
        )

        return acknowledgement
