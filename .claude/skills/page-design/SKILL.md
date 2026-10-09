---
name: page-design
description: "Designs or redesigns one page of the app until it looks and works extremely cleanly: researches how comparable products and the products with the best UX reputations solve the same problem, writes a plan, builds in the house style, then loops on real browser screenshots (scripts/ui_shots.py) until nothing is left to fix. Use this skill when the user says 'make this page cleaner', 'this page is cluttered', 'make it slick', 'redesign <page>', 'refresh the UI', 'polish this', 'UX pass on <page>', 'it should feel easier', or when new-feature or review-feature builds or reshapes a page. NOT for linting one template or script (html-review, js-review), NOT for functional browser coverage on its own (e2e-playwright), NOT for load time (perf-guardrails), NOT for marketing copy or the landing site (content-producer). Autonomous: ships one MR with the plan and before/after screenshots; the MR is the human gate."
---

# Page Design

A page can pass every gate this repo has and still be a ten-field filter form stacked on
an eleven-column table. Tests prove it works; nothing proves anyone looked at it. And a
design judged from the template is a guess: the Inventory page's script ran once per
browser session, its search threw on every keystroke, and its trend column had never had
data. All three were found by opening the page, none by reading it (!509).

This skill makes looking mandatory and repeatable: research first, a written plan, then a
screenshot loop that only ends when a pass finds nothing.

Read `.agents/autonomy.md`. Ships via MR; an unattended run surfaces its assumptions in
the plan rather than stopping to ask.

## The bar

**Room to breathe, simple, polished, almost too easy.** In practice:

- The first screen shows the answer, not the controls. If filters push the content below
  the fold, the page has failed before anyone scrolls.
- Fewer things, each with more space. Cut columns and fields to what is read every time;
  everything else is one click away (a panel, a "more" control), never deleted.
- One primary action per view. The next step is obvious without reading.
- It looks like its sibling pages: shared tokens, shared card and button classes, one
  accent colour. A page that is beautiful and different is wrong.
- Status is words plus colour ("21 days left"), never colour alone.
- Every state is designed: loading, empty, filtered-to-nothing, error, detail open, phone
  width, dark theme, and arriving by an in-app link rather than a full load.

"Almost too easy" is the test to apply last: if a first-time user would have to think
about where to look or what to press, there is still something to remove.

## Steps

### 0. Preflight and a worktree

```bash
python3 scripts/preflight.py --json
git fetch origin main && git worktree add -b feat/<page>-design ~/.herdr/worktrees/workflow-engine/feat-<page>-design origin/main
cd ~/.herdr/worktrees/workflow-engine/feat-<page>-design && uv sync --extra dev
```

Needs the test database up and Playwright's Chromium (preflight reports both).

### 1. Read the page as it is

The template, its script, its stylesheet, the route that serves it, and every test bound
to its class names or headings (`grep -rn "<class-or-id>" tests/`). Write down what the
page is for in one sentence; that sentence decides what stays on the first screen.

Fix real bugs you find. They ship in the same MR, named in its description, each with a
test that fails on the old code.

### 2. Seed and shoot the page as it is

```bash
env -u ENVIRONMENT uv run python scripts/ui_shots.py seed stock lineage
cp .claude/skills/page-design/scenarios.example.py ~/.cache/workflow-engine-ui-shots/scenarios.py
env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot ~/.cache/workflow-engine-ui-shots/00-before \
    --scenarios ~/.cache/workflow-engine-ui-shots/scenarios.py 2>&1 | grep '^ui-shots:'
```

`seed` creates a throwaway org in the local test database: `stock` is thirty-odd lines
with suppliers, batches, expiries and quantity history; `lineage` is two gin batches
through three steps, sold on six invoices to four customers. Realistic data is the point.
A page designed against three rows named "Test Item 0" is designed for a product nobody
runs. If the page needs data neither seed has, add a seed to `scripts/ui_shots.py`.

Edit your copy of the scenario file so there is one function per state in **The bar**.
Also shoot two sibling pages for the house style (`/core/suppliers`, `/core/dashboard`).
**Read every PNG** with the Read tool. The `00-before` set goes in the MR.

### 3. Research: who does this best

Three kinds of source, all three every time. Use WebSearch and WebFetch.

1. **Comparable products**: at least three that solve the same job for the same kind of
   user (for a stock page: MRP and inventory tools; for a trace: batch-genealogy and
   data-lineage tools). What do they put on the first screen? What did they leave out?
2. **Products with a reputation for craft**: at least two, from any domain, that people
   cite when they praise an interface, and that show the same *shape* of information
   (dense tables: fintech dashboards and watchlists; graphs: lineage and monitoring
   tools; lists with detail: issue trackers). Reputation matters because the bar is
   "feels easy", and these are the products that set what easy feels like.
3. **Pattern guidance**: at least one written source on the specific pattern (data
   tables, filter bars, side panels, graph layout), preferably a design system's own docs.

Prefer a product's own docs, help-centre screenshots and changelogs to listicles. For
each finding record **the pattern, where it came from, and what it changes on this
page**. A finding that changes nothing is not a finding. Say what you looked for and did
not find; do not present your own judgment as a source.

Research decides *structure* (what is on the page, in what order, what is hidden). The
house style decides *appearance*. Never import another product's palette or typeface.

### 4. Write the plan

`docs/<page>-redesign-plan.md`, in the shape of `docs/trace-and-recall-redesign-plan.md`:

- **What is wrong today**: observed in the screenshots, not assumed. (For a new page:
  **What the page must answer**.)
- **What other products do**: the research table from step 3.
- **Design**: section by section, in plain statements.
- **Not in this change**: APIs, calculations and exports left alone, and follow-ups.
- **Checks**: tests to add and the widths and themes to shoot.

The plan ships in the MR. If `docs/source-to-sale-plan.md` or `docs/ux-overhaul-plan.md`
has an item this delivers, tick it in the same MR.

### 5. Build in the house style

- Tokens from `app/core/frontend/css/design-system.css` (`--ui-accent`, `--ui-border`,
  `--ui-surface`, `--ui-text-muted`); layout from `app/core/frontend/css/workspace-overviews.css`
  (`workspace-page`, `workspace-header`, `workspace-stack`, `workspace-card`,
  `workspace-button`). Dark theme comes free if you use the tokens.
- Vanilla JS, no framework. Build DOM with `createElement` and `textContent`.
- The page script goes **inside the content block** with `defer`, and binds to the page's
  root element. Boosted navigation swaps only `#page-content` and keeps `window`, so a
  run-once flag on `window` means the second visit never loads. See
  `app/core/frontend/inventory/view.html`.
- `app/core/frontend/css/base-spa.css` sizes every `#page-content input` and `select`
  with `!important` at high specificity. A compact control needs an id selector
  (`#page-content #my-input`) to win.
- Keep the hooks existing tests use where the element survives. Where behaviour changed
  on purpose, update the test to the new behaviour and say so in the MR; never loosen an
  assertion to get green.

### 6. The loop: shoot, look, list, fix, repeat

```bash
env -u ENVIRONMENT uv run python scripts/ui_shots.py shoot ~/.cache/workflow-engine-ui-shots/01 \
    --scenarios ~/.cache/workflow-engine-ui-shots/scenarios.py 2>&1 | grep '^ui-shots:'
```

One numbered directory per pass (`01`, `02`, ...). Each pass:

1. Shoot every scenario. The command exits 1 if a scenario failed or the page logged a
   console error; that is a defect, fix it before judging pixels.
2. **Read every PNG.** Not a sample.
3. Write the defects down against **The bar**: what crowds, what repeats, what is
   misaligned, what a control is doing at that size, what is clipped at the phone width,
   what disappears in dark.
4. Fix them. Shoot again.

**Stop only when a full pass produces an empty list.** Expect at least three passes; the
Inventory page took six and Trace took three. A pass that finds nothing on the first try
means the scenarios are too few, not that the page is done: add the states you skipped.

Scenarios must *use* the page, not only load it: type in the search, apply and clear a
filter, open and close the detail, save an edit, leave by an in-app link and come back.
Several defects in !509 were behaviour that driving the page exposed, including one in the
new code (a re-render on blur swallowed the click on "Clear filters").

### 7. Prove it works

- Browser tests for what the page now does, following **e2e-playwright**. Include one per
  bug fixed in step 1, run against the old file first to see it fail.
- The suites bound to the page, plus the shared ones:

```bash
env -u ENVIRONMENT uv run pytest tests/e2e/test_production_pages_layout.py tests/e2e/test_pages_render.py tests/e2e/test_boosted_navigation.py -q
node --check app/core/frontend/js/<script>.js
uv run --extra dev ruff check app/
semgrep --config .semgrep/rules/ app/core/frontend/js/<script>.js --error -q
```

- Hand changed or new tests to **test-evaluator**; hand the template and script to
  **html-review** and **js-review** if the diff is large.

### 8. Ship and clean up

```bash
env -u ENVIRONMENT uv run python scripts/ui_shots.py upload ~/.cache/workflow-engine-ui-shots/00-before/desktop.png ~/.cache/workflow-engine-ui-shots/<last>/desktop.png 2>&1 | grep '^ui-shots:'
env -u ENVIRONMENT uv run python scripts/ui_shots.py purge 2>&1 | grep '^ui-shots:'
```

`upload` prints the markdown for each image. The MR description (via **merge-request**)
carries: a before/after table, the other states, what changed, **Behaviour to be aware
of** (anything a user will notice is different or gone), the research basis in three
lines, and the tests. CI's relevant-test selection skips e2e, so say the browser tests
were verified locally. Always `purge`: the seeded org lives in the shared test database.

### 9. Record the run

```bash
python3 scripts/skill_metrics.py record --skill page-design --run-type interactive \
  --scope <page> --verdict patched --findings <defects fixed across passes> --ref feat/<page>-design
```

## Report

`.agents/reports/page-design/<page>.md`:

```markdown
# PAGE DESIGN — <page> — <date>
plan: docs/<page>-redesign-plan.md
research: <n> comparable products, <n> craft references, <n> pattern sources
passes: <n>   defects fixed: <n>   bugs fixed: <list>
screenshots: ~/.cache/workflow-engine-ui-shots/<dirs>
tests: <added> added, <changed> changed (why)
follow-ups: <what the plan deferred>
verdict: patched | findings-open | error
```

`patched`: the last pass was empty and the MR is open. `findings-open`: shipped, but the
list names defects still present or states not shot. `error`: could not seed, boot or
shoot; say which. There is no `clean`: a run that changed nothing did not need this skill.

## Handoffs

- ← the user: "make <page> cleaner", "redesign <page>", "make it slick".
- ← **new-feature**: when the spec adds or reshapes a page, after the build is green and
  before e2e-playwright, so the tests are written against the final page.
- ← **review-feature**: when the audited feature's page fails **The bar**.
- → **e2e-playwright**: conventions for the browser tests in step 7.
- → **test-evaluator**: grades tests this skill added or changed.
- → **html-review** / **js-review**: a line-level pass on a large diff.
- → **perf-guardrails**: if the redesign adds a request or a heavier render.
- → **fix-bug**: a bug found in step 1 that is too wide to fix inside a design MR.
- → **merge-request**: opens and watches the MR.

## Rules

- **Never call a page done without reading the screenshots of the final code.** A design
  judged from the diff is the failure this skill exists to prevent.
- **Never stop the loop on a pass that still found something**, and never shrink the
  scenario list to make a pass come back empty.
- Research is not optional and not decoration: no plan without all three kinds of source,
  and no finding without what it changes here.
- Do not present your own opinion as research. If a search came back thin, say so.
- Structure from research, appearance from the house style. One accent colour.
- Hide, do not delete: a filter or field removed from the first screen stays reachable.
- No change to an API's response, a calculation or an export under the cover of a
  redesign. If the page needs different data, say so in the plan and the MR.
- Never weaken a test to get green. Behaviour changed on purpose is stated in the MR.
- `scripts/ui_shots.py` refuses any `ENVIRONMENT` but local. Do not work around it, and
  never seed a shared or production database (`.agents/autonomy.md`).
- Always `purge`. A leaked org in the shared test database fails someone else's suite.
- Screenshots go under `~/.cache/workflow-engine-ui-shots/`, never into the repository.
