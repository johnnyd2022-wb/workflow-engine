# security-audit — compliant_tools

## Scanner pass (Sonnet, orchestrator-run)

- **semgrep** (`.semgrep/` + `p/flask` + `p/owasp-top-ten`) on the new feature files:
  1 finding — `raw-fetch-post` on `tools-page.js` (a POST `fetch` that *did* carry the
  `X-CSRFToken` header, so the rule's intent was met but its structural pattern fired).
  Fixed: extracted a `postJson()` helper matching `compliant.js`'s idiom → 0 findings.
  (Pre-existing `csv-writer-injection` in `compliant/routes/api_routes.py:349` is
  untouched and already mitigated by `_csv_safe()` — not this change.)
- **gitleaks** `main..HEAD`: no leaks.
- **uv audit**: no known vulnerabilities; no dependency changes in this branch.
- **semgrep performance rules** (N+1) on the gate + routes + context processor + repo:
  none. The gate adds exactly one indexed `feature_subscriptions` lookup per compliant
  request; no loop queries.

## security-tenant-audit (Codex gpt-5.6-sol, high effort)

**No critical / high / medium.** Isolation model judged sound: every repo read/write
filters the exact `org_id`; `grant`/`revoke` cannot select another org's row; the
`(org_id, feature_key)` unique constraint preserves separation; `org_has_feature` fails
closed without a valid org; calculator dispatch is a fixed dict lookup (no traversal /
dynamic import / attribute lookup); solvers touch no tenant table; CLI args are
UUID-parsed + bound parameters; the migration's raw SQL is a literal.

Two **low** findings:

1. `app_factory.py` context processor trusted `g.compliant_subscribed` without binding it
   to `g.current_org_id` → under Flask app-context reuse, a subscribed org's cached
   `True` could render the Compliance **nav item** (not data) for a later unsubscribed
   org in the same context. **Fixed**: `before_request` now also sets
   `g.compliant_subscribed_org`; the context processor reuses the cache only when it
   equals the current org, else recomputes. Regression test:
   `test_ac7_nav_state_does_not_leak_across_orgs_in_a_reused_context`.
2. Unauthenticated `OPTIONS`/`405` on a known compliant path returns `200`/`405` + an
   `Allow` header, vs `404` for an unknown path — so an unauthenticated caller can
   confirm the Compliant blueprint is mounted (route/method shape only; no tenant data,
   no per-org subscription state). **Accepted, not fixed**: this is Flask's
   automatic-OPTIONS / 405 behaviour shared by every blueprint in the app (crm,
   workflow_engine, core), the info revealed (blueprint mounted) is already public via
   `prod.ini`'s `compliant_enabled = true`, and AC3's cross-tenant 404 concealment for
   *authenticated* unsubscribed orgs is intact and verified. A one-off fix for only
   `compliant` would be inconsistent; a repo-wide fix is out of this feature's scope.
