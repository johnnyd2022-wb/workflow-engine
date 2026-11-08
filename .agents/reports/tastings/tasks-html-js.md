# Typed Tastings Tasks — HTML and JavaScript review

Reviewed the current `git diff HEAD` for Tasks and embedded Tastings templates, controllers and styles under `.claude/skills/html-review/SKILL.md` and `.claude/skills/js-review/SKILL.md`. Read-only app/test/script stage; no database operations. Root owns real-browser runs; this report does not claim independent browser execution.

## Initial findings (both closed on follow-up)

1. **P2 — Stock pagination failure is written behind the modal.** `app/features/crm/frontend/js/tastings.js:275` catches `/pool?offset=…` errors with `notice(err.message)`. The notice target is the `[data-tasting-status]` paragraph outside `#tasting-stock`, while the stock panel is now a native modal dialog. The background is inert/covered, so a failed More batches operation has no usable in-dialog error or retry feedback. Route the error to `[data-tasting-pool-error]` and expose an in-dialog retry; keep the current offset unchanged on failure. Verify a first page with `has_more`, fail page two, assert a visible alert in the open dialog, then retry successfully.

2. **P2 — Switching back cannot display a customer selected outside the ordinary drawer's first page.** `tasks-calendar.js:343` restores only scalar IDs from `tasting-draft-return`. Ordinary Tasks loads only the first200 customers in `loadCustomers()`, whereas the tasting editor can search further customer pages. Select such a customer in the tasting form and switch Type to General/Call/Email: `drawerForm.contact_id` is assigned an ID absent from `customers`, so `#task-customer` has no matching option and shows no selected customer. The existing `ensureCustomerOptionForTask()` solves this for saved task editing but is not applied to draft returns. Preserve the selected customer's label/contact metadata in the return payload, add a matching option before showing the ordinary drawer, and apply the same treatment to any selected rep absent from `operators` (including transient operator-load failures). Verify that switching back and again retains both the ID and the visibly selected customer; saving an ordinary task must preserve that customer without requiring reselection.

## Checks without findings

- Tasks extends the shared SPA shell; specialized markup is now an included partial with no duplicate shell or calendar.
- User-provided text is rendered with Alpine `x-text` or DOM `textContent`; the changed integration adds no unsafe HTML interpolation, sensitive storage or org ID authority in client attributes.
- Mutating non-Core requests include JSON/CSRF headers and same-origin credentials; paths/queries use encoded values. Unified creation sends only supported nested tasting fields.
- New root initialization is guarded, global HTMX listeners bind once, beforeSwap aborts the old tasting controller, and detached roots do not render fetched details. Existing head scripts define Tasks before Alpine initialization.
- Opening ordinary Tasks initializes the embedded controller without fetching stock choices, pool or a separate tasting-event list. Specialized requests are triggered by a task/detail/stock interaction.
- Ordinary typed CRUD retains existing paths and type defaults. Tasting cards/done/delete actions open specialized details and dragging is suppressed; server lifecycle authority remains a separate backend/security check.
- Type/view URL replacement preserves other query state. Specialized forms have visible/associated labels, native modal semantics, heading references and correctly scoped HTMX boost disabling. Styles use existing tokens and remain component scoped.
- Draft switching captures specialized fields and allocation metadata and maps common fields without a preliminary save. Explicit length validation retains long source text instead of truncating it.

## Non-blocking follow-up

`openDetail()` still waits silently before opening a dialog and has no per-detail request token. This predates the refinement; a detail skeleton/token would improve slow-network feedback and prevent a late earlier request replacing a newer selection. It is not counted as a newly introduced finding in this integration review.

Initial verdict: findings-open.

## Follow-up review

Both findings are closed in the current source:

- `loadPool(more)` now handles initial load and pagination through the same guarded path. It writes failure text to the pool alert inside the open dialog, exposes its retry button, leaves the committed offset unchanged on failure, and records whether retry should request the next page. More batches is disabled while the request is in flight. The new browser case asserts a visible dialog alert, both preserved and appended batches, and exact request offsets `[0, 50, 50]` across failure and retry.
- The draft-return event now includes the selected customer label/email/phone and rep display name. `restoreTastingDraft()` inserts missing customer/rep options before showing the drawer and strips those display-only fields before merging writable form values. The new browser case deliberately empties ordinary customer/user options, selects people supplied by tasting choices, checks visible selected labels and IDs after switching, switches back and again, then verifies the ordinary creation request retains both references.

Independently re-read the affected controller paths and new regression cases and ran `node --check` successfully on both changed JavaScript files. Root reports the people-focused browser case passed and the stock retry case passed within its broader run; final full browser/CI results remain root's separate gate. No app/test/script edits or database operations performed by this reviewer. The earlier non-blocking slow-detail note is unchanged and is not an open regression finding.

VERDICT: clean
