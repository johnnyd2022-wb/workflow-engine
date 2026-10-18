# PAGE DESIGN — batches — 2026-10-17
plan: docs/batches-redesign-plan.md
research: 4 comparable products (Katana, MRPeasy, Ekos, Jira), 3 craft references (Linear, Vercel, GitHub Actions), 2 pattern sources (Kanban aging guidance, Carbon status indicators)
directions: 3 (Lanes, List, Next steps); chosen: Style 1 — Lanes (founder selection)
passes: 8   defects fixed: 19   bugs fixed: search by workflow name never matched; dark theme batch titles unreadable; timeline repeated date labels
screenshots: ~/.cache/workflow-engine-ui-shots/batches-00-before, batches-01 … batches-08
tests: 17 added (tests/e2e/test_batches_design.py, 12 of them CONCEPT ONLY), 1 changed (test_production_pages_layout: card heading "Under way")
follow-ups: align Home's "idle for more than 48 hours" (started > 48h) with this page's Waiting (no step recorded for 48h)
verdict: patched

## Selection cleanup

Deleted List and Next steps and all preview switching. Kept five functional/regression cases and replaced twelve concept cases with four responsive Lanes cases. Independent evaluator: valid, no weakened assertions. Restored shared visually-hidden filter labels found by review. Load the stylesheet once through the shared head instead of duplicate head/content links; responsive tests assert both properties. Final page suite: 9 passed, including original dark contrast threshold. All 21 final pass03 screenshots were inspected; only the two intentionally injected 503 console errors occurred. Earlier missing stylesheet/contrast failures are recorded in the plan and not erased by reruns. Shared pre-cleanup suite: 116 passed, one unrelated CRM undefined-address failure and one stylesheet/dark contrast failure before the asset change; see MR for final shared and exact-head CI results. Screenshot fixture purged.

Final shared suites (production layout, boosted navigation, navigation): 87 passed; one Compliance evidence boosted-form mismatch passed unchanged in isolation (1 passed). This limitation is documented, not suppressed. Final additional responsive assertions independently graded valid; no remaining static cleanup findings.

Implementation head `b201afe0`: pipeline2959896162 passed, including relevant_tests and mr_e2e. MR removed from draft; human review and merge remain required.
