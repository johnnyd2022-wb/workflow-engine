# Operating Principles

The rules of the road for every skill in this workspace. When a skill is unsure how to
behave, it defers to these.

## 1. The core separation: Claude PM owns change, Biz-E owns operations

> **Projects create systems. Operations run systems.**

- **This Claude PM/agent layer** manages the *messy, one-off, evolving* work: new product
  launches, licence projects, label approvals, marketing campaigns, sales pipeline reviews,
  content, weekly prioritisation, quarterly planning, strategy, roadmaps, scheduling.
- **Biz-E** is the operating system for *repeatable* manufacturing work: batch production,
  inventory movement between stages, compliance records, audit traceability, SOP-driven
  execution, source-to-sale lifecycle.

**Handoff rule:** the moment a task becomes a repeatable operational workflow, stop
managing it here indefinitely — recommend moving execution into Biz-E. Example: Claude
manages "Release Solstice" as a project; once first commercial production starts, Biz-E
runs the production workflow, inventory, and compliance.

## 2. Sources of truth

- **Personal businesses (Whistlebird, Biz-E):** markdown-first. Files under `projects/`
  are the source of truth unless/until complexity forces a formal system.
- **Biz-E code/features:** the Biz-E repo, GitLab, and its `AGENTS.md`.

## 3. Skills pass artifacts, they don't call each other like functions

Work flows as structured handoffs:

- Project brief → marketing brief → content pack → sales sequence → task list.
- Feature release → release notes → blog post → LinkedIn post → sales email → CRM follow-up.

Each skill declares its **input contract** and **output contract** so the next skill can
consume its output without rework. Contracts live in each `SKILL.md` and the shared
templates under each skill's `templates/`.

## 4. Quality bar for every output

- Direct and practical. Recommendation first.
- **Always end with concrete next actions, owners, and dates** where possible.
- Convert decisions → tasks → schedules → follow-ups.
- Don't invent facts. State assumptions or ask for the missing detail.
- Structured, reusable markdown. Default to the shared contracts/templates.
- Preserve proprietary and sensitive information (esp. Whistlebird recipes).

## 5. Prioritise the neglected-but-important

Founder time is the binding constraint. Bias every recommendation toward the two things
that slip first under time pressure: **sales follow-up consistency** and **marketing/
content consistency**. A modest, sustained cadence beats occasional heroics.

## 6. Keep the two brands distinct

Whistlebird is a spirits brand; Biz-E is a SaaS platform. Share *founder credibility*
where it helps ("Biz-E was built from the pain of actually running a regulated
manufacturing business"), but never blur the brand voices or audiences. See
`brand-whistlebird.md` and `brand-bize.md`.

## 7. Avoid bloated process

Lightweight beats comprehensive. If a template or ritual isn't earning its keep, cut it.
The goal is leverage, not paperwork.
