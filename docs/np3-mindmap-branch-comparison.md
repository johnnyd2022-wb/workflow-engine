# NP3 mind map vs. `feat/np3-guided-operations`: comparison

Date: 2026-09-12
Source: Miro mind map (board `uXjVHocGNYc`), compared against the working tree on
`feat/np3-guided-operations` at the point Codex paused for quota (uncommitted changes to
`app/features/compliant/modules/nz_alcohol/np3_audit.py`, `module.py`, `service.py`,
`api_routes.py`, and the compliant frontend/templates/tests).

This is a read-only comparison. Nothing in the WIP diff was touched — see the "How to use
this" note at the end for why.

## What the mind map actually is

A restatement, in the founder's own words and with Whistlebird-specific detail, of the
National Programme 3 (Food Act 2014, MPI) guidance card — the same document the branch
already encodes as `np3-food-control` in `catalogue.py` and drives through
`NP3_AUDIT_CATEGORIES` / `NP3_EVIDENCE_PLAYBOOKS` / `NP3_LOG_TEMPLATES` in `np3_audit.py`.
Structurally the two are the same taxonomy: hazards (biological/chemical/physical),
record-keeping, competency, water supply, sourcing/receiving/tracing, pest control,
maintenance, storage & display, separating food, cooking/pasteurising, packing &
labelling, and the recall/verification process.

## Where they agree (no action needed)

The branch's control catalogue is a strict superset of the mind map's topic list — every
node in the mind map maps to an existing `control_id` in `NZ_ALCOHOL_FRAMEWORKS["np3-food-control"]`.
The branch also already goes further than the board in places the board doesn't model at
all: per-control `state` derivation (ready/attention/missing), guidance-version drift
detection (`guidance_update_required`), roster-driven staff-training gap detection
(`staff_actions`), and structured log templates with typed fields for staff-competency,
health-and-sickness, cleaning-and-hygiene, receiving-food, time-temperature-processing,
cooling-freezing, display-temperature, calibration, pest-animal-control, corrective-actions,
and trace-and-recall.

## Gaps: things the board has that the branch doesn't act on yet

1. **Water supply is generic; the board has site-specific facts.** The board names the
   actual source (Petone Aquifer), notes it's council-monitored, that storage containers
   previously held pure NGS (96.4% ethyl alcohol), and flags a recurring pH check. The
   `water-supply` playbook (`np3_audit.py`) has only generic example fields
   (`water_source`, `water_assurance`). Worth folding the site facts in as example/help
   text the way `_field_guidance` already does for other controls, or as a per-org
   free-text "site facts" note — no log template exists for water supply at all yet.

2. **No maintenance log template.** `pest-animal-control` gets a full structured register
   (`pest_inspection`); `maintenance` gets a playbook and a Core-tasks pointer but no
   register of its own, even though the board separately calls out (a) maintenance
   chemicals/compounds needing their own labelling/storage/segregation-from-food controls,
   distinct from general chemical hazards, and (b) "record when something goes wrong with
   maintenance" as its own record type — closer in shape to `corrective-actions` than to a
   simple task reminder. A `maintenance` entry in `NP3_LOG_TEMPLATES` (device/area,
   what was found, food-safety release decision) would close this.

3. **MPI recall-notification specifics are nowhere in the code.** The board has the
   operational detail a founder actually needs mid-incident: notify MPI within 24 hours,
   call 0800 00 83 33 for the Food Compliance team (or ask for the on-call Food Safety
   Officer after hours), and the trade-level vs. consumer-level recall distinction. None
   of this appears in `trace-and-recall` or `unsafe-unsuitable-food`'s playbook `proof`/
   `fields`. This is static reference content, not logic — cheap to add, high real-world
   value if a recall ever happens.

4. **Bottling/packaging handling is more specific on the board.** "Keep bottles boxed and
   sealed until ready for bottling," "cork immediately after filling" — process discipline
   for a spirits producer that's more concrete than the current `food-labelling-advertising`
   playbook's label-review framing. Could live as example content there or under
   `equipment-design`.

5. **Dried botanicals / reducing water content has no example anywhere.** The board
   explicitly ties "package or store concentrated/dried foods to prevent water
   reabsorption" to dried botanicals — a gin-specific ingredient class. Worth an example
   under `food-standards-microbiological` or `storage-stock-rotation`.

6. **"Application changes" — an ingredient-tracing UI feature, not an audit item.** The
   board has a distinct node (not part of the NP3 topic tree) proposing: a button on an
   ingredient + expiry date that surfaces full tracing — every batch that used it, every
   sale from those batches, which retailers stock the product, and an estimate of
   remaining stock. This is a Core/Inventory/Source Map feature, not a compliance-module
   change. It's already anticipated structurally — `NP3_CORE_CONNECTIONS["trace-and-recall"]`
   points at `/core/sourcemap?show=check-needed` — but the board's ask (expiry-driven,
   button-triggered, retailer-level rollup) is more specific than what Source Map does
   today. Worth a proper feature spec of its own rather than folding into this branch.

## Gaps the other way

Nothing found: everything on the board is either already covered by the branch's control
catalogue, or falls into the gaps above. The branch has no NP3 topic that isn't reachable
from the board's tree (the board just doesn't elaborate every branch to the same depth,
e.g. `defrosting-reheating`, `importing-food`, `waste-management`, `equipment-design` are
present in `catalogue.py` but weren't drawn out on the board — consistent with those being
lower-relevance for a distillery and not evidence the board disagrees with the code).

## How to use this

Items 1–5 are small, additive changes to `np3_audit.py` (new dict entries / example
strings) — exactly the kind of edit that should wait for Codex's current pass on that
file to land, to avoid a conflict on an actively-edited file. Item 6 is unrelated code
(Core/Source Map, not `compliant/`) and could be scoped as its own spec independently of
this branch. Nothing here blocks the current WIP; treat this file as the backlog to work
from once `feat/np3-guided-operations` merges.
