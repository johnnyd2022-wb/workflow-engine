# SECURITY: process-design
date: 2026-08-02
mode: chain stage (read-only grader for review-feature) — no patches applied
verdict: findings-open
scanned: semgrep(0 findings), gitleaks(0), uv-audit(0 vulnerabilities)
manual_checklist: 7/7 completed

## Scope
`app/core/backend/backend.py:139-424` (flow-wizard state, `_safe_flow_return_to`,
`_assert_flow_process_access`, `_assert_valid_step_write`), `backend.py:855-1022`
(create wizard), `backend.py:1201-1694` (process/step CRUD + reorder),
`app/core/backend/process_docs/` (routes/service/validation/storage),
`app/core/db/repositories/process_repo.py`,
`app/core/db/repositories/process_step_document_repo.py`.

## Scanner pass
- `semgrep --config p/python --config p/flask --config p/owasp-top-ten --config .semgrep/`
  scoped to the 8 files above: **0 findings** (174 rules run).
- `gitleaks detect` (repo-wide, 939 commits): **no leaks found**.
- `uv audit --frozen`: **0 vulnerabilities**, 84 packages audited (project-wide; nothing
  process-design-specific to scope this to).
- Prior finding-history lookup for the two known items below: both `new` (no prior
  human verdict) — triaged fresh in this run, recorded `confirmed`.

## Findings

- F1 [fix] backend.py:272-292 `_assert_valid_step_write` — **CONFIRMED dead code.**
  `grep -rn "_assert_valid_step_write" app/ tests/` returns only the definition line;
  zero call sites in any route (`add_step`, `update_step`, `reorder_steps` all skip
  it). Its docstring claims it "prevents inconsistent state caused by skipping ahead
  or colliding step numbers," which is not true of the shipped behavior. Note: even if
  wired in, its body is a no-op beyond a 400 on invalid `requested_step_number` and an
  org-scope 404 (both already independently enforced elsewhere) — it builds a step_number
  list and explicitly declines to enforce uniqueness ("Option B: step_number is not
  canonical ordering. No uniqueness enforcement here."). So this is dead code with an
  overclaiming docstring, not a live authorization/integrity gap — remediation is
  delete-or-wire-in, not urgent, but should not ship with a docstring lying about
  what's enforced.
  repro/evidence: `grep -rn "_assert_valid_step_write" app/ tests/` → 1 match (the def).
  rule_added: none — not mechanically distinguishable from other unused-helper cases
  without high false-positive rate; recommend `ruff`/vulture dead-code pass instead of a
  bespoke semgrep rule.

- F2 [fix] backend.py:1638-1663 `reorder_steps` — **CONFIRMED, both parts.**
  (a) Connection leak: opens `sess = SessionLocal()`, enters `with sess.begin():`, and
  four paths return early from inside that block — process-not-found (1643),
  no-steps-to-reorder (1649), unknown-step-id (1653), zero-row-update (1660) — each
  skipping the `sess.close()` at line 1662, which only executes on the success path.
  Every failed reorder call (a bad step id, an already-empty process, or a race losing
  the row-lock update all trip this) leaks one pooled connection. (b) No audit trail:
  unlike `add_step`/`update_step`/`delete_step`, this handler never inserts a
  `ProcessVersion` snapshot nor calls `EventWriter.emit` after committing position
  changes — reordering is invisible to `traceability`/activity-log despite being a
  real mutation of process state.
  repro/evidence: read backend.py:1591-1674 directly; the `with sess.begin():` block's
  four `return jsonify(...)` statements at lines 1643, 1649, 1653, 1660 all precede the
  unreachable-on-those-paths `sess.close()` at 1662.
  rule_added: none this run (chain-stage, no patch) — recommend a `learned.yml` rule
  for "return inside `with sess.begin():` before the matching `.close()`" once
  fix-bug's patch shape is known, so the next occurrence of this pattern elsewhere in
  the app is caught by machine.
  patch: both parts fixed — backend.py's `reorder_steps` now wraps the whole body in
  try/except/finally with `sess.close()` in `finally`; process_repo.py's `reorder_steps`
  now calls `_insert_process_version()` and `EventWriter.emit('process.steps_reordered')`.
  Regression test: `tests/test_process_design.py::test_ac9_reorder_writes_process_version_and_emits_event`
  (verified 2026-08-08 by findings-sweep).

- F3 [accepted-risk candidate, escalate] backend.py:1394 `DELETE /api/core/processes/<id>`
  has only `@requires_auth`, no `@requires_role(ADMIN)` — yet it is strictly more
  destructive than `DELETE /api/core/process-docs/<doc_id>` (which *is* ADMIN-gated):
  it cascades to delete every step under the process and (via DB `ON DELETE CASCADE`)
  every `ProcessVersion` snapshot — the entire version history a process ever had,
  including history predating the current wizard revision. Grep of all
  `@core_bp.route` process/step handlers (list/create/update/delete process; add/
  update/delete step; reorder) confirms **zero** carry `@requires_role`; only
  process-docs DELETE does. This may be the intentional "process design is a shared
  team activity" choice the spec's ASSUMPTION calls out — but if so, the asymmetry
  (single-file delete gated, whole-process-plus-history delete not) reads as
  inconsistent rather than deliberate, and is worth a human call rather than being
  waved through. Recommend: either drop the process-docs ADMIN gate for consistency,
  or add one to process delete — not a decision this audit self-approves.

## Attempted but clean

- **Tenant isolation** — every process/step read/write in `process_repo.py` and every
  process-docs query in `process_step_document_repo.py` filters by `org_id` sourced
  from `g.org_id`/`g.current_org_id` (via `_org_uuid()` / `_get_process_or_404()`),
  never from request body/query string. Confirmed no route passes a client-supplied
  org value into a repo call.
- **`GET /api/core/process-docs/<step_id>` org-scoping via the doc's own `org_id`
  column** (AC17) — traced the only write path that sets `ProcessStepDocument.org_id`
  (`ProcessStepDocumentRepository.create`, called from `upload_sop_file` and
  `create_or_update_inline`): `org_id` is always the caller's own org from
  `_org_uuid()`, and creation is gated by `validate_process_and_step()` /
  `validate_upload_request()` / `validate_inline_request()`, which independently
  confirm `process_id` belongs to `org_id` and `step_id` belongs to that process
  *before* the row is written. No update path in the repo (`update_inline`,
  `soft_delete`) ever touches `org_id`/`process_id`/`step_id` after creation, and the
  app has no "transfer process to another org" feature. So a doc's `org_id` cannot
  diverge from its step's/process's real org — scoping by the doc's own column is
  safe as designed, not a shortcut that skipped re-validation.
- **IDOR / 404-not-403** — every process/step/doc lookup (`get_process_by_id`,
  `get_by_id`, `soft_delete`, reorder's `get_process_by_id`) returns `None`/0-rows
  identically for "doesn't exist" and "exists in another org," and every route maps
  that to a bare 404 with a generic message ("Process not found," "Document not found
  or access denied," "Step not found") — never 403. Consistent across all 20 ACs'
  worth of endpoints checked.
- **`_safe_flow_return_to` open-redirect guard (backend.py:148-209)** — actively tried
  to break it:
  - Encoded slashes/backslash (`%2F%2F`, `%5c`, `%255c` double-encoded backslash): the
    literal `\` produced by up to 2 rounds of `unquote()` is checked *after*
    decoding (`if "\\" in s: return default`), so single- and double-encoded
    backslash both get caught. A hypothetical triple-encoded backslash survives
    decoding as literal text `%5c` (not a real backslash), which is inert — no
    filesystem/URL-parser reinterprets an undecoded `%5c` as a separator.
  - Protocol-relative (`//evil.com`) and scheme (`javascript:`, `data:`, `vbscript:`,
    `foo://`) prefixes are explicitly blocked, but even without those checks the
    trailing `if not s.startswith("/"): return default` is a default-deny allowlist
    that would reject them anyway (defense in depth, not redundant dead code).
  - Tab/newline-obfuscated scheme (`java\tscript:` relying on browsers stripping
    ASCII tab/newline during URL parsing before scheme detection) — traced: the
    obfuscated string doesn't start with `/`, so it's caught by the same catch-all
    regardless of whether the naive prefix check would have missed it.
  - `..`-traversal out of `/core/flows` (`/core/flows/../../admin`) — `posixpath
    .normpath()` resolves it to `/admin`, which fails the
    `norm_path.startswith(_ALLOWED_RETURN_PREFIX)` check.
  - Unicode-normalization lookalikes (fullwidth slash `／` U+FF0F, fullwidth colon
    `：` U+FF1A as spoofed scheme/path separators) — not exploitable: browsers do not
    NFKC-normalize non-ASCII punctuation to ASCII `/`/`:` when parsing a URL/Location
    value; only IDN hostnames go through punycode normalization. These pass through
    as literal non-functional characters.
  - CRLF/header-injection via `return_to` — the guard itself doesn't strip `\r\n`,
    but (a) `return_to` is never passed to `redirect()`/set as a raw header value in
    this slice, it's rendered into an `href` in `batch-start.html`/
    `batch-start-fragment.html` template context (execution-slice consumer, out of
    process-design's registered routes but sharing this guard function), and (b)
    confirmed directly: `werkzeug.datastructures.Headers.__setitem__` raises
    `ValueError: Header values must not contain newline characters` for any value
    containing `\r`/`\n`, so even a hypothetical future `redirect(return_to)` call
    would 500 rather than inject.
  - No bypass found. This guard is well-constructed: the "must start with `/`"
    catch-all does most of the real work; the scheme/backslash/protocol-relative
    checks are defense-in-depth rather than the sole line of defense.
- **File upload path** (`process_docs_validation.py`, `process_docs_storage.py`) —
  MIME sniffed from magic bytes (`_detect_mime_from_path`, falls back to
  `Content-Type` header only when magic bytes don't match a known signature);
  filenames are always `f"{uuid4()}{ext}"` server-generated
  (`prepare_final_path`), never derived from the client's `original_filename`;
  every filesystem touch (`finalize_from_temp`, `read_file_path`, `delete_file`)
  re-validates the filename against `_SAFE_FILENAME_RE` = `^[a-f0-9\-]{36}\.
  (pdf|doc|docx|md|txt|bin)$` and `read_file_path` additionally confirms
  `candidate.resolve().relative_to(root.resolve())` stays under the storage root.
  No path-traversal or extension-spoofing vector found; the design correctly treats
  "filename is never user input" as the primary control and the regex/relative_to
  checks as defense in depth rather than the only control.
- **Role gating (process/step CRUD, reorder, process-docs upload/inline/list/
  download)** — confirmed only `@requires_auth`, no role gate, matching the spec's
  documented ASSUMPTION. Flagged as F3 above rather than accepted outright, because
  process-delete's blast radius (cascades to all steps + all ProcessVersion history)
  exceeds doc-delete's (one file) — the one endpoint that *is* gated.

## Not verified
- No live app server running (preflight: `app_server: down`) — did not exercise any
  route over HTTP; all findings are from static code reading plus two Python
  snippets executed directly (`Headers.__setitem__` CRLF check, dead-code grep). No
  request/response behavior (actual 404 status codes, actual `send_file` headers) was
  observed at runtime.
- Did not run the test suite; per the spec's own "Known gaps" section there is no
  process-docs test file and no reorder test at all, so none of this was cross-checked
  against existing red/green tests.
- CSRF/cookie flags not re-verified per-route — per CLAUDE.md these are enforced
  app-wide (Flask-WTF, `X-CSRFToken` header) rather than per-blueprint; did not
  re-audit the app-wide CSRF wiring itself, only confirmed nothing in this slice
  opts out of it.
- Noticed but out of security scope (functional, not a vuln, flagging for the
  caller anyway): global `app.config["MAX_CONTENT_LENGTH"]` is set from
  `evidence_max_file_size_mb` (default 10MB, `app/api/app_factory.py:51`), which is
  *smaller* than `process_docs_max_file_size_mb` (default 20MB). Uploads between
  10-20MB to `/api/core/process-docs/upload` will be rejected by Flask's global
  content-length cap before ever reaching the process-docs size/MIME check — the
  advertised 20MB limit is unreachable. This is accidentally protective (caps
  disk-exhaustion exposure at 10MB rather than 20MB) but is config drift worth a
  functional fix; not filed as a security finding.

## Findings not actioned (this run patches nothing — chain stage, read-only)
- F1, F2, F3 above are all logged here for the calling `review-feature` session to
  route: F1/F2 are scoped-to-feature fixes (small patches, could be done in-place with
  a test); F3 is a design/authorization-model question that should go to a human
  call, not be silently patched either direction.

VERDICT: findings-open
