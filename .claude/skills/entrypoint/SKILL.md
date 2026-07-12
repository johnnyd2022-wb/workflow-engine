---
name: entrypoint
description: "Top-level router across every registered skill in this repo — both the biz-e code suite (new-feature, review-feature, fix-bug, and their specialists) and the founder-ops pack (business-operator and its 19 specialists). Use this when the user doesn't know which skill to reach for: 'which skill should I use', 'help', 'where do I start', 'I want to build/fix/ship X' with no named skill, or any request that could plausibly map to more than one skill. Not for requests that already clearly name their skill (e.g. 'run sales-manager') — invoke that skill directly instead."
---

# Entrypoint

One door in front of 38 registered skills across two unrelated surfaces — this repo's
engineering work (`.claude/skills/`) and the founder's two businesses
(`.claude/agents/skills/`, symlinked into the same `.claude/skills/` directory). Nobody
should have to know the roster to get started. Your job is triage: read the request,
name the one skill (or short chain) that actually answers it, say why, and invoke it —
don't just print a menu and stop.

This is a router, not a decision-maker. It does not do the work of the skill it routes
to, and it does not out-rank `business-operator` on business *prioritization* calls
("what should I work on this week" is business-operator's call once you're in the
founder-ops world — entrypoint's job ends at getting you there).

## Two surfaces, one map

### 1. Code work on this repo (Flask/SQLAlchemy/Postgres, multi-tenant)

**Front doors — pick exactly one, it chains the rest itself:**

| Ask sounds like | Skill |
|---|---|
| "Build/add a new feature, endpoint, page, capability" | `new-feature` |
| "Review/audit/harden an existing feature", "is X solid", "check X before launch" | `review-feature` |
| "This is broken", a bug report, a stack trace, a request_id, a regression | `fix-bug` |
| A CVE/pip-audit finding, "bump this dependency" | `dependency-update` |
| "Deploy this", "ship to prod/test", "roll this back" | `deploy-runner` (technical) → hands off to `release-manager` (readiness/changelog/GTM) |
| Already built + verified, needs the MR opened/pushed/watched | `merge-request` (front doors call this themselves — rarely invoked directly) |

**Specialists — normally chained automatically by a front door above; invoke directly only for a narrow, standalone ask:**

| Ask sounds like | Skill |
|---|---|
| "What's the convention for X here", "how do we normally do Y" | `repo-conventions` |
| Need seeded test data / org+user fixtures for a new test | `test-fixtures` |
| Set up or modify CI, `.gitlab-ci.yml`, pre-commit, protected branches | `ci-gate` |
| Security review, semgrep/gitleaks/pip-audit, tenant isolation | `security-audit` |
| Browser/E2E tests, Playwright, "does the app actually work" | `e2e-playwright` |
| Migration reversibility, schema change safety | `migration-safety` |
| Logging, monitoring, "why did this fail in prod" (triage mode) | `observability` |
| Turn a feature request into a written spec before building | `spec-first` |

**Ad hoc file review (not a workflow, just a lint pass on a specific file):**
`html-review`, `js-review`, `python-review` — point at a specific template/script/module
someone wants a second pair of eyes on, outside the new-feature/review-feature chain.

**Multi-agent build/verify pairing (Herdr + Codex only):** `herdr-multi-agent-collab` —
niche, only relevant with a Codex pane running alongside.

### 2. Running Whistlebird / Biz-E (the businesses, not the codebase)

**Front door:** "What should I do next/this week", Monday review, overwhelm, or
anything spanning both businesses → **`business-operator`**. It routes onward to the
specialists below — if the ask already clearly belongs to one of them, skip straight
there instead of going through business-operator first.

| Domain | Ask sounds like | Skill |
|---|---|---|
| Cross-business | New project, milestones, next actions | `project-manager` |
| Cross-business | "Plan my week", tonight's next action | `calendar-planner` |
| Cross-business | Margins, MRR, cashflow, runway, time/$ decisions | `finance-advisor` |
| Demand & revenue | Positioning, campaign, content calendar | `marketing-director` |
| Demand & revenue | Turn a brief into finished posts/copy/newsletter | `content-producer` |
| Demand & revenue | Pipeline review, follow-ups, outreach, objections | `sales-manager` |
| Demand & revenue | "Check my email", inbox triage (Gmail, drafts only) | `sales-watches` |
| Demand & revenue | Cold first-touch drafts from a new contact list | `outbound-sales` |
| Demand & revenue | Log a sales action, flag a stale lead | `crm-updater` |
| Demand & revenue | Daily subreddit/community scan for Biz-E angles | `community-triage` |
| Demand & revenue | Debrief a demo/discovery call transcript | `discovery-synthesis` |
| Demand & revenue | Weekly competitor pricing/changelog/review check | `competitor-watch` |
| Whistlebird | "Should we launch X", awards, retail, events strategy | `distillery-strategy-advisor` |
| Whistlebird | Licence/label project tracking (not legal advice) | `compliance-project-assistant` |
| Whistlebird | "Quiz me", mock interview for the duty manager's cert | `licence-study-coach` |
| Biz-E | Roadmap, PRDs, "should we build this", prioritisation | `bize-product-manager` |
| Biz-E | Architecture review, ADRs, before a build starts | `cto-software-architect` |
| Biz-E | Pre-release checklist, changelog, GTM handoff | `release-manager` |
| Biz-E | Onboarding, demo scripts, support drafts | `customer-success-onboarding` |

## How to route

1. **Read the ask for domain first**: is this about *this codebase* (files, bugs,
   features, CI, deploys) or about *running the businesses* (Whistlebird, Biz-E as
   companies — sales, marketing, product, compliance, finance)? The two tables above
   rarely overlap; get this call right and the rest is a lookup.
2. **Match to the most specific row, not the front door, if the ask already names the
   specific work.** "Draft a follow-up to Liquorland Petone" goes straight to
   `sales-manager`, not through `business-operator` first. Front doors
   (`new-feature`/`review-feature`/`fix-bug`/`business-operator`) are for when the ask
   is broad or the user genuinely doesn't know where it lands.
3. **If it's genuinely ambiguous** (could be two skills, or spans both surfaces —
   e.g. "the Xero integration is broken and customers are asking about it" is both
   `fix-bug` and arguably a `sales-manager`/`customer-success-onboarding` concern), ask
   one short clarifying question rather than guessing, or name the primary skill and
   note the likely follow-on handoff so nothing gets dropped.
4. **State the match and why in one sentence**, then invoke the skill — don't just
   describe it and stop. Routing that ends in a description instead of an action isn't
   routing.
5. **If nothing on this map fits**, say so plainly rather than forcing a bad match —
   this roster changes (see below); a genuinely new kind of request might mean a skill
   is missing, which is worth flagging back to whoever maintains this workspace rather
   than papering over with the closest-but-wrong skill.

## Keeping this map honest

This table is a snapshot, not a live query — it will drift as skills are added, renamed,
or retired. If a routing decision feels off, or the user names a skill not listed here,
cross-check against the live roster before trusting this file over reality:

- Code suite skills: `ls .claude/skills/` (this repo's actual registered skills).
- Founder-ops pack: `.claude/agents/README.md`'s roster table is the maintained source;
  `.claude/agents/skills/` is the underlying directory.

Whoever adds a new skill to either surface should add one row here in the same change —
treat an unrouted skill as a broken handoff, not a documentation nicety.

## What this skill does NOT do

- Doesn't replace `business-operator`'s prioritisation judgment once you're in the
  founder-ops world — it gets you to business-operator, not past it.
- Doesn't replace a front door's own chaining (`new-feature` still runs its full
  spec → build → verify → merge-request sequence) — entrypoint's job is choosing the
  front door, not re-implementing what happens after.
- Doesn't invent a skill that doesn't exist. If the ask has no home, say that.
