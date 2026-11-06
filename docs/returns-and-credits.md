# Returns, credit notes and duty

How Biz-E handles goods that come back from a customer (go-live item GL-P01). It has one rule:

> **Money, goods and duty are three separate records.** A credit note doesn't prove stock came
> back, and stock coming back doesn't prove Customs owes you duty. Each one is recorded on its
> own, and they are linked so an auditor can follow one to the next.

| Record | Where it comes from | What it changes |
|---|---|---|
| **Credit note** (money) | Xero, synced with your invoices (`ACCRECCREDIT`) | Net sales on the Sales overview. Never stock. |
| **Customer return** (goods) | You record it: Sales → Overview → *Did stock come back?* | Stock: back into the batch it was sold from, onto quality hold, or nothing. |
| **Possible duty credit** (duty) | Automatic, from a return that put stock back inside the licensed area | A *possible credit* line on the excise draft (Compliance → Customs). It's never claimed for you. |

## The cases

**Partial or full credit, goods came back in good condition**

1. Raise the credit note in Xero as usual. After the next sync, the credited product shows under
   *Did stock come back?*
2. Enter how many came back, choose **Fine: back into stock** and the date received, then press
   **Record return**.
3. Biz-E puts the goods back into the batch the sale came from (it finds the sale line on the
   credited invoice). If it can't tell which batch, they go into a new lot of that product.
4. If they came back into the licensed area (bond), the excise draft for that month lists them
   as a possible credit. Decide with Customs whether to claim it.

**Damaged goods**

Do the same, but choose **Damaged: back on quality hold**. The goods become a lot of their own
on quality hold (GL-P02) with the note as the reason. They can't be used, sold or dispatched until
an admin releases the hold with a note. If you write them off, record the lot as waste.

**Goods destroyed or kept by the customer**

- Destroyed (by the customer, a carrier or you on arrival): choose **Destroyed: nothing back**.
  The return is recorded but no stock changes and no duty credit is listed.
- Kept by the customer, or a price-only credit: use **Credit only · no goods** with a note. The
  credit note stays and nothing else changes.

**A credit for more lines than came back**

Record each part separately: say 2 of 3 back now and 1 later. The line stays on the list until
what came back, or a "credit only" decision, covers the credited quantity. Biz-E refuses to
record more back than was credited.

**Voided or deleted invoice**

Nothing to record. When Xero voids or deletes an invoice, the sync already puts the stock back
into the exact batch it came from, and the sale leaves the excise draft (or, once that period is
lodged, it appears as an adjustment in the next one).

**Re-selling returned stock**

Sell it as normal. A sale from a lot inside the licensed area is a removal again, with duty
again, which is why the earlier return was listed as a possible credit.

**Goods back with no credit note** (a swap, a breakage collected by a rep)

The API takes a return without a credit-note line (`POST /api/crm/returns` with `product_name`).
It goes into a new lot of that product. There's no screen for this yet, so ask support to
record it until there is.

## What the records show

- **The credit note:** in Sales, with its lines and any *credit only* decision (who, when, why).
- **The return:** in `GET /api/crm/returns` and the audit log (`customer_return_recorded`), with
  the credit-note line, the invoice and sale line, the batch it went back into, and any hold.
- **The stock:** the lot's history shows "Sale reversed" (back into its batch) or a new lot with
  `customer_return` in its details. A damaged lot also shows "Put on quality hold: Returned
  damaged…".
- **The duty:** the excise draft's possible-credit lines read "Customer return: <product>
  (<condition>)".

This describes how Biz-E records returns. It isn't tax advice: check duty refunds and drawback
with NZ Customs.
