# 快速开始

使用 Python 3.12 或更高版本。在本仓库中运行：

```bash
uv sync --locked
uv run pytest
```

`sound-receive` 是已部署的运行时。它只通过 WSS 从 Orchestrator 接收控制信息，只在已注册的 UDP sink 上接收 RTP。测试不需要扬声器设备、GPU 或凭据。

设置 `.env.example` 中的必要生产值：`ORCHESTRATOR_WS_URL` 必须是 WSS URL，`TRUSTED_LAN_TOKEN`、`SOUND_RTP_STREAM_ID`、`SOUND_RTP_BIND_PORT` 和 `SOUND_RTP_ADVERTISED_HOST` 必须非空。`SOUND_RTP_BIND_HOST` 的默认值为 `0.0.0.0`。使用以下命令启动接收运行时：

```bash
uv run sound-receive
```

它绑定 UDP，向 Orchestrator 注册 `media.rtp.sink.register`，然后等待匹配的 `media.stream.command`。接受命令后，它报告 ready、queued 和 playing 状态。匹配的 `cancel` 会报告 cancelled 状态，并阻止该流之后的数据包。TLS、token、网络和真实验证要求请参阅[部署指南](deployment.zh-CN.md)。

仅当 URL 是回环测试用的 `ws://` URL 且设置 `SOUND_ALLOW_LOOPBACK_WS=true` 时，才允许使用 `ws://`。生产环境绝不能使用此设置。

该诊断工具需要 PortAudio。Windows 和 macOS 上的 `sounddevice` wheel 已包含它。Linux 上请先安装发行版提供的 PortAudio 运行时软件包，再运行 `sound-play`。

使用以下命令列出输出设备及其数字索引：

```bash
uv run python -m sounddevice
```

`sound-play` 是本地诊断工具，不是已部署的播放方式。要运行它，请通过标准输入提供一个完整的 V2/PT96 L16 RTP 数据包，并配置其流格式。`BITNP_PLAYBACK_DEVICE` 是可选项。设为 `default` 或不设置时使用默认输出设备，也可使用设备列表中的索引，或使用能匹配输出设备的名称查询。

```bash
BITNP_PLAYBACK_DEVICE=default \
BITNP_SOUND_PLAY_STREAM_ID=demo-stream \
BITNP_SOUND_PLAY_SAMPLE_RATE=48000 \
BITNP_SOUND_PLAY_CHANNELS=1 \
uv run sound-play < packet.rtp
```

例如，将 `default` 替换为 `3` 可选择索引为 3 的设备，替换为 `USB Audio` 等名称查询也可选择设备。`sound-play` 从标准输入读取一个 RTP 数据包。它仅在 PortAudio 输出边界将网络字节序 L16 样本转换为设备原生 `int16`，在本地播放后停止并关闭。它不会从 Orchestrator 接收数据，也不会向 Orchestrator 报告数据。
