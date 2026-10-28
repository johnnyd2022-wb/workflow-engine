# Moving stock: one Move dialog and a Stock transfers page built for receiving (GL-P07 A4)

**What it is for, in one sentence:** *move stock anywhere it can go from where you are looking at it, and receive it in one click when it arrives.*

## What is wrong today

- **Moving starts on the wrong page.** The only way to move stock between sites is a seven-field form on Stock transfers, with a select of every lot in the business. Nothing on Inventory moves a line.
- **Every compliance question at once.** With NZ Alcohol on, the form asks ten questions, including strength tests that only apply to removals for home consumption.
- **A same-site move across the licensed boundary is refused afterwards.** Moving into the cellar door shop at the same site fails with "requires a recorded dispatch and receipt", after you've filled it in.
- **Receiving takes a form.** Even when everything arrived, receiving means expanding a form and typing the quantity. Received quantities read "Transit 10.0000".

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| [Shopify Stocky, stock transfers](https://help.shopify.com/en/manual/sell-in-person/shopify-pos/inventory-management/stocky/inventory-management/stock-transfers) (comparable) | Mark in transit, then "Receive all items"; in-transit transfers have their own tab | "Received in full" is one click; what is in transit leads |
| [Shopify, transfers and shipments](https://help.shopify.com/manual/products/inventory/transfers) (craft) | Receive full or partial; receive only what actually arrived | "Something's different" for partial, damaged or missing |
| [Katana, what is a stock transfer](https://support.katanamrp.com/en/articles/5966914-what-is-a-stock-transfer) (comparable) | Created → In transit → Received; locked once in transit | Status board columns (Style 2) |
| [Moneris, incoming inventory transfers](https://mymorris.moneris.com/help/en_CA/moneris_pos_admin/inventory/inventory_transfers/incoming_inventory_transfers.htm) (comparable) | "Receive All" for a full receipt, a separate action for partial | Same split: one primary action, one quiet one |
| [GOV.UK, question pages](https://design-system.service.gov.uk/patterns/question-pages/) (pattern) | Ask only the questions that apply, based on earlier answers | Compliance questions carry `show_when`; the dialog asks them only then |

**Looked for, not found:** a product whose move dialog decides for you between a one-step internal move and a dispatch based on the licensed area. That is the 10x: you say *where*, the dialog works out *how* (one step, dispatch, or dispatch across the licensed boundary) and asks only what that needs.

## Chosen: Style 1, to receive first (founder, 2026-10-28)

- **Style 2 (status board)** lost because narrow columns stacked the actions and made a phone scroll further, for a pipeline view few businesses need.
- **Style 3 (by site)** lost because it showed each transfer under two sites and offered nothing a person receiving deliveries needs first.

## Three directions for Stock transfers (as presented)

| | Style 1: To receive first | Style 2: Status board | Style 3: By site |
|---|---|---|---|
| Idea | A "To receive" card leads, history underneath | A column each for In transit, Part received, Received | Each site: coming in, going out, arrived |
| Taken from | Stocky's In transit tab, notification inboxes | Katana statuses, kanban boards | Location-first POS receiving |
| Best at | The person receiving deliveries | Seeing the whole pipeline | Businesses with a person at each site |
| Gives up | Less sense of the whole flow | Narrow cards, more scrolling on a phone | Repeats a transfer under two sites |

**All three share:** Move stock in the header (pick a line, then the Move dialog), "Received in full" / "Received the rest (n)" in one click, "Something's different" for partial, damaged or missing, the docket, and plain words ("40 of 48 received", "In transit").

## The Move dialog (shared)

`app/ui/shared/move-stock.js`, opened from **Move…** in an Inventory line's detail panel and from **Move stock** on Stock transfers:

- **Quantity** (all of it by default) and **To**: other areas here, then other sites and their areas.
- Another area at the same site, same side of the licensed boundary: **one step**, recorded straight away.
- Another site, or across the licensed boundary: a **dispatch**. It asks for the carrier, a docket reference (filled in) and the date, plus the compliance module's questions, and only the ones the chosen answers need.
- A refusal stays in the dialog, beside what caused it.

## Data changes

- `GET /api/core/sites/choices`: each area says whether it is `inside_licensed_area`.
- Transfers carry `source_site_name`, `destination_site_name` and `batch`, taken from the snapshot made when the stock left.
- Compliance requirement fields may carry `show_when: {field: [values]}`. NZ Alcohol's approval reference and date belong to prior Customs approval; its five strength and volume fields belong to home consumption.

## Not in this change

- **Licensed status:** it still comes from each area's flag; reading it from the Customs register is A5. The dialog doesn't yet know a product needs a Customs classification until Dispatch is pressed (A5: ask the module about the line when the dialog opens).
- **Confirmed losses:** in NZ Alcohol they need Customs accounting first; the receipt form says so when refused (A5).

## Checks

- Unit: licensed flags in choices; snapshot names on transfers; NZ `show_when`.
- Browser:
  - a one-step area move;
  - a dispatch to another site from Inventory, received in one click;
  - a refused quantity kept in the dialog;
  - no Move for a single-site business;
  - NZ dispatch with approval, then a partial receipt and the docket (rewritten for the dialog);
  - home-consumption removal across the boundary at one site;
  - the page fits and receives at phone, laptop and wall.
