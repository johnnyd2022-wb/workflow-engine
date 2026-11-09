# Wine compliance in Biz-E: build plan

**Status:** plan, 2026-11-09. Builds on the desk research in
[`nz-wine-producer-compliance-research.md`](nz-wine-producer-compliance-research.md) (!662).
**Goal (founder):** wine is its own compliance module inside NZ Alcohol, like spirits and beer.
When it's switched on, production flows pick up its constraints, so the winemaker just does the
work: every record the law expects is captured *as part of production*, in as few clicks as
possible. It should feel too easy.

This is not legal advice and the product never claims "MPI approved" or "compliant". It records
what happened, checks what can be checked mechanically, and names the operator decision where one
is needed (research §14, *Trust requirements*).

## 1. Cross-check of the research

I re-checked the facts the build enforces against primary or regulator sources (9 Nov 2026):

| Fact used by the build | !662 says | Checked | Build treatment |
|---|---|---|---|
| Variety / vintage / area claim needs ≥85% of the wine to meet it | Yes, Wine Regulations | MPI label guide: applies from vintage 2007; exports may follow the destination's rules instead | Enforced as a **check with an explained result**, never a silent block; export markets are out of scope for W1 |
| Small winemaker WSMP exemption: <20,000 L over 2 years, notified, no export | Yes | MPI: reg 19 of the Wine Regulations 2021; apply **before making wine**; valid 2 years; exempt wine can't be exported; random audits | Tracked as an operating status with an expiry date and a live 2-year volume meter |
| Added sulphites ≥10 mg/kg must be declared | Yes, Food Standards Code | Consistent with FSANZ Standard 1.2.3 | Label pre-flight item, driven by the SO₂ additions recorded in the cellar |
| Standard drinks = mL × ABV × 0.789 ÷ 10 | Yes | Consistent with FSANZ / the existing Tools calculator | Computed at bottling, never typed |
| Records kept 7 years; trace records within 24 hours | WSMP model | **Not independently confirmed** (search found no primary text) | Retention is a profile setting defaulting to 7 years; no deletion guard depends on it in W1 |
| Annual simulated recall | Yes | Consistent with the WSMP model | Reuses the recall drill from GL-P03 (!647); the Wine page shows when the last drill was |

Gaps in the research the plan adds: none legal. Two product points it understates: (a) wine
composition can be **derived** from the trace graph Biz-E already keeps (each step's
`actual_inputs` lists the lots and quantities it consumed), so nobody types a blend sheet; and
(b) the most-repeated typing at vintage is grower/variety/vintage at intake, which can be
**prefilled from the grower's last delivery**.

## 2. What exists today

- `nz_alcohol` already knows the product type `wine` (`presets.PRODUCT_TYPES`) and has a
  `wine-standards` framework with four generic controls (`catalogue.py`).
- Starter pack **Wine: intake to bottle** (intake → crush and press → ferment → cellar → bottle)
  and six winery templates (`process_templates`).
- The seam for "production inherits compliance": `WorkflowRule` providers
  (`compliant/platform/workflow_rules.py`) add prompts to a step and Core enforces
  `prompt_value` / `active_evidence` constraints at completion (`execution_routes.py`). ABV on a
  final product already works this way.
- Recall drills, quality holds, returns, CCA/excise and Customs entries are product-agnostic and
  already shipped.

What's missing is anything wine-specific behind the framework name.

## 3. Design

### 3.1 A wine module inside NZ Alcohol

`app/features/compliant/modules/nz_alcohol/wine/`:

| File | Owns |
|---|---|
| `roles.py` | What a production step *is* in winemaking: `intake`, `crush`, `ferment`, `cellar`, `blend`, `bottle`. Inferred from step and output names ("Grape intake", "Bottle"…), overridable per step in configuration. No migration on `steps`. |
| `rules.py` | `WineWorkflowRules`, a `WorkflowRule` provider appended by `NZAlcoholWorkflowRules` only when `wine` is in the org's product types. |
| `composition.py` | Walks a lot's `actual_inputs` back to intake lots and returns variety / vintage / region shares by volume, plus the 85% claim check. |
| `label.py` | Bottling pre-flight: ABV, standard drinks, sulphite declaration, fining-agent allergens, pregnancy warning, lot code, claims. |
| `wsmp.py` | Operating status: registered WSMP (plan, verifier, next verification) or small-maker exemption (start, expiry, 2-year litres vs 20,000). |

Spirits and beer keep NP1/2/3; wine gets the WSMP. `framework_applies` already routes `wine` to
`wine-standards`.

### 3.2 Production inherits the constraints (the "too easy" part)

Nothing new to learn: the winemaker records the step they were already recording, and the
compliance fields appear on it.

| Step role | Asked (required unless noted) | Saved clicks |
|---|---|---|
| Intake | Grower or block · Variety · Vintage · Region · Spray diary received (yes/no) | Vintage defaults to the current vintage; variety and region default from the grower's last delivery |
| Crush / ferment | Vessel (optional) | — |
| Cellar | SO₂ added (mg/L, optional) · Fining agent (none / egg / milk / fish / other, optional) | Defaults to "none" |
| Blend | Nothing: composition is computed | The whole blend sheet |
| Bottle | ABV (existing rule) · Bottle size (mL) | Standard drinks, sulphite statement and claim check are computed |

Constraints: intake can't complete without grower, variety and vintage (the trace and the 85%
check depend on them). Nothing else blocks production in W1; the pre-flight surfaces gaps on the
Wine page instead of stopping a bottling run.

### 3.3 Composition and claims

`composition(lot)` → `{variety: {"Sauvignon blanc": 0.92, …}, vintage: {...}, region: {...},
volume_basis, estimated}` weighted by quantity consumed at every step. Inputs that aren't wine
(yeast, nutrients, packaging) are excluded. Mixed units at one step fall back to equal weights and
mark the result `estimated` so the UI says so. A claim passes when one value is ≥85%.

### 3.4 Wine page (Compliance → Wine), Style 1

Shown when `wine` is a product type. The shared header with right-aligned actions: **Record
intake** (primary), Tools, Premises.

1. **Plan status card:** WSMP registered (plan, verifier, next verification) *or* exemption
   (expiry and a meter: litres made in the 2-year window out of 20,000 L, amber at 80%).
2. **Vintage at a glance:** intake lots this vintage, litres in tank, bottled.
3. **Label claims:** each finished or in-progress wine lot with its top variety, vintage and
   region and a pass, needs-review or can't-claim chip.
4. **Bottling pre-flight:** each bottled lot's checklist (standard drinks, sulphites, allergens,
   pregnancy warning, claims), with gaps first.
5. **Recall readiness:** the last recall drill date (from GL-P03) and a link to run one.

## 4. Delivery

| Stage | Scope | MR |
|---|---|---|
| **W1a** | Wine module: roles, rules, composition, label pre-flight, WSMP status service and API, plus tests | one MR with W1b |
| **W1b** | Wine page (Style 1, phone and desktop, light and dark), starter pack prompts updated, e2e and screenshots | one MR with W1a |
| W2 | Export: batch eligibility, eligible-volume balance, EES/official assurance refs, OMAR pre-flight | later, with a pilot winery |
| W3 | Grower declarations portal, offline vintage capture, cellar door / remote sale tasks, organic and SWNZ overlays | later, demand-led |

W2 and W3 wait on customer discovery (research §15 *Stage 0*): building export rules without a
winery checking them would be guessing.

## 5. Out of scope / decisions for the founder

- No export, OMAR or MPI Trade Certification work in W1.
- Retention defaults to 7 years but isn't enforced, because I couldn't confirm the period.
- Rules aren't effective-dated yet: the 85% and 10 mg/kg thresholds are constants with their
  source cited. Effective-dating comes with W2's rule calendar.

## 6. Requirement coverage (every requirement in the research → where Biz-E meets it)

Founder, 2026-11-09: wine compliance must cover *every* requirement in !662, not a first slice.
Each row is a requirement from the research, the feature that meets it, and how the
winemaker meets it without extra work. "Record" means a dated compliance record with
evidence, owner and due date (`ComplianceRecord`, the same evidence register Customs and
NP use), shown on the Wine page's WSMP checklist.

| § | Requirement (research) | Type | Where Biz-E meets it | How |
|---|---|---|---|---|
| 3.1 | Activity/product scope matches what's made, packed, stored, exported | Law | Compliance configuration + Wine plan dialog | Product types, exporter, SWNZ, organic switches; frameworks apply from them |
| 3.2 | Registered WSMP (operator, site, plan, verifier) | Law | Wine → plan card; control `wsmp-registration` | Plan reference, verifier, next verification; record with the registration evidence |
| 3.2 | Records accurate, who/what/when, kept ≥7 years | Law | Every production record (actor, timestamp); control `record-retention` | Automatic; Biz-E never deletes production records |
| 3.2 | Trace records retrievable within 24 h; other records within 2 working days | Law | Wine → each lot's **trace and mass balance**, CSV | One click per lot |
| 3.2 | Significant-change and minor-change notifications (2026 amendment) | Law | Control `wsmp-changes` | Record each notification with its due date; overdue shows on the checklist |
| 3.2 | Small winemaker exemption: <20,000 L / 2 yrs, notified, no export, 2-yr expiry | Law | Wine → exemption meter; export refused while exempt | Litres from ferment steps; amber at 80% or 60 days to expiry |
| 3.3 | 2026 amendments effective-dated (28 Aug 2026; export fees 1 Jul 2026) | Law | Rule constants carry their source and start date | Shown in the checklist and export levy |
| 4.1 | Premises, equipment, maintenance, calibration | Law (WSMP) | Control `premises-equipment` | Record with evidence and next due |
| 4.1 | Water suitable for use (source, treatment, testing) | Law (WSMP, 2026 amendment) | Control `water` | Record test results, due date |
| 4.1 | Cleaning, sanitation, maintenance compounds, chemicals | Law (WSMP) | Control `cleaning-chemicals` | Record; production evidence photos also count |
| 4.1 | Pest, waste, drains, contamination pathways | Law (WSMP) | Control `pest-waste` | Record |
| 4.1 | Staff illness, hygiene, training, protective clothing | Law (WSMP, 2026 amendment) | Control `staff-hygiene` | Competency record per person, due date |
| 4.1 | Grape supplier spray/withholding info; intake identity, condition, accept/reject | Law (WSMP) | **Intake step** fields; control `grape-intake` (live) | Asked at every intake; the checklist shows the share of this vintage's lots with a spray diary |
| 4.1 | Inputs and processing aids recorded per batch | Law (WSMP) | **Cellar step** SO₂ and fining; step inputs | Asked in production; composition carries them to the label |
| 4.1 | Specifications, sampling/testing, non-conforming product, release decision | Law (WSMP) | **Bottle step** release field; control `lab-release` | "Released for sale" asked at bottling; lab file on the step |
| 4.1 | Contractors, cross-site and off-site work covered | Law (WSMP) | Control `contractors` | Record each contractor's coverage evidence |
| 4.2 | Separate Food Act activities (cellar-door food) | Law | Compliance → Food registrations (existing) | Unchanged; linked from the Wine checklist |
| 4.3 | Sulphites ≥10 mg/kg declared; allergen fining assessed | Law (FSANZ) | **Bottling pre-flight** | Worked out from cellar records |
| 5.1 | Source-to-recipient trace: vineyard, intake, making, packaging, movement, distribution | Law | Trace graph (existing) + intake fields + sales | Every step already links lots; Wine adds grower/variety/vintage/region |
| 5.1 | Mass balance: inputs reconcile to stock, loss, samples, sales | Good practice / recall | Wine → **trace and mass balance** per lot | In vs out per step, loss %, flagged when out > in |
| 5.3 | Recall procedure; simulated recall at least every 12 months | Law | Recalls and drills (GL-P03, existing); control `recall` (live) | Checklist goes amber at 11 months, red at 12 |
| 5.3 | Notify within 24 h of deciding to recall; CNC/ENC within 24 h | Law | Wine → **Report a problem** | Records the incident with a 24-hour due date and **places a quality hold** on the lot |
| 6.1 | Mandatory label: identity, ABV, standard drinks, pregnancy warning, allergens, lot ID, business details | Law (FSANZ) | **Bottling pre-flight** | Worked out per lot; lot ID is the bottled lot |
| 6.1 | Alcohol energy statement (transition ends 13 Aug 2028) | Law (FSANZ) | **Bottling pre-flight** | "Review" now, "On the label" from 13 Aug 2028 |
| 6.2 | 85% variety / vintage / region claims; GI is a separate layer | Law | **Label claims** | Worked out from the trace; region list is the registered GIs |
| 6.3 | Label approval stored, invalidated when composition, ABV or claims change | Recommended | **Approve label** on the pre-flight | Approval fingerprints the facts; any change lapses it |
| 7.1–7.3 | CCA licence, boundaries, movement ledger, duty classification, monthly or 6/12-month entries, nil returns | Law | Compliance → Customs (existing, product-agnostic; grape, fortified and fruit wine tariff items exist) | Unchanged |
| 7.4 | Export clearance through TSW is separate from MPI eligibility | Law | **Export register**: consignment records the Customs entry reference separately | Required field |
| 8.1 | Export eligibility per batch and volume; EES before shipment; quantity ≤ eligible volume; packaged ≤2 yrs, bulk ≤3 months | Law | **Export register** | Eligibility per lot with EES reference; consignments refused over the balance, after expiry, or for an unreleased or exempt lot |
| 8.1 | Trade samples ≤110 L (not for sale) and ≤27 L consignments with current eligibility | Law | **Export register** | Recorded as such; the limits are checked |
| 8.2 | Fruit wine, cider, mead and non-NZ grape wine export path; exporter registration | Law | Framework `wine-export`, control `exporter-registration` | Record registration |
| 8.3 | OMARs and market documents per destination | Market access | Framework `wine-export`, control `market-requirements` | Record each market's OMAR version and documents |
| 8.4 | Organic official assurance; organic claims need evidence | Market/industry | Framework `organic` (when switched on) | Certificate, chain of custody and OOAP records |
| 3.3 / 10.2 | Export levy $0.0037/L after the first 200,000 L per exporter; MPI document fees | Law | **Export register** levy summary | Running litres and levy for the year |
| 9.1–9.2 | Alcohol licences, managers, cellar-door tasting, remote sales | Law | Compliance → Licensing (existing) | Unchanged; linked from the checklist |
| 10.1 | SWNZ certification and records | Industry | Framework `swnz` (when switched on) | Certification and audit records |
| 10.2 | NZ Winegrowers levy | Law (levy order) | Control `nzw-levy` | Record each return |
| 10.3 | Water, waste, H&S, hazardous substances, biosecurity | Adjacent | Trade waste (existing); out of the wine module's scope | Noted, not modelled |
| 11 | Seasonal cycle (pre-vintage, vintage, release, periodic) | Workflow | Due dates on records; production prompts | Checklist orders by what's due |

What the platform still leaves to people, deliberately: the WSMP's own content, the verifier's
judgement, filing with MPI Trade Certification and Customs TSW, and artwork review. Biz-E
records that they happened and checks the facts behind them; it never files or approves on
anyone's behalf.
