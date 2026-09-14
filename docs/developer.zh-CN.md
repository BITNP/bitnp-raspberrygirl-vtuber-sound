# Sound 开发者文档

Sound 是 Orchestrator-only 的 RTP playback client。它不感知业务策略，不接受 Mic 直连，也不向 Frontend 或 Comments 暴露端点。系统架构、部署编排和规范协议以 [Orchestrator 开发者文档](../../bitnp-raspberrygirl-vtuber-orchestrator/docs/developer.zh-CN.md) 为准；通过 `ORCHESTRATOR_REPO` 引用其 schema。

## 技术栈

Python 3.12+、`uv`、`pytest`、`pytest-asyncio`、`websockets` 和 `sounddevice`。命令入口为 `sound-health`、`sound-play` 和 `sound-receive`。

## 架构与数据流

`sound-receive` 先绑定 UDP sink，再建立 WSS control connection，发送 `media.rtp.sink.register`。收到 Orchestrator 的 `media.stream.command` 后，它校验 stream、endpoint、codec 和 SSRC，随后接收 RTP 并推动播放状态。

```text
Orchestrator WSS command -> stream validation -> RTP receiver -> PortAudio output
Orchestrator UDP RTP ----/
```

## 通信协议

Sound 通过 `ORCHESTRATOR_REPO` 引用 Orchestrator 的 `schemas/protocol/envelope.schema.json` 和 `schemas/protocol/event-data.schema.json`，不复制 schema 或 fixture。媒体契约固定为 L16、16 kHz、mono、payload type 96、每帧 320 samples。`media.stream.flush` 和取消命令必须按 cancellation epoch 抑制 stale RTP，并返回匹配 ack 或状态。

## 模块契约

- 必须只连接 Orchestrator。
- 必须先绑定 UDP，再注册 sink。
- 必须只播放匹配 command 的流。
- 必须报告 ready、queued、playing、finished、cancelled、error 等规范状态；`finished` 只能在 jitter/本地播放队列耗尽、PortAudio callback 停止且 stream 关闭后发送。五秒 drain 超时只发送 `error`。异常 WSS 关闭会完整释放本次连接的 UDP、队列和 worker，再按带抖动的上限 10 秒退避重连。
- RTP jitter 默认以 60 ms 为目标、200 ms 为硬上限；乱序包在租约内重排，缺失序号超过 60 ms 后只补一个 20 ms L16 静音帧，再继续等待后续缺口。收到 `media.stream.end` 后即使未达到初始目标也会排空短流。
- `sound-play` 只用于本地一包诊断。
- 生产部署在 `ORCHESTRATOR_TLS_CA_PATH` 设置同一个只读 PEM CA bundle，用于校验 Orchestrator WSS 证书。该路径也由 Orchestrator、Mic、Comments 使用；主机系统信任库只是已安装相同 CA 时的可选替代。

本地安装和测试见[用户文档](user.zh-CN.md)。受信任局域网 `ws://` 联调必须设置 `SOUND_ALLOW_LOOPBACK_WS=true`，并继续提供 Sound 专属 `TRUSTED_LAN_TOKEN`；集中步骤见[受信任局域网明文联调指南](../../bitnp-raspberrygirl-vtuber-orchestrator/docs/local-loopback.zh-CN.md)。真实部署验证应覆盖 sink 注册、命令匹配、RTP 播放、状态 envelope 和取消抑制。

播放 adapter 必须显式实现 `finish_stream` 与 `wait_stream_drained`：前者结束输入并启动正常排空，后者在样本队列排空、设备回调停止且流关闭后返回。`close_stream` 用于取消；正常完成不得以取消代替。


## 输出租约的播放生命周期

`PlaybackLifecycle` 持有当前与最近播放命令、最低代次、RTP 队列、jitter 驱动、排空任务和播放通知；`ReceiveRuntime` 只持有连接、注册及重连，并将已解析控制事件和 UDP 包交给它。每次连接建立一个实例，退出时回收所有任务。

正常连接结束保留有界 UDP 尾帧等待和设备排空；明确取消立即作废租约并回收排空任务。`media.stream.end` 必须匹配命令、代次及 SSRC，重复 end 不重复排空。物理排空完成或超时后再次核验租约身份，旧任务不能清除或关闭新播放。

每个入队 RTP 包绑定接收时的租约身份；替换、取消和已应用的 flush 清除旧包。新租约的 ready/queued 发送完成后才发送 playing；通知发送等待者被取消不会使独立通知写入任务崩溃。flush 重放只重发回执，不重复作废新租约。

生命周期测试通过真实输入 interface 配合可控设备排空信号，覆盖迟到完成、迟到超时、重复与错误 end、flush 重放、旧包失效、发送端验证及正常关闭的 UDP 尾帧；不依赖真人语音或真实音频设备。
