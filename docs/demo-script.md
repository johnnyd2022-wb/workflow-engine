# Demo script (GL-C06, placeholder)

**Placeholder.** Not demoing until the go-live checklist is done (founder, 2026-10-26). The two
orgs and the order below are a starting point to rehearse and rewrite.

## Load the orgs

```bash
env -u ENVIRONMENT uv run python scripts/demo_orgs.py load     # prints the two sign-ins and one password
env -u ENVIRONMENT uv run python scripts/demo_orgs.py status
env -u ENVIRONMENT uv run python scripts/demo_orgs.py purge    # after the demo
```

| Org | What's in it | Use it for |
|---|---|---|
| Demo · Kōwhai Distillery (new) | An admin, the Compliance (NZ Alcohol) plan, nothing else | "How fast do I get value?" |
| Demo · Harbour Spirits (established) | Months of history: stock with suppliers and expiries, gin and limoncello batches traced to Xero sales, excise periods (two lodged, a backlog), a sale to a duty free shop, NP3 evidence, licences, contract orders, tasks | Specific questions |

The data is synthetic, built from the screenshot harness's seeds (`scripts/ui_shots.py`).
Whistlebird's own replay (`scripts/replay_whistlebird.sh`) has real customers and suppliers, so
it is not used in front of prospects.

## Scenario 1: a new setup, value fast (Kōwhai, about 10 minutes)

The point: from sign-up to "this batch went to these customers" without a consultant.

1. **Home → Getting started** (`/core/getting-started`). Six steps, in order, each one link.
2. **Set up a product workflow:** *Pick a template* → *Spirit: receive to bottle*. Say what
   comes switched on: ABV at bottling, batch numbers, the checks NP3 and Customs ask for.
3. **Count the stock you hold today:** add two botanicals and a neutral spirit with batch
   numbers. Opening stock is how they start without rebuilding history.
4. **Record your first batch:** *Record production step* → start a batch → record the first
   step. Two taps to any step.
5. **Connect Xero** (talk track only in the demo org): every authorised invoice takes its
   bottles off the oldest batch (FIFO), so the trace and the excise entry build themselves.
6. Close on the setup guide: what's done, what's next.

## Scenario 2: an established distillery, the exception loop (Harbour Spirits, 15–20 minutes)

The assessment's test: receipt → production → sale → exception → corrected trace and duty,
with every manual step visible. Pick the parts the prospect asks about.

| Question | Where | What to show |
|---|---|---|
| "What needs me today?" | Home (`/core/dashboard`) | Needs attention, the compliance score, this week's figures |
| "Where is everything at?" | Production (`/core`), Production board | Seven batches at different steps; *Record next step* |
| "A supplier recalls a botanical lot" | Trace and recall (`/core/sourcemap`) | From the lot to every batch and every customer invoice, and back |
| "What do I lodge with Customs this month?" | Compliance → Customs (`/compliant/nz-alcohol/customs`) | The entry in Trade Single Window's order, copy buttons, overdue months, the year's duty |
| "We sell to the airport duty free" | Customs → Transfers | Left out of duty; when it left, the carrier, the receipt |
| "Our stock doesn't match" | Customs → Stock, stocktake | Counted against expected, what explains the difference |
| "MPI verification is next month" | Compliance → NP3 | The checks, the evidence each has, what's overdue |
| "We make for other brands" | Production → Contract orders | Orders, customer-owned materials, dispatch to their CCA |
| "Who did what?" | Any batch → its history | Every step, who recorded it and when |

**Exceptions still to script** (they depend on checklist items not built yet):
- a return or credit note (GL-P01);
- a quality hold and release (GL-P02);
- a recall case with acknowledgements (GL-P03).

## Before the first real demo

- Founder rehearses both scenarios and rewrites this page in their own words.
- Decide whether the demo runs locally or on the deployed test environment (the loader refuses
  anything but the local test database today).
- Re-run `load` the morning of a demo: the dates are relative to today.
