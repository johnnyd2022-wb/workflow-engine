# Spec Critic — dilution_calculator

Spec: `.agents/specs/dilution_calculator.md` (status: `approved-unattended`)
Graded against: `.claude/skills/spec-critic/SKILL.md`
Mode: unattended (per `.agents/autonomy.md`) — gaps below are checked against the spec's
existing `## Assumptions` block; none of the gaps found are already covered by a stated
`ASSUMPTION:` line, so this does not yet clear the bar for unattended `sound`.

## What was verified sound (checked, not just assumed)

- **Tenant scoping (task item 4) — genuinely resolved.** Checked against the live codebase:
  `app/features/crm/routes/page_routes.py` uses `@requires_auth` alone (no
  `@requires_org_scope`) for every page route, and `app/core/security/permissions.py` shows
  `requires_org_scope` only asserts `g.current_org_id` is set — it is not a prerequisite
  `requires_auth` depends on. `@requires_auth`-only is an established, existing pattern in
  this app for routes that touch no org-scoped table. The spec's `tenant_scoped: no` +
  auth-only claim is consistent with that precedent, not a novel/undecided call. **Not a gap.**
- **Destructive/data-model claim — consistent.** `Data model: changes: none, destructive: no`
  agrees with AC7 ("no model, repository, or table... no rows are written anywhere") and with
  the description. No contradiction found. **Not a gap.**
- **AC2's directional claim (`final_volume_ml > 2000` for the 40%→20%/1000mL example) is
  physically correct**, not just plausible-sounding: ethanol-water contraction means the mixed
  volume is less than the naive sum, so for a *given* amount of water added the actual ABV
  ends up higher than the naive formula predicts — meaning more water (and hence more final
  volume) is needed to hit the same target ABV than the naive linear answer gives. The
  direction asserted is right.
- **AC5's literal boundary (`final_abv == starting_abv` rejected via `>=`) is unambiguous as
  written** — the task flagged this as a boundary to check, and it's actually fine; equality
  is explicitly included in the rejection. (The problem with AC5 is elsewhere — see Gap 2.)

## Gaps

**GAP 1 (high): the density/mass-balance model narrates a method, not equations — two
defensible implementations diverge numerically, and no AC can tell them apart.**

The spec states ethanol mass is conserved, gives `rho(w) ≈ 1.0 - 0.207w - 0.005w²` (mixture
density vs. ethanol *mass* fraction), and says the ABV↔mass-fraction relationship is solved
"numerically" because it's implicit. What it never states is the actual equation linking
%ABV (a *volume* fraction, per the input contract) to `w`. That conversion needs pure-component
reference densities for ethanol and water, and the spec is silent on which to use:

- Option A: derive them from the *same* formula's own endpoints (`rho(0)=1.0`, `rho(1)=0.788`),
  giving a fully self-contained, closed system: `ABV(w) = 100 · w · rho(w) / rho(1)`.
- Option B: use independent literature reference densities at 20°C (water ≈ 0.9982 g/mL,
  ethanol ≈ 0.7893 g/mL) to convert the *input* ABV to ethanol mass, while using `rho(w)` only
  for the mixture's own volume.

Both are "internally consistent" mass-balance implementations of the prose as written; they
give different numeric answers for the same request. Neither AC2 (a directional `> 2000`
check) nor AC3 (a self-consistency round-trip) can distinguish a correct implementation of
*either* interpretation from an incorrect one — both interpretations pass both ACs, and so
would a third, different-again interpretation, as long as it's monotonic and self-consistent.
This fails the task's bar: implementable "without further guessing" it is not.
→ *Resolution the spec should state*: pick one interpretation explicitly (Option A is the
cheaper, self-contained one — no extra constants to source or transcribe) and add one worked
numerical example with an exact expected value (not just a `>` bound), e.g. "given
`starting_abv=40, starting_volume_ml=1000, final_abv=20`, `final_volume_ml` = *N.NN* ± 0.05."
That pins the formula, not just its direction.

**GAP 2 (high): AC5's "known values" framing is only well-formed for 2 of the 4 solve_for
directions.**

AC5 rejects "when the known values imply `final_abv >= starting_abv`." That works cleanly
when `solve_for` is `starting_volume_ml` or `final_volume_ml` — in both cases `starting_abv`
and `final_abv` are given inputs, so the comparison is checkable before any solve happens.
But when `solve_for` is `starting_abv` or `final_abv`, one side of that exact comparison is
*the value being solved for* — it isn't "known" at request time. The spec doesn't say whether
AC5's check is meant to run pre-solve (impossible for these two directions as stated) or
post-solve (compute the value, then reject the response if it violates the physical
constraint). This is a real testability gap for half of AC5's stated scope, not a nitpick —
a builder has to invent the ordering and error path themselves.
→ *Resolution*: state explicitly that for `solve_for ∈ {starting_abv, final_abv}` the
constraint is checked **after** computing the solved value, and specify what the 400 response
looks like in that case (does it still return 400, or does an already-computed result ever
get discarded and rejected post-hoc? — needs one sentence).

**GAP 3 (medium-high): no validation rule for volume-direction physical plausibility.**

Water-only dilution can only add volume — `final_volume_ml` must exceed `starting_volume_ml`
whenever both are inputs (i.e., when solving for `starting_abv` or `final_abv`). AC4 checks
volume positivity (`<= 0` rejected) and AC5 checks the ABV-monotonicity direction, but nothing
checks the analogous volume-monotonicity direction. A request like `solve_for=final_abv,
starting_volume_ml=1000, final_volume_ml=500` (shrinking via "dilution" — physically
impossible) passes every stated AC4/AC5 rule and its behavior is undefined: does the root
solver diverge, return a nonsensical negative mass fraction, or throw an unhandled 500?
→ *Resolution*: add the missing rule to AC4/AC5 — reject 400 when `final_volume_ml <=
starting_volume_ml` and both are known inputs.

**GAP 4 (medium): AC3's round-trip tolerance is only specified for the ABV output.**

AC3 gives a concrete number — "within 0.01 percentage points" — for the case of round-tripping
through `final_abv`. It then says "Holds for all four solve directions" without stating a
tolerance for the volume-valued round trips (solving back to `starting_volume_ml` or
`final_volume_ml`). Without a stated mL tolerance (absolute or relative — matters differently
at 50 mL vs. 50,000 mL scale), three of AC3's four sub-checks are not falsifiable as written:
there's no number to compare a test's drift against.
→ *Resolution*: state a volume round-trip tolerance, e.g. "within 0.05 mL or 0.005%,
whichever is larger."

**GAP 5 (medium): response JSON schema is unspecified.**

AC1 says the endpoint "returns 200 with the computed value for that field"; AC8 additionally
requires the naive (linear) result and a fixed disclaimer string in the *same* response. No
field names are given for any of the three: is the solved value echoed under its own field
name (`final_volume_ml: …`) or a generic key (`result: …`)? What key holds the naive value
(`naive_final_volume_ml`? `linear_result`?) and the disclaimer (`disclaimer`? `notice`?)? Also
unspecified: output rounding/precision (mL to how many decimals, ABV to how many decimal
places) — relevant since AC3's 0.01-point tolerance implies at least 2 decimals of ABV
precision, but nothing says so directly, and volume precision isn't addressed at all.
→ *Resolution*: give one example response body with real field names and decimal precision.

**GAP 6 (low-medium): `starting_abv == 0` boundary is a dead end the spec doesn't call out.**

ABV is validated as `[0, 100]` inclusive (AC4 rejects only *outside* that range), so
`starting_abv = 0` is accepted as a valid input. But combined with AC5 (`final_abv >=
starting_abv` rejected), a `starting_abv` of exactly 0 means *no* valid `final_abv` exists
(it would have to be negative). Every request with `starting_abv=0` is therefore always
rejected by AC5, regardless of the other inputs — not incorrect, but the spec never says this
is intentional, so a builder can't tell if `starting_abv=0` should instead be excluded
earlier (e.g. required `> 0`) with a clearer, dedicated error message rather than falling
through to the generic AC5 message. Symmetric note: `final_abv = 100` is likewise only ever
rejectable by AC5 (dilution can never raise ABV to 100 from anything `<= 100`), which is
physically correct and doesn't need special-casing — flagging only the `starting_abv = 0`
side since that one produces an always-invalid input silently rather than by evident physics.
→ *Resolution*: one sentence confirming this is accepted-but-always-rejected-downstream
behavior (fine), or tightening AC4 to require `starting_abv > 0` with a dedicated message.

**GAP 7 (low): AC4 doesn't cover all malformed-request shapes.**

AC4 lists: ABV out of `[0,100]`, volume `<= 0`, the `solve_for`-named field present when it
shouldn't be, and missing required fields. It does not state behavior for: `solve_for` absent
from the body entirely; `solve_for` naming something outside the four allowed strings; or a
present field with the wrong type (e.g. `starting_abv: "forty"`). These are foreseeable and
almost certainly meant to be 400s by extension of AC4's spirit, but as written a builder must
infer that rather than read it.
→ *Resolution*: fold these three cases explicitly into AC4's rejection list.

**GAP 8 (low, note only): "real-time" in the description isn't backed by any AC.** No latency
budget or performance AC exists for a description that frames this as a live production-floor
tool. Likely fine to leave to the generic perf-guardrails sweep rather than a bespoke AC, but
worth naming so it's a conscious omission rather than a silent one.

## Summary

8 gaps found: 2 high, 1 medium-high, 3 medium/low-medium, 2 low. The high-severity pair (1:
the density/mass-fraction conversion formula itself is never pinned down, so AC2/AC3 cannot
catch a wrong-but-self-consistent implementation; 2: AC5's validation timing is undefined for
2 of 4 solve directions) are genuine build-blockers for the stated goal of "implement without
further guessing" — not stylistic nitpicks. None of the 8 gaps are currently covered by an
`ASSUMPTION:` line in the spec, so per the unattended-mode contract this run does not yet
qualify as `sound`: these gaps should become explicit `ASSUMPTION:` lines (each with its
default and rejected alternative) before build starts, most importantly Gap 1's worked
numerical example, which is the one thing that actually makes the physics testable.

VERDICT: gaps-found
