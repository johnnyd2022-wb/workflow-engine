# AI engineering workflows on two $20 subscriptions

Research date: **8 November 2026**. Scope: engineering this existing Flask/PostgreSQL/vanilla-JS SaaS with Claude Code, Codex, and Herdr. Companion: [implementation plan](ai-engineering-workflow-change-plan.md). Repository source snapshots: [research manifest](ai-workflow-source-snapshots-2026-11-08.json).

Publication note, 9 November 2026: the local audit below describes checkout `6ce608e3`, inspected during the research. Before opening the MR, this branch was updated to main at `9b8a46e3`. That newer base already aligns AGENTS.md with the host test-environment and Alembic instructions, so the original instruction-drift finding is historical and that part of plan step 1 needs revalidation rather than repeating the fix. Inventory counts, file sizes, and metrics below are also research-time snapshots.

## Recommendation

Keep the engineering safeguards; simplify the machinery around them. Default to **one scoped task, one implementing agent, relevant executable checks, and one independent review when the risk justifies it**. Use the second subscription as a separate capacity pool and a source of independent scrutiny. Avoid making every task pay for a specification committee, multiple test graders, a browser audit, performance work, observability instrumentation, and a new agent process for each step.

The highest-value changes here are correcting contradictory setup instructions, replacing the universal AI verification chain with explicit risk tiers, lowering routine effort, and measuring completed work against quota consumption. Installing another comprehensive workflow framework would mostly duplicate infrastructure we already have.

This is a reasoned recommendation, **not a measured claim that one workflow is universally best**. No controlled comparison of these workflows on this repository was run. Vendor documentation establishes supported behavior; source review exposes workflow overhead; Reddit provides useful failure reports and counterexamples, not reliable savings percentages.

## Subscription reality

The user's budget is $40/month in stated subscription prices. Anthropic calls its $20 US monthly plan **Pro**. OpenAI's $20 plan is **ChatGPT Plus**, with Codex included; OpenAI Pro is a different tier. These names matter when reading advice written for people with much larger allowances. Regional prices and taxes can differ. [Claude Pro](https://support.claude.com/en/articles/8325606-what-is-the-pro-plan), [OpenAI pricing](https://learn.chatgpt.com/docs/pricing).

Claude Pro has five-hour and weekly limits, shared between Claude and Claude Code. Moving research into Claude chat does not create a second Claude allowance. Claude API access is separately billed, and its support documentation warns that an `ANTHROPIC_API_KEY` can select API authentication instead of subscription use. [Claude subscription access and limits](https://support.claude.com/en/articles/11145838-use-claude-code-with-your-pro-max-or-ultra-plan).

Codex local and cloud activity share the plan allowance; weekly limits can also apply. Official message ranges are estimates, not a task budget. Use `/status` and the usage dashboard rather than assuming a fixed number of productive hours. Model, effort, context, and speed settings affect consumption. [Codex pricing and usage](https://learn.chatgpt.com/docs/pricing).

**Operating policy proposed here:** subscription authentication, standard speed, no automatic purchase of credits or API fallback, and no assumption that two subscriptions support continuous unattended engineering. Preserve some capacity for incidents. Check the actual account entitlement before changing model routing; this research did not inspect billing credentials or prove which models these accounts can access.

## What the official material supports

### Give the agent a verifiable assignment

OpenAI recommends supplying a goal, relevant context, constraints, and a definition of done. For us, that means a symptom or user outcome, one existing implementation to follow, important tenant/data rules, and the checks that establish success. A small clear task often needs no separate planning ceremony. [Official OpenAI best practices](https://learn.chatgpt.com/guides/best-practices).

Anthropic's current guidance emphasizes runnable verification, short project instructions, and enforcing genuinely invariant rules with deterministic tooling. It also explains that subagents spend the same allowance and must gather their own context. Fresh eyes can help; extra agents do not inherently produce smarter answers. [Claude Code best practices](https://code.claude.com/docs/en/best-practices).

### Manage relevance, not just context capacity

Anthropic frames context as a limited resource whose usefulness depends on selection and retrieval. Keep durable pointers and retrieve the relevant implementation, rather than injecting whole subsystems or transcripts. [Context engineering](https://www.anthropic.com/research/effective-context-engineering-for-ai-agents).

A particularly relevant July 2026 update reports that Anthropic removed over 80% of its system prompt for advanced models without measurable loss on its coding evaluations. That result is specific to its harness and evaluations; it does not prove we can delete 80% of our rules. It does justify re-evaluating overlapping instructions and model-era workarounds. [New context-engineering guidance](https://claude.dev/blog/the-new-rules-of-context-engineering-for-claude-5-generation-models/).

Google's CLI also supports project context files and modular context loading. The reusable idea is a discoverable project memory structure, not a reason to introduce a third provider. [Gemini CLI project context](https://geminicli.com/docs/cli/gemini-md/).

### Use progressive disclosure for skills

The Agent Skills standard separates discovery metadata, instructions, and supporting resources. Installed skills do **not** imply every full skill body enters every prompt. The metadata listing and whatever bodies or references are actually loaded still consume context. [Agent Skills specification](https://agentskills.io/specification).

Codex documents `.agents/skills` as its current repository discovery location and supports symlinked skill folders. Its initial skill listing has a context budget and can shorten descriptions or omit entries. That is a reason to keep descriptions precise and check discovery in the running client. [Build skills](https://learn.chatgpt.com/docs/build-skills).

Claude distinguishes automatic skills from explicitly invoked ones. `disable-model-invocation: true` removes a skill's description from automatic context, but also affects subagent preloading and session-scoped scheduled invocation. Do not apply it blindly to skills used by automation. [Claude skill invocation controls](https://code.claude.com/docs/en/skills).

### Spend deliberation where it prevents rework

Anthropic recommends matching models to the work, limiting unused MCP integrations, and keeping unrelated tasks out of the same session. Current MCP definitions can be deferred, so claims that every connector always injects its full schema are outdated. Inspect actual context. [Claude cost guidance](https://code.claude.com/docs/en/costs).

Our inference: start ordinary implementation at medium effort; escalate for unclear architecture, tricky concurrency, tenant boundaries, financial quantities, and migrations. A more capable model that gets a difficult task right can be cheaper overall than repeated failed attempts with a smaller one. Avoid changing model on every mechanical step simply to chase a lower nominal rate.

### Durable state helps; repeated orchestration has a price

Anthropic's long-running-agent work uses explicit progress records, incremental work, and environment setup so a later session can continue reliably. We should retain a compact task state and reproducible checks, not the entire conversation. [Long-running harnesses](https://www.anthropic.com/research/effective-harnesses-for-long-running-agents).

Its research system reported multi-agent token consumption around 15 times ordinary chat in that particular setting. That is **not** a multiplier for a two-agent code review, nor a coding benchmark. It demonstrates why added agents require an economic justification. [Multi-agent research system](https://www.anthropic.com/research/multi-agent-research-system).

## Community anecdotes: what people actually report

These are original Reddit discussions, including comments, rather than generated thread summaries. Thread ages and search dates can disagree, so the links and access date are more reliable than precise relative ages. The sample is purposeful, small, and biased toward people posting about problems.

| Discussion read | Experiences and disagreement | Practical implication here |
|---|---|---|
| [Workflow by task size](https://www.reddit.com/r/ClaudeCode/comments/1wmax2u/whats_your_actual_claude_code_workflow_by_task/) | The author describes a small feature dragging on under repeated reviews. Replies include support for Matt Pocock's workflows and test-first Superpowers-style development. | Match process to ambiguity and impact; structure can help without requiring the same ceremony for every change. |
| [Still using Superpowers?](https://www.reddit.com/r/ClaudeCode/comments/1u2tqud/are_you_guys_still_using_the_superpowers_skill/) | Some retain it for brainstorming, browser previews, and large changes. Others prefer lean rules and hooks or question whether older skill instructions still help new models. | Keep useful individual practices; compare the current version rather than judging only by older experience. |
| [Quota burn after Superpowers](https://www.reddit.com/r/OpenaiCodex/comments/1v3xyky/my_weekly_usage_limit_was_being_burned_almost/) | The author reports a dramatic reduction after removing the plugin. Replies question versions and report similar depletion without the plugin. | A plausible overhead signal, not proof of causation or a transferable savings percentage. Instrument our own workflow before blaming a plugin. |
| [Tips for Plus users](https://www.reddit.com/r/codex/comments/1u8a3en/tips_to_survive_as_a_plus_user/) | Useful examples include oversized coverage output and task scoping. Comments dispute frequent compaction and whether a cheaper model reduces total work. | Bound tool output. Do not adopt arbitrary compaction thresholds, obsolete model prescriptions, or account-rotation suggestions. |
| [Claude Pro users making usage last](https://www.reddit.com/r/ClaudeCode/comments/1x3fz2l/claude_pro_users_how_are_you_actually_making_your/) | The author reports rapid depletion even with Sonnet medium. Replies disagree about the cause and suggest focused work, fewer agents, model selection, and handoff files. | Medium effort is not a guaranteed allowance fix. Track context, agent starts, retries, and quota together. |

The recurring theme is **process proportionality**. Successful anecdotes do not agree on one model, skill pack, or compaction percentage. They do repeatedly expose expensive exploration, broad requests, redundant reviews, and context-heavy sessions. Forum complaints also warn against promising predictable all-day capacity from a $20 plan.

## Measured evidence that challenges token-saving claims

JetBrains ran a paired evaluation of the Caveman style skill on SkillsBench with Claude Code and Sonnet 5 at low effort. It reported about **8.5% fewer output tokens**, rather than the advertised 65% prose-example saving, with no statistically detectable quality difference in that sample. That does not prove equivalent quality. It also does not measure today's entire Caveman package, which now includes input compression and routing features. The important distinction is between compressing narration and reducing a complete coding session. [JetBrains Caveman evaluation](https://blog.jetbrains.com/ai/2026/07/speak-to-ai-agents-like-cavemen-tosave-tokens/).

In another pinned-version evaluation, JetBrains tested RTK v0.43.0, a command-output compression proxy. It reported a median **7.6% higher cost at low effort** and essentially no cost change at high effort, despite the tool's own large savings counter. These are API-cost results from a specific harness/model/benchmark, not measurements of our subscription quota or every later version. They support measuring the whole task, retries and cache included, rather than trusting a compressor's raw before/after character count. This research reviewed that evaluation, not RTK's implementation. [JetBrains RTK evaluation](https://blog.jetbrains.com/ai/2026/07/rtk-claude-code-token-savings/).

Two related workflow patterns deserve explicit treatment. HumanLayer's **research → plan → implement** approach puts human scrutiny on the understanding and plan before expensive code generation. Use it for unfamiliar or cross-cutting work, without turning its older context-utilization heuristics into universal rules for current models. [Original RPI field report](https://www.humanlayer.dev/blog/advanced-context-engineering). **Ralph Loop** automatically resubmits the task through a stop hook until a completion condition or iteration limit. It can help a well-specified, mechanically verifiable task, but is not our default on limited subscriptions: use a hard iteration bound and an external correctness check, not the model's completion phrase as proof. [Official Ralph Loop description](https://claude.com/marketplace/plugins/ralph-loop).

## Published skills and frameworks reviewed

Selection combined official collections, visible GitHub adoption, the skills.sh leaderboard, and frameworks appearing in the discussions above. Popularity is a discovery signal, not an effectiveness ranking. As accessed, skills.sh prominently listed `find-skills`, Matt Pocock's interviewing skills, and `agent-browser`. Its counters are registry-specific, not audited numbers of successful engineering tasks. [Skills directory](https://www.skills.sh/).

Stars below are rounded GitHub API snapshots from this research, not projected figures. The manifest records full revision IDs and exactly which source files were retrieved. Review depth was README plus selected skill bodies; this was not an exhaustive audit of every script, dependency, reference, or release, and no downloaded skill was installed or executed.

| Collection / adoption snapshot | What was examined and what it contributes | Judgment for this setup |
|---|---|---|
| [Anthropic skills](https://github.com/anthropics/skills), ~189k stars | `skill-creator`, `frontend-design`, `webapp-testing`. Concrete examples of skill evaluation, visual direction, and Python browser workflows. | Strong references. Keep the already-enabled frontend-design plugin for intended design work. Adapt testing examples to our established fixtures and readiness checks. |
| [OpenAI plugins](https://github.com/openai/plugins), ~7.8k; [legacy skills](https://github.com/openai/skills), ~28.6k | Current frontend testing/debugging and security diff-scan entrypoints; legacy Playwright and GitHub CI repair skills. The legacy README explicitly redirects to plugins. | Use current official sources selectively. GitHub Actions instructions do not fit our GitLab CI. Security tooling has prerequisites and should not become a mandatory dependency for every task. |
| [Superpowers](https://github.com/obra/superpowers), ~314k | Discovery policy, systematic debugging, verification before completion, and subagent-driven development. Current source explicitly offers inline execution, bounded reviews, and avoiding redundant test runs. | Useful debugging and evidence habits. Do not enable the whole framework by default over our existing one. Its broad skill-invocation policy and per-task agent/reviewer option can still add substantial overhead. |
| [Matt Pocock skills](https://github.com/mattpocock/skills), ~318k | `grill-me`/`grilling`, `grill-with-docs`, diagnosing bugs, and TDD. Short wrappers delegate to other skills; interviewing resolves a decision tree; TDD emphasizes behavior and public interfaces. | Best ideas to adapt: questions when requirements are ambiguous, a fast feedback loop, behavior tests. Avoid mandatory exhaustive interviewing or fact-finding subagents on already-clear work. |
| [Compound Engineering](https://github.com/EveryInc/compound-engineering-plugin), ~26k | `ce-code-review` and `ce-compound`. Current review supports lite/focused paths; knowledge capture can decline routine lessons and supports lightweight mode. | A good conceptual fit: risk-based review and the cheapest durable lesson. Full paths still involve many references and reviewers. Borrow the selection logic rather than adding another orchestrator. |
| [GSD Core](https://github.com/open-gsd/gsd-core), ~11.3k; [old GSD](https://github.com/gsd-build/get-shit-done), ~64.2k, archived | Successor README, quick-task skill, configuration signals. Durable phase state, fresh contexts, and budget/model controls. Even quick mode describes planner and executor agents. | Relevant for large staged work, but overlaps with Herdr, specs, worktrees, and our existing reports. Adopt compact resumable state; defer the framework. |
| [BMAD](https://github.com/bmad-code-org/BMAD-METHOD), ~55.1k | README and v7 build entrypoint/workflow. Current design scales between oneshot/full routes and excludes trivial maintenance. README distinguishes stable v6.12 from changing v7 preview. | More adaptive than older descriptions suggest. Still a poor default addition to this mature setup; introduces another process/config layer. No reason to migrate to a preview for token savings. |
| [Trail of Bits skills](https://github.com/trailofbits/skills), ~8.1k | Differential review and property-based testing. Risk and blast-radius analysis; properties for calculations and transformations. | Highest-value specialist candidate: adapt focused security review and consider properties for unit conversion, quantity conservation, idempotency, and DAG invariants. Check actual applicability and license first. |
| [Vercel agent skills](https://github.com/vercel-labs/agent-skills), ~33.7k | Web design guidelines and collection scope. Small entrypoint retrieves a larger external checklist. Much of the pack is React/Next/Vercel-specific. | Web interface checks can help; React/Next/deployment guidance does not fit our stack. A short skill file is not necessarily a cheap execution. |
| [agent-browser](https://github.com/vercel-labs/agent-browser), ~47.1k | Browser skill entrypoint and CLI overview. Focused browser operation with referenced workflow material. | Optional experiment if browser context is demonstrably costly. We already have Playwright; do not maintain a second browser stack without a measured gain. |
| [planning-with-files](https://github.com/OthmanAdi/planning-with-files), ~27.9k | Main skill: persistent planning/recovery, lifecycle hooks, completion gating options. The reviewed body alone is about 6,000 words. | Durable state is valuable; the full hook/reinjection system overlaps with our plans and handoffs. Use a short state file first. |
| [Impeccable](https://github.com/pbakaus/impeccable), ~105.7k | Main Claude skill and README. Targeted design moves, critique, accessibility/UX audit, persistent design vocabulary. | Worth testing for a deliberate UI redesign. Choose one primary design skill per task; layering it onto page-design and frontend-design risks competing aesthetic instructions. |
| [Karpathy-inspired guidelines](https://github.com/multica-ai/andrej-karpathy-skills), ~230.7k | README, CLAUDE.md, and `karpathy-guidelines`: expose assumptions, keep changes surgical, avoid speculative complexity, define verifiable outcomes. This is a community interpretation of his observations, not evidence of his authorship or endorsement. | Sensible compact principles; largely already present in our instructions. Do not install duplicate global rules or make every ordinary implementation decision require a question. |
| [Caveman](https://github.com/JuliusBrussee/caveman), ~118.2k | README and `skills/caveman/SKILL.md`. The current voice skill preserves exact technical payload and negations; the wider package also offers compression, routing, hooks, and browser features. | Concise plain language already fits our needs. Do not infer whole-session savings from prose compression or silently introduce the larger proxy/routing stack. Test any optional compression on our actual logs. |

### Specific quality findings from source review

**Skill size is misleading without following its entrypoints.** Matt's `grill-with-docs` wrapper calls two other skills; Vercel's web guidelines fetch an external rules document; BMAD renders a workflow. Count activated references, tools, and agent contexts, not just `SKILL.md` lines. [Matt wrapper](https://github.com/mattpocock/skills/blob/main/skills/engineering/grill-with-docs/SKILL.md), [Vercel entrypoint](https://github.com/vercel-labs/agent-skills/blob/main/skills/web-design-guidelines/SKILL.md), [BMAD build](https://github.com/bmad-code-org/BMAD-METHOD/blob/main/skills/bmad-build/SKILL.md).

**Official examples still need technical review.** Anthropic's webapp-testing sample repeatedly prescribes `networkidle`. Playwright's own documentation discourages it for test readiness and recommends web assertions. For our telemetry-enabled SPA, use a concrete visible state or the specific relevant response. Do not import a vendor skill verbatim merely because it is official. [Sample skill](https://github.com/anthropics/skills/blob/main/skills/webapp-testing/SKILL.md), [Playwright readiness guidance](https://playwright.dev/python/docs/api/class-page#page-wait-for-load-state).

**Modern frameworks are not uniformly agent-heavy.** Current Superpowers documents an inline route; current Compound Engineering has review-depth gates. Forum reports about older versions do not establish the behavior or cost of today's versions. Nevertheless, adding either entire framework would duplicate this repository's orchestration. [Superpowers execution choices](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md), [Compound review](https://github.com/EveryInc/compound-engineering-plugin/blob/main/skills/ce-code-review/SKILL.md).

**Evaluate a skill against its absence.** Anthropic's creator includes test prompts, baseline comparisons, and performance evaluation. Borrow that discipline in small samples. A skill earns a place by improving outcomes or reducing total work on our tasks, not by making the agent produce a longer plan. [Skill creator](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md).

**Recommended adoption order:** keep and simplify local skills; adapt debugging/verification habits; pilot focused differential review and property-based testing; optionally compare one design skill. Defer wholesale Superpowers, GSD, BMAD, Compound Engineering, browser-stack migration, and general skill-directory installation. Document/file-generation skills can remain available for explicit business work without joining the engineering path.

## Audit of our current setup

These are observations from this checkout and selected user configuration, not assumptions about generic Claude/Codex installations. Credentials and conversation databases were not read. Global settings and launcher overrides may differ from a process already running.

| Evidence | Finding | Consequence |
|---|---|---|
| `AGENTS.md`; `CLAUDE.md`; `app/config/{local,test}.ini`; `scripts/preflight.py` | AGENTS tells a host user to set `ENVIRONMENT=test`; CLAUDE explains that the host should leave it unset because `test.ini` uses `host.docker.internal`. AGENTS also points to `workflow upgrade-db`; CLAUDE/preflight point to Alembic. | The two agents can follow different operational instructions. Local source corroborates CLAUDE's distinction; no live DB or migration was run for this research. Correct and consolidate first. |
| Root instruction files | AGENTS is 7,624 bytes; CLAUDE is 8,739 bytes, with extensive overlap and different updates. | Main issue is conflicting truths and maintenance, not just size. Move detailed reference material behind links and share one canonical operational reference. |
| `~/.claude/settings.json` | Persisted default `model: opus`, `effortLevel: high`; frontend-design enabled. | Routine interactive work starts with expensive deliberation unless the running launcher/session overrides it. Test Sonnet medium as a repo workflow default before changing every global task. |
| `~/.codex/config.toml`; `.agents/model-routing.json` | Global Codex default is `gpt-6-sol`, medium. Stage routing still maps `sol` to `gpt-5.6-sol`; several stage explanations assume older model behavior. | Interactive and stage execution differ. Validate identifiers and capability from the installed clients; a JSON-valid mapping is not proof that a model is available. |
| `.agents/verification-chain.md`; `fix-bug` | Bug fixes and features share the full applicable chain. The fix path includes repro evaluation, build review, tenant audit, final test evaluation, plus other applicable stages. | Several fresh contexts inspect overlapping evidence. Keep the checks, but batch review and make extra stages conditional on risk. |
| `.agents/model-routing.json` | Build, migration-safety, and findings-sweep use xhigh; many other stages use high. | The configuration already recognizes two quota pools, but heavy reasoning remains the default across much of the chain. |
| `.claude/skills/` inventory | 54 exposed skills: 34 local directories and 20 founder-ops symlinks. All exposed `SKILL.md` bodies total 477,961 bytes; local bodies 365,687 bytes. Entrypoint alone is 567 lines. | These are disk-size measurements, **not measured prompt tokens**. Still, broad descriptions and routing/chain overlap warrant a visibility and invocation audit. |
| `.codex/skills/`; `.agents/skills/` | Checkout has one Codex Breaker skill; `.agents/skills` contains language reference Markdown files, not a shared engineering skill roster. | The two tools do not have symmetric local workflow discovery. Preserve the currently visible Breaker integration while validating current supported paths. |
| Global hooks and Codex config | Claude hooks cover Herdr state and mission-control events. No MCP servers are configured in the inspected Codex TOML; this session exposes connected app tools through its host. | Do not blame MCP for the observed costs or remove integration hooks blindly. Inspect actual runtime context and hook output before proposing changes. |
| `skill_metrics.py scorecard` | 262 recorded stage rows. Most acceptance and duration fields are missing; findings-sweep shows zero mean duration. No quota/token fields in the documented run schema. | Current data cannot demonstrate cost effectiveness. Findings volume is not accepted value, and missing escaped-defect records do not prove zero defects. |
| Existing guards | `agent_launch.py --check` returns `routing OK`; `skill_graph.py --check` finds all 54 skills reachable and indexed. | Wiring is structurally sound. The missing question is whether the selected work and number of stages are worthwhile. |

### Preserve these strengths

Real PostgreSQL tests; tenant isolation and quantity-write invariants; preflight as a deterministic script; existing CI scanners; explicit migration checks; file-backed review evidence; one writer per worktree; read-only review where supported; reproducible findings; and the two-round circuit breaker. The change plan must not turn quota exhaustion into a passing security review.

One refinement: a read-only reviewer can still inspect a moving tree if it runs beside an E2E stage that writes tests. A one-writer rule prevents edit collisions but does not create a stable review snapshot. Bind review and test receipts to a commit or content digest and invalidate them when relevant files change.

## Proposed daily workflow

1. **Scope:** state one user outcome, acceptance checks, relevant paths, constraints, and non-goals. Read only enough to choose a risk tier. A one-line auth change can be high risk.
2. **Prepare:** preflight once for the capabilities needed. Use the existing test environment instructions after consolidation. Do not start unused observability or browser infrastructure.
3. **Implement:** one agent owns the change. For a reproducible behavioral bug, show the regression fails for the right reason, then fix it. Test new behavior and meaningful boundaries; do not add implementation-mirroring tests to reversible prose or cosmetic edits.
4. **Verify:** run affected tests/lint/scanners and relevant CI. Persist full logs but return concise failures, counts, and exit status. Reuse results only for the same relevant tree, command, configuration, and environment.
5. **Review:** for ordinary behavior changes, use the other provider once against the spec, diff, changed tests, and receipts. Batch correctness, tenant concerns, and test adequacy in that review. High-risk changes get the relevant specialist depth. A reviewer may rerun any test needed to investigate a concrete concern.
6. **Close:** fix supported findings, rerun affected checks, then obtain targeted re-review. Stop after two unsuccessful rounds on the same issue. Record what is verified, what remains open, and the review status. The existing human merge/deploy boundary remains.

For routine tasks use whichever pool has capacity and whose model succeeds on that class of work. Claude need not always plan and Codex need not always review. The author does not provide the only independent review of its own high-risk change. Prefer task-boundary handoffs over frequent provider switching.

## Efficiency rules worth keeping

- Optimize **accepted, safe changes per quota and founder hour**, not tokens per answer or findings per reviewer.
- Use a small plan when there is real uncertainty; use a written spec for significant product choices. Never regenerate an accepted spec just because another agent started.
- Search paths and symbols before reading large files. Keep giant diffs, coverage tables, HTML dumps, and traces on disk; retrieve relevant sections.
- Keep related work in the same session while it is useful. Start fresh for unrelated work or a clean independent review. Use automatic compaction normally; preserve decisions and next actions when manually compacting. No universal 60% reset rule.
- Run deterministic scripts directly. Starting another LLM merely to run Ruff or read a CI status adds little value.
- Schedule deterministic detection where possible; invoke AI on a meaningful change, failed check, or explicit request. An idle UI pane is not itself evidence of token use; repeated autonomous turns and scheduled runs are.
- Preserve domain knowledge in tests, constraints, and concise design decisions. Avoid rewriting a learning into several instruction files and skills.
- Pin reviewed third-party sources; inspect scripts/hooks, external access, transitive references, licensing, and overlap before adoption. This is ordinary dependency review, not a reason to install an elaborate scanner platform.

## Confidence and next evidence

High confidence: current instruction drift exists; universal orchestration repeats context; the setup lacks usable quota measurements; deterministic checks should remain. Moderate confidence: a single consolidated review and medium routine effort will improve throughput. Unproven: exact savings, the best model for our tasks, and whether an extra external skill improves shipped quality.

The companion plan proposes a small real-work trial, with risk classification and quality checks held constant, before making model or skill choices permanent. It changes the cost of the workflow without silently lowering the SaaS's correctness requirements.
