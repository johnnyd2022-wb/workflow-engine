# Claude Ops — Founder Operating Workspace

A lightweight AI operating layer for running **Whistlebird** (craft gin) and **Biz-E**
(SaaS for manufacturers) — without duplicating Biz-E or drowning in process. Personal
businesses only: the day job stays in its own systems and matters here only as a capacity
constraint. This layer manages *change* (projects, strategy, marketing, sales, planning).
Biz-E manages *repeatable operations*. See `context/operating-principles.md`.

> **Projects create systems. Operations run systems.**

## What's here

```text
agents/                     ← workspace root (location-independent; currently ~/Downloads/agents)
  README.md                 ← you are here
  AGENTS.md                 ← how any agent should behave in this workspace
  CLAUDE.md                 ← auto-loaded by Claude Code sessions started here; points at AGENTS.md
  context/                  ← shared facts every skill reads
    founder.md  whistlebird.md  bize.md
    brand-whistlebird.md  brand-bize.md
    audiences.md  offers-pricing.md  operating-principles.md
  skills/                   ← the playbooks (20 built)
    business-operator/      ← "what should I do next?" chief-of-staff
    project-manager/        ← lightweight project plans, milestones, next actions
    calendar-planner/       ← turns priorities into a realistic week
    marketing-director/     ← positioning, calendar, campaign & content briefs
    content-producer/       ← briefs → finished posts/newsletters/copy
    sales-manager/          ← pipeline discipline, follow-ups, outreach, stalled-thread scan, pre-call prep
    sales-watches/          ← Gmail inbox triage + reply drafts (drafts only, never sends)
    outbound-sales/         ← cold first-touch email drafts (drafts only, never sends)
    crm-updater/            ← pipeline hygiene after sales actions
    community-triage/       ← subreddit scan for Biz-E angles, drafted replies (never posts)
    discovery-synthesis/    ← call transcript → pains/objections/feature asks/quotes
    competitor-watch/       ← weekly diff of competitor pricing/changelog/reviews
    finance-advisor/        ← margins, MRR, cashflow, runway, time/$ decisions
    distillery-strategy-advisor/  ← Whistlebird product/growth strategy
    compliance-project-assistant/ ← licence/label projects (not legal advice)
    licence-study-coach/    ← duty manager's cert Inspector-interview drilling
    bize-product-manager/   ← Biz-E roadmap, PRDs, prioritisation
    cto-software-architect/ ← Biz-E architecture, ADRs, security/data review
    release-manager/        ← ship Biz-E safely; changelog; GTM handoffs
    customer-success-onboarding/  ← Biz-E adoption, demos, onboarding
  projects/                 ← the source of truth for personal-business work
    whistlebird/  bize/
  skill-pages/              ← cofounder-friendly HTML page per skill (turn into artifacts;
                              regenerate with `python3 skill-pages/_generate.py` after edits)
  outputs/                  ← generated weekly/quarterly artifacts land here
```

## How to use these skills

All 20 skills are **registered as project-level Claude Code skills** via symlinks in
`.claude/skills/` (each links back to `agents/skills/<name>/`, so this directory stays
the single source of truth). In any Claude Code session in this repo you can invoke them
directly:

> `/sales-watches` — triage the inbox and draft replies
> `/outbound-sales` — 6 store emails attached, lead with Green Gold
> `/sales-manager` — review the Whistlebird pipeline and give me this week's follow-ups

Each `SKILL.md` tells Claude what to read, what to produce, and what to hand off next.
If you add a new skill folder here, re-run the registration loop from the repo root:

```bash
cd .claude/skills
for s in ../agents/skills/*/; do
  name=$(basename "$s"); [ -e "$name" ] || ln -s "../agents/skills/$name" "$name"
done
```

## The skill roster (20)

### Cross-business — decide & coordinate
| Skill | Owns | Typical trigger |
|---|---|---|
| Business Operator | What matters now; routing; operating rhythm | Monday review, "what next?" |
| Project Manager | Project plans, milestones, next actions | New project / weekly update |
| Calendar Planner | Turns priorities into a realistic, time-blocked week | "Plan my week", tonight |
| Finance Advisor | Margins, MRR, cashflow, runway, time/$ decisions | Weekly finance summary |

### Demand & revenue (both businesses)
| Skill | Owns | Typical trigger |
|---|---|---|
| Marketing Director | Positioning, calendar, campaign/content briefs | Weekly marketing pack |
| Content Producer | Briefs → finished content assets | After a marketing brief |
| Sales Manager | Pipeline, follow-ups, outreach, objections, daily stalled-thread scan, pre-call prep | Daily/weekly sales review |
| Sales Watches | Gmail inbox triage; reply drafts in the founder's voice (never sends) | "Check my email", catch-up after days away |
| Outbound Sales | Cold first-touch email drafts from a contact list + topic (never sends) | New stockist/prospect list to approach |
| CRM Updater | Pipeline hygiene, stale-lead flags, follow-up tasks | After an email/call/demo |
| Community Triage | Subreddit scan for Biz-E angles; scored fit; drafted replies (never posts) | Daily community scan |
| Discovery Synthesis | Demo/call transcript → pains, objections, feature asks, quotes | After a demo/discovery call |
| Competitor Watch | Weekly diff of competitor pricing/changelog/reviews | Weekly / "what are competitors doing" |

### Whistlebird
| Skill | Owns | Typical trigger |
|---|---|---|
| Distillery Strategy Advisor | Product/growth strategy, awards, retail, events | "Should we launch X?" |
| Compliance Project Assistant | Licence/label projects (organises & drafts; not legal advice) | Compliance deadline |
| Licence Study Coach | Duty manager's cert Inspector-interview drilling and readiness tracking | "Quiz me", mock interview |

### Biz-E
| Skill | Owns | Typical trigger |
|---|---|---|
| Biz-E Product Manager | Roadmap, PRDs, prioritisation, MVP scope | "Should we build this?" |
| CTO / Software Architect | Architecture, ADRs, security & data-model review | Before build / design review |
| Release Manager | Ship safely, changelog, GTM handoffs | Feature merged / git tag |
| Customer Success / Onboarding | Adoption, demos, onboarding, support drafts | Won deal / onboarding |

The pack recommends adopting them in phases — the first 5 (Business Operator, Project
Manager, Marketing Director, Content Producer, Sales Manager) carry the most leverage; the
rest are there when you need them. Don't feel obliged to run all 20. The **biz-e code
suite** (new-feature, review-feature, fix-bug, repo-conventions, test-fixtures,
merge-request, deploy-runner, dependency-update, ci-gate, security-audit, e2e-playwright,
migration-safety, observability, spec-first) is a separate, code-facing skill set
registered directly in `.claude/skills/` at the repo root — see `.claude/skills/*/SKILL.md`
and `.agents/conventions.md`, not this roster.

### Email skills — the standing rule

**Sales Watches** and **Outbound Sales** work directly in Gmail (connected as
`sales@whistlebird.co.nz`). They **only ever create drafts — they never send**. The
founder reviews every draft in Gmail and sends manually. Both calibrate their tone from
our own sent mail before writing anything.

## Start-of-week ritual (highest leverage)

1. **Business Operator** → weekly command centre (`outputs/weekly-command-centre.md`).
2. **Sales Manager** → this week's follow-ups (protects the thing that slips first).
3. **Marketing Director + Content Producer** → one week of content.

See `AGENTS.md` for the operating rules and `context/` for the facts.
