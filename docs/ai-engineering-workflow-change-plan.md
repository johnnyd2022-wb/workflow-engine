# Plan: reliable AI engineering within the existing subscription budget

Prepared 8 November 2026. Status: **proposed; configuration changes not applied**. Basis: [research and local audit](ai-engineering-workflows-research-2026-11-08.md), including Reddit anecdotes and current official/source documentation. Scope is engineering tooling, not the founder's business workspace or product roadmap behavior.

Publication update, 9 November 2026: main at `9b8a46e3` already aligns the host test-environment and Alembic guidance in AGENTS.md. Revalidate step 1 against the current checkout and retain completed corrections; the original audit used `6ce608e3`. This MR publishes the proposal and does not activate its workflow changes.

## Intended result

An ordinary change uses one implementer and at most one independent review, with deterministic checks selected by impact. Auth, tenant, inventory, financial, and migration work retains deeper verification. The default spends the existing subscriptions only. No additional paid platform or workflow framework is required.

Implement this as several small tooling changes. Keep the current full verification policy available during migration. Do not let an agent opt out of current mandatory stages merely by citing this proposal.

## 1. Establish one operational truth

Priority: first. Expected effort: one short documentation/tooling session; actual time depends on verifying the local runner.

Files: `AGENTS.md`, `CLAUDE.md`, `.agents/conventions.md`, `.claude/skills/preflight/SKILL.md`, and a concise shared operational reference such as `docs/ai-engineering-operations.md`.

- Reconcile host vs Docker/CI test invocation using config and preflight evidence. Explicitly distinguish host `local.ini`/localhost from container or CI `test.ini` behavior. Document a safe test-database assertion before any write or migration.
- Reconcile the Alembic upgrade command. Verify commands in a disposable test environment; do not run migration reversibility against a shared local database to validate prose.
- Keep the root files focused on exact commands, domain invariants, misleading legacy patterns, and pointers. Proposed starting budget: each wrapper below about 800 words, detailed operations loaded on demand. Treat that as a maintenance target, not an empirical optimum.
- Preserve multi-tenant `org_id`, quantity-write reasons, CSRF/auth requirements, migration precautions, system-finding module ownership, and roadmap/MR conventions.
- Add a small consistency check for the shared command reference, not a brittle test that asserts all prose is identical. Check both tools can discover and read the reference.

Done when: neither agent receives contradictory commands; host and CI examples are separately verified; no credentials are written into docs. Deliver this independently of the rest.

## 2. Introduce explicit risk-based verification

Priority: highest ongoing savings. Files: `.agents/verification-chain.md`, `.agents/autonomy.md`, `.agents/model-routing.json`, and the `new-feature`, `fix-bug`, `review-feature`, `test-author`, `test-evaluator`, `entrypoint`, and Herdr collaboration skills.

Choose the tier **before implementation**, record the reasons, and reconsider after seeing the final diff. File count and line count are hints, never sole criteria.

| Tier | Examples | Required work | AI review |
|---|---|---|---|
| A: mechanical | Prose, typo, isolated cosmetic adjustment with no behavioral or config effect | Inspect diff; applicable formatting/link/render checks; ordinary CI still applies | Author check; no separate model by default |
| B: ordinary behavior | Bounded workflow change outside high-risk boundaries | Acceptance checks, relevant PostgreSQL tests, behavior regression where appropriate, affected lint/scanners, browser flow if UI behavior changed, required CI | One independent consolidated review of the diff and tests |
| C: high risk | Auth/roles, `org_id` scope, shared query helpers, inventory quantities/units/lineage/idempotency, invoicing/calculation correctness, concurrency, schema/data migrations, public ingest/uploads/webhooks, security/production configuration | Tier B plus explicit attack or invariant cases and relevant specialist checks; migration checks on disposable DB; wider dependent tests when shared behavior changes | One independent deep review; add a separate specialist only for an identified gap |

Unknown blast radius promotes the change until inspected. UI rendering of sensitive data is not automatically cosmetic. A small change to tenant-scoped queries remains Tier C. A workflow policy change that controls shipping also requires substantive review.

Universal guarantees: no weakening assertions or scanners for green, no fabricated results, no production writes as a test, no accepted security risk by the agent, no merge/deploy without existing authorization rules, one writer per checkout, and honest skipped/blocked status.

Change the existing chain in these specific ways:

- Repro-test-first remains normal for reproducible behavioral bugs. Remove the automatic separate **pre-fix** test-evaluator process; save failing assertion evidence for the consolidated reviewer. Invoke an early grader for a disputed/nontrivial repro or a Tier C case that needs it.
- Combine build-review, test adequacy, and tenant-boundary review into one independent assignment for Tier B. Tier C requires deeper tenant/security examination, which may fit the same review context or justify a specialist.
- Run browser verification when rendering or interaction changes. Do not author new E2E tests for every acceptance statement already well established at another appropriate layer.
- Run performance measurement for plausible changes to query count, load, large data paths, or an observed regression. Instrument observability when changed behavior needs new diagnostic signals. Neither becomes an unconditional code-writing stage.
- Keep relevant CI mandatory. **Checking** an existing pipeline does not invoke a skill that redesigns CI unless CI itself needs changing.
- Re-review only fixes and their blast radius unless new evidence warrants broader work. Preserve the two-round unresolved-finding limit.

Done when: the contract and all callers agree; a mechanical example does not expand into a full chain; tenant and migration examples cannot select Tier A/B; independent review cannot be silently replaced by author self-review when quota is exhausted. Before that point, keep the current chain authoritative.

## 3. Make model and agent use deliberate

Files: `.agents/model-routing.json`, `scripts/agent_launch.py`, launch configuration where the actual defaults are set. User settings involved: `~/.claude/settings.json`, `~/.codex/config.toml`. Prefer repository/workflow-specific controls over a global change that also affects founder business work.

Proposed policy, subject to account availability and the trial:

| Work | Starting choice | Escalation |
|---|---|---|
| Running lint, collecting test results, checking CI | Direct CLI/script | Ask an agent only to interpret a real problem |
| Clear routine implementation | Claude Sonnet, medium; or current Codex workhorse, medium | Raise capability/effort after a diagnosis of why the first approach failed |
| Ambiguous design or difficult incident | Opus or current capable Codex model, high for that bounded task | Split uncertainty before adding more agents |
| Independent ordinary review | Other provider's capable model, medium | High for Tier C or an identified subtle failure class |
| Simple search/summarization | Direct tools first; smaller model only if useful and available | Preserve exact paths/evidence rather than asking a larger model to redo everything |

Current OpenAI docs list GPT-6.1 Sol, Terra, and Luna among available choices, but model access and the installed client must be checked before using exact IDs. Do not hard-code this date's “latest” into every skill. Existing Codex global medium effort is already sensible; its older stage mapping needs separate validation. [Official pricing/model availability](https://learn.chatgpt.com/docs/pricing).

- Default agent concurrency: **one**. During review, the implementer waits for the result rather than polling or continuing unrelated work on the reviewed tree. A second active model is an intentional review or bounded independent task, not a default fleet.
- Stop automatically spawning a fresh agent for each deterministic stage. Retain a dedicated reviewer context, with read-only restrictions supported by the host.
- Keep role reversal possible: Codex can implement and Claude can review. Capacity is a scheduling constraint, not proof one provider is always better at one role.
- No automatic API-key fallback, paid credits, premium speed mode, unbounded autonomous continuation, or best-of-N runs. At a limit, persist state and wait or hand off useful work to the other pool; required missing review stays missing.
- Check model availability through supported client/account surfaces. Structural routing validation cannot validate an entitlement. Avoid paid diagnostic API calls.

Done when: a dry-run launch plan shows explicit models/effort and agent count, a simulated quota failure produces resumable pending work, and ordinary work does not inherit Opus/high or xhigh merely because of global defaults.

## 4. Reduce skill overlap and align discovery

Files: `.claude/skills/`, `.codex/skills/`, `.agents/skills/`, `scripts/skill_graph.py`, and Claude's entrypoint index. Preserve the existing language reference files; they are not already discoverable skill directories.

- Keep the core engineering entrypoints: fix, feature, review. Make their bodies short dispatch guides to the same risk policy, rather than copies of the chain.
- Share portable procedures through supported skill directories or symlinks. Codex currently documents `.agents/skills/<name>/SKILL.md`; Claude supports its own locations. Pilot **one** shared engineering skill and verify discovery in both running clients before migrating the roster. Avoid duplicate names through overlapping discovery paths. [Codex discovery](https://learn.chatgpt.com/docs/build-skills).
- Keep host-specific permission, hook, and collaboration details in small adapters. Preserve the currently exposed Herdr Breaker skill until replacement discovery is proven.
- Shorten discovery descriptions to a specific task and boundary. Move stage choreography and long examples into referenced material. Entrypoint should route a request without re-auditing all skill wiring every time; CI or an explicit maintenance command can own the graph audit.
- Keep founder operations available, but test a separate launch profile/workspace or explicit-only visibility for unrelated business skills during engineering. Do not edit the symlink targets merely to hide them. Explicit-only Claude skills can affect scheduled callers; audit those first. [Claude controls](https://code.claude.com/docs/en/skills).
- Reduce takeaway/export drift: document canonical sources and generate or check copies when intentionally exporting.

External additions: initially **none required**. First candidates to adapt are Trail of Bits differential-review/property-based-testing ideas and the concise debugging/verification habits identified in the report. For a planned redesign compare existing frontend-design with Impeccable; select one primary design workflow. Record source revision and license for anything copied, including CC-BY-SA obligations where applicable.

Defer token-compression proxies and full Caveman installation until a paired whole-task comparison justifies them. The research includes external evaluations where large advertised token reductions did not become comparable agent-session savings. Preserve raw error evidence and exit status in any output filter. Use research → plan → implement for unfamiliar changes; keep automatic Ralph-style retry loops off the default path.

Done when: both clients discover the intended core workflow, a bug request chooses one front door, business skills remain usable from the intended profile, and graph checks cover the new canonical paths without forcing every utility into an automatic chain.

## 5. Bind handoffs and check receipts to real state

Files: Herdr collaboration skills, `scripts/agent_launch.py`, `.agents/verification-chain.md`, existing handoff/report templates.

Use one compact handoff per task, not a new reporting framework:

```text
Task / user outcome:
Risk tier and reasons:
Acceptance criteria and non-goals:
Branch, base revision, reviewed head or working-tree digest:
Relevant files and spec pointer:
What changed / remaining work:
Checks: command, tree identity, environment, exit status, log path:
Known failures / assumptions / review status:
Next concrete action:
```

Target roughly 300–600 words unless the task needs more. Do not paste whole transcripts or summaries of every clean stage.

- Review a stable commit or snapshot. Do not run an E2E writer alongside a reviewer inspecting the live checkout. Read-only filesystem access also does not prevent a test from mutating the database; use isolated test state and serialize conflicting DB operations.
- Capture a read-only reviewer's final output from the parent process. Preserve the existing rule that it cannot bypass the sandbox to write its own report.
- Reuse evidence only if the checked content and relevant environment match. Changed code invalidates affected tests/review; shared helpers can invalidate many receipts. A skip or collection failure is not a pass.
- Preserve full logs locally and return terse summaries with failures. Build bounded JSON/CLI output rather than spawning an agent to hide routine verbose output.

Done when: a file mutation makes the relevant receipt stale, a reviewer can receive a self-contained assignment without conversation history, and unrelated task context is unnecessary to resume.

## 6. Measure a small real-work trial

Reuse `scripts/skill_metrics.py` and `.agents/metrics/`; do not build a new analytics service. Existing duration data is incomplete, and the current schema does not measure tokens or quota.

Add optional fields: task ID, risk tier, workflow version, provider/model/effort, process count, elapsed time, test receipt, review outcome, accepted/rejected findings, rework rounds, and before/after session/weekly allowance readings when exposed. Where supported, record input/output/cached tokens separately. Unknown values are null, never zero. Keep device/other-work confounding visible. API-dollar estimates must not be presented as subscription charges or exact quota consumption.

Use 6–10 naturally occurring tasks across mechanical, ordinary, and high-risk work. Capture a few current-workflow baselines, then use the proposed loop on comparable tasks. Avoid repeatedly rebuilding the same feature with multiple agents merely for measurement. Where comparing model output needs a controlled case, use a small historical patch in an isolated checkout; do not pretend it estimates production defect rates.

Judge:

- Acceptance criteria and appropriate checks met; high-risk review completed or honestly pending.
- Time and quota per accepted task, accounting for risk, model, context, and other concurrent use.
- Human corrections, false-positive review findings, rework, and subsequently observed regressions.
- Whether fewer agent starts actually reduce total work; whether a smaller model causes extra retries.

Proposed decision rule: keep changes that improve typical task effort/quota with no observed loss of the required checks or acceptance quality. The sample cannot prove equal security or rare-defect rates. Expand only an inconclusive part of the trial. A 20–30% improvement could be a useful **target**, not a forecast or pass/fail statistical claim.

Done when: the founder can see evidence for keeping or rejecting the change, without having to interpret raw token logs. Missing usage telemetry means report elapsed time/rework and disclose the missing quota evidence.

## 7. Review automation only after the default loop works

Inventory configured timers, queued work, loops, and autonomous retry behavior with read-only inspection. The research reviewed repository automation code and hook declarations, **not a complete live scheduler inventory**.

Prefer deterministic error/scanner/CI detection and an AI task only when there is an actionable result. Bound each autonomous task by scope, retry count, and supported run limits; do not assume an API dollar cap enforces a subscription percentage cap. Require an explicit list of what may run unattended. Leave production monitoring coverage in place while reducing repetitive AI interpretation. Queue unfinished work at quota exhaustion.

Done when: unattended usage is attributable to named jobs, no unlimited restart loop consumes a window, and reducing AI jobs does not remove incident detection.

## Rollout, validation, and rollback

Suggested reviewable changes: (1) documentation truth, (2) risk policy and callers with conservative opt-in, (3) launcher defaults and receipts, (4) skill discovery/visibility cleanup, (5) trial results and promotion to default. Combine only changes small enough to review clearly. Do not open an MR or modify global settings merely as part of publishing this plan.

For implementation, run existing routing and skill-graph checks plus focused tests for risk selection, receipt invalidation, one-writer behavior, and quota-failure handling. Check representative cases: CSS-only edit; ordinary CRUD behavior; a one-line missing tenant filter; quantity conversion; migration; documentation-only change; unavailable reviewer. Validate actual discovery in both clients. No application test suite is needed solely for this research documentation.

Rollback by reverting the tooling/policy change and restoring the previous launch profile; keep deterministic CI and product tests in both configurations. If a class of change loses a required check or causes repeated missed findings, restore the deeper route for that class while investigating. Retain trial evidence so the next revision learns from the result.
