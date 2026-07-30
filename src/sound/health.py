"""模块契约说明.

职责: 提供 sound.health
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

import json
from dataclasses import dataclass
from typing import Literal

from sound import __version__
from sound.config import SERVICE_NAME, OrchestratorWsUrl, ServiceConfig, load_config


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """类契约说明.

    职责: 保存 HealthStatus
    不可变数据结构,用类型标注表达字段契约。
    契约: 字段: service、service_version、stat
    us、orchestrator_ws_url。 方法: to_json。
    """

    service: str

    service_version: str

    status: Literal["ready"]

    orchestrator_ws_url: OrchestratorWsUrl

    def to_json(self) -> str:
        """函数契约说明.

        功能: 将输入转换为目标表示。
        参数: self 表示当前实例。
        契约: 同步调用。 返回 `str`。
        """

        payload: dict[str, str] = {
            "service": self.service,
            "service_version": self.service_version,
            "status": self.status,
            "orchestrator_ws_url": self.orchestrator_ws_url,
        }

        return json.dumps(payload, sort_keys=True)


def health_status(config: ServiceConfig) -> HealthStatus:
    """函数契约说明.

    功能: 执行 health_status 的同步逻辑,并协调
    HealthStatus。
    参数: config: ServiceConfig。 必填。
    契约: 同步调用。 返回 `HealthStatus`。
    """

    return HealthStatus(
        service=SERVICE_NAME,
        service_version=__version__,
        status="ready",
        orchestrator_ws_url=config.orchestrator_ws_url,
    )


def main() -> int:
    """函数契约说明.

    功能: 执行命令行或服务入口流程并返回进程级结果。
    参数: 无显式业务参数。
    契约: 同步调用。 返回 `int`。
    """

    print(health_status(load_config()).to_json())

    return 0
