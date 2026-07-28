# 测试

运行 `uv sync --locked`，再运行 `uv run pytest`。接收运行时测试使用伪造的 WSS 控制连接和 UDP 绑定。它们验证 UDP 在 WSS 连接前绑定、发送可信局域网 bearer header、sink 注册包含绑定端点、匹配命令接受 RTP、取消会屏蔽之后的 RTP，并报告 queued、playing 和 cancelled 状态。测试不需要音频设备。

真实部署验证请遵循[部署指南](deployment.zh-CN.md)中的四步检查：验证注册、命令和 RTP 播放、状态 envelope，以及取消屏蔽。使用 WSS 和真实的可信局域网 token。`ws://` 路由只允许用于设置 `SOUND_ALLOW_LOOPBACK_WS=true` 的显式回环测试，绝不能作为部署检查。

`sound-play` 是选择性的本地诊断工具，不是已部署的播放方式。它需要 PortAudio 和输出设备。先使用 `uv run python -m sounddevice` 列出设备，再将一个完整的 V2/PT96 L16 RTP 数据包通过标准输入传给 `sound-play`。如有需要，将 `BITNP_PLAYBACK_DEVICE` 设为 `default`、数字索引或可匹配的设备名称查询。该命令在本地播放后关闭，不会从 Orchestrator 接收数据，也不会向 Orchestrator 报告数据。此手动检查不属于无需硬件的测试套件。
