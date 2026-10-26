# Tastings page design research — 26 October 2026

What the page must answer: where am I tasting next, who is going, what stock can I take,
and is that stock removal recorded for excise?

| Reference | Observed pattern | Consequence here |
|---|---|---|
| [Overproof Tastings](https://overproof.com/tastings/) | Scheduling, event details and mobile outcomes are one activation workflow. | A tasting detail contains schedule, stock dispatch and measured usage; the first screen leads with upcoming events. |
| [SevenFifty Sample Sheets](https://buyer.sevenfifty.com/static_pages/sample_sheets) | Products, account context and notes stay attached to the tasting history. | Keep product/batch lines and optional customer together with venue and rep; retain completed events. No external sharing in this scope. |
| [Repsly field execution](https://www.repsly.com/) | Field-team schedules and execution progress are distinct operational concerns. | Offer a preparation board direction for the person organising stock, distinct from a rep's date-first agenda. Public material does not establish a specific NZ duty treatment. |
| [Linear board layout](https://linear.app/docs/board-layout) | List and status board share data and actions; card properties are selectively visible. | Agenda and readiness board use the same data/detail; venue, time, rep and state suffice on cards. Put proof and accounting details in the drawer. |
| [Notion views](https://www.notion.com/help/views-filters-and-sorts) and [calendar](https://www.notion.com/en-gb/help/calendars) | Date/calendar, list and grouped board are views over the same records; detail can open beside the list. | A calendar direction leads with the week; every event still opens the same editable detail. Sales/Core share the same linked task projection. |
| [Carbon data table guidance](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines) | A toolbar contains global actions; expansion progressively reveals additional detail. | One primary scheduling action; compact filters; pool/removal evidence below the event list or behind detail, rather than a giant first-screen form. |

The references support workflow structure; they do not supply Flume's palette/typeface or
prove NZ tax compliance. The implementation uses the existing house tokens and Core stock
and NZ Alcohol accounting conventions. No live authenticated competitor interface was
available; this research uses their own public product/help material, not a claimed
hands-on benchmark.

Domain basis: [Customs and Excise Act 2018](https://www.legislation.govt.nz/act/public/2018/4/en/latest/),
section81 and Schedule3, distinguish removal for home consumption from merely scheduling
or selling; [Customs' alcohol/excise guidance](https://www.customs.govt.nz/business/excise/alcohol-and-excise)
links record-keeping and authorised excise-unpaid movements. This page records a physical
removal and its source evidence. It does not issue a venue licence, grant movement
permission or claim the return is lodged. For own-venue sampling, use the actual recorded
consumption/removal rather than moving the calendar appointment alone.

## Three structural directions

| | Style1: Agenda | Style2: Week | Style3: Preparation board |
|---|---|---|---|
| Idea | Date-grouped event rows; stock pool beside the agenda | Seven-day calendar leads; pool below | Workflow columns lead: planned, stock out, completed, cancelled |
| Research | Overproof + SevenFifty; quiet Linear list properties | Notion calendar + field-team scheduling | Linear board + Repsly execution |
| Best at | A rep looking for the next visit | Seeing the team's week and gaps | Preparing stock and closing outcomes |
| Gives up | Calendar gaps need a switch/link | Long titles need the shared detail | Dates are secondary within each status |

All three keep scheduling, stock/removal evidence, shared calendar links, filters, pool
reuse, measured usage, loading/error/empty states, phone/dark support and one shared
accessible detail. A concept switch is review-only; MR remains draft until a style is
chosen and the alternatives are deleted.

## Behaviour and deliberate limits

A booking can have no stock yet; dispatch requires at least one of at most twenty lines.
Planning removes nothing. Physical dispatch records its actual date, source batch, actor,
volume and frozen excise basis. Measured outcomes preserve plan notes and record separate
outcome notes. Tasting stock is a distinct mL ledger, including partly used bottles, never
Library stock. Reuse does not create another warehouse debit or removal.

Shared Sales and Production calendars carry one linked, date-only task on the NZ start
date. Its detail opens the timed tasting; changes go through Tastings to keep stock and
status consistent. This first version does not add a separate tasting-only calendar silo.

Not in this change: venue licence verification, POS/sales attribution, recurring bookings,
offline operation, automatic Customs filing/payment/remission, return-to-bond or amendments
to completed outcomes. Ambiguous coalesced prior-removal history requires review instead
of guessing a duty identity. Unknown duty classifications/rates stay visible as problems;
they cannot become a false complete/nil return.

## Checks

Real PostgreSQL tests cover permissions, tenant references, signed warehouse movements,
concurrent dispatch and pool reservations, replay, rollback, actual-date rates, partial
bottles, reuse, cancellation, immutable evidence and late captures. Browser checks drive
booking, stock-first search, dispatch and measured outcomes at desktop and phone sizes,
the shared calendar and boosted revisits, filters, errors and all three concept layouts.
The final runs also use a UTC host clock while retaining NZ event dates.

Visual review uses a realistic seven-event week with planned, stock-out, completed and
cancelled records, plus an unsampled 550 mL remainder. Each pass covers all three styles
at 390, 1440 and 1920 widths; busy/quiet, dark, detail, editor, empty, loading and error
states. Home and Suppliers are house-style references. Screenshots stay outside Git;
final images and the three-way comparison belong in the draft MR.

## Decision

Awaiting the founder's style selection. The MR remains draft until the two alternatives
and the review-only switch are removed and the selected layout is rechecked.
