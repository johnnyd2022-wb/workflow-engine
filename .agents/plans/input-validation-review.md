# Plan: input validation review, every UI element and its endpoint

Requested by the founder on 2026-11-27. The Sauron orchestrator owns it. One worker runs at a time. Branch
`security/input-validation-20261127` ends in one MR.

## Goal

Every input the app accepts must be checked on the **server** for its type, whether it is required,
its length or range, and allowed values, and must be rejected cleanly. That covers form fields, JSON
bodies, query strings, path parameters and file uploads. A rejection is a 400 or 422 with a
field-level message. It is never a 500, never a silent coercion, never a stored bad row and never
a reflected value. Every UI control needs matching client-side constraints (`required`, `type`,
`min`/`max`/`step`, `maxlength`, `pattern`, `accept`) so users get help before submitting. Client-side
checks help usability but are not security. The server check is what counts.

## Baseline (2026-11-27, origin/main `9cd5c32c`)

- About 136 raw `request.get_json()` / `request.json` reads and about 140 `request.form` / `request.args`
  reads under `app/`. Only one route uses `app/utils/api_helpers.validate_api_input`.
- `validate_api_input` only checks presence and blank strings. It has no types, and it swallows
  exceptions. It is not enough as the standard.
- semgrep repo rules (`.semgrep/rules/`) have no input-validation rule.

## Standard (decided in VAL-00, then applied everywhere)

1. A small shared validation layer in `app/utils/` with typed field specs (str with min/max length,
   int/Decimal with range, enum, UUID, date/datetime, bool, list of T) and required/optional. It returns
   `{field: message}` errors as 400/422 JSON for APIs and re-renders forms with errors for HTML. Use
   an existing dependency if the repo already has one (check `pyproject.toml`) before adding anything.
2. Unknown JSON fields are rejected or ignored. Pick one and state it. Bodies that are not JSON or not
   an object are rejected. UUID path parameters go through converters or validation, so a bad ID gives
   400/404 and never 500.
3. Quantities, money and ABV are Decimal with an explicit range and precision. NaN and Infinity are
   never accepted, and negative values only where the domain allows them.
4. Strings are trimmed where appropriate and length-capped to the DB column. Control characters are
   rejected in names and identifiers.
5. Files are checked for size, extension and sniffed content type before they are stored.

## Method per area (one wb task each)

For each blueprint, page by page:

1. **Inventory.** List every route (method, path, auth) and every input it reads. List every form or
   control on the pages that call it. Record this in the area section of the report.
2. **Unit and integration tests first** (`tests/validation/test_<area>_validation.py`). For each
   input, test missing, wrong type, empty, over-length, out-of-range, NaN/Inf, bad UUID, bad enum and
   extra fields. Expect a 4xx with a field error, no 500, and no row written. Run them, watch the
   gaps fail, then fix the routes using the shared layer. Never weaken an existing test.
3. **semgrep.** Run the repo rules and the new `input-validation` rule over the area, then triage
   every hit.
4. **Playwright** (`tests/e2e/validation/test_<area>_forms.py`). Each form has client-side
   constraints. Submitting invalid data shows a clear error. Bypassing client checks (direct
   `page.request` POST with bad data) is rejected by the server.
5. Iterate until the area is green. Then commit (one or more commits per area), update the wb task
   to `done` with a note, and move on.

## Areas, in order (wb ids)

| wb id | Area |
| --- | --- |
| VAL-00 | Baseline: route/input inventory script, shared validation layer, semgrep `input-validation` rule + fixtures, Playwright validation helpers |
| VAL-AUTH | auth, admin_auth, google_auth, invite, legal, getting_started, go_live |
| VAL-ORG | org, people_pages, sites, stock_locations, admin |
| VAL-PROC | core_bp processes and process design, process_templates (api and pages) |
| VAL-EXEC | core_bp executions, batches, record_step, execution records and evidence uploads |
| VAL-INV | inventory, stocktake, wastage, dilution_calculator, reconciliation |
| VAL-TRACE | trace/sourcemap, activity_log, dashboard, compliance_checks |
| VAL-CRM | crm, crm_api, crm_oauth, crm_pages (rebase after !771 if it has merged) |
| VAL-COMP1 | compliant, compliant_api, compliant_pages, compliant_tools, compliant_verification |
| VAL-COMP2 | compliant_licensing, compliant_premises, compliant_food_registrations, compliant_cca_movements, compliant_cca_transfers |
| VAL-CASES | operational_cases (api and pages) |
| VAL-CM | contract_manufacturing orders and portal |
| VAL-PLAN | planning, site_transfers, tastings, demo_data |
| VAL-MCP | mcp_oauth endpoints and public MCP tool arguments |
| VAL-FINAL | full suite, full semgrep, full Playwright validation sweep, report, MR |

## Deliverables

- Report at `.agents/reports/security-audit/2026-11-27-input-validation.md`, ordered by severity.
  Severity runs from a 500 or crash, through stored invalid data and missing server checks, down to
  missing client hints. For each area it includes the inventory table, findings with file:line,
  what was fixed, and the test that pins each fix.
- One MR to `main`, with the wb board updated as each area finishes.

## Rules

Follow `.agents/autonomy.md`. Don't merge, push to main, force-push, or touch production. Use the shared
test DB with `ENVIRONMENT` unset. If a migration is needed, use a private DB via `PYTEST_XDIST_WORKER`.
Never weaken a test or gate. If a fix changes user-visible behaviour (for example, a field that
used to accept something now rejects it) and existing data might violate it, record that in the
report rather than migrating data.
