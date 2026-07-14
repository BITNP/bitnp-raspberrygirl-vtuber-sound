from dataclasses import dataclass

from sound.config import OrchestratorWsUrl, ServiceConfig
from sound.playback import PlaybackCancelCommand, PlaybackCommand, PlaybackService, SoundEvent, SoundEventSink


@dataclass(frozen=True, slots=True)
class OrchestratorWebSocketBoundary:
    config: ServiceConfig

    def target_url(self) -> OrchestratorWsUrl:
        return self.config.orchestrator_ws_url

    def describe_placeholder(self) -> str:
        return "sound WebSocket boundary placeholder targets Orchestrator only"

    def receive_play_command(self, service: PlaybackService, command: PlaybackCommand) -> None:
        service.enqueue(command)

    def receive_cancel_command(self, service: PlaybackService, command: PlaybackCancelCommand) -> None:
        service.cancel(command)

    def send_sound_event(self, sink: SoundEventSink, event: SoundEvent) -> None:
        sink.receive_sound_event(event)
