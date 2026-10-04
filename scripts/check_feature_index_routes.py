"""Check every Feature Index route claim against the composed Flask URL map."""

import fnmatch
import os
import secrets
import sys
from pathlib import Path

INDEX = Path(__file__).resolve().parent.parent / ".agents" / "feature-index.md"


def route_claims(text: str) -> list[tuple[str, str]]:
    claims = []
    section = None
    in_routes = False
    block_count = 0
    for line in text.splitlines():
        if line.startswith("## "):
            if in_routes and not block_count:
                raise ValueError(f"empty routes block in {section}")
            section = line[3:]
            in_routes = False
        elif line == "    routes:":
            if section is None:
                raise ValueError("routes block appears before a slice heading")
            in_routes = True
            block_count = 0
        elif in_routes and line.startswith("      - "):
            pattern = line[8:].strip()
            if not pattern.startswith("/") or any(char.isspace() for char in pattern):
                raise ValueError(f"invalid route pattern in {section}: {pattern!r}")
            claims.append((section, pattern))
            block_count += 1
        elif in_routes:
            if not block_count:
                raise ValueError(f"empty routes block in {section}")
            in_routes = False
    if in_routes and not block_count:
        raise ValueError(f"empty routes block in {section}")
    return claims


def main() -> int:
    if os.environ.get("ENVIRONMENT") != "test":
        print("Run with ENVIRONMENT=test so all optional product routes are mounted.", file=sys.stderr)
        return 2

    try:
        claims = route_claims(INDEX.read_text(encoding="utf-8"))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not claims:
        print("Feature Index has no route claims.", file=sys.stderr)
        return 2

    # This process only inspects routes; it does not serve requests or use OAuth.
    os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_urlsafe(48))
    os.environ.setdefault("GOOGLE_CLIENT_ID", "route-check.apps.googleusercontent.com")
    os.environ.setdefault("GOOGLE_CLIENT_SECRET", "route-check-only-secret")

    from app.app import app

    live_routes = {rule.rule for rule in app.url_map.iter_rules()}
    missing = [
        f"{slice_name}: {pattern}"
        for slice_name, pattern in claims
        if not any(fnmatch.fnmatchcase(route, pattern) for route in live_routes)
    ]
    if missing:
        print("Feature Index route claims missing from Flask URL map:", file=sys.stderr)
        for claim in missing:
            print(f"  {claim}", file=sys.stderr)
        return 1

    print(f"Feature Index: {len(claims)} route claims resolve against {len(live_routes)} live paths.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
