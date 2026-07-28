# VTuber Sound Service

Mode agnostic RTP playback component for the Raspberry Girl VTuber system. Production `sound-receive` binds its UDP RTP sink, opens an authenticated WSS connection only to Orchestrator, registers that sink, and plays only the commanded L16 stream. It reports ready, queued, playing, and cancelled state through the canonical control channel. No peer service endpoint is supported.

Use `sound-receive` for deployment. `sound-play` is a local one-packet stdin and PortAudio diagnostic only. It isn't deployed playback and it doesn't connect to Orchestrator.

- [English quickstart](docs/quickstart.en.md)
- [简体中文快速开始](docs/quickstart.zh-CN.md)
- [English deployment guide](docs/deployment.en.md)
- [简体中文部署指南](docs/deployment.zh-CN.md)
