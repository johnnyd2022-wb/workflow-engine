# SECURITY: activity-log
date: 2026-08-09
verdict: patched
scanned: semgrep(0 findings across 174 rules / 5 targeted files), gitleaks(0, 976 commits), uv-audit(0 vulnerabilities / 84 packages)
manual_checklist: 7/7 completed

## Findings

- F1 [fix] `app/core/backend/backend.py:5538` (`entity_summary_detail`) — **confirmed cross-tenant BOLA/IDOR (CWE-639)**.
  `db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == eid).first()` has no
  `org_id` filter. `entity_id` is `entity_event_summaries`'s primary key (globally unique
  across every tenant), and `eid` is parsed directly from the URL path with zero ownership
  check anywhere in the route. Any authenticated user of any org who obtains another org's
  entity UUID gets that entity's full pre-computed `summary` JSONB back.
  Severity is raised by `_parse_entity_type` allowing `entity_type in {"user", "org"}`, not
  just inventory/execution/process: `_update_user_summary` (event_writer.py:414) puts
  `email`, `role`, `login_count`, `failed_login_count`, `last_login_at` into the summary;
  `_update_org_summary` (event_writer.py:443) puts `name`, `status`, `last_changed_by`. So
  this single missing filter leaks another org's user PII and org metadata, not just
  inventory data.
  Distinguished from the inventory-list enrichment case already reviewed
  (`.agents/reports/inventory/review.md`, ruled non-exploitable because the ids that query
  filtered on were already org-scoped upstream, `entity_id` there never came from raw user
  input) — here `eid` is fully attacker-controlled with zero upstream scoping. Confirmed
  exploitable, not defense-in-depth.
  The route has **zero frontend callers** (grepped `app/*/frontend` — no reference to this
  path anywhere), but it is live, authenticated, and reachable directly. Same "dead branch,
  still a real bug" precedent as the traceability review's F2 (`sourcemap_trace`'s
  as_of-absent branch), not a reason to defer the fix.
  repro/evidence: org A user calling `GET /api/core/entities/user/<org-B-user-uuid>/summary`
  (or `entity_type=org` with another org's own id) receives that entity's `summary` JSONB in
  the response body; the sibling `recent_events` query two lines below (which does filter by
  `org_id`) correctly returns empty for the same request, confirming the gap is isolated to
  this one query.
  patch: added `EntityEventSummary.org_id == org_id` to the filter, matching the pattern
  already used by the `recent_events` query in the same handler.
  rule_added: `.semgrep/rules/learned.yml#bize-entity-event-summary-missing-org-filter`
  (fixtures: `.semgrep/fixtures/bize-entity-event-summary-missing-org-filter/{vulnerable,fixed}.py`,
  verified via `scripts/rule_candidates.py verify`)

- F2 [fix] `app/core/backend/backend.py:5365-5366` (`entity_story`) and `:5580-5581`
  (`entity_activity_feed`) — unhandled `int()` parse on `limit`/`offset` query params. A
  non-numeric value (e.g. `?limit=abc`) raises an unhandled `ValueError`. No global
  `ValueError`→400 handler is registered in `app/api/app_factory.py` (only a 401 handler
  exists), so this propagates to an uncaught 500. Same bug class the traceability review
  found and fixed for `page`/`limit`/`depth` on the sibling `/api/core/sourcemap/*` routes in
  this same file (commit `7c32b89`, F3/F4).
  repro/evidence: `GET /api/core/entities/inventory_item/<uuid>/story?limit=abc` (or
  `?offset=abc`) raises inside route body, before any response is constructed.
  patch: wrapped both call sites in `try/except (TypeError, ValueError): return
  jsonify({"error": "limit and offset must be integers"}), 400`.
  rule_added: none — the existing `learned.yml` rules don't generalise cleanly to this
  parse-site shape without over-matching legitimate `int()` calls elsewhere in the file
  (unlike traceability's equivalent finding, which also didn't get a rule for the same
  reason). Left as a manual-checklist item for future reviews of this file.

- F3 [accepted-risk, reported not remediated] `app/core/db/repositories/audit_repo.py:35`
  (`AuditRepository.list_logs_for_org`) — not a security issue. Zero callers anywhere in
  `app/`. The legacy `audit_logs` table (`AuditLog` model) is still written on some actions
  (e.g. `org.settings_updated`, confirmed via `tests/test_org_routes.py`) via `log_action()` →
  `AuditRepository.write_log`, but nothing reads it back — `_merge_inventory_legacy_audit`
  (the function the feature index describes as blending "AuditLog rows") actually reads
  `InventoryItem.extra_data["inventory_audit_history"]`, a different, third legacy format
  entirely. Net effect: `audit_logs` rows accumulate unbounded with no read path and no
  retention policy, and the feature index's description of the merge function is inaccurate.
  Not remediated here — whether to wire `list_logs_for_org` into a read surface or stop
  writing to `audit_logs` is a product decision, not a bug fix, and out of this review's
  blast radius (rule: don't refactor beyond what findings require). Reported to the user in
  the review summary for a call.

## Manual checklist (7/7)

1. **Auth on every route** — all three routes (`entity_story`, `entity_summary_detail`,
   `entity_activity_feed`) carry `@requires_auth`. None carry `@requires_role`, but this is
   uniform across the slice and consistent with the feature's evident intent (audit-trail
   visibility for any authenticated org member, not an admin-only surface) — not flagged as
   a gap on its own.
2. **Tenant isolation** — `entity_story` and `entity_activity_feed` correctly filter every
   `EntityEvent` query by `org_id`; `_merge_inventory_legacy_audit` correctly re-scopes its
   `InventoryItem` lookup by `(id, org_id)`. `entity_summary_detail` was the one gap (F1,
   now fixed). `_dashboard_event_counts_by_day` (dashboard's own direct query against
   `EntityEvent`, out of this slice) was read far enough to confirm it filters by `org_id` —
   clean, not this slice's debt to fix regardless.
3. **Mass assignment** — N/A, all three routes are GET with no request body.
4. **Injection** — no raw SQL string interpolation in the reviewed range; all queries use
   SQLAlchemy ORM filters with bound parameters. `event_writer.py`'s `_do_upsert` uses
   parameterized `text()` (out of scope, platform layer, read only far enough to confirm no
   string-formatted SQL).
5. **SSRF / uploads** — N/A, no URL or file inputs in this slice.
6. **Secrets / config** — gitleaks clean across 976 commits. No secrets in the reviewed files.
7. **CSRF / CORS** — all three routes are read-only GETs; no state change, CSRF not
   applicable. No CORS wildcard in the reviewed files.

## Attempted but clean

- Checked whether `entity_type == "user"`/`"org"` combined with F1 allowed privilege
  escalation (e.g. altering another user's role) — no, all three routes are read-only; the
  leak is confidentiality (PII/org metadata disclosure), not integrity.
- Checked `_load_existing_summary` (event_writer.py:224, also `entity_id`-only, no `org_id`)
  for the same class of bug — not exploitable: this is a write-path internal helper called
  only with an `entity_id` already trusted from the `EntityEvent` being persisted (itself
  created by app business logic already scoped to the correct org), never from raw request
  input. Out of scope (platform/writer layer) and not attacker-reachable.
- Checked `_smart_list_diff_rows`/`_build_diff_rows`/`_fmt_field_value` for injection via
  crafted `diff`/`payload` JSONB (these values are echoed into JSON responses, not
  HTML/templates) — output is JSON-serialized, not rendered via `| safe` or `innerHTML` on
  the server side; frontend escaping is `traceability`'s AC24 concern for the shared
  `sourcemap.js` rendering path, not re-litigated here.
- Checked `_parse_entity_type`'s fixed allowlist for injection/enumeration risk — it's a
  closed set (`{"inventory_item", "execution", "process", "user", "org"}`), no wildcard or
  reflection.

not_verified: browser-side XSS on the diff-rendering surfaces in `sourcemap.js`/`view.html`
consuming this slice's `summary`/`diff_rows` fields — covered by traceability's AC24, not
re-checked here since the rendering code lives outside this slice.

VERDICT: patched
