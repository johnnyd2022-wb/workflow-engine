# Semgrep Remediation Plan

**Branch:** `chore/semgrep-remediation`
**Snapshot taken:** 2026-07-19 (semgrep 1.139.0, `--config .semgrep/rules/ app/ --include="*.py" --include="*.js"`)
**Total findings:** 116 — 10 ERROR, 104 WARNING, 2 INFO

This document is the running order for clearing the semgrep backlog. Work the groups
**top to bottom** — they are ordered by impact (real risk × blast radius), not by count.
Each group is an independent, self-contained batch: fix it, run the group's verify
command, commit, move on. Do not bundle groups into one mega-commit — small commits keep
the review and any revert cheap.

## CI context (read first — it changes the urgency)

Two semgrep jobs run in `.gitlab-ci.yml`:

- **`semgrep_observability`** — `allow_failure: false` (**blocking**), but only
  `--severity ERROR` against `observability.yml`. That file's only ERROR rule is
  `no-print-in-app`, which has **0 findings today**. So the blocking gate is currently
  green, and none of the 116 findings are failing CI right now.
- **`semgrep`** — the full-ruleset run, `allow_failure: true` (**non-blocking**). Every
  finding below surfaces here but does not block a merge.

**Implication:** this is backlog cleanup, not a fire. But two of the ERROR groups are
genuine security posture (CSRF, XSS) and should be treated as if they were blocking. The
end-state goal is to get the full `semgrep` run clean enough to flip it to
`allow_failure: false` — see "Definition of done".

## Verify commands

```bash
# Whole run (baseline / final check)
semgrep --config .semgrep/rules/ app/ --include="*.py" --include="*.js" --error

# One rule at a time while working a group
semgrep --config .semgrep/rules/ app/ --include="*.py" --include="*.js" \
  --json --quiet | python3 -c "import json,sys;print(len([r for r in json.load(sys.stdin)['results'] if r['check_id'].endswith('RULE_ID')]))"

# App + suite must stay green after each group (ENVIRONMENT unset — see CLAUDE.md)
uv run pytest tests/ -v
```

Always re-run the full baseline after a group so a fix in one file doesn't regress another
rule's count.

---

## Group 1 — `route-missing-requires-auth` (2 × ERROR) — DO FIRST

**Why first:** ERROR severity, security-class rule (missing auth is the one class the
custom `python-multitenant.yml` ruleset exists to catch), and it's only 2 sites — highest
signal, lowest effort.

| Finding | Location |
|---|---|
| `/telemetry` (Faro ingest) | `app/api/app_factory.py:208` |
| `/telemetry/posthog/<path>` | `app/api/app_factory.py:229` |

**These are almost certainly false positives.** Both are the same-origin telemetry proxy
routes — deliberately public, `@limiter.limit("120 per minute")`, and forward only to
fixed upstreams. Adding `@requires_auth` would break browser RUM ingestion.

**Action:** do NOT add auth. Suppress with justification so the rule stays honest for real
regressions. Preferred: add each route's file/pattern to the `paths.exclude` list in
`.semgrep/rules/python-multitenant.yml` (it already excludes `auth_routes.py` and
`app.py`), OR add a `# nosemgrep: route-missing-requires-auth` line with a one-line reason
above each decorator. Pick the exclude-list approach if you expect more public telemetry
routes; otherwise inline `nosemgrep` keeps the exception visible at the call site.

**Confirm** each route is genuinely meant to be public before suppressing — read the
handler, confirm no tenant data is returned. (Verified in this snapshot: both only proxy
to telemetry upstreams.)

**Verify:** rule count → 0. `uv run pytest tests/ -v`.

---

## Group 2 — `raw-fetch-post` (8 × ERROR) — CSRF surface

**Why second:** ERROR severity, real security relevance — this app is CSRF-protected via
Flask-WTF and SPA calls must send the `X-CSRFToken` header (see CLAUDE.md → Security). A
raw `fetch(..., {method:'POST'})` with no CSRF header is either a bug waiting to 400, or a
route that isn't protected. Either way it needs eyes.

| Location | Likely disposition |
|---|---|
| `app/core/frontend/js/flows2-steps.js:752` | app POST — check CSRF header |
| `app/core/frontend/js/inventory-adjust.js:169` | app POST — check CSRF header |
| `app/core/frontend/js/process-flow-next-steps-steps.js:469` | app POST — check CSRF header |
| `app/core/frontend/js/sourcemap.js:675` | app POST — check CSRF header |
| `app/ui/shared/account-info.js:92` | app POST — check CSRF header |
| `app/ui/shared/password-policy.js:27` | app POST — check CSRF header |
| `app/ui/shared/workflow-engine-settings.js:144` | app POST — check CSRF header |
| `app/ui/shared/posthog-array.full.js:1` | **vendored third-party bundle — suppress, don't edit** |

**Action:**
1. Find the shared CSRF-aware fetch helper already used elsewhere in the SPA (grep for
   `X-CSRFToken` in `app/ui/shared/`). Route the 7 first-party POSTs through it, or add the
   header explicitly to match the established pattern.
2. `posthog-array.full.js` is a vendored PostHog bundle — do not hand-edit. Either exclude
   vendored bundles from the scan in `.semgrep/rules/js-security.yml` `paths.exclude`
   (recommended — add `**/*.full.js` or the shared vendor path), or inline-suppress.

**Verify:** rule count → 0. Manually exercise one adjusted POST (e.g. inventory-adjust) via
e2e or the app to confirm the request still succeeds with the CSRF header.

---

## Group 3 — DOM XSS sinks: `innerhtml-template-literal` (30) + `innerhtml-string-concat` (16) + `insertadjacenthtml` (8) — 54 × WARNING

**Why third:** WARNING severity but the highest **real-risk** group by volume — every one
is an untrusted-string-into-DOM sink, i.e. stored/reflected XSS potential in a
multi-tenant app. Treat as security work despite the WARNING label.

**Concentration matters — fix by file, biggest first:**

| File | Sink count |
|---|---|
| `app/core/frontend/js/sourcemap.js` | 27 |
| `app/core/frontend/js/app.js` | 4 |
| `app/core/frontend/js/execution-render-outputs.js` | 4 |
| `app/core/frontend/js/create-process-modal.js` | 3 |
| `core-active-batches-graph.js`, `core.js`, `execution-render-prompts.js` | 2 each |
| ~10 more files | 1 each |

`sourcemap.js` alone is half the group — start there; the fix pattern you establish will
apply to the rest.

**Action (per sink, in priority order):**
1. **Does the string contain any user/tenant data?** If it's built only from hardcoded
   literals, it's a low-risk stylistic finding — still fix, but it's not an XSS.
2. Preferred fix: replace `el.innerHTML = ...` / `insertAdjacentHTML` with
   `textContent`, `createElement` + `append`, or an escaping helper. Grep the SPA for an
   existing escape/sanitise utility before writing a new one (`app/ui/shared/`).
3. Where markup genuinely must be built, centralise on one sanitiser so this doesn't
   regress.

This is the largest and most tedious group — expect it to be several commits (one per file
or per small cluster of files). Do NOT blanket-suppress; each needs the "is this data
tainted?" judgement.

**Verify:** rule counts → 0 across all three rule ids. Re-render the affected views
(execution outputs, process modal, batches graph, sourcemap view) in the app or via e2e to
confirm nothing broke visually.

---

## Group 4 — `no-stdlib-getlogger` (49 × WARNING) — observability consistency

**Why fourth:** largest single group by count, but **lowest per-item risk** — it's a
consistency rule (use structlog `get_logger()` not stdlib `logging.getLogger()`), not a
security or correctness issue. High volume, mechanical, low judgement → ideal for a fast
batch once the risk-bearing groups are done.

**Concentration is extreme:**

| File | Count |
|---|---|
| `app/core/backend/backend.py` | 24 |
| ~25 other files | 1 each |

`backend.py` is half the group. The other 25 are one-liners.

**Action:** mechanical swap to the repo's structlog helper. Grep for the canonical import
(`from ... import get_logger` / `structlog.get_logger`) used elsewhere and match it
exactly — same logger-name convention. This is find-and-replace-with-care, not redesign.
Watch for any place that relies on stdlib logger behaviour (handlers, `.setLevel`) — those
need a real look, not a blind swap.

**Verify:** rule count → 0. `uv run pytest tests/ -v` — logging changes can break tests
that assert on log output.

---

## Group 5 — Cleanup tail: `prefer-structlog-over-current-app-logger` (2 × INFO) + `setinterval-result-discarded` (1 × WARNING)

**Why last:** 3 findings, INFO/low-WARNING, no risk. Sweep them in a single final commit.

| Finding | Rule |
|---|---|
| 2 sites | `prefer-structlog-over-current-app-logger` — swap `current_app.logger` → `get_logger()` (pairs naturally with Group 4) |
| 1 site | `setinterval-result-discarded` — capture the interval id and clear it on teardown to avoid a leaked timer |

**Verify:** full baseline run → 0 findings.

---

## Definition of done

1. `semgrep --config .semgrep/rules/ app/ --include="*.py" --include="*.js" --error`
   exits **0 findings** (suppressions counted as resolved, each with a written reason).
2. `uv run pytest tests/ -v` green (expect `252 passed, 30 skipped` with no dev server).
3. Every suppression (Groups 1, 2-vendor) has an inline reason or a commented
   `paths.exclude` entry — no silent `nosemgrep`.
4. **Then** flip the `semgrep` job in `.gitlab-ci.yml` from `allow_failure: true` to
   `false` so the cleaned-up state is enforced going forward. Do this as the final commit,
   separately, so it's easy to see and easy to revert if the runner behaves differently
   from local.

## Suggested commit sequence

```
1. chore(semgrep): mark public telemetry routes as intentionally unauthenticated   [Group 1]
2. fix(security): send CSRF header on SPA POSTs; exclude vendored bundles           [Group 2]
3. fix(security): escape untrusted data in sourcemap.js DOM sinks                   [Group 3a]
4. fix(security): escape remaining innerHTML/insertAdjacentHTML sinks               [Group 3b...]
5. refactor(logging): use structlog get_logger across backend                      [Group 4]
6. chore(semgrep): sweep current_app.logger + leaked setInterval                   [Group 5]
7. ci: make the semgrep job blocking now the backlog is clear                      [DoD #4]
```

## Notes for the implementer

- Run `uv run pytest` with **`ENVIRONMENT` unset** (resolves to `local` → test DB on
  `localhost:8401`). Setting `ENVIRONMENT=test` from the host hangs. See CLAUDE.md.
- The `security-audit` skill can drive this whole class of work if you'd rather orchestrate
  it than hand-fix — but for a bounded 116-finding backlog, straight-line fixing by group
  is faster and gives cleaner commits.
- Re-baseline after **every** group. A change in a shared JS file can move more than one
  rule's count.
