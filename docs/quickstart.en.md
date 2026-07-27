# Quickstart

Use Python 3.12 or later. From this repository, run:

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run sound-health
```

The normal path replays RTP L16 audio and stream state locally. Tests need no speaker device, GPU, or credentials.
