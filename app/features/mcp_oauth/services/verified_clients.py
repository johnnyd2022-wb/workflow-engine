"""The OAuth clients Biz-E has verified (design review S3).

This list in code is the source of truth. ``oauth_clients.verified`` only caches what it says, and is
brought back in line every time a client is registered, resolved or used (``sync``), so removing an
entry here ends that client's verified status on its next request.

A client matches an entry by **where its codes go**, never by its name: every redirect URI it
registered (or its metadata document lists) must be one of the entry's exact, vendor-controlled
``https`` URIs. A code sent there reaches only the vendor, so an impostor that copies them gains
nothing. When an entry lists metadata document URLs, a metadata-URL client must also be one of
them. Loopback redirect URIs are never listed: any local process can listen on a port and claim
to be the client (MCP authorization spec, "localhost redirect URI risks").

Every identifier is cited from the vendor's own current documentation. Before adding one, cite it
the same way; a client that cannot be cited stays unverified (the org can still allow it).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.features.mcp_oauth.models.oauth_client import REGISTRATION_DCR, REGISTRATION_METADATA_URL


@dataclass(frozen=True)
class VerifiedClient:
    name: str
    redirect_uris: frozenset[str]
    metadata_urls: frozenset[str] = frozenset()
    source: str = ""


VERIFIED_CLIENTS: tuple[VerifiedClient, ...] = (
    # claude.ai on the web, Claude Desktop, mobile and Cowork share one fixed callback.
    # Claude Code uses a loopback redirect on an ephemeral port, so it is not listed.
    VerifiedClient(
        name="Claude",
        redirect_uris=frozenset({"https://claude.ai/api/mcp/auth_callback"}),
        source="https://claude.com/docs/connectors/building/authentication#callback-urls",
    ),
    # ChatGPT's stable redirect and metadata document, used with authorization servers that return
    # ``iss`` on the redirect (RFC 9207), which this one does. The callback-ID-specific variants
    # (``/connector/oauth/{callback_id}``) differ per connector and are not listed.
    VerifiedClient(
        name="ChatGPT",
        redirect_uris=frozenset({"https://chatgpt.com/connector_platform_oauth_redirect"}),
        metadata_urls=frozenset({"https://chatgpt.com/oauth/client.json"}),
        source="https://developers.openai.com/apps-sdk/build/auth",
    ),
)


def match(client_id: str, registration: str, redirect_uris) -> VerifiedClient | None:
    """The entry this client is, or ``None``. Pure: no database, no network."""
    if registration not in (REGISTRATION_DCR, REGISTRATION_METADATA_URL):
        return None
    uris = set(redirect_uris or ())
    if not uris:
        return None
    for entry in VERIFIED_CLIENTS:
        if not uris <= entry.redirect_uris:
            continue
        if registration == REGISTRATION_METADATA_URL and entry.metadata_urls and client_id not in entry.metadata_urls:
            continue
        return entry
    return None


def sync(row) -> bool:
    """Set ``row.verified`` (and, when verified, ``row.client_name``) from the list.

    Returns True when the row changed, so the caller knows to commit. A first-party row is left as
    it is. A client-supplied name is shown as-is only while the client is unverified.
    """
    if row.registration not in (REGISTRATION_DCR, REGISTRATION_METADATA_URL):
        return False
    entry = match(row.client_id, row.registration, row.redirect_uris)
    verified = entry is not None
    changed = bool(row.verified) != verified
    row.verified = verified
    if entry is not None and row.client_name != entry.name:
        row.client_name = entry.name
        changed = True
    return changed
