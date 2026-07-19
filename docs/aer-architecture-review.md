# AER Proposal — Review Against This Repo's Agentic Design

Reviewer: Claude (Opus 4.8) · Date: 2026-07-19 · Branch: `review/aer-architecture`

Honest assessment of the [AER proposal](./aer-architecture-proposal.md) against what
this repo already runs (`.claude/skills/`, `.agents/`, `scripts/`).

## Headline

The AER document is a **vision whiteboard**; this repo is a **running system** that
already implements ~70% of AER's principles — and in the areas AER hand-waves (autonomy
contract, safety, honest reporting, adversarial test grading) our design is materially
**more mature and more concrete**. AER's genuine value to us is in **three disciplines we
have only partially**: a measurement/evaluation layer, an automated finding→rule learning
loop, and a persistent historical-findings/PR-outcome store. Everything else in AER we
either already have or have deliberately traded away.

## What AER proposes vs. what we already have

| AER concept | Our implementation | Verdict |
|---|---|---|
| Deterministic-first | `preflight.py`, `.semgrep/rules/*` (multitenant, perf, observability, js-security), gitleaks, pip-audit, `perf_triage.py` (fuses semgrep + measured runs), `error_scan.py` (dedup registry), `skill_graph.py`, `e2e_coverage.py` | **We have it, genuinely wired** — not just a principle |
| Specialisation (one skill per discipline) | 38+ skills: security-audit, perf-guardrails, migration-safety, e2e-playwright, observability, test-author, test-evaluator, ci-gate, docs-truth, etc. | **We exceed it** |
| Adversarial verification / different model families | Verification by subagents that didn't write the code; `test-evaluator` adversarially grades tests; Herdr **Claude-Architect / Codex-Breaker** cross-model round-trip | **We have it, and it's real** — AER's is aspirational |
| Mapping graph (skills declare edges; reachability) | `skill_graph.py` builds the reference graph, flags **orphans** (nothing routes to them), unindexed, stale roots; `entrypoint` self-syncs the index | **We have the reachability half**; not the declarative cost/confidence half (see gaps) |
| Self-authoring skills | `skill-smith` scaffolds/audits/registers skills to house standard; `entrypoint` index | **We have it** |
| Closed-loop engineering (build→test→review→sec→perf→PR→CI→repair→merge) | `new-feature` chain: preflight → spec-first → build → migration-safety → security-audit ‖ e2e → perf-guardrails → observability → test-author → test-evaluator → ci-gate → merge-request (watches pipeline, repairs) | **We have it, sequenced with rationale** |
| Learning loop (finding → deterministic rule → future detection without LLM) | Ad hoc: security findings become custom semgrep rules; N+1 findings become perf rules; `prod-sentinel` dedups against a known-issues registry | **Partial** — done by hand, not systematised |
| Repository intelligence layer (shared substrate) | Document-based & per-domain: `conventions.md`, `test-map.md`, `budgets.json`, perf baselines, known-issues registry, quarantine registry | **Partial** — scattered docs, no unified/queryable substrate, no call/symbol graph, no PR-outcome history |
| Evaluation layer (precision/recall/acceptance/escaped defects/cost) | **None** | **Genuine gap** |
| Event-driven runtime (repo event auto-routes) | Invocation-driven: human front doors + cron watchers (`prod-sentinel`, `security-audit`, `suite-warden`, `perf-guardrails`, `docs-truth`, `skill-smith`) | **Deliberate difference**, not a gap (see below) |
| Safety (budgets, rollback, human approval, evidence) | `.agents/autonomy.md`: MR-is-the-gate, never-authorised list, unattended-mode substitutions, circuit breakers (2-round ceiling), per-run work-volume caps, honest-reporting doctrine | **We vastly exceed it** — AER's safety section is one bullet list; ours is an operating contract |

## Where we are clearly *better* than AER

1. **The autonomy contract.** AER says "human approval for high-risk actions." We have a
   full operating contract (`.agents/autonomy.md`): the MR is the only gate, an explicit
   never-authorised list (no prod DB, no merge, no deploy, no external comms, no secret
   exfiltration, **no weakening a gate to get green**), and a rule for unattended runs —
   replace every blocking question with a *written reviewable assumption*. AER has no
   equivalent to "would a reviewer reading the MR be able to reject the assumption you
   made?"
2. **Honest-reporting doctrine.** The whole loop rests on `clean` meaning checked and
   `skipped` meaning stated. AER never addresses the single biggest failure mode of an
   unwatched agent: shading its own report.
3. **Adversarial *test* grading.** AER's "Test Reviewer" bullet ("detects weak
   assertions") is exactly what `test-evaluator` does — but ours runs mutation
   spot-checks, blocks the ship on a `valid` verdict, and never edits code. We built the
   thing AER only names.
4. **Concrete circuit breakers & work caps.** 2-round ceiling per finding; one fix MR per
   `prod-sentinel` run; one MR per finding class in `security-audit`. AER says "execution
   budgets" abstractly.
5. **It runs against a real multi-tenant Flask codebase.** AER is a diagram.

## Real gaps / opportunities worth taking

Ranked by ROI. These are the parts of AER genuinely worth stealing.

### 1. Evaluation layer — the biggest real gap (high ROI)
We cannot currently answer "is `security-audit` finding real bugs or crying wolf?" or
"which skill's findings get accepted vs. reverted?" AER's metrics list (precision, recall,
accepted/rejected findings, escaped defects, latency, cost, developer acceptance) is the
discipline we lack.
- **Cheap first step:** a `.agents/metrics/` ledger. Each scheduled/chained skill run
  appends one row: skill, run date, findings opened, MR outcome (merged / closed /
  amended), escaped-to-prod (cross-ref `prod-sentinel`). No ML — just a CSV/JSONL and a
  `scripts/skill_scorecard.py` that prints acceptance rate per skill.
- **Payoff:** turns "retire poor performers" from a slogan into a decision we can make,
  and tells us which skills earn their token cost.

### 2. Systematise the finding→rule learning loop (high ROI, fits our philosophy)
We already convert findings into semgrep rules by hand. AER's flagship idea — *every
validated finding becomes a permanent deterministic check* — deserves a defined pipeline,
not ad hoc effort.
- **Step:** when a `security-audit`/`perf-guardrails` finding is confirmed and its fix
  merges, `skill-smith` (or a new lightweight `rule-smith` handoff) proposes a semgrep
  rule candidate that would catch the class next time — reviewed via the normal MR gate.
- **Payoff:** directly serves the North Star (reduce the need for LLM reasoning over
  time). This is the highest-leverage idea in the whole AER doc and it's aligned with what
  we already do.

### 3. Historical-findings / previous-PR-outcome store (medium ROI)
AER lists "historical findings" and "previous PR outcomes" in its intelligence layer; we
have `error_scan`'s known-issues registry and the test-quarantine registry, but review
skills start cold on *"what did we already find/reject here."*
- **Step:** persist review verdicts per file/area under `.agents/history/` so
  `review-feature`/`security-audit` can suppress already-rejected findings and re-surface
  recurring ones. This also *feeds gap #1*.
- **Payoff:** fewer repeat false positives; compounding memory.

### 4. Declarative capability graph — partial, lower ROI
AER wants each skill to declare triggers/inputs/outputs/cost budget/confidence thresholds,
with **graph traversal deriving execution order**. Our `skill_graph.py` proves
reachability but ordering is hardcoded in each orchestrator.
- **Honest take:** deriving order from a declared graph is elegant but the hardcoded
  chains in `new-feature`/`review-feature`/`fix-bug` are readable and correct today.
  Worth adding *cost/confidence metadata* to frontmatter (feeds #1), **not** worth
  rebuilding orchestration around graph traversal. Deferred-value, not a gap.

## AER ideas we should *not* chase (deliberate trade-offs)

- **Full event-driven runtime** (every push auto-routes to specialists). Expensive and
  removes the human front door. Our cron-watcher + human-front-door model is a considered
  cost/safety trade, not an oversight. Keep it; maybe add a single lightweight
  post-merge trigger for the metrics ledger.
- **Call graph / symbol graph substrate.** Heavy to build and maintain for one Flask app
  where `conventions.md` + semgrep + `test-map.md` already cover most of what it would
  give us. Adopt intelligence *artifacts* selectively (see #3), not a whole graph DB.
- **"Model-agnostic interchangeable workers"** as a full abstraction. We already get the
  real benefit via Herdr's Claude/Codex split; a generic worker abstraction is overkill.

## Bottom line

Our design is **ahead of AER on execution, safety, and honesty**, and **level on
specialisation, adversarial review, and deterministic-first**. AER's contribution is to
name three disciplines we've under-invested in: **measure ourselves (eval layer)**,
**convert every validated finding into a permanent deterministic rule (learning loop)**,
and **remember prior findings (history store)**. Those three — in that order — are where
we get more efficient and effective. The rest of AER is either already ours or a trade we
made on purpose.

Suggested next move: stand up the `.agents/metrics/` ledger + scorecard (#1)
first, because it's small and every other improvement becomes measurable once it exists.

## Roadmap checklist — closing the gap to frontier

Ordered so each item is independently shippable and later items build on earlier ones.
Effort is not the constraint; correctness and compounding leverage are. Check items off as
they land on this branch.

### Phase 1 — Evaluation layer (measure ourselves) ✅
- [x] `.agents/metrics/` append-only run ledger (`runs.jsonl` / `outcomes.jsonl`) with a
      documented schema
- [x] `scripts/skill_metrics.py`: `record` (append a run), `outcome` (attach MR result),
      `scorecard` (per-skill acceptance rate, findings volume, escaped defects, cost),
      `--check` for CI
- [x] `.agents/metrics/README.md` documenting the schema and how skills append
- [x] DB-free unit test for the scorecard aggregation (falsifiable) —
      `tests/test_skill_metrics.py`, 11 tests green

### Phase 2 — Learning loop (finding → permanent deterministic rule) ✅
- [x] `scripts/rule_candidates.py`: `scaffold` (fixture skeleton + rule template),
      `verify` (proves each learned rule fires on vulnerable.* and stays silent on
      fixed.*), `list` (provenance)
- [x] Finding-born rules live in `.semgrep/rules/learned.yml` with provenance metadata;
      fixtures under `.semgrep/fixtures/<id>/`; seeded with a real one
      (`bize-mass-assignment-from-request` — a checklist item that had no scanner rule)
- [x] `security-audit` §3 rewritten to route through the enforced tool + fixture
      convention (was prose-only, easily skipped)
- [x] `semgrep_learned_rules` CI job makes it a blocking gate on every MR
- [x] DB-free unit tests pin the under-match / over-match / parse logic
      (`tests/test_rule_candidates.py`, 6 tests)

### Phase 3 — Historical-findings store (compounding memory) ✅
- [x] `.agents/history/findings.jsonl` verdict store keyed by a stable, tool-agnostic
      signature (area + kind + normalised evidence — survives line moves & literal churn)
- [x] `scripts/finding_history.py`: `signature`, `decide`
      (new/known-confirmed/recurring/suppress), `record`, `--check`; suppression only ever
      earned by a human verdict; last-verdict-wins
- [x] `security-audit` triage + `review-feature` Step 4 rewired to consult and record
- [x] `data_stores` CI job guards the ledgers; feeds the Phase 1 scorecard
      (accepted-vs-rejected signal); 11 DB-free tests (`tests/test_finding_history.py`)

### Phase 4 — Wiring the ledger live ✅
- [x] `.agents/autonomy.md` gains a **Measure yourself** section — a universal contract
      (every skill references autonomy.md): record the run, record finding verdicts, record
      the outcome when known. Framed as honest-reporting's machine-readable twin.
- [x] Orchestrators wired to append per-stage rows: `new-feature` Step 8, `review-feature`
      Step 5; scheduled `security-audit` §6 sweep records its run
- [x] `skill-smith` audit gains a **Performance** dimension: runs the scorecard, flags
      crying-wolf / escaped-defect / unrecorded skills — makes "improve or retire poor
      performers" actionable instead of a slogan
- [x] **Dropped: static `cost`/`confidence` frontmatter.** Honest call — the ledger
      *measures* real cost (duration) and real confidence (acceptance rate) per run;
      hand-declared estimates would duplicate that and rot. Measured beats declared. (This
      also settles the review's Phase-4 "declarative capability graph" note: not worth
      rebuilding orchestration around; the useful half — metadata feeding the scorecard — is
      better served by measurement.)

Progress log lives at the bottom of this file as each phase lands.

## Progress log

- 2026-07-19 — Phase 1 started.
- 2026-07-19 — **Phase 1 complete.** Evaluation ledger + scorecard shipped
  (`scripts/skill_metrics.py`, `.agents/metrics/`, `tests/test_skill_metrics.py`). We can
  now measure per-skill acceptance rate, findings/run, escaped defects, and cost. Next:
  Phase 4's wiring is what makes skills actually *append* to this — but Phase 2 (learning
  loop) is the higher-leverage North-Star item, so it goes next.
- 2026-07-19 — **Phase 2 complete.** Learning loop is now enforced, not aspirational:
  `.semgrep/rules/learned.yml` + `scripts/rule_candidates.py` prove every finding-born rule
  fires on its bug and is silent on the fix; `semgrep_learned_rules` CI job blocks broken
  ones; `security-audit` §3 routes through it; seeded with a real rule
  (`bize-mass-assignment-from-request`). Each validated finding can now become permanent,
  *tested* deterministic capability — the North Star made mechanical.
- 2026-07-19 — **Phase 3 complete.** Review skills now have memory:
  `.agents/history/findings.jsonl` + `scripts/finding_history.py` suppress
  already-rejected findings and re-surface regressions, keyed by a churn-resistant
  signature. Wired into `security-audit` and `review-feature`; `data_stores` CI job guards
  it. This is also the accepted-vs-rejected feed the Phase 1 scorecard needed.
- 2026-07-19 — **Phase 4 complete. Roadmap done.** The ledger is now live, not just
  built: `.agents/autonomy.md` makes recording runs/verdicts/outcomes a universal contract;
  `new-feature`, `review-feature`, and `security-audit` append rows; `skill-smith` reads
  the scorecard to catch underperformers. Consciously dropped static cost/confidence
  frontmatter — measured cost/acceptance from the ledger supersedes hand-declared numbers.

## Where this leaves us vs. AER

All three real gaps closed, and the North Star item (learning loop) is enforced in CI. The
system now **measures itself** (Phase 1), **turns findings into permanent tested rules**
(Phase 2), **remembers prior findings** (Phase 3), and **acts on the measurements** (Phase
4). What remains AER-side is the deliberately-declined set: full event-driven-on-every-push
routing, a call/symbol-graph substrate, and generic model-agnostic workers — trades we made
on purpose, documented above. On execution, safety, honesty, adversarial review, and now
self-measurement and compounding learning, this repo is at or past the frontier the AER doc
describes — with the advantage that ours runs.
