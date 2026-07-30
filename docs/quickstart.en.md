# Quickstart

Use Python 3.12 or later. From this repository, run:

```bash
uv sync --locked
uv run pytest
```

`sound-receive` is the deployed runtime. It accepts control only from Orchestrator over WSS and accepts RTP only on its registered UDP sink. Tests need no speaker device, GPU, or credentials.

Set the required production values from `.env.example`: `ORCHESTRATOR_WS_URL` must be a WSS URL, `TRUSTED_LAN_TOKEN`, `SOUND_RTP_STREAM_ID`, `SOUND_RTP_BIND_PORT`, and `SOUND_RTP_ADVERTISED_HOST` must be nonempty. `SOUND_RTP_BIND_HOST` defaults to `0.0.0.0`. Start the receive runtime with:

```bash
uv run sound-receive
```

It binds UDP, registers `media.rtp.sink.register` with Orchestrator, and waits for a matching `media.stream.command`. On acceptance it reports ready, queued, and playing state. A matching `cancel` reports cancelled state and blocks later packets for that stream. See the [deployment guide](deployment.en.md) for TLS, token, network, and live verification requirements.

For the onsite spoken-dialogue loop, set `SOUND_SESSION_ID` and `SOUND_RTP_STREAM_ID` to the same values Mic uses, and set `ORCHESTRATOR_WS_URL` to the same `/control` WSS endpoint. Start Sound after Orchestrator and before Mic. Sound stays strategy-agnostic and never has a direct Mic endpoint.

`ws://` is only permitted for a loopback test URL when `SOUND_ALLOW_LOOPBACK_WS=true`. Never use that setting in production.

The diagnostic needs PortAudio. The `sounddevice` wheel includes it on Windows and macOS. On Linux, install the distribution's PortAudio runtime package before running `sound-play`.

List output devices and their numeric indexes with:

```bash
uv run python -m sounddevice
```

`sound-play` is a local diagnostic, not deployed playback. To run it, provide one complete V2/PT96 L16 RTP packet on standard input and configure its stream format. `BITNP_PLAYBACK_DEVICE` is optional. Set it to `default` or leave it unset for the default output device, use an index from the device list, or use a name query that matches an output device.

```bash
BITNP_PLAYBACK_DEVICE=default \
BITNP_SOUND_PLAY_STREAM_ID=demo-stream \
BITNP_SOUND_PLAY_SAMPLE_RATE=48000 \
BITNP_SOUND_PLAY_CHANNELS=1 \
uv run sound-play < packet.rtp
```

For example, replace `default` with `3` to select device index 3, or with a name query such as `USB Audio`. `sound-play` reads one RTP packet from standard input. It converts network-order L16 samples to device-native `int16` only at the PortAudio output boundary, plays locally, then stops and closes. It doesn't receive from or report to Orchestrator.
