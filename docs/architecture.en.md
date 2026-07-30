# Architecture

Sound is an Orchestrator-only client. It is strategy agnostic, so product scenarios and Orchestrator interaction choices do not change this contract. The production path has two routes from Orchestrator: authenticated WSS control and UDP RTP media. Sound doesn't expose or use a peer service endpoint.

`sound-receive` first binds `SOUND_RTP_BIND_HOST:SOUND_RTP_BIND_PORT`, then opens `ORCHESTRATOR_WS_URL`, and registers `SOUND_RTP_ADVERTISED_HOST` plus the bound port as `SOUND_RTP_STREAM_ID`. Orchestrator commands the registered sink with `media.stream.command`. The command must name the configured stream and bound port, and must use L16, 16 kHz, mono, payload type 96, 320 samples per frame, and the command SSRC. Only RTP that matches the active command reaches PortAudio.

The runtime sends `media.rtp.sink.ready`, then `media.stream.state` values `queued` and `playing`. A matching canonical `cancel` closes the active output stream, reports `cancelled`, and suppresses later RTP for that stream. Shutdown closes the UDP binding, WSS connection, and output stream.

RTP L16 stays in network byte order until the PortAudio output boundary, where it is converted to native `int16`. `sound-play` reads one complete V2/PT96 RTP packet from standard input and exits. It is a local diagnostic, not part of this architecture.
