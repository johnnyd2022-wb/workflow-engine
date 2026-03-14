# Refactor Process Creation Flow: Modal → SPA Page

## Goal

Refactor the existing process / process-step creation flow from a modal-based
wizard to a full SPA-style page **without changing business logic**.

This is a **presentation refactor only**.

The existing modal logic is tidy and must be preserved.

---

## Non-Goals (Explicit)

- ❌ Do NOT change backend APIs
- ❌ Do NOT change DAG semantics
- ❌ Do NOT rewrite validation rules
- ❌ Do NOT duplicate logic
- ❌ Do NOT alter data contracts or payload shapes

---

## Core Principle

> Extract shared flow logic so it can be used by:
> - the existing modal
> - the new SPA page

The SPA page is just a new container.

---

## Step 1: Identify and Extract Flow Logic

Locate the existing modal code responsible for:

- Step ordering
- Next / back navigation
- Validation per step
- Accumulated process state (inputs, outputs, execution config, batch info)

Extract this into a **flow controller module**, e.g.:

- `useProcessFlowState.js` (or equivalent)
- `ProcessFlowController`

This module must expose:
- currentStep
- goNext()
- goBack()
- canProceed()
- flowState (inputs, outputs, execution prompts, batch config)
- setters for each section

⚠️ No UI code should live here.

---

## Step 2: Extract Step Components

Each step must be its own reusable component:

- Process Inputs Step
- Process Outputs Step
- Execution Prompts Step
- Batch / Execution Metadata Step

These components:
- Receive state via props
- Emit updates via callbacks
- Perform only local validation/UI concerns

They must NOT:
- manage navigation
- manage global flow state
- assume modal-specific behavior

---

## Step 3: Preserve Modal by Reusing the Extracted Logic

Refactor the existing modal to:

- Import the extracted flow controller
- Render step components conditionally based on `currentStep`
- Keep next/back buttons wired to shared navigation logic

The modal should behave **identically** after refactor.

This confirms no logic regressions.

---

## Step 4: Create SPA Page Container

Create a new page (route-based SPA view) that:

- Uses the same flow controller
- Uses the same step components
- Renders steps inline instead of in a modal
- Uses persistent navigation (top or side step indicator)

Differences allowed:
- Layout
- Spacing
- Visual hierarchy

Differences NOT allowed:
- Step order
- Validation rules
- State transitions
- API calls

---

## Step 5: Navigation & UX Enhancements (Optional but Allowed)

Allowed SPA-only improvements:
- Step progress indicator
- Breadcrumbs
- Ability to jump to previous completed steps (respecting validation)

Not allowed:
- Skipping required steps
- Silent auto-advancement

---

## Step 6: Verification Checklist

Before marking complete:

- Modal flow behaves exactly as before
- SPA flow produces identical payloads
- Back/forward navigation preserves state
- Validation blocks progression consistently
- No duplicated logic exists between modal and SPA

---

## Acceptance Criteria

- One shared flow controller
- One set of step components
- Two containers (modal + SPA)
- Zero business logic divergence
