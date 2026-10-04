# Workspace refresh browser evidence

Acceptance criteria: `.agents/specs/workspace-ui-refresh.md`.
Plan: `.agents/plans/merge-queue-and-ui-refresh.md`.

| Criterion | Coverage | Result |
|---|---|---|
| AC1 Four primary destinations; reachable secondary pages | `test_ac1_ac4_ac5_four_primary_destinations_and_context_actions`; navigation role/fallback integration tests | Pass |
| AC2 Grouped actions; inventory choices | `test_ac2_ac3_health_card_and_inventory_menu`; setup flow follows Manual entry to the real page | Pass |
| AC3 Severity, details, keyboard focus, unknown/loading states | Healthy/degraded/critical/unavailable colours and wording; Enter/Escape/focus restoration; empty/pending assertions | Pass |
| AC4 Compliance hierarchy and framework links | Desktop/mobile overview screenshots, programme setup and contextual Premises navigation | Pass |
| AC5 Phone width, legacy links and boosted pages | 390/1440 px, light/dark screenshots, inventory query link, existing all-page boost suite | Pass |

Before-change acceptance failed in all three workspaces: 7, 8 and 6 primary tabs.
The resulting UI has at most four, with all URLs retained in the registry. Tests
exercise real HTTPS login and real PostgreSQL data in isolated UUID organisations;
the fixture removes each organisation afterwards. Controlled health payloads test
presentation states only; authentication and the real hub aggregate stay active.

Twelve new browser cases passed in three consecutive repetitions (3/3). The combined
workspace and all-page boosted-navigation run passed 64 cases. Fifty focused
navigation, registry and frontend-asset checks passed. Ruff check/format passed.
Full regression passed: **2,860 tests, 507 skipped**. Remote CI results are recorded in the MR.

Visual review iterated through the duplicate-tab/banner baseline, shared header/action
cards, flatter Production metrics, and dark-mode contrast repairs. Inspected screenshots
include desktop/mobile overviews, all severity states, unavailable/pending and empty
setup. Screenshots live in GitLab uploads linked by the MR, keeping generated PNGs out
of the source tree. Raw local captures: `/home/johnny/ui-refresh-artifacts`.

Existing authentication, access-policy and tenant-isolation suites cover unchanged
security controls. There is no new object API or mutating form in this layout change;
no duplicate cross-tenant or invalid-form test was added.

Reproduce locally (the test DB and Chromium must be present):

```bash
E2E_ALLOW_TEST_INPROCESS=1 ENVIRONMENT=test uv run python - <<'PY'
from app.utils.config_loader import config
config.config.set('database', 'host', '127.0.0.1')
import pytest
raise SystemExit(pytest.main([
    'tests/e2e/test_workspace_overviews.py',
    'tests/e2e/test_boosted_navigation.py', '-q',
]))
PY
```

The changed browser test is selected automatically by the MR test selector and brings
Chromium/app-server setup into the required `relevant_tests` job. The normal MR smoke,
security and migration jobs also remain enabled. This UI MR does not use `ci::fast`.

Updated Compliance module/browser checks also passed 23 cases in three repetitions.

## Visual gallery

- Production: [before desktop](https://gitlab.com/whistlebird/workflow-engine/uploads/1600f5f9414ef865e8c20f9ce723f8d4/before-production-1440.png), [after desktop](https://gitlab.com/whistlebird/workflow-engine/uploads/b496e6c93aa289b5306ba0bfd3741778/after-production-1440.png), [phone](https://gitlab.com/whistlebird/workflow-engine/uploads/89881e01a5532f1857830359556cf9a9/after-production-390.png), [dark mode](https://gitlab.com/whistlebird/workflow-engine/uploads/ee6ad8542ac60f60b9ffd888ab11f797/after-production-dark-1440.png).
- Compliance: [before desktop](https://gitlab.com/whistlebird/workflow-engine/uploads/b6edf8f68dfcbc1aad076a27247f803d/before-compliance-1440.png), [after desktop](https://gitlab.com/whistlebird/workflow-engine/uploads/747b8abfc263dce6a4f5e18929296c9b/after-compliance-1440.png), [phone](https://gitlab.com/whistlebird/workflow-engine/uploads/5ec06736daedad96cbf17bfd3c4ff925/after-compliance-390.png), [dark mode](https://gitlab.com/whistlebird/workflow-engine/uploads/1230864141cb87ab7a64919ba31b750d/after-compliance-dark-1440.png).
- Sales: [before desktop](https://gitlab.com/whistlebird/workflow-engine/uploads/c3a8768e1f20c0b5c7c1b98c701d65b5/before-sales-1440.png), [after desktop](https://gitlab.com/whistlebird/workflow-engine/uploads/f6d3e59ecade3a76678cd4b3d3a958d6/after-sales-1440.png), [phone](https://gitlab.com/whistlebird/workflow-engine/uploads/56b8ee108a021df850f109db4a6a57d0/after-sales-390.png), [dark mode](https://gitlab.com/whistlebird/workflow-engine/uploads/b272457b8302524f83d512ff8a940558/after-sales-dark-1440.png).
