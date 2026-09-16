# spec-critic — compliant_tools (round 1)

Engine: codex gpt-5.6-sol, effort high, read-only sandbox.
Graded `.agents/specs/compliant_tools.md` @ status: approved (round 1).

## VERDICT: gaps-found

13 gaps (6 high, 7 medium). No files changed by the grader. Verbatim gap list:

GAP (high): The excise formula assumes every rate is `rate_nzd_per_lal` (spec:80-89), but NZ
Customs applies some alcohol rates per litre of beverage and others per litre of alcohol. The
2026 schedule explicitly contains both bases; GST and the Pae Ora levy also need defined
treatment. A single `lal × rate` formula will produce incorrect duty for several classes.
→ Model `rate_basis` explicitly, apply the appropriate volume, pin every supported
classification/rate/effective date, and state whether GST and levies are excluded.

GAP (high): The description promises subscription enforcement on every `/compliant` and
`/api/compliant` route (spec:15-20), but AC3/AC4 sample only four routes (spec:209-218).
Existing surfaces also include static assets, capture context, profile, products, records,
reports (`compliant_bp.py:28`; `routes/api_routes.py:69-302`). Kill-switch behaviour is
promised but lacks an AC → Require a blueprint-wide invariant and tests covering every
registered endpoint/method, including `compliant_enabled=false`, while preserving existing
ADMIN gates.

GAP (high): Input/output contracts missing for most calculators — discriminators, mutual
exclusion, exact ranges, array limits, output keys, edge behaviour all undecided (spec:76-192)
→ Add a per-calculator schema table: required/optional fields, direction selection, ranges,
exclusivity rules, output shape, boundary behaviour.

GAP (high): Several calculation models contradictory/incomplete. IBU introduces an extra
inverse-1.65 factor and says it is already folded into `bigness`; SO₂ calls KMBS 57.6% but
divides by `0.5674`; the Lyons polynomial is absent; ABW→ABV without SG is undefined; gravity
inverses and refractometer-derived ABV not pinned; partial-cone fill geometry ambiguous
→ Supply one definitive equation per direction, with constants, iteration/tolerance rules,
edge cases.

GAP (high): AC11 lets the builder choose its own worked examples and tolerances (spec:264-270)
— a wrong implementation can select matching expected values → Pin independent input/output
fixtures and numeric tolerances in the spec for every calculator, especially regulatory ones.

GAP (high): The excise catalogue itself is unspecified: beverage classes end in an ellipsis,
rates absent, effective date deferred to "build time" (spec:81-89, 341-343). AC11 checks
metadata presence, not correctness → Include the complete authoritative snapshot and rate
bases in the spec or a named reviewed fixture, plus stale-rate behaviour and update ownership.

GAP (high): `destructive: no` contradicts a downgrade that drops `feature_subscriptions`
(spec:297-298). Once populated, downgrade destroys entitlement data → Mark rollback data loss
as destructive; define backup/restoration or prohibit downgrade after subscription rows exist.

GAP (medium): Description presents Tools as exposing the calculator suite (spec:32-40) but
AC13 requires usable UI only for dilution (spec:278-281) → Decide: API-only, or forms +
displayed results for every catalogue entry.

GAP (medium): Dilution promised relocated with unchanged validation/disclaimers (spec:24-30,
317-318), while the global result contract requires every result to gain `sources` (spec:59-62,
259-262). Current dilution result has no `sources` → State whether additive response fields
are permitted; pin byte-identical payload/error behaviour or the exact allowed delta.

GAP (medium): whistlebird_test grant promised "as part of this work" (spec:20-22) but AC7 only
proves the command would grant it and disclaims prod state → Identify the environment whose
state must change and how it is verified, or reframe the grant as a documented operator action
outside the committed build.

GAP (medium): AC14 says calculator routes read no tenant table, then permits `org_has_feature`
which reads tenant-scoped `feature_subscriptions` → Separate the contracts: solver functions
do zero DB access; HTTP routes do exactly the entitlement lookup and nothing else.

GAP (medium): Relocating the standalone blueprint has an unstated observability dependency —
`app/observability/context.py:18-24` maps the soon-to-be-deleted nested blueprint names, with
assertions in `tests/test_observability_context.py:57-103` → Require deletion of stale
mappings and assert the new routes keep the `compliant` feature label.

## Orchestrator resolution (round 1 → round 2)

Interactive run, but the user delegated iteration to the MR reviewer ("continue the build, I
will have another agent review the MR"). Per `.agents/autonomy.md` the interactive step gets
its substitute: resolve every gap in the spec as an explicit decision/assumption, re-run
spec-critic once. Resolutions:

- **Excise**: model `rate_basis` (`per_lal` | `per_litre_beverage`); ship a small pinned
  `EXCISE_RATES` catalogue with `effective_date` + `source_url` per entry; GST and the Pae Ora
  / health levy explicitly **excluded** and stated in the result; disclaimer says confirm the
  live rate + classification with NZ Customs. Fixtures pinned in the spec.
- **Blueprint-wide gate**: a single `compliant_bp.before_request` entitlement check; new AC
  enumerates every registered `compliant.*` endpoint and asserts 404 when unsubscribed /
  normal when subscribed, plus `compliant_enabled=false` → routes absent entirely. Existing
  `@requires_role(ADMIN)` gates preserved.
- **Per-calculator schema + formula + fixture table**: added to the spec for all Tier-1
  calculators. One equation per direction, constants inline, tolerances pinned.
- **Contradictory formulas**: the ambiguous ones (ibu_tinseth, priming_sugar, strike_water,
  refractometer_fg, chaptalisation, potential_alcohol, acid_addition, so2_addition) are moved
  to a named **Tier-2 fast-follow** (explicit out-of-scope), because shipping a
  half-verified regulatory/chemistry formula is worse than not shipping it. Tier-1 keeps the
  calculators whose single formula is unambiguous and citable now (11).
- **Pinned fixtures**: every Tier-1 calculator gets spec-pinned input→output fixtures +
  tolerance; AC11 references them by table rather than letting the builder choose.
- **destructive**: changed to `yes` (downgrade drops a populated entitlement table);
  migration-safety runs; `downgrade()` emits a warning and the runbook says export first.
- **Dilution parity**: pinned byte-identical — dilution keeps its exact current payload and
  error contract, no added `sources` key. The "every result carries sources" rule applies to
  the **new** calculators only; spec wording corrected.
- **whistlebird_test**: reframed — AC7 proves the CLI command; the grant itself is an operator
  action. The orchestrator runs it against the **local** DB after build and records it in the
  run report; test/prod are operator steps.
- **AC14**: reworded — solver functions perform zero DB access (pure); the HTTP route
  performs exactly one `org_has_feature` lookup and touches no compliance/inventory/execution/
  CRM table.
- **Observability**: new AC — update `app/observability/context.py` (drop the
  `dilution_calculator_*` mappings, ensure `compliant_*` + the new tools endpoints map to
  feature `compliant`), update `tests/test_observability_context.py`.

Re-graded in round 2 below.

---

## Round 2 — VERDICT: gaps-found (9 gaps: 3 high, 6 medium) (all resolved by round 4's final "sound" verdict below — verified 2026-09-13 by findings-sweep)

Round-1 closure audit (codex): 5 gaps fully closed (excise rate_basis design, dilution
parity, whistlebird_test framing, observability mapping, blueprint-gate route inventory),
the rest partially closed. New/persisting gaps:

- (high) Retained Tier-1 contracts had arithmetic/boundary bugs: `standard_drinks`
  inverse fixture wrong by 10x; `gravity_convert` SG→Plato fixture disagreed with the
  cubic; `plato`/`baume` input ranges had no root in the SG interval; div-by-zero
  reachable in `lal` (abv=0), `abv_from_og_fg` (og=1.0), `tank_volume` (flat bottom,
  fill=0).
- (high) **excise catalogue still unpinned** — symbolic R/D/U/W fixtures, no real class
  set or rate values. Codex flagged this as materially the round-1 finding →
  **two-round circuit breaker tripped**.
- (high) Catalogue `inputs` schema vocabulary too thin (no enum/default/exclusive
  bounds/one_of/array bounds); exact per-calculator `inputs` JSON not pinned.
- (medium) UI AC only forced dilution to actually solve/render.
- (medium) "one entitlement DB call" contradicted by the context processor re-querying.
- (medium) nav visibility didn't AND in `compliant_enabled`.
- (medium) AC3 "`< 400`" invariant admits 401/403/405/500, not the required generic 404.
  Already fixed in round 3 (below): AC3 rewritten to assert exactly 404, implemented in
  `tests/test_compliant_subscription_gate.py` (verified 2026-09-15 by findings-sweep).
- (medium) rollback runbook had export but no restore path / no AC.
- (medium) per-calculator disclaimer content not asserted for all new solvers.

## Round 2 → Round 3 resolution

Circuit breaker: it tripped on **excise_duty's rate data**, which the agent cannot
author honestly. Resolution is to **remove `excise_duty` from Tier-1** (→ Tier-2
follow-up, explicitly blocked on a human supplying the reviewed NZ Customs rate table).
That dissolves the repeated gap rather than grinding it a third time. Every other round-2
gap is a concrete, closable spec defect, now fixed:

- Tier-1 reduced to 10 (excise gone). All fixtures recomputed and verified by hand
  (`standard_drinks` inverse → 31.6761 mL; `gravity_convert` SG 1.048 → 11.91 °P /
  6.6412 °Bé; etc.).
- Added **## Catalogue schema vocabulary** (enum, default, exclusive_min/max, one_of via
  `solve`, array `item_fields` + bounds, `text`) and pinned the exact `inputs` object +
  `solve` shape per calculator; AC11 asserts them field-by-field.
- Zero-denominator boundaries closed with explicit exclusive bounds / branch order in
  every contract (`lal` abv>0 to solve volume; `abv_from_og_fg` og_sg exclusive_min
  1.000; `tank_volume` branch on `fill==0` and `cone==0` first).
- Entitlement: one query, cached on `g.compliant_subscribed` by `before_request`; context
  processor reuses it (## Entitlement resolution section + AC7/AC14).
- Nav visibility = `compliant_enabled AND subscribed`, with a flag-off/subscribed test
  (AC7 case c).
- AC3 rewritten: iterate the URL map, build a valid request per rule×method, assert
  **exactly 404** + non-disclosing body.
- Rollback: stated **irrecoverable except from a manual CSV export**, restore command
  given, `downgrade()` warns with row count, AC18 asserts the warning.
- AC13 asserts non-empty disclaimer (≥20 chars, per-calculator keyword) + non-empty
  sources for every new solver.
- AC16 reworked to a pure-function renderer module tested via `node --test` (repo has no
  jsdom) across every Tier-1 calculator + fixture; AC17 is the Python route test.

Re-graded in round 3 below.

---

## Round 3 — VERDICT: gaps-found (5 gaps: 3 high, 2 medium)

Independent fixture audit **passed** (codex recomputed every pinned value within
tolerance). Excise confirmed out of scope — circuit-breaker gap dissolved, not re-raised.
Remaining: (1) catalogue not deep-equality-testable; (2) UI functional wiring untested +
an assumption contradicting AC16's no-jsdom design; (3) unauth `before_request` 404s
before `@requires_auth` (contradiction with AC17); (4) `gravity_convert` baume=20 hits an
exclusive sg bound / derives out-of-range plato; (5) AC14 doesn't test file/network I/O.

## Round 3 → Round 4 resolution (all applied)

- **Appendix A** added: the complete canonical catalogue literal for all 10 calculators.
  AC11 rewritten to deep-equality against it (byte-copied to
  `tests/fixtures/compliant_tools_catalogue.json`). Descriptor key-presence rules pinned.
- UI split: **AC16** (pure `node --test` helpers — `buildFormFields`/`buildPayload`/
  `solveUrl`/`renderResult`/`renderError`, every calculator), **AC17** (served markup +
  control counts), **AC19** (e2e-playwright real browser fill→submit→result for
  `dilution` + `standard_drinks`, + unsubscribed 404 / no nav / old-URL 404). The
  contradicting "stubbed-fetch JS/DOM" assumption removed.
- **Entitlement resolution** rewritten: `before_request` returns without acting when
  `g.current_org_id` is unset (→ `@requires_auth` gives 302/401); only an authed user in
  an unsubscribed org gets 404. AC3 adds an unauthenticated-iteration companion asserting
  never-404.
- "Bounds constrain caller-provided values only; derived outputs may lie outside a
  sibling range" rule added; `gravity_convert` domains aligned (sg 1.0–1.15, baume 0–18).
- **AC14** now = AST import allowlist + sandboxed fixture run (open/socket/urlopen/Popen
  patched to raise).

## Round 4 (final) — VERDICT: sound

Codex confirmed all five round-3 gaps closed; audited Appendix A against the
per-calculator contracts (field names, types, units incl. `null`, bounds, defaults, help,
solve shapes, categories, sources — all consistent) and re-verified every worked fixture
against its formula. General readiness: every AC falsifiable, tenant scoping decided,
destructive downgrade declared+tested, description covered by ACs, external surfaces
absent, out-of-scope substantive. **Build may proceed.**

Round tally: 13 → 9 → 5 → sound. One circuit-breaker (excise rate data) resolved by
descoping to a named Tier-2 follow-up blocked on human-supplied NZ Customs rates.
