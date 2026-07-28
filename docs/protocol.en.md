# Protocol Subset

The target protocol makes Sound an Orchestrator-only client: it may receive RTP L16 media and control from Orchestrator, and it must not establish peer connections with other services or the frontend. Set `ORCHESTRATOR_REPO` to an Orchestrator checkout and read `$ORCHESTRATOR_REPO/schemas/protocol/envelope.schema.json` and `$ORCHESTRATOR_REPO/schemas/protocol/event-data.schema.json`. Sound does not copy schemas or fixtures.

`sound-receive` binds its configured UDP RTP endpoint before connecting to `ORCHESTRATOR_WS_URL` over authenticated WSS. It sends `media.rtp.sink.register`, waits for `media.stream.command`, announces the commanded L16 stream to the RTP receiver, then sends `media.rtp.sink.ready` and `media.stream.state`. A matching canonical `cancel` suppresses later packets and reports `cancelled` state. The production runtime has no stdin media path.

The `sound-play` diagnostic reads one complete V2/PT96 RTP packet from standard input, plays it locally, then closes. It is not a protocol path and does not receive from or report to Orchestrator.
