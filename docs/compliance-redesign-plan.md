# Compliance overview redesign

Scope: `/compliant/nz-alcohol`, the page reached by the Compliance navigation item.
Purpose: tell an operator what evidence is current, what needs review, and where to act next.
Branch: `feat/compliance-design`, initially based on fresh main `311458a4`, then rebased
onto `dbf2f6f3` after Home/sidebar !512 merged, and then `ba166c7b` after Production !515. All three concepts retain the shared
expanded sidebar, labelled rail and phone navigation from that merge.
The industry index and the NP, Customs, licensing and registration workspaces remain separate.
The founder selected Style 1, the Board. The final MR ships only that layout.

## What is wrong today

Observed in the before screenshots (1440, 390 and dark):

- The headline says **0 need attention** while the two cards show 47 checks to review.
  Frameworks in `setup` are omitted from that headline. Show the API's check counts instead.
- Customs says **NP3 checks**, and the NP2 programme uses an NP3 label/link. Match the
  actual programme; describe Customs and other frameworks as controls.
- **Compliance score** contradicts the disclaimer underneath. Call it evidence coverage;
  keep the server's existing score and calculations unchanged.
- The API's six priority actions are not displayed. A new operator sees numbers without
  the next step. Surface that queue and one primary action, retaining every returned item.
- Nested cards give two frameworks the same visual importance as the entire overview.
  The management card pushes the answer down the page on a phone.
- Use the shared page-init lifecycle for the dedicated overview script. The shell already
  carries scripts/styles on boosted loads; the new overview also keeps its assets in content.

Before screenshots: `~/.cache/workflow-engine-ui-shots/compliance/00-before/`.

## What other products do

Primary sources read 11 October 2026. Structure is our interpretation of these patterns,
not a claim that another product prescribes this exact Compliance page.

| Source | Observed pattern | Change here |
|---|---|---|
| [MaintainX overview](https://help.getmaintainx.com/getting-started-new-users/mobile-app-overview) | Separates priority/overdue status from the to-do list and secondary modules | Readiness and a short next-action queue; setup follows the work |
| [FoodDocs features](https://www.fooddocs.com/food-safety-solutions) | At-a-glance food-safety status across locations, with monitoring tasks and document storage | Give the board an immediate readiness answer and clear status words; do not invent a legal compliance rating |
| [SafetyCulture actions](https://help.safetyculture.com/en-US/005384/) | Corrective actions sit beside the investigation and link to existing work | Put the returned action title, reason and destination together, rather than an isolated number |
| [Linear display options](https://linear.app/docs/display-options) | Lists and boards share data; grouping and ordering determine what leads | Register concept uses compact summaries with full details one click away; all concepts share one script |
| [Notion layouts](https://www.notion.com/help/layouts) | Important properties stay in the heading, others in a details panel | Action desk keeps important evidence beside the work queue; the register discloses evidence metrics without losing them |
| [Carbon dashboards](https://www.carbondesignsystem.com/building-blocks/data-visualization/dashboards) | Most important information first; fewer metrics and deliberate white space | One primary next step, quiet secondary actions, three essential evidence counts without repeating the current count |
| [Production !515](https://gitlab.com/whistlebird/workflow-engine/-/merge_requests/515) | Selected board, title above underlined tabs, solid primary at right, full-width work rows | Style 1 follows this hierarchy and spacing; all three use the settled shared section head |

Research limits: the SafetyCulture article was searchable but a subsequent fetch failed.
We use its published action description, not an unseen dashboard. None of these sources
establishes how NZ regulatory compliance should be scored. Linear and Notion are craft
references, not food-safety compliance products. No regulatory interpretation is introduced.

## Selected direction: match the settled Production approach (!515)

Read !515's final MR and its four-round plan. The board was chosen first; then the
header actions; then the title-first shared section head, underlined green tabs and
one solid action at the right. The shared section head already shipped on main.
Rebasing the first Compliance draft exposed a duplicate title: our concept header
still said Compliance beneath the new section title. Remove that header and subtitle,
use the shared h1, align every concept to the section's 1280px width, and put the
first returned actionable suggestion into the section action slot. Its explanation
and remaining suggestions stay in Next action. Premises stays as an outlined
secondary action. Error/loading states hide the dynamic primary rather than imply
that stale evidence has loaded. Managers with no applicable frameworks get Set up
Compliance; other readers retain explicit admin guidance.

Research refreshed 11 October 2026: FoodDocs monitoring/status documentation,
MaintainX reporting guidance and SafetyCulture's published actions description;
Linear display options and Notion layouts; Carbon tabs guidance. Sources describe
status paired with actionable work, alternate layouts over the same data, disclosure
of secondary properties, and tabs immediately above content. These inform the
structure; !515's reviewed choices determine appearance. The SafetyCulture fetch
still failed, so no unseen interface detail is claimed. No task dates or custom
regulatory status can be invented from this overview response.

| | Style 1: Board (selected) | Style 2: Action desk | Style 3: Register |
|---|---|---|---|
| Idea | Readiness beside next-action context; full-width framework rows and links | Compact readiness band, action queue at left, evidence cards at right | Compact readiness band, short action context and framework disclosures |
| Taken from | Settled Production !515 board and direct row actions | MaintainX action work, FoodDocs monitoring and Notion important properties | Linear lists, Notion disclosure |
| Best at | Familiarity across Home, Production and Compliance | Completing setup/review while consulting framework evidence | Comparing obligation summaries and inspecting one framework |
| Gives up | Board needs a wide screen and stacks when narrower | Expanded queue takes more vertical room; cards stack on phones | One extra interaction for each detailed evidence breakdown |

Style 1 was selected because its paired readiness and next-action cards, followed by
full-width framework rows, match the settled Production hierarchy while keeping the
operator's evidence and next step visible together. Style 2 gave the action queue more
vertical weight than this overview needs. Style 3 added disclosure interactions to a
small framework set. The chooser, preview query, remembered preference and both losing
layouts were removed before shipping.

The selected Board retains every applicable framework, all returned priority actions,
evidence coverage, current/review/overdue counts and workspace management links. It uses
the existing template, script, API and shared UI tokens.

### Shared design

Readiness: show current evidence once as a count out of the total, alongside to-review and
(overlapping) overdue counts. The coverage ratio has no new numeric score. A short note
explains that evidence coverage is not a legal compliance score. A textual status is
always present; colour alone carries no meaning. Live-data gaps and source counts stay
accessible in a Data coverage disclosure, preserving the old overview signal.

Next actions: put the primary button in the shared tab row, keeping its context in the card. Use `priority_actions` exactly as returned; do not generate new obligations
or reorder the server's queue. The first action is the primary button; later ones expand
under “More next steps”. Food-programme actions open its register, Customs actions open
the existing exact control, and product mapping opens Configuration for managers.
Generated links retain the previous overview’s full-navigation behavior. The shared shell
already supports boosted assets, so this is continuity rather than a new lifecycle fix.
Unsupported-framework actions direct managers to Configuration; other users get a clear
request to ask an admin. No pretend control-specific destination.

Frameworks: programme-specific links and labels for NP1/2/3, generic control counts for
other frameworks, server evidence score labelled “Evidence coverage”. Readiness metrics
link to the food-safety register's existing filters. The register layout groups each
framework into a keyboard-operable native disclosure; no draggable board semantics.

Loading, no configuration, a quiet queue, request failure/retry, dark, narrow screens and
returning by boosted navigation all have explicit states. No endless loading copy or
success-shaped zeros on an API failure. Disclosure changes do not fetch.

## Not in this change

No API, calculations, exports, permissions, compliance rules, or production configuration
changes. No new overall score, no artificial dates, no backup/Slack changes in this MR.
No shell navigation relocation from !512: Claude owns Home/Production. No redesign of
individual NP, Customs, registration or licensing pages. No search added for the small
framework catalogue; the food-safety register retains its existing search and filters.
The roadmap's general UI unification item is already completed; this concept review does
not finish a new source-to-sale capability, so no additional roadmap box is ticked.

## Checks

Regression tests first against unchanged main: setup counts cannot disappear, Customs
cannot be called NP3, and NP2 must link as NP2. Browser checks cover the selected Board at
390, 1024, 1440 and 1920, dark theme, expansion, primary destination,
quiet/setup/error/retry and boosted return. The Board deliberately changes readiness from a full-width card to a 5/7 pair on a wide
content container, while obligations and management remain full-width. Tests assert
the new alignment, single shared title, action placement and unchanged destinations. No weakening of tests.

The final winner pass covers desktop, laptop, phone, wall, dark, expanded, quiet, setup,
loading, failure, 401/403, boosted return and collapsed-sidebar states. Inspect every image,
record defects each pass and repeat until no defects remain. Use an isolated screenshot
state folder and purge only this run's throwaway org.
Run relevant frontend/unit and shared layout/render/navigation suites, JS syntax, ruff,
semgrep and independent HTML/JS/test review. Upload comparison images into the draft MR.
