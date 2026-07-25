# Spec Critic — dilution_calculator (Round 3 / circuit-breaker pass)

Spec: `.agents/specs/dilution_calculator.md` (status: `approved-unattended`)
Scope per task: grade ONLY whether the two round-2 patches close GAP 1 (division by zero)
and GAP 2 (rounding/precision) cleanly, plus a tight sanity pass on what those edits could
have disturbed. Not re-litigating rounds 1-2 beyond that.

## Patch (a): AC5 explicit divisor check — closes GAP 1

The new AC5 clause adds, on top of the existing pair rule: reject with 400 if
`solve_for=final_volume_ml` and `final_abv == 0`, checked explicitly rather than inferred.
Re-derived independently rather than trusting the spec's own proof (the same discipline that
caught GAP 1 last round):

- `solve_for=final_volume_ml` → divides by `final_abv`. **This is the only unguarded case.**
  Confirmed via round 2's exact counter-example
  (`{starting_abv:40, starting_volume_ml:1000, final_abv:0}`): `0 >= 40` is false, so the
  pair rule alone doesn't reject it. The new explicit `final_abv == 0` check now does. Fixed.
- `solve_for=final_abv` → divides by `final_volume_ml`, a *given* value directly guarded by
  AC4's `volume <= 0` rule. Safe independent of AC5.
- `solve_for=starting_volume_ml` → divides by `starting_abv`, a *given* value. Re-derived:
  this branch's pair check is "reject if `final_abv >= starting_abv`"; if `starting_abv=0`,
  passing requires `final_abv < 0`, which AC4's `[0,100]` range makes impossible — so
  `starting_abv=0` can never reach the division on this branch. Safe, matches the spec's own
  claim and round 2's independent confirmation ("that direction got lucky").
- `solve_for=starting_abv` → divides by `starting_volume_ml`, a *given* value directly
  guarded by AC4. Safe.

So exactly one of the four directions needed an explicit divisor guard, and the patch adds
exactly that one — no more, no less. The spec's own re-derived justification text (AC4's
`volume <= 0` rule covers two directions, the `c >= a` pair rule covering `starting_abv==0`
covers the third) matches this independent check term-for-term. **GAP 1 is closed cleanly;
no symmetric divisor==0 hole was missed.**

Boundary check on the fix itself: AC4 already constrains ABV to `[0,100]`, so `final_abv`
can't be negative — checking `== 0` (rather than `<= 0`, which round 2's *suggested*
resolution used) is equivalent in effect and doesn't under-guard.

One interaction worth confirming didn't regress: the spec's stated degenerate "diluting
water with water" case (`solve_for=starting_abv`, `final_abv=0` given, solved down to
`starting_abv=0`) still works — that branch's divisor is `starting_volume_ml`, not
`final_abv`, so the new check (scoped only to the `solve_for=final_volume_ml` branch)
doesn't accidentally reject it. Confirmed no regression.

## Patch (b): AC9 full-precision response fields — closes GAP 2

AC9 lists exactly the numeric fields named in AC1's response contract: `solved_value`, the
four echoed `starting_abv/starting_volume_ml/final_abv/final_volume_ml`, `water_to_add_ml`,
`water_to_add_naive_ml` — and states none are server-side rounded. Cross-checked against
AC1's full field list: `solved_field` (string) and `disclaimer` (string) are correctly
omitted, nothing numeric is missed. This directly implements round 2's suggested resolution
verbatim ("state that response numeric fields are returned at full float precision") and
removes the ambiguity that made AC3's `1e-6` round-trip tolerance builder-dependent.
**GAP 2 is closed cleanly.**

## Sanity pass on what the edits could have disturbed

- **AC4/AC5 cross-references**: AC5's new clause references "AC4's `volume <= 0` rule" —
  matches AC4's actual wording. Internally consistent, no broken reference.
- **AC5 self-consistency**: minor wording tension only — AC5 opens with "one uniform,
  direction-independent rule" and then adds "Additionally" a second explicit divisor check,
  so it's now technically two rules stacked, not one. This doesn't create builder ambiguity
  (both checks are stated explicitly and are each independently testable), so not scoring it
  as a gap — flagging as a cosmetic wording nit only.
- **AC numbering/ordering**: AC9 was appended with the next free number but inserted in
  document order between AC5 and AC6 (reading order is now AC1-5, AC9, AC6-8). This is
  untidy — a reader skimming top-to-bottom hits "AC9" before "AC6" — but every AC is
  identified by its own label regardless of position, so it doesn't create testability
  ambiguity or a broken cross-reference. Cosmetic only; not scored as a gap, but worth a
  trivial reorder (move AC9 after AC8, or renumber sequentially) before this spec is used as
  a long-term reference doc.
- **AC3 symmetry claim re-verified**: "Holds symmetrically for all four solve directions" —
  re-checked against the corrected AC5, still true; the divisor fix doesn't change which
  *valid* inputs round-trip, it only rejects the one input that previously crashed.
- **Nothing else in Description, Users & permissions, Data model, External surfaces, Out of
  scope, or the other Assumptions was touched by these two edits** — no ripple checked
  further per task scope.

## Verdict rationale

Both round-2 gaps are closed by the patches as written, independently re-derived rather than
taken on faith. No new correctness gap found. The only residual items are two cosmetic
nits (AC5's "one rule" framing now stacks two checks; AC9 sits out of numeric order in the
document) — neither blocks a builder from implementing this spec unambiguously, so neither
is scored as a `gaps-found` item under this skill's gap categories (untestable AC, undecided
tenant scope, silent destructive change, description/AC mismatch, hidden external surface).

VERDICT: sound
