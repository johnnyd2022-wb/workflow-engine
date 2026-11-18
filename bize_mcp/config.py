"""Configuration, from the environment only. No database credentials, no app secrets.

``BIZE_API_BASE_URL``  where the app is, from this container (an internal address in production)
``MCP_PUBLIC_URL``     the address assistants use for this server, e.g. ``https://mcp.biz-e.app/mcp``
``BIZE_ISSUER_URL``    the app's public address; it is the OAuth authorization server
``BIZE_KNOWLEDGE_DIR`` optional: the business-knowledge Markdown directory (default ``docs/knowledge``)
``BIZE_API_VERIFY_TLS`` optional: ``false`` skips certificate verification on the call to the app. Only for
                       the private Docker network scripts/run_mcp.sh deploys onto, where the app serves a
                       self-signed certificate under a name it does not cover. Verified by default.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

METADATA_PATH = "/.well-known/oauth-protected-resource"
ENV_VARS = ("BIZE_API_BASE_URL", "MCP_PUBLIC_URL", "BIZE_ISSUER_URL")


class ConfigError(ValueError):
    """The server cannot start: a setting is missing or is not an http(s) URL."""


def _check_url(name: str, value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        raise ConfigError(f"{name} must be an http(s) URL")
    return value


def _verify_tls(raw: str | None) -> bool:
    """Verification stays on unless the value plainly says off; a typo is an error, never a silent opt-out."""
    value = (raw or "").strip().lower()
    if value in {"", "true", "1", "yes", "on"}:
        return True
    if value in {"false", "0", "no", "off"}:
        return False
    raise ConfigError("BIZE_API_VERIFY_TLS must be true or false")


@dataclass(frozen=True)
class Config:
    api_base_url: str
    public_url: str
    issuer_url: str
    request_timeout: float = 15.0
    knowledge_dir: str = "docs/knowledge"
    verify_tls: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "api_base_url", _check_url("api_base_url", self.api_base_url).rstrip("/"))
        object.__setattr__(self, "public_url", _check_url("public_url", self.public_url))
        object.__setattr__(self, "issuer_url", _check_url("issuer_url", self.issuer_url).rstrip("/"))

    @property
    def origin(self) -> str:
        parts = urlsplit(self.public_url)
        return f"{parts.scheme}://{parts.netloc}"

    @property
    def metadata_url(self) -> str:
        """Where an assistant finds the protected-resource metadata (RFC 9728)."""
        return f"{self.origin}{METADATA_PATH}"

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> Config:
        env = os.environ if environ is None else environ
        missing = [name for name in ENV_VARS if not (env.get(name) or "").strip()]
        if missing:
            raise ConfigError("Missing environment variables: " + ", ".join(missing))
        return cls(
            api_base_url=env["BIZE_API_BASE_URL"].strip(),
            public_url=env["MCP_PUBLIC_URL"].strip(),
            issuer_url=env["BIZE_ISSUER_URL"].strip(),
            knowledge_dir=(env.get("BIZE_KNOWLEDGE_DIR") or "docs/knowledge").strip(),
            verify_tls=_verify_tls(env.get("BIZE_API_VERIFY_TLS")),
        )
