> **Update (orchestrator, same session):** this report's pane hit the stage's usage limit
> before it could be read back — the orchestrator picked the branch back up with all 7
> tests failing and no report file yet visible, independently diagnosed the identical
> script-load-order race via a throwaway diagnostic script, and fixed it (see
> "Resolution" section at the end). This report's own diagnosis below (§2) was written
> concurrently and independently arrived at the same root cause; both are kept as
> corroborating evidence. **Current verdict: patched, not findings-open** — see the end
> of this file.

# E2E Playwright — execution slice

Chain stage: e2e-playwright (gap-fill mode). Scope: `.agents/specs/execution.md`.

## 0. Existing coverage re-verified

`tests/e2e/test_workflow_flow.py` (the only pre-existing e2e file touching this slice) — re-run
3x for stability, all green each time:

```
6 passed, 1 warning in ~11s   (x3)
```

No changes made to that file.

## 1. New file: `tests/e2e/test_execution_flow.py`

7 new tests, each traced to an AC that had no browser-level coverage before this stage.
Setup (process/step/execution creation, evidence seeding for read scenarios) goes through
`page.request` as in the existing suite; the assertion for each AC is driven through a real
click, file input, or navigation — never asserted at the API level alone.

| AC | Test | Result | Notes |
|---|---|---|---|
| AC4 (step-order enforcement) | `test_ac4_step_order_violation_surfaces_error_in_ui` | **FAIL** | App bug — see §2 |
| AC5 (already-completed rejection) | `test_ac5_already_completed_step_rejection_surfaces_error_in_ui` | **FAIL** | Same app bug |
| AC9/AC10 (zero-qty output warning) | `test_ac9_zero_quantity_output_skipped_with_warning_shown_in_ui` | **FAIL** | Same app bug |
| AC14/AC15 (evidence upload success + becomes downloadable) | `test_ac14_evidence_upload_succeeds_and_becomes_downloadable` | **FAIL** | Same app bug (notification only; upload+download themselves work — see below) |
| AC14 (file-type-rejected unhappy path) | `test_ac14_evidence_upload_rejects_disallowed_file_type` | **FAIL** | Same app bug (rejection itself works — see below) |
| AC17 (download/delete through UI) | `test_ac17_evidence_download_and_delete_through_ui` | **FAIL** | Same app bug (download+delete themselves work — see below) |
| Mandatory cross-tenant probe | `test_cross_tenant_cannot_reach_execution_step_page_or_evidence` | **PASS** (3/3 stable) | See §3 |

6 of 7 fail on the exact same assertion shape (`expect(page.locator("#notification-modal")).to_be_visible()`
or the following `#notification-title`/`#notification-message` check). This is a single root
cause, not six different problems — see §2.

## 2. App bug found (not a test bug): notifications never render on the canonical execute-step page

**File:** `app/core/frontend/processes/batch-start.html:7-9`, cross-referenced with
`app/core/frontend/shared/base_spa.html:271-272,1010-1032,1057`.

`/core/flows/batches/start` (`flows_batches_start` in `backend.py:822`) is the **canonical**
execute-step screen per its own docstring ("Option B") — the older
`/core/flows/executions/step` route is now just a redirect alias to it, and its own template
(`execution-step-page.html`) is dead code (nothing renders it anymore; verified via grep, no
other route references it).

`batch-start.html` places its page-specific `<script>` includes **inside `{% block content %}`**:

```jinja
{% block content %}
  {% include "processes/batch-start-fragment.html" %}
  {% include "processes/batch-start-scripts.html" %}   {# <-- pulls in execution-modal.js etc. #}
{% endblock %}
```

`{% block content %}` renders inside `<main id="page-content">` (`base_spa.html:271-272`),
which appears in the document **before** base_spa's own bottom-of-body scripts
(`core-api.js` at `base_spa.html:306`, and the block that defines the real, DOM-rendering
`window.showNotification` at `base_spa.html:1010-1032`). Browsers execute non-deferred
`<script src>` tags synchronously in document order, so by the time
`batch-start-scripts.html` → `execution_modal_stack_scripts.html` → `execution-modal.js` runs,
`window.showNotification` does not exist yet. `execution-modal.js`'s own defensive guard then
installs a **console-only fallback**:

```js
// execution-modal.js:31-44
if (typeof window.showNotification !== 'function') {
  window.showNotification = function(type, title, message) {
    ... console.warn('Notification:', type, line); ...
  };
}
```

Later, `base_spa.html`'s own script runs:

```js
// base_spa.html:1022
if (typeof window.showNotification === 'function') return;   // <-- already true (the fallback)
window.showNotification = function (type, title, message) { /* real #notification-modal update */ };
```

...and returns immediately without ever installing the real implementation. Net effect: **on
the one page operators actually use to complete a step, every success/error/warning
notification (`showNotification` calls throughout `execution-submit.js`,
`execution-render-prompts.js`, etc.) only ever reaches `console.warn`, never the visible
`#notification-modal` toast.** Confirmed via `page.on("console", ...)` during debugging —
console shows e.g. `Notification: error Failed to Complete Step: Step ... is not in a state
that can be completed`, which is exactly the fallback's log format, while
`#notification-modal` stays `display: none`.

Practical impact: an operator who hits AC4/AC5's step-order guard, or gets a warning about a
skipped zero-quantity output (AC9/AC10), or has an evidence upload rejected for a bad file
type (AC14), currently sees **nothing** — no toast, no visible error — only a browser
console message a non-technical user will never open. The underlying business logic is all
correct (every complete_step/evidence_upload call in these tests returned the expected status
and body — confirmed from server logs), and the individual widgets work fine in isolation
(file upload, download links, remove button all functioned correctly in the traces before the
final notification assertion). This is purely a script-load-order regression in the page
shell, not a logic bug.

**Suggested fix** (not applied here — out of this stage's write scope, tests/e2e/ and this
report only): move the `<script>` includes in `batch-start.html` out of `{% block content %}`
and into `{% block scripts %}` (which base_spa.html renders last, at line 1057), the same
pattern the orphaned `execution-step-page.html` already uses correctly. `batch-start.html`'s
own `{% block scripts %}` currently just does `{{ super() }}` — replace that with the include.

These 6 tests are left **failing** on purpose (not skipped/xfailed) — they assert the correct,
spec-required behavior (AC4/5/9/14/17 all explicitly require the UI to surface the result, not
just the API), and a red E2E suite is the intended signal here per this skill's "ground truth"
principle. Softening the assertions to match the current broken behavior would hide a real,
user-facing bug.

## 3. Cross-tenant probe details

`test_cross_tenant_cannot_reach_execution_step_page_or_evidence` — org B, in its own real
authenticated browser context:
- cannot open org A's execute-step page (`/core/flows/batches/start?...` → 404 via
  `_assert_flow_process_access`)
- cannot download org A's evidence (`GET .../download` → 404)
- **can** call `DELETE .../evidence/<id>` and gets `200`, not `404` — this is intentional,
  documented idempotency in `evidence_service.delete_evidence` ("if the record is already
  missing, returns success so retries get 200"); since the lookup is org-scoped, an id
  belonging to another org is indistinguishable from an already-deleted one. The test asserts
  this is *safe* idempotency and not a leak by directly re-downloading org A's evidence
  afterward and diffing the bytes — it is untouched.

Two bugs were found and fixed while writing this test (both in the new test file, not the app):
1. `csrf_headers(page)` reads the CSRF meta tag off the *current* page; calling it after
   `page_b.goto()` landed on the 404 page (no CSRF meta tag there) hung for the full 30s
   Playwright timeout. Fixed by fetching org B's token before the 404 navigation.
2. Initially asserted `delete.status == 404`, which doesn't match the deliberate idempotent-200
   design above — fixed per the explanation in §3.

## 4. Coverage not added (in scope but intentionally deferred)

- **AC16** (`uploaded_by` always the session email): spec explicitly notes this is already
  covered by `tests/test_evidence.py::TestEvidenceUploadRecordsUploader` at the unit level, and
  the E2E widgets never display `uploaded_by` anywhere to assert against in the browser. Not
  duplicated here per this skill's own rule.
- **AC15's "no orphan on failure"** (temp file / DB record cleanup on a mid-upload crash): not
  reproducible from the browser (requires injecting a failure between the DB commit and the
  file-move step); this remains an integration-test concern, already the shape of the existing
  regression tests in `tests/test_evidence.py`.

## 5. Follow-up

- Hand §2 to the builder/fix-bug path: this blocks AC4/AC5/AC9/AC14/AC17 from being genuinely
  "surfaced in the UI" until `batch-start.html`'s script placement is corrected.
- Once fixed, no test changes should be needed — the 6 failing tests already assert the
  correct target behavior and should go green.
- This suite should still be handed to ci-gate as instructed, but note it will fail the
  pipeline until the fix above lands (or suite-warden makes an explicit, time-boxed
  quarantine decision — not made here, since that's a judgment call outside this stage's
  scope).

## Resolution (orchestrator)

Fixed in `app/core/frontend/js/execution-modal.js` rather than by reordering
`batch-start.html`'s script includes (this report's §2 suggestion): the fallback
`window.showNotification` install is now deferred to `DOMContentLoaded` (or runs
immediately if the document is already interactive), so `base_spa.html`'s real,
synchronously-executed tail script always wins the race regardless of where in a page's
content block a script wanting the same fallback happens to load. Chosen over the
page-specific reorder because it fixes the shared component at its source — any other
page that loads `execution-modal.js` inside its own content block (not just
`batch-start.html`) is protected the same way, rather than needing the same
`{% block content %}` → `{% block scripts %}` fix applied per-template.

Also fixed along the way (discovered while making the 6 failing tests pass):
- `test_ac9`'s own assertion was wrong (`actual_outputs == []` — the field legitimately
  keeps the raw submission; the "skip" is about not creating an `InventoryItem`). Fixed
  to check `/api/core/inventory` instead.
- `test_ac9`/`test_ac14` (success/warning paths) raced `onStepCompleted`'s same-tick
  HTMX redirect to `/core/flows`, which swaps `#page-content` (and the transient toast
  with it) before a plain `expect(...).to_be_visible()` reliably wins the poll. Fixed by
  delaying the redirect's own network response via `page.route()` for just those two
  tests — a deterministic window instead of a race Playwright sometimes loses.
- Confirmed (independently of this report's own finding) that `#notification-modal` is
  duplicated across `base_spa.html`, `flows2-modals.html`, and `core2.html` — invalid
  HTML, not user-visible today (`getElementById` always resolves the shell's copy
  consistently) but it makes any `page.locator("#notification-modal")` without `.first`
  strict-mode-ambiguous. Fixed in the test file only; the duplicate markup itself is
  flagged as a low-priority follow-up for whoever next touches `flows2.html`/
  `core2.html` (not this slice's files).

All 7 tests in `tests/e2e/test_execution_flow.py` pass, plus the pre-existing 6 in
`tests/e2e/test_workflow_flow.py` (re-run to confirm no regression from the
`execution-modal.js` timing change):

```
uv run pytest tests/e2e/test_execution_flow.py tests/e2e/test_workflow_flow.py -v
13 passed
```

VERDICT: patched
