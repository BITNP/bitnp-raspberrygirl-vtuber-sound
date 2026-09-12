# VTuber Sound Service

Sound 是树莓娘的策略无关播放模块。它只连接 Orchestrator：注册 UDP RTP sink，等待 Orchestrator 的 `media.stream.command`，只播放匹配的 L16 RTP 流，并通过规范控制通道报告 ready、queued、playing、cancelled 和 flush ack。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)
