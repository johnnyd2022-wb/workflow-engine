# security-tenant-audit — process_templates

engine: codex (gpt-5.6-sol, effort high), `--sandbox read-only` via direct CLI
invoked_as: chain stage (called by new-feature) — read-only grader, no remediation performed
verdict: clean

Report captured and written by the orchestrator on the grader's behalf per
`.agents/verification-chain.md` §5: the read-only sandbox correctly rejected the
grader's own attempt to write this file (`patch rejected: writing is blocked by
read-only sandbox`), so this is a verbatim transcription of its findings, not a
summary written from memory.

## Scope

Diff: `git diff proc-template...HEAD -- app/` (17 files touched in
`app/features/process_templates/`, `app/api/app_factory.py`,
`app/core/backend/backend.py`, `app/core/frontend/core/core2.html`,
`app/core/frontend/processes/{flow-create-chooser.html,list.html}`).

Independently re-verified — not just trusted — the prior `security-audit` pass's
tenant-isolation claims, per its own instruction: "verify independently."

## What was checked (and how)

1. **`_resolve_permitted_families` call sites.** Confirmed every caller in
   `process_templates_service.py` (`list_catalog`, `get_template_detail`,
   `copy_template`) receives `org_id` from the route layer's `UUID(g.org_id)` — never
   from a request body, query param, or path segment. Traced `g.org_id`'s own origin to
   `tenant_context.py:122`, set from the server-side `Organisation` row loaded via the
   session-authenticated user (`tenant_context.py:87-124`), not from client input at any
   point in the chain.

2. **`get_permitted_template` / `templates_for_families` (registry.py).** Confirmed
   both the detail-fetch (`get_template_detail`) and copy-action (`copy_template`) call
   sites intersect the requested `template_id`'s family against the caller's
   server-resolved permitted-family set before returning/acting — no code path returns
   or copies a template whose family isn't in that set.

3. **`sample_only` override in `backend.py`'s `complete_step`.** Confirmed the lookup
   reads only `execution_step.step.outputs` — `execution_step` is the same,
   already-org-scoped object the rest of `complete_step` operates on
   (`org_id = UUID(g.org_id)` gates the whole handler). The override matches by output
   *name* within that single step's own static output list only; a crafted
   `actual_outputs` payload in the request body cannot make it read another org's step
   definitions, since which step's outputs it reads is never client-controlled.

4. **Every route in `api_routes.py`/`page_routes.py`.** Re-verified `@requires_auth` on
   all four (`list`, `detail`, `copy`, catalogue page) and that `org_id` in every DB
   call is `UUID(g.org_id)`, never client input.

5. **The static-asset route rename (`static` → `serve_process_templates_static`).**
   Verified by actually registering the blueprint and iterating
   `app.url_map.iter_rules()`: the live endpoint name is
   `process_templates.serve_process_templates_static`, which does not end in `.static`
   — confirming `tenant_context.py:71`'s public-endpoint skip no longer applies and
   `g.current_user` is populated before `@requires_auth` runs, i.e. the F1 fix from
   `e2e-playwright.md` is real, not just claimed by that report.

## Findings

None. No tenant-isolation or missing-auth defect found.

VERDICT: clean
