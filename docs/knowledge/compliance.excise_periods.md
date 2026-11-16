---
topic: "compliance.excise_periods"
title: "Excise periods and drafts"
domain: "compliance"
summary: "Excise is drafted per lodgement period from recorded removals from the licensed area, not from invoices. A lodged period is frozen."
related_topics:
  - compliance.excise_position
  - compliance.cca_movements
  - inventory.sites_and_locations
  - sales.fifo_matching
related_operations:
  - compliant_compliant_api_get_excise_period
  - compliant_compliant_api_list_excise_periods
  - compliant_compliant_api_get_excise_position
features:
  - compliant
---
# Excise periods and drafts

## What it means

NZ Customs taxes alcohol **removed from the Customs-controlled (licensed) area**, not alcohol invoiced. A period's lines are built from removals:

- a sale matched to a lot that was in the licensed area, counted on the invoice date;
- stock moved from the licensed area to an outside location, counted on the move date. A later sale of that stock is not counted again.

Stock moved back inside is listed separately as a possible credit to raise with Customs. It is never claimed automatically. A sale to another business's CCA is a transfer, listed apart from the duty lines.

Duty per line is litres of alcohol (litres x ABV) times the rate in force at the start of the period, or litres of drink times a rate for some bands. The rate is the organisation's own, else the built-in Customs guide.

Periods are monthly, six-monthly or twelve-monthly.

## How the records relate

- A **lodged** period is a stored snapshot. A removal recorded afterwards, such as a late invoice, is carried into the next open period as an adjustment naming the period it belongs to.
- With several sites, each CCA licence has its own entry, chosen with `cca`.
- Lines with missing product setup appear as `problems`, and the entry is marked incomplete.

## Authoritative operations

- `compliant_compliant_api_get_excise_period`: one period's draft or lodged entry (`period` date, `cca`). Without `period` it returns the previous period.
- `compliant_compliant_api_list_excise_periods`: the current and last eleven periods with lodged status and due dates.
- `compliant_compliant_api_get_excise_position`: the wider position (see compliance.excise_position).

## Do not assume

- **Sales are not removals.** A sales-based excise estimate exists, but the period draft is the figure to lodge.
- **A draft is not tax advice and not lodged.** Check `status`.
- **An incomplete entry has no reliable total.** If `complete` is false or `problems` exist, say what is missing.
- **A nil return is not implied by no lines.**
