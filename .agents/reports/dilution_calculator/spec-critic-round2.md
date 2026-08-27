# Spec Critic — dilution_calculator (Round 2 / final permitted pass)

Spec: `.agents/specs/dilution_calculator.md` (status: `approved-unattended`)
Graded fresh against `.claude/skills/spec-critic/SKILL.md`. Prior report:
`.agents/reports/dilution_calculator/spec-critic.md` (8 gaps, `gaps-found`).

## Physics/algebra check on the (a,b,c,d) exact-identity claim (task item 1)

Verified sound. The spec's derivation is correct: `%ABV(v/v)` is defined as the volume
pure ethanol *would occupy at 20°C* per 100 volumes of the actual (already-contracted)
solution. That means `(ABV/100) * V_solution = mass_ethanol / rho_ethanol_pure(20°C)` by
definition — a ratio of two *fixed* quantities (ethanol mass is conserved by water-only
dilution; `rho_ethanol_pure` is a constant, not a function of mixture composition). No
mixture-density model enters this equation at all — not "cancels out", it was never a term
in the first place. So `starting_abv * starting_volume_ml = final_abv * final_volume_ml`
holds exactly, and all four closed-form divisions in the Calculation model follow directly.
This is the same identity distillers actually use for Gay-Lussac dilution tables, so the
claim is not just internally consistent, it matches real-world practice. **No flaw found
in the core identity** — this is the strongest part of the rewrite.

Also checked the mass-fraction/ABV link used for `water_to_add_ml`: substituting
`mass_ethanol = w * V * rho_mix(w)` and `rho_ethanol_pure := rho_mix(1)` into the definition
above reproduces the spec's stated `x = 100 * w * rho_mix(w) / rho_mix(1)` exactly — the
self-consistent "Option A" that Round 1's Gap 1 asked for. Checked monotonicity of
`rho_mix(w) = 1.0 - 0.207w - 0.005w²` over `w ∈ [0,1]`: `d/dw[w·rho_mix(w)] = 1 - 0.414w -
0.015w²`, minimum on `[0,1]` is `0.571` at `w=1`, strictly positive throughout — so
`x(w)` is strictly monotonic and the bisection is well-posed with a unique root. Numerically
checked AC2's worked example (40%/1000mL → 20%): `water_to_add_ml ≈ 1003 mL >
water_to_add_naive_ml = 1000 mL`, confirming AC2's `>` direction is not just plausible but
correct.

## Original 8 gaps — status

All 8 are substantively closed:

1. **Density/mass-fraction formula unpinned** → closed. Exact equation + constants given,
   self-consistent, no external literature constant to transcribe.
2. **AC5 validation timing undefined for ABV-solve directions** → closed. The rewritten
   rule cleverly swaps which pair it checks based on `solve_for`, so in all 4 directions the
   checked pair is always among the 3 *given* fields — genuinely pre-solve computable. (But
   see new Gap 1 below — the swap closes the *timing* problem while leaving a *correctness*
   gap in one branch.)
3. **No volume-monotonicity check** → closed, folded into AC5's ABV-field branch.
4. **AC3 round-trip tolerance unspecified for volumes** → closed. Uniform `1e-6` justified
   as floating-point (not measurement) tolerance, applies to all 4 directions symmetrically —
   correct, since these are pure algebraic divisions with no scale-dependent measurement
   error to accommodate.
5. **Response schema unspecified** → mostly closed (see residual below). Field names for
   all four echoed values, `solved_field`, `solved_value`, `water_to_add_ml`,
   `water_to_add_naive_ml`, `disclaimer` are all now named in AC1.
6. **`starting_abv=0` dead-end boundary uncalled-out** → closed, AC5 now states explicitly
   that it's always-rejected-downstream and that `final_abv=0` solved from `starting_abv=0`
   round-tripping is an intentionally-allowed degenerate case.
7. **AC4 malformed-request coverage** → closed, `solve_for` missing/unknown and
   non-numeric/non-finite fields are now explicit. (Reconfirmed already-closed
   2026-08-25 by findings-sweep — no outstanding action.)
8. **"Real-time" wording unbacked by an AC** → closed, now a stated `ASSUMPTION:` line.

## New/residual gaps

**GAP 1 (high): AC5's "uniform rule" and its proof sketch have an unstated division-by-zero
hole — `final_abv = 0` given, `solve_for = final_volume_ml`, `starting_abv > 0` passes
validation and then crashes the exact-identity formula.**

For `solve_for = final_volume_ml`, the identity computes `final_volume_ml = starting_abv *
starting_volume_ml / final_abv` — the divisor is `final_abv`. AC5's rule for this branch is
"reject if `final_abv >= starting_abv`". Take `starting_abv=40, starting_volume_ml=1000,
final_abv=0`: `0 >= 40` is false, so the request is **not** rejected — yet `final_abv=0` is
literally the divisor, giving `40*1000/0`, an undefined/`ZeroDivisionError` result. `final_abv
= 0` is a legal value under AC4 (`[0,100]` inclusive), so nothing else in the spec catches
this either.

The spec's own proof sketch claims "`final_abv < starting_abv` and `final_volume_ml >
starting_volume_ml` are equivalent statements" — I checked this by dividing the identity
through: `final_volume_ml > starting_volume_ml ⟺ starting_abv/final_abv > 1 ⟺ starting_abv >
final_abv`, **which requires dividing by `final_abv`, i.e. assumes `final_abv ≠ 0`**. The
proof silently assumes away exactly the value that breaks it. This is not symmetric with the
already-handled `starting_abv=0` case: for `solve_for=starting_volume_ml` the divisor is
`starting_abv`, and AC5's shared rule *does* force rejection whenever `starting_abv=0`
(`final_abv >= 0` is always true) — that direction got lucky because the inequality's fixed
operand happens to be the right one. For `solve_for=final_volume_ml` the divisor is
`final_abv`, but the shared rule's fixed operand is still `starting_abv`, so it does not
protect the `final_abv=0` divisor. The "one uniform rule covers all 4 directions" claim is
false for this specific input.

Physically this input isn't nonsensical to reject — diluting a real spirit to exactly 0%
ABV requires infinite water, so it *should* be a 400 — but as written it isn't one; it's
undefined behavior (crash or `inf`/`nan` depending on runtime), which contradicts AC1's
unconditional "200 with resolved fields" promise for anything AC4/AC5 don't reject, and
contradicts AC5's own "proof [it] is sufficient."
→ *Resolution the spec should state*: extend the volume-field branch to also reject when
the value that direction actually divides by is zero, e.g. "reject if `final_abv >=
starting_abv` **or** (`solve_for=final_volume_ml` and `final_abv <= 0`) **or**
(`solve_for=starting_volume_ml` and `starting_abv <= 0`)" — i.e. state that the two
volume-solving sub-cases are not truly interchangeable under one inequality; each needs its
own divisor guarded, even though the "which pair is known pre-solve" part of the rule is
correctly shared.

**GAP 2 (medium): response value rounding/precision is still unspecified, and it isn't a
cosmetic gap here — it can make AC3 objectively unsatisfiable.**

AC1 now names every response field, closing most of Round 1's Gap 5, but no field states a
rounding/precision rule. AC3's round trip explicitly re-feeds a previous response's
`solved_value` back in as a request input and requires the second solve to land within
`1e-6` of the original. If a builder makes the ordinary API-hygiene choice to round
`solved_value` before serializing (e.g. to 2 or 4 decimal places — nothing in the spec
forbids or permits this), that rounding error (up to `0.005` at 2dp) is 4+ orders of
magnitude larger than the `1e-6` tolerance AC3 demands, and the round-trip test fails on an
implementation that violates no other stated rule. This wasn't an issue in Round 1's phrasing
(tolerance was looser/unspecified there) but the new tight `1e-6` tolerance makes rounding
policy load-bearing.
→ *Resolution*: state that response numeric fields are returned at full float precision
(no rounding) — or, if rounding to N decimals is wanted for display, say so and loosen
AC3's tolerance to be compatible with it.

## Other checks performed (no issues found)

- AC5 boundary at `final_abv=100` / `starting_abv=100`: correctly always rejected by the
  existing `>=` check (diluting can never raise ABV to 100 from ≤100) — no gap.
- Bisection boundary `w=0`/`w=1` (ABV 0/100 in the `water_to_add_ml` calc specifically, as
  opposed to the identity calc where Gap 1 lives): spec explicitly states these are handled
  analytically, not by bisection — correct and sufficient.
- Description/AC coverage, tenant scoping, destructive/data-model, external surfaces: all
  re-checked, no contradictions found (tenant scoping precedent re-verified sound in Round 1
  against live `@requires_auth`-only routes; nothing in this rewrite touches that).
- Bisection iteration count/tolerance is still not a literal number, but AC7 only requires
  a *fixed* (non-time-based) stopping condition for same-implementation determinism, which
  is testable as stated — not re-raising this as a gap.

## Summary

Both original high-severity gaps (density formula, AC5 timing) are genuinely closed, and
all 6 others are closed or turned into explicit `ASSUMPTION:` lines per the unattended
protocol. The core (a,b,c,d) exact-identity physics is verified sound with no flaw. However,
the specific instruction to check AC5's proof sketch rather than trust it surfaced a real,
concrete division-by-zero hole in that same rewritten rule (`final_abv=0` given +
`solve_for=final_volume_ml`), plus a residual precision/rounding ambiguity that threatens
AC3's own falsifiability. Neither is covered by an existing `ASSUMPTION:` line, so per the
unattended-mode contract this does not yet clear `sound`.

VERDICT: gaps-found
