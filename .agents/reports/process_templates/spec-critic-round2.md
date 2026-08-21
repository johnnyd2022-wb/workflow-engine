# spec-critic round 2: process_templates

Spec: `.agents/specs/process_templates.md` (status: `approved-unattended`)
Prior report: `.agents/reports/process_templates/spec-critic.md` (verdict: gaps-found,
2 high, 1 medium, 1 low)

Re-verified against the real code: `app/core/backend/backend.py` (lines 213-450 for the
wizard-sequencing/`_maybe_enforce_flow_wizard_step` machinery, lines 2273-2360 for the
output-typing / `custom_expiry` `od`-lookup precedent), `app/core/db/models/process.py`
(`description = Column(String(1000), ...)`), `app/features/compliant/models/
compliance_profile.py` (`enabled`, `industry_module` columns), and
`docs/industry-process-templates-spec.md` (source PRD, to check the AC10 reinterpretation
against the PRD's actual wording).

## Fix 1 — AC9 `sample_only` mechanism: HOLDS

Confirmed the precedent is real and matches the spec's description precisely.
`backend.py:2339-2348` already does exactly the pattern the spec cites: iterates
`step_def.outputs` (a list of dicts), matches by `od.get("name") == output_name`, and
reads `(od.get("extra_data") or {}).get("custom_expiry")`. The spec's proposed
`sample_only` check is the same shape: `(od.get("extra_data") or {}).get("sample_only")
== True`, forcing `inventory_type = InventoryType.WORK_IN_PROGRESS.value` regardless of
`execution_step.is_terminal_step` (currently the sole determinant, `backend.py:2296-2303`,
confirmed unchanged).

One implementation-order detail the spec doesn't spell out: today, `inventory_type` is
assigned (line ~2301-2303) *before* the code reaches the `custom_expiry` `od`-lookup
(line ~2339). A `sample_only` override therefore needs its own lookup positioned before
(or the assignment moved after) that existing block — the spec says "same precedent," not
"same code location," so it isn't asserting an order that doesn't exist. This is a pure
implementation-placement detail with one obviously-correct answer (any competent build
gets identical testable behavior), not an ambiguity that risks a wrong build. Not a gap.

The spec is also honest about scope: the blueprint header now flags this up front
("plus one small, precedented change to existing shared execution-completion code in
`app/core/backend/backend.py`"), and AC8's "no template-specific execution code" claim
still holds because the new check is driven by a generic `extra_data.sample_only` flag on
any step's output definition — usable by any process, not gated to template origin —
exactly parallel to how `custom_expiry` already works. No contradiction with "Data model:
changes: none" either, since this is behavior code, not schema.

## Fix 2 — AC6/AC10 response-shape conflict: HOLDS

Checked the PRD's actual language (`docs/industry-process-templates-spec.md:51-54,199`):
"Template cards and confirmation language explicitly tell the operator to customise..."
and "an explicit 'customise before using' statement" on each card. Nothing in the PRD
requires the advisory to live in the `POST .../copy` JSON response specifically — "cards
and confirmation language" reads naturally as frontend UI copy (cards + a pre-copy
confirmation step), which is exactly how the spec now resolves it.

AC10 is now scoped explicitly: the advisory is required in AC2/AC3 (list/detail)
responses, and the frontend (AC12) renders it "in the confirmation step before calling
AC6's copy endpoint" — sourced from the detail response, not duplicated. AC6 is
reaffirmed unchanged: `{"process_id": ...}` only. The two ACs now agree on what the copy
endpoint returns. No residual contradiction, and the reinterpretation is a defensible
reading of the PRD's own wording, not an invented one.

## Fix 3 — AC12/AC13 (catalogue page, post-copy redirect): HOLDS, verified against real routing code

Checked `_maybe_enforce_flow_wizard_step` (`backend.py:417-450`) and the step-map
(`backend.py:213-230`, confirms `/core/flows/create/summary` is registered as step 6).
For a freshly-copied process navigated to directly via `?id=<process_id>`: `started` is
initially `False` in session state, but because `process_id is not None`, the function
initializes `bucket["started"] = True` and `max_step = max(1, requested)` in place —
i.e. it does **not** redirect away. AC13's redirect target
(`/core/flows/create/summary?id=<process_id>`) is a real, reachable route today, exactly
as the round-1 report predicted ("likely isn't broken") — now confirmed, not just
inferred.

AC12 covers route existence, auth (`@requires_auth`), content (family filter, cards,
preview panel, "Use this template" action), and the empty-family 200-not-404 behavior
consistent with AC2. Both ACs are testable as written.

One thin residual: AC1 (the chooser) never states that choosing "Start from a template"
navigates the browser to AC12's `/core/flows/create/template-catalog` URL — only the
"Start from scratch" branch's destination is pinned. In isolation this would be a
Description/AC coverage gap (the Description promises the choice; AC1 only tests half of
it). In practice it is forced to one answer: `template-catalog` is the only template-browsing
URL anywhere in the spec (also named in the top-of-file `url_prefix` line), so there is no
second plausible destination for an implementer to guess wrong toward. I'm noting it
rather than gating on it — see verdict note below.

## Fix 4 — AC6 fallback/truncation text: HOLDS, cleaner than the round-1-suggested fix

The round-2 rewrite didn't invent arbitrary fallback copy (which is what round 1 flagged
as needing definition) — it eliminated the need for any: when a template has no
description, the field is just `"Created from: <template name> v<catalogue_version>"`
alone, with no separate fallback sentence to define. When a description exists, the join
is explicit: `"<template.description>\n\nCreated from: <template name>
v<catalogue_version>"` — separator is literally `"\n\n"`, not left to interpretation.

The truncation rule is fully determined, not just "a rule exists": `Process.description`
is confirmed `String(1000)` in `app/core/db/models/process.py:32`, matching the spec's
claim exactly. Given the suffix and separator are fixed-length strings, "truncate the
template's own description first so the suffix is never cut" pins an exact, computable
truncation length (`1000 - len(separator) - len(suffix)` characters of the template
description kept) — no ellipsis/word-boundary decision is left open because none is
needed. This is falsifiable: a test can assert the exact resulting string for a
deliberately-long fixture description. Gap closed, no residual ambiguity.

## Fresh pass: one new minor observation (not counted as a blocking gap)

- `catalogue_version` (used in AC6's exact provenance string) is never defined anywhere
  in the spec — not its type, not whether it's global-to-the-registry or per-template,
  not its starting value. Unlike round 1's fallback-text gap, this doesn't require
  inventing human-facing copy: "version" on a "versioned Python registry" (spec's own
  Data-model wording) has an obvious, low-risk default (a module-level int constant,
  starting at 1) and AC6 is still testable by pattern/format even without the spec
  pre-committing a literal number — a test reads whatever value the implementation
  assigns and asserts the string is built from it, same as any other internally-generated
  version identifier. Judged not to rise to gap severity: no plausible wrong-guess path,
  no security/tenant/data-loss exposure, cosmetic only.

No other contradictions, scope shifts, or vague terms were introduced by the four edits.
Tenant scoping, destructive-changes, and external-surfaces sections are unchanged from
round 1 and were re-spot-checked against `compliance_profile.py` and `process.py` — still
accurate.

## Verdict rationale

Both high-severity gaps from round 1 (AC9's unbuildable mechanism, AC6/AC10's direct
contradiction) are closed and now grounded in verified real code, not just assertion. The
medium gap (missing catalogue-page/redirect ACs) is closed by AC12/AC13, confirmed
against the actual wizard-sequencing code rather than taken on faith. The low gap
(undefined fallback/join text) is closed more cleanly than round 1 suggested. The two
residual items found in this fresh pass (AC1→AC12 button target; `catalogue_version`
definition) are both forced-to-one-answer or risk-free-to-infer — neither creates a
plausible path to a wrong build, unlike the original high-severity items, which had
multiple plausible-but-incompatible readings. Per the skill's own standard ("is this
buildable without guessing" — not "is this the best possible spec"), the spec clears that
bar.

VERDICT: sound
