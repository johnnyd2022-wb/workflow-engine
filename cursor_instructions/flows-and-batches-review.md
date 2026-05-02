You’ve essentially refactored this in the right direction, but there are a few subtle correctness + architecture issues hiding in here that will matter in production.

I’ll break this down into security/robustness, data consistency, and frontend architecture/maintainability.

1. safeInventoryManualReturnTo — good improvement, but still has a blind spot
What you fixed well
Moving from string prefix checks → new URL() parsing is a real security upgrade
Properly enforcing:
same origin
/core/ path restriction
Handling query string preservation correctly
Remaining issue (important)

You are still allowing path traversal style abuse via base resolution behavior:

new URL(s, loc.origin);

If s = "/../something" or encoded variants, URL normalization will resolve it before your regex check.

Fix

You should normalize after URL resolution:

var path = url.pathname.replace(/\/+/g, '/');

And then validate strictly:

if (!path.startsWith('/core/')) return '';
if (path.includes('/../')) return '';

Even though browsers usually collapse ../, this closes edge cases and keeps intent explicit.

2. Duplicate logic removal (good refactor, but partial)

You introduced:

formatExecutionInventoryTriggerLabel(inv)

and correctly removed duplication in:

triggerLabel.textContent = formatExecutionInventoryTriggerLabel(inv);
Issue

You only partially removed duplication.

There are still multiple implicit formatting contracts in the codebase:

Example elsewhere:

return productName + ' - ' + quantity + ' ' + unit;

This is now inconsistent with:

process_name - name - qty unit
Recommendation

You now have 3 competing label formats:

picker card
trigger label
selected card header

These should be unified into:

InventoryDisplay.format(inv, mode)

Where mode is:

compact
detailed
trigger

Right now, you’ve only standardized one surface.

3. Picker search performance — unnecessary WeakMap complexity

You added:

var invSearchHayCache = new WeakMap();
Problem

WeakMap provides no benefit here because:

inv objects are reused but not guaranteed stable identity across renders
you are iterating fresh arrays frequently
GC pressure is not the real bottleneck here
Better option

Use a simple derived field once:

inv._searchHay ??= buildSearchHay(inv);

or precompute:

allInventory = allInventory.map(inv => ({
  ...inv,
  _searchHay: ...
}));

Then:

return inv._searchHay.includes(q);

This is significantly cheaper and more predictable.

4. Redundant DOM churn in picker rendering (biggest real issue)

You rebuild full card DOM every render:

pickerFrag.appendChild(buildExecPickerCard(inv));

That function:

creates many nodes
assigns attributes
injects innerHTML twice (chips, metaBlock)
Problem

This will become a performance bottleneck at scale (100–1000 items).

Improvement direction

Either:

switch to incremental DOM updates, OR
memoize cards per inv.id

Example:

if (cardCache.has(inv.id)) return cardCache.get(inv.id);

Even basic caching will reduce churn significantly.

5. Inconsistent type normalization boundaries

You now correctly centralized:

InventoryTypeUtils.normalizeInventoryTabType

But:

Problem

You still duplicate logic in multiple places:

picker filtering
expected tab hint
legacy inline comparisons

Example:

if (t === 'intermediate' || t === 'work_in_progress' || t === 'wip')

and later:

if (selected === 'all') return true;
Issue

You now have:

canonical normalization module
but still scattered rule knowledge
Recommendation

Make InventoryTypeUtils the only source of truth:

InventoryTypeUtils.isType(inv, selectedType)
InventoryTypeUtils.matchesSearch(inv, q)

Right now, logic duplication will drift again within 2–3 features.

6. UI structure: picker panel is doing too much

This block is becoming a mini-application inside a modal:

segmented control
search
cards
selection state
add missing flow
add another input flow
warnings
Risk

This will eventually:

become untestable
require fragile event wiring
break across refactors
Architectural suggestion

Split into:

InventoryPickerController
InventoryPickerView
InventoryRowRenderer

Even a lightweight separation (not full framework) would help.

7. Minor correctness issues
A. Typo bug
"Finals products"

Should be:

"Final products"

This will show in UI.

B. Potential undefined dataset coercions
if (input.producing_process_name)

but elsewhere:

String(input.producing_process_name)

You’re inconsistent about normalization safety.

C. Hidden input initialization
hiddenInput.dataset.quantity = "";
hiddenInput.dataset.unit = "";

This may mask bugs later because:

empty string ≠ null state
downstream logic likely assumes presence means valid selection

Better:

delete hiddenInput.dataset.quantity;
delete hiddenInput.dataset.unit;
Bottom line

You’ve improved:

security posture (URL handling)
UI readability (label function extraction)
type normalization (partial centralization)

But the system is now at a stage where the main risk is no longer correctness—it’s accumulating UI + logic duplication across the execution modal ecosystem.