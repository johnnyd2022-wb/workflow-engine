# process_templates — verification rounds

## Spec critic

- Round 1 (2026-08-22): gaps-found. AC9 mechanism didn't exist in real code
  (requires_inventory_selection is frontend-only); AC6/AC10 response-shape conflict;
  missing catalogue-page/redirect AC; undefined description-fallback text. Report:
  .agents/reports/process_templates/spec-critic.md
- Round 2 (2026-08-22): sound. All four fixes verified against real code
  (backend.py line numbers checked). One non-gating note: `catalogue_version` type/
  starting value undefined — resolved during build as a per-template static int
  starting at 1. Report: .agents/reports/process_templates/spec-critic-round2.md
