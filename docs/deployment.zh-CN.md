# 部署

Sound 只有一个控制对端，即 Orchestrator。生产控制使用 WSS，媒体通过配置的 UDP RTP sink 到达。不要配置对等服务端点。

将 `.env.example` 复制到部署配置，并在版本控制外设置以下值：

| 变量 | 部署值 |
| --- | --- |
| `ORCHESTRATOR_WS_URL` | Orchestrator 的 `wss://` 控制 URL。Sound 主机必须信任其 TLS 证书。 |
| `TRUSTED_LAN_TOKEN` | 可信局域网 bearer token。将实际值放在部署密钥存储中。使用 WSS 时必须设置。 |
| `SOUND_RTP_STREAM_ID` | Orchestrator 命令的稳定 sink 标识。现场链路中它必须等于 Mic 的 `BITNP_MIC_RTP_STREAM_ID`。 |
| `SOUND_RTP_BIND_HOST` | UDP 监听器的本地地址。未设置时默认值为 `0.0.0.0`。 |
| `SOUND_RTP_BIND_PORT` | UDP 监听器端口，范围为 1 至 65535。 |
| `SOUND_RTP_ADVERTISED_HOST` | Orchestrator 用于向此主机发送 UDP RTP 的地址。 |
| `SOUND_TRACE_ID`、`SOUND_SESSION_ID` | 可选的注册 envelope 标识。现场链路中 `SOUND_SESSION_ID` 必须等于 Mic 的 `BITNP_SESSION_ID`。 |
| `BITNP_PLAYBACK_DEVICE` | 可选的 PortAudio 设备。空值或 `default` 使用系统默认值。数字索引或设备名称查询可选择其他输出。 |

`SOUND_RTP_BIND_PORT` 是期望的本地端口。`sound-receive` 会向 Orchestrator 注册实际绑定的端口，因此命令必须使用该注册端口和配置的流 ID。仅允许受信任的 Orchestrator 网络路径访问所选 UDP 端口。不得提交 bearer token、私钥或生成的证书。

使用 `uv run sound-receive` 启动运行时。它在建立 WSS 连接前绑定 UDP，发送 `media.rtp.sink.register`，然后等待命令。有效命令必须使用 L16、16 kHz、单声道、负载类型 96、每帧 320 个采样、已注册端点及其 SSRC。Sound 没有现场策略设置，只接受来自 Orchestrator 中心的生成 RTP。

生产环境会拒绝 `ws://`。唯一例外是主机为 `127.0.0.1`、`localhost` 或 `::1` 的回环测试 URL，且必须设置 `SOUND_ALLOW_LOOPBACK_WS=true`。此开关仅供测试使用。部署时不要设置它，也不要用它绕过 WSS 或 TLS。

播放需要 PortAudio。Windows 和 macOS 上的 `sounddevice` wheel 已包含它。Linux 上请安装发行版提供的 PortAudio 运行时软件包。使用 `uv run python -m sounddevice` 列出可用输出设备。

按以下顺序验证真实部署：

1. 使用生产 WSS URL、可信局域网 token、可访问的已发布主机、UDP 端口和可用 PortAudio 设备启动 `sound-receive`。
2. 确认 Orchestrator 收到 `media.rtp.sink.register`，其中包含预期的流 ID、已发布主机和绑定端口。
3. 发送匹配的 `media.stream.command`，再向该 UDP 端点发送使用命令 SSRC 的 RTP。确认收到 `media.rtp.sink.ready`，随后 `media.stream.state` 的值为 `queued` 和 `playing`。
4. 发送匹配的规范 `cancel`。确认 `media.stream.state` 报告 `cancelled`，且该流之后的 RTP 不会播放。

`sound-play` 是独立的本地诊断工具。它从标准输入读取一个完整的 V2/PT96 RTP 数据包，播放一次后关闭。它不连接 Orchestrator，也不是已部署的播放方式。
