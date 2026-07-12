---
name: spec-first
description: "Turn a feature request into a written, testable spec BEFORE any code is written. Use this skill whenever a new feature, endpoint, blueprint, or significant change is requested and no spec exists yet in .agents/specs/. Also trigger when the user says 'spec this out', 'plan this feature', or when new-feature calls it as step 1. Ambiguous specs are the number one cause of agentic rework, so never skip this for non-trivial work."
---

# Spec First

A feature without acceptance criteria cannot be verified, and unverifiable work is where agentic coding goes wrong. This skill produces the single spec file that every downstream skill (build, security-audit, e2e-playwright, migration-safety, review-feature) parses. The format is a contract: keep it exact.

## 1. Interview the user

Ask for anything not already stated. Do not invent answers. One round of focused questions beats five rounds of guessing:

1. **Feature name.** Must reduce to a valid Python identifier slug (lowercase, underscores). This slug becomes the Flask blueprint name, the module path `app/features/<slug>/`, the URL prefix `/<slug>`, and the spec filename. Confirm the slug back to the user.
2. **Description.** One paragraph: what it does and why.
3. **Users and permissions.** Who can use it? Which roles? Is any part of it tenant-scoped? (In a multi-tenant B2B app, assume yes unless the user says otherwise, and say you are assuming it.)
4. **Acceptance criteria.** 3 to 8 testable statements. Push vague answers into testable form: "fast" becomes "list view returns in under 500ms at 1k rows"; "secure" becomes "user in org A receives 404 for org B's records".
5. **Data model changes.** New tables/columns? Anything destructive? This decides whether migration-safety runs.
6. **External surfaces.** Third-party APIs, webhooks, file uploads, background jobs. These drive the security review's focus.
7. **Out of scope.** What this feature deliberately does NOT do. Prevents scope creep by builder agents.

If the user has already supplied some of these in their request, extract them and only ask what is missing. Confirm the assembled spec before writing it.

## 2. Write the spec file

Path: `.agents/specs/<slug>.md`. Exact format:

```markdown
# SPEC: <slug>
status: draft | approved | built | reviewed
name: <Human Readable Name>
slug: <slug>
blueprint: app/features/<slug>/
url_prefix: /<slug>

## Description
<paragraph>

## Users & permissions
- roles: <list>
- tenant_scoped: yes | no

## Acceptance criteria
- AC1: <testable statement>
- AC2: ...

## Data model
- changes: none | <list of tables/columns>
- destructive: no | <what and why>

## External surfaces
- <list or none>

## Out of scope
- <list>
```

Every acceptance criterion gets an `AC<n>` ID. Downstream skills reference these IDs: unit tests name themselves `test_ac1_...`, Playwright tests map to ACs, and review-feature audits coverage per AC. That traceability is the whole point.

## 3. Get approval

Show the spec to the user and ask for approval or edits. Only set `status: approved` after explicit sign-off. Downstream skills must refuse to build from a spec still in `draft`.

## Rules

- Never write code in this skill. Spec only.
- Never mark your own spec approved without the user.
- If the user resists the interview ("just build it"), compress to the two non-negotiables: slug and acceptance criteria. Everything else can carry stated assumptions, written into the spec as `ASSUMPTION:` lines the user can veto later.
