# NP3 mind map vs. `feat/np3-guided-operations`: build backlog

Date: 2026-09-12 (fact-checked 2026-09-12 against the primary source)
Source: Miro mind map (board `uXjVHocGNYc`), compared against the working tree on
`feat/np3-guided-operations` at the point Codex paused for quota (uncommitted changes to
`app/features/compliant/modules/nz_alcohol/np3_audit.py`, `module.py`, `service.py`,
`api_routes.py`, and the compliant frontend/templates/tests), and verified directly
against **National Programme 3 Guidance, December 2025 Version 2**
(`NP3_GUIDANCE_URL` in the code: `https://www.mpi.govt.nz/dmsdocument/21853/direct`) —
the same version the code's `NP3_GUIDANCE_VERSION = "2025-v2"` claims to track. Every
page number and quoted fact below was read directly from that PDF, not carried over
from the mind map or the code without checking.

## Fact-check note — page citations in the existing code are frequently wrong

Before getting to the five content findings, the more urgent thing this check turned up:
`NP3_EVIDENCE_PLAYBOOKS` in `np3_audit.py` cites a `page` number and section title for
every control, presumably meant to deep-link a verifier/operator straight to the right
card. Checked against the actual Dec 2025 v2 contents page, **most are wrong** — some by
a few pages, one collapses two entirely separate cards into one citation. This predates
anything in this doc; I'm flagging it rather than fixing it, per "don't touch the WIP
files."

| Control(s) | Code says | Actual page / card |
|---|---|---|
| `registration-scope`, `delegation` | p12 "Taking responsibility" | ✅ correct |
| `documentation-record-keeping`, `operator-verification` | p19 "Checking the programme is working well" | p15 — p19 is actually "Managing places and equipment" |
| `staff-competency` | p26 | p25 |
| `personal-hygiene`, `health-and-sickness` | p32 | ✅ correct |
| `cleaning-and-hygiene` | p27 | ✅ correct |
| `pest-animal-control` | p29 | ✅ correct |
| `maintenance` | p30 | ✅ correct |
| `trace-and-recall`, `suppliers-and-purchasing`, `receiving-food`, `importing-food` | p35 "Sourcing, receiving and tracing food; Recalling food" | Wrong on both counts — "Sourcing, receiving and tracing food" is p37; "Recalling your food" is a **separate** red card at p68. p35 is actually "Producing, processing or handling food". |
| `food-standards-composition`, `allergen-management` | p40 "Allergens and knowing what is in your food" | p43 — p40 is actually "Safe storage and display" |
| `food-standards-microbiological`, `cross-contamination`, `biological-hazards`, `chemical-hazards` | p43 "Preventing contamination of your food" | p46 |
| `time-temperature-processing`, `cooking-poultry` | p46 "Thoroughly cooking or pasteurising food" | p48 |
| `defrosting-reheating` | p48 | p53 |
| `storage-stock-rotation`, `cooling-freezing`, `display-temperature` | p37 "Safe storage and display" | p40 |
| `calibration` | p57 "Checking measuring equipment" | There's no standalone card by this name — calibration is a sub-point of "Managing places and equipment" (p19/31) |
| `physical-hazards` | p57 "Keeping foreign matter out of food" | p59 — p57 is actually "Pickling, fermenting, or acidifying food" |
| `waste-management`, `premises-services`, `equipment-design` | p59 "Managing places and equipment" | p19 |
| `water-supply` | p64 "Ensuring your water is suitable" | p21 — p64 is actually "Transporting food" |
| `transporting-food` | p66 | p64 |
| `food-labelling-advertising` | p61 "Packaging and labelling your food" | ✅ correct |
| `corrective-actions`, `unsafe-unsuitable-food` | p67 "Taking action when something goes wrong" | p66 |

Worth a small, low-risk cleanup pass on `NP3_EVIDENCE_PLAYBOOKS["page"]` once Codex's
current edits land — these are exactly the kind of deep-link a verifier or new staff
member would actually click, and right now most of them land on the wrong card.

## What's already settled

The branch's control catalogue is broader than the mind map's topic list in most places,
and already goes further than the board in ways the board doesn't represent at all
(per-control state machine, guidance-version drift detection, roster-driven
staff-training gaps). Ingredient tracing — the board's "Application changes" node — is
**done**: Core tracing already covers this and links to the relevant NP3 evidence
sections. No further action there.

The five items below are the real gaps, now written up with the verified regulatory
detail (not the mind map's paraphrase) so Codex can build directly from official wording.

---

## 1. Water supply: self-supplied vs. registered-supplier evidence are genuinely different obligations

**Verified against p21–24 ("Ensuring your water is suitable").** This is a bigger split
than "self-supplied vs. council", and it's more prescriptive than either the mind map or
my first draft suggested:

- **Registered drinking water supply** (e.g. council/network): the *supplier* carries
  responsibility for safety. Suppliers have until **November 2025** to register with
  Taumata Arowai (searchable at `hinekorako.taumataarowai.govt.nz/publicregister/supplies/`).
  The operator's obligation is mainly to know they're on a registered supply.
- **Self-supply water** (rainwater, own bore, any source other than a registered
  supplier — this is exactly the Petone Aquifer case): the operator must have it
  **tested at an accredited lab** (`hinekorako.taumataarowai.govt.nz/publicregister/laboratories/`):
  - before using any new source for the first time, **and**
  - within 1 week of restarting operations after severe weather/an adverse event that
    could have affected the supply.
  - Required test criteria (this is a real table in the guidance, not an
    operator-set frequency — correcting my first draft, which assumed the app
    shouldn't assert numbers here):

    | Measurement | Criteria |
    |---|---|
    | *E. coli* | < 1 cfu/g in any 100 mL sample (must be accredited-lab tested) |
    | Turbidity | ≤ 5 NTU |
    | Chlorine (when chlorinated) | 0.2–5 mg/L, min. 30 min contact time |
    | pH (when chlorinated) | 6.5–8.0 |

    Note the pH criterion is conditional on chlorination (it's there because pH affects
    chlorine's disinfecting power) — it is **not** a general water-quality check
    independent of treatment method. The mind map's "also check PH levels regularly" is
    correct as a reminder but should be scoped to "if/when the water is chlorinated",
    not presented as a standalone rule.
  - Bores must be "designed and maintained so they are protected from surface
    contamination."
  - Water intakes must be ≥10m from livestock and ≥50m from contamination sources
    (silage stacks, offal pits, waste, chemical stores).
- **All water supplies, regardless of source**: "Only use water tanks, containers,
  pipes, taps and treatment systems... that are safe for drinking water (food-grade)."
  This directly validates the mind map's concern about containers that previously held
  pure NGS (96.4% ethyl alcohol) now storing water — the guidance's rule is general
  (any storage vessel must be food-grade), not specific to reuse, but the board's
  instinct to flag a repurposed container is exactly the kind of thing this rule is for.
- Record-keeping: "It is recommended you record the water source for each of the sites
  you operate in" (recommended, not phrased as mandatory) and, explicitly, **"You need
  to keep records of self-supply water tests"** (mandatory, self-supply only).

**Current gap.** `water-supply` (`np3_audit.py`) has only two generic fields
(`water_source`, `water_assurance`), cites the wrong page (64 instead of 21), and has no
log template — `pest-animal-control`/`calibration` get structured registers, water
supply doesn't.

**Proposed schema.**

```python
"water-supply": _playbook(
    "Ensuring your water is suitable",
    21,
    (
        "Water source and, for self-supply, accredited-lab test results",
        "Food-grade storage/tank/container evidence, including any repurposed vessel",
    ),
    (
        ("water_source_type", "Registered supplier (e.g. council) or self-supply (bore/roof/aquifer)?"),
        ("water_source", "Water source reviewed"),
        ("water_assurance", "Supplier registration reference (registered) or accredited-lab test reference (self-supply)"),
        ("storage_container_provenance", "Any repurposed/previously-used storage container and how it was confirmed food-grade"),
    ),
),
```

```python
"water-supply": _log_template(
    "water_check",
    "Water suitability register",
    "Self-supply sources need an accredited-lab test before first use and within a "
    "week of restarting after severe weather. A registered-network supply only needs "
    "the periodic confirmation that the connection/registration is current.",
    "reading",
    (
        {"key": "event_date", "label": "Test or check date", "type": "date", "required": True},
        {
            "key": "source_type",
            "label": "Source type",
            "type": "select",
            "required": True,
            "options": (("self-supply", "Self-supply (bore/roof/aquifer)"), ("registered-supplier", "Registered drinking-water supplier")),
        },
        {"key": "test_or_check", "label": "Test performed (self-supply: accredited lab) / check made", "type": "text", "required": True},
        {"key": "result", "label": "Result", "type": "select", "required": True, "options": (("ok", "Meets criteria"), ("action-required", "Action required"))},
        {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
    ),
),
```

**Priority:** high — self-supply water has a hard, numeric, lab-verified compliance
requirement with zero structured record in the app today.

---

## 2. Maintenance: the code's gap matches the card almost word for word

**Verified against p30–31 ("Maintaining equipment and facilities").** The mind map's
line is close to verbatim: the actual guidance says *"Ensure any substances or chemicals
used for maintenance are: fully labelled, stored, sealed and only used following the
manufacturer's instructions; stored and transported in containers that can not be
mistaken for food containers."* — this is a real, distinct rule, separate from general
food-contact cleaning chemicals (`cleaning-and-hygiene`).

One correction to my first draft: the guidance does **not** split maintenance into
"planned" vs. "defect found" record types the way I designed. Per the requirements table
(p9), `Maintenance` only has a "Required" (routine) obligation — an unplanned failure
falls under the generic "Taking action when something goes wrong" process (see finding
3), not a maintenance-specific incident type. A single routine register is the more
faithful shape; don't add an `entry_type` field for defects.

The guidance also explicitly says **"You must keep records of any maintenance you
do"** and suggests a maintenance schedule and/or maintenance record (MPI's own Record
Blanks template exists for this).

**Current gap.** `maintenance` (`catalogue.py`) has a playbook (page citation is
correct — p30) and a Core-tasks pointer, but no `NP3_LOG_TEMPLATES` entry at all.

**Proposed schema.**

```python
"maintenance": _log_template(
    "maintenance_check",
    "Maintenance register",
    "One entry per service or check. If maintenance chemicals/compounds are used, "
    "confirm they're labelled, sealed and stored in containers that can't be mistaken "
    "for food containers.",
    "reading",
    (
        {"key": "event_date", "label": "Date", "type": "date", "required": True},
        {"key": "asset_or_area", "label": "Asset, equipment or area", "type": "text", "required": True},
        {"key": "task_performed", "label": "Task performed / check made", "type": "text", "required": True},
        {
            "key": "maintenance_chemicals_checked",
            "label": "Maintenance chemicals labelled, sealed and stored apart from food (if used)",
            "type": "select",
            "required": False,
            "options": (("ok", "Confirmed"), ("not-applicable", "No chemicals used"), ("action-required", "Action required")),
        },
        {"key": "result", "label": "Result", "type": "select", "required": True, "options": (("ok", "Suitable/working properly"), ("action-required", "Action required"))},
        {"key": "corrective_action", "label": "Corrective action", "type": "textarea", "required": False},
    ),
),
```

An unplanned defect that turns into an incident should go through the existing
`corrective-actions` log template, not this one — that keeps the app's shape matching
the guidance's own two-track model instead of inventing a third.

**Priority:** high — confirmed missing register for a control with an explicit,
verbatim "you must keep records" requirement.

---

## 3. MPI recall notification: the mind map's phrasing doesn't match the current card — corrected version below

**Verified against p66–67 ("Taking action when something goes wrong") and p68–70
("Recalling your food") — two separate red cards, not one.** This is the finding where
fact-checking changed the most: the mind map's text ("notify MPI... call 0800 00 83 33
and ask for the Food Compliance team (business hours) or ask for the on-call MPI Food
Safety Officer (after hours)") does **not** match the current Dec 2025 v2 wording. The
phone number is right; the rest reads like a different version or a different MPI
process. Do not build from the mind map's wording for this one — use what's below.

**What the current guidance actually says:**

- **Two kinds of recall** (verbatim definitions):
  - **Consumer level** — "removing affected product from the supply chain **and**
    communicating to consumers."
  - **Trade level** — "removing affected product from the supply chain" (no public
    consumer communication).
- **Two recall triggers**:
  - **Supplier-notified** — a supplier tells you an ingredient/product/equipment/
    packaging you use has been recalled.
  - **Self-initiated** — you find your own food is unsafe/unsuitable.
- **Self-initiated recall process** (this is the structured sequence the guidance uses,
  good shape for a checklist UI): **Investigate** (gather info, identify affected
  products/batches, put affected product on hold) → **Inform** (tell your verifier, or
  call NZFS on 0800 00 83 33 and ask to speak to a **Food Coordinator**, or email
  `Food.Recalls@mpi.govt.nz`) → **Assess** (complete a Food Recall Risk Assessment form,
  email to NZFS) → **Check** (**report your recall decision to NZFS within 24 hours**,
  by email to `Food.Recalls@mpi.govt.nz` or by calling 0800 00 83 33 and asking for a
  Food Coordinator) → **Communicate** (point-of-sale notice for consumer-level; notify
  businesses that received the product for trade-and-consumer; notify consumers directly
  for consumer-level) → **Audit** (check product returned, review corrective/preventive
  actions, inform an **NZFS Food Compliance Officer** how the recall went).
- The **24-hour clock is on reporting the recall decision**, not on first becoming aware
  of a problem — a meaningfully different trigger than the mind map implies.
- A **simulated (mock) recall is required at least once every 12 months**, unless a real
  recall was already carried out effectively in that period.
- Records required: all actions taken (same retention as "Taking action when something
  goes wrong" — **at least 4 years**), the completed risk assessment form, and a copy of
  the recall notice.

**Proposed approach — unchanged from the first draft's structural idea, updated
content.** Extend `_playbook()` with an optional `reference_notes` tuple the frontend
renders as a callout (not a form field), on both `trace-and-recall` (p37, not p35 — see
fact-check table above; consider also citing p68 directly given it's a separate card)
and `unsafe-unsuitable-food`:

```python
reference_notes=(
    "Consumer-level recall = product removed from the supply chain AND consumers are "
    "notified directly. Trade-level recall = product removed from the supply chain, "
    "no public/consumer notification.",
    "Self-initiated recall: Investigate → Inform your verifier or NZFS (0800 00 83 33, "
    "ask for a Food Coordinator) → Assess (Food Recall Risk Assessment form) → report "
    "your recall decision to NZFS within 24 hours (email Food.Recalls@mpi.govt.nz or "
    "call 0800 00 83 33) → Communicate → Audit.",
    "A mock recall is required at least once every 12 months unless a real, effective "
    "recall already happened in that period.",
)
```

Re-verify this against whatever `NP3_GUIDANCE_VERSION` is current before shipping —
this is precisely the kind of process detail that changes between versions, which is
why the mind map's version and the current one already disagree.

**Priority:** high-value — this replaces a plausible-sounding but unverified claim
(mine and the board's) with the actual current process. Worth double-checking directly
with MPI/your verifier before this ships anywhere a real recall decision would be made
from it.

---

## 4. Bottling/packaging handling — confirmed, but the specific gin steps are the founder's own extrapolation, not MPI wording

**Verified against p61–63 ("Packaging and labelling your food") — the code's citation
(p61) is correct, unlike most others in the table above.** The guidance's actual line is
close to verbatim to the mind map: *"Handle and store packaging with the same care as a
food or ingredient."* Confirmed real, correctly cited already.

What the guidance does **not** say verbatim: "keep bottles boxed and sealed until ready
for bottling" or "cork immediately after filling." Those are sound, specific
applications of the general packaging-handling principle for a bottling line — worth
keeping in the schema — but should be presented to Codex/the founder as
business-specific practice, not quoted MPI text, so nobody later cites them to a
verifier as if from the card.

**Current gap.** No log template exists for `food-labelling-advertising`.

**Proposed schema (unchanged from first draft):**

```python
"food-labelling-advertising": _log_template(
    "packaging_handling",
    "Packaging handling verification",
    "Spot-check that empty packaging and filled containers are handled to prevent "
    "contamination between unpacking and sealing. (Site-specific practice — not "
    "verbatim NP3 wording, which only requires packaging be handled 'with the same "
    "care as a food or ingredient'.)",
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

**Priority:** lower than 1–3 — process discipline worth recording, not a missing
MPI-named control.

---

## 5. "Reducing water content" and "making food acidic" are full standalone cards with mandatory numeric records — bigger gap than first thought

**Verified against p55–56 ("Using water activity to control bugs") and p57–58
("Pickling, fermenting, or acidifying food to keep them safe").** My first draft treated
these as generic example content under `biological-hazards`. That undersells it: these
are **two separate MPI cards**, each with its own mandatory numeric record requirement
(per the p9 requirements table, both are "Required"), and **neither has a distinct
`control_id` in `catalogue.py`** — the current catalogue folds both into the generic
`biological-hazards`/general hazard buckets.

- **Water activity** (relevant to dried botanicals): lowering water activity below
  **0.85** prevents bug growth. Must be verified per batch by one of: a calibrated water
  activity meter, an accredited-lab sample, or a proven consistent method (only
  acceptable if the target water activity is below 0.80). **Required records**: the
  method used to dry/concentrate, and the water-activity test result — per batch.
- **Acidification/fermentation** (the mind map correctly says "not applicable" for
  Whistlebird): pH < 3.6 kills most harmful bugs; pH 3.6–4.6 still needs added
  pasteurising/cooking; measured by a calibrated pH meter or accredited lab, proven to
  ±0.1 of target. **Required records**: the method used, and pH test results.

**Proposed change — bigger than the original "richer example text" suggestion.** Given
both are separately named, separately record-required cards, the more faithful design
is two new control_ids in `catalogue.py`'s `np3-food-control` controls tuple:

```python
("water-activity-control", "Prove any dried/concentrated food's water activity is below 0.85, per batch."),
("acidification-fermentation-control", "Prove pH control for any pickled, fermented or acidified food, or confirm not applicable."),
```

...with playbooks citing p55 and p57 respectively, and log templates capturing
`method` + `test_result` (mirroring `calibration`'s shape) for the applicable one — plus
a one-line attestation path for `acidification-fermentation-control` so "not applicable
to this product line" is an explicit, recorded answer rather than the topic silently not
appearing anywhere.

**Priority:** medium — upgraded from the first draft. This isn't cosmetic; it's two
MPI-named, record-required controls with no distinct representation in the catalogue at
all, only implied inside a generic hazard bucket.

---

## Sequencing note

1, 2 and 3 are the highest-value, most concrete gaps — all three have hard, verbatim
"you must keep records" language in the actual guidance with no register in the app
today (water, maintenance) or materially wrong process detail that shouldn't ship
unverified (recall). 5 is a real structural gap, upgraded on fact-check. 4 is polish. The
pagination fact-check table is a separate, orthogonal finding worth a quick pass on its
own. None of this should be started until Codex's current pass on
`np3_audit.py`/`catalogue.py` lands, to avoid working the same file at the same time.
