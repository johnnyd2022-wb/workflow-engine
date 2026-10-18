# Batches redesign: three directions

## Selected design — 2026-10-18

The founder selected **Style 1: Lanes**. Styles 2 and 3 were not selected and are removed, together with the preview switch and remembered/query-string layout selection. The comparison below records the alternatives considered; the shipped page has one layout. Final responsive tests retain the selected layout at phone, 1024, desktop and wall widths, including old preview bookmarks.

Scope: `/core/executions/live`, the **Batches** page (Production › Batches; registry title
"Batches"). Purpose: **show every batch under way, where each one is, and which ones have
been waiting too long for their next step, so someone can record it.** The executions API,
the step-recording screen and the Home figures are not changed.

## What is wrong today

Observed in the seeded screenshots (`~/.cache/workflow-engine-ui-shots/batches-00-before`:
1440, 390, 1920 and dark; three workflows with seven batches under way):

- **Most batches are hidden.** The board shows one workflow at a time, picked in a dropdown.
  With seven batches across three workflows, the first screen shows three; the other four
  need the dropdown, and nothing says they exist.
- **The same thing twice.** A step rail (numbered boxes, "1 batch here") sits above step
  columns that repeat the same names and counts. Together they push the first batch to
  y≈820 at 1440, at the fold.
- **No sense of age.** A card says "Started 3 days ago" and "2 of 3 steps done", but not how
  long the batch has sat at its current step. Home reports "Production batches idle for more
  than 48 hours" and links here, and this page cannot show which ones they are.
- **Every card says "In progress".** All seven do; the pill carries no information. The
  "Ready to record" filter and figure are always 0, because a started batch is never
  `pending`.
- **Searching by workflow name does nothing.** The search reads `process_name`, which the
  executions list never returns.
- **Dark theme.** Batch cards keep a white background with pale text, so their titles are
  unreadable; the arrows in the step rail vanish.
- **Phone.** The process select, view toggle, search and three filter chips fill the first
  screen; the bottom nav bar covers the figures.
- **Timeline.** Date marks repeat ("Oct 14 Oct 14 Oct 15 Oct 15") when the range is short.
- The card is titled "Production board", which is also the Planner board's page title.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [Katana, managing the production process](https://support.katanamrp.com/en/articles/149-managing-the-production-process) | Page read | Two views of the same work: a **Schedule** of manufacturing orders as cards, and a **Tasks** list of the operations to do next, assignable to operators | Style 1 is the schedule-as-cards view; Style 3 is the tasks view, grouped by the next step to record |
| [Katana, Shop Floor Control app](https://support.katanamrp.com/en/articles/5967437-shop-floor-control-app-overview) | Search summary only | Operators see only their tasks; within an order "this task" is highlighted, with Start / Finish as the one action | Style 3 leads each queue item with **Record next step**; the detail sheet marks the current step |
| [MRPeasy, manufacturing orders](https://www.mrpeasy.com/resources/user-manual/production-planning/manufacturing-orders/) | Search summary only | Order status is set by the system: In progress once the first operation starts, **Paused** when started but no operation is active | Status is derived, not a pill on every card: a batch shows how long it has waited at its step, and the long waits are called out |
| [Ekos, fermentation history](https://www.brewbound.com/news/supplier-news/new-ekos-feature-enables-brewers-to-track-fermentation-history-across-batches/) | Search summary only | Brewery batches tracked over time and compared side by side | Confirms the timeline (time spent per step) is worth keeping; it stays one click away in all three styles. No in-progress screen was found to compare |
| [Jira, "Days in column"](https://community.atlassian.com/forums/Jira-questions/How-to-add-Days-in-Column-Card-layout-menu-missing/qaq-p/2554688) | Search summary only | A card can show how long it has sat in its current column | Every batch shows time at its current step ("2 days at Distil") |
| [Linear, board layout](https://linear.app/docs/board-layout) | Page read | Columns follow the workflow order; **swimlanes** add a second dimension (rows across the columns); empty groups can be hidden; cards stay short and the full item opens in a peek | Style 1 is one lane per workflow with its steps as columns; empty steps shrink; the detail sheet is the peek |
| [Vercel, managing deployments](https://vercel.com/docs/deployments/managing-deployments) and [deployment filters](https://vercel.com/changelog/deployment-filters-for-project-dashboard) | Search summary only | One list of every deployment across branches, filtered by dropdowns; filter state lives in the URL | Style 2 is one list of every batch across workflows; the workflow filter and search are in the URL so a filtered view can be shared or linked from Home |
| GitHub Actions run list (`gh run list` columns, via a third-party guide) | Search summary only | Each run is a row: status, name, workflow, branch, elapsed | Style 2's row: batch, workflow, step, time at step, started |
| [Kanban Guide work item age](https://prokanban.org/blog/visualising-work-item-aging-in-jira) and [Kanban Zone card aging](https://kanbanzone.com/2020/card-aging-fun-and-helpful-visual-signal-for-kanban/) | Search summary only | Item age is time since work started; aging is shown on the card, resets when the card moves column, and has thresholds | Age at the current step resets when a step is recorded; one threshold (48 hours, the same number Home uses) marks a batch "Waiting" in words and colour |
| [Carbon, status indicator pattern](https://www.carbondesignsystem.com/patterns/status-indicator-pattern) | Search summary only | Status is icon, colour **and** a text label; progress is medium attention, needing no action | Waiting is a word plus amber, never amber alone; the step progress bar is quiet |

Research limits: only the Katana production-process and Linear board pages were opened and
read; the rest are search summaries. Searches for Primer (GitHub's design system) guidance on
run lists, and for an Ekos in-progress screen, came back with nothing usable.

## Three directions considered

| | Style 1: Lanes | Style 2: List | Style 3: Next steps |
|---|---|---|---|
| Idea | A lane per workflow, its steps as columns, each batch a card in the step it is at | One list of every batch, longest wait first, one row each | One sentence, then the work to do: grouped by the next step to record, oldest first |
| Taken from | Linear swimlanes, Katana schedule cards, Jira days in column | Vercel deployments, GitHub run list, MRPeasy order list | Katana Tasks and Shop Floor app, Kanban aging |
| Best at | Seeing where batches pile up; a screen on the wall | Many batches; searching; a phone | Starting a shift: what do I record next |
| Gives up | Width: a phone stacks each lane's steps | The shape of each workflow | Which workflow a batch is in reads second |

All three share:

- **Every workflow at once.** No process dropdown in the way; a "Workflow" filter narrows it
  ("All workflows" by default). Workflows with nothing under way are left out.
- **Time at the current step** on every batch ("3 hours at Distil"). A batch with no step
  recorded for 48 hours is **Waiting** ("Waiting 4 days"), in words and amber.
- **Figures**: under way, waiting, finished in the last 7 days (Style 3 says them as a sentence).
- **One action per batch**: Record next step, in the detail sheet (and on the item in Style 3).
- **Timeline** stays, one click away (the "Timeline" toggle), now across every workflow.
- **Filters**: search (batch, workflow, step or person) and All / Waiting chips; filter state
  is in the URL (`?workflow=`, `?q=`, `?show=waiting`). The "Ready to record" chip and
  figure go: they were always 0.
- The card is titled **Under way**, so it no longer shares a name with the Planner's
  Production board.
- Loading, nothing under way, filtered to nothing (with Clear filters), and a load error
  (with Try again) each have their own message.

## Not in this change

No change to the executions API, the step-recording screen (`/core/flows/batches/start`),
permissions or the Home figures. "Waiting" is computed in the browser from step timestamps
the list already returns.

Home's "Production batches idle for more than 48 hours" counts batches **started** more than
48 hours ago; this page's "Waiting" counts batches with **no step recorded** for 48 hours. The
seed shows 3 against 2. Aligning Home's figure is a follow-up for the founder to decide, not
part of a redesign.

The script is still loaded from `base_spa.html` on every page (it binds only when the board is
present); moving it into the content block is left for the cleanup after the pick.

## Checks

- **Browser tests** (`tests/e2e/test_batches_design.py`):
  - every workflow's batches on the first screen with no dropdown;
  - time at step, and Waiting after 48 hours, in words;
  - search by workflow name (failed before: the search read a field the API never sends);
  - workflow filter and the Waiting chip, written to the URL, and Clear filters;
  - the detail sheet's Record next step link;
  - dark theme batch titles readable (failed before: white cards, pale text);
  - selected Lanes layout at 390, 1024, 1440 and 1920 with no sideways scroll or overlapping cards, old preview bookmarks, one stylesheet and hidden accessible filter labels.
- **Existing tests**: the shared layout test now finds the page by its "Under way" card.
  `test_workflow_flow.py` picks a workflow with the new filter.
- **Screenshots**: each style at laptop, phone, wall and dark; busy and quiet; filtered,
  filtered to nothing, nothing under way, load error, detail open, timeline, and arriving by
  an in-app link.

## Review outcome

Eight screenshot passes (`~/.cache/workflow-engine-ui-shots/batches-01` … `batches-08`), each
covering all three styles at laptop, 1024, phone, wall and dark, busy and quiet, searched,
Waiting only, filtered to nothing, one workflow, nothing under way, a load error and retry,
the detail sheet, the timeline, and arriving by an in-app link:

1. **Pass 1.**
   - The search and workflow labels and the table's "Action" header showed: `sr-only` is not
     defined on this page.
   - The figures repeated the card title ("Under way" twice).
   - Style 2's Waiting tag stretched the width of its cell.
   - A phone left a tall blank gap under the figures.
   - Style 3's waiting row sat indented against the others.
   - A brand-new batch read "under a minute at this step".
   - Long step names in an empty column were cut off.
2. **Pass 2.** The page stylesheet sometimes failed on a full load (`ERR_TOO_MANY_RETRIES`)
   because it was only linked inside the content block; it is now in the head as well, and the
   content-block link stays for boosted visits. On a phone no batch was on the first screen, so
   the heading and view toggle now share a row.
3. **Pass 3.** Style 3 spread a batch and its Record button 1,100px apart on a wide screen; its
   sections now keep a reading width. Style 2's columns jumped when a filter changed.
4. **Pass 4–5.** Figures and filters showed on the error and empty states, where they have
   nothing to say. The timeline skipped a day label (13, then 15 Oct). Style 3's empty state
   said "nothing under way" twice.
5. **Pass 6–7.** Style 2's "Record …" link ran past the card at 1024px. The phone timeline's
   last date ran under "Now".
6. **Pass 8.** No defects found.

The local screenshot server also drops Stocktake's page stylesheet on a cold first load, so
that failure is the dev server's, not this page's; the scenario file reloads once when it
happens. The two console errors in every pass are the 503s the load-error scenario injects.

## Final selection verification — 2026-10-18

The founder chose Style 1 (Lanes). List and Next steps were not selected, and their renderers, CSS, DOM, preview controls and layout persistence are deleted. Historical comparisons above document the choice. All 21 final screenshots in `batches-style1-final/03` were visually inspected, including dark/phone, filters, detail, timeline, quiet/empty states, error/retry and boosted return; no visual defects remain. The two console errors are the intentionally injected 503 responses. Earlier passes encountered Chromium `ERR_TOO_MANY_RETRIES` for the stylesheet. Duplicate page stylesheet links were replaced with a single shared-head link following the sibling-page pattern; this removes redundant/late loading without claiming to diagnose the transport failure. The final pass had no such failed requests.

Independent review caught the shared visually-hidden filter-label utility during cleanup; it is restored. Four responsive tests assert one stylesheet and the hidden label utility, and all nine final page cases passed, including the unchanged 4.5:1 contrast threshold. Independent HTML/JS/test review found no further cleanup findings or weakened assertions. Node syntax and Ruff passed. The page HTML/JS Semgrep scan passed; expanding the scan to the shared base template flags its existing inline data-URI favicon as missing external-resource integrity, on an unchanged line. The baseline comparison is recorded in the MR; shared-suite results and exact-head CI are recorded in the MR. Screenshot fixture purged.
