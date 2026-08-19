# OBSERVABILITY: shell

date: 2026-08-15
invoked_as: chain stage, instrument mode
scope: `app/core/security/permissions.py` (`requires_auth`, app-wide), `app/api/app_factory.py`
(`serve_ui_shared`, AC7), `app/app.py` (AC11 `/initialize`), `app/core/backend/backend.py`
(AC5/AC6 static-asset routes), `app/api/middleware/session_security.py` (AC12
session-expiry render path)

## What was instrumented

### 1. `requires_auth` — missing `access_denied` log (the assigned gap)

`app/core/security/permissions.py`'s `requires_auth` decorator aborted with a bare 401 on
missing auth with no log line, while the sibling `requires_role` decorator in the same file
logged a structured `access_denied` warning before its 403. `requires_auth` gates every
`@requires_auth` route app-wide, including AC1/AC2/AC4's shell chrome routes and the
just-fixed AC11 `/initialize` route (this review's own security fix, F2, now depends on this
being observable — without it, repeated unauthenticated probes against `/initialize` left no
audit trail).

Added the equivalent warning before the `abort(401, ...)`:

```python
logger.warning(
    "access_denied",
    reason="unauthenticated",
    path=request.path,
    method=request.method,
)
```

No `user_id`/`org_id` — there is no authenticated user at this point, matching the task's
explicit instruction not to fabricate identity fields that don't exist yet.

### 2. Double-log check against the global `@app.errorhandler(401)`

Read `app/api/app_factory.py:300-314`. The global 401 handler only decides response shape
(redirect for HTML page-shaped GETs vs JSON for API/`/auth/`/static requests) — it contains
no `logger.*` call of its own. So there is no double-log risk: `requires_auth`'s new warning
is the only log line for this event, regardless of which branch of the global handler
formats the response afterward. Confirmed empirically too (see test below): the same request
that gets 302'd by the global handler still produces exactly one `access_denied` warning.

### 3. Found gap: `serve_ui_shared` (`/ui/shared/<filename>`, AC7) had the identical hole

`app/api/app_factory.py`'s `serve_ui_shared` enforces auth inline (`abort(401, ...)` on
`not g.current_user`) rather than via `@requires_auth`, specifically so the
`PUBLIC_UI_SHARED_FILES` allowlist can be honoured (see the view's own docstring). Because
it bypasses the decorator, it also bypassed the decorator's logging — same class of gap
(unauthenticated request to a protected shell route, zero audit trail), same file family
this task named ("static-asset serving"), so it's fixed here rather than left as a
follow-up:

```python
if filename not in PUBLIC_UI_SHARED_FILES and (not hasattr(g, "current_user") or not g.current_user):
    logger.warning(
        "access_denied",
        reason="unauthenticated",
        path=request.path,
        method=request.method,
    )
    abort(401, description="Authentication required")
```

Confirmed this route's `abort(401)` also flows through the same global errorhandler with no
logging of its own, so the same double-log analysis applies — one log point, not two.

## Scanned, no gap found

- **AC5/AC6 static-asset routes** (`backend.py`'s `serve_core_js/css/inventory_static/img`):
  the "file not found" 404 branch is already logged at INFO with an explicit in-code
  rationale (Werkzeug-version comment on why both `FileNotFoundError` and `NotFound` are
  caught) — correctly left alone per the task's own instruction not to relitigate deliberate
  info-level logging.
- **AC5/AC6 path-traversal 400s** (`..`/`/`/`\` in filename, bad extension, non-allowlisted
  filename): considered and *not* instrumented. These four routes are intentionally
  unauthenticated, public, high-traffic asset endpoints (spec: "no auth so they load
  reliably"). `../` traversal payloads against public static-file-shaped URLs are routine
  internet background noise (mass vulnerability scanners probe every asset-looking endpoint
  for this) — logging every rejection at WARNING here would be exactly the noise-over-signal
  failure mode the observability skill warns against ("a level someone would actually alert
  on"), not a genuine gap. This is a different situation from `app/core/backend/process_docs/
  process_docs_storage.py:100` and `app/core/backend/evidence/evidence_storage.py:137`, which
  *do* log `"...rejected unsafe filename"` at WARNING for their own traversal checks — but
  those guard authenticated, org-scoped object storage, where a traversal attempt is a rare,
  high-signal event (an authenticated session doing something malicious), not a routine
  unauthenticated crawl. Recommend leaving this as-is; flagging the reasoning explicitly per
  the skill's "gaps stated honestly" instruction rather than silently skipping it.
- **AC7 traversal/extension 400s** (`serve_ui_shared`, post-auth): same reasoning as above,
  and lower volume again since these checks only run for the already-authenticated caller
  (or the single hardcoded-safe allowlisted filename) — not instrumented, not flagged as a
  gap.
- **AC12 session-expiry render path** (`app/api/middleware/session_security.py`): already
  well-instrumented — `session_expired_due_to_inactivity` at INFO (expected, user-triggered
  event, not a denial) with `user_id`, `user_session_timeout_load_failed` and
  `invalid_last_activity_at_format` at WARNING for actual failures. No change needed.

## Tests added (logging is code — asserted per the skill's rule)

- `tests/test_org_routes.py::test_unauthenticated_request_logs_access_denied` — mirrors the
  existing `test_forbidden_role_check_logs_access_denied` pattern for `requires_role`.
  Monkeypatches `permissions.logger.warning`, hits `/org` with the `org_world` fixture's
  `anon_client`, asserts exactly one `access_denied` warning with
  `reason="unauthenticated"`, `path="/org"`, `method="GET"`, and no `user_id` key.
- `tests/test_ui_shared_access_denied.py` (new file) — two tests for `serve_ui_shared`:
  unauthenticated request to a non-allowlisted file logs `access_denied` once (and confirms
  the response is the global handler's 302, not a bare 401 — the log is what makes that
  redirect auditable); a request for the publicly-allowlisted `password-policy.js` logs
  nothing. Uses a spy `get_logger` patch rather than a module-attribute patch, because
  `app_factory.create_app()` binds `logger` as a local variable (the only module in this repo
  that does; every other module assigns `logger = get_logger(__name__)` at module scope) —
  documented inline in the test file so a future reader doesn't wonder why this one test
  can't use the simpler `monkeypatch.setattr(module.logger, ...)` pattern used elsewhere.

## Verification

`unset ENVIRONMENT; uv run pytest tests/ -q --ignore=tests/e2e` → **1234 passed, 1 skipped**,
no failures, no regressions. `ruff check` / `ruff format --check` clean on all four changed
files.

## Gaps (honest, not fixed here)

- No Sentry (per this skill's own instructions, not proposed — OTel/Grafana LGTM is the
  equivalent stack and is already wired).
- The two path-traversal-400 classes noted above are a judgment call, not a hard gap; if
  production experience later shows attacker traffic against `/ui/shared/*` specifically
  (post-auth, so genuinely suspicious there), that's the one worth revisiting first.

VERDICT: patched
