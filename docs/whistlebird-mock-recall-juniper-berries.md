# SIMULATED RECALL — toxic look-alike berries in juniper, two gin batches, 32 bottle stores

**Every document in this pack is part of a simulated recall. Nothing in it is real. Do not send any draft to a customer, NZFS or the public.**

- **Business:** Whistlebird Ltd
- **Policy followed:** [Whistlebird food and drink recall policy](whistlebird-recall-policy.md) (updated 30 September 2026)
- **MPI guidance followed:** [Simulated Recall Guidance for Food Businesses](https://www.mpi.govt.nz/dmsdocument/50630-Simulated-Recall-Guidance-For-Food-Businesses) and MPI's simulated recall checklist
- **System used to trace:** Biz-E (our own system): supplier lot to production to gin batches to Xero sales to customers
- **Pack prepared:** 30 September 2026
- **Led by:** Johnny Dempsey. Johnny Dempsey and Nikolai Scott are both recall decision makers with equal authority.
- **Status:** completed 30 September 2026 as a desk-based exercise led by Johnny Dempsey. All steps below were worked through in one session that day; individual step times were not recorded. The next exercise is due by 30 September 2027.

All batch numbers, lot numbers, quantities, stores and lab figures below are invented for the exercise and use the prefix `SIM-`, so they cannot be confused with real batches. The store names are placeholders; real names and contacts are in Xero and Biz-E.

## 1. The scenario

**Problem (chemical hazard).** A lot of dried juniper berries is found to contain berries from a toxic look-alike plant, savin juniper (*Juniperus sabina*). Savin is poisonous and is not a gin botanical. Its oil is volatile, so we cannot assume it is removed when we distil.

**Why this one.** It could really happen here. We buy wild-harvested dried berries, they go into every gin, and the gin is sold through bottle stores that sell on to the public. MPI asks for a worst case for the business and a consumer-level recall where possible. This is one: the bottles are already on shelves in 32 stores around the country and we cannot see who has bought them.

**Back-story.**

- **Day −70:** 10 kg of dried juniper berries (supplier lot `SIM-JB-14`, two 5 kg bags) are received and booked into Biz-E.
- **Day −56:** gin batch `SIM-G-201` is made (500 bottles of 700 mL) using 2.5 kg of the berries.
- **Day −35:** gin batch `SIM-G-202` is made (500 bottles) using another 2.5 kg.
- **Day −50 to Day −12:** the gin is invoiced in Xero and delivered to bottle stores.
- **Day 0, 08:40:** our supplier emails to say another of their customers had the same lot tested and savin berries were found. They suspect a mix-up when the pickers' bags were combined at the collection point. They tell us to stop using the lot.

**Other causes we would have to rule out** (an investigation does not assume the first answer):

| Possible cause | Why it is plausible | How we would check |
|---|---|---|
| Toxic look-alike berries mixed in (this scenario) | Wild harvest, bags combined before export | Lab identification of berries; supplier's harvest and packing records |
| Pesticide or fumigant residue | Dried botanicals are often treated in storage or transit | Ask for the supplier's certificate of analysis; residue test on retained berries |
| Mould toxins (aflatoxin, ochratoxin A) | Damp storage or slow drying | Mycotoxin test; look at the berries and the store |
| Heavy metals | Soil or drying equipment | Metals test on berries and on the finished gin |
| Mix-up or cross-contamination at the supplier's packing | Shared packing line | Supplier's packing records and their other customers |

Mould toxins and metals stay mostly in the still residue, while a volatile oil can come through into the spirit. That is why the lab is asked to test the gin as well as the berries.

## 2. Supporting information (released to the people running the exercise)

**Simulated email from the supplier, Day 0, 08:40.** *SIMULATED RECALL.* "Another customer had our lot SIM-JB-14 tested and a lab found savin juniper berries in it. Please stop using it and tell us how much you have used and where the product went. A copy of the lab report is attached. We are still working out how it happened."

**Simulated lab summary, Day 1, 14:00 (attached to the supplier's follow-up).** *SIMULATED RECALL.* Berries from both 5 kg bags of lot SIM-JB-14 examined under the microscope: savin juniper berries found in both, about 10% by weight in the worse bag. The supplier did not test finished gin. Whistlebird's retained sample of each gin batch goes to a lab for a volatile oil screen.

## 3. Tracing it in Biz-E

| Stage in Biz-E | What we looked at | Result |
|---|---|---|
| Inventory | Juniper berries, supplier lot SIM-JB-14 | Received Day −70, 10 kg, two bags. 5 kg used, 5 kg left. |
| Source map, then the lot | Trace forward from the supplier lot, steps listed in process order | Two production runs used it: SIM-G-201 and SIM-G-202. Nothing else. |
| Source map, **Recall** tab, **Recall mode** on | Header (product, batch, ABV, bottling date) and the summary line | `834 bottles sold · 32 customers · 120 bottles on hand` |
| Recall customer table | Customer, quantity, invoices, sale dates, primary contact, phone, email, address | 32 rows (section 3.1), each with contact details. |
| **Export CSV** and **Print / Save PDF** | The recall record | The CSV is the contact list for section 7.3; the PDF goes in the evidence pack. |
| Cross-check | Start from store 17's invoice and trace backward | Lands on both batches and on lot SIM-JB-14. |

Stock on hand in Biz-E (120 bottles) is what goes on hold. Retained and QC samples, staff and marketing bottles and the tasting bottles are accounted for in section 8.

### 3.1 Affected bottles by customer (from the Biz-E recall screen)

| # | Customer | SIM-G-201 | SIM-G-202 | Total | Invoices | Sale dates |
|---|---|---|---|---|---|---|
| 01 | Bottle store 01 (Ponsonby, Auckland) | 36 | — | 36 | SIM-INV-4101 | Day -50 |
| 02 | Bottle store 02 (Mt Eden, Auckland) | 30 | — | 30 | SIM-INV-4102 | Day -49 |
| 03 | Bottle store 03 (Albany, Auckland) | 30 | — | 30 | SIM-INV-4103 | Day -48 |
| 04 | Bottle store 04 (Manukau, Auckland) | 24 | — | 24 | SIM-INV-4104 | Day -47 |
| 05 | Bottle store 05 (Hamilton) | 24 | — | 24 | SIM-INV-4105 | Day -46 |
| 06 | Bottle store 06 (Tauranga) | 18 | — | 18 | SIM-INV-4106 | Day -45 |
| 07 | Bottle store 07 (Rotorua) | 18 | — | 18 | SIM-INV-4107 | Day -44 |
| 08 | Bottle store 08 (Taupō) | 12 | — | 12 | SIM-INV-4108 | Day -43 |
| 09 | Bottle store 09 (Napier) | 12 | — | 12 | SIM-INV-4109 | Day -42 |
| 10 | Bottle store 10 (Hastings) | 12 | — | 12 | SIM-INV-4110 | Day -41 |
| 11 | Bottle store 11 (Gisborne) | 12 | — | 12 | SIM-INV-4111 | Day -40 |
| 12 | Bottle store 12 (New Plymouth) | 12 | — | 12 | SIM-INV-4112 | Day -39 |
| 13 | Bottle store 13 (Palmerston North) | 12 | — | 12 | SIM-INV-4113 | Day -38 |
| 14 | Bottle store 14 (Masterton) | 36 | 36 | 72 | SIM-INV-4114, SIM-INV-4114B | Day -37, Day -30 |
| 15 | Bottle store 15 (Te Aro, Wellington) | 30 | 30 | 60 | SIM-INV-4115, SIM-INV-4115B | Day -36, Day -29 |
| 16 | Bottle store 16 (Petone, Lower Hutt) | 30 | 24 | 54 | SIM-INV-4116, SIM-INV-4116B | Day -35, Day -28 |
| 17 | Bottle store 17 (Miramar, Wellington) | 24 | 24 | 48 | SIM-INV-4117, SIM-INV-4117B | Day -34, Day -27 |
| 18 | Bottle store 18 (Karori, Wellington) | 24 | 18 | 42 | SIM-INV-4118, SIM-INV-4118B | Day -33, Day -26 |
| 19 | Bottle store 19 (Nelson) | 18 | 18 | 36 | SIM-INV-4119, SIM-INV-4119B | Day -32, Day -25 |
| 20 | Bottle store 20 (Blenheim) | — | 36 | 36 | SIM-INV-4120 | Day -24 |
| 21 | Bottle store 21 (Christchurch Central) | — | 30 | 30 | SIM-INV-4121 | Day -23 |
| 22 | Bottle store 22 (Riccarton, Christchurch) | — | 30 | 30 | SIM-INV-4122 | Day -22 |
| 23 | Bottle store 23 (Papanui, Christchurch) | — | 24 | 24 | SIM-INV-4123 | Day -21 |
| 24 | Bottle store 24 (Timaru) | — | 24 | 24 | SIM-INV-4124 | Day -20 |
| 25 | Bottle store 25 (Queenstown) | — | 24 | 24 | SIM-INV-4125 | Day -19 |
| 26 | Bottle store 26 (Wānaka) | — | 18 | 18 | SIM-INV-4126 | Day -18 |
| 27 | Bottle store 27 (Dunedin Central) | — | 18 | 18 | SIM-INV-4127 | Day -17 |
| 28 | Bottle store 28 (Mosgiel, Dunedin) | — | 18 | 18 | SIM-INV-4128 | Day -16 |
| 29 | Bottle store 29 (Invercargill) | — | 18 | 18 | SIM-INV-4129 | Day -15 |
| 30 | Bottle store 30 (Whangārei) | — | 12 | 12 | SIM-INV-4130 | Day -14 |
| 31 | Bottle store 31 (Kāpiti Coast) | — | 12 | 12 | SIM-INV-4131 | Day -13 |
| 32 | Bottle store 32 (Whanganui) | — | 6 | 6 | SIM-INV-4132 | Day -12 |
| | **Total** | **414** | **420** | **834** | | |

Quantities are whole cartons of six. Stores 14 to 19 took both batches.

## 4. Checklist (MPI format)

Each step is linked to the section of the [recall policy](whistlebird-recall-policy.md) it tests. Policy §5 (test the procedure) is met by this exercise as a whole.

| Step | Task | Detail and result | Recall policy | Who | Date |
|---|---|---|---|---|---|
| | Record the report of the problem | Supplier email received, Day 0 08:40. Lot SIM-JB-14. Notified by the supplier. | §1 Investigate and contain | Johnny Dempsey | 30 Sep 2026 |
| 1 Investigate | Tell production and sales and invite them to take part | Everyone who handles production, sales or communications told this is a simulated recall. | §1 Investigate and contain | Johnny Dempsey | 30 Sep 2026 |
| | Decide what to investigate and in what order | Remaining 5 kg of berries put on hold. Lot traced in Biz-E. Supplier asked for their records and lab report. Retained gin samples sent to a lab. | §1 Investigate and contain | Johnny Dempsey | 30 Sep 2026 |
| | Use records to find the affected products | Biz-E source map from lot SIM-JB-14: batches SIM-G-201 and SIM-G-202 (1,000 bottles). | §1 Investigate and contain | Johnny Dempsey | 30 Sep 2026 |
| | Use records to find where all of it is | Biz-E Recall tab: 32 customers, 834 bottles, 120 on hand. CSV exported. The rest accounted for in section 8. | §1 Investigate and contain | Johnny Dempsey | 30 Sep 2026 |
| | Cross-check the trace | Traced backward from store 17's invoice to the same lot. | §1 Investigate and contain | Johnny Dempsey | 30 Sep 2026 |
| | Test the on-hold process | Stock labelled **ON HOLD — DO NOT USE OR SELL**, moved to a locked or taped-off area, quantities recorded (120 bottles and 5 kg of berries). | §1 (hold and label stock) | Johnny Dempsey | 30 Sep 2026 |
| 2 Inform | Draft the email to the NP3 verifier or NZFS | Section 7.1. Not sent. | §2 Inform and assess | Johnny Dempsey | 30 Sep 2026 |
| | Optional: draft precautionary emails to customers and the supplier | Section 7.3. Not sent. | §2 Inform and assess | Johnny Dempsey | 30 Sep 2026 |
| 3 Assess | Tell whoever does technical assessment and decisions | Johnny Dempsey led the assessment as a recall decision maker. | §2 Inform and assess | Johnny Dempsey | 30 Sep 2026 |
| | Complete the risk assessment, headed SIMULATED RECALL | Section 5, on MPI's risk assessment form. | §2 (risk assessment) | Johnny Dempsey | 30 Sep 2026 |
| | Decide whether to recall, the level, which batches, and why | Section 6. | §2 (decision; either decision maker can authorise) | Johnny Dempsey | 30 Sep 2026 |
| 4 Check | Draft the email checking the decision and disposal plan with NZFS, with the risk assessment attached | Section 7.2. Not sent. Real recall: within 24 hours of the decision. | §3 (NZFS within 24 hours) | Johnny Dempsey | 30 Sep 2026 |
| 5 Communicate | Tell anyone who handles communications | Whoever looks after social media and the website told. | §3 Check the decision and communicate | Johnny Dempsey | 30 Sep 2026 |
| | Draft a point-of-sale notice (consumer-level) | Section 7.4. Not sent. | §3 Check the decision and communicate | Johnny Dempsey | 30 Sep 2026 |
| | Draft emails to the 32 impacted businesses | Section 7.3, made from the Biz-E CSV. Not sent. | §3 Check the decision and communicate | Johnny Dempsey | 30 Sep 2026 |
| | Draft consumer communications | Section 7.5 and 7.6. Not published. | §3 Check the decision and communicate | Johnny Dempsey | 30 Sep 2026 |
| 6 Audit | Collect the reconciliation | Section 8. All 1,000 bottles accounted for, including the 6 from an unrecorded tasting. | §4 Reconcile, audit and close | Johnny Dempsey | 30 Sep 2026 |
| | Optional: complete the recall audit form | Attached to this record. | §4 Reconcile, audit and close | Johnny Dempsey | 30 Sep 2026 |
| | Review and set corrective actions | Section 10. | §4 and §5 (review, corrective actions) | Johnny Dempsey | 30 Sep 2026 |

## 5. Risk assessment — SIMULATED RECALL

- **Product and who drinks it:** Whistlebird gin, 700 mL, batches SIM-G-201 and SIM-G-202. Sold to adults, including people who may be pregnant or unwell.
- **Hazard and likely harm:** a toxic look-alike berry (savin juniper) may have been distilled into the gin. Savin is documented as poisonous and as unsafe in pregnancy. The level in the finished gin is unknown, and the volatile oil can carry into a spirit.
- **Source and time window:** supplier lot SIM-JB-14, received Day −70, used on Day −56 and Day −35. Gin delivered Day −50 to Day −12.
- **Affected lots and quantity:** two batches, 1,000 bottles. 120 on hold at Whistlebird, 834 with 32 bottle stores, 12 retained samples, 28 with staff and marketing, 6 at an unrecorded trade tasting.
- **Where it is now:** section 3.1 and section 8. The 834 bottles at stores may already have been sold to consumers. We do not know who bought them.
- **What we do not know:** the amount of toxic material in the gin and how many bottles stores have already sold.
- **Advice sought:** NZFS and our verifier (**0800 00 83 33**, **Food.Recalls@mpi.govt.nz**).

## 6. Decision

- **Decision:** consumer-level recall of Whistlebird gin batches SIM-G-201 and SIM-G-202, and a hold on the remaining berries from lot SIM-JB-14.
- **Why:** the hazard is a poison, it cannot be ruled out of the finished gin without a lab result, and 834 bottles are already in 32 stores where members of the public can buy them. Waiting for results before acting would leave people exposed. If the lab later shows the gin is clear, the recall can be closed and stock released, recorded as a separate decision.
- **Made by:** Johnny Dempsey. Either Johnny or Nikolai can authorise a recall decision (policy §2).
- **Held stock:** not released until its safety is established and the release is recorded.

## 7. Draft communications (none of these are sent)

### 7.1 To the NP3 verifier or NZFS — inform

> **SIMULATED RECALL — do not send**
> Subject: Possible recall — Whistlebird gin, juniper berry lot SIM-JB-14
>
> Our juniper supplier has told us that lot SIM-JB-14 contains berries from savin juniper (*Juniperus sabina*), a toxic look-alike. The lot was received on [date]. We used 5 kg in two gin batches, SIM-G-201 and SIM-G-202 (1,000 bottles of 700 mL). 120 bottles and 5 kg of berries are on hold. The rest went to 32 bottle stores (834 bottles). We traced this in our system today. We have sent retained samples to a lab and asked the supplier for their records. We are assessing the risk now and will send the assessment shortly. Please tell us if you want anything else. Johnny Dempsey / Nikolai Scott, Whistlebird Ltd.

### 7.2 To NZFS — check the decision and disposal plan (risk assessment attached)

> **SIMULATED RECALL — do not send**
> Subject: Recall decision — Whistlebird gin SIM-G-201 and SIM-G-202
>
> We have decided on a consumer-level recall of Whistlebird gin batches SIM-G-201 and SIM-G-202 because of possible savin juniper in the juniper berries used. The risk assessment is attached. On hold: 120 bottles. With bottle stores: 834 bottles across 32 stores (list attached). We do not sell direct to the public for these batches, so we cannot contact consumers ourselves and propose a point-of-sale notice in every store plus our website and social media. We will keep returned stock segregated and hold it until you confirm whether it is to be destroyed or returned to the supplier. Please check the recall level, the notice and our plan, or tell us what to change.

### 7.3 To each bottle store (one email per store, made from the Biz-E export)

> **SIMULATED RECALL — do not send**
> Subject: Product recall — please stop selling Whistlebird gin SIM-G-201 and SIM-G-202
>
> We are recalling two batches of Whistlebird gin because the juniper berries used may include a toxic look-alike berry. Please stop selling the batches below, take them off the shelf and out of your stock room, and keep them separate and labelled. Please put the attached notice up where the gin was displayed. Reply today to confirm how many bottles you have of each batch and how many you have already sold. We will arrange collection or tell you how to dispose of them. Our records show you received: SIM-G-201 — [n] bottles; SIM-G-202 — [n] bottles (invoices [numbers], delivered [dates]). Phone us on [number] if you need help. Johnny Dempsey / Nikolai Scott.

### 7.4 Point-of-sale notice (for all 32 stores)

> **SIMULATED RECALL — do not send**
> **PRODUCT RECALL — WHISTLEBIRD GIN.** Batches SIM-G-201 and SIM-G-202 (700 mL). The juniper berries used may include a toxic look-alike berry. **Do not drink this gin.** Return it to where you bought it for a refund, or contact Whistlebird on [number] or [email]. If you have drunk any and feel unwell, call Healthline on 0800 611 116 or see a doctor.

### 7.5 Message for the website and social media

> **SIMULATED RECALL — do not publish**
> We are recalling two batches of Whistlebird gin (SIM-G-201 and SIM-G-202, 700 mL). The berries used may include a toxic look-alike berry. Please don't drink it. The batch number is on the back label. Take it back to the store where you bought it for a refund, or email us. If you drank any and feel unwell, call Healthline on 0800 611 116. We're sorry.

### 7.6 Short media release

> **SIMULATED RECALL — do not release**
> Whistlebird recalls two batches of gin. Whistlebird Ltd is recalling Whistlebird gin batches SIM-G-201 and SIM-G-202 (700 mL) because the juniper berries used may include berries from a toxic look-alike plant. The gin was sold through bottle stores around New Zealand. Customers should not drink it and should return it to the store for a refund. Contact [details].

## 8. Reconciliation (recall policy §4)

| | SIM-G-201 | SIM-G-202 | Total |
|---|---|---|---|
| **Produced** | 500 | 500 | **1,000** |
| On hold at Whistlebird (Biz-E stock on hand) | 60 | 60 | 120 |
| Retained and QC samples | 6 | 6 | 12 |
| Staff, marketing and tastings | 14 | 14 | 28 |
| Sold to trade customers (32 stores) | 414 | 420 | 834 |
| Trade tasting not recorded in inventory | 6 | 0 | 6 |

120 + 12 + 28 + 834 + 6 = 1,000. The 6 bottles from SIM-G-201 did not show in Biz-E at first. They were traced to a trade tasting that had not been recorded in inventory, which is a finding in section 10.

Berries: 10 kg received = 5 kg used in batches + 5 kg on hold.

MPI's reconciliation lines: amount produced 1,000; other (samples, staff, tastings) 46; with trade customers 834; unaccounted for 0 after the tasting was traced. Bottle stores also report how many bottles they have already sold, which is the amount that may be with consumers.

## 9. Targets for the next exercise

Step times were not recorded in this exercise. Record them against these targets in the next one:

- Lot traced to both batches and the full customer list exported from Biz-E within 1 hour of the report.
- All 32 stores contacted within 4 hours.
- Drafts to the verifier or NZFS ready within 24 hours of the decision.
- Reconciliation adds up to 100% of produced bottles, with nothing left unexplained.

## 10. Review (recall policy §4 and §5)

| | |
|---|---|
| **Date run and who took part** | 30 September 2026. Desk-based exercise led by Johnny Dempsey. |
| **Decision reached** | Consumer-level recall of Whistlebird gin batches SIM-G-201 and SIM-G-202, and a hold on the rest of juniper lot SIM-JB-14. |
| **Justification** | The hazard is a poison that cannot be ruled out of the gin without a lab result, and 834 bottles were already in 32 bottle stores where the public can buy them. |
| **What went well** | Biz-E traced the juniper lot to both batches and listed every store, with quantities, invoices and contact details, from the Recall screen. The drafts to NZFS, the stores and the public were all prepared on the day. |
| **What did not go so well** | Six bottles were missing from the inventory records because a trade tasting had not been recorded. Step times were not recorded. |

**Corrective and preventive actions**

| Action | Who | When |
|---|---|---|
| Ask the juniper supplier for a certificate of analysis and botanical identification for each lot before we use it | Johnny Dempsey | 31 December 2026 |
| Check and photograph every lot of juniper on receipt against a reference sample | Nikolai Scott | From the next delivery |
| Keep a retained sample of every botanical lot | Nikolai Scott | From the next delivery |
| Record every tasting, event and gift bottle in the inventory | Johnny Dempsey and Nikolai Scott | From 1 October 2026 |
| Decide who posts to the website and social media in a recall | Johnny Dempsey and Nikolai Scott | 31 October 2026 |
| Time each step in the next mock recall against the targets in section 9 | Johnny Dempsey and Nikolai Scott | Next exercise, by 30 September 2027 |

## Records to keep for the verifier

This pack, the Biz-E recall CSV and PDF, the completed checklist, the risk assessment, the decision record, the draft emails and notices, the reconciliation, the review and the corrective actions. Keep them with the NP3 evidence, as the recall policy says. Record any training given as a result in the staff competency register.
