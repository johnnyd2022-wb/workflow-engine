# Customs licences and areas (Premises) redesign plan

**The page answers:** which of our stock areas sit inside a Customs-licensed area, under which licence, and until when?

## What is wrong today

Observed in the `00-before` screenshots (a seeded distillery with a bond store, five stock areas, three Customs licences, one of them ended):

- **No house layout:**
  - a blue underlined "Back to Customs" link, then an unstyled heading;
  - no header actions, and nothing like Customs or NP3 beside it.
- **The forms come first:** "Register a licence" and "Assign a licensed area" sit open at the top every visit. The register starts below the fold on a laptop, and after 1,000 px on a phone.
- **No answer:**
  - licences and areas are two plain lists;
  - nothing says whether an area is licensed today;
  - an ended licence sits among the current ones with "(ended)" only in its name;
  - nothing shows the cellar door shop has never been inside a licensed area.
- **ISO dates** ("2024-11-23 to ongoing").
- **The wrong tab:**
  - the page is about Customs, yet the Compliance **Overview** tab lights up;
  - the breadcrumb reads "Compliance / Premises" while the page calls itself "Customs licences and areas".

## What other products do

| Source | Pattern | What it changes here |
|---|---|---|
| Sovos ShipCompliant licence management (comparable) | A register of licences with expiry alerts well ahead of the date | Every licence and area carries "Ends in 45 days" or "Ended 28 Mar 2026" in words |
| RenewAlert (comparable) | A hierarchy: each site sees its own deadlines, and the business sees all of them | Style 2 groups areas under their site |
| Expiration Reminder (comparable) | One database of every permit, with documents attached | Each licence and area shows its document reference |
| Gantt and timeline views in project tools such as Linear's project timeline (craft) | Bars across months with today marked; gaps and overlaps show at a glance | Style 3's coverage timeline |
| GOV.UK summary card (pattern) | A card per item with key facts, and rows for what belongs to it | Style 1: a card per licence listing the areas it covers |

**Looked for but not found:** a Customs-specific (CCA) register in any product. The NZ Customs guidance describes the licence, not a screen.

## Three directions to choose from

| | Style 1: By licence | Style 2: By place | Style 3: Timeline |
|---|---|---|---|
| Idea | A card per licence listing the areas it covers, then what is outside any licence | Each site and its areas, each saying Licensed or Outside, with the licence and end date | A row per area and a bar per licence across the months, today marked; licences below |
| Taken from | Sovos register, GOV.UK summary cards | RenewAlert's per-site view | Project timelines and Gantt bars |
| Best at | Matching the paperwork Customs issued | "Is the stock in this room under bond?" | Seeing gaps, overlaps and what ends next |
| Gives up | You read every card to find one room | Licence details are a level down | Small text on a phone; exact dates are in the tooltip |

**All three share:**
- the house header, titled to match the Customs header link;
- the Customs tab and a Customs breadcrumb;
- **Register a licence** and **Assign an area** as dialogs, with the server's refusal shown inside the dialog;
- a one-line summary ("4 areas licensed under 2 current licences · CCA-OSS-0418 ends in 45 days · 2 areas outside");
- dates in words;
- ended licences folded away.

## Not in this change

- **APIs and rules:** the premises API and its validation are unchanged.
- **Customs stock:** still reads `inside_licensed_area` from Settings → Sites.
- **Follow-up:** editing or ending a licence or an area (the API only creates).

## Checks

- **Browser tests** in `tests/e2e/test_customs_premises_browser.py`:
  - the phone test now opens the dialogs;
  - new: a refused area shows its reason inside the dialog;
  - new: the summary and an area's status say what is licensed today;
  - CONCEPT ONLY: each style at phone, laptop and wall widths with no sideways scroll.
- **Changed tests:**
  - **Registry:** the page moves to the Customs tab, and the Premises tab (only a Compliance overview action) is removed.
  - **Overview actions:** `test_workspace_overviews` checks Tools in its place.
- **Screenshots:**
  - every style at laptop (first screen and full page), phone, wall and dark;
  - both dialogs and a refused area;
  - ended licences opened;
  - arriving from the Customs header twice;
  - empty and failed loads.

## Chosen: Style 1, By licence

Picked by the founder on 2026-10-25. Styles 2 (By place) and 3 (Timeline) are deleted with the switch and their CONCEPT ONLY tests. Each licence lists its areas, and what is outside a licensed area today ends the page.
