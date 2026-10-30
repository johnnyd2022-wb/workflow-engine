# Mobile page audit E2E report

| Criterion | Evidence | Verdict |
|---|---|---|
| AC1: every navigable HTML page opens at a phone width without document overflow | `tests/e2e/test_mobile_page_audit.py`, 320 px and 390 px full sweeps; [route index](../../../docs/mobile-page-audit-index.md) | pass |
| AC2: seeded detail, wizard, invitation and OAuth selection states render on phones | `test_seeded_detail_pages_at_phone_width`, `test_workflow_wizard_pages_at_phone_width`, `test_valid_invitation_at_phone_width`, `test_xero_tenant_picker_at_phone_width`, `test_google_second_factor_page_at_phone_width` | pass |
| AC3: customer portal and transfer docket remain usable at 320 px and 390 px | `tests/e2e/test_contract_portal.py`, `tests/e2e/test_site_transfers.py` | pass |
| AC4: mobile navigation and customer task sheet work by touch | `test_mobile_navigation_and_customer_task_sheet` | pass |
| AC5: Sales Analytics renders populated product rows and flexible Top N filter | `tests/e2e/test_sales_design.py` | pass |

The app was served over real TLS against the isolated local test PostgreSQL database. Playwright saved full-page screenshots at `/tmp/mobile-page-audit/screenshots`; synthetic-data contact sheets are committed under `docs/mobile-page-audit/`. Screenshots were reviewed at phone widths, including long pages, detail states, the portal, docket and the corrected process diagram. No screenshot diff gate is used.

Runs: 320 px suite 69/69; 390 px final suite 73/73; 768 px route suite 67/67; Sales design 26/26; transfer docket 3/3. The 390 px affected routes (Analytics, customer profile, diagram) were also retested individually after each fix. These are cross-width and targeted reruns, not three identical full-suite flake passes.

The MR E2E job runs the route suite, portal flow and docket flow as blocking checks. Remaining limits: screenshots prove the tested states, not every data permutation or role combination; other feature suites cover broader behavior.
