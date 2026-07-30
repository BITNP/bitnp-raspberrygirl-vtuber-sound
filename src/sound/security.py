"""模块契约说明.

职责: 提供 sound.security
模块的领域模型、边界函数和运行时协作逻辑。
契约: 模块只提供注释所描述的公开入口,不在文档更新中改变运行时行为。
"""

from typing import TypedDict

from sound.config import ServiceConfig


class AuthHeader(TypedDict, total=False):
    """类契约说明.

    职责: 定义 AuthHeader 的状态、行为和对外协作边界。
    契约: 字段: authorization。
    """

    authorization: str


def trusted_lan_auth_header(config: ServiceConfig) -> AuthHeader:
    """函数契约说明.

    功能: 执行 trusted_lan_auth_header
    的同步逻辑,并维持签名契约。
    参数: config: ServiceConfig。 必填。
    契约: 同步调用。 返回 `AuthHeader`。
    """

    if config.trusted_lan_token is None:
        return {}

    return {"authorization": f"Bearer {config.trusted_lan_token}"}


def trusted_lan_token_is_valid(config: ServiceConfig, header: str) -> bool:
    """函数契约说明.

    功能: 执行 trusted_lan_token_is_valid
    的同步逻辑,并维持签名契约。
    参数: config: ServiceConfig。 必填。
    header: str。 必填。
    契约: 同步调用。 返回 `bool`。
    """

    if config.trusted_lan_token is None:
        return True

    return header == f"Bearer {config.trusted_lan_token}"
