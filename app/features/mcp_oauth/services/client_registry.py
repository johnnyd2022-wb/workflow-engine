"""OAuth clients: dynamic registration (RFC 7591) and client ID metadata documents.

Two ways a client exists, both open (founder decision Q3) and both labelled "Unverified app" until
Biz-E staff mark them verified:

* **Dynamic registration**: ``POST /oauth/register`` with a name and 1-5 redirect URIs.
* **Client ID metadata document**: the ``client_id`` is an ``https://`` URL; the app fetches that
  document once and caches it for 24 hours.

The second one makes the server fetch a URL a stranger chose, so the fetch is the dangerous part
and is held to hard limits: https on port 443 only, no credentials in the URL, every address the
name resolves to must be a public one (loopback, private, link-local, shared, multicast and
reserved ranges are refused, including IPv4 hidden in IPv4-mapped, 6to4, Teredo and NAT64
addresses), the connection is pinned to the address that was checked (so a second DNS answer
cannot swap in a private one), no redirects, 5 seconds, 64 KB.
"""

from __future__ import annotations

import ipaddress
import json
import secrets
import socket
import time
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

from sqlalchemy.exc import IntegrityError

from app.features.mcp_oauth.models import OAuthClient
from app.features.mcp_oauth.models.oauth_client import REGISTRATION_DCR, REGISTRATION_METADATA_URL
from app.observability import get_logger

logger = get_logger(__name__)

MAX_REDIRECT_URIS = 5
MAX_URI_LENGTH = 2000
MAX_NAME_LENGTH = 100
METADATA_TIMEOUT_SECONDS = 5
METADATA_MAX_BYTES = 64 * 1024
METADATA_CACHE_SECONDS = 24 * 3600
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1"})
SUPPORTED_GRANT_TYPES = ("authorization_code", "refresh_token")
SUPPORTED_RESPONSE_TYPES = ("code",)


class ClientError(Exception):
    """A client could not be registered or resolved. ``code`` is the RFC error to answer with."""

    def __init__(self, code: str, description: str = ""):
        super().__init__(f"{code}: {description}" if description else code)
        self.code = code
        self.description = description


@dataclass(frozen=True)
class FetchResult:
    status: int
    headers: dict
    body: bytes


# --- redirect URIs and names --------------------------------------------------------------------


def validate_redirect_uri(uri) -> str:
    """The URI itself when it is a safe redirect target, else ``invalid_redirect_uri``.

    ``https://`` with a host, or ``http://localhost|127.0.0.1:<port>/...`` (a native app listening
    on loopback). No credentials, no fragment, no backslashes or whitespace. Returned unchanged:
    redirect URIs are compared exactly.
    """
    bad = ClientError("invalid_redirect_uri", "Redirect URIs must be https, or http on localhost with a port")
    if not isinstance(uri, str) or not uri or len(uri) > MAX_URI_LENGTH:
        raise bad
    if "\\" in uri or any(ch.isspace() or unicodedata.category(ch).startswith("C") for ch in uri):
        raise bad
    try:
        parts = urlsplit(uri)
        port = parts.port
    except ValueError:
        raise bad from None
    host = (parts.hostname or "").lower()
    if parts.username is not None or parts.password is not None or parts.fragment or not host:
        raise bad
    if parts.scheme == "https":
        return uri
    if parts.scheme == "http" and host in LOOPBACK_HOSTS and port is not None:
        return uri
    raise bad


def validate_redirect_uris(value) -> list[str]:
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_REDIRECT_URIS:
        raise ClientError("invalid_redirect_uri", f"Give between 1 and {MAX_REDIRECT_URIS} redirect URIs")
    uris = [validate_redirect_uri(item) for item in value]
    if len(set(uris)) != len(uris):
        raise ClientError("invalid_redirect_uri", "Redirect URIs must be distinct")
    return uris


def clean_client_name(value) -> str:
    """A display name with no control, format or line-separator characters (no bidi tricks)."""
    if not isinstance(value, str):
        raise ClientError("invalid_client_metadata", "client_name must be text")
    cleaned = "".join(ch for ch in value if not unicodedata.category(ch).startswith("C") and ch not in "  ")
    cleaned = " ".join(cleaned.split())
    if not cleaned or len(cleaned) > MAX_NAME_LENGTH:
        raise ClientError("invalid_client_metadata", f"client_name must be 1-{MAX_NAME_LENGTH} characters")
    return cleaned


# --- dynamic registration -----------------------------------------------------------------------


def _subset(payload: dict, key: str, allowed: tuple[str, ...]) -> list[str]:
    value = payload.get(key)
    if value is None:
        return list(allowed)
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v in allowed for v in value):
        raise ClientError("invalid_client_metadata", f"{key} must be a non-empty subset of {list(allowed)}")
    return list(dict.fromkeys(value))


def register_dcr(db, payload) -> tuple[OAuthClient, dict]:
    """Create an unverified client. Returns the row and the RFC 7591 response body."""
    if not isinstance(payload, dict):
        raise ClientError("invalid_client_metadata", "Send a JSON object")
    name = clean_client_name(payload.get("client_name"))
    uris = validate_redirect_uris(payload.get("redirect_uris"))
    if payload.get("token_endpoint_auth_method", "none") != "none":
        raise ClientError("invalid_client_metadata", "Only public clients (token_endpoint_auth_method none)")
    grant_types = _subset(payload, "grant_types", SUPPORTED_GRANT_TYPES)
    response_types = _subset(payload, "response_types", SUPPORTED_RESPONSE_TYPES)
    row = OAuthClient(
        client_id=secrets.token_urlsafe(24),
        client_name=name,
        redirect_uris=uris,
        registration=REGISTRATION_DCR,
        verified=False,
    )
    db.add(row)
    db.commit()
    return row, {
        "client_id": row.client_id,
        "client_id_issued_at": int(row.created_at.timestamp()),
        "client_name": row.client_name,
        "redirect_uris": list(row.redirect_uris),
        "token_endpoint_auth_method": "none",
        "grant_types": grant_types,
        "response_types": response_types,
        "scope": "bize.read",
    }


# --- the address check --------------------------------------------------------------------------


def _embedded_ipv4(ip: ipaddress.IPv6Address) -> list[ipaddress.IPv4Address]:
    found = []
    if ip.ipv4_mapped is not None:
        found.append(ip.ipv4_mapped)
    if ip.sixtofour is not None:
        found.append(ip.sixtofour)
    if ip.teredo is not None:
        found.extend(ip.teredo)
    if ip in ipaddress.ip_network("64:ff9b::/96"):  # NAT64 well-known prefix
        found.append(ipaddress.IPv4Address(int(ip) & 0xFFFFFFFF))
    return found


def is_public_address(address: str) -> bool:
    """True only for an address that is routable on the public internet."""
    try:
        ip = ipaddress.ip_address(str(address).split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and not all(is_public_address(str(v4)) for v4 in _embedded_ipv4(ip)):
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or not ip.is_global
    )


def resolve_public_addresses(hostname: str, port: int = 443) -> list[str]:
    """Every address ``hostname`` resolves to, only if all of them are public."""
    refused = ClientError("invalid_client", "The client metadata URL is not reachable from here")
    try:
        literal = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        literal = None
    if literal is not None:
        if not is_public_address(str(literal)):
            raise refused
        return [str(literal)]
    try:
        infos = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, UnicodeError):
        raise refused from None
    addresses = list(dict.fromkeys(info[4][0] for info in infos))
    if not addresses or not all(is_public_address(a) for a in addresses):
        raise refused
    return addresses


# --- the fetch ----------------------------------------------------------------------------------


def http_get_pinned(url: str, *, ip: str, hostname: str, timeout: float, max_bytes: int) -> FetchResult:
    """GET ``url`` over TLS from the already-checked ``ip``, presenting and verifying ``hostname``.

    No redirects are followed, the whole exchange has to finish within ``timeout`` seconds, and a
    body over ``max_bytes`` is an error. This is the only function in the feature that opens a
    socket to an address a stranger chose.
    """
    import certifi
    import urllib3

    parts = urlsplit(url)
    target = parts.path or "/"
    if parts.query:
        target += "?" + parts.query
    deadline = time.monotonic() + timeout
    pool = urllib3.HTTPSConnectionPool(
        host=ip,
        port=443,
        server_hostname=hostname,
        assert_hostname=hostname,
        cert_reqs="CERT_REQUIRED",
        ca_certs=certifi.where(),
        timeout=urllib3.Timeout(total=timeout),
        retries=False,
    )
    try:
        response = pool.urlopen(
            "GET",
            target,
            headers={"Host": hostname, "Accept": "application/json", "User-Agent": "biz-e-oauth-client-fetch"},
            redirect=False,
            retries=False,
            preload_content=False,
        )
        try:
            body = b""
            while True:
                # read1 returns what has arrived instead of waiting to fill a buffer, so the
                # deadline below is checked after every bit of data, not only after 8 KB.
                chunk = response.read1(8192, decode_content=False)
                if not chunk:
                    break
                body += chunk
                if len(body) > max_bytes:
                    raise ClientError("invalid_client", "The client metadata document is too large")
                if time.monotonic() > deadline:
                    raise ClientError("invalid_client", "The client metadata fetch timed out")
            headers = {k.lower(): v for k, v in response.headers.items()}
            return FetchResult(status=response.status, headers=headers, body=body)
        finally:
            response.release_conn()
    except urllib3.exceptions.HTTPError:
        raise ClientError("invalid_client", "The client metadata document could not be fetched") from None
    finally:
        pool.close()


def fetch_client_metadata(url: str) -> dict:
    """Fetch and validate a client ID metadata document. Raises ``ClientError`` on anything wrong."""
    refused = ClientError("invalid_client", "The client metadata document was refused")
    if len(url) > MAX_URI_LENGTH or any(ch.isspace() or unicodedata.category(ch).startswith("C") for ch in url):
        raise refused
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise refused from None
    hostname = (parts.hostname or "").lower()
    if (
        parts.scheme != "https"
        or not hostname
        or parts.username is not None
        or parts.password is not None
        or parts.fragment
        or port not in (None, 443)
        or parts.path in ("", "/")
        or "\\" in url
    ):
        raise refused
    addresses = resolve_public_addresses(hostname)
    result = http_get_pinned(
        url, ip=addresses[0], hostname=hostname, timeout=METADATA_TIMEOUT_SECONDS, max_bytes=METADATA_MAX_BYTES
    )
    if result.status != 200 or "json" not in str(result.headers.get("content-type", "")).lower():
        raise refused
    try:
        doc = json.loads(result.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise refused from None
    if not isinstance(doc, dict) or doc.get("client_id") != url:
        raise refused
    if doc.get("token_endpoint_auth_method", "none") != "none":
        raise refused
    try:
        name = clean_client_name(doc.get("client_name") or hostname)
        uris = validate_redirect_uris(doc.get("redirect_uris"))
    except ClientError:
        raise refused from None
    return {"client_name": name, "redirect_uris": uris}


# --- resolving a client_id ----------------------------------------------------------------------


def _fresh(row: OAuthClient, now: datetime) -> bool:
    fetched = row.metadata_fetched_at
    return fetched is not None and (now - fetched).total_seconds() < METADATA_CACHE_SECONDS


def lookup_client(db, client_id, *, now: datetime | None = None) -> OAuthClient:
    """The client for ``client_id``, fetching and caching its metadata document when it is a URL.

    Raises ``ClientError("invalid_client")`` for an unknown or unusable client. Callers decide what
    to do with a disabled client: it is returned so the consent page can say so.
    """
    unknown = ClientError("invalid_client", "Unknown client")
    if not isinstance(client_id, str) or not client_id or len(client_id) > MAX_URI_LENGTH:
        raise unknown
    now = now or datetime.now(UTC)
    # oauth_clients is the one global table: no tenant filter applies, by design.
    row = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).one_or_none()
    if not client_id.startswith("https://"):
        if row is None:
            raise unknown
        return row
    if row is not None and (row.registration != REGISTRATION_METADATA_URL or _fresh(row, now)):
        return row
    db.commit()  # do not hold a transaction (and its pooled connection) open across the network call
    document = fetch_client_metadata(client_id)  # raises when the URL is refused or unreachable
    if row is None:
        row = OAuthClient(
            client_id=client_id,
            client_name=document["client_name"],
            redirect_uris=document["redirect_uris"],
            registration=REGISTRATION_METADATA_URL,
            metadata_url=client_id,
            metadata_fetched_at=now,
            verified=False,
        )
        try:
            with db.begin_nested():
                db.add(row)
        except IntegrityError:  # a concurrent request stored it first
            row = db.query(OAuthClient).filter(OAuthClient.client_id == client_id).one()
    else:
        row.client_name = document["client_name"]
        row.redirect_uris = document["redirect_uris"]
        row.metadata_fetched_at = now
    db.commit()
    logger.info("mcp.client_metadata_fetched", client_id=client_id)
    return row
