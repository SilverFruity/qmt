"""Connection settings for the QMT client."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18080
DEFAULT_TIMEOUT = 10.0
DEFAULT_ENV_PREFIX = "QMT_"


@dataclass
class QMTConfig:
    """Immutable-ish connection settings.

    The server binds 127.0.0.1:18080 by default. For a LAN deployment point
    host at the server LAN address (or set QMT_HOST); the server must list that
    address in allowed_hosts and the transport is plaintext HTTP.
    """

    token: str
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    timeout: float = DEFAULT_TIMEOUT

    @property
    def base_url(self):
        return "http://%s:%d" % (self.host, self.port)

    @property
    def ws_url(self):
        return "ws://%s:%d/ws" % (self.host, self.port)

    @classmethod
    def from_env(cls, prefix=DEFAULT_ENV_PREFIX, **overrides):
        """Build a config from environment variables.

        Variables: <prefix>AUTH_TOKEN, <prefix>HOST, <prefix>PORT and
        <prefix>TIMEOUT. Explicit keyword overrides win over the environment.
        """
        values = {
            "token": overrides.pop("token", None) or os.environ.get(prefix + "AUTH_TOKEN") or "",
            "host": overrides.pop("host", None) or os.environ.get(prefix + "HOST") or DEFAULT_HOST,
            "port": overrides.pop("port", None) or os.environ.get(prefix + "PORT") or DEFAULT_PORT,
            "timeout": overrides.pop("timeout", None) or os.environ.get(prefix + "TIMEOUT") or DEFAULT_TIMEOUT,
        }
        values.update(overrides)
        return cls(
            token=str(values["token"]).strip(),
            host=str(values["host"]),
            port=int(values["port"]),
            timeout=float(values["timeout"]),
        )
