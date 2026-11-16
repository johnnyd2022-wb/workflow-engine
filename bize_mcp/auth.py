"""Who is calling, and what may they read: ``GET /api/core/mcp/me``, cached for a minute.

``tools/list`` is filtered per caller from the permissions the app reports (the person's own
permissions intersected with the read-only set). The answer is cached for 60 seconds per token,
keyed on a hash of the token so the raw value never sits in a dictionary, and a failed lookup is
never cached. The cache only decides which tools are *listed*: every tool call still goes to the app,
which checks the token, the organisation's switch and the person's role again.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from bize_mcp.client import AppClient

IDENTITY_TTL = 60.0
MAX_CACHED = 2048
ME_PATH = "/api/core/mcp/me"


def _now() -> float:
    return time.monotonic()


@dataclass(frozen=True)
class Identity:
    permissions: frozenset[str]
    user_name: str | None = None
    org_name: str | None = None
    role_label: str | None = None
    user_id: str | None = None
    org_id: str | None = None
    client_id: str | None = None
    grant_id: str | None = None
    features: frozenset[str] | None = None  # None: the app did not say, so nothing is hidden by feature

    def has_feature(self, feature: str | None) -> bool:
        return not feature or self.features is None or feature in self.features


def token_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _parse(body: object) -> Identity:
    data = body if isinstance(body, dict) else {}
    permissions = data.get("permissions")
    user = data.get("user") if isinstance(data.get("user"), dict) else {}
    org = data.get("org") if isinstance(data.get("org"), dict) else {}
    return Identity(
        permissions=frozenset(p for p in permissions if isinstance(p, str)) if isinstance(permissions, list) else frozenset(),
        user_name=user.get("name"),
        org_name=org.get("name"),
        role_label=data.get("role_label"),
        user_id=user.get("id"),
        org_id=org.get("id"),
        client_id=data.get("client_id"),
        grant_id=data.get("grant_id"),
        features=frozenset(f for f in data["features"] if isinstance(f, str))
        if isinstance(data.get("features"), list)
        else None,
    )


class IdentityCache:
    def __init__(self, client: AppClient):
        self._client = client
        self._entries: dict[str, tuple[float, Identity]] = {}

    async def identity_for(self, token: str) -> Identity:
        key = token_key(token)
        now = _now()
        hit = self._entries.get(key)
        if hit is not None and hit[0] > now:
            return hit[1]
        identity = _parse(await self._client.get(ME_PATH, token))  # 401 and 403 propagate; nothing is cached
        self._remember(key, identity, now)
        return identity

    def _remember(self, key: str, identity: Identity, now: float) -> None:
        if len(self._entries) >= MAX_CACHED:
            self._entries = {k: v for k, v in self._entries.items() if v[0] > now}
            while len(self._entries) >= MAX_CACHED:
                self._entries.pop(next(iter(self._entries)))
        self._entries[key] = (now + IDENTITY_TTL, identity)
