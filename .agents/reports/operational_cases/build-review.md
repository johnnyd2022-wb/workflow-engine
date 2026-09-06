# Independent build review — operational cases A1
Date: 2026-09-05
Reviewer: independent Codex subagent, gpt-5.6-sol / medium, read-only.
Baseline: parent reran case/dashboard/corechecks/finding-history suites: 117 passed.

## Findings handed back for correction
1. P1: detail.js edit omits expected_version; every Save fails 400.
2. P1: conditional app_factory blueprint registration strands history when deployment flag off.
3. P1: ID-only FKs lack approved tenant-consistent composite parent/child/predecessor integrity.
4. P1: source snapshot str()s execution IDs without same-org validation.
5. P1: create and transition commands accept/ignore unsupported fields.
6. P1/P2: Dashboard has server data only, no count/link rendering or case LiveSync subscription.
7. P2: case detail lacks corrective-source links and return context.
8. P2: source-status loads all historical cases for source IDs; unbounded result count.
9. P2: owner 404/400 semantics mismatch and inactive owner mutation not guarded.
10. P2: 32 KiB request and 8 KiB event byte bounds missing.
11. P2: Notifications lacks case LiveSync updates.
12. P2: creation event omits observed_at, so source freshness is lost.
13. P2: malformed filters silently default or raise 500.
14. P2: export has no consistent snapshot; checksum omits newline bytes; no executable restore rehearsal.
15. P2: local/test configs enable the deployment capability rather than default off.

Parent additionally requested evidence upload references (not substituted execution-step IDs),
readable/lazy timeline payloads, query/response budgets, stable client retry keys, and
fault-injection recovery coverage. Corrections assigned in .herdr-collab/operational-cases-patch.md.
Read-only reviewer did not patch code. This first review is not a green gate.

## Resolution verification

The implementation was corrected for each finding above: detail saves include optimistic
versions; the recovery blueprint mounts independently of the feature gate; composite
tenant reference constraints are added in `operational_cases_002`; snapshot/evidence,
request/event bounds and filter validation are enforced; and the queue, Notifications and
Dashboard consume bounded case data and LiveSync changes. The deployment flag is false by
default in every environment.

Verification after the corrections: 53 operational-case tests, 84 related
dashboard/core-check/finding-history tests, JavaScript syntax checks and smoke E2E passed.
The disposable PostgreSQL upgrade/down/upgrade cycle passed. The export/restore rehearsal
test verifies checksums and rolls all rehearsal writes back.

VERDICT: corrected; normal code review and pilot rollout remain required.
