"""Own one Sound output lease and its packet, drain and notification lifecycle."""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic_ns
from typing import Final, Self

from sound.notification_writer import NotificationWriter, OutboundNotification
from sound.orchestrator_ws import (
    JsonValue,
    encode_envelope,
    optional_str,
    required_int,
    required_mapping,
    required_str,
)
from sound.rtp_playback import L16PlaybackSink, RtpPlaybackReceiver, RtpPlaybackState
from sound.stream_flush import (
    FlushDisposition,
    StreamFlush,
    StreamFlushAck,
    StreamFlushController,
)

L16_CODEC: Final[dict[str, JsonValue]] = {
    "format": "L16",
    "clock_rate_hz": 16_000,
    "channels": 1,
    "payload_type": 96,
    "samples_per_frame": 320,
}

_LOGGER = logging.getLogger(__name__)
_RTP_NOMINAL_GAP_MS: Final = 20.0
_RTP_LATE_GAP_MS: Final = 40.0
_DRAIN_TIMEOUT_SECONDS: Final = 5.0
_END_GRACE_SECONDS: Final = 0.100


def _rtp_packet_summary(packet: bytes) -> str:
    sequence = int.from_bytes(packet[2:4], "big") if len(packet) >= 4 else -1
    ssrc = int.from_bytes(packet[8:12], "big") if len(packet) >= 12 else -1
    digest = hashlib.sha256(packet).hexdigest()[:16]
    return f"bytes={len(packet)} sequence={sequence} ssrc={ssrc} sha256={digest}"


@dataclass(slots=True)
class _IngressTiming:
    """Per-output diagnostics that isolate upstream RTP delivery from playback."""

    packet_count: int = 0
    dropped_packets: int = 0
    late_gap_count: int = 0
    max_gap_ms: float = 0.0
    _last_arrival_ns: int | None = None

    def record_arrival(self) -> None:
        now_ns = monotonic_ns()
        previous_ns = self._last_arrival_ns
        self._last_arrival_ns = now_ns
        self.packet_count += 1
        if previous_ns is None:
            return
        gap_ms = (now_ns - previous_ns) / 1_000_000
        self.max_gap_ms = max(self.max_gap_ms, gap_ms)
        if gap_ms > _RTP_LATE_GAP_MS:
            self.late_gap_count += 1

    def record_drop(self) -> None:
        self.dropped_packets += 1

    def log(self, *, stream_id: str) -> None:
        _LOGGER.debug(
            "rtp_ingress_diagnostic stream=%s packets=%d drops=%d late_gaps=%d "
            + "max_gap_ms=%.3f nominal_gap_ms=%.1f",
            stream_id,
            self.packet_count,
            self.dropped_packets,
            self.late_gap_count,
            self.max_gap_ms,
            _RTP_NOMINAL_GAP_MS,
        )


@dataclass(frozen=True, slots=True)
class PlaybackCommand:
    command_id: str

    stream_id: str

    ssrc: int

    trace_id: str

    session_id: str

    seq: int

    turn_id: str | None

    segment_id: str | None

    cancellation_epoch: int

    rtp_sender_endpoint: tuple[str, int]


class PlaybackLifecycle:
    """Keep command identity and all completion ordering behind one interface."""

    def __init__(
        self,
        *,
        session_id: str,
        stream_id: str,
        playback_sink: L16PlaybackSink,
        notifications: NotificationWriter,
        jitter_target_ms: int,
        jitter_max_ms: int,
    ) -> None:
        self._session_id = session_id
        self._stream_id = stream_id
        self._sink = playback_sink
        self._notifications = notifications
        self._receiver = RtpPlaybackReceiver(
            playback_sink=playback_sink,
            jitter_target_ms=jitter_target_ms,
            jitter_max_ms=jitter_max_ms,
        )
        self._flushes = StreamFlushController(
            session_id=session_id, receiver=self._receiver
        )
        self._active: PlaybackCommand | None = None
        self._latest: PlaybackCommand | None = None
        self._minimum_epoch = 0
        self._playing = False
        self._ready = False
        self._has_samples = False
        self._end_requested = False
        self._drain_task: asyncio.Task[None] | None = None
        self._group: asyncio.TaskGroup | None = None
        self._closed = False
        self._packets: asyncio.Queue[tuple[bytes, PlaybackCommand]] = asyncio.Queue(
            maxsize=256
        )
        self._jitter_wakeup = asyncio.Event()
        self._timing = _IngressTiming()

    @asynccontextmanager
    async def running(self) -> AsyncGenerator[Self]:
        """Normal input completion drains; cancellation aborts and joins all work."""
        if self._group is not None or self._closed:
            raise RuntimeError("playback lifecycle cannot be reused")
        async with asyncio.TaskGroup() as group:
            self._group = group
            writer = group.create_task(self._notifications.run())
            playback = group.create_task(self._play_packets())
            jitter = group.create_task(self._advance_jitter())
            try:
                yield self
                # A normal WSS close may precede its authorized UDP tail.
                # Keep ingress open during the existing bounded end grace.
                await self._packets.join()
                if self._drain_task is not None:
                    await self._drain_task
                self._notifications.close()
                await writer
            finally:
                self._closed = True
                self._active = None
                self._cancel_drain()
                self._discard_packets()
                _ = playback.cancel()
                _ = jitter.cancel()
                _ = writer.cancel()
                self._receiver.close()
                self._group = None

    def receive_packet(
        self, packet: bytes, sender: tuple[str, int] | None = None
    ) -> None:
        command = self._active
        if self._closed or command is None:
            return
        self._timing.record_arrival()
        if self._timing.packet_count == 1:
            _LOGGER.debug(
                "rtp_ingress_started stream=%s sender=%s expected_sender=%s %s",
                command.stream_id,
                sender,
                command.rtp_sender_endpoint,
                _rtp_packet_summary(packet),
            )
        if sender is not None and sender != command.rtp_sender_endpoint:
            self._timing.record_drop()
            self._log_packet(command, packet, "sender_rejected")
            return
        if self._packets.full():
            self._timing.record_drop()
            self._log_packet(command, packet, "queue_full")
            return
        self._packets.put_nowait((packet, command))
        self._log_packet(command, packet, "queued")
        self._jitter_wakeup.set()

    async def handle_control(self, event: Mapping[str, JsonValue]) -> None:
        if self._closed or self._group is None:
            return
        if required_str(event, "session_id") != self._session_id:
            return
        _LOGGER.debug(
            "playback_control trace=%s session=%s seq=%s turn=%s segment=%s payload=%r outcome=received",
            event.get("trace_id"),
            self._session_id,
            event.get("seq"),
            event.get("turn_id"),
            event.get("segment_id"),
            event,
        )
        match required_str(event, "event_type"):
            case "media.stream.command":
                await self._command(event)
            case "cancel":
                await self._cancel(event)
            case "media.stream.flush":
                await self._flush(event)
            case "media.stream.end":
                self._end(event)
            case _:
                pass

    async def _command(self, event: Mapping[str, JsonValue]) -> None:
        candidate = _active_command(event)
        data = required_mapping(event, "data")
        if (
            candidate.stream_id != self._stream_id
            or required_mapping(data, "codec") != L16_CODEC
            or not 0 < candidate.ssrc <= 0xFFFF_FFFF
            or candidate.cancellation_epoch < self._minimum_epoch
            or (
                self._latest is not None
                and candidate.cancellation_epoch <= self._latest.cancellation_epoch
            )
        ):
            return
        # Invalidate the old identity before any await can resume its drain.
        self._cancel_drain()
        self._discard_packets()
        self._active = self._latest = candidate
        self._playing = self._end_requested = False
        self._ready = self._has_samples = False
        self._timing = _IngressTiming()
        self._receiver.announce_stream(
            stream_id=candidate.stream_id,
            sample_rate=16_000,
            channels=1,
            expected_ssrc=candidate.ssrc,
        )
        await self._notifications.begin_stream(candidate.stream_id)
        await self._notifications.send(
            OutboundNotification(self._ready_envelope(event))
        )
        await self._state(candidate, "queued")
        self._ready = True
        self._notify_playing()

    async def _cancel(self, event: Mapping[str, JsonValue]) -> None:
        command = self._active
        if command is None or optional_str(event, "segment_id") != (
            command.segment_id or command.stream_id
        ):
            return
        self._active = None
        self._playing = False
        self._cancel_drain()
        self._discard_packets()
        self._receiver.cancel_stream(command.stream_id)
        await self._notifications.invalidate_playing(command.stream_id)
        await self._state(command, "cancelled")

    async def _flush(self, event: Mapping[str, JsonValue]) -> None:
        acknowledgement = self._flushes.apply(_flush(event))
        if acknowledgement is None:
            return
        if acknowledgement.disposition is FlushDisposition.APPLIED:
            self._minimum_epoch = max(
                self._minimum_epoch, acknowledgement.cancellation_epoch
            )
            self._active = None
            self._playing = False
            self._cancel_drain()
            self._discard_packets()
            await self._notifications.invalidate_playing(acknowledgement.stream_id)
        message = self._flush_ack_envelope(event, acknowledgement)
        _LOGGER.debug(
            "playback_flush_ack payload=%s outcome=%s",
            message,
            acknowledgement.disposition,
        )
        await self._notifications.send(OutboundNotification(message))

    def _end(self, event: Mapping[str, JsonValue]) -> None:
        command = self._active
        data = required_mapping(event, "data")
        if (
            command is None
            or self._end_requested
            or (
                required_str(data, "stream_id") != command.stream_id
                or required_str(data, "command_id") != command.command_id
                or required_int(data, "cancellation_epoch")
                != command.cancellation_epoch
                or required_int(data, "ssrc") != command.ssrc
            )
        ):
            return
        assert self._group is not None
        self._end_requested = True
        self._drain_task = self._group.create_task(self._drain(command))

    async def _drain(self, command: PlaybackCommand) -> None:
        await asyncio.sleep(_END_GRACE_SECONDS)
        if self._active is not command:
            return
        self._timing.log(stream_id=command.stream_id)
        if not self._receiver.finish_stream(command.stream_id, command.ssrc):
            return
        state = "finished"
        try:
            async with asyncio.timeout(_DRAIN_TIMEOUT_SECONDS):
                await self._sink.wait_stream_drained(command.stream_id)
        except TimeoutError:
            if self._active is not command:
                return
            self._sink.close_stream(command.stream_id)
            state = "error"
        if self._active is not command:
            return
        self._active = None
        self._playing = False
        await self._state(command, state)

    def _cancel_drain(self) -> None:
        if self._drain_task is not None:
            _ = self._drain_task.cancel()
            self._drain_task = None

    def _discard_packets(self) -> None:
        while not self._packets.empty():
            packet, command = self._packets.get_nowait()
            self._log_packet(command, packet, "discarded")
            self._packets.task_done()

    async def _play_packets(self) -> None:
        while True:
            packet, command = await self._packets.get()
            try:
                if self._active is not command:
                    continue
                previous = self._last_playback_state()
                accepted = self._receiver.receive_packet(
                    packet, stream_id=command.stream_id
                )
                if not accepted:
                    self._timing.record_drop()
                self._has_samples |= self._last_playback_state() is not previous
                self._notify_playing()
                self._log_packet(command, packet, "played" if accepted else "rejected")
            finally:
                self._packets.task_done()

    async def _advance_jitter(self) -> None:
        while True:
            try:
                async with asyncio.timeout(0.020):
                    await self._jitter_wakeup.wait()
            except TimeoutError:
                pass
            self._jitter_wakeup.clear()
            previous = self._last_playback_state()
            self._receiver.tick()
            self._has_samples |= self._last_playback_state() is not previous
            self._notify_playing()

    def _last_playback_state(self) -> RtpPlaybackState | None:
        states = self._receiver.playback_states
        return states[-1] if states else None

    def _notify_playing(self) -> None:
        command = self._active
        if command is None or not self._ready or not self._has_samples or self._playing:
            return
        self._notifications.enqueue(
            OutboundNotification(
                self._state_envelope(command, "playing"),
                stream_id=command.stream_id,
                is_playing=True,
            )
        )
        self._playing = True

    def _log_packet(
        self, command: PlaybackCommand, packet: bytes, outcome: str
    ) -> None:
        if _LOGGER.isEnabledFor(logging.DEBUG):
            _LOGGER.debug(
                "playback_packet trace=%s session=%s seq=%s turn=%s segment=%s "
                "command=%s epoch=%s stream=%s kind=RTP codec=L16 %s outcome=%s",
                command.trace_id,
                command.session_id,
                command.seq,
                command.turn_id,
                command.segment_id,
                command.command_id,
                command.cancellation_epoch,
                command.stream_id,
                _rtp_packet_summary(packet),
                outcome,
            )

    async def _state(self, command: PlaybackCommand, state: str) -> None:
        _LOGGER.debug(
            "playback_state trace=%s session=%s seq=%s turn=%s segment=%s command=%s epoch=%s outcome=%s",
            command.trace_id,
            command.session_id,
            command.seq,
            command.turn_id,
            command.segment_id,
            command.command_id,
            command.cancellation_epoch,
            state,
        )
        await self._notifications.send(
            OutboundNotification(self._state_envelope(command, state))
        )

    def _ready_envelope(self, event: Mapping[str, JsonValue]) -> str:

        return encode_envelope(
            event_type="media.rtp.sink.ready",
            trace_id=required_str(event, "trace_id"),
            session_id=required_str(event, "session_id"),
            seq=required_int(event, "seq"),
            data={"stream_id": self._stream_id},
        )

    def _state_envelope(self, command: PlaybackCommand, state: str) -> str:

        data: dict[str, JsonValue] = {
            "command_id": command.command_id,
            "stream_id": self._stream_id,
            "state": state,
            "cancellation_epoch": command.cancellation_epoch,
        }

        return encode_envelope(
            event_type="media.stream.state",
            trace_id=command.trace_id,
            session_id=command.session_id,
            seq=command.seq,
            turn_id=command.turn_id,
            segment_id=command.segment_id,
            data=data,
        )

    def _flush_ack_envelope(
        self, event: Mapping[str, JsonValue], acknowledgement: StreamFlushAck
    ) -> str:

        return encode_envelope(
            event_type="media.stream.flush.ack",
            trace_id=required_str(event, "trace_id"),
            session_id=acknowledgement.session_id,
            seq=required_int(event, "seq"),
            turn_id=acknowledgement.turn_id,
            segment_id=acknowledgement.segment_id,
            data={
                "stream_id": acknowledgement.stream_id,
                "cancellation_epoch": acknowledgement.cancellation_epoch,
                "request_id": acknowledgement.request_id,
                "target_generated_ssrc": acknowledgement.target_generated_ssrc,
                "disposition": acknowledgement.disposition.value,
            },
        )


def _flush(event: Mapping[str, JsonValue]) -> StreamFlush:

    data = required_mapping(event, "data")

    return StreamFlush(
        session_id=required_str(event, "session_id"),
        stream_id=required_str(data, "stream_id"),
        turn_id=required_str(event, "turn_id"),
        segment_id=required_str(event, "segment_id"),
        cancellation_epoch=required_int(data, "cancellation_epoch"),
        request_id=required_str(data, "request_id"),
        target_generated_ssrc=required_int(data, "target_generated_ssrc"),
    )


def _active_command(event: Mapping[str, JsonValue]) -> PlaybackCommand:

    data = required_mapping(event, "data")

    return PlaybackCommand(
        command_id=required_str(data, "command_id"),
        stream_id=required_str(data, "stream_id"),
        ssrc=required_int(data, "ssrc"),
        trace_id=required_str(event, "trace_id"),
        session_id=required_str(event, "session_id"),
        seq=required_int(event, "seq"),
        turn_id=optional_str(event, "turn_id"),
        segment_id=optional_str(event, "segment_id"),
        cancellation_epoch=required_int(data, "cancellation_epoch"),
        rtp_sender_endpoint=(
            required_str(required_mapping(data, "rtp_sender_endpoint"), "host"),
            required_int(required_mapping(data, "rtp_sender_endpoint"), "port"),
        ),
    )
