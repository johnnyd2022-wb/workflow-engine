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
