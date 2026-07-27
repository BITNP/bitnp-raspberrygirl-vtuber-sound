from dataclasses import dataclass, replace
from enum import Enum
from typing import Final, NewType, assert_never

StreamId = NewType("StreamId", str)
RtpTimestamp = NewType("RtpTimestamp", int)
PlaybackPositionSamples = NewType("PlaybackPositionSamples", int)

_RTP_HEADER_BYTES: Final = 12
_RTP_VERSION: Final = 2
_L16_PAYLOAD_TYPE: Final = 96


class StreamStatus(Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RtpPlaybackState:
    stream_id: StreamId
    rtp_timestamp: RtpTimestamp
    playback_position_samples: PlaybackPositionSamples


@dataclass(frozen=True, slots=True)
class _AnnouncedStream:
    sample_rate: int
    channels: int
    status: StreamStatus
    playback_position_samples: PlaybackPositionSamples


@dataclass(frozen=True, slots=True)
class _L16RtpPacket:
    timestamp: RtpTimestamp
    l16_sample_count: int


class RtpPlaybackReceiver:
    """Tracks deterministic L16 RTP playback for Orchestrator-announced streams."""

    def __init__(self) -> None:
        self._streams: dict[StreamId, _AnnouncedStream] = {}
        self.playback_states: list[RtpPlaybackState] = []

    def announce_stream(self, *, stream_id: str, sample_rate: int, channels: int) -> None:
        if stream_id == "" or sample_rate <= 0 or channels <= 0:
            return
        self._streams[StreamId(stream_id)] = _AnnouncedStream(
            sample_rate=sample_rate,
            channels=channels,
            status=StreamStatus.ACTIVE,
            playback_position_samples=PlaybackPositionSamples(0),
        )

    def cancel_stream(self, stream_id: str) -> None:
        resolved_stream_id = StreamId(stream_id)
        stream = self._streams.get(resolved_stream_id)
        if stream is None:
            return
        self._streams[resolved_stream_id] = replace(stream, status=StreamStatus.CANCELLED)

    def receive_packet(self, packet: bytes, *, stream_id: str | None = None) -> None:
        parsed_packet = _parse_l16_rtp_packet(packet)
        if parsed_packet is None:
            return
        resolved_stream_id = self._resolve_stream_id(stream_id)
        if resolved_stream_id is None:
            return
        stream = self._streams.get(resolved_stream_id)
        if stream is None:
            return
        if parsed_packet.l16_sample_count % stream.channels != 0:
            return
        match stream.status:
            case StreamStatus.ACTIVE:
                playback_position = PlaybackPositionSamples(
                    int(stream.playback_position_samples)
                    + parsed_packet.l16_sample_count // stream.channels
                )
            case StreamStatus.CANCELLED:
                return
            case unreachable:
                assert_never(unreachable)
        self._streams[resolved_stream_id] = replace(
            stream,
            playback_position_samples=playback_position,
        )
        self.playback_states.append(
            RtpPlaybackState(
                stream_id=resolved_stream_id,
                rtp_timestamp=parsed_packet.timestamp,
                playback_position_samples=playback_position,
            )
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
        or len(payload) % 2 != 0
    ):
        return None
    return _L16RtpPacket(
        timestamp=RtpTimestamp(int.from_bytes(packet[4:8], byteorder="big")),
        l16_sample_count=len(payload) // 2,
    )
