# SECURITY: compliant-nz-alcohol
date: 2026-08-23
verdict: findings-open
invoked_as: chain stage (read-only grader) — report only, no patching. Orchestrator routes remediation.
scanned: semgrep(0 findings), gitleaks(0 findings in scope; 65 pre-existing repo-wide, none touching scoped files), uv-audit(0 vulnerabilities)
manual_checklist: 7/7 completed

## Scope
`app/features/compliant/modules/nz_alcohol/{catalogue,councils,module}.py`, the NZ-alcohol
branches of `app/features/compliant/service.py` (`evaluate()`'s framework filtering,
`framework_for_profile()`, `build_audit_pack()`'s applicability gate), and
`/api/compliant/alcohol-products` (GET/POST) validation. `/api/compliant/profile`,
`/api/compliant/records`, `/api/compliant/reports/*`, `compliant_bp.py`'s static route, and
CSV export are explicitly out of scope — already audited and patched in
`.agents/reports/compliant-platform/review.md` (2026-08-22). `_control_state()`'s generic
record-evaluation logic (measured_value/limit_value comparisons, record CRUD) is platform
territory feeding `/api/compliant/records`, not NZ-alcohol-specific, so it was not re-derived
here per the same boundary.

## 1. Scanner pass
- **semgrep** — `p/python`, `p/flask`, `p/owasp-top-ten`, `.semgrep/` (174 rules incl.
  `python-multitenant.yml` and `learned.yml`) against
  `app/features/compliant/modules/nz_alcohol/` and `app/features/compliant/service.py`:
  **0 findings**. Report: `.agents/reports/compliant-nz-alcohol/semgrep.json`.
- **gitleaks** — `detect` scans full git history (1094 commits) regardless of `--source`
  path; **65 pre-existing leaks** found repo-wide (`generic-api-key` ×47, `gitlab-pat` ×18),
  **none in any file under the audited scope**. These are standing, previously-known repo
  state (see the skill's own worked example, `app/tls/app_cert.key`, an accepted-risk
  finding unrelated to this module) — not attributable to or introduced by this feature.
  Report: `.agents/reports/compliant-nz-alcohol/gitleaks.json`.
- **uv audit** — `--frozen`, 84 packages audited: **0 vulnerabilities, 0 adverse statuses**.
  Report: `.agents/reports/compliant-nz-alcohol/uv-audit.json`.

## 2. Manual checklist (7/7)
1. **Auth on every route** — clean. The only HTTP routes in scope,
   `GET`/`POST /api/compliant/alcohol-products` (`app/features/compliant/routes/api_routes.py:109-165`),
   both carry `@requires_auth`; `POST` additionally carries `@requires_role(UserRole.ADMIN)`.
   `catalogue.py`, `councils.py`, and `module.py` expose no routes — pure functions and an
   internal `CoreChecksRunner` registration, no HTTP surface to check.
2. **Tenant isolation** — clean. `ComplianceService.product_profiles()` and
   `add_product_profile()` (`service.py:220-232`) filter/scope by `org_id` on every query;
   the route resolves `org_id` from `g.org_id` (server-set by tenant middleware), never from
   client input (`api_routes.py:47-48`). `catalogue.py`/`councils.py` are stateless
   in-memory lookups with no tenant dimension — nothing to isolate. `evaluate()`,
   `framework_for_profile()`, and `build_audit_pack()`'s applicability gate
   (`service.py:529-566`, `626-671`) all operate on a `profile` already fetched via
   `get_profile(org_id)`, so no cross-tenant leakage path exists in the NZ-alcohol branches.
3. **Mass assignment** — clean. `add_product_profile(org_id, data)` (`service.py:228-232`)
   receives an explicit allowlisted dict built field-by-field in the route
   (`api_routes.py:150-157`: `inventory_name`, `product_type`, `abv_percent`,
   `customs_product_code`) — never raw `request.json`.
4. **Injection** — clean. No raw SQL, no template `| safe`/`Markup()`, no `subprocess`, no
   file-path handling in the scoped files.
5. **SSRF / uploads** — N/A. No user-supplied URLs or file uploads in scope.
6. **Secrets and config** — clean per gitleaks (see above); no hardcoded secrets in the
   scoped files.
7. **CSRF / CORS** — not re-verified here; `/api/compliant/alcohol-products` is a
   state-changing POST route protected by the same platform-wide CSRF/CORS configuration
   already covered by the compliant-platform review (2026-08-22). Not re-derived per scope
   boundary — see `not_verified` below.

## Findings

- F1 [fix] `app/features/compliant/routes/api_routes.py:144-147` — `abv_percent: "nan"` (or
  `"Infinity"`-adjacent NaN spellings: `"nan"`, `"-nan"`, `"snan"`) crashes
  `POST /api/compliant/alcohol-products` with an unhandled `decimal.InvalidOperation`
  instead of a clean 400.
  repro/evidence: `Decimal(str("nan"))` constructs without raising (NaN is a valid Decimal
  literal), so `_decimal()`'s `except InvalidOperation` guard never fires. The crash happens
  one line later at the *comparison* `Decimal("0") < abv_percent <= Decimal("100")`
  (`api_routes.py:147`), which is outside the `try/except ValueError` block that only wraps
  the construction on line 144. Verified directly:
  `Decimal('0') < Decimal('nan')` raises `decimal.InvalidOperation`, confirmed on this host.
  `sqlalchemy.exc` isn't in play here — this is bare `decimal`, so nothing downstream catches
  it either; Flask's default handler returns a generic 500 (prod has `debug = false`, so no
  stack trace leaks), but the request fails ugly instead of validating cleanly. Requires
  `ADMIN` role to trigger (self-inflicted, no cross-tenant or unauthenticated path) — severity
  is input-validation robustness, not data exposure or auth bypass.
  patch: not applied (read-only chain stage) — orchestrator to route as a scoped fix: catch
  `decimal.InvalidOperation` alongside `ValueError` around the comparison, or reject
  non-finite Decimals (`abv_percent.is_finite()`) before comparing.
  rule_added: none — recommend a `.semgrep/rules/learned.yml` rule for "Decimal comparison
  operator used on a value built from unvalidated user input without an `is_finite()`/
  `InvalidOperation` guard"; not added here per read-only scope (no writes under `.semgrep/`
  in this stage).
  history: recorded `confirmed` in `.agents/history/findings.jsonl` (sig `110e879dd1a0`).
  Already fixed by commit `6cdbea7`: `api_routes.py:144-148` now wraps both the `Decimal()`
  construction and the `is_finite()`/range comparison in one `try/except (ValueError,
  InvalidOperation)` (verified 2026-08-25 by findings-sweep).

- F2 [fix] `app/features/compliant/routes/api_routes.py:156` — `customs_product_code` has no
  server-side length validation before insert; the column is `String(100)`
  (`app/features/compliant/models/alcohol_product_profile.py:24`), so a value over 100 chars
  raises `sqlalchemy.exc.DataError` (Postgres `StringDataRightTruncation`), which is **not**
  a subclass of `IntegrityError` (confirmed via MRO check:
  `DataError → DatabaseError → DBAPIError → StatementError → SQLAlchemyError`) and so falls
  through the `except IntegrityError` block at `api_routes.py:159-163` uncaught — same class
  of unhandled-500 as F1. `inventory_name` (line 141) and `product_type` (line 138) are both
  correctly bounded before insert; `customs_product_code` is the one field the route forgets
  to bound. `ADMIN`-only, self-inflicted, no cross-tenant path.
  patch: not applied (read-only chain stage) — orchestrator to route as a scoped fix: add a
  `len(customs_product_code) > 100` check alongside the existing `inventory_name` length
  check, returning 400.
  rule_added: none — same candidate learned-rule class as F1 (unvalidated field length
  before insert into a bounded `String(N)` column); not added here per read-only scope.
  history: recorded `confirmed` in `.agents/history/findings.jsonl` (sig `0e7d865883c7`).
  Already fixed by commit `6cdbea7`: `api_routes.py:141-143` now validates
  `customs_product_code` length (<=100 chars, 400 otherwise) matching the DB column
  (verified 2026-08-25 by findings-sweep).

Both F1 and F2 are the same underlying pattern (validate happy-path shape, not edge-case
input, before handing data to a DB layer that will raise a non-`IntegrityError` exception) —
recommend routing both together as one scoped fix-bug pass rather than two separate MRs, per
the skill's "one MR per finding class" cap.

## Attempted but clean
- `framework_applies()` (`catalogue.py:115-129`) — traced all three branches
  (`consent_required`, product-type tuple, default `all_alcohol`) against the AC; matches
  spec exactly, no bypass found for an org with `alcohol_product_types` unset (correctly
  shows everything) or set (correctly filters).
- `framework_for_profile()` (`catalogue.py:132-141`) — confirmed it returns a *new* dict via
  `dict(framework)` + `.update()`, never mutates the shared `NZ_ALCOHOL_FRAMEWORKS` module
  global in place; a subsequent call for a different org can't see a previous org's council
  overlay.
- `build_audit_pack()`'s applicability gate (`service.py:626-671`) — confirmed the
  `framework_applies()` check runs *before* `self.records(org_id, framework_slug)` and the
  org-wide movement scan, so a request for an inapplicable-but-real slug is rejected
  (`ValueError` → 400 at the route, `api_routes.py:293`) without touching the database, as
  the AC requires.
- `council_catalogue()` / `framework_by_slug()` — confirmed both return `None` (never raise)
  for unknown or `None` input, per AC.
- Cross-tenant read/write on `AlcoholProductProfile` — `product_profiles()` and
  `add_product_profile()` both filter/insert against the caller's own `org_id` only; no path
  takes an org id from the request body or query string.
- `GET /api/compliant/alcohol-products` auth-only (no role gate) vs. `POST` requiring
  `ADMIN` — checked against the spec (`Users & permissions` section), this asymmetry is
  explicitly documented as intentional, not a gap.
- `run_check()`/`register_checks()` (`module.py`) — no user-controlled input; `org_id` is
  supplied by the internal `CoreChecksRunner`, and the flag gate (`config.compliant_enabled`)
  matches the platform-wide pattern.

## not_verified
- CSRF/CORS enforcement on `/api/compliant/alcohol-products` — deferred to the
  compliant-platform review's existing coverage per this audit's scope boundary; not
  independently re-checked here.
- Live-server/E2E behavior — `live_server_tests=skip` (no app server running); the NaN and
  overlong-string crashes above were verified by direct code/type reasoning and a standalone
  Python repro of the `Decimal` comparison, not by an actual HTTP round-trip against a
  running server.
