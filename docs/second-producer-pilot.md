# Second-producer pilot and pricing decisions

Preparation for plan 6.2 and 6.3. A completed checklist is evidence only after a real
brewery or winery has used it. No producer, session date or prices have been selected.

## Before booking

The founder selects a brewery or winery, the producer's owner/operator, and a single
session date. Agree which sales workflow they actually use (Xero or manually entered
sales), the appropriate compliance pack, and the real stock available at go-live.
Do not make linking Xero a prerequisite if they do not use it.

Use a release in which the source-to-sale dependencies have merged and CI has passed:
roles/2FA, whole units, go-live stock, matching, recall, stock integrity, excise and
Customs stocktake; include the relevant starter pack when plan 2.4 is available.
Finish production/test separation, backup scheduling and restore rehearsal before
onboarding real tenant data (0.1). Verify the nightly integrity timer is running (1.7).
Use a separate synthetic demo tenant for rehearsal.

Record the release SHA and prerequisite check results. Prepare one production process,
a supplier lot, its finished product/pack size, a customer and a sale. Use the producer's
normal units and actual method. Do not silently substitute the distillery example for
a brewery/winery process.

## Session

The participant operates the product. Start the clock when the participant begins
workspace setup; finish it when they can trace their first sale back to its source lot.
Record interruptions and their duration. Do not exclude facilitator help from the
elapsed time.

| Step | Participant action | Evidence to record |
| --- | --- | --- |
| Access | Sign in, enrol required 2FA and invite one staff member with the intended role | Role, successful login, unexpected denials or excess access |
| Go-live | Set the boundary date and count opening stock, including work already in progress | Go-live date, opening batch IDs, counted quantities/units |
| Process | Configure or adopt a suitable process; record the batch through its real steps | Process/execution IDs, manual changes, points needing help |
| Finished stock | Check quantity, pack size and ABV where applicable | Output batch ID, bottles/cans/kegs/cases and on-hand quantity |
| Sale | Record/import one real sale and use the chosen FIFO/hybrid/manual matching mode | Invoice/sale reference, matching mode, allocation status |
| Trace | Follow that sale backwards to production and supplier lot | Trace result, first-traced-sale timestamp and elapsed minutes |
| Recall | Trace the input forwards and export the affected customer list | Customer count, known missing contacts, CSV reviewed by participant |
| Compliance | Find the pack evidence and period excise draft relevant to this producer | Screens/exports located and any missing information |
| Stock count | On a synthetic rehearsal batch, resolve a mismatch as stock elsewhere or breakage | Expected/count values, explanation and completed count |

Do not create fictional discrepancies in their real stock to demonstrate a feature.
For real sales, preserve the actual invoice/customer and allocation evidence. Keep
sensitive customer exports in the tenant's authorised storage, not in this repository.

## Observation record

Copy this into the team's approved operating workspace and fill it during the session.

```text
Producer/type:
Participant and facilitator:
Session date/time/timezone:
Release SHA:
Go-live date:
Compliance pack / sales workflow / matching mode:
Started at:
First traced sale at:
Elapsed minutes (including help):
Process / execution / batch / sale references:
Participant independently found the source lot: yes/no
Recall export understood and checked: yes/no
Missing contact or compliance information:
Interrupted session / blocker:
Next session if unfinished:
```

For each point requiring help, record:

| Time / step | Participant's exact question or observed problem | Help given | Minutes | Owner / proposed plan item |
| --- | --- | --- | --- | --- |
| Pending session | | | | |

At the end, ask the participant to explain the trace and identify what they would do
if an affected customer had no phone/email. Record their explanation and remaining
questions; avoid replacing it with the facilitator's answer.

## Completion and follow-up

6.2 completes when this second producer reaches a traced sale in one sitting and their
questions are added as actionable plan items. A synthetic demo or an unfinished
session does not meet that condition. Assign owners to each gap, link evidence in the
operating workspace, and record the producer's permission for any testimonial. Only
then approve the landing-page rollout under the plan's Phase 6 ordering.

## Pricing decision sheet (6.3)

The inclusion model is already decided: Production, a compliance pack appropriate to
the producer, and the Xero sales link. The founder sets amounts and terms; the table
below does not create subscriptions or change entitlements.

| Component | Included work | Founder decision still needed |
| --- | --- | --- |
| Production | Processes, executions, inventory and source-to-sale tracing | Recurring price, billing unit and any limits |
| Compliance pack | The selected pack's evidence/checks and applicable alcohol workflows | Price by pack and whether sold separately or bundled |
| Xero sales link | Sales import and allocation/matching integration | Add-on price and supported-account terms |

Also decide currency, GST presentation, monthly/annual billing, onboarding/support
inclusions, trial terms, cancellation and any usage limits. Record decisions with the
founder and date before publishing numbers or charging a producer. Do not imply
regulatory approval or guaranteed compliance in a price description.

For each proposed offer, fill:

```text
Offer name:
Production included:
Compliance pack included:
Xero sales link included:
Recurring amount / currency / GST treatment:
Billing period / billing unit:
Limits (or explicitly none):
Onboarding and support:
Trial / cancellation terms:
Founder approval and date:
Subscription entitlement mapping checked:
```

6.3 stays open until the founder has approved prices/terms and the published offer
matches the actual subscription entitlements.
