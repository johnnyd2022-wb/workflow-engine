# Flows2 hardening & refactor review (`flows2.html` + `flows2-*.js`)

This doc tracks **security / perf boundaries** after splitting the flows page into modules. Use it as a **PR and regression checklist**.

---

## 1. Frontend module layout (your refactor)

Scripts are loaded from `processes/flows2.html` (`{% block scripts %}`) in this **fixed order** — do not reorder without checking dependencies:

| Order | File | Role |
|------:|------|------|
| (inline) | `flows2.html` | **`processId`** from URL/Jinja; **`window.ExecutionModalConfig`** — must run **before** `execution-ui-utils.js` |
| — | `execution-ui-utils.js` | Shared execution helpers |
| — | `shared/execution_modal_stack_scripts.html` | Modal stack |
| 1 | **`flows2-utils.js`** | Caps (`FLOWS2_MAX_*`), **`Flows2InvLoad`**, **`flows2Inventory`**, **`escapeHtml`** / **`flows2EscapeAttr`**, **`flows2SafeKeys`**, SVG helpers, serialization helpers |
| 2 | **`flows2-steps.js`** | Step list **`renderSteps`**, **`createStepCard`**, I/O row builders, drag reorder, **`saveStep`** / **`deleteStep`**, etc. |
| 3 | **`flows2-executions.js`** | **`loadExecutions`**, **`createExecutionCard`**, execution DOM builders, batches panel collapse state |
| 4 | **`flows2-inventory.js`** | Inventory cards, **`buildFlows2InventoryDetailsFragment(item)`** (DOM fragment — **no `innerHTML`** for details body), **`loadInventory`**, **`flows2RerenderInventory`** |
| 5 | **`flows2-modals.js`** | **`openModal` / `closeModal`**, notifications, static-input warning, searchable dropdown, add I/O / prompts, record-wastage wiring as applicable |
| 6 | **`flows2-init.js`** | Tab/panel activation, inventory sub-tabs, manage menu, **`loadProcessData`**, page bootstrap |

**Global coupling (intentional today):** files share page globals such as **`processId`**, **`currentProcess`**, **`currentUser`**, **`flows2Inventory`**, **`CoreAPI`**, **`showNotification`**. Refactors that rename or move init order can break at runtime. A future **`window.Flows2 = { ... }`** (or ES modules) would namespace this; not required for correctness if **load order** stays documented and tests/manual smoke pass.

---

## 2. Backend: bounded `extra_data` on list inventory

**Function:** `_bound_inventory_extra_data_for_list_response` in `app/core/backend/backend.py`.

**What’s good**

- Shallow copy (`out = dict(extra_data)`) avoids mutating ORM JSON in place.
- List **length** caps on **`previous_steps_data`**, **`inventory_audit_history`**, **`reconciliation_history`** reduce huge list responses.
- Constants (aligned with UI caps comment in backend): **`LIST_INVENTORY_MAX_PREVIOUS_STEPS = 80`**, **`LIST_INVENTORY_MAX_AUDIT_HISTORY = 120`**, **`LIST_INVENTORY_MAX_RECONCILIATION_HISTORY = 60`**.

**Remaining gap (review is fair)**

- Bounding is **per-field list length**, not **per-element size**. A single `previous_steps_data[i]` could still carry large nested blobs (e.g. huge string fields inside one object).
- **Optional follow-up:** per-item string trim, max depth, or max serialized size for elements inside those lists.

---

## 3. Frontend: JSON display / CPU

**In `flows2-utils.js`:** `FLOWS2_MAX_JSON_DISPLAY_CHARS`, **`flows2ClampObjectForDisplay`** (depth + array caps), then stringify + length cap where used.

**What’s good**

- Post-stringify character cap matches real wire/DOM cost.
- Clamping before stringify reduces pathological depth/breadth.

**Subtle improvement (optional)**

- Very large **single** objects can still cost CPU/memory **during** `JSON.stringify` before truncation. A replacer that limits depth or node count (or streaming-safe stringify) would harden further.

---

## 4. DOM rendering & XSS

**What changed with the refactor**

- Dynamic surfaces use **`createElement`**, **`textContent`**, and **`createElementNS`** for SVG — not template literals assigned to **`innerHTML`** for API-fed text.
- **Inventory expanded details** are built by **`buildFlows2InventoryDetailsFragment`** in **`flows2-inventory.js`** (append **`DocumentFragment`** — **not** `content.innerHTML = buildFlows2InventoryDetailsSection(...)`).

**Critical choke point**

- Any **new** inventory / execution / step UI must keep **`textContent`** for untrusted strings. If a legacy **`innerHTML`** path is reintroduced, every interpolated field must go through **`escapeHtml`** / **`flows2EscapeAttr`** / **`flows2ValueForHtml`** as appropriate.

**Escaping matrix (keep consistent)**

| Context | Method |
|--------|--------|
| Text node | **`element.textContent = …`** |
| HTML string (last resort) | **`escapeHtml`** once at interpolation |
| Attribute value | **`flows2EscapeAttr`** |

---

## 5. Async race handling

**`Flows2InvLoad`** in **`flows2-utils.js`**: **`AbortController`** + monotonic **`generation`** so stale **`loadInventory`** responses do not overwrite newer results. Treat this pattern as **required** for any new parallel fetch that can race with tab/filter/process changes.

---

## 6. IDs and selectors

**`dataset.inventoryId`**, **`data-step-id`**, element **`id`**s derived from server IDs: today these are expected to be server-issued UUIDs. If any path ever accepts client-controlled IDs, **normalize** (e.g. allow only safe charset) before **`querySelector`** / **`getElementById`**. **`flows2QueryById`** already helps when IDs contain CSS-special characters.

---

## 7. Step drag / clipboard

Reorder uses **`dataTransfer.setData('text/plain', 'flows2-step:' + stepId)`** (not card HTML) so the drag payload does not snapshot DOM HTML.

---

## 8. Summary

| Area | Assessment |
|------|------------|
| **Refactor structure** | Clear split (utils → steps → executions → inventory → modals → init); **respect script order**. |
| **XSS** | Greatly reduced vs string templates; inventory details are **fragment-based**. |
| **DoS** | Layered: backend list caps, frontend JSON caps, DOM rendering. |
| **Async** | **`Flows2InvLoad`** + generation pattern is production-grade. |
| **Remaining risks** | Shallow backend bounding inside list elements; optional deeper JSON stringify limits; implicit globals across files until namespaced. |

---

## PR checklist (flows2 modules)

- [ ] New scripts: insert in **`flows2.html`** in dependency order; document any new global.
- [ ] No **`innerHTML`** / **`insertAdjacentHTML`** for API or user text without **`escapeHtml`** / **`textContent`** split.
- [ ] New inventory list fields: consider extending **`_bound_inventory_extra_data_for_list_response`**.
- [ ] New fetches that can race: **`Flows2InvLoad.begin()`**-style or equivalent (**AbortSignal** + stale guard).

---

## Note

Older external reviews may still mention a **single** `buildFlows2InventoryDetailsSection` + **`innerHTML`**. The current codebase uses **`buildFlows2InventoryDetailsFragment`** in **`flows2-inventory.js`** with **DOM-only** details. Update any stale docs or tickets to match.
