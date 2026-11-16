"""Check that ``docs/openapi.json`` is the document the app generates now, or rewrite it.

    uv run python scripts/check_openapi.py            # exit 1 when the committed copy is stale
    uv run python scripts/check_openapi.py --write    # regenerate it

The document is generated from the Flask URL map, the policy table and the overlay
(``app/api/openapi/``). The optional product areas (CRM, Compliant) add routes only when their
blueprint is mounted, so this must run where they are: ``ENVIRONMENT=test`` in CI, ``local`` on a
developer's machine. Like the Feature Index route check, it only reads the URL map; it serves nothing.
"""

import argparse
import difflib
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _generate() -> str:
    # This process only inspects routes; it does not serve requests or use OAuth.
    os.environ.setdefault("FLASK_SECRET_KEY", secrets.token_urlsafe(48))
    os.environ.setdefault("GOOGLE_CLIENT_ID", "route-check.apps.googleusercontent.com")
    os.environ.setdefault("GOOGLE_CLIENT_SECRET", "route-check-only-secret")

    from app.api.app_factory import create_app
    from app.api.openapi import build_document, canonical_json

    app = create_app()
    mounted = app.extensions.get("product_availability", {})
    missing = sorted(name for name in ("crm", "compliant") if not mounted.get(name))
    if missing:
        raise SystemExit(
            f"Product areas not mounted: {', '.join(missing)}. The document must describe every route, "
            "so run with the environment that mounts them (ENVIRONMENT=test, or local)."
        )
    return canonical_json(build_document(app))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--write", action="store_true", help="rewrite docs/openapi.json instead of checking it")
    args = parser.parse_args()

    from app.api.openapi import COMMITTED_PATH

    generated = _generate()
    if args.write:
        COMMITTED_PATH.write_text(generated, encoding="utf-8")
        print(f"Wrote {COMMITTED_PATH.relative_to(ROOT)} ({generated.count(chr(10))} lines).")
        return 0
    committed = COMMITTED_PATH.read_text(encoding="utf-8") if COMMITTED_PATH.exists() else ""
    if committed == generated:
        print(f"{COMMITTED_PATH.relative_to(ROOT)} is current.")
        return 0
    diff = difflib.unified_diff(
        committed.splitlines(), generated.splitlines(), "docs/openapi.json (committed)", "generated", lineterm="", n=1
    )
    for index, line in enumerate(diff):
        if index >= 60:
            print("... (diff truncated)", file=sys.stderr)
            break
        print(line, file=sys.stderr)
    print(
        "\ndocs/openapi.json is stale. Run `uv run python scripts/check_openapi.py --write` and commit it.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
