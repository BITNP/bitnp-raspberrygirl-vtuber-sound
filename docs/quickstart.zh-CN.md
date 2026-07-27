# 快速开始

使用 Python 3.12 或更高版本。在本仓库中运行：

```bash
uv sync --locked
uv run pytest
ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run sound-health
```

默认路径在本地回放 RTP L16 音频和流状态。测试不需要扬声器设备、GPU 或凭据。
