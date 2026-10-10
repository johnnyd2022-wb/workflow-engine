# Compliance overview redesign

Scope: `/compliant/nz-alcohol`, the page reached by the Compliance navigation item.
Purpose: tell an operator what evidence is current, what needs review, and where to act next.
Branch: `feat/compliance-design`, initially based on fresh main `311458a4`, then rebased
onto `dbf2f6f3` after Home/sidebar !512 merged. All three concepts retain the shared
expanded sidebar, labelled rail and phone navigation from that merge.
The industry index and the NP, Customs, licensing and registration workspaces remain separate.
Three concepts await the founder's pick in a draft MR; this is not a production rollout.

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
| [Notion layouts](https://www.notion.com/help/layouts) | Important properties stay in the heading, others in a details panel | Focus concept reads as a briefing; the register discloses evidence metrics without losing them |
| [Carbon dashboards](https://www.carbondesignsystem.com/building-blocks/data-visualization/dashboards) | Most important information first; fewer metrics and deliberate white space | One primary next step, quiet secondary actions, three essential evidence counts without repeating the current count |
| [Home !512](https://gitlab.com/whistlebird/workflow-engine/-/merge_requests/512) | Style 2 is a sized board, equal bordered metrics, paired regions | Compliance style 2 uses the same hierarchy, spacing and card language without copying Home's score calculation or shell experiment |

Research limits: the SafetyCulture article was searchable but a subsequent fetch failed.
We use its published action description, not an unseen dashboard. None of these sources
establishes how NZ regulatory compliance should be scored. Linear and Notion are craft
references, not food-safety compliance products. No regulatory interpretation is introduced.

## Three directions to choose from

| | Style 1: Focus | Style 2: Board | Style 3: Register |
|---|---|---|---|
| Idea | A reading column, evidence then next action | Readiness and next steps beside each other, obligations across the board | A compact readiness band, framework rows with evidence detail on demand |
| Taken from | MaintainX action queue, Notion property hierarchy | FoodDocs overview, Carbon hierarchy, Home !512 style 2 | Linear grouped lists, Notion disclosure |
| Best at | One operator deciding what to do next | A wide screen and consistency with the chosen Home direction | An experienced operator comparing obligations and opening one |
| Gives up | More vertical scrolling | Stacks at tablet/phone widths; no promise to fit arbitrary data on one wall screen | Extra click to see each framework's full metric breakdown |

All three retain every applicable framework, all returned priority actions, evidence
coverage, current/review/overdue counts and workspace management links. They use the
same template, script, API and shared UI tokens. The three-button switch is temporary.
`?style=1|2|3` takes precedence over the remembered choice; default is Style 1.

### Shared design

Readiness: show current evidence once as a count out of the total, alongside to-review and
(overlapping) overdue counts. The coverage ratio has no new numeric score. A short note
explains that evidence coverage is not a legal compliance score. A textual status is
always present; colour alone carries no meaning. Live-data gaps and source counts stay
accessible in a Data coverage disclosure, preserving the old overview signal.

Next actions: use `priority_actions` exactly as returned; do not generate new obligations
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
success-shaped zeros on an API failure. Collapse/expand and style selection do not fetch.

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
cannot be called NP3, and NP2 must link as NP2. Browser checks cover all styles at 390,
1024, 1440 and 1920, dark theme, expansion, primary destination, quiet/setup/error/retry,
choice persistence and boosted return. Retain the existing overview layout contract for
Style 1's full-width readiness, obligations and management cards. No weakening of tests.

Shoot every style on laptop, phone and dark and the board at 1920. Inspect every image,
record defects each pass and repeat until no defects remain. Use an isolated screenshot
state folder to avoid interfering with Claude's seed. Purge only this run's throwaway org.
Run relevant frontend/unit and shared layout/render/navigation suites, JS syntax, ruff,
semgrep and independent HTML/JS/test review. Upload comparison images into the draft MR.
