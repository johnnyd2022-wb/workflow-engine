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

## 3. Get approval — or make the assumptions reviewable

**Interactive run** (the user is there): show the spec, ask for approval or edits, set `status: approved` only after explicit sign-off.

**Unattended run** (scheduled, chained from another skill, or the user has walked away — see `.agents/autonomy.md`): there is nobody to sign off, and blocking here would stop the whole chain to wait for a person who isn't coming. Instead:

1. Write the spec with **every** open question resolved into an explicit `ASSUMPTION:` line — the default you chose *and* what you rejected.
2. Set `status: approved-unattended`. Downstream skills treat this as buildable.
3. The assumptions block goes at the **top of the MR description**, verbatim. That is where sign-off happens now: the human reads the assumptions next to the diff and rejects the MR if one is wrong.

This trades "approve a spec you can't see the consequences of" for "review a working change with its assumptions listed". The gate moved; it did not disappear.

Never use `approved-unattended` to dodge an interview the user is available for — a live user is always better evidence than your best guess.

## Rules

- Never write code in this skill. Spec only.
- Never mark a spec plain `approved` without the user. `approved-unattended` is a different, honest status — use it rather than blurring the two.
- An `ASSUMPTION:` line that isn't surfaced in the MR description is a silent decision, which `.agents/autonomy.md` prohibits. Surfacing them is what earns the autonomy.
- If the user resists the interview ("just build it"), compress to the two non-negotiables: slug and acceptance criteria. Everything else carries stated assumptions the user can veto later.
