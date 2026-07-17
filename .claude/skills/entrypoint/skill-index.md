# Skill Index (cached)

Cached, categorized roster of every registered skill in `.claude/skills/`. This file is
**generated and maintained by the entrypoint skill** — it re-syncs it against the live
directory on every run (see SKILL.md, Step 0). Hand-edits are fine but will be preserved
only if the skill still exists; rows for deleted skills get pruned, new skills get added.

last_synced: 2026-07-17
skill_count: 39

## Roster fingerprint

Sorted output of `ls -1 .claude/skills/`. If the live listing differs from this block,
the index is stale — re-sync before routing.

Scan scope (see SKILL.md Step 0 for the full procedure): `.claude/skills/` is the
registered roster this fingerprint tracks; `.claude/agents/skills/` is the founder-ops
source — entries there without a symlink in `.claude/skills/` get symlinked in during
sync; stray SKILL.md files elsewhere under `.claude/` are reported to the user, never
auto-registered. `.claude/takeaway/` (export copies, including the Codex-side breaker
skill) is always excluded.

```
bize-product-manager
business-operator
calendar-planner
ci-gate
community-triage
competitor-watch
compliance-project-assistant
content-producer
crm-updater
cto-software-architect
customer-success-onboarding
dependency-update
deploy-runner
discovery-synthesis
distillery-strategy-advisor
e2e-playwright
entrypoint
finance-advisor
fix-bug
herdr-multi-agent-collab
html-review
js-review
licence-study-coach
marketing-director
merge-request
migration-safety
new-feature
observability
outbound-sales
project-manager
python-review
release-manager
repo-conventions
review-feature
sales-manager
sales-watches
security-audit
spec-first
test-fixtures
```

## Categories

### 1. Code — front doors (pick exactly one; it chains the specialists itself)

| Ask sounds like | Skill |
|---|---|
| "Build/add a new feature, endpoint, page, capability" | `new-feature` |
| "Review/audit/harden an existing feature", "is X solid", "check X before launch" | `review-feature` |
| "This is broken", a bug report, stack trace, request_id, regression | `fix-bug` |
| A CVE/pip-audit finding, "bump this dependency" | `dependency-update` |
| "Deploy this", "ship to prod/test", "roll this back" | `deploy-runner` (technical) → hands off to `release-manager` |
| Already built + verified, needs the MR opened/pushed/watched | `merge-request` (front doors call this themselves) |

### 2. Code — specialists (normally chained by a front door; direct only for a narrow standalone ask)

| Ask sounds like | Skill |
|---|---|
| "What's the convention for X here" | `repo-conventions` |
| Need seeded test data / org+user fixtures | `test-fixtures` |
| Set up/modify CI, `.gitlab-ci.yml`, pre-commit, protected branches | `ci-gate` |
| Security review, semgrep/gitleaks/pip-audit, tenant isolation | `security-audit` |
| Browser/E2E tests, Playwright, "does the app actually work" | `e2e-playwright` |
| Migration reversibility, schema change safety | `migration-safety` |
| Logging, monitoring, "why did this fail in prod" | `observability` |
| Turn a feature request into a written spec | `spec-first` |

### 3. Code — ad hoc file review (single-file lint pass, outside any chain)

| Target | Skill |
|---|---|
| A Jinja2 template | `html-review` |
| A JS/TS file or script block | `js-review` |
| A Python module | `python-review` |

### 4. Multi-agent orchestration (Herdr)

| Ask sounds like | Skill |
|---|---|
| Cross-pane Claude↔Codex handoff, adversarial review, "hand this to Codex", Architect/Breaker | `herdr-multi-agent-collab` |

Only meaningful when `HERDR_ENV=1`. When routing code front doors inside Herdr, this
skill is the verification transport, not a destination on its own — see SKILL.md Step 3.

### 5. Business — cross-business operations (Whistlebird + Biz-E)

Front door for "what should I work on" / weekly review / overwhelm: **`business-operator`**.

| Ask sounds like | Skill |
|---|---|
| New project, milestones, next actions | `project-manager` |
| "Plan my week", tonight's next action | `calendar-planner` |
| Margins, MRR, cashflow, runway, time/$ decisions | `finance-advisor` |

### 6. Business — demand & revenue

| Ask sounds like | Skill |
|---|---|
| Positioning, campaign, content calendar | `marketing-director` |
| Turn a brief into finished posts/copy/newsletter | `content-producer` |
| Pipeline review, follow-ups, outreach, objections | `sales-manager` |
| "Check my email", inbox triage (Gmail, drafts only) | `sales-watches` |
| Cold first-touch drafts from a contact list | `outbound-sales` |
| Log a sales action, flag a stale lead | `crm-updater` |
| Daily subreddit/community scan for Biz-E angles | `community-triage` |
| Debrief a demo/discovery call transcript | `discovery-synthesis` |
| Weekly competitor pricing/changelog/review check | `competitor-watch` |

### 7. Whistlebird-specific

| Ask sounds like | Skill |
|---|---|
| "Should we launch X", awards, retail, events strategy | `distillery-strategy-advisor` |
| Licence/label project tracking (not legal advice) | `compliance-project-assistant` |
| "Quiz me", mock interview for the duty manager's cert | `licence-study-coach` |

### 8. Biz-E-specific

| Ask sounds like | Skill |
|---|---|
| Roadmap, PRDs, "should we build this", prioritisation | `bize-product-manager` |
| Architecture review, ADRs, before a build starts | `cto-software-architect` |
| Pre-release checklist, changelog, GTM handoff | `release-manager` |
| Onboarding, demo scripts, support drafts | `customer-success-onboarding` |

### 9. Meta

| Skill | Role |
|---|---|
| `entrypoint` | This router itself — never route to it. |

## Outside this index

Harness-provided skills (`code-review`, `verify`, `run`, `loop`, `schedule`,
`update-config`, `keybindings-help`, `claude-api`, plugin skills, …) are not files in
`.claude/skills/` and are not tracked here. If an ask is about the Claude Code harness
itself (config, keybindings, scheduling, code review of a diff), name the harness skill
directly rather than forcing a match from this index.
