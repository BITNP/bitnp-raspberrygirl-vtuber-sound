# 测试

运行 `uv sync --locked`，再运行 `uv run pytest`。测试覆盖 RTP 和流状态行为，不需要音频设备。运行 `ORCHESTRATOR_WS_URL=ws://orchestrator.local/ws uv run sound-health` 可检查健康命令。
