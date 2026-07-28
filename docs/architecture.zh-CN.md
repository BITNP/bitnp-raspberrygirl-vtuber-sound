# 架构

Sound 只连接 Orchestrator。它不感知模式，因此系统模式不会改变此契约。生产路径有两条来自 Orchestrator 的链路：已认证的 WSS 控制链路和 UDP RTP 媒体链路。Sound 不提供也不使用对等服务端点。

`sound-receive` 先绑定 `SOUND_RTP_BIND_HOST:SOUND_RTP_BIND_PORT`，再打开 `ORCHESTRATOR_WS_URL`，随后以 `SOUND_RTP_STREAM_ID` 注册 `SOUND_RTP_ADVERTISED_HOST` 和实际绑定端口。Orchestrator 通过 `media.stream.command` 命令已注册的 sink。命令必须指定配置的流 ID 和绑定端口，且必须使用 L16、16 kHz、单声道、负载类型 96、每帧 320 个采样及命令中的 SSRC。只有匹配活动命令的 RTP 才会送至 PortAudio。

运行时发送 `media.rtp.sink.ready`，然后发送值为 `queued` 和 `playing` 的 `media.stream.state`。匹配的规范 `cancel` 会关闭活动输出流，报告 `cancelled`，并屏蔽该流之后的 RTP。关闭运行时会关闭 UDP 绑定、WSS 连接和输出流。

RTP L16 在到达 PortAudio 输出边界前保持网络字节序数据，在该边界转换为原生 `int16`。`sound-play` 从标准输入读取一个完整的 V2/PT96 RTP 数据包后退出。它只是本地诊断工具，不属于此架构。
