# Sales to other CCAs (GL-P08)

## The rule (founder, 2026-10-26)

> As soon as goods leave a premise it needs to be recorded as movement from the CCA. If it's
> moved to another CCA that transfer is recorded, which requires the time and date of movement
> and ideally proof of receipt. Duty free (we sell to them) is the same: we record it
> transferring to another CCA and need their CCA code. The same applies to contract
> manufacturing. As soon as goods leave the CCA they are either transferred to another CCA or
> lodged for excise.

Customs' operational policy *Product movement excise unpaid – alcohol* (v2.0) agrees:

- **Para 7:** the general authorisation in every Alcohol Excise Plan covers removals to a duty
  free shop or an export warehouse. It also covers a contract manufacturer sending finished
  goods to an owner who holds a CCA licence. No permit is needed.
- **Para 11:** the sending CCA stays responsible until the goods are receipted at the destination.
- **Para 15:** the sender keeps a register: the destination CCA's name and address, the date it
  moved, the carrier and consignment notes, the date it was received, and what moved.
- **Para 16:** the destination gives written acknowledgement that the goods arrived.

## What was wrong

A Xero sale to a duty free shop counted as a removal for home consumption. The excise draft
taxed it, and nothing recorded the movement Customs asks for. The only CCA movement register
covered transfers between the org's own sites.

## What this change does

- **CCAs you send to** (`cca_destinations`): name, CCA code, address, kind, and optionally the
  customer it belongs to. Linking a customer makes every sale to them a transfer.
- **The register** (`cca_departures`): one row per sale. It records the destination, when it
  left (NZ time), the carrier, the consignment note, and the receipt with its evidence. A
  receipt can't be recorded without its evidence (database check), or dated before the goods left.
- **The excise draft:**
  - Sales that are transfers are left out of the duty lines and listed under `cca_transfers`,
    with their LAL kept for the register.
  - A transfer without its register row is a "Fix before lodging" item that links to Transfers.
  - Late invoices that are transfers aren't carried into the next period as removals.
  - The lodged snapshot keeps the transfer list.
- **A sale can be marked by hand**, for a one-off to a customer who isn't linked, and unmarked again.
- **Statuses:** Needs movement details, Awaiting receipt, Receipt overdue (14 days after it
  left), and Received.

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| NZ Customs policy (para 15–16) | The register's columns, and a written receipt | Style 1's columns. Every form asks only these. |
| EMCS / HMRC BEER7040 (UK/EU duty suspension) | A movement stays open until a report of receipt arrives, due within 5 days. An open movement holds the guarantee. | The "Awaiting receipt" and "Receipt overdue" states, and Style 2's to-do list |
| TTB 27 CFR 19.405 / 25.292 (US in-bond) | The consignor keeps a transfer record per shipment and sends the original to the consignee | One register row per sale, with the consignment note |
| GOV.UK task list (pattern) | Rows with short status tags, the action named in words | Style 2 names each card by its action ("Record the receipt: …") |
| Vanta / Drata controls (from the Records redesign) | Grouped by the thing being proven | Style 3 groups by destination |

**Looked for but not found:** how Ekos, DistillX5 or Orchestrated lay out in-bond transfers.
Their help pages were not reachable (403) or don't describe the screen.

## Chosen: Style 1, the register (founder, 2026-10-26)

Customs → Transfers is the register laid out the way Customs asks for it: sale, destination, goods, when it left, when it was received, and status. It is filtered To do / Received / All, and a row opens its detail and the next form.

- **Style 2 (To do)** lost: it gave the fastest backlog-clearing, but no overview of the register itself.
- **Style 3 (By destination)** lost: its cards are narrow, and there is no single date-ordered list to show Customs.

## Three directions considered

| | Style 1: Register | Style 2: To do | Style 3: By destination |
|---|---|---|---|
| Idea | Customs' register as a table (sale, went to, goods, left, received, status), filtered To do / Received / All; a row opens its detail and the next form | One card per transfer still to record, each with its form already open; received ones folded below | One card per destination CCA (code, address, linked customer) with its sales under it |
| Taken from | Customs' para 15 register, TTB transfer record | EMCS open movements, GOV.UK task list | Vanta controls, an address book |
| Best at | Showing a Customs officer the register | Clearing the backlog in one sitting | "What have we sent the duty free shop, and is it all receipted?" |
| Gives up | A click to reach each form | Less of an overview of what's done | No single date-ordered list |

**All three share:**
- the summary line;
- "Mark a sale as a transfer";
- the forms;
- the CCAs you send to;
- the rule note;
- the entry page's "Left out of duty: N sales to another CCA → Transfers" line.

## Not in this change

- **Dispatching contract orders** (GL-P08 part 2). Contract goods leave without a Xero sale, so
  they need a dispatch record that takes the stock off. It follows in its own MR: a
  customer-liable order's dispatch is a transfer here, and a producer-liable one is a removal.
- **A period that is already lodged** keeps its snapshot. Marking one of its sales as a transfer
  afterwards doesn't credit the duty paid: raise a duty credit with Customs, as for returns.
- **An export of the register** (CSV or PDF for Customs).

## Checks

- `tests/test_cca_transfers.py` (8). Three of them fail on the old excise code:
  - a linked sale is left out of duty;
  - marking and unmarking by hand;
  - late transfers aren't carried.
  
  The others cover:
  - receipt evidence and dates;
  - destination validation;
  - tenant isolation;
  - the overdue status.
- `tests/e2e/compliant-platform/test_customs_transfers.py`:
  - record a movement, then the receipt;
  - the entry page note and its link;
  - adding a CCA linked to a customer;
  - the register at phone, laptop and wall width with no sideways scroll, and no design switch left.
- Screenshots: `~/.cache/workflow-engine-ui-shots/transfers/01`–`07`. Passes 1–6 found:
  - misaligned register columns;
  - form labels at uneven heights;
  - a truncated destination select;
  - a form with no heading;
  - a crushed form in Style 3's narrow cards.
  
  Pass 7 found nothing. After the pick, pass 8 of Style 1 alone found nothing.
