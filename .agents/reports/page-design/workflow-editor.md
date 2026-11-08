# PAGE DESIGN — workflow editor — 2026-10-13

plan: docs/workflow-editor-redesign-plan.md
research: 3 comparable products, 2 craft references, 1 pattern source
directions: 3 (Board, Editing desk, Document); chosen: awaiting the pick
passes: 4; defects fixed: 8
bugs fixed: accessible name/description associations; concept query overriding a newer selection; scoped Jinja variable unavailable inside title block during implementation
screenshots: ~/.cache/workflow-engine-ui-shots/workflow-editor-design/{00-before,01,02,03,04,diagnostic}
tests: 3 new test functions / 14 parameter-expanded cases; no existing tests weakened
follow-ups: scratch/template chooser, catalogue, graph viewer, legacy modal; explicit inventory loading indicator; selection/removal of concepts
verdict: findings-open

## Verification

Seeded one throwaway local test organisation with stock and production workflows. The initial screenshots include the original overview and step editor plus Production and Suppliers. The four design passes contain 37, 37, 49 and 55 images. Every pass's images were inspected, with the independent reviewer handling complete sets and the author checking key views directly. Final layouts cover all seven stages, four viewport widths, dark, quiet/new, populated edit, help open, validation, inventory pending, stale-write feedback, created, edited and in-app return.

Actual browser interactions created and saved one workflow per style, edited its step, saved again and verified the API retained the same step identity without adding duplicates. Style choices survived navigation and the in-app return. The injected 409 stale-write response remained on review, showed the existing warning and preserved the stored step. No production database was used.

Static checks: Node syntax, Ruff app/test lint and test formatting, Semgrep auto scan, diff whitespace check. Pytest, mutation checks and CI monitoring were skipped at the user's explicit request. The tests are supplied for CI, not reported as locally passing.

The screenshot harness's first speculative TLS stylesheet request produced `ERR_TOO_MANY_RETRIES` in pass 01. Later scenarios fetch the **real app stylesheet** through Playwright route.fetch/fulfill; no CSS is stubbed. Passes 02 and 03 have no console errors. Pass 04 deliberately injects the stale-write 409; CoreAPI logs that expected failure and the harness therefore exits 1 despite all three scenarios passing. There are no unexplained console or scenario failures. This injected error is not a failed real save.

The independent review raised a suspected missing Next rail in returned captures. Direct image inspection and a separate DOM capture confirmed the rail is present, fixed at y=839–900, not hidden, with correct wizard body attributes. This was not an application defect. Full-page screenshots place fixed controls at the original viewport bottom; the viewport comparisons and interaction checks establish that content remains reachable by scrolling.

Resolved design issues: pale active segments with white labels, excessive nested action-rail padding, Style 3 width specificity, expanded Style 2 guide spacing, uppercase overview field heading, label associations, concept URL persistence and Jinja block scoping. Shared API/save/version-guard logic was left intact.

## Review

Independent html-review/js-review/test-evaluator handoff completed static inspection. No security finding or weakened assertion. Existing-step CI coverage was added after the reviewer noted the original tests covered only new workflow navigation. The MR stays draft until the user chooses a concept.

Final independent review inspected all 55 pass-04 images and found no new layout/contrast defects. Slow inventory retains its existing blank pending region, without an explicit loading label; that legacy feedback limitation is recorded for follow-up rather than reported as a designed loading indicator. The seeded organisation was purged successfully.
