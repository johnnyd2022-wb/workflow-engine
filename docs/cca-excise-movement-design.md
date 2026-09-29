# CCA movement accounting integration

The next 7.1e/f slice uses the append-only transfer decision as the physical removal
fact. It must not create a second stock debit or classify a later sale of the same
receipt fragment as another removal. Source CCA identity, dated coverage, measured
volume/strength evidence, tariff/rate basis and accountable business are frozen at
dispatch. Partial receipts refer to the original fact; they do not create another tax
charge. Duty-paid return stock is not automatically credited or made duty-unpaid.

## Scope constraints

- Keep the operations gate off until global legacy excise drafts and sales allocations
  consume the same recorded tax status. The old location Boolean and location=None
  cannot identify a licensed area when multiple sites are enabled.
- An authorised CCA-to-CCA movement remains excise-unpaid; leaving CCA B for an
  unlicensed destination belongs to B's entry, not the originating CCA A.
- Unknown classification, duty basis, strength/volume evidence or ownership prevents
  opening the new removal path. A product-profile target ABV is not tested strength.
- Customer-owned raw material does not establish an order's duty payer or title to
  finished goods. Initially support producer-owned stock only. Contract order/duty
  linkage needs its separate trusted adapter.
- The legacy rate table explicitly describes rates per LAL. Never apply it to a
  tariff charged per litre of beverage. Levy/GST and other sources of removal are
  separate completeness requirements, not zero values.
- A transfer-only period projection cannot declare a nil return or claim a complete
  lodgement: sales, samples, destruction, corrections and other taxable uses also
  have to be accounted for.
- Preserve already-applied main migration history (custom_roles -> planner_demands
  -> contract_orders). Integrate future CCA/site siblings additively and test the
  deployed upgrade path as well as a fresh database.

## Primary references checked 30 September 2026

[Excise entries](https://www.customs.govt.nz/business/excise/excise-declarants/excise-entries)
sets out physical removals, consumption, loss/destruction and nil returns.
[Volume of alcohol rules](https://www.customs.govt.nz/business/excise/alcohol-and-excise/volume-of-alcohol-rules-summary-for-excise-declarants)
requires tested/verified strength and distinguishes LAL from beverage volume.
[Excise-unpaid movements](https://www.customs.govt.nz/business/excise/alcohol-and-excise/moving-products-excise-unpaid)
sets out movement authorities and OSS prior-approval requirements.

## Implemented prerequisite interface

`capture_spirits_removal_basis` returns a frozen `CapturedRemovalBasis(valid,
reason,evidence)` with canonical JSON. Its validity is distinct from movement
permission. It requires exact dated source CCA coverage, a matching active spirits
classification, a trusted producer-owner snapshot, documentary volume/testing
references and testing no later than dispatch. Only spirits over23% ABV, L/mL or
whole bottles/cans/kegs, and the existing explicitly LAL rate table are supported.
The applicable configured rate and all measurement values are copied into the
snapshot. Contract duty payer, levy and GST remain unknown. This helper does not
write stock, authorise a removal, commit, create a lodged return or automatically
persist tax evidence. That integration remains to be delivered.

The staff GET API `/api/compliant/nz-alcohol/excise/cca-movements` reads a bounded
[start,end) period from the immutable physical transfer ledger. It validates the
recorded identity/date/quantity and groups recognised excise-unpaid movements by the
source CCA. A partial receipt does not duplicate the dispatch. Missing or mismatched
proof is unresolved. The result always marks the entry incomplete, with unknown
nil-return/total-duty values and an explicit list of missing accounting sources.
It cannot replace the lodgement screen. Access requires the existing compliance
view permission and feature entitlement, and the organisation comes from the session.

## Next integration slice (still behind the site-operations release gate)

The transfer service now asks the configured module to prepare its duty context before
locking Org/Site/Inventory rows. For an output lot, this locks Step → Execution →
Contract Order, then the dispatch policy compares those facts with the locked source
lot. It refuses customer-licensee and customer-underbond orders until their actual
CCA authority is linked and verified. A customer-owned raw lot cannot enter this
finished-spirits path.

An explicit `home_consumption` authority can record a producer-liable, measured
spirits removal from a dated LMA/OSS to an area with no dated CCA coverage. The
dispatch stores its original measurement, rate, source CCA, physical lot, consignment
and actor in one immutable decision alongside the stock debit. Partial receipts copy
the original decision and do not create a second excise liability. The per-CCA
register shows only **observed excise duty** for these dispatches; it still says
`complete_lodgement=false`, `nil_return=null`, and `total_duty=null` because other
taxable sources, levy and GST are not yet reconciled. Its tax status means **excise
due**, not paid or lodged.

When multiple sites are enabled, the old location-based draft cannot be recorded as
lodged or as a nil return. Its preview displays an unresolved warning; historical
lodged snapshots remain visible. Operational site transfers are still off by default.
The remaining release work includes full per-CCA entries and lodgement, all removal
sources, customer contract duty authority, paid/returned stock treatment and
reconciliation with sales and stocktakes.
