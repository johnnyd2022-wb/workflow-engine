"""Token and authorization-code primitives: generation, hashing, PKCE.

Codes and tokens are 32 random bytes, base64url, behind a prefix that makes a leaked one
recognisable (``bza_`` access, ``bzr_`` refresh, ``bzc_`` code). Only the SHA-256 hex digest is
ever stored, and the raw value is never logged (structlog redaction also covers the pattern).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from datetime import timedelta

ACCESS_PREFIX = "bza_"
REFRESH_PREFIX = "bzr_"
CODE_PREFIX = "bzc_"

ACCESS_TTL = timedelta(seconds=3600)
REFRESH_TTL = timedelta(days=30)
CODE_TTL = timedelta(seconds=60)
# How long after a refresh token is rotated out it may be presented once more without ending the
# grant (a client retrying after a lost response). Measured from the rotation, never extended.
REFRESH_REUSE_GRACE = timedelta(seconds=30)

# 32 random bytes as unpadded base64url is 43 characters.
_TOKEN_BODY = r"[A-Za-z0-9_-]{43}"
_TOKEN_RE = {
    ACCESS_PREFIX: re.compile(rf"{re.escape(ACCESS_PREFIX)}{_TOKEN_BODY}"),
    REFRESH_PREFIX: re.compile(rf"{re.escape(REFRESH_PREFIX)}{_TOKEN_BODY}"),
    CODE_PREFIX: re.compile(rf"{re.escape(CODE_PREFIX)}{_TOKEN_BODY}"),
}

# RFC 7636: a verifier is 43-128 characters of the unreserved set; an S256 challenge is the
# unpadded base64url of a SHA-256 digest, so always 43 characters.
_VERIFIER_RE = re.compile(r"[A-Za-z0-9\-._~]{43,128}")
_CHALLENGE_RE = re.compile(r"[A-Za-z0-9_-]{43}")


def new_token(prefix: str) -> str:
    return prefix + secrets.token_urlsafe(32)


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def looks_like(prefix: str, raw: str) -> bool:
    """True when ``raw`` has the exact shape of one of our values of this kind."""
    return isinstance(raw, str) and _TOKEN_RE[prefix].fullmatch(raw) is not None


def is_valid_challenge(value: str) -> bool:
    return isinstance(value, str) and _CHALLENGE_RE.fullmatch(value) is not None


def pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def verifier_matches(verifier: str, challenge: str) -> bool:
    """Constant-time S256 check of a presented ``code_verifier`` against the stored challenge."""
    if not isinstance(verifier, str) or _VERIFIER_RE.fullmatch(verifier) is None:
        return False
    return hmac.compare_digest(pkce_s256(verifier), challenge)
