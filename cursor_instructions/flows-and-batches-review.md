# Flows2 hardening review (`flows2.html` + related)

**Status:** Follow-up items from the prior review are **implemented** in code (see below). Keep this file as the **PR / regression checklist** for any new inventory or execution UI.

| | |
|---|---|
| **Verdict** | **Inventory** details, **execution cards** (`createExecutionCard`), and **process step** cards (`createStepCard` + `updateStepMeta`) use **DOM + `textContent` / `createElementNS`** for user-facing / API-fed text. Serialization uses **depth- and length-capped** `JSON.stringify` where applicable; inventory loads use **`Flows2InvLoad`**. |
| **Residual risk** | **`escapeHtml`** is string-only (no DOM). Step drag sets **`text/plain`** (`flows2-step:<id>`). Backend list clamp on `extra_data` remains in `backend.py`. |

---

## Implemented mitigations

| Issue | Mitigation |
|-------|------------|
| **Details panel `innerHTML`** | **`buildFlows2InventoryDetailsFragment(item)`** — all sections (`Production`, `System findings`, `Custom prompts`, `Inputs`, `Output`, `Upstream`, `Notes`, `Audit`) append **nodes only**; **`content.appendChild(fragment)`** on the card. |
| **Step list summary `innerHTML`** | **`createStepCard`** builds header + body with **`flows2AppendStepSummaryItem`**, drag/chevron SVG helpers, and **`textContent`** on **`<pre>`** for docs/config JSON. **`updateStepMeta`** updates counts without **`innerHTML`**. |
| **JSON display sink** | **`flows2ClampObjectForDisplay`** (max depth + array cap) before stringify; then **length cap**; values land in **`textContent`** via DOM builders. |
| **Mixed paradigms (inventory)** | Inventory expanded body is **DOM-only**; helpers named **`flows2AppendInventory…`** / **`flows2InvAppend…`**. |
| **Async races** | **`Flows2InvLoad.begin()`** returns `{ signal, gen }`; stale responses dropped. |
| **SVG `innerHTML`** | Inventory: **`flows2CreateChevronSvgEl16()`**. Executions: **`flows2SvgChevron14` / `16`**, play triangles. Steps: **`flows2SvgStepDragGrip18`**, **`flows2SvgChevronDown18`**, **`flows2SvgHelpCircle14`**, **`flows2SvgCloseX14`**. Toasts: **`flows2SvgNotificationSuccess24`**, **`flows2SvgNotificationError24`**. |
| **Lists / modals / dropdowns** | **`renderSteps`** / **`renderExecutions`** / **`flows2RenderInventoryList`** empty states use **`replaceChildren`** + **`textContent`**. **`createSearchableDropdown`** builds input/list in DOM; rows use **`textContent`**. **`showStaticInputWarningModal`** DOM-only. **`addExecutionPrompt`** / **`addOutput`** append **`createElement`** trees. **Dispose (wastage)** modal cards built with DOM. **`updateUnitDropdown`** uses **`replaceChildren`**. |
| **JSON CPU** | Clamp reduces stringify cost on pathological depth/breadth before string building. |
| **Multiple escapers** | Documented in **`escapeHtml`** block comment (encoding contract). |
| **Fragmented load state** | **`Flows2InvLoad`** encapsulates controller + monotonic generation. |

---

## PR checklist (flows2 inventory / details)

- [ ] No new **`innerHTML`** under inventory details, **execution** sections, or **`flows2-step`** summary body — extend **`buildFlows2InventoryDetailsFragment`** / **`flows2Build…Execution…`** / **`flows2AppendStepSummaryItem`** or add DOM helpers with **`textContent`**.
- [ ] Any new API-fed text: **DOM text nodes** or **`flows2InvAppendExecPickerKv`** / **`flows2InvAppendKvRowsFromObject`**.
- [ ] Objects shown as JSON: **`flows2SerializeForDisplay`** only (already clamped).

---

## Optional future work

- Add **`truncated`** flags on **`GET /api/core/inventory`** if product wants explicit server-side visibility into clipping.

---

## Bottom line

**Inventory**, **executions**, **step summary**, **step editor rows** (inputs/outputs/prompts), **searchable raw-material dropdown**, **toast icons**, **static-input warning modal**, **inventory list empty states**, and **dispose/wastage cards** are DOM-first for dynamic content. **`escapeHtml`** uses character escapes only (no **`innerHTML`**). Step reorder drag uses **`text/plain`** payload only.
