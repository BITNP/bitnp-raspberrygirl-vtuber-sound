
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from enum import Enum
from time import monotonic_ns
from typing import Final, NewType, Protocol

StreamId = NewType("StreamId", str)

RtpTimestamp = NewType("RtpTimestamp", int)

PlaybackPositionSamples = NewType("PlaybackPositionSamples", int)


_RTP_HEADER_BYTES: Final = 12

_RTP_VERSION: Final = 2

_L16_PAYLOAD_TYPE: Final = 96

_L16_FRAME_BYTES: Final = 640


class StreamStatus(Enum):

    ACTIVE = "active"

    CANCELLED = "cancelled"

    FINISHED = "finished"


@dataclass(frozen=True, slots=True)
class RtpPlaybackState:

    stream_id: StreamId

    rtp_timestamp: RtpTimestamp

    playback_position_samples: PlaybackPositionSamples


@dataclass(frozen=True, slots=True)
class L16PlaybackFrame:

    stream_id: StreamId

    sample_rate: int

    channels: int

    payload: bytes


class L16PlaybackSink(Protocol):

    def write(self, frame: L16PlaybackFrame) -> None:

        ...

    def close_stream(self, stream_id: str) -> None:

        ...

    def close(self) -> None:

        ...


@dataclass(frozen=True, slots=True)
class _AnnouncedStream:

    sample_rate: int

    channels: int

    expected_ssrc: int | None

    status: StreamStatus

    playback_position_samples: PlaybackPositionSamples


@dataclass(frozen=True, slots=True)
class _L16RtpPacket:

    sequence: int

    timestamp: RtpTimestamp

    ssrc: int

    l16_sample_count: int

    payload: bytes


@dataclass(slots=True)
class _JitterState:
    packets: dict[int, _L16RtpPacket] = field(default_factory=dict)
    expected_sequence: int | None = None
    started: bool = False
    missing_since_ms: int | None = None
    last_timestamp: RtpTimestamp | None = None


class RtpPlaybackReceiver:

    def __init__(
        self,
        *,
        playback_sink: L16PlaybackSink | None = None,
        jitter_target_ms: int = 20,
        jitter_max_ms: int = 200,
        clock_ms: Callable[[], int] = lambda: monotonic_ns() // 1_000_000,
    ) -> None:

        if jitter_target_ms < 20 or jitter_target_ms % 20:
            raise ValueError("jitter_target_ms")
        if jitter_max_ms < jitter_target_ms or jitter_max_ms % 20:
            raise ValueError("jitter_max_ms")

        self._streams: dict[StreamId, _AnnouncedStream] = {}

        self._jitter: dict[StreamId, _JitterState] = {}

        self._playback_sink: L16PlaybackSink | None = playback_sink

        self._playback_states: deque[RtpPlaybackState] = deque(maxlen=512)
        self._target_frames: int = jitter_target_ms // 20
        self._max_frames: int = jitter_max_ms // 20
        self._target_ms = jitter_target_ms
        self._clock_ms = clock_ms

    @property
    def playback_states(self) -> list[RtpPlaybackState]:
        return list(self._playback_states)

    def announce_stream(
        self,
        *,
        stream_id: str,
        sample_rate: int,
        channels: int,
        expected_ssrc: int | None = None,
    ) -> None:

        if (
            stream_id == ""
            or sample_rate <= 0
            or channels <= 0
            or (expected_ssrc is not None and not 0 < expected_ssrc <= 0xFFFF_FFFF)
        ):
            return

        resolved_stream_id = StreamId(stream_id)

        existing_stream = self._streams.get(resolved_stream_id)

        if existing_stream is not None and self._playback_sink is not None:
            self._playback_sink.close_stream(stream_id)

        self._streams[resolved_stream_id] = _AnnouncedStream(
            sample_rate=sample_rate,
            channels=channels,
            expected_ssrc=expected_ssrc,
            status=StreamStatus.ACTIVE,
            playback_position_samples=PlaybackPositionSamples(0),
        )
        self._jitter[resolved_stream_id] = _JitterState()

    def cancel_stream(self, stream_id: str) -> None:

        resolved_stream_id = StreamId(stream_id)

        stream = self._streams.get(resolved_stream_id)

        if stream is None:
            return

        self._streams[resolved_stream_id] = replace(
            stream, status=StreamStatus.CANCELLED
        )

        if self._playback_sink is not None:
            self._playback_sink.close_stream(stream_id)

    def flush_stream(self, stream_id: str, target_generated_ssrc: int) -> bool:

        stream = self._streams.get(StreamId(stream_id))

        if stream is None or stream.expected_ssrc != target_generated_ssrc:
            return False

        self.cancel_stream(stream_id)

        return True

    def finish_stream(self, stream_id: str, expected_ssrc: int) -> bool:
        stream = self._streams.get(StreamId(stream_id))
        if (
            stream is None
            or stream.status is not StreamStatus.ACTIVE
            or stream.expected_ssrc != expected_ssrc
        ):
            return False
        resolved_stream_id = StreamId(stream_id)
        self._drain_jitter(resolved_stream_id, final=True)
        self._streams[resolved_stream_id] = replace(
            self._streams[resolved_stream_id], status=StreamStatus.FINISHED
        )
        if self._playback_sink is not None:
            finish_stream = getattr(self._playback_sink, "finish_stream", None)
            if finish_stream is None:
                self._playback_sink.close_stream(stream_id)
            else:
                finish_stream(stream_id)
        return True

    def receive_packet(self, packet: bytes, *, stream_id: str | None = None) -> bool:

        parsed_packet = _parse_l16_rtp_packet(packet)

        if parsed_packet is None:
            return False

        resolved_stream_id = self._resolve_stream_id(stream_id)

        if resolved_stream_id is None:
            return False

        stream = self._streams.get(resolved_stream_id)

        if stream is None:
            return False

        if (
            stream.expected_ssrc is not None
            and parsed_packet.ssrc != stream.expected_ssrc
        ):
            return False

        if parsed_packet.l16_sample_count % stream.channels != 0:
            return False

        if stream.status is not StreamStatus.ACTIVE:
            return False
        jitter = self._jitter.setdefault(resolved_stream_id, _JitterState())
        expected = jitter.expected_sequence
        if expected is None:
            jitter.expected_sequence = parsed_packet.sequence
            expected = parsed_packet.sequence
        distance = (parsed_packet.sequence - expected) & 0xFFFF
        if distance >= 0x8000 or distance >= self._max_frames:
            return False
        if parsed_packet.sequence in jitter.packets:
            return False
        jitter.packets[parsed_packet.sequence] = parsed_packet
        self._drain_jitter(resolved_stream_id, final=False)
        return True

    def tick(self) -> None:
        """Advance expired loss deadlines even when no new datagram arrives."""
        for stream_id, stream in tuple(self._streams.items()):
            if stream.status is StreamStatus.ACTIVE:
                self._drain_jitter(stream_id, final=False)

    def close(self) -> None:

        if self._playback_sink is not None:
            self._playback_sink.close()

    def _drain_jitter(self, stream_id: StreamId, *, final: bool) -> None:
        jitter = self._jitter.get(stream_id)
        stream = self._streams.get(stream_id)
        if jitter is None or stream is None or jitter.expected_sequence is None:
            return
        if not jitter.started:
            if not final and len(jitter.packets) < self._target_frames:
                return
            jitter.started = True
        while jitter.packets:
            sequence = jitter.expected_sequence
            packet = jitter.packets.pop(sequence, None)
            if packet is None:
                if not final:
                    now_ms = self._clock_ms()
                    if jitter.missing_since_ms is None:
                        jitter.missing_since_ms = now_ms
                        return
                    if now_ms - jitter.missing_since_ms < self._target_ms:
                        return
                timestamp = RtpTimestamp(
                    (int(jitter.last_timestamp) + 320)
                    & 0xFFFF_FFFF
                    if jitter.last_timestamp is not None
                    else 0
                )
                packet = _L16RtpPacket(
                    sequence=sequence,
                    timestamp=timestamp,
                    ssrc=stream.expected_ssrc or 1,
                    l16_sample_count=320,
                    payload=b"\x00" * _L16_FRAME_BYTES,
                )
                jitter.missing_since_ms = None
            else:
                jitter.missing_since_ms = None
            self._emit_packet(stream_id, packet)
            jitter.last_timestamp = packet.timestamp
            jitter.expected_sequence = (sequence + 1) & 0xFFFF

    def _emit_packet(self, stream_id: StreamId, packet: _L16RtpPacket) -> None:
        stream = self._streams[stream_id]
        playback_position = PlaybackPositionSamples(
            int(stream.playback_position_samples)
            + packet.l16_sample_count // stream.channels
        )
        if self._playback_sink is not None:
            self._playback_sink.write(
                L16PlaybackFrame(
                    stream_id=stream_id,
                    sample_rate=stream.sample_rate,
                    channels=stream.channels,
                    payload=packet.payload,
                )
            )
        self._streams[stream_id] = replace(
            stream, playback_position_samples=playback_position
        )
        self._playback_states.append(
            RtpPlaybackState(stream_id, packet.timestamp, playback_position)
        )

    def _resolve_stream_id(self, stream_id: str | None) -> StreamId | None:

        if stream_id is not None:
            return StreamId(stream_id)

        active_stream_ids = [
            candidate_stream_id
            for candidate_stream_id, stream in self._streams.items()
            if stream.status is StreamStatus.ACTIVE
        ]

        if len(active_stream_ids) != 1:
            return None

        return active_stream_ids[0]


def _parse_l16_rtp_packet(packet: bytes) -> _L16RtpPacket | None:

    if len(packet) < _RTP_HEADER_BYTES:
        return None

    first_byte = packet[0]

    second_byte = packet[1]

    version = first_byte >> 6

    has_padding = bool(first_byte & 0b0010_0000)

    has_extension = bool(first_byte & 0b0001_0000)

    csrc_count = first_byte & 0b0000_1111

    payload_type = second_byte & 0b0111_1111

    ssrc = int.from_bytes(packet[8:12], byteorder="big")

    payload = packet[_RTP_HEADER_BYTES:]

    if (
        version != _RTP_VERSION
        or has_padding
        or has_extension
        or csrc_count != 0
        or payload_type != _L16_PAYLOAD_TYPE
        or ssrc == 0
        or len(payload) != _L16_FRAME_BYTES
    ):
        return None

    return _L16RtpPacket(
        sequence=int.from_bytes(packet[2:4], byteorder="big"),
        timestamp=RtpTimestamp(int.from_bytes(packet[4:8], byteorder="big")),
        ssrc=ssrc,
        l16_sample_count=len(payload) // 2,
        payload=payload,
    )
