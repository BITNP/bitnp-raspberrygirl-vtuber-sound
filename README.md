# VTuber Sound Service

Sound 是树莓娘的策略无关播放模块。它只连接 Orchestrator：注册 UDP RTP sink，等待 Orchestrator 的 `media.stream.command`，只播放匹配的 L16 RTP 流，并通过规范控制通道报告 ready、queued、playing、cancelled 和 flush ack。

- [用户文档](docs/user.zh-CN.md)
- [开发者文档](docs/developer.zh-CN.md)

播放收尾独立于控制接收循环：收到 `media.stream.end` 后继续接收打断命令，
只有实际设备排空后才发送 `finished`；五秒超时会关闭排空中的设备并报告 `error`。
取消、替换和断线均清理对应排空任务。连接内保留已接纳命令的代次高水位，
结束或取消后不会重新启动旧命令。连续 RTP 丢失超过最大窗口时，接收器在
有效新包处重新缓冲，避免永久卡在旧序号；迟到包和重复包仍被丢弃。
