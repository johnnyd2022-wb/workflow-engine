# Returns, credit notes and duty

How Biz-E handles goods that come back from a customer (go-live item GL-P01). It has one rule:

> **Money, goods and duty are three separate records.** A credit note doesn't prove stock came
> back, and stock coming back doesn't prove Customs owes you duty. Each one is recorded on its
> own, and they are linked so an auditor can follow one to the next.

| Record | Where it comes from | What it changes |
|---|---|---|
| **Credit note** (money) | Xero, synced with your invoices (`ACCRECCREDIT`) | Net sales on the Sales overview. Never stock. |
| **Customer return** (goods) | You record it: Sales → Overview → *Did stock come back?*, or a customer's invoice → *Record a return* | Stock: back into the batch it was sold from, onto quality hold, or written off as waste. |
| **Possible duty credit** (duty) | Automatic, from a return that put stock back inside the licensed area | A *possible credit* line on the excise draft (Compliance → Customs). It's never claimed for you. |

## The cases

**Partial or full credit, goods came back in good condition**

1. Raise the credit note in Xero as usual. After the next sync, the credited product shows under
   *Did stock come back?*
2. Enter how many came back, choose **Fine: back into stock**, the date received and **where it
   was received** (bond or a duty-paid area such as the shop), then press **Record return**.
3. Received where the batch is, the goods go back into the batch the sale came from (Biz-E finds
   the sale line on the credited invoice). Received anywhere else, or when Biz-E can't tell the
   batch, they become a new lot at that place, carrying the batch number so the trace reads through.
4. If they were received into the licensed area (bond), the excise draft for that month lists them
   as a possible credit. That's decided by where they were *received*, not where the lot is moved
   later. Decide with Customs whether to claim it.

From a customer's page you can do the same without a credit note: open the invoice, press **Record a
return**, pick the product (Biz-E shows how many of each sale line can still come back) and save.
The customer's **Returns** list shows every return and what happened to it.

**Damaged goods**

Do the same, but choose **Damaged: back on quality hold**. The goods become a lot of their own
on quality hold (GL-P02) with the note as the reason. They can't be used, sold or dispatched until
an admin releases the hold with a note. If you write them off, record the lot as waste.

**Goods destroyed or kept by the customer**

- Destroyed (by the customer, a carrier or you on arrival): choose **Destroyed: nothing back**.
  The return is recorded as a lot and immediately written off, so the loss is on the wastage register
  with the reason "Customer return destroyed". No duty credit is listed.
- Kept by the customer, or a price-only credit: use **Credit only · no goods** with a note. The
  credit note stays and nothing else changes.

**A credit for more lines than came back**

Record each part separately: say 2 of 3 back now and 1 later. The line stays on the list until
what came back covers the credited quantity, or someone records **Credit only** for the rest
(after a partial return that means "no more goods are coming"; the record keeps how many did come
back). Biz-E refuses to record more back than was credited, or more than was sold on a sale line.

**Voided or deleted invoice**

Nothing to record. When Xero voids or deletes an invoice, the sync already puts the stock back
into the exact batch it came from, and the sale leaves the excise draft (or, once that period is
lodged, it appears as an adjustment in the next one).

**Re-selling returned stock**

Sell it as normal. A sale from a lot inside the licensed area is a removal again, with duty
again, which is why the earlier return was listed as a possible credit.

**Goods back with no credit note** (a swap, a breakage collected by a rep)

Open the invoice on the customer's page and press **Record a return**. If there's no invoice at
all, the API takes a return with just a product name (`POST /api/crm/returns` with
`product_name`), which goes into a new lot of that product.

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
