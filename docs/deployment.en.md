# Deployment

Configure the service through `.env.example`, with secrets kept outside the repository. Sound terminates the RTP L16 playback boundary and reports stream state to Orchestrator. Use `uv run sound-health` for the health command. Do not connect Sound directly to Mic, Comments, or the frontend.
