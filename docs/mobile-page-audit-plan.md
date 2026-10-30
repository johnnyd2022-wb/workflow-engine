# Mobile page audit plan

The goal is a usable, polished phone experience across every navigable HTML page, including feature-gated NZ Alcohol pages. The [index](mobile-page-audit-index.md) is the route-by-route ledger and must record evidence before a page is marked complete.

## Scope and method

1. Derive the page inventory from Flask's GET route map, excluding JSON APIs, static assets, downloads, redirects, and fragments. Record data-dependent pages separately with the fixture needed to reach them.
2. Run Playwright at 390 × 844 (common phone), with authenticated test users and the NZ Alcohol subscription enabled. Save full-page screenshots. Check route response, actual destination, JavaScript errors, and document overflow.
3. Review every screenshot visually for readable hierarchy, clear actions, working navigation, usable forms, sensible tables/cards, and no clipping. Exercise mobile navigation and at least one main action per page family. Recheck at 320 × 700 for narrow screens and 768 × 1024 for tablet layouts after fixes.
4. Fix defects using established page and shared component patterns. Rerun affected pages, then the full route suite. Keep full screenshots in the local test run and commit synthetic-data contact sheets for MR review.

## Acceptance criteria

- The document does not scroll horizontally at phone width. Wide data grids may scroll inside a clearly bounded container.
- Titles, labels, values, and controls remain readable without zoom; no overlay hides primary content or actions.
- Navigation opens, closes, and reaches the current workspace. Primary actions and filters are reachable and usable by touch.
- Forms, drawers, dialogs, empty states, loading states, and populated states use the same spacing and visual language as established pages.
- Every index row has an actual Playwright screenshot review and a passing retest before its status is `done`. A redirect, 403, empty fixture where populated content matters, or missing screenshot is `blocked` or `todo`, never `done`.

## Exclusions

API endpoints, static assets, PDF/download routes, redirects, and non-standalone HTML fragments are not pages. The HTML transfer docket is included. Invitation/token routes and record/detail routes require seeded identifiers and are explicitly tracked in the index. External OAuth callbacks are flows, not destination pages.

## Evidence

Run `MOBILE_AUDIT_SCREENSHOTS=/tmp/mobile-page-audit/screenshots uv run pytest tests/e2e/test_mobile_page_audit.py -q`. The screenshot directory contains full-page local test evidence; the committed contact sheets contain only synthetic test data. The index records reviewed routes and findings; the Playwright test remains as a regression gate.
