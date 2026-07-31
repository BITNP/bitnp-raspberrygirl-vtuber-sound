# Sound 用户文档

Sound 负责播放 Orchestrator 指定的 RTP 音频。部署入口是 `sound-receive`，本地诊断入口是 `sound-play`。

## 功能

- 绑定 UDP RTP sink。
- 通过 WSS 向 Orchestrator 注册播放端。
- 接收并播放匹配 `media.stream.command` 的 L16 RTP。
- 报告 queued、playing、cancelled 等播放状态。
- 在取消或 flush 时抑制过期音频。

## 快速开始

```bash
uv sync --locked
uv run pytest
```

## 使用指南

部署时配置 `.env.example` 中的 `ORCHESTRATOR_WS_URL`、`TRUSTED_LAN_TOKEN`、`ORCHESTRATOR_TLS_CA_PATH`、`SOUND_SESSION_ID`、`SOUND_RTP_STREAM_ID`、`SOUND_RTP_BIND_PORT` 和 `SOUND_RTP_ADVERTISED_HOST`。`ORCHESTRATOR_TLS_CA_PATH` 指向与 Orchestrator、Mic、Comments 共用的只读 PEM CA bundle，可包含内部根证书和中间证书。生产环境必须使用 WSS 和 token。

现场讲解链路中，Sound 应在 Orchestrator 后、Mic 前启动。它接收的是 Orchestrator 生成的 RTP，不是 Mic 原始 RTP。

`sound-play` 只从 stdin 读取一个完整 RTP packet 并用 PortAudio 本地播放。它不连接 Orchestrator，也不是部署播放路径。
