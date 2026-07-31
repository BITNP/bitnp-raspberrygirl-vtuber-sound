import ssl
from pathlib import Path

from sound.config import TLS_CA_PATH_KEY, ConfigError


def build_tls_context(ca_path: Path | None) -> ssl.SSLContext | None:
    if ca_path is None:
        return None

    context = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)

    try:
        context.load_verify_locations(cafile=str(ca_path))
    except (OSError, ssl.SSLError) as error:
        raise ConfigError(
            key=TLS_CA_PATH_KEY, reason="must be a readable PEM CA bundle"
        ) from error

    return context
