# Flows2 — security & performance review

**Scope:** `app/core/frontend/processes/flows2.html` — inventory, batches/executions, and API-driven rendering. Treat this as a **high-risk** screen: string templates, `innerHTML`, and data that can include long strings, nested objects, and large arrays.

| | |
|---|---|
| **Bottom line** | Risk is reduced further: inventory **card chrome** (title, badge, quantity rows, banner) is built with **DOM APIs + `textContent`**; API blobs go through **`flows2SerializeForDisplay`** with a **max character bound**; **`flows2ValueForHtml`** covers execution metadata objects; inventory loads are **abortable** and generation-guarded; **GET `/api/core/inventory`** clamps large nested lists in `extra_data`. Remaining risk is mainly **`innerHTML` inside inventory details + execution cards** (must keep `escapeHtml` on every interpolated string). |
| **Already shipped** | All of the prior items **plus**: DOM inventory header/shell; `FLOWS2_MAX_JSON_DISPLAY_CHARS` + truncation; `flows2ValueForHtml`; escaped IO qty/unit lines; metadata values use `flows2ValueForHtml`; `AbortController` + load generation on `loadInventory`; backend `_bound_inventory_extra_data_for_list_response`. |
| **Still open** | Large **`innerHTML`** blocks (`buildFlows2InventoryDetailsSection`, `createExecutionCard` body); alternate API clients bypass UI caps unless endpoints enforce limits everywhere; multi-process SPA without full reload still a theoretical singleton-cache edge case. |

**How to use this doc:** Read the summary row above first, scan **Critical issues** for “why,” jump to **Fixes (what to do next)** for backlog items and the PR checklist.

---

Below is the detailed review (strict pass): what materially changed, what still moves risk, and where we are honest about limits.

I’m going to be strict: structurally this is much improved, but a few high-confidence attack-surface and architectural issues remain.

🔴 CRITICAL ISSUES
1. ❗ Still DOM XSS surface via innerHTML (reduced but not eliminated)
Where it remains

**Update:** `createInventoryItemCardFlows` builds the card shell with **`createElement` / `textContent`**; only the **expanded details** pane sets `innerHTML` from `buildFlows2InventoryDetailsSection(...)`.

You still use:

card.innerHTML = ` / template strings

in:

buildFlows2InventoryDetailsSection (and helpers it calls)
execution rendering blocks (`createExecutionCard`)
IO panes
metadata sections
Why this still matters

You did improve escaping discipline, but the fundamental risk remains:

❌ Problem class

You are still mixing:

string templates
nested object serialization
conditional HTML injection

Example risky chain:

flows2SerializeForDisplay(sp[k])

→ inserted into:

<span>${escapeHtml(...)}</span>

BUT:

some branches bypass escapeHtml entirely (notably JSON blocks and metadata rendering)
some values are double-rendered objects → stringified twice in inconsistent ways
innerHTML is still the execution boundary (single failure = full DOM XSS)
Key insight

Even with good escaping, template-based DOM construction = fragile security boundary

✅ Required fix (structural, not cosmetic)

Move to one of:

document.createElement composition (preferred)
or a strict HTML builder that forces escaping at leaf nodes only

If you keep innerHTML, you are relying on perfect discipline forever — which is not realistic in a growing system.

2. ❗ Attribute context encoding (improved; stay disciplined)
Previously a minimal `flows2EscapeAttr` only handled `&` / `"` / `<`. **Code now encodes** `& " ' < >` for double-quoted `data-*` attributes. **Remaining risk:** new code must use this helper (or the same rules) for every dynamic attribute; backticks and other edge cases are not a normal HTML attribute concern but avoid passing attribute values into `eval` / `setAttribute` with event-handler names.

**Rule:** one canonical function for attribute text; no ad-hoc `.replace` chains in templates.

3. ❗ Click handler logic still depends on DOM structure trust

You improved:

execHdr.addEventListener('click', ...)

Good.

BUT:

Risk still exists in:
delegation patterns relying on .closest()
unscoped event propagation stops:
e.stopPropagation()
Problem class

This becomes fragile when:

UI nesting increases
new interactive elements are added
future devs forget propagation rules
Impact

Not direct XSS, but:

logic bypass
accidental event hijacking
UI state desync (security-adjacent reliability issue)
4. ❗ Prototype pollution protections are incomplete

You added:

flows2SafeKeys()

Good improvement.

BUT:

Gap

Still multiple direct unsafe access patterns:

executionData[key]
step.execution_prompts
entry[k]

Even with safe keys, you are still trusting:

object shape integrity
backend guarantees
Missing protection layer

You are not validating:

value types
depth limits
nested object structure
Impact

If backend is compromised or malformed:

UI poisoning (not just display)
potential DOM injection via string coercion paths
🟠 HIGH PRIORITY ISSUES
5. ⚠️ Performance risk still present (large payload rendering)

You improved with caps:

FLOWS2_MAX_AUDIT_HISTORY = 80
FLOWS2_MAX_IO_ROWS_PER_STEP = 200
Good

BUT:

Problem

These caps are still:

relatively high for synchronous DOM rendering
applied after mapping in some cases (wasted CPU work)

Example:

.map(...)
.slice(...)

→ still builds full array before slicing

Impact
unnecessary CPU load
layout blocking on large datasets
mobile performance degradation
Fix

Apply slicing before mapping consistently.

6. ⚠️ Mixed trust model (backend + frontend validation split)

You are doing:

frontend filtering (UUID checks, empty checks)
frontend truncation
frontend type inference
Problem

Frontend is now acting as:

validator
sanitizer
renderer

This is a classic security debt amplifier

Impact
inconsistent enforcement
bypass risk via alternate clients (API misuse)
logic divergence over time
7. ⚠️ flows2Inventory state model is better but still global

Good improvement:

const flows2Inventory = { ... }

BUT:

Issue

Still effectively singleton global state for:

filter
cache
grouping
Risk
multi-process UI contamination
stale renders if async loads overlap
race conditions during rapid filter switching
🟡 MEDIUM ISSUES
8. UI logic still tightly coupled to data transformation

Functions like:

flows2RenderInventoryOutputSection
flows2RenderInventoryUpstreamSection

mix:

business rules
formatting
rendering
Impact
increases blast radius of bugs
makes security auditing harder
makes safe refactors risky
9. Repeated DOM queries still present

Example:

document.querySelector(...)
flows2QueryById(...)

inside event handlers and toggles.

Impact
avoidable layout thrashing in large DOM trees
10. UUID “sanitization” still misleading

Comment:

// UX only: hide values that look like raw UUIDs
Problem

This is not security, but:

devs may misinterpret it as validation
could lead to incorrect trust assumptions later
🟢 POSITIVE IMPROVEMENTS (significant)

These are meaningful upgrades:

✅ 1. Introduced safe key filtering
flows2SafeKeys()

This is a real improvement against prototype pollution

✅ 2. Added explicit caps for all major arrays

Good coverage:

audit history
IO rows
upstream steps
prompts

This materially reduces DoS risk.

✅ 3. Removed window-scoped inventory state

Moving toward:

const flows2Inventory = {}

This is a good architectural direction

✅ 4. Event listener refactor (big improvement)

You replaced inline handlers with:

addEventListener

This reduces:

injection surface
CSP fragility
debugging complexity
📊 FINAL RISK SUMMARY
🔴 Critical (still open)
DOM XSS risk remains due to innerHTML templating model
Attribute escaping: core helper is in place; risk is **new** unescaped dynamic attributes
Data-to-DOM trust boundary still fragile
🟠 High
Performance risk from partial slicing patterns
Prototype pollution not fully contained (only partially mitigated)
Global state still impacts multi-instance safety
🟡 Medium
Tight coupling of rendering + business logic
Repeated DOM querying inefficiencies
UX/security confusion in UUID filtering logic

---

## Fixes (what to do next)

Concrete remediation mapped to the issues above. **P0** can ship quickly; **P1–P3** are structural or backend.

### P0 — Frontend quick wins

| Issue | Fix |
|-------|-----|
| **2 — Incomplete attribute escaping** | Use a single `flows2EscapeAttr` (or shared util) for every dynamic `data-*` and other quoted attribute. Encode at minimum `& " ' < >` (aligned with `flows2.html` `flows2EscapeAttr`). Do not hand-roll partial replacements in new code. |
| **5 — Slice before map** | For capped lists, call `.slice(0, N)` **before** `.map` / heavy transforms. Audit any new execution or inventory template for `.map(...).slice` order. |
| **10 — UUID comment confusion** | In code, keep the comment `UX only — not identity validation` next to UUID masking; optionally link reviewers to this doc. |

### P1 — Structural (flows2.html)

| Issue | Fix |
|-------|-----|
| **1 — innerHTML XSS boundary** | Incrementally replace high-risk blocks: build card shells with `innerHTML` only for static structure; set user/API text via `textContent` or `element.appendChild(document.createTextNode(...))`. Priority: inventory detail sections and execution step metadata rows. |
| **1 — Serialization paths** | Treat `flows2SerializeForDisplay` output as **text**: always pass through `escapeHtml` before template interpolation, or write JSON into a `<pre>` via `textContent`. |
| **3 — Delegation / propagation** | Document in a short comment above execution header listener: “inner clicks on `.flows2-exec-next-step-wrap` must not toggle expand”; add new interactive children under that subtree or use `pointer-events` + explicit button roles. |
| **4 — Key access after safeKeys** | After `flows2SafeKeys`, validate **value** shape where it affects HTML (e.g. reject non-string/non-number for labels); cap nesting depth for JSON shown in UI (optional small depth guard in `flows2SerializeForDisplay` display path). |

### P2 — Backend & trust model

| Issue | Fix |
|-------|-----|
| **6 — Mixed trust model** | Enforce limits and schemas on APIs that feed flows2 (max audit entries, reconciliation rows, prompt map size). Return explicit `truncated` flags where the server clips. |
| **7 — Inventory singleton / races** | **Partially done:** `loadInventory` uses `AbortController` + load generation; `flows2SetInventoryFromApi(..., processId)` records `loadedProcessId`. **Optional:** namespace cache by `processId` if one HTML page ever hosts multiple process contexts without reload. |

### P3 — Performance & maintainability

| Issue | Fix |
|-------|-----|
| **8 — Mixed concerns** | Extract pure formatters (dates, quantities, labels) into functions with **no** HTML; keep HTML builders thin wrappers that only call `escapeHtml` at boundaries. |
| **9 — Repeated queries** | Cache `details` / `arrow` elements when expanding inventory rows if profiling shows hot toggles; low priority until measured. |

### Verification checklist (PRs touching flows2)

- [ ] No new inline `onclick="...${dynamicId}..."`
- [ ] No `${variable}` in templates without `escapeHtml` / `flows2EscapeAttr` / `textContent`
- [ ] New arrays from API: cap + slice-before-map
- [ ] Object iteration from API: `flows2SafeKeys` or explicit schema

---

### Already implemented (reference)

`flows2SafeKeys`; `FLOWS2_MAX_*` + `FLOWS2_MAX_JSON_DISPLAY_CHARS` (bounded `flows2SerializeForDisplay`); `flows2ValueForHtml` for object-shaped metadata; `flows2Inventory` + `itemsByType` + `loadedProcessId`; `loadInventory` **abort** + **stale-response** guard; inventory **card shell** via DOM + `textContent` (details pane still template HTML with `escapeHtml`); execution card **propagation contract** comment; **IO** quantity/unit and **metadata** value escaping; `flows2EscapeAttr`; `CSS.escape` / `flows2QueryById`; listener-based handlers (no injected `onclick` for dynamic IDs). **Backend:** `_bound_inventory_extra_data_for_list_response` on `GET /api/core/inventory`.