# Testing

Run `uv sync --locked`, then `uv run pytest`. The tests cover RTP and stream state behavior without an audio device. Run `ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run sound-health` to exercise the health command.
