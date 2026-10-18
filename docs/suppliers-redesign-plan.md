# Suppliers redesign: three directions

Scope: `/core/suppliers` (Production › Inventory › Suppliers; registry title "Suppliers").
Purpose: **who you buy from, what you buy from them, and how to reach them.** That sentence
decides the first screen: each supplier with what you buy from them and a way to call or email,
and which of them are missing details.

## What is wrong today

Observed in `~/.cache/workflow-engine-ui-shots/suppliers/00-before` (seeded with `stock` and the
new `suppliers` seed: eight suppliers, four missing a phone, email or address, one name on stock
that is not a supplier record):

- **An address book with no link to buying.** The table is name, contact, phone, email, address,
  notes, Edit and Delete. Nothing says what you buy from whom, though every inventory line already
  names its supplier. "Southern Hops", which you have bought nothing from, looks the same as
  "Davis Trading", which supplies three lots in stock.
- **Seven columns, two buttons per row.** Long notes and addresses make every row three lines tall;
  at 1440px only two suppliers fit on the first screen. Edit and Delete repeat on every row.
- **Dark theme is unreadable (bug).** The stylesheet hard-codes `#172033` text and white backgrounds:
  supplier names, the four figures and the search box disappear (text contrast 1.02:1).
- **The search box is 60px tall (bug)** with a second bordered box inside it: `base-spa.css` sizes
  every page input with `!important`, and the page's own rule loses.
- **Phone width** keeps the seven-column table and scrolls it sideways inside the card.
- **Phone and email are plain text**: no tap to call or mail.
- **A load error** leaves two empty cards under a red line, with no way to try again.
- **"All suppliers" is highlighted by default**, so the eye lands on the least useful figure.

## What other products do

| Source | How it was read | Pattern | What it changes here |
|---|---|---|---|
| [Katana, Supplier cards](https://katanamrp.com/?p=13251) and [Suppliers collection](https://support.katanamrp.com/en/collections/13060759-suppliers) | Blog page read; help collection from search summary | A supplier table; clicking a name opens the supplier's card with phone and address, used to ring a supplier about an order or brief a courier | Style 1: a slim table, the name opens the details in a drawer, with Call and Email first |
| [MRPeasy, purchasing](https://www.mrpeasy.com/demo-videos/purchasing-management/) | Search summary of the demo transcript; no vendor-list doc found | Choosing a vendor highlights the items linked to it; the vendor is defined by what you buy from it | "What you buy" on every style, and search matches it ("juniper" finds Davis Trading) |
| [Xero, contacts](https://www.xero.com/nz/accounting-software/organise-contacts/) | Search summary only | Each supplier's contact page carries the history with them (bills, payments, notes), not only an address | The details show the inventory lines bought from them, with batch and quantity |
| Unleashed, suppliers | Search found only third-party reviews; no help doc found | Supplier records with performance reporting | Nothing taken: no first-party source to read |
| [Apple HIG, split views](https://developer.apple.com/design/human-interface-guidelines/split-views) (craft: Contacts, Mail) | Search summary of the HIG page | Pick in the leading pane, see the item in the next; keep the selection highlighted; stack on a narrow screen | Style 2: the list beside one supplier's details, selection highlighted, a drawer on a phone |
| [Attio, record pages](https://attio.com/help/academy/introduction/record-pages) (craft: CRM praised for its interface) | Search summary | A record's actions (compose email, add note) sit right under its name; attributes in sections | Call and Email sit under the supplier's name in the details, above the facts |
| [Notion, gallery view](https://www.notion.com/help/galleries) (craft) | Search summary | Each record a card showing only the properties you choose | Style 3: a card per supplier showing contact, what you buy, and its call and email buttons |
| [Microsoft list/details](https://learn.microsoft.com/en-au/windows/apps/develop/ui/controls/list-details) and [SAP Fiori master-detail](https://www.sap.com/design-system/hcm/patterns/structure-and-layout/master-detail/usage) | Search summaries | Side by side from ~640px, stacked below; for browsing a set fast without a page change | Style 2 goes side by side from 900px (the page has a sidebar) and opens a drawer below it |
| [Carbon, data table usage](https://carbondesignsystem.com/components/data-table/usage/) | Search summary | Tables are for reaching a specific record to finish a task; expandable rows suit a little extra detail, not a whole record | Style 1 opens a drawer rather than expanding rows: the details carry their own actions |
| [GOV.UK summary list](https://design-system.service.gov.uk/components/summary-list/) and summary card | Search summary | Label and value rows for one record's details; a card variant when one action applies to the block | The details are a labelled list (Contact, Phone, Email, Address, Notes), with "Not recorded" for a gap |

Research limits: most sources were search summaries, not pages read in full. No first-party
supplier-list documentation was found for MRPeasy or Unleashed; Linear (craft) was searched for
its customer pages but they show requests per customer, not contact records, so nothing was taken.

The three schools found: **a table you scan** (Katana, Carbon), **a list beside the selected
record** (Apple Contacts and Mail, Attio, Fiori), and **a gallery of cards** (Notion, GOV.UK
summary cards).

## Three directions to choose from

| | Style 1: Register | Style 2: Address book | Style 3: Cards |
|---|---|---|---|
| Idea | Four figures that filter, then a slim table; a row opens the details in a drawer | A strip of figures, then the list beside one supplier's details | One sentence, then a card per supplier, the ones missing details first |
| Taken from | Katana supplier table and cards, Carbon data table, Home's figures | Apple Contacts / Mail split view, Attio record page, Fiori master-detail | Notion gallery, GOV.UK summary cards |
| Best at | Scanning many suppliers; matches Home and the other refreshed pages | Looking people up all day: every detail on screen without a click | Filling in the gaps; calling or emailing straight from the list |
| Gives up | A click to see address and notes | Width: on a phone it is a list and a drawer, like Style 1 | Density: fewer suppliers per screen; the figures become words |

All three share:
- "What you buy" for every supplier, worked out in the browser from the compact inventory list
  (`GET /api/core/inventory?view=compact`, already used by Trace and recall), with lots in stock;
- the gaps named in words ("No email or address") as an amber tag, and a **Need details** filter;
- a **Buying from now** filter (suppliers with a lot in stock);
- search over name, contact, phone, email, address, notes **and what you buy**;
- **On stock, not listed**: names on inventory lines with no supplier record, with a one-click
  import (the same `import-from-inventory` call as the header button, which stays);
- one supplier's details: Call and Email links, a labelled list with "Not recorded" for gaps, the
  inventory lines bought from them, **Edit details** as the one primary action, Delete as a quiet
  link. After a save the details come back with a **Saved** tag;
- loading, filtered-to-nothing (with Clear search and filters), load-error (Try again) and
  no-suppliers states; tokens only, so the dark theme follows.

## Decisions for the founder (not taste)

- **Removed from the first screen:** the Address and Notes columns, and Edit/Delete on every row.
  All are one click away in the details. The old "Complete details", "No phone or email" and
  "No address" groups become one **Need details** filter; each row's tag says which detail is missing.
- **New figure: Buying from now** counts suppliers with at least one inventory line above zero
  that names them (matched on the supplier name, ignoring case).

## Not in this change

No API, model, calculation or export change. The page reads one more existing endpoint (the
compact inventory list) for "what you buy"; if it fails, the register still works and says
stock could not be loaded. The add/edit form (`core-suppliers.js`, shared with the Inventory tab)
is unchanged.

Follow-ups: purchase dates per lot (the compact list does not return `purchase_date`, so "last
bought" would need an API addition); linking an inventory line's free-text supplier to a supplier
record by id rather than by name.

## Checks

- `tests/e2e/test_suppliers_design.py`:
  - what you buy, and search by it; Clear search and filters;
  - gaps named and the Need details / Buying from now filters;
  - a row opens the details with `tel:` and `mailto:` links; Escape closes; an edit comes back
    with Saved;
  - On stock, not listed imports the missing name;
  - a failed load offers Try again;
  - dark theme text contrast ≥ 4.5 (fails on the old page at 1.02);
  - search box ≤ 44px tall (fails on the old page at 60px);
  - **CONCEPT ONLY**: each style at 390, 1024, 1440 and 1920 — no sideways scroll, the
    regions present, the details open in the pane (Style 2, wide) or the drawer.
- Existing: production pages layout, pages render, boosted navigation, compliance design (it
  boosts to `/core/suppliers`), `tests/test_core_suppliers.py`, `tests/test_navigation.py`.
- Screenshots: each style at 1440, 1024, 390 (and full height), 1920 and dark; search, nothing
  matches, filtered, details at desktop and phone, saved, add, load error, and after a boosted
  round trip.

## Review outcome

Six screenshot passes over all three styles (`~/.cache/workflow-engine-ui-shots/suppliers/01` … `06`):

1. **Pass 1.** Emails broke mid-word; on a phone an empty phone cell indented the email and left gaps;
   Style 3's group headings picked up the global `h3` size; "All" highlighted by default; "and 1
   more" instead of the one name; the save confirmation landed off-screen.
2. **Pass 2.** After a save the drawer gave no sign it had saved; a hover from the previous scenario
   showed in the shots.
3. **Pass 3.** Style 2's save scrolled its pane under the top bar; Style 3's cards were cramped on
   a phone (card padding inside card padding).
4. **Pass 4.** Style 1 clean. Style 2's error state showed an empty details card; Style 3's error
   state left "At a glance" empty.
5. **Pass 5.** Style 2 on a phone still highlighted a selection it was not showing.
6. **Pass 6.** No defects found in any style.
