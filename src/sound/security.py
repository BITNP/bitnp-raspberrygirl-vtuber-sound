from typing import TypedDict

from sound.config import ServiceConfig


class AuthHeader(TypedDict, total=False):
    authorization: str


def trusted_lan_auth_header(config: ServiceConfig) -> AuthHeader:
    if config.trusted_lan_token is None:
        return {}
    return {"authorization": f"Bearer {config.trusted_lan_token}"}


def trusted_lan_token_is_valid(config: ServiceConfig, header: str) -> bool:
    if config.trusted_lan_token is None:
        return True
    return header == f"Bearer {config.trusted_lan_token}"
