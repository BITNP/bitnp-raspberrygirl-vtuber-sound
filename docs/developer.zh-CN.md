# Sound 开发者文档

Sound 是 Orchestrator-only 的 RTP playback client。它不感知业务模式，不接受 Mic 直连，也不向 Frontend 或 Comments 暴露端点。

## 技术栈

Python 3.12+、`uv`、`pytest`、`pytest-asyncio`、`websockets` 和 `sounddevice`。命令入口为 `sound-health`、`sound-play` 和 `sound-receive`。

## 架构与数据流

`sound-receive` 先绑定 UDP sink，再建立 WSS control connection，发送 `media.rtp.sink.register`。收到 Orchestrator 的 `media.stream.command` 后，它校验 stream、endpoint、codec 和 SSRC，随后接收 RTP 并推动播放状态。

```text
Orchestrator WSS command -> stream validation -> RTP receiver -> PortAudio output
Orchestrator UDP RTP ----/
```

## 通信协议

Sound 引用 Orchestrator schema。媒体契约固定为 L16、16 kHz、mono、payload type 96、每帧 320 samples。`media.stream.flush` 和取消命令必须按 cancellation epoch 抑制 stale RTP，并返回匹配 ack 或状态。

## 模块契约

- 必须只连接 Orchestrator。
- 必须先绑定 UDP，再注册 sink。
- 必须只播放匹配 command 的流。
- 必须报告 ready、queued、playing、cancelled 等规范状态。
- `sound-play` 只用于本地一包诊断。

## 验证

```bash
uv sync --locked
uv run pytest
```

真实部署验证应覆盖 sink 注册、命令匹配、RTP 播放、状态 envelope 和取消抑制。
