# VTuber Sound Service

Sound 是 Raspberry Girl 的策略无关播放模块。它只连接 Orchestrator：注册 UDP RTP sink，等待 Orchestrator 的 `media.stream.command`，只播放匹配的 L16 RTP 流，并通过规范控制通道报告 ready、queued、playing、cancelled 和 flush ack。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)
- [English quickstart](docs/quickstart.en.md)
- [快速开始](docs/quickstart.zh-CN.md)
- [架构](docs/architecture.zh-CN.md)
- [协议](docs/protocol.zh-CN.md)
- [测试](docs/testing.zh-CN.md)
- [部署](docs/deployment.zh-CN.md)
