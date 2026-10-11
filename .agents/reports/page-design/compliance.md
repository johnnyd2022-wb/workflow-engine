# PAGE DESIGN — Compliance — 2026-10-11

plan: docs/compliance-redesign-plan.md
research: 3 comparable products (MaintainX, FoodDocs, SafetyCulture), 2 craft references (Linear, Notion), 1 pattern source (Carbon), plus Home !512 style 2
directions: 3 (Focus, Board, Register); chosen: awaiting the pick
passes: 3 implementation passes, plus a capture-only correction for expanded scroll position
screenshots: ~/.cache/workflow-engine-ui-shots/compliance/{00-before,01,02,03,04-rebase}
tests: 23 browser cases added, 0 existing tests changed
verdict: findings-open (concept selection and losing-style cleanup only)

## Findings and loop

Baseline: setup frameworks disappeared from the headline attention count; NP2 and Customs
were described as NP3; a “Compliance score” overstated the existing evidence signal; the
returned next-action queue was unused. These are corrected without a backend change.

Pass 1 inspected all captured concepts/expansions and found duplicated current-evidence
count and an over-stretched readiness card when Board actions expanded. State/navigation
capture callbacks also failed: corrected the callback signature and fulfill-before-unroute
order in the external scenario script. This pass was incomplete and did not end the loop.

Pass 2 completed and inspected all 30 images. Duplication and Board expansion remained to
polish; independent code review also requested differentiated 401/403 guidance, named
regions, and retention of the old live-data gap signal. All are addressed. A suspected
boosted-script problem was withdrawn after inspecting the shell's existing asset handling;
generated workspace links retain the old full-navigation behavior.

Pass 3 completed and inspected all 30 images: each style at desktop, phone, dark and 1920;
expanded actions/data coverage (and Register framework); quiet, setup and 503/retry;
loading and boosted return. No remaining overview defects found. Expanded capture was
re-shot at scrollTop=0 because clicking the low Register disclosure moves the fixed shell
inside a full-page image. Phone full-page captures similarly show the existing fixed
bottom navigation at viewport bottom; this is a screenshot placement artifact, not a
new navigation implementation. No comparison images added to git.

Busy data is the harness's actual test-org overview. Quiet/setup/error/loading are clearly
identified endpoint state fixtures; they do not claim a real business is fully compliant.
Nine distinct implementation findings were addressed across baseline, visual and code
review (count, labels, score wording, actions, duplicate metric, Board expansion, auth
errors, coverage retention, accessible named regions).

## Validation

Two presentation regressions failed unchanged main before implementation. New browser
suite: 23 passed on each of three stable runs (including UTC). Existing Compliance
frontend/route and shared Production layout/render/boosted-navigation suites: 123 passed
unchanged. Initial intermediate run had two failures: wrong COMPLIANCE fixture role
(corrected to MEMBER, preserving assertions) and one framework render failure while
assets were being edited. The final three stable runs have no failures. CI outcome is
in the MR description.

JS syntax, ruff, whitespace and local semgrep checks passed. Independent HTML/JS review
has no unresolved code findings. Test evaluator: valid, with green/red/green permission
mutation performed in an isolated copy (shared code never mutated).

## Sidebar compatibility after !512

Rebased cleanly onto main `dbf2f6f3` after !512 merged. The application/test patch
carried over unchanged. Captured and read all 39 refreshed screenshots: the existing
30 concept/state comparisons plus each concept with the collapsed rail in light,
dark and 1024px laptop layouts. Verified rail choice survives boosted navigation and
reload, Compliance remains reachable, and layouts have no horizontal overflow.
No new overview defects found. Uploaded refreshed comparisons to the draft MR and
purged only the disposable screenshot organisation.

Combined Compliance design, sidebar rail, workspace overview, boosted navigation and
Compliance frontend-asset checks: 122 passed. JS syntax, ruff and whitespace passed;
semgrep ran 200 rules on the overview JS with zero findings. CI result for the new
head is recorded in the MR description. All three concepts remain pending selection.

## Followups

Founder picks one concept in this draft MR. Delete the two losing structures, chooser,
query/storage handling and concept-only tests in this MR, shoot the winner again and
rerun checks before removing draft. No merge/deploy at this stage.

Exact action/filter destinations and no-refetch assertions are optional additional test
coverage; existing backend workspace calculations are outside this UI change. No Slack
announcement for a draft, and no backup alert wiring: available Slack token is read-only
and there is no usable posting connector/webhook in this session.

## Production styling after !515

Rebased on main `ba166c7b` and read !515's four discussion rounds: Board chosen,
header actions moved, title/tab placement researched, then Mockup A selected. All
three now use the shared title-only head, touching underlined tabs, secondary Premises
action and one filled primary action at the right. Below 1100px of content width,
actions move below the tabs with the primary first.

Current directions: 1 Board (closest to Production), 2 Action desk (all next steps
open beside obligations), 3 Register (compact framework rows with disclosures).
A queued action can make the Action desk taller than its obligations column; that
is an intentional density tradeoff rather than padding the shorter column.

Before: read all five images, including current Production and Home siblings.
Pass 1: read all 45; fixed dark primary-button specificity, overly compressed
Action desk framework columns and half-width Register data coverage. Duplicate
page title was removed during implementation. Pass 2: read all 45, no defects.
Pass 3: read all 51, including 401/403 states, no defects. A scenario callback
signature error interrupted the first capture attempt; the external harness was
corrected and every scenario rerun successfully. No application edits after pass 2.
Images: ~/.cache/workflow-engine-ui-shots/compliance-515/{00-before,01,02,03}.
All five before and 51 final images uploaded; disposable org purged successfully.

Validation: 24 Compliance browser cases passed in the broad run and in two further
UTC runs (24 each). Broad suite: 147 passed and one old wide-screen geometry
expectation failed because readiness is intentionally paired with Next action.
Updated that assertion to check same-row pairing and the full-column right edge,
retaining equal widths on narrower screens and all existing content/link/overflow
checks. All three changed geometry cases then passed. Independent evaluator
confirmed the contract change is valid and a broken-wide-pair mutant fails.
Independent HTML/JS review and 16 additional evaluator cases passed; permission
and primary-fill mutations were caught. Details: compliance-515-review.md.

Ruff, JS syntax, whitespace and local-rule semgrep passed. New header-primary test
checks destination, placement, filled appearance, hiding on 503 and retry restore.
Report/CI results refer to this branch, with final CI recorded in the MR.
verdict: findings-open — only the founder's concept choice and losing-style cleanup remain.

Repository-wide semgrep auto scan reported existing findings outside this change.
The auto scan against origin/main returned zero new findings (exit 0); its HTML
parser reported partial parsing of Jinja delimiters. Local JS rules had zero findings.
