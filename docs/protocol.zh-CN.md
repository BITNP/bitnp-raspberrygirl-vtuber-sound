# 协议子集

Sound 是仅连接 Orchestrator 的客户端。它只从 Orchestrator 接收 RTP L16 媒体和控制信息，不与其他服务或前端建立对等连接。请将 `ORCHESTRATOR_REPO` 设置为 Orchestrator 检出目录，并读取 `$ORCHESTRATOR_REPO/schemas/protocol/envelope.schema.json` 和 `$ORCHESTRATOR_REPO/schemas/protocol/event-data.schema.json`。Sound 不复制 schema 或 fixture。

`sound-receive` 在连接 `ORCHESTRATOR_WS_URL` 前绑定配置的 UDP RTP 端点，并通过已认证的 WSS 连接发送 `media.rtp.sink.register`。它等待 `media.stream.command`，将已命令的 L16 流交给 RTP 接收器，然后发送 `media.rtp.sink.ready` 和 `media.stream.state`。匹配的规范 `cancel` 会屏蔽后续数据包，并报告 `cancelled` 状态。生产运行时没有 stdin 媒体路径。

`sound-play` 诊断工具从标准输入读取一个完整的 V2/PT96 RTP 数据包，在本地播放后关闭。它不是协议路径，不会从 Orchestrator 接收数据，也不会向 Orchestrator 报告数据。
