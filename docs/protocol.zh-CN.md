# 协议子集

Sound 是中心客户端。请将 `ORCHESTRATOR_REPO` 设置为 Orchestrator 检出目录，并读取 `$ORCHESTRATOR_REPO/schemas/protocol/envelope.schema.json` 和 `$ORCHESTRATOR_REPO/schemas/protocol/event-data.schema.json`。Sound 处理自身的 RTP L16 媒体及 `media.stream.command` 或 `media.stream.state` 子集，不复制 schema 或 fixture。
