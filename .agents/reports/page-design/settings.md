# PAGE DESIGN — Settings — 2026-10-12

plan: docs/settings-redesign-plan.md
research: 3 comparable products, 2 craft references, 2 pattern sources; Production !515
directions: 3 (Board, Settings desk, Register); chosen: awaiting the pick
passes: 7; final full pass: 07, all five scenario groups passed, no console errors
defects fixed: 10 presentation/behavior findings across implementation and review
bugs fixed: editable blanks after failed account load; duplicate initializer overwriting
drafts; boosted arrival/return failing to initialize security and profile; repeated global
effects across visits; stale requests/transient notifications surviving page teardown
screenshots: ~/.cache/workflow-engine-ui-shots/settings-design/00-before through /07
tests: 6 new functions (17 parameterized cases); 1 shared test changed (3 widths) to
assert the intended Board geometry, retaining headings, links and overflow checks
validation: JavaScript syntax, Ruff, repository Semgrep rules and Semgrep auto passed;
HTML/JS/static test review clean. Local pytest and mutation checks not run, per user;
CI owns test execution and will not be monitored.
follow-ups: select one style, remove preview and losers, complete remaining UX 2.5 work
verdict: findings-open — awaiting concept choice, no known design defect

Every generated PNG was inspected between author and reviewer. The final 45 images
include four widths, dark mode, each category, an edited profile, loading/error/retry,
boosted return, session save, enrollment open/cancel, and the actual appearance toggle.
Enrollment comparison captures mask the throwaway QR/manual secret. The six baseline
images include two sibling pages. All 51 final/baseline images were uploaded to GitLab.
The throwaway organisation was purged from the test database.

Passes 01–03 exposed initialization defects and a local TLS stylesheet transport failure.
04 completed the base scenarios; expanding security/appearance in 05–06 exposed invalid
capture selectors and an offscreen native switch input in the harness. 07 drove the
visible switch label and completed every flow. Its stylesheet is fetched from the real
running application through Playwright's HTTP client to avoid the local TLS speculative
connection failure; page data and operations use the real application. A final capture
of the same enrollment state masks secrets and uses the phone viewport instead of a
full-page image. No production data or configuration was used.
