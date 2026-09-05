# Operational cases — independent spec critique

date: 2026-09-05
scope: documentation-only A1 draft
spec: [operational_cases](../../specs/operational_cases.md)
reviewer: independent Codex spec-critic subagent, gpt-5.6-sol / high
skill: [.claude/skills/spec-critic/SKILL.md](../../../.claude/skills/spec-critic/SKILL.md)

The author wrote the spec; the reviewer inspected it read-only against current code and
returned findings. The author made the following corrections:

| Pass | Finding | Resolution |
|---|---|---|
| Initial | Conflicting ADMIN-only versus owner reassignment permissions | ADMIN-only after creation; MEMBER owner reassignment returns 403 |
| Initial | Source snapshot allowlist unspecified | Exact versioned keys, bounds, normalization and exclusion of arbitrary metadata/free text |
| Initial | Predecessor represented in both FK and generic links | previous_case_id is the sole canonical predecessor; server validates latest same-source terminal predecessor |
| Recheck | Snapshot amendment rejected missing remaining balance that canonical checks allow | Preserve absent balance as null, retain missing-as-zero eligibility/verification, add legacy positive-stock regression |

Reviewer confirmed the original three gaps resolved, then confirmed the focused
remaining-balance correction sound. No original gap remained unresolved through two
rounds. Final reviewer verdict is about specification consistency, not product approval.

Author checks: local Markdown links, required spec sections, AC1–AC8 uniqueness,
20 unique programme slice IDs across A–D, whitespace and metrics-ledger schema passed.
Preflight found missing local venv/dependencies and no app server. Build, migration,
security, browser, performance, observability and CI implementation gates were not run:
the user requested slice planning and a spec writeup, and no application code changed.
Customer discovery, performance measurements and pilot sign-off remain outstanding.
The spec remains `status: draft`; no implementation, database mutation or MR was created.

VERDICT: sound
