"""Sound-owned generated playback flush boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, final


class GeneratedPlaybackReceiver(Protocol):
    """Playback capability that can reject one generated SSRC."""

    def flush_stream(self, stream_id: str, target_generated_ssrc: int) -> bool: ...


@dataclass(frozen=True, slots=True)
class StreamFlush:
    """Canonical interruption request received from the Orchestrator."""

    session_id: str
    stream_id: str
    turn_id: str
    segment_id: str
    cancellation_epoch: int
    request_id: str
    target_generated_ssrc: int

    def with_target_generated_ssrc(self, target_generated_ssrc: int) -> StreamFlush:
        """Return a testable immutable variant with a different generated SSRC."""
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
    """Exact acknowledgement of one accepted flush request."""

    session_id: str
    stream_id: str
    turn_id: str
    segment_id: str
    cancellation_epoch: int
    request_id: str
    target_generated_ssrc: int

    @classmethod
    def from_flush(cls, flush: StreamFlush) -> StreamFlushAck:
        """Create the acknowledgement that preserves every flush correlation field."""
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
    """Mutable per-Sound stream state because WSS commands arrive sequentially."""

    def __init__(self, *, session_id: str, receiver: GeneratedPlaybackReceiver) -> None:
        self._session_id = session_id
        self._receiver = receiver
        self._epochs: dict[str, int] = {}
        self._acknowledgements: dict[tuple[str, int, str], StreamFlushAck] = {}

    def apply(self, flush: StreamFlush) -> StreamFlushAck | None:
        """Apply one flush exactly once, returning an idempotent matching acknowledgement."""
        if flush.session_id != self._session_id or flush.cancellation_epoch < 0:
            return None
        key = (flush.stream_id, flush.cancellation_epoch, flush.request_id)
        duplicate = self._acknowledgements.get(key)
        if duplicate is not None:
            return duplicate
        previous_epoch = self._epochs.get(flush.stream_id)
        if previous_epoch is not None and flush.cancellation_epoch <= previous_epoch:
            return None
        if self._receiver.flush_stream(flush.stream_id, flush.target_generated_ssrc) is False:
            return None
        acknowledgement = StreamFlushAck.from_flush(flush)
        self._epochs[flush.stream_id] = flush.cancellation_epoch
        self._acknowledgements[key] = acknowledgement
        return acknowledgement
