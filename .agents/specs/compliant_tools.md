# SPEC: compliant_tools
status: approved
name: Compliant — per-org subscription + NZ alcohol tools suite
slug: compliant_tools
blueprint: app/features/compliant/  (extended; no new top-level blueprint)
url_prefix: /compliant/tools

## Description

Three connected pieces of work that productise the existing `compliant` feature for sale
to the wider NZ alcohol manufacturing industry (spirits, beer, wine, cider):

1. **Per-org subscription (entitlement).** A first-class, persisted per-org entitlement
   primitive — `feature_subscriptions` (`org_id`, `feature_key`, `active`) — owned by
   core. Access to the whole Compliant product area (nav item, every page, every API
   route, the blueprint's static assets) is gated on the caller's org holding an `active`
   subscription to `feature_key = "compliant"`. The deployment-wide
   `[features] compliant_enabled` .ini flag is retained unchanged as the kill switch that
   governs whether the blueprint is registered at all; the subscription is a second,
   per-tenant gate. **Both** must be true for a route to respond and for the nav item to
   show.

2. **Dilution calculator relocation.** The standalone `dilution_calculator` feature is
   moved wholesale into `compliant` as the first entry in a calculators suite. Its solve
   API moves from `POST /api/dilution-calculator/solve` to
   `POST /api/compliant/tools/dilution/solve`. Maths, validation, error messages, and
   response payload are **preserved exactly** (byte-identical JSON for equal inputs, same
   error strings and status codes). Only location, URL, and subscription-gating change.
   The standalone blueprint registration, the `app/features/dilution_calculator/`
   package, the nav item, and any WhiteNoise/asset wiring for it are removed.

3. **NZ alcohol tools suite (Tier 1).** A "Tools" area inside Compliant:
   - `GET /compliant/tools` — HTML page (extends the shared SPA base, shows the
     subscription-gated Compliant nav), listing calculators grouped by category, each
     with a form rendered by one generic client renderer from the catalogue's `inputs`
     schema, and a result panel showing returned values + disclaimer + sources.
   - `GET /api/compliant/tools` — the JSON catalogue.
   - `POST /api/compliant/tools/<key>/solve` — dispatch to the named calculator.

   Solvers are **pure functions**: take a dict, return a dict or raise
   `CalculatorValidationError`; **zero** DB / file / network access. Tier-1 set (10):
   `dilution`, `lal`, `standard_drinks`, `abv_abw`, `gravity_convert`, `abv_from_og_fg`,
   `tank_volume`, `yield_loss`, `yeast_pitch`, `keg_fill`. Formulas, exact catalogue
   `inputs` JSON, and worked-example fixtures are pinned per calculator in
   **## Calculator contracts**.

The Compliant tab continues to host the module dashboard ("all things related to the
modules they have"); "Tools" is a sub-navigation entry within that area.

## Users & permissions

- roles: any authenticated user in a subscribed org may open the Tools page and call the
  catalogue/solve endpoints — no role gate (matches the current dilution calculator).
  Existing `@requires_role(ADMIN)` gates on `PUT /api/compliant/profile` and
  `POST /api/compliant/alcohol-products` are kept as-is; the subscription gate is
  additive and applied first.
- granting/revoking a subscription: operator-only, via CLI, against the target
  environment's DB. No in-app self-serve subscribe/billing flow.
- tenant_scoped: **yes**.
  - `feature_subscriptions` carries `org_id` (FK `organisations`, `ON DELETE CASCADE`).
    Plain `Base` model (not `TenantScoped`), matching sibling `compliance_profiles` /
    `system_findings_cache`. Every read filters on `org_id` explicitly and inline
    (conventions §2). The request-path check is called with the current request's
    `g.current_org_id`; the CLI path runs under `unscoped()` like the other admin
    commands.
  - Calculator maths is org-agnostic (no tenant rows read). *Access* is per-tenant via
    the subscription gate.

## Entitlement resolution (one query per request, cached on `g`)

- The parent `compliant` blueprint registers a single `before_request` for its endpoints.
  Logic, in order:
  1. If `g.current_org_id` is not set (unauthenticated request) → **return without
     acting**. The route's own `@requires_auth` then runs and produces the app's normal
     unauthenticated response (page → 302 to `/`, API → 401). The subscription gate never
     turns an unauthenticated request into a 404.
  2. Otherwise compute `subscribed = bool(config.compliant_enabled) and
     org_has_feature(db_session(), g.current_org_id, "compliant")` **once**, store it as
     `g.compliant_subscribed`.
  3. If `subscribed` is false → `abort(404)` with a generic body (Flask's default
     "Not Found"; no "compliant"/"subscription"/"feature" text).
- `before_request` also stores `g.compliant_subscribed_org = org_id` so the cache is
  tenant-tagged (a reused Flask app context can carry a prior request's `g` attributes;
  `tenant_context.py` clears `g.current_org_id` per request but not arbitrary `g` keys).
- The app-factory context processor injects `compliant_subscribed`: reuse
  `g.compliant_subscribed` **only** when `g.compliant_subscribed_org == g.current_org_id`
  (i.e. cached for this request's org); else, if `g.current_org_id` is set, compute it
  (one query); else `False`. It never runs a second query when `before_request` already
  cached one for this org — which is every `/compliant*` page.
- No calculator solver touches the DB, filesystem, network, or a subprocess. The tools
  routes issue no query beyond reading the cached `g.compliant_subscribed`. (The auth
  middleware's own pre-existing user/org lookups are out of scope and unchanged.)

## Catalogue schema vocabulary

`GET /api/compliant/tools` returns `{"calculators": [entry, ...]}`. Each `entry`:

```
{
  "key": str,
  "title": str,
  "category": "general" | "beer" | "wine" | "vessel",
  "sources": [str, ...],          # non-empty
  "solve":                         # how the "unknown" is chosen; one of:
      null                               # single fixed output
    | {"field": "solve_for", "enum": [...], "default": "..."}   # explicit target field
    | {"one_omitted_of": [field, ...]}   # caller omits exactly one; it is solved
    | {"one_provided_of": [field, ...]}, # caller provides exactly one; rest derived
  "inputs": { <field>: <descriptor>, ... }
}
```

`<descriptor>`:

```
{
  "type": "number" | "integer" | "enum" | "array" | "text",
  "unit": str | null,
  "required": bool,
  "default": <value>,                 # optional
  "min": <n>, "max": <n>,             # inclusive, optional
  "exclusive_min": <n>, "exclusive_max": <n>,   # optional
  "enum": [<value>, ...],             # when type == "enum"
  "item_fields": { <field>: <descriptor>, ... },  # when type == "array"
  "min_items": <n>, "max_items": <n>, # when type == "array"
  "help": str                          # one line, shown under the field
}
```

Descriptor key presence rules (so the catalogue is deep-equality-testable):
- `type` and `required` are **always** present.
- `unit` is **always** present on `number`/`integer`/`text` fields (`null` when
  unitless); absent on `enum`/`array`.
- `default` present **iff** the contract states a default for that field.
- `enum` present **iff** `type == "enum"`. `item_fields`, `min_items`, `max_items`
  present **iff** `type == "array"`.
- `min`/`max`/`exclusive_min`/`exclusive_max` present only where the contract states that
  bound. `help` present **iff** the per-calculator contract gives a quoted help string
  for that field (verbatim).

**Bounds constrain caller-provided values only.** `min`/`max`/`exclusive_*` reject an
*input* field outside range (400 "`<field>` must be …"). *Derived* output values (e.g.
`gravity_convert` returning a °Plato computed from a Baumé input) are returned as
computed and may fall outside another unit's stated input range — that is not an error.

The generic UI renderer builds one labelled control per `inputs` field from this
descriptor (number input, select for `enum`, `text` input, repeatable group for
`array`), marks the `solve` target (disabled/"solving for this"), and renders the result
panel from the solver's returned keys plus `disclaimer` and `sources`.

The complete canonical catalogue is pinned verbatim in **## Appendix A**; AC11 asserts
`GET /api/compliant/tools` deep-equals it.

## Calculator contracts

Shared solver rules:

- `solve(payload: dict) -> dict`; invalid input raises `CalculatorValidationError(msg)`
  with `msg` safe to return verbatim. Dispatch route → `400 {"error": msg}`.
- Every numeric field must be a finite, non-bool `int`/`float`. `bool` → reject
  ("`<field>` must be a number"). NaN/±inf → reject ("`<field>` must be a finite
  number"). Missing required → "`<field>` is required".
- Every **new** calculator (all except `dilution`) returns, additionally:
  `"disclaimer"` (str, ≥ 20 chars, containing the keyword noted per calculator) and
  `"sources"` (non-empty `list[str]`).
- `dilution` is exempt: exact current payload + error strings, no `sources` key.
- Volumes are litres unless the field name ends `_ml`. ABV/attenuation are percentages.
  Temperatures °C.
- **`solve` shape semantics** (shared by every calculator):
  - `{"field": "solve_for", "enum": E, "default": D}` — `payload["solve_for"]`, if
    present, must be in `E` (else 400 "solve_for must be one of: …"); if absent, `D` is
    used. The field named by the (effective) `solve_for` must be **absent or `null`** in
    the payload (else 400 "`<field>` must be omitted when solving for it"). The other
    source fields are required per their descriptors.
  - `{"one_omitted_of": F}` — exactly one member of `F` is absent-or-`null` and the rest
    are present finite numbers (else 400 "provide exactly N-1 of: `<F joined>`", where
    N = len(F)). The omitted one is solved.
  - `{"one_provided_of": F}` — exactly one member of `F` is present (finite number) and
    the rest absent-or-`null` (else 400 "provide exactly one of: `<F joined>`").
  - `null` — no solve target; all `required` fields must be present.
  - A field value of JSON `null` is treated identically to the key being absent,
    everywhere.
- **`array` field validation** (`yield_loss.steps`): the value must be a JSON list (else
  400 "`<field>` must be a list") of length in `[min_items, max_items]` (else 400
  "`<field>` must have between M and N items"); each element a JSON object (else 400
  "each `<field>` item must be an object") whose keys are a subset of `item_fields` (an
  unknown key → 400 "unexpected field '`<k>`' in `<field>` item"); each item validated
  against `item_fields` by the same rules (required/type/bounds).
- **`text` field validation**: value must be a non-empty `str` after `.strip()`, ≤ 80
  chars (else 400 "`<field>` must be a non-empty string of at most 80 characters").
- Fixtures give `input → expected` with an absolute tolerance. Tests assert these exact
  spec-pinned numbers (AC13) — the builder chooses neither examples nor tolerances.

---

### dilution  (category: general) — RELOCATED UNCHANGED

Behaviour, formulas, validation, payload, disclaimer: exactly
`.agents/specs/dilution_calculator.md` + current
`app/features/dilution_calculator/services/dilution_service.py`. Not re-specified.
`solve` = `{"field": "solve_for", "enum": ["starting_abv","starting_volume_ml",
"final_abv","final_volume_ml"], "default": "final_volume_ml"}`; `inputs` = the four
fields, `type number`, units `%`/`mL`, all `required:false` (the omitted one is the
target). Parity fixture: `{"solve_for":"final_volume_ml","starting_abv":40,
"starting_volume_ml":1000,"final_abv":20}` → `solved_value == 2000.0` exactly,
`water_to_add_naive_ml == 1000.0`, response keys identical to the pre-move endpoint.

### lal  (category: general)

`solve` = `{"one_omitted_of": ["volume_l","abv_pct","lal"]}`.
`inputs`:
- `volume_l`: number, unit "L", required false, `exclusive_min: 0`, help "Batch volume".
- `abv_pct`: number, unit "%", required false, `min: 0`, `max: 100`.
- `lal`: number, unit "L alcohol", required false, `min: 0`.
Rules: exactly one of the three omitted/null (else 400 "provide exactly two of volume_l,
abv_pct, lal"). Formula `lal = volume_l * abv_pct / 100`, rearranged. Solving `volume_l`
requires `abv_pct` in `(0, 100]` (else 400 "abv_pct must be greater than 0 to solve for
volume_l"). Solving `abv_pct` requires `volume_l > 0`; result must be in `[0, 100]` else
400. Output `{solved_field, volume_l, abv_pct, lal, disclaimer, sources}`.
Fixtures: `{volume_l:100, abv_pct:40}` → `lal == 40.0` (tol 1e-9);
`{abv_pct:40, lal:40}` → `volume_l == 100.0` (tol 1e-9);
`{volume_l:100, lal:40}` → `abv_pct == 40.0` (tol 1e-9).
Reject: all three present; only one present; `{volume_l:null, abv_pct:0, lal:null}`
(can't solve two); solving `volume_l` with `abv_pct:0`.
Disclaimer keyword: "operational" — "Operational estimate; confirm LAL for excise with
NZ Customs' method."
Source: NZ Customs — litres-of-alcohol basis for excise.

### standard_drinks  (category: general)

`solve` = `{"field": "solve_for", "enum": ["standard_drinks","volume_ml"],
"default": "standard_drinks"}`.
`inputs`:
- `volume_ml`: number, unit "mL", required false, `exclusive_min: 0`.
- `abv_pct`: number, unit "%", required true, `min: 0`, `max: 100`.
- `standard_drinks`: number, unit "drinks", required false, `min: 0`.
Constant `ETHANOL_DENSITY_20C_G_PER_ML = 0.78924`, `NZ_STANDARD_DRINK_GRAMS_ETHANOL = 10`.
- `solve_for == "standard_drinks"`: require `volume_ml` (>0), `abv_pct` in `[0,100]` →
  `standard_drinks = volume_ml * (abv_pct/100) * 0.78924 / 10`.
- `solve_for == "volume_ml"`: require `standard_drinks` (≥0), `abv_pct` in `(0,100]` →
  `volume_ml = standard_drinks * 10 / (0.78924 * abv_pct/100)`.
Output `{solved_field, volume_ml, abv_pct, standard_drinks, disclaimer, sources}`.
Fixtures: `{volume_ml:330, abv_pct:5}` → `standard_drinks == 1.302246` (tol 1e-6);
`{solve_for:"volume_ml", standard_drinks:1, abv_pct:40}` → `volume_ml == 31.6761`
(tol 1e-3).
Reject: `solve_for:"volume_ml"` with `abv_pct:0`; missing `abv_pct`; `abv_pct:150`.
Disclaimer keyword: "verify" — "Label standard-drink statements must be verified and
rounded per the Australia New Zealand Food Standards Code (Standard 2.7.1)."
Source: FSANZ Standard 2.7.1; Health NZ standard-drink definition (10 g ethanol).

### abv_abw  (category: general)

`solve` = `{"field": "solve_for", "enum": ["abw_pct","abv_pct"], "default": "abw_pct"}`.
`inputs`:
- `abv_pct`: number, unit "%", required false, `min: 0`, `max: 100`.
- `abw_pct`: number, unit "%", required false, `min: 0`, `max: 100`.
- `solution_sg`: number, unit "SG", required true, `exclusive_min: 0.7`,
  `exclusive_max: 1.1`.
`abw_pct = abv_pct * 0.78924 / solution_sg`; inverse `abv_pct = abw_pct * solution_sg /
0.78924`. Given value and result both in `[0,100]` (else 400). `solution_sg` required
regardless of direction.
Output `{solved_field, abv_pct, abw_pct, solution_sg, disclaimer, sources}`.
Fixtures: `{abv_pct:40, solution_sg:0.9352}` → `abw_pct == 33.7571` (tol 1e-3);
`{solve_for:"abv_pct", abw_pct:33.7571, solution_sg:0.9352}` → `abv_pct == 40.0`
(tol 1e-2).
Reject: missing `solution_sg`; `solution_sg:1.5`; `abv_pct:120`.
Disclaimer keyword: "measured" — "First-order density relation; use a measured method
for tax or label ABV."
Source: standard alcoholometry (mass/volume fraction; OIML R22 density basis).

### gravity_convert  (category: beer)

`solve` = `{"one_provided_of": ["sg","plato","brix","baume"]}`.
`inputs` (each number, required false, with the bounds below), plus `help` noting only
one may be given:
- `sg`: unit "SG", `min: 1.000`, `max: 1.150`.
- `plato`: unit "°P", `min: 0`, `max: 33`.
- `brix`: unit "°Bx", `min: 0`, `max: 33`.
- `baume`: unit "°Bé", `min: 0`, `max: 18`.
(The four input domains are aligned: `sg 1.150` ≈ `plato 34.8` capped display /
`baume 18` → `sg 1.1417`. Per the "bounds constrain inputs only" rule, a derived output
may still land just outside a sibling range and that is not an error.)
Exactly one provided (else 400 "provide exactly one of: sg, plato, brix, baume").
Resolve `sg` first:
- given `sg`: identity.
- given `plato` or `brix` (treated identically): bisect the cubic below on
  `sg ∈ (1.000, 1.150)`, 60 iterations, deterministic. `plato`/`brix` outside the range
  the cubic reaches on that interval → 400 "value not representable".
- given `baume`: `sg = 145 / (145 - baume)`.
Then from `sg`:
- `plato = -616.868 + 1111.14*sg - 630.272*sg**2 + 135.997*sg**3`
- `brix = plato`
- `baume = 145 - 145/sg`
Output `{sg, plato, brix, baume, disclaimer, sources}`.
Fixtures: `{sg:1.048}` → `plato == 11.91` (tol 0.05), `brix == plato`,
`baume == 6.6412` (tol 1e-3);
`{plato:11.91}` → `sg == 1.048` (tol 1e-3);
`{baume:6.6412}` → `sg == 1.048` (tol 1e-4).
Reject: zero inputs; two inputs; `sg:1.30`; `plato:40`; `baume:25`.
Disclaimer keyword: "approximation" — "°Brix is treated as equal to °Plato (an
approximation diverging ~0.3 at high gravity); SG↔°Plato uses the ASBC cubic."
Source: ASBC Methods of Analysis (SG↔°Plato cubic); standard hydrometry (Baumé, modulus 145).

### abv_from_og_fg  (category: beer)

`solve` = `null`.
`inputs`:
- `og_sg`: number, unit "SG", required true, `exclusive_min: 1.000`, `max: 1.200`.
- `fg_sg`: number, unit "SG", required true, `min: 0.980`, `max: 1.100`.
Require `og_sg > fg_sg` (else 400 "og_sg must be greater than fg_sg"). `og_sg` strictly
> 1.000 (exclusive bound; guards the attenuation divisor).
`abv_pct = (og_sg - fg_sg) * 131.25`;
`apparent_attenuation_pct = (og_sg - fg_sg) / (og_sg - 1.0) * 100`.
Output `{abv_pct, apparent_attenuation_pct, og_sg, fg_sg, disclaimer, sources}`.
Fixture: `{og_sg:1.050, fg_sg:1.010}` → `abv_pct == 5.25` (tol 1e-6),
`apparent_attenuation_pct == 80.0` (tol 1e-6).
Reject: `og_sg <= fg_sg`; `og_sg:1.000`; missing `fg_sg`.
Disclaimer keyword: "approximation" — "The ×131.25 approximation; for tax or label ABV
use a measured method."
Source: standard craft-brewing reference (Palmer, "How to Brew").

### tank_volume  (category: vessel)

`solve` = `null`.
`inputs`:
- `diameter_m`: number, unit "m", required true, `exclusive_min: 0`.
- `cyl_height_m`: number, unit "m", required true, `exclusive_min: 0`.
- `cone_height_m`: number, unit "m", required false, default `0`, `min: 0`.
- `fill_height_m`: number, unit "m", required true, `min: 0`.
`r = diameter_m / 2`.
`capacity_l = (pi*r**2*cyl_height_m + (1/3)*pi*r**2*cone_height_m) * 1000`.
Filled volume:
- `fill_height_m == 0` → `filled_l = 0.0`.
- `cone_height_m == 0` → `filled_l = pi*r**2*fill_height_m * 1000` (pure cylinder).
- `0 < fill_height_m <= cone_height_m` →
  `filled_l = (1/3)*pi*(r*fill_height_m/cone_height_m)**2*fill_height_m * 1000`.
- `fill_height_m > cone_height_m` →
  `filled_l = ((1/3)*pi*r**2*cone_height_m + pi*r**2*(fill_height_m - cone_height_m)) * 1000`.
- `fill_height_m > cone_height_m + cyl_height_m` → 400 "fill_height_m exceeds tank height".
`headspace_l = capacity_l - filled_l`.
Output `{capacity_l, filled_l, headspace_l, disclaimer, sources}`.
Fixtures:
`{diameter_m:1.0, cyl_height_m:2.0, cone_height_m:0.3, fill_height_m:1.3}` →
`capacity_l == 1649.336` (tol 0.01), `filled_l == 863.938` (tol 0.01),
`headspace_l == 785.398` (tol 0.01);
`{diameter_m:1.0, cyl_height_m:2.0, cone_height_m:0, fill_height_m:0.5}` →
`capacity_l == 1570.796` (tol 0.01), `filled_l == 392.699` (tol 0.01);
`{diameter_m:1.0, cyl_height_m:2.0, cone_height_m:0.3, fill_height_m:0}` →
`filled_l == 0.0`, `headspace_l == 1649.336` (tol 0.01).
Reject: `fill_height_m:3.0` for the first tank (0.3+2.0 = 2.3 max); `diameter_m:0`.
Disclaimer keyword: "nominal" — "Nominal cylinder+cone geometry; ignores dished heads,
wall thickness and fittings."
Source: solid geometry (cylinder + right circular cone).

### yield_loss  (category: vessel)

`solve` = `null`.
`inputs`:
- `start_volume_l`: number, unit "L", required true, `exclusive_min: 0`.
- `steps`: array, required true, `min_items: 1`, `max_items: 50`, `item_fields` =
  `{ "name": {"type": "text", "required": true},
     "loss_pct": {"type": "number", "unit": "%", "required": false, "min": 0,
                  "exclusive_max": 100},
     "loss_l":   {"type": "number", "unit": "L", "required": false, "min": 0} }`.
  (`type: "text"` is added to the descriptor vocabulary for free-text labels; the
  renderer shows a text input. A step supplies exactly one of `loss_pct`/`loss_l`.)
Each step object carries **exactly one** of `loss_pct` / `loss_l` (else 400 "each step
needs exactly one of loss_pct or loss_l"); **all** steps in one request use the same key
(else 400 "steps must all use loss_pct or all use loss_l"). Apply sequentially to a
running `remaining`; `remaining -= remaining*loss_pct/100` or `remaining -= loss_l`. If
`remaining < 0` at any step → 400 "cumulative loss exceeds available volume".
`total_loss_l = start_volume_l - final`; `effective_yield_pct = final/start_volume_l*100`.
Output `{start_volume_l, final_volume_l, total_loss_l, effective_yield_pct,
per_step: [{name, remaining_l}], disclaimer, sources}`.
Fixture: `{start_volume_l:1000, steps:[{name:"brewhouse",loss_pct:8},
{name:"fermentation",loss_pct:5},{name:"packaging",loss_pct:2}]}` →
`final_volume_l == 856.52` (tol 1e-6), `total_loss_l == 143.48` (tol 1e-6),
`effective_yield_pct == 85.652` (tol 1e-6), `per_step[1].remaining_l == 874.0`.
Reject: empty `steps`; a step with both `loss_pct` and `loss_l`; mixed keys across steps;
`start_volume_l:0`; a `loss_l` step larger than the running volume.
Disclaimer keyword: "estimate" — "Planning estimate; actual losses vary by process and
equipment."
Source: arithmetic (sequential proportional / absolute loss).

### yeast_pitch  (category: beer)

`solve` = `null`.
`inputs`:
- `volume_l`: number, unit "L", required true, `exclusive_min: 0`.
- `gravity_plato`: number, unit "°P", required true, `exclusive_min: 0`, `max: 40`.
- `pitch_rate_m_per_ml_per_p`: number, unit "M/mL/°P", required true, `exclusive_min: 0`,
  `max: 5`, help "≈0.75 ale, ≈1.5 lager".
- `pack_billion`: number, unit "B cells", required false, default `100`,
  `exclusive_min: 0`.
`cells_required_billion = pitch_rate_m_per_ml_per_p * volume_l * gravity_plato`
(derivation: rate × (volume_l·1000 mL) × °P million cells, ÷1000 → billion).
`packs = ceil(cells_required_billion / pack_billion)`.
Output `{cells_required_billion, packs, pack_billion, disclaimer, sources}`.
Fixture: `{volume_l:20, gravity_plato:12, pitch_rate_m_per_ml_per_p:1.0}` →
`cells_required_billion == 240.0` (tol 1e-9), `packs == 3`.
Reject: `volume_l:0`; `pitch_rate_m_per_ml_per_p:0`; `gravity_plato:50`;
`pack_billion:0`.
Disclaimer keyword: "viability" — "Assumes 100% viability; adjust for yeast age and a
starter."
Source: White & Zainasheff, "Yeast" (pitching-rate model).

### keg_fill  (category: vessel)

`solve` = `null`.
`inputs`:
- `available_l`: number, unit "L", required true, `exclusive_min: 0`.
- `keg_size_l`: number, unit "L", required true, `exclusive_min: 0`.
- `fill_loss_pct`: number, unit "%", required false, default `0`, `min: 0`, `max: 50`.
Source draw per full keg = `keg_size_l * (1 + fill_loss_pct/100)`.
`full_kegs = floor(available_l / (keg_size_l * (1 + fill_loss_pct/100)))`;
`packaged_l = full_kegs * keg_size_l`;
`loss_l = full_kegs * keg_size_l * fill_loss_pct/100`;
`remainder_l = available_l - packaged_l - loss_l`.
Output `{full_kegs, packaged_l, loss_l, remainder_l, disclaimer, sources}`.
Fixture: `{available_l:1000, keg_size_l:50, fill_loss_pct:2}` → `full_kegs == 19`,
`packaged_l == 950.0`, `loss_l == 19.0` (tol 1e-6), `remainder_l == 31.0` (tol 1e-6).
Reject: `keg_size_l:0`; `available_l:0`; `fill_loss_pct:80`.
Disclaimer keyword: "estimate" — "Estimate; real fill loss depends on line length,
foaming and temperature."
Source: arithmetic (integer packaging with proportional fill loss).

## Constants (single source of truth)

`app/features/compliant/modules/nz_alcohol/constants.py`:
- `ETHANOL_DENSITY_20C_G_PER_ML = 0.78924`
- `NZ_STANDARD_DRINK_GRAMS_ETHANOL = 10.0`

No calculator module redefines these as literals; each imports from the shared module
(AC14).

## Acceptance criteria

### Subscription / entitlement

- AC1: A `feature_subscriptions` table exists with columns: `id` uuid pk; `org_id` uuid
  NOT NULL, FK `organisations.id` `ON DELETE CASCADE`; `feature_key` varchar(80) NOT
  NULL; `active` boolean NOT NULL default true; `granted_at` timestamptz NOT NULL default
  now(); `granted_by_user_id` uuid NULL, FK `users.id` `ON DELETE SET NULL`; `notes`
  varchar(500) NULL. Unique constraint on `(org_id, feature_key)`; index on
  `(org_id, feature_key)`. `alembic upgrade` → `downgrade` → `upgrade` all run cleanly
  against the test DB.

- AC2: `org_has_feature(session, org_id, feature_key) -> bool` returns `True` iff a row
  exists for that exact `(org_id, feature_key)` with `active is True`; `False` for no row
  and for `active is False`. The query filters on `org_id` explicitly and inline. Given a
  second org's active row for the same `feature_key`, a call for org A does not see org
  B's row.

- AC3: The parent `compliant` blueprint's `before_request` enforces the subscription for
  **every** endpoint whose name starts `compliant` (covers `compliant`,
  `compliant_api`, `compliant_pages`, the `/compliant/static/<f>` route, and the new
  tools routes). Test: iterate `app.url_map` for rules with
  `endpoint.startswith("compliant")`; for each rule and each method it allows (excluding
  `HEAD`/`OPTIONS`), build a valid request (valid path params; a minimal valid JSON body
  where the method needs one) as an **authenticated user in an unsubscribed org** and
  assert the response is **exactly `404`** and the body contains neither "compliant" nor
  "subscription" nor "feature" (generic not-found). This runs with
  `compliant_enabled = true`. A companion case: the **same iteration as an
  unauthenticated client** asserts every rule returns the app's normal unauthenticated
  response (302 to `/` for pages, 401 for `/api/*`) and **never `404`** — the gate must
  not fire before `@requires_auth`.

- AC4: With the caller's org subscribed (`active = true`): those routes behave normally
  (GET pages/catalogue `200` for a valid session; solve endpoints per their calculator
  ACs). A non-admin user in a *subscribed* org still gets `403` from the two
  ADMIN-gated routes (the subscription gate did not replace the role gate). Flipping the
  row to `active = false` restores `404` on the next request, no app restart.

- AC5: When a route is refused for lack of subscription, one warning-level structured log
  line is emitted: `event="access_denied"`, `reason="org_not_subscribed"`,
  `feature="compliant"`, `org_id=<caller org>`, `path`, `method`.

- AC6: With `compliant_enabled = false`, `create_app()` raises nothing and the blueprint
  is not registered: every `/compliant*` and `/api/compliant*` path returns `404`
  regardless of subscription (config-override test).

- AC7: `compliant_subscribed` in template context is
  `bool(config.compliant_enabled) and org_has_feature(...)` for the current org, reusing
  `g.compliant_subscribed` when `before_request` already cached it, and `False` when
  `g.current_org_id` is unset. The sidebar renders the Compliant nav `<li>` iff
  `compliant_subscribed` is truthy. Verified: (a) `compliant_enabled=true` + subscribed
  logged-in user → item present; (b) `compliant_enabled=true` + unsubscribed → absent;
  (c) `compliant_enabled=false` + subscribed → absent; (d) logged-out page → absent, no
  error. The hard-coded "Dilution Calculator" nav `<li>` is removed from **both**
  `app/ui/templates/shared/sidebar-v2.html` and `app/ui/shared/sidebar-v2.html`, and
  neither file contains `/dilution-calculator` afterwards.

- AC8: CLI commands on the `workflow` group, all running under `unscoped()`, validating
  the org exists, exiting non-zero with a message on a bad/unknown `--org-id`:
  - `workflow grant-feature --org-id <uuid> --feature <key> [--note <text>]` — inserts,
    or re-activates + updates `notes` on an existing `(org_id, feature_key)` row.
    Idempotent: run twice → exactly one row, `active = true`.
  - `workflow revoke-feature --org-id <uuid> --feature <key>` — sets `active = false`
    (no error if absent; prints a notice).
  - `workflow list-features --org-id <uuid>` — prints each
    `(feature_key, active, granted_at)` for the org.
  Covered by tests invoking the click commands against the test DB.

### Dilution relocation

- AC9: `POST /api/compliant/tools/dilution/solve` (subscribed, authed) returns a JSON
  body **equal** to the pre-move `POST /api/dilution-calculator/solve` for the same
  input, for: the parity fixture, a solve-for-each-of-the-four-variables set, and three
  validation-error inputs (same `{"error": ...}` string and status).
  `POST /api/dilution-calculator/solve` → `404`. `app/features/dilution_calculator/`
  does not exist. `app_factory.py` no longer imports or registers
  `create_dilution_calculator_blueprint`, and no `dilution` WhiteNoise/asset wiring
  remains.

- AC10: `app/observability/context.py` `BLUEPRINT_FEATURE` no longer contains the two
  `dilution_calculator.*` keys and does map `"compliant"`, `"compliant.compliant_api"`,
  `"compliant.compliant_pages"` → `"compliant"`.
  `tests/test_observability_context.py`'s `dilution_calculator` nested-app test is
  replaced by a `compliant` nested-app test asserting `GET /compliant/tools` and
  `POST /api/compliant/tools/dilution/solve` resolve to feature `"compliant"`.

### Tools suite

- AC11: `GET /api/compliant/tools` (subscribed) returns a JSON body that **deep-equals**
  the canonical catalogue pinned in **## Appendix A** — compared as: same set of
  `calculators` by `key` (order-insensitive), and for each entry an exact recursive
  equality of `key`, `title`, `category`, `sources` (list, order-sensitive), `solve`, and
  `inputs` (every field, every descriptor key/value including `unit`, `default`, `help`,
  `enum`, `item_fields`, `min_items`/`max_items`, and all bound keys). The canonical
  literal is committed as `tests/fixtures/compliant_tools_catalogue.json` and served from
  `app/features/compliant/tools/catalogue.json`; a test asserts the served catalogue, the
  committed fixture, **and the Appendix A JSON block** are all `json.loads`-equal (the
  invariant is field/value content, not byte formatting), and that the key set is exactly
  the 10 Tier-1 keys.

- AC12: `POST /api/compliant/tools/<key>/solve` dispatches to `CALCULATORS[key].solve`.
  Unknown `<key>` → `404 {"error": "unknown calculator"}`. A payload failing the
  calculator's validation → `400 {"error": "<safe message>"}`, no traceback, no 500. A
  well-formed request logs `event="compliant.tool_solved"`, `tool=<key>` (info); a
  rejected one logs `event="compliant.tool_rejected"`, `tool=<key>`, `reason=<msg>`
  (warning).

- AC13: **Every** Tier-1 calculator has unit tests that (a) assert its spec-pinned
  fixture(s) — exact input, exact expected field(s), the spec tolerance; and (b) assert
  each documented rejection path for that calculator (the shared ones plus the
  calculator-specific list in its contract). Additionally, for every **new** calculator
  a test asserts the returned `disclaimer` is a non-empty str ≥ 20 chars containing that
  calculator's stated keyword, and `sources` is a non-empty `list[str]`.

- AC14: Solver purity is enforced two ways:
  (a) **Import allowlist** — a test parses each solver module's AST and asserts every
  top-level `import`/`from` target is in the allowlist `{math, decimal, typing,
  collections.abc, functools, __future__,
  app.features.compliant.modules.nz_alcohol.constants,
  app.features.compliant.tools.errors,
  app.features.compliant.tools.calculators._validate}`. Any of `os`, `io`, `pathlib`,
  `socket`, `urllib`, `subprocess`, `requests`, `flask`, `sqlalchemy`, `app.core.db`,
  or a `*_repo` module → fail. (`_validate` is on the allowlist and is itself covered by
  the same test.)
  (b) **Sandboxed fixture run** — a test calls every solver with its pinned fixture while
  `builtins.open`, `socket.socket`, `urllib.request.urlopen`, and `subprocess.Popen` are
  monkeypatched to raise `AssertionError`, and asserts each returns its pinned result
  with no Flask app context.
  The tools **routes** perform no DB query beyond reading the cached
  `g.compliant_subscribed`: a test patches the compliance/inventory/execution/CRM
  repositories and `Session.execute`/`Session.query` and asserts none is invoked during a
  `POST /api/compliant/tools/<key>/solve` request that has already passed
  `before_request`.

- AC15: `ETHANOL_DENSITY_20C_G_PER_ML` and `NZ_STANDARD_DRINK_GRAMS_ETHANOL` resolve to
  a single definition in `constants.py`; a test greps the calculator modules and asserts
  none rebinds either name to a literal.

The `/compliant/tools` UI is verified at three levels — pure render logic (AC16),
served-page structure (AC17), and a real end-to-end browser flow (AC19). AC16/AC17
deliberately do **not** by themselves prove the page works; AC19 does.

- AC16: The client logic lives in a **pure function module**
  `app/features/compliant/frontend/static/tools-render.js` (CommonJS-style exports like
  `app/core/frontend/js/execution-render-docs.js`, so `node --test` can `require()` it —
  the repo has no jsdom). It exports:
  - `buildFormFields(catalogEntry) -> [{name, label, type, unit, required, options?,
    is_solve_target}]` — one entry per `inputs` field (nested `item_fields` flattened
    with a `parent` marker), `solve` target flagged.
  - `buildPayload(catalogEntry, rawFieldValues) -> object` — assembles the POST body:
    numbers coerced, empty strings dropped, `solve_for` set from the marked target,
    array fields grouped.
  - `solveUrl(catalogEntry) -> "/api/compliant/tools/<key>/solve"`.
  - `renderResult(catalogEntry, solverResultObj) -> htmlString` — result panel: the
    solver's returned numeric keys, then `disclaimer`, then `sources`.
  - `renderError(errorMessage) -> htmlString`.
  `tests/js/compliant-tools-render.test.js` (`node --test`) asserts, **for every Tier-1
  calculator**: `buildFormFields` yields exactly that calculator's pinned `inputs` field
  names with the right `type`/`required`/`is_solve_target`; `buildPayload` from that
  calculator's pinned fixture input produces the exact POST body the fixture describes;
  `solveUrl` is the right path; `renderResult(entry, <pinned fixture expected output>)`
  contains every pinned expected value as text, the `disclaimer`, and each `sources`
  entry; `renderError("bad input")` contains "bad input".
- AC17: `GET /compliant/tools` (subscribed, authed) returns `200` HTML that extends the
  shared SPA base (subscription-gated Compliant nav present), contains a heading/section
  per `category`, loads `tools-render.js` plus a small page controller script, and
  contains a `<form data-calculator="<key>">` with one control per that calculator's
  catalogue `inputs` field, plus a `[data-result]` container, for **every** Tier-1
  calculator. Unauthenticated → 302 to `/`; unsubscribed → `404`. A Python route test
  asserts the status codes, all 10 `data-calculator=` markers, and that each form has the
  expected number of input controls.
- AC19 (e2e-playwright): against a live server, as a subscribed authenticated user, open
  `/compliant/tools`; for the **dilution** and **standard_drinks** calculators, fill the
  form with that calculator's pinned fixture input, submit, and assert the rendered
  result panel shows the pinned expected value(s) and the disclaimer text. Also assert:
  an unsubscribed user visiting `/compliant/tools` gets a 404 page and sees no
  "Compliance" nav item; the old `/dilution-calculator` URL 404s.

- AC18: `feature_subscriptions_001` `downgrade()` emits one warning-level log line
  containing the current row count before `op.drop_table`. A test runs `downgrade` with
  ≥1 row present and asserts the warning (and row count) is logged.

## Data model

- changes:
  - **new table** `feature_subscriptions` (AC1). Core-owned:
    model `app/core/db/models/feature_subscription.py` (add to
    `app/core/db/models/__init__.py` and `migrations/env.py` imports);
    repo `app/core/db/repositories/feature_subscription_repo.py`
    (`FeatureSubscriptionRepository(session)` with `get(org_id, feature_key)`,
    `is_active(org_id, feature_key)`,
    `grant(org_id, feature_key, granted_by_user_id=None, notes=None)`,
    `revoke(org_id, feature_key)`, `list_for_org(org_id)` — every method takes `org_id`
    explicitly, filters inline); module function `org_has_feature(session, org_id,
    feature_key)` in `app/core/security/entitlements.py` wrapping
    `FeatureSubscriptionRepository(session).is_active(...)`; migration
    `app/core/db/migrations/versions/feature_subscriptions_001.py`
    (`down_revision = "system_findings_cache_001"`).
  - no changes to any existing table.
- destructive: **yes** — `downgrade()` drops `feature_subscriptions`, destroying all
  entitlement rows once populated. migration-safety runs. Rollback is **irrecoverable
  except from a manual pre-rollback CSV export**; there is no in-migration data
  preservation. Runbook (migration docstring + MR description): before downgrading any
  environment with real grants, run
  `\copy feature_subscriptions to 'feature_subscriptions.csv' csv header`; to restore,
  re-run `upgrade` then `\copy feature_subscriptions from 'feature_subscriptions.csv'
  csv header`. `downgrade()` logs the row count it is about to drop (AC18). No existing
  table's column is renamed or dropped.

## External surfaces

- none. No third-party APIs, webhooks, uploads, or background jobs. Calculator maths is
  local and pure.

## Out of scope

- **Tier-2 calculators** — a follow-up MR, each blocked on a single verified source
  formula + spec-pinned fixtures before it ships: `ibu_tinseth`, `priming_sugar`,
  `strike_water`, `refractometer_fg`, `hydrometer_temp_correction`, `chaptalisation`,
  `potential_alcohol`, `acid_addition`, `so2_addition`, and **`excise_duty`**.
  `excise_duty` is additionally blocked on a **human supplying the reviewed NZ Customs
  alcoholic-beverage excise rate table** (every class, rate, `rate_basis`, unit,
  effective date, source URL) — the spec-critic circuit breaker tripped twice on
  inventing that data, so it is explicitly not in this MR. The `rate_basis` design and
  the "GST/levy excluded, snapshot + operator-refresh" contract from earlier drafts
  carry forward into that follow-up.
- Any in-app self-serve subscribe / billing / plan-management flow.
- Retro-fitting the `feature_subscriptions` gate onto CRM, workflow_engine, or
  process_templates. The primitive is generic; only `compliant` is wired to it now.
- Persisting calculator inputs/outputs, per-user history, or attaching results to
  compliance records.
- Non-metric unit systems (US proof gallons, °F inputs).
- Changing the dilution calculator's maths, validation, error messages, disclaimer, or
  payload shape.
- Reconciling the two divergent sidebar files into one — only the dilution/compliant nav
  lines are touched in each; the broader duplication is a noted follow-up.
- In-migration backup/restore of `feature_subscriptions` on downgrade — the export is a
  manual operator step (see Data model).
- Legal/regulatory advice. Every calculator result disclaims that it is an operational
  aid and points to the instrument or regulator for anything feeding a legal obligation.

## Assumptions (lead the MR description)

- ASSUMPTION: entitlement is a generic core-owned `feature_subscriptions` table keyed by
  `(org_id, feature_key)`, not a boolean on `organisations` and not a reuse of
  `ComplianceProfile.enabled`. Rejected: (a) an `organisations` boolean — doesn't
  generalise to the next product area; (b) `ComplianceProfile.enabled` — that means
  "module configured", distinct from "tenant is entitled".
- ASSUMPTION: an unsubscribed org gets **404** (not 403) on every Compliant route, to
  avoid disclosing the feature's existence across tenants.
- ASSUMPTION: Tier-1 is **10** calculators; the remaining 10 (incl. `excise_duty`) are a
  named Tier-2 follow-up. Driven by the spec-critic circuit breaker on the excise rate
  data and concrete formula contradictions in the deferred set. The rejected alternative
  (ship all 20 now with best-effort formulas/rates) is recorded for the MR reviewer to
  overrule.
- ASSUMPTION: one entitlement query per request, cached on `g.compliant_subscribed` by
  the blueprint `before_request`; the context processor reuses it. The auth middleware's
  own user/org lookups are pre-existing and unchanged.
- ASSUMPTION: the migration is **destructive**; `downgrade()` warns + logs the row
  count; recovery is via a manual CSV export only (no in-migration preservation).
  Rejected: making `downgrade()` raise — breaks migration-safety's up/down/up check.
- ASSUMPTION: `whistlebird_test` is granted the `compliant` subscription by the
  orchestrator running `workflow grant-feature` against the **local** DB after the build,
  recorded in the run report. test/prod grants are operator actions; the spec asserts
  only that the command works (AC8).
- ASSUMPTION: staying on the existing `nz-alc-tools` branch/worktree.
- ASSUMPTION: no role gate on the calculators; existing ADMIN gates kept, applied after
  the subscription gate.
- ASSUMPTION: `gravity_convert` takes exactly one input unit, returns all four, treats
  `brix == °Plato`; `abv_abw` requires `solution_sg`; `abv_from_og_fg` uses only
  `×131.25` and requires `og_sg > 1.000`. Zero-denominator boundaries in `lal`,
  `abv_from_og_fg`, `tank_volume`, `standard_drinks` inverse are closed by explicit
  exclusive bounds / branch order in the contracts above.
- ASSUMPTION: the `/compliant/tools` UI is verified at three levels — `node --test` pure
  render/payload logic for **every** Tier-1 calculator (AC16), a Python served-markup
  test for structure (AC17), and an e2e-playwright real-browser fill→submit→result flow
  for `dilution` + `standard_drinks` (AC19). The repo has no jsdom, so there is no
  headless-DOM unit test; e2e is the functional proof.
- ASSUMPTION: the subscription `before_request` **does not act** on an unauthenticated
  request (no `g.current_org_id`); the route's `@requires_auth` produces the normal
  response (302 to `/` for pages, 401 for APIs). Only an authenticated user in an
  unsubscribed org gets the generic 404. Rejected: 404-ing before auth — it contradicts
  the app's established unauthenticated-redirect behaviour and AC17.
- ASSUMPTION: descriptor `min`/`max`/`exclusive_*` bounds constrain caller-provided
  fields only; a derived output value (e.g. a °Plato computed from a Baumé input) may
  fall outside another unit's input range and that is not an error. The four
  `gravity_convert` input domains are nonetheless aligned to reduce surprise.
- ASSUMPTION: the canonical `inputs` catalogue is pinned verbatim as **## Appendix A**
  and byte-copied to `tests/fixtures/compliant_tools_catalogue.json`; AC11 is a
  deep-equality assertion against it. Help strings and defaults change only via a spec +
  fixture edit.

## Appendix A — canonical catalogue (AC11 deep-equality target)

`GET /api/compliant/tools` returns exactly this object. It is byte-copied to
`tests/fixtures/compliant_tools_catalogue.json`. `dilution` describes only its form
shape — its solver keeps its own validation/payload (## dilution contract); every other
entry's `inputs` bounds are authoritative and the solver enforces them.

```json
{
  "calculators": [
    {
      "key": "dilution",
      "title": "Dilution / proofing down",
      "category": "general",
      "sources": ["Dilution calculator spec (.agents/specs/dilution_calculator.md), Calculation model"],
      "solve": {"field": "solve_for", "enum": ["starting_abv", "starting_volume_ml", "final_abv", "final_volume_ml"], "default": "final_volume_ml"},
      "inputs": {
        "starting_abv": {"type": "number", "unit": "%", "required": false},
        "starting_volume_ml": {"type": "number", "unit": "mL", "required": false},
        "final_abv": {"type": "number", "unit": "%", "required": false},
        "final_volume_ml": {"type": "number", "unit": "mL", "required": false}
      }
    },
    {
      "key": "lal",
      "title": "Litres of absolute alcohol (LAL)",
      "category": "general",
      "sources": ["NZ Customs — litres-of-alcohol basis for excise duty"],
      "solve": {"one_omitted_of": ["volume_l", "abv_pct", "lal"]},
      "inputs": {
        "volume_l": {"type": "number", "unit": "L", "required": false, "exclusive_min": 0, "help": "Batch volume"},
        "abv_pct": {"type": "number", "unit": "%", "required": false, "min": 0, "max": 100},
        "lal": {"type": "number", "unit": "L alcohol", "required": false, "min": 0}
      }
    },
    {
      "key": "standard_drinks",
      "title": "Standard drinks",
      "category": "general",
      "sources": ["FSANZ Standard 2.7.1", "Health New Zealand — standard drink = 10 g ethanol"],
      "solve": {"field": "solve_for", "enum": ["standard_drinks", "volume_ml"], "default": "standard_drinks"},
      "inputs": {
        "volume_ml": {"type": "number", "unit": "mL", "required": false, "exclusive_min": 0},
        "abv_pct": {"type": "number", "unit": "%", "required": true, "min": 0, "max": 100},
        "standard_drinks": {"type": "number", "unit": "drinks", "required": false, "min": 0}
      }
    },
    {
      "key": "abv_abw",
      "title": "ABV ↔ ABW",
      "category": "general",
      "sources": ["Standard alcoholometry (mass/volume fraction; OIML R22 density basis)"],
      "solve": {"field": "solve_for", "enum": ["abw_pct", "abv_pct"], "default": "abw_pct"},
      "inputs": {
        "abv_pct": {"type": "number", "unit": "%", "required": false, "min": 0, "max": 100},
        "abw_pct": {"type": "number", "unit": "%", "required": false, "min": 0, "max": 100},
        "solution_sg": {"type": "number", "unit": "SG", "required": true, "exclusive_min": 0.7, "exclusive_max": 1.1}
      }
    },
    {
      "key": "gravity_convert",
      "title": "Gravity unit converter",
      "category": "beer",
      "sources": ["ASBC Methods of Analysis (SG↔°Plato cubic)", "Standard hydrometry (Baumé, modulus 145)"],
      "solve": {"one_provided_of": ["sg", "plato", "brix", "baume"]},
      "inputs": {
        "sg": {"type": "number", "unit": "SG", "required": false, "min": 1.0, "max": 1.15, "help": "Provide exactly one unit"},
        "plato": {"type": "number", "unit": "°P", "required": false, "min": 0, "max": 33, "help": "Provide exactly one unit"},
        "brix": {"type": "number", "unit": "°Bx", "required": false, "min": 0, "max": 33, "help": "Provide exactly one unit"},
        "baume": {"type": "number", "unit": "°Bé", "required": false, "min": 0, "max": 18, "help": "Provide exactly one unit"}
      }
    },
    {
      "key": "abv_from_og_fg",
      "title": "ABV from OG & FG",
      "category": "beer",
      "sources": ["Standard craft-brewing reference (Palmer, \"How to Brew\") — the ×131.25 approximation"],
      "solve": null,
      "inputs": {
        "og_sg": {"type": "number", "unit": "SG", "required": true, "exclusive_min": 1.0, "max": 1.2},
        "fg_sg": {"type": "number", "unit": "SG", "required": true, "min": 0.98, "max": 1.1}
      }
    },
    {
      "key": "tank_volume",
      "title": "Tank volume",
      "category": "vessel",
      "sources": ["Solid geometry (cylinder + right circular cone)"],
      "solve": null,
      "inputs": {
        "diameter_m": {"type": "number", "unit": "m", "required": true, "exclusive_min": 0},
        "cyl_height_m": {"type": "number", "unit": "m", "required": true, "exclusive_min": 0},
        "cone_height_m": {"type": "number", "unit": "m", "required": false, "default": 0, "min": 0},
        "fill_height_m": {"type": "number", "unit": "m", "required": true, "min": 0}
      }
    },
    {
      "key": "yield_loss",
      "title": "Production yield & loss",
      "category": "vessel",
      "sources": ["Arithmetic (sequential proportional / absolute loss)"],
      "solve": null,
      "inputs": {
        "start_volume_l": {"type": "number", "unit": "L", "required": true, "exclusive_min": 0},
        "steps": {
          "type": "array",
          "required": true,
          "min_items": 1,
          "max_items": 50,
          "item_fields": {
            "name": {"type": "text", "unit": null, "required": true},
            "loss_pct": {"type": "number", "unit": "%", "required": false, "min": 0, "exclusive_max": 100},
            "loss_l": {"type": "number", "unit": "L", "required": false, "min": 0}
          }
        }
      }
    },
    {
      "key": "yeast_pitch",
      "title": "Yeast pitch rate",
      "category": "beer",
      "sources": ["White & Zainasheff, \"Yeast\" (pitching-rate model)"],
      "solve": null,
      "inputs": {
        "volume_l": {"type": "number", "unit": "L", "required": true, "exclusive_min": 0},
        "gravity_plato": {"type": "number", "unit": "°P", "required": true, "exclusive_min": 0, "max": 40},
        "pitch_rate_m_per_ml_per_p": {"type": "number", "unit": "M/mL/°P", "required": true, "exclusive_min": 0, "max": 5, "help": "≈0.75 ale, ≈1.5 lager"},
        "pack_billion": {"type": "number", "unit": "B cells", "required": false, "default": 100, "exclusive_min": 0}
      }
    },
    {
      "key": "keg_fill",
      "title": "Keg fill",
      "category": "vessel",
      "sources": ["Arithmetic (integer packaging with proportional fill loss)"],
      "solve": null,
      "inputs": {
        "available_l": {"type": "number", "unit": "L", "required": true, "exclusive_min": 0},
        "keg_size_l": {"type": "number", "unit": "L", "required": true, "exclusive_min": 0},
        "fill_loss_pct": {"type": "number", "unit": "%", "required": false, "default": 0, "min": 0, "max": 50}
      }
    }
  ]
}
```
