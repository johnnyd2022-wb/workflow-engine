# Getting started: a guided first day (GL-P09)

## What the page must answer

**What do I do next to get from sign-up to my first sale traced back to its batch, and how far am I?**

The go-live assessment (!570, GL-P09) found that "getting started is still a collection of capable screens". Opening stock, workflow templates, the Xero connection and product mapping all exist, but a newcomer gets no dependable sequence. Home had one banner, "Setting up? Go live with a stocktake", which covered one step of six.

## The path

Seven steps. Each one's state is read from what the org has actually done, so nothing needs ticking and the guide can't drift from the data. A step for a module the org doesn't have (Compliance, Sales) is left out.

| Step | Done when | Where it's done | Waits for |
|---|---|---|---|
| Tell us what you make | the Compliance profile has product types | `/compliant/nz-alcohol` | — |
| Set up a product workflow | a non-draft workflow exists | template catalogue | — |
| Count the stock you hold today | the go-live date is set | `/core/go-live` | — |
| Record your first batch | any batch step is recorded | `/core/processes` | a workflow |
| Connect Xero | a Xero tenant or invoice exists | `/crm/configuration` | — |
| Match your Xero products to yours | a product mapping exists | `/crm/configuration` | Xero |
| Follow a batch to its customers | a sale is allocated to a batch | `/core/sourcemap` | mappings |

Home's banner now reads "Getting started · 5 of 7 done · Next: …" with **Continue setup**, until every step is done.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Shopify Polaris setup guide](https://shopify.dev/docs/api/app-home/patterns/compositions/setup-guide) (comparable; craft) | One card on the home page: "N out of M steps completed", one step expanded with its description and action, the rest folded; steps are ticked when done | Style 1. The open step is the next one, and done steps show their fact ("4 workflows") |
| [GOV.UK task list](https://design-system.service.gov.uk/components/task-list/) (pattern) | Grouped lists; each whole row is a link; status in words, sentence case; "Completed" plain so to-dos stand out; for tasks done in any order across sessions | Style 2. Groups (Your business, Production, Sales, Check it works), and "Cannot start yet" with the reason in place of the hint |
| [Stripe account checklist](https://docs.stripe.com/get-started/checklist/account) (craft) | A short checklist to finish before going live, used without blocking the dashboard | All three: setup never blocks the app; the guide is reachable from Home, not a gate |
| Wizard and stepper guidance ([Visa](https://design.visa.com/patterns/wizard), onboarding pattern write-ups) | One step at a time with a step indicator and `aria-current="step"`; let people skip non-essential steps; a checklist beats a wizard when steps are optional | Style 3. One large step with **Skip for now**, and the path beside it to jump anywhere |

**Looked for and not found:** Katana's and Xero's own first-run checklists. Their help centres describe setup steps, but not the screen.

## Three directions to choose from

| | Style 1: Setup guide | Style 2: Task list | Style 3: One step at a time |
|---|---|---|---|
| Idea | One card; the next step open with its button, the rest one line each | Grouped cards of rows; every row a link with its status in words | The next step large, with the path of all steps beside it |
| Taken from | Shopify setup guide, Stripe checklist | GOV.UK task list | Stepper and wizard guidance |
| Best at | Seeing the whole path and acting on the next step in one glance | Coming back later and picking any step; reads like a plan | A first-timer who wants to be told one thing |
| Gives up | Other steps' explanations are a click away | More to read; the next step is marked, not featured | Seeing every step's detail at once |

**Chosen: Style 1, the setup guide** (the founder's pick on !574, 2026-10-26).
- **Style 2 (task list)** lost: it reads like a plan, but makes a newcomer scan four cards to find the one thing to do.
- **Style 3 (one step at a time)** lost: it hides the whole path behind a side list, and on a phone shrinks the path to numbered dots.

**Shared by all three:**
- progress as "N of M done" with a bar;
- status always in words ("To do", "Done", "Cannot start yet") alongside colour;
- a blocked step says what it waits for;
- the "You're set up" state;
- the error state;
- the same API and the Home banner.

## Not in this change

- No step is done on this page; each links to the page that does it.
- **Follow-up:** a sector picker at sign-up, so templates and frameworks are chosen from the start.
- **Follow-up:** the 32px drop on a boosted arrival at pages without section tabs (this page and Go live). It's app-wide, logged for GL-U04.

## Checks

- `tests/test_getting_started.py`: states from records, blocked steps, drafts don't count, the page renders.
- `tests/e2e/test_getting_started_page.py`:
  - progress and the open next step;
  - a blocked step;
  - all done, where the Home banner goes away;
  - a failed load;
  - the guide at 390, 1440 and 1920 with no sideways scroll.
- `tests/e2e/dashboard/test_dashboard_today.py`: the Home banner leads here (an intended change).
- Shots: each style in the real, new and done states at laptop, phone and dark, plus wall, error, Home and a boosted arrival. Seven passes; the last was clean.
