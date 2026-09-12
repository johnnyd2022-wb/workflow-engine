# NP3 mind map vs. `feat/np3-guided-operations`: build backlog

Date: 2026-09-12
Source: Miro mind map (board `uXjVHocGNYc`), compared against the working tree on
`feat/np3-guided-operations` at the point Codex paused for quota (uncommitted changes to
`app/features/compliant/modules/nz_alcohol/np3_audit.py`, `module.py`, `service.py`,
`api_routes.py`, and the compliant frontend/templates/tests).

This is a build spec, not a status report — each finding below is written to hand to
Codex directly once the current WIP lands. Nothing here has been implemented; the
proposed schemas reuse the existing `_playbook()` / `_log_template()` shapes in
`np3_audit.py` so they can be dropped in with minimal redesign.

## What's already settled

The branch's control catalogue (`NZ_ALCOHOL_FRAMEWORKS["np3-food-control"]` in
`catalogue.py`) is a strict superset of the mind map's topic list, and the branch already
goes further than the board in ways the board doesn't represent at all (per-control state
machine, guidance-version drift detection, roster-driven staff-training gaps). Ingredient
tracing — the board's "Application changes" node (expiry-driven button surfacing batches,
sales, retailers stocking, remaining stock) — is **done**: Core tracing already covers
this and links to the relevant NP3 evidence sections. No further action there.

The five items below are the real gaps: places where the board carries operational detail
the code doesn't act on yet.

---

## 1. Water supply: self-supplied vs. council-reticulated need different evidence

**Regulatory nuance.** NP3 draws a real line the current code doesn't: water connected to
a monitored public/council network is the network operator's responsibility to keep
suitable, so the food business mainly needs to show it's on that supply and stays alert to
any advisory (e.g. a boil-water notice) affecting production. Self-supplied water — a
private bore, roof collection, or (as here) drawing from the Petone Aquifer — puts the
suitability burden on the operator: it needs its own testing regime (typically
bacteriological at minimum, plus anything else relevant to how the water is used), and the
test *frequency* and *parameters* are a judgement call for the operator/verifier to set,
not a number this app should assert. That mirrors how `trade-waste` already refuses to
assert numeric discharge limits — same principle applies here.

There's a second, distinct issue the board raises: storage containers **repurposed** from
another use (the board specifically notes containers that previously held pure NGS —
96.4% ethyl alcohol — now used for water storage). Reusing a non-food-grade or
previously-contaminated vessel is a suitability/equipment-design question independent of
the water source itself, and today nothing prompts for it.

**Current gap.** `water-supply` (`np3_audit.py` → `NP3_EVIDENCE_PLAYBOOKS["water-supply"]`)
has only two generic fields (`water_source`, `water_assurance`) and **no log template** —
unlike `pest-animal-control` or `calibration`, there's no structured register at all.

**Proposed schema.**

Add a `water_source_type` field to the existing playbook so the UI can branch:

```python
"water-supply": _playbook(
    "Ensuring your water is suitable",
    64,
    ("Water source and suitability assessment", "Relevant treatment, test or maintenance record"),
    (
        ("water_source_type", "Is this water self-supplied or from a council/reticulated network?"),
        ("water_source", "Water source reviewed"),
        ("water_assurance", "Test, treatment or assurance reference (self-supplied) or network confirmation (reticulated)"),
        ("storage_container_provenance", "Any reused/repurposed storage container and how it was made suitable"),
    ),
),
```

And a log template — this is the piece that's actually missing:

```python
"water-supply": _log_template(
    "water_check",
    "Water suitability register",
    "One entry per test or check. Self-supplied sources need their own test result; "
    "a reticulated/council supply only needs the periodic confirmation that the "
    "connection is active and no advisory is in effect.",
    "reading",
    (
        {"key": "event_date", "label": "Check or test date", "type": "date", "required": True},
        {
            "key": "source_type",
            "label": "Source type",
            "type": "select",
            "required": True,
            "options": (("self-supplied", "Self-supplied (bore/aquifer/collected)"), ("reticulated", "Council/reticulated network")),
        },
        {"key": "test_or_check", "label": "Test performed / check made", "type": "text", "required": True},
        {"key": "result", "label": "Result", "type": "select", "required": True, "options": (("ok", "Suitable"), ("action-required", "Action required"))},
        {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
    ),
),
```

`source_type` on each entry (rather than a fixed per-org setting) matters if the org ever
draws from more than one source, or switches — the register should show which kind of
check each entry actually was.

**Priority:** medium-high — there's currently zero structured record for the org's actual
water source, which is one of the more concrete verifier-facing gaps.

---

## 2. Maintenance has no log template — and the board wants two different kinds of entry

**Regulatory nuance.** The board separates two things that are easy to conflate:
*planned* maintenance/servicing (equipment condition checks, servicing schedule,
premises deterioration checks — routine, low-drama), and an *unplanned* finding — "record
when something goes wrong with maintenance" — which is closer in shape to a
corrective-action (something broke, was product/production affected, what was done about
it) than to a routine service log. The board also calls out a control the code doesn't
surface anywhere: maintenance compounds/chemicals (lubricants, coolants, CIP chemicals
used in servicing) must be labelled, stored/sealed per manufacturer instructions, and kept
in containers that can't be mistaken for food containers — distinct from the general
food-contact cleaning-chemical control already covered by `cleaning-and-hygiene`.

**Current gap.** `maintenance` (`catalogue.py`) has a playbook and a `NP3_CORE_CONNECTIONS`
entry pointing at Core Tasks for scheduling, but **no `NP3_LOG_TEMPLATES` entry** —
`pest-animal-control`, which is structurally the closest analogue (recurring
inspection + finding + corrective action), does have one. Maintenance doesn't.

**Proposed schema.**

```python
"maintenance": _log_template(
    "maintenance_check",
    "Maintenance and equipment-condition register",
    "Covers both routine servicing and an unplanned defect. A defect entry should "
    "record whether production was affected and the food-safety release decision "
    "before equipment/premises went back into use.",
    "reading",
    (
        {"key": "event_date", "label": "Date", "type": "date", "required": True},
        {"key": "asset_or_area", "label": "Asset, equipment or area", "type": "text", "required": True},
        {
            "key": "entry_type",
            "label": "Entry type",
            "type": "select",
            "required": True,
            "options": (("planned-service", "Planned service/check"), ("defect-found", "Unplanned defect/failure")),
        },
        {"key": "task_or_finding", "label": "Task performed / what was found", "type": "textarea", "required": True},
        {
            "key": "maintenance_chemicals_checked",
            "label": "Maintenance chemicals labelled, sealed and stored apart from food (if used)",
            "type": "select",
            "required": False,
            "options": (("ok", "Confirmed"), ("not-applicable", "No chemicals used"), ("action-required", "Action required")),
        },
        {
            "key": "food_safety_release",
            "label": "Food-safety release decision",
            "type": "select",
            "required": True,
            "options": (("cleared", "Cleared for production use"), ("not-cleared", "Not cleared — action pending")),
        },
        {"key": "corrective_action", "label": "Corrective action (defects only)", "type": "textarea", "required": False},
    ),
),
```

Keeping this as one log template (rather than splitting planned/unplanned into two
separate registers) means a verifier sees the full maintenance history for an asset in one
place, with `entry_type` doing the filtering. If Codex's implementation review finds the
mixed shape awkward in practice, splitting `defect-found` entries into the existing
`corrective-actions` register (tagged with a `source_control: "maintenance"` detail) is
the fallback — but that loses the asset/area field, so the dedicated template above is the
better default.

**Priority:** high — this is the clearest structural gap: an MPI-named record type with
zero representation today, not just missing example content.

---

## 3. MPI recall notification details are absent from the code entirely

**Regulatory nuance.** The board carries the exact operational detail a founder needs
*during* an actual recall, which is meaningfully different from "evidence to show a
verifier": notify MPI as soon as possible and within 24 hours; call 0800 00 83 33 for the
Food Compliance team during business hours, or ask for the on-call MPI Food Safety Officer
after hours; and the trade-level (product already out to retail/distributors) vs.
consumer-level (public notification required) distinction, which changes what response is
proportionate. None of this appears anywhere in `trace-and-recall` or
`unsafe-unsuitable-food`.

**Current gap.** Both playbooks only ask for evidence references
(`mock_recall_date`/`trace_result`, `affected_product`/`disposition`/`incident_reference`)
— there's no quick-reference content for what to *do* if a real recall starts.

**Proposed approach.** This is reference content, not an evidence field, so it shouldn't
be forced into the `fields` tuple that drives log entries. Two options for Codex to choose
between:

- **(a) Extend `_playbook()`** with an optional `reference_notes: tuple[str, ...]` the
  frontend renders as a callout (not a form field) on the `trace-and-recall` and
  `unsafe-unsuitable-food` cards:
  ```python
  reference_notes=(
      "Notify MPI as soon as possible and within 24 hours: call 0800 00 83 33 for "
      "the Food Compliance team (business hours) or ask for the on-call MPI Food "
      "Safety Officer (after hours).",
      "Trade-level recall = product already distributed to retail/distributors. "
      "Consumer-level recall = public notification is required.",
  )
  ```
- **(b) A standalone `NP3_RECALL_QUICK_REFERENCE` constant** in `np3_audit.py` that the
  frontend surfaces prominently whenever a `trace-and-recall`/`unsafe-unsuitable-food`
  card is opened, independent of the playbook's evidence-field machinery. Simpler to ship
  first; (a) is the more integrated long-term shape.

Either way: **verify the phone number and 24-hour window against the current
`NP3_GUIDANCE_VERSION` ("2025-v2") card before hardcoding it** — the guidance-drift
detection this branch already built (`guidance_update_required`) exists precisely because
this kind of detail can change between versions, and a stale emergency phone number is
worse than none.

**Priority:** high-value, low-effort — pure reference content, no new data model, but the
kind of thing that matters most in exactly the moment it'd be most annoying to be missing.

---

## 4. Bottling/packaging handling has no home

**Regulatory nuance.** The guidance card groups packaging and labelling under one section
("Packaging and labelling your food", page 61 — already cited by `food-labelling-advertising`),
so this doesn't need a new control_id. But the board's detail is about *handling*, not
label content: keep bottles boxed/sealed until immediately before filling (limits dust/pest
exposure to empty bottles), cork/cap immediately after filling (limits contamination and
oxidation window), and handle packaging materials (labels, corks, boxes) with the same care
as an ingredient — i.e. not stored somewhere exposed to pests or damp. `food-labelling-advertising`
today only asks about label/artwork approval, not this.

**Current gap.** No log template exists for `food-labelling-advertising` at all — same
situation as `water-supply`.

**Proposed schema.** Given this is closer to an observed-practice check (similar to
`personal-hygiene`) than a per-batch reading, a lightweight log is enough:

```python
"food-labelling-advertising": _log_template(
    "packaging_handling",
    "Packaging handling verification",
    "Spot-check that empty packaging and filled containers are handled to prevent "
    "contamination between unpacking and sealing.",
    "reading",
    (
        {"key": "event_date", "label": "Check date", "type": "date", "required": True},
        {
            "key": "checked_practice",
            "label": "Practice checked",
            "type": "select",
            "required": True,
            "options": (
                ("bottles-boxed-until-filling", "Bottles kept boxed/sealed until filling"),
                ("corked-immediately", "Corked/capped immediately after filling"),
                ("packaging-storage", "Packaging materials stored away from contamination risk"),
            ),
        },
        {"key": "result", "label": "Result", "type": "select", "required": True, "options": (("ok", "Confirmed"), ("action-required", "Action required"))},
        {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
    ),
),
```

**Priority:** lower than 1–3 — this is process discipline that's easy to skip recording,
but a gap in a "nice to have" register rather than a missing MPI-named control.

---

## 5. Dried botanicals / "reducing water content" has no example anywhere

**Regulatory nuance.** "Reducing water content" (drying) and "making food acidic" are two
of the standard methods NP3 recognises for making food safe, alongside cooking/pasteurising
(`time-temperature-processing`) and chilling/freezing. Neither has its own control_id in
`catalogue.py` — they're implementation detail under the general `biological-hazards`
("process controls for biological hazards") bucket, which is correct; they don't need to
become new controls. What's missing is the example content that makes the generic control
concrete for this business: botanicals (juniper, citrus peel, etc.) are stored dry
specifically to prevent water reabsorption, and — per the board — acidification is **not
applicable** to Whistlebird's product line. Leaving that silent invites a verifier question
that a one-line attestation would pre-empt.

**Current gap.** `biological-hazards` playbook (`np3_audit.py`) has generic fields
(`hazard`, `control_verification`) with no example text at all.

**Proposed change.** No schema change needed — just richer `_field_guidance` example
content, the same mechanism already used for `training_register_reference` etc.:

```python
"hazard": (
    "Name the specific biological hazard and how it's controlled for this product/ingredient.",
    "Dried botanicals (juniper, citrus peel) stored dry to prevent water reabsorption; "
    "acidification is not applicable to this product line.",
),
```

**Priority:** lowest of the five — cosmetic/example-quality improvement, not a missing
record type.

---

## Sequencing note

Items 2 and 3 are the highest-value, most concrete gaps (a genuinely missing MPI-named
register, and safety-critical reference content with zero present coverage). Item 1 is
next — it's a real missing register, just lower-stakes day to day than a maintenance
defect or a live recall. Items 4 and 5 are polish. None of this should be started until
Codex's current pass on `np3_audit.py`/`catalogue.py` lands, to avoid working the same
file at the same time.
