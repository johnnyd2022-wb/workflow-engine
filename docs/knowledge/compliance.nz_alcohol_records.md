---
topic: "compliance.nz_alcohol_records"
title: "NZ alcohol compliance records"
domain: "compliance"
summary: "Records are evidence a person logs against a framework's controls. Only Customs litres of alcohol is worked out live from stock."
related_topics:
  - compliance.excise_periods
  - compliance.excise_position
  - inventory.stocktakes
related_operations:
  - compliant_compliant_api_list_records
features:
  - compliant
---
# NZ alcohol compliance records

## What it means

The NZ alcohol module organises compliance as **frameworks**, each a list of **controls**: Customs alcohol reconciliation, NP3 food control, Wine Standards, council trade waste, and liquor licensing. Which apply depends on the organisation's product types and settings.

A **record** is evidence logged against one control. Its type is `attestation`, `reading`, `lodgement`, `competency` or `incident`, and its status is `complete`, `failed`, `open` or `superseded`. It can carry a due date, an evidence file and references to Core records.

Each control has a state: `compliant`, `setup` (evidence or configuration still needed) or `attention` (an open or failed record, an overdue one, or a recorded value over its limit).

## How the records relate

- Only Customs production and wastage in litres of alcohol (LAL) is derived live from stock movements, using each product's ABV profile. Every other framework is evidence-led: the state reflects what people recorded.
- Excise, stocktakes and CCA movements are separate figures (compliance.excise_periods, compliance.excise_position, compliance.cca_movements).
- Council trade-waste limits come from the organisation's own consent, never from a general figure.

## Authoritative operations

`compliant_compliant_api_list_records` lists records, newest first, up to 200, optionally for one `framework`.

## Do not assume

- **A record is not proof of compliance.** It is what a person logged. Check the control's state and status.
- **No records means setup is needed, not failure.**
- **Do not state a legal requirement from this data.** The module records and drafts. It gives no legal advice.
- **Frameworks the organisation does not use are absent**, not failed.
