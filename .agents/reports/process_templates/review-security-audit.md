# SECURITY (review pass): process_templates
date: 2026-08-22
invoked_as: chain stage (called by review-feature) — read-only grader, no remediation performed
verdict: clean
scanned: semgrep(0 findings), gitleaks(0 in-scope), uv-audit(0 vulnerabilities)
manual_checklist: 7/7 completed
scope: `app/features/process_templates/` (all files) + the `app/core/backend/backend.py`
hunk touched by this feature (`flows_create_start_chooser`, and the `sample_only`
override block in `complete_step`, lines ~2318-2337). This feature already went through
a build-time audit (`.agents/reports/process_templates/security-audit.md`,
`security-tenant-audit.md`, both clean) — this is an independent re-audit, not a
re-statement of those.

## What's different about this pass vs. the two build-time audits

Same codebase, same conclusion (clean), reached independently:

- Re-ran semgrep/gitleaks/uv audit scoped to the feature directory + the backend.py
  hunk, from scratch, rather than trusting the prior scan output.
- **Actually executed** `tests/test_process_templates.py` (29/29 passed) instead of
  only reading test bodies to confirm they assert what the ACs claim — the prior
  `security-audit.md` explicitly listed "did not re-run the full pytest suite" under
  `not_verified`; this pass closes that gap.
- Independently traced `ComplianceService.get_profile` (`app/features/compliant/service.py:198-199`),
  `ProcessRepository.get_process_with_steps` (`app/core/db/repositories/process_repo.py:444-451`),
  and confirmed no route exposes `registry.register_family`/`unregister_family`/
  `unregister_template` (grep against `routes/` and `services/` — zero hits; these
  mutators are test-only helpers, unreachable from any HTTP surface).
- Read the frontend JS (`template-catalog.js`) and both Jinja templates
  (`flow-create-chooser.html`, `template-catalog.html`) line-by-line rather than
  relying on the semgrep triage note alone.

## Scanner pass

- **semgrep** (`p/python`, `p/flask`, `p/owasp-top-ten`, `.semgrep/`, scoped to
  `app/features/process_templates/` + `app/core/backend/backend.py`): **0 findings.**
  The build-time audit's two findings (`innerhtml-string-concat` at
  `template-catalog.js:129-137`, `raw-fetch-post` at `template-catalog.js:145-148`)
  are now silent because inline `# nosemgrep:`/`// nosemgrep:` justification comments
  were added in commit `9c05156` ("move nosemgrep directives inline to fix CI") —
  confirmed present at `template-catalog.js:132` and `:150`, each with an adjacent
  "Audited: ..." comment explaining the mitigation (escapeHtml round-trip / explicit
  CSRF header). This is the correct outcome per the security-audit skill's own rule
  (scoped suppression + justification, not a blanket ignore) — re-verified the
  underlying claim is still true by reading the current file (see Manual pass below),
  not just the comment.
- **gitleaks** (`--source app/features/process_templates`, full history): 65 raw hits,
  **0 in the feature's own path**. All 65 are pre-existing `generic-api-key` matches in
  unrelated files across repo history (`.agents/reports/org/gitleaks.json`,
  `.agents/reports/auth/gitleaks.json`, `app.py`/`app.py.bak`/`app.py.xero_processing_updates_in_progress`,
  `config/prod.ini`, CI shell scripts, skill docs) — gitleaks scans full git history
  regardless of `--source`, so these are noise from the repo's standing count, not
  something this feature introduced. Not this audit's finding to action; consistent
  with the security-audit skill's note that a bare scan over the whole repo returns a
  standing pre-existing count and the signal is the *diff* against it, which here is
  zero new hits.
- **uv audit**: 0 vulnerabilities, 0 adverse statuses. No dependency changes in this
  feature.

## Manual pass (7/7)

1. **Auth on every route** — confirmed on all four routes: `api_routes.py` list/detail/copy
   (`@requires_auth`, lines 21/31/42), `page_routes.py`'s catalogue page (line 11),
   `backend.py:898`'s new chooser route, and `process_templates_bp.py:29`'s static-asset
   route (`serve_process_templates_static` — deliberately *not* named `static` so
   `tenant_context.py`'s `.static`-suffix public-endpoint skip doesn't apply; confirmed
   the reasoning in the code comment against `app/api/middleware/tenant_context.py:71`).
   No bare route.

2. **Tenant isolation** — independently re-traced the full chain rather than trusting
   the two prior reports:
   - `_org_id()` (`api_routes.py:16-17`) reads `g.org_id`, set by `tenant_context`
     middleware from the session-authenticated user, never client input.
   - `_resolve_permitted_families` (`process_templates_service.py:26-30`) calls
     `ComplianceService(session).get_profile(org_id)`, which filters
     `ComplianceProfile.org_id == org_id` server-side
     (`app/features/compliant/service.py:198-199`) — confirmed by reading the method
     directly, not just the prior report's citation.
   - `get_permitted_template`/`templates_for_families` (`registry.py:136-147`) both
     intersect the requested id/filter against the caller's server-resolved family set;
     no path returns or copies an unpermitted family (AC3).
   - Copy path: `ProcessRepository.create_process`/`add_step` write `org_id` onto the
     row from the server-resolved value, never from client input. Cross-org read of a
     template-sourced process is blocked by `get_process_with_steps`'s
     `Process.org_id == org_id` filter (confirmed by reading the method:
     `process_repo.py:444-451`) — this is the method the real `GET /api/core/processes/<id>`
     route uses, per the test's own comment about an earlier, weaker test version.
   - `sample_only` override (`backend.py:2318-2337`) reads only
     `execution_step.step.outputs` — `execution_step` is the same, already org-scoped
     object the rest of `complete_step` operates on (`org_id = UUID(g.org_id)` at
     `backend.py:2070` gates the whole handler); the override matches the client-supplied
     `actual_outputs[].name` against that single step's own static output list only, so
     a crafted payload can change inventory classification of *that step's own output*
     at most, never reach another org's data.
   - Ran the actual test suite (see below) rather than only reading assertions.

3. **Mass assignment** — no route loads `request.json`/`request.args` into a model
   constructor or via looped `setattr`. List/detail are GET with no body; copy takes no
   client body — the entire `Process`/`Step` payload originates from the static,
   server-only `registry.py` catalogue.

4. **Injection** — no raw SQL; all access via SQLAlchemy ORM. `template_id` (path
   param) is only ever compared for string equality against the in-process catalogue
   list (`registry.get_template_by_id`), never interpolated into a query or a
   filesystem path. The static-asset route rejects any `filename` containing `/` or
   `..`, or not ending in `.js`/`.css`, before `send_from_directory` — traversal closed.

5. **SSRF / uploads** — none. No user-supplied URLs, no file uploads anywhere in this
   feature.

6. **Secrets and config** — 0 leaks in the feature's own path (see gitleaks above). No
   secrets/tokens in `registry.py` or any new file.

7. **CSRF and CORS** — the one state-changing route (`POST .../copy`) is called with an
   explicit `X-CSRFToken` header read from `meta[name="csrf-token"]`
   (`template-catalog.js:150-152`, `csrfHeaders()`), matching the app's session-based
   CSRF model. No CORS changes.

## Frontend XSS re-check (beyond the semgrep-flagged lines)

Read `template-catalog.js` in full, not just the two flagged spans. Every
server-response field rendered via string-concatenated `innerHTML` —
`renderFilters` (family key/name), `renderCards` (family/name/traceability_shape/units),
`renderPreview` (name/description/traceability_shape/advisory, and each input/output/
prompt list item) — is passed through the file's own `escapeHtml()` (a
`div.textContent`-round-trip, `template-catalog.js:9-13`) before concatenation. The one
field left unescaped is `t.step_count` (`template-catalog.js:72`), which is a
server-computed integer (always `1`, per `_template_summary`'s hardcoded
`"step_count": 1`, `process_templates_service.py:40`), not a string field — no injection
surface. `flow-create-chooser.html` and `template-catalog.html` render no user- or
request-derived data (static copy only) — no server-side template injection surface.

## AC4 extensibility / registry mutation surface

Confirmed `registry.register_family`/`unregister_family`/`unregister_template` (used by
the AC4 unit test to register a synthetic second module) are not reachable from any
route — grepped `app/features/process_templates/routes/` and `services/` for these
names: zero hits outside the registry module itself and the test file. No
runtime-registry-mutation attack surface exists.

## Independent test-suite run (closes prior audit's `not_verified` gap)

```
env -u ENVIRONMENT uv run pytest tests/test_process_templates.py -v
```
Result: **29 passed**, 0 failed, 0 skipped. This includes
`test_ac3_detail_404_for_org_without_permitted_family`,
`test_ac6_copy_404_for_org_without_permitted_family`,
`test_ac7_copy_is_tenant_scoped` (proven against `get_process_with_steps`, the exact
method the real route calls), and `test_ac9_sample_only_output_is_work_in_progress_even_though_terminal`.
The prior `security-audit.md` read these test bodies but explicitly did not execute
them; this run did, and they pass against the current code, not just against what the
assertions claim to check.

## Attempted but clean

- Probed for a client-controlled override of `compliant_enabled`/`industry_module`
  anywhere in the request path (query param, header, body) — none found; both values
  are read exclusively from the server-loaded `ComplianceProfile`.
- Probed whether the `family` query filter could *expand* visible templates beyond the
  server-resolved permitted set — `templates_for_families` does `set(families) &
  {family_filter}`, an intersection, so it can only narrow, never add
  (`registry.py:136-140`).
- Probed the registry-mutation functions (`register_family` et al.) for route exposure
  — none; test-only.
- Probed `sample_only` override for cross-tenant reach — confirmed it operates only on
  the single, already org-scoped `execution_step` already in scope for the rest of
  `complete_step`.

## Not verified

- Did not audit `complete_step`'s pre-existing logic (inventory consumption, quantity
  conversion, the rest of the function) beyond the new `sample_only` hunk — unchanged
  by this feature and out of scope for both this and the prior audit.
- Live-server/browser-driven checks were skipped per this run's preflight
  (`live_server_tests: skip` — no app server listening); the catalogue page and modal
  were verified by reading the rendered templates/JS and by the unit test suite
  (`test_ac12_*`, `test_ac13_*`), not by clicking through a running instance.

## Rule added this run

None — no new vulnerability class surfaced. The two previously-flagged semgrep
patterns remain correctly suppressed with inline justification (not a new finding to
write a rule against); everything else this pass checked was already covered by the
existing manual-checklist categories.

## Findings

None.

VERDICT: clean
