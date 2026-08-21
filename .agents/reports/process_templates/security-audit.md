# SECURITY: process_templates (chain-stage audit)
date: 2026-08-22 (re-confirmation of 2026-08-21 run — same branch/diff, independently re-verified)
invoked_as: chain stage (called by new-feature) — read-only grader, no remediation performed
verdict: clean
scanned: semgrep(2 findings, both false-positive), gitleaks(0), uv-audit(0; no dependency changes in this diff)
manual_checklist: 7/7 completed
diff_scope: `git diff proc-template...HEAD` (22 files, +2240/-2) per .agents/specs/process_templates.md

## Re-confirmation note

A prior security-audit run on this same branch (2026-08-21T20:13:44Z, recorded in
`.agents/history/findings.jsonl` sigs `beac3e6b1244`/`2e8f6b73ef37`) reached the same two
scanner findings and the same manual-checklist conclusions documented below. This run
independently re-ran semgrep/gitleaks/uv audit against the current diff and re-read every
route, service function, and repository call cited below from scratch — same result. The
process note directly below is carried over from that prior run because it flags a real,
still-unresolved process issue that a human needs to see, not because it was taken on faith.

## Process note (self-correction, flagging for human review)

The prior run recorded `scripts/finding_history.py record --verdict false-positive` on both
semgrep findings below (sigs `beac3e6b1244`, `2e8f6b73ef37`). Per this skill's own rule
("Only a human's call is `false-positive`/`accepted-risk`; you may record `confirmed`/`fixed`
yourself") and `.agents/history/README.md`, that verdict may only be granted by a human — it
should have recorded nothing and left the false-positive call in the report only. The
technical determination itself (both are mitigated, detailed below) holds up under this
run's independent re-check too, but the two history-store entries still need a human to
actually confirm/ratify them. This run did **not** call `finding_history.py record` again —
re-recording would not fix the original overstep, and `decide` against both signatures today
still returns `new` under a slightly different evidence string, confirming no human verdict
has landed since. Until a human ratifies, treat those two history-store entries as an
agent's unconfirmed recommendation, not an authoritative suppression.

## Findings

- F1 [false-positive, pending human confirmation — see process note] `app/features/process_templates/frontend/static/template-catalog.js:129-137` semgrep `innerhtml-string-concat` on `renderPreview`'s `modalBodyEl.innerHTML = ...` string-concat.
  evidence: every interpolated value (`detail.name`, `detail.description`, `detail.traceability_shape`, `detail.advisory`, and each input/output/prompt list item built in the `.map()` calls above) is passed through the file's own `escapeHtml()` (line 9-13, a `div.textContent` round-trip) before concatenation. No raw API/user string reaches `innerHTML`.
  patch: none needed.
  rule_added: none — pattern is "innerHTML via concat" with no way to distinguish escaped-before-concat from the vulnerable shape without dataflow, which is exactly what makes this a scanner-class false-positive rather than a rule gap.

- F2 [false-positive, pending human confirmation — see process note] `app/features/process_templates/frontend/static/template-catalog.js:145-148` semgrep `raw-fetch-post` on `useTemplate`'s `fetch(.../copy, {method: "POST", headers: csrfHeaders()})`.
  evidence: `csrfHeaders()` (line 4-7) reads `meta[name="csrf-token"]` and sets `X-CSRFToken` — exactly the mitigation the rule's own message recommends for non-CoreAPI-client fetches ("read the token from meta[name=csrf-token] and pass it as the X-CSRFToken header").
  patch: none needed.
  rule_added: none — same shape as F1; the rule can't see that the header is attached without dataflow into the `headers` object literal.

## Attempted but clean

- **Auth on every route.** All three new/changed routes carry `@requires_auth`: `api_routes.py` (list/detail/copy), `page_routes.py` (catalogue page), `backend.py:898` (`/core/flows/create/start` chooser), and the static-asset route in `process_templates_bp.py:19` serving `template-catalog.js`/`.css`. No bare route found.
- **Tenant isolation.** `_org_id()` reads `g.org_id`, set by `tenant_context` middleware before any route body runs (`app/api/middleware/tenant_context.py:122`) — never a client-supplied value. `_resolve_permitted_families` reads `ComplianceProfile` server-side via `ComplianceService(session).get_profile(org_id)`, itself org-filtered (`compliant/service.py:198-199`). `get_permitted_template` rejects a real catalogue id whose family isn't in the caller's permitted set → 404, not 403 (AC3, tested `test_ac3_detail_404_for_org_without_permitted_family`). Copy writes go through `ProcessRepository.create_process`/`add_step`, both taking `org_id` and writing it onto the row; cross-org read of a template-sourced process is proven blocked via `ProcessRepository.get_process_by_id`'s existing `(id, org_id)` filter (`test_ac7_copy_is_tenant_scoped`). The `sample_only` addition in `backend.py:2327-2337` reads `execution_step.step.outputs` — `execution_step`/`execution` are the pre-existing, already org-scoped objects the rest of `complete_step` operates on (`org_id = UUID(g.org_id)` at `backend.py:2070`); the new code adds no new query and matches by output name only within that single, already-tenant-scoped step's own output list, so it can't reach or leak another org's step definitions.
- **Mass assignment.** No route in this diff loads `request.json` into a model constructor or via looped `setattr`. `complete_step`'s body goes through `CompleteStepRequestBody.model_validate` (pydantic schema, pre-existing) before use; the process-templates routes take no client body at all (list/detail are GET, copy takes no body — the whole payload for the created `Process`/`Step` comes from the static, server-only `registry.py` catalogue).
- **Injection.** No raw SQL anywhere in the diff — all DB access is via SQLAlchemy ORM (`ProcessRepository`, `ComplianceService`). No `subprocess` calls. `template_id` (path param, e.g. `distillery_receive_ingredient_lot`) is only ever compared for equality against a static in-process Python list (`registry.get_template_by_id`) — never interpolated into a query or the filesystem. The static-file route (`process_templates_bp.py:18-23`) rejects any `filename` containing `/` or `..` or not ending in `.js`/`.css` before `send_from_directory` — traversal closed (the `/`-rejection also makes the `path:` converter's slash-matching moot, since any slash 400s).
- **SSRF / uploads.** None — no user-supplied URLs, no file uploads anywhere in this feature (spec's own "External surfaces: none" holds).
- **Secrets and config.** gitleaks: 0 leaks in the diff's commit. No secrets, tokens, or credentials in `registry.py` or anywhere else in the new code.
- **CSRF and CORS.** The one new state-changing route (`POST /api/core/process-templates/<id>/copy`) is called from the frontend via `csrfHeaders()` (see F2 above) — consistent with the app's session-based CSRF model. No CORS changes in this diff.

## Not verified

- Did not re-run the full `pytest tests/test_process_templates.py` suite as part of this audit (that's e2e-playwright/new-feature's own verification step, not this stage's job) — I read the AC2/AC3/AC5/AC6/AC7/AC9 test bodies directly (`tests/test_process_templates.py:252-401`) to confirm they assert what the ACs claim, rather than executing them.
- Did not audit `app/core/backend/backend.py` beyond the two diff hunks (the new `/core/flows/create/start` route and the `sample_only` override block) — the rest of `complete_step`'s pre-existing logic (inventory consumption, quantity conversion) is unchanged and out of this diff's scope.

## Rule added this run

None. Both scanner findings were determined to be already-mitigated false positives with no reliable dataflow-aware rule available to distinguish them from the real vulnerable shape (see F1/F2 `rule_added` lines) — no manual-pass finding surfaced a new vulnerability class either.
