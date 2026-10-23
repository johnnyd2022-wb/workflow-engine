# Customs: Records for Customs, redesigned

## What is wrong today

Observed in the before shots (`customs2/04/style1-records.png`), not assumed:

- The checks are a grid of cards and the records a second grid of cards. Neither looks like any other list in the platform (rows with a status tag), and cards have no reading order on a phone.
- Checks show their slugs' wording from the catalogue, and "0 records" for checks that are proven automatically.
- One "Add a record" form of 12 fields serves every check, so a retention attestation asks for a period, litres of alcohol and Production records.
- It sits folded under the entry, so the entry page carries a second job.

## Context

The founder doesn't like the current Records for Customs area at the bottom of the Customs entry page (!549):
- The **check cards** and **record cards** don't match the rest of the platform.
- The **"Add a record" evidence form** below them (12 fields, the same for every check) isn't slick.

They asked for options through `/page-design`, using how NP3 now handles evidence as the reference (!550: Summary and Checks pages, then a page per check with what's asked, the evidence we have, record evidence and history). They also asked whether Records should stay on the entry page or move to a dedicated page, as NP3's evidence has.

**What Records is for, in one sentence:** *for each thing Customs can ask to see, do we have current proof, and how do I add it?*

## Recommendation on placement: a dedicated Records view

Customs gets a fourth view: **Excise entry · Stock · Records · Settings**, at `/compliant/nz-alcohol/customs/records`.

On the entry page, the folded Records card becomes a single line: "Records for Customs · 3 of 5 current · Open records →".

Why:
- the entry page stays about this month's entry, which is the founder's room-to-breathe ask;
- it matches NP3, where the checks moved off the summary;
- records aren't monthly work; they're occasional, like settings and stock.

All three styles below live in that view.

## What the code allows (exploration)

- **Five Customs checks** (`catalogue.py` customs-alcohol):
  - product-mapping;
  - period-lodgement (now filed automatically when an entry is recorded as lodged, !549);
  - reconciliation;
  - movement-evidence;
  - record-retention.
- **State per check** comes from `ComplianceService._control_state`, via `/api/compliant/overview` (`frameworks[].controls[]` with state and reason).
- **Records** come from `GET /api/compliant/records?framework=customs-alcohol` and `POST /api/compliant/records`.
- **Each check needs only some fields** (`CONTROL_REQUIREMENTS` in `catalogue.py`, exposed as `control.capture`):
  - period-lodgement: type lodgement, a period, evidence;
  - reconciliation: reading or attestation, a period, evidence, declared LAL;
  - movement-evidence: evidence and Production records;
  - record-retention: evidence.

  So the form can show only what that check needs, with the rest under "More details".
- The Production record picker (`/api/compliant/core-sources`) and the record form logic already exist in `compliant.js`.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| Vanta, controls page (comparable) | Controls list with OK or Needs evidence, and a summary of what lacks evidence. A control's page lists its evidence; expired files move to a History section with an audit trail | Style 1: rows with status, then a page per check with the evidence first and history below |
| Drata, evidence (comparable) | One evidence library mapped to many controls, added from Evidence or from a control's Evidence tab. The classic interface added it from a control drawer through a short modal | Style 2's sheet; one "Record evidence" in Style 3 that asks which check |
| Secureframe, controls (comparable) | Healthy, At Risk or Unhealthy per control. Evidence is uploaded in a modal, and is valid from when the activity happened, not when it was uploaded | Every form asks when it happened (the period), not only the upload date |
| Hyperproof, activity feed (comparable) | A timestamped activity feed per object, which auditors read | Style 3's month-by-month feed |
| GOV.UK task list (pattern) | Whole-row links, short status tags, completed items in plain text | The rows in Styles 1 and 2 |
| Polaris Sheet, Material side sheet, CMS Drawer (pattern) | A sheet beside the page for detail tied to the current task, closed with Done or Escape. Atlassian and Polaris React are both moving away from drawers | Style 2 is a fair option, but its trade-off is stated: the sheet is the least established pattern |

**Looked for but not found:** whether any of these products adds evidence in a page, a drawer or a modal in their current interface. The docs describe the data, not the container.

## Three directions (all on the Records view)

| | Style 1: Checks and a page each | Style 2: Checklist with a side sheet | Style 3: Evidence timeline |
|---|---|---|---|
| Idea | The five checks as rows (status, latest proof, next due); each opens its own page: what Customs asks, the evidence we have, record evidence, history, as on NP3 | The same five rows; clicking one opens a sheet from the right with the check's evidence, history and a tailored form, without leaving the list | A month-by-month feed of every record, with the five checks as filter chips above it and one "Record evidence" button that asks which check first |
| Taken from | Vanta controls, NP3 in !550 | GOV.UK task list, Atlassian Drawer / Polaris Sheet | Drata evidence library, an audit-log feed |
| Best at | The same feel as NP3; room per check | Quick additions without losing your place | "What did we show Customs, and when?" |
| Gives up | A page change per check | Less room for long history in a sheet | Status per check is less prominent |

**Shared by all three:**
- plain names for the checks ("Each period's entry lodged", not `period-lodgement`);
- status in words;
- the auto-filed lodgement records;
- the **tailored form**: only the fields the check needs, the right record types, a title filled in for you, the Production picker only where the check uses it, and everything else under "More details";
- house list rows rather than cards.

## Not in this change

- **APIs:** the records and overview APIs are unchanged (the new pages only read them).
- **NP3:** untouched.
- **Follow-ups:** a duty-credit line on the entry; delete the record cards and form from `compliant.js`.

## Files

- **Routes:** `app/features/compliant/routes/page_routes.py` gains `/customs/records`, plus `/customs/records/<control_id>` for Style 1.
- **Registry:** `app/ui/page_registry.py`, `staff_site_endpoint_registry.py`. The old `/compliant/nz-alcohol/evidence` URL redirects to the Records view.
- **Templates:**
  - new `customs_records.html` and `customs_record_check.html`;
  - `_customs_header.html` gains the Records tab;
  - `customs.html` replaces the Records card with the one-line link.
- **Scripts:**
  - new `static/customs-records.js` (list, sheet, timeline, and the tailored form, reusing `CustomsUI`);
  - `excise.js` fills the one-line link's hint ("3 of 5 checks have current proof").
  - `compliant.js` is untouched: the Customs page no longer loads it, so its record cards and form are unused by Customs. Removing them is a follow-up, kept out so this diff stays reviewable.
- **Styles:** `static/customs.css` (a records section and the CONCEPT ONLY blocks).
- **Tests:**
  - new `tests/e2e/compliant-platform/test_customs_records.py`: each check once with plain names; a tailored form shows only its fields; adding a record makes it the latest proof; the lodgement record shows; CONCEPT ONLY widths;
  - update `test_customs_page.py` (Records now a link), `test_dashboard_page.py` and `test_records_flow.py` where they open the old form.
- **Seed:** `scripts/ui_shots.py` adds a reconciliation reading and a movement record linked to Production records, to the excise seed.
- **Docs:** `docs/customs-records-redesign-plan.md`, `.agents/reports/page-design/customs-records.md`.

## Execution

1. Worktree `feat/customs-records-design` off `origin/main`; `uv sync --extra dev`.
2. Shoot `00-before`: Records open, the form open, phone, dark.
3. Build the Records view and the three styles. Run the screenshot loop until a pass is clean:
   - laptop, phone, wall and dark;
   - states: each check, the form open and saved, arriving by the tab.
4. Tests and suites (with `TZ=UTC` too), then a draft MR with the three side by side.

## Verification

- `env -u ENVIRONMENT uv run pytest tests/e2e/compliant-platform/ tests/test_compliant_routes.py tests/test_compliant_frontend_assets.py tests/test_navigation.py tests/test_page_registry.py tests/test_staff_site_roles.py -q`
- `ruff`, `node --check` and `semgrep` on the new scripts.
- Purge the seed.

## Outcome

**Style 1, Checks and a page each, was chosen** (founder, 2026-10-23). Six screenshot passes; the final one, on Style 1 alone, was clean.

- Style 2 (side sheet) lost: it repeats the check page in less room, and a sheet is the least established of the three patterns.
- Style 3 (timeline) lost: it answers "what did we show, and when?" but makes each check's status less visible, and that status is the page's job.

The switch, the sheet, the chips, the timeline feed and their CONCEPT ONLY test are deleted.
