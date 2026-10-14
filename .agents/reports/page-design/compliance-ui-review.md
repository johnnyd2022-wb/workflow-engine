# Compliance UI review — 2026-10-11

Scope: `dashboard.html`, `compliance-overview.js`, and `compliance-overview.css`. Read the complete `.claude/skills/html-review/SKILL.md` and `.claude/skills/js-review/SKILL.md`, with page-design requirements and destination templates/lifecycle code as context. Independent read-only implementation review; no implementation files changed. Three concepts intentionally remain pending the founder's selection.

## Final findings

No unresolved code findings in the reviewed template, script or stylesheet. Final source review completed after the pass-3 polish.

### Resolved P2 — Retain the existing live-data-gap information

The previous overview summary rendered `overview.data_coverage.unresolved_live_data_gaps`. Final code restores this count in a native Data coverage disclosure, with the server-provided scope and evidence/Production source counts rendered through `textContent`. The disclosure is hidden for an unconfigured operation. No API change was needed. The existing inventory-movement update timestamp was not previously rendered on this overview and is not required to close this finding.

### Resolved P3 — Avoid redundant readiness counts and stretched empty space

Final template shows the headline current-proof count once, retaining to-review and overdue beneath it. The original `data-ready` test hook now shares that headline element. Board uses start alignment when More next steps is open, avoiding an equally tall empty readiness card while retaining balanced collapsed cards. These polish findings are closed by source review; the parent reports a successful 30-screenshot pass under `~/.cache/workflow-engine-ui-shots/compliance/03`.

## Re-review and correction

The original P1 navigation finding is **withdrawn**. I missed the explicit boosted-assets mechanism in `base_spa.html:293–303`: on `HX-Boosted` requests, the shell copies both `self.head_extras()` and `self.scripts()` into hidden containers inside `#page-content`, where htmx executes the scripts. Their normal full-page location outside that subtree does not establish a broken destination. Retaining `hx-boost="false"` preserves the old overview links' navigation behavior, rather than repairing a proven initialization failure. The link helper comment now accurately states that preservation. The plan correctly describes page-local lifecycle support and acknowledges that the shell already carries scripts/styles on boosted loads.

The original P2 authentication/access finding is resolved: 401 offers a full-page Sign in link to the existing `/` landing/sign-in page, 403 gives admin access guidance, and neither offers an ineffective retry. Transient errors retain retry and avoid parser/raw server messages.

Both original P3 accessibility findings are resolved: the visual `order:-1` rule was removed, matching the evidence-then-action DOM order, and the Applicable frameworks section restores a named region.

## Checks and positive findings

- Template extends the shared SPA shell and retains shared workspace links. The custom header is deliberate under page-design's shared workspace layout, rather than an unrelated new header system.
- Dynamic values use `textContent` and DOM node creation, with internal destinations built from fixed paths and encoded Customs control IDs. No dynamic `innerHTML`, secret storage, or unsafe template values found.
- The only new request is a same-origin read-only GET outside Core; raw fetch introduces no mutation/CSRF omission here. Server authentication and subscription gates remain active.
- `bize.onPage` initializes each root once, supports revisits, and invokes the returned abort teardown on swaps. Root-scoped element assumptions match this template. Retry is disabled during loading, preventing overlapping requests.
- Counts match backend `summary_health` and `evidence_readiness`; overdue is explicitly described as a subset of attention. NP1/NP2/NP3 naming is derived from the actual programme rather than hardcoded NP3. Coverage is identified as operational evidence rather than legal compliance.
- Concept selection has labelled buttons and pressed state; framework details and next-step disclosures use native semantics; progress is individually labelled. Styles use shared theme tokens and scoped CSS.
- Empty setup handles managers and viewers separately; viewers receive an admin instruction instead of a setup mutation. Error UI is visible and announced.
- Focus, Board and Register differ structurally in priority, paired regions and framework disclosure density. No requirement to remove the three concepts before the user picks; the MR must stay draft.

## Verdict

**Approved for draft concept review; no unresolved code findings.** Page-design's overall run remains **findings-open** solely because the founder's concept choice is pending. After selection, remove the chooser and losing styles/tests and perform the final winner verification before taking the MR out of draft. Auth recovery, accessibility, live-data visibility and spacing corrections pass source review. JavaScript syntax check passed. This report is a source/lifecycle review, not a substitute for the parent task's real browser screenshot and interaction loop.
