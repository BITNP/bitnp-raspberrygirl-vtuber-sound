# Deployment

Sound has one control peer, Orchestrator. Production control uses WSS and media arrives on the configured UDP RTP sink. Don't configure a peer service endpoint.

Copy `.env.example` into deployment configuration and set these values outside version control:

| Variable | Deployment value |
| --- | --- |
| `ORCHESTRATOR_WS_URL` | Orchestrator's `wss://` control URL. The TLS certificate must be trusted by the Sound host. |
| `TRUSTED_LAN_TOKEN` | The trusted-LAN bearer token. Keep the actual value in the deployment secret store. It is required with WSS. |
| `SOUND_RTP_STREAM_ID` | The stable sink identity that Orchestrator commands. |
| `SOUND_RTP_BIND_HOST` | Local address for the UDP listener. It defaults to `0.0.0.0` when unset. |
| `SOUND_RTP_BIND_PORT` | UDP listener port, from 1 through 65535. |
| `SOUND_RTP_ADVERTISED_HOST` | Address Orchestrator uses to send UDP RTP to this host. |
| `SOUND_TRACE_ID`, `SOUND_SESSION_ID` | Optional registration envelope identifiers. Both default to `sound-receive`. |
| `BITNP_PLAYBACK_DEVICE` | Optional PortAudio device. Empty or `default` uses the system default. A numeric index or device-name query selects another output. |

`SOUND_RTP_BIND_PORT` is the desired local port. `sound-receive` registers the actual bound port with Orchestrator, so the command must use that registered port and the configured stream ID. Allow the selected UDP port only from the trusted Orchestrator network path. Never commit the bearer token, a private key, or generated certificates.

Start the runtime with `uv run sound-receive`. It binds UDP before making the WSS connection, sends `media.rtp.sink.register`, then waits for the command. A valid command must use L16, 16 kHz, mono, payload type 96, 320 samples per frame, the registered endpoint, and its SSRC.

`ws://` is rejected in production. The only exception is a loopback test URL whose host is `127.0.0.1`, `localhost`, or `::1`, with `SOUND_ALLOW_LOOPBACK_WS=true`. That switch is test-only. Don't set it for deployment and don't use it to bypass WSS or TLS.

PortAudio is required for playback. The `sounddevice` wheel includes it on Windows and macOS. On Linux, install the distribution's PortAudio runtime package. List available output devices with `uv run python -m sounddevice`.

Verify a real deployment in this order:

1. Start `sound-receive` with the production WSS URL, trusted-LAN token, reachable advertised host, UDP port, and a working PortAudio device.
2. Confirm Orchestrator receives `media.rtp.sink.register` with the expected stream ID, advertised host, and bound port.
3. Send a matching `media.stream.command`, then RTP with the commanded SSRC to that UDP endpoint. Confirm `media.rtp.sink.ready`, followed by `media.stream.state` values `queued` and `playing`.
4. Send a matching canonical `cancel`. Confirm `media.stream.state` reports `cancelled` and later RTP for that stream isn't played.

`sound-play` is a separate local diagnostic. It reads one complete V2/PT96 RTP packet from standard input, plays it once, then closes. It doesn't connect to Orchestrator and isn't deployed playback.
