# SPEC: dilution_calculator
status: reviewed
name: Dilution Calculator
slug: dilution_calculator
blueprint: app/features/dilution_calculator/
url_prefix: /dilution-calculator

## Description
A real-time, stateless calculator for spirits production staff. Given three of the four
dilution variables — starting ABV (a), starting volume (b), final ABV (c), final volume
(d) — it solves for the fourth, and reports how much water actually needs to be poured in
to execute the dilution. It does not read or write inventory, executions, or any other
tenant data; it is a production-floor aid used while diluting a real batch.

## Calculation model (pins down spec-critic gap: exact formulas, not prose)

**The (a, b, c, d) relationship is exact, not contraction-dependent.** By the standard
alcoholometric definition, `%ABV(v/v)` is "the volume pure ethanol would occupy (at 20°C)
as a percentage of the solution's actual volume." Diluting with water only adds water —
the mass (and therefore the reference volume) of ethanol present is unchanged — so
`%ABV × Volume` is conserved exactly between the starting and final states:

```
starting_abv * starting_volume_ml = final_abv * final_volume_ml     (exact identity)
```

Each solve-for scenario is therefore closed-form division, no numerical solving involved:

```
final_volume_ml    = starting_abv * starting_volume_ml / final_abv
final_abv          = starting_abv * starting_volume_ml / final_volume_ml
starting_volume_ml = final_abv * final_volume_ml / starting_abv
starting_abv       = final_abv * final_volume_ml / starting_volume_ml
```

(An earlier draft of this spec assumed contraction would perturb this relationship and
built a density-based implicit solve for it. That was wrong: algebraically, *any*
self-consistent mixture-density model collapses to exactly the identity above when used
to relate `%ABV × Volume` states — the density function cancels out. Do not reintroduce a
density model here; it cannot change this relationship and building one to do so would
silently fail to satisfy AC2 below, or worse, quietly diverge from the correct answer.)

**Where contraction actually matters: `water_to_add_ml`.** Contraction is real, but it
doesn't affect the relation above — it affects how much water, measured on its own before
mixing, must physically be poured into the starting batch to reach the final state,
because mixed volume is less than the sum of the components' own volumes. This *is*
density-dependent and is computed via mass balance:

- Mass-fraction/ABV link: for an ABV value `x` (0-100), ethanol mass fraction `w` solves
  `x = 100 * w * rho_mix(w) / rho_mix(1)`, root-found by bisection on `w in [0, 1]`.
  `w=0` and `w=1` are exact analytically (`x=0` and `x=100` respectively — no bisection
  needed at the boundaries).
- Mixture density approximation (engineering approximation, 20°C reference, not full
  OIML R22/Bettin–Spieweck precision — see Assumption below):
  `rho_mix(w) = 1.0 - 0.207*w - 0.005*w^2` (g/mL). `rho_mix(1)` (~0.788 g/mL) is used as
  the self-consistent pure-ethanol reference density and `rho_mix(0)` (1.0 g/mL) as the
  pure-water reference density — both taken from this same formula, not an external
  literature constant, so `w=0`/`w=1` map to exactly `ABV=0`/`ABV=100`.
- `mass_total_start_g = starting_volume_ml * rho_mix(w(starting_abv))`
- `mass_total_final_g = final_volume_ml * rho_mix(w(final_abv))`
- `water_to_add_ml = (mass_total_final_g - mass_total_start_g) / rho_mix(0)`
- `water_to_add_naive_ml = final_volume_ml - starting_volume_ml` (the naive
  volumes-just-add assumption, returned alongside for comparison)

This is computed once all four of `starting_abv/starting_volume_ml/final_abv/
final_volume_ml` are known (i.e. on every request, after whichever value was solved
for), using the same two `w()` bisections regardless of which field was the unknown.

## Users & permissions
- roles: any authenticated org member (no elevated role — the tool performs no writes
  and reads no tenant data)
- tenant_scoped: no (stateless computation; touches no `org_id`-scoped table). Routes
  still require `@requires_auth` per app-wide convention.

## Acceptance criteria
- AC1: `POST /api/dilution-calculator/solve` accepts JSON with a `solve_for` field naming
  one of `starting_abv | starting_volume_ml | final_abv | final_volume_ml`, plus the
  other three as numeric fields (the field named by `solve_for` must be absent or null).
  Returns 200 with a body containing all four resolved fields (`starting_abv`,
  `starting_volume_ml`, `final_abv`, `final_volume_ml` — the solved one filled in),
  `solved_field`, `solved_value`, `water_to_add_ml`, `water_to_add_naive_ml`, and
  `disclaimer` (see AC8).
- AC2: Given `starting_abv=40, starting_volume_ml=1000, final_abv=20,
  solve_for=final_volume_ml`: `solved_value` (`final_volume_ml`) equals **2000, within
  1e-6** — this is the exact identity, not a contraction-adjusted figure, so it must
  match naive C1V1=C2V2 (AC2 exists to pin down that the (a,b,c,d) relation is *not*
  where a density model belongs — see Calculation model). Separately, `water_to_add_ml`
  in the same response must be **strictly greater than** `water_to_add_naive_ml`
  (1000 mL) — this is where contraction is actually applied and observable: mixing
  contracts volume, so slightly more separately-measured water is needed than the naive
  additive assumption to reach the same actual final state.
- AC3: Round-trip consistency: solving `final_volume_ml` from `(a, b, c)`, then feeding
  `(a, b, final_volume_ml)` back in to solve `final_abv`, returns a value within 1e-6 of
  the original `c` (this is exact-arithmetic division, not a numerical root-find, so the
  tolerance is floating-point precision, not measurement precision). Holds symmetrically
  for all four solve directions/fields.
- AC4: Requests are rejected with 400 and a clear JSON error message when: any ABV
  (given or solve_for target after solving) is outside `[0, 100]`; any volume is `<= 0`;
  `solve_for` is missing or not one of the four valid field names; the field named by
  `solve_for` is present (non-null) in the body; any of the other three required fields
  is missing, non-numeric, or non-finite (`NaN`/`Infinity`).
- AC5: Requests are rejected with 400 using one uniform, direction-independent rule,
  checked against whichever pair of the three *given* values is available before
  solving: when `solve_for` is a volume field (`starting_volume_ml` or
  `final_volume_ml`), reject if `final_abv >= starting_abv`; when `solve_for` is an ABV
  field (`starting_abv` or `final_abv`), reject if `final_volume_ml <=
  starting_volume_ml`. (Proof this is sufficient, not just for 2 of 4 cases: given the
  exact identity in the Calculation model, `final_abv < starting_abv` and
  `final_volume_ml > starting_volume_ml` are equivalent statements — whichever pair is
  known pre-solve, checking it also guarantees the other holds post-solve. A
  `starting_abv=0` input always fails this check when solving a volume field, since no
  valid `final_abv >= 0` can be `< 0`; solving `starting_abv` down to a computed `0`
  given `final_abv=0` is allowed — "diluting water with water" is a degenerate but valid
  case, not specially rejected.) **Additionally**, whichever given value the closed-form
  division uses as its divisor must be strictly positive, checked explicitly (not just
  inferred from the AC5 pair rule): solving `final_volume_ml` divides by `final_abv`, so
  reject with 400 if `final_abv == 0` even though `0 < starting_abv` alone would
  otherwise pass the pair check (`{starting_abv: 40, starting_volume_ml: 1000,
  final_abv: 0, solve_for: final_volume_ml}` must be rejected, not divide by zero). The
  other three solve directions divide by `final_volume_ml`, `starting_abv`, or
  `starting_volume_ml` respectively, which AC4's `volume <= 0` rule and AC5's `c >= a`
  pair rule (covering `starting_abv == 0` whenever `final_abv >= 0`) already guarantee
  are non-zero — implement the `final_abv == 0` divisor check explicitly in code rather
  than relying on that proof holding at runtime.
- AC9: All numeric response fields (`solved_value`, the four echoed
  `starting_abv/starting_volume_ml/final_abv/final_volume_ml`, `water_to_add_ml`,
  `water_to_add_naive_ml`) are returned as full-precision floats with **no server-side
  rounding**; any display rounding is a frontend-only concern applied after the API
  response is received. This is what makes AC3's `1e-6` round-trip tolerance achievable
  in practice.
- AC6: `GET /dilution-calculator` renders the calculator page for an authenticated user.
  An unauthenticated request gets the app's standard `@requires_auth` rejection
  (redirect to login / 401, matching existing routes).
- AC7: The endpoint is stateless and deterministic: identical requests return
  byte-identical JSON (the `water_to_add_ml` bisection uses a fixed iteration
  count/tolerance, not a time- or platform-dependent stopping condition), and the
  feature introduces no model, repository, or table — no rows are written anywhere by
  using this calculator.
- AC8: Every response includes `water_to_add_ml` (contraction-aware) and
  `water_to_add_naive_ml` (naive) side by side, plus a fixed `disclaimer` string noting
  the mixture-density model is an engineering approximation (not an OIML-certified
  legal-metrology figure) and should be checked against a hydrometer before being relied
  on for regulatory label ABV compliance. The `(a,b,c,d)` solve itself carries no such
  disclaimer — it is exact, not an approximation.

## Data model
- changes: none
- destructive: no

## External surfaces
- none (no third-party APIs, webhooks, uploads, or background jobs — pure server-side
  computation behind existing auth)

## Out of scope
- Persisting calculations to inventory or execution records (brief explicitly says
  real-time production use, not inventory tracking)
- Temperature correction / temperature as an input (fixed 20°C reference)
- Full OIML R22 / Bettin–Spieweck legal-metrology precision tables for `water_to_add_ml`
  (see Assumption below) — the `(a,b,c,d)` solve itself needs no such table since it's
  exact algebra, independent of any density model
- Sequential/multi-source blending (more than one starting liquid)
- Non-water dilutants (flavoring, other spirits, etc.) — water dilution only
- Units other than mL and % ABV (no L/gal/oz/proof inputs in v1)
- A bespoke latency SLA — "real-time" describes interactive compute-on-submit UX, not a
  performance budget beyond the app's existing standard (see Assumption below)

## Assumptions (unattended run — no user available to interview; see .agents/autonomy.md)

- ASSUMPTION: Routing — page at `/dilution-calculator`, API at
  `/api/dilution-calculator/solve`, own blueprint `app/features/dilution_calculator/`,
  registered unconditionally in the app factory (no feature flag, unlike
  `crm_enabled`/`workflow_engine_enabled`) since this is a lightweight, always-useful
  tool with zero data-model risk. Rejected: folding it into `core_bp`, because it isn't
  execution/DAG-related; rejected: a feature flag, because there's no signal a staged
  rollout is needed.
- ASSUMPTION: Units — volumes in millilitres (matches the brief's own example, "1000ml"),
  ABV as a percentage `0-100` (not a `0-1` fraction). Rejected: litres/other units, out
  of scope per brief.
- ASSUMPTION: No persistence — the feature writes nothing to the database; every request
  is computed fresh from the four numbers given. Rejected: logging calculations to a new
  table, because the brief explicitly excludes inventory tracking and states no such
  requirement.
- ASSUMPTION: Auth — `@requires_auth` only, no elevated role, since the tool performs no
  writes and reads no tenant data. Rejected: a dedicated "operator" role gate — the brief
  doesn't ask for one and the app has no fine-grained role model to hang it on.
- ASSUMPTION (**flag for founder review**): `water_to_add_ml`'s mixture density is
  approximated at a fixed 20°C reference via `rho_mix(w) ≈ 1.0 - 0.207*w - 0.005*w²`
  (g/mL, `w` = ethanol mass fraction) — a published engineering approximation, not the
  full 12-coefficient OIML R22 / Bettin–Spieweck polynomial. Rejected: encoding the
  official OIML coefficients from memory, because a half-remembered 12-constant
  polynomial risks a *silent* transcription error, worse than a disclosed simpler model
  with a stated error band. The brief's framing — "real-time production use" — maps to
  the "standard/practical" tier research for this spec surfaced (vs. an "OIML precise /
  legal compliance" tier). AC8's disclaimer and this note are the reviewable surface: if
  label-compliance-grade precision on `water_to_add_ml` matters, validate against a
  hydrometer or swap in certified OIML table data before trusting it past that bar. Note
  this uncertainty is scoped **only** to `water_to_add_ml` — the `(a,b,c,d)` solve
  itself (AC2's `solved_value`, AC3's round-trip) is exact and carries no such caveat.
- ASSUMPTION: No temperature correction — fixed 20°C, no temperature input, since the
  brief lists exactly four inputs and doesn't mention temperature. Rejected: adding a
  fifth input field, scope creep beyond the brief.
- ASSUMPTION: Only the dilution direction is supported — AC5's uniform rule rejects any
  request implying `final_abv >= starting_abv` or `final_volume_ml <=
  starting_volume_ml`, because adding water can only lower ABV and raise volume; results
  implying otherwise would be physically wrong and could mislead a real batch.
- ASSUMPTION: "Real-time" (brief's wording) is interpreted as interactive
  compute-on-submit UX (no batch/async job), not a bespoke latency SLA distinct from the
  app's existing performance budget. Rejected: writing a custom tighter perf AC, since
  the brief gives no numeric target and the calculation itself is closed-form
  arithmetic plus two bounded bisections — inherently fast, no budget risk to call out
  specially.
