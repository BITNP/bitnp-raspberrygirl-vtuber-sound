# Testing

Run `uv sync --locked`, then `uv run pytest`. The receive-runtime tests use a fake WSS control connection and UDP binding. They verify that UDP binds before WSS connection, the trusted-LAN bearer header is sent, sink registration contains the bound endpoint, a matching command accepts RTP, cancellation suppresses later RTP, and queued, playing, and cancelled states are reported. The suite needs no audio device.

For a real deployment verification, follow the four-step check in the [deployment guide](deployment.en.md): verify registration, command and RTP playback, state envelopes, then cancellation suppression. Use WSS and a real trusted-LAN token. A `ws://` route is allowed only for an explicit loopback test with `SOUND_ALLOW_LOOPBACK_WS=true`, never as a deployment check.

`sound-play` is an opt-in local diagnostic, not deployed playback. It requires PortAudio and an output device. First list devices with `uv run python -m sounddevice`, then feed one complete V2/PT96 L16 RTP packet to `sound-play` on standard input. Set `BITNP_PLAYBACK_DEVICE` to `default`, a numeric index, or a matching device-name query as needed. The command plays locally, then closes. It neither receives from nor reports to Orchestrator. This manual check is not part of the hardware-free test suite.
