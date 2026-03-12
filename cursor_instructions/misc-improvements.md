1. Modal Lifecycle Refactor (Good)

You introduced:

showModal()
hideModal()
clearModalSections()

This is a good separation of concerns.

Before:

modal display logic
modal clearing
modal rendering

were interwoven.

Now:

modal lifecycle
    ↓
clear UI
    ↓
render sections

This reduces bugs where stale UI elements persist between executions.

One small improvement:

function hideModal() {
  modal.style.display = 'none';
  document.body.style.overflow = 'auto';

  if (modal._inputStateByKey) modal._inputStateByKey.clear();
}

Otherwise stale state can persist between executions if the modal is reused.

2. Moving Input State Out of the DOM (Major Improvement)

This is the most important change you made:

modal._inputStateByKey = new Map()

Each row now has:

row.dataset.stateKey

and the state lives here:

{
  input_name,
  inventory_item_id,
  quantity,
  unit,
  expired_reason
}
Why this is a big upgrade

Previously the source of truth was:

DOM inputs
hidden dataset attributes
querySelector lookups

Problems with that model:

fragile
slow
hard to validate
hard to diff changes

Now you have:

State → UI

instead of

UI → State

This is essentially a mini React-style state model, implemented manually.

Excellent direction.

3. Deterministic Submission Logic

This block is very good:

var stateIter = (modal._inputStateByKey && modal._inputStateByKey.size > 0)

Meaning:

prefer state
fallback to DOM

This protects you from:

partial migrations
future UI refactors

Good defensive coding.

4. Input Row State Initialization

Inside createInputRow:

if (!modal._inputStateByKey.has(stateKey)) {

You correctly prevent overwriting existing state.

This matters for cases like:

inventory selected
user edits quantity
dropdown re-renders
state preserved

Without this guard you'd lose the state.

Good.

5. Quantity Input Sync

You added:

qtyInput.addEventListener('input', function() {
  var st = modal._inputStateByKey.get(stateKey);
  var q = parseFloat(qtyInput.value);
  st.quantity = isNaN(q) ? 0 : q;
});

This is correct.

But one small improvement:

if (!Number.isFinite(q)) q = 0;

parseFloat() can return Infinity in weird cases.

Not critical but safer.

6. State Updates on Inventory Selection (Good)

When selecting inventory:

st.inventory_item_id = String(inv.id)
st.unit = inv.unit
st.expired_reason = reason

This keeps state consistent.

Good.

But one improvement:

st.unit = inv.unit || st.unit

If inventory unit is empty you currently overwrite the step unit.

7. Remove Row Cleanup (Correct)

You correctly added:

modal._inputStateByKey.delete(stateKey)

Without this you'd accumulate orphan state objects.

Good catch.

8. Ready Date Validation Refactor (Nice)

This block is much cleaner:

stateIter.forEach(function(st) {

Before:

scan DOM rows
query selectors
dataset parsing

Now:

iterate state objects

Much faster and less fragile.

9. Inventory Indexing for Submission (Good)

You introduced:

var invById = new Map()

This avoids repeated scans when checking:

system_findings
ready date checks

Good consistency with earlier Map optimization.

10. A Subtle Bug: State Not Cleared When Modal Opens

You initialize:

if (!modal._inputStateByKey) modal._inputStateByKey = new Map();

But if the modal opens twice:

old state remains

This can cause phantom inputs during submission.

Better:

modal._inputStateByKey = new Map();

when starting the modal.

You can do this right after:

clearModalSections()
11. Minor Edge Case in Submission

Inside:

quantity: st.quantity != null ? st.quantity : 0

If user clears the input field:

'' → NaN → stored as 0

This might allow silent zero consumption.

Safer option:

if (!Number.isFinite(st.quantity) || st.quantity <= 0) return;

so only valid quantities submit.

12. Performance Improvements from This Change

You likely improved:

Before

Submission logic:

querySelectorAll
querySelector
dataset reads
parseFloat

For every row.

Complexity:

O(rows × DOM queries)
Now

Submission:

Map iteration
object reads

Complexity:

O(rows)

DOM queries are orders of magnitude slower than JS object access.

13. Code Quality Score
Area	Rating
State management	9/10
UI determinism	9/10
Performance	9/10
Robustness	8.5/10

This modal is now much closer to SPA-quality UI architecture.

14. One Architectural Suggestion (Big Future Win)

Right now state looks like:

Map(stateKey → inputState)

You could make it even simpler:

modal._inputs = [
  {
    input_name,
    inventory_item_id,
    quantity,
    unit
  }
]

And rows just store:

row.dataset.index

Benefits:

simpler iteration
ordered inputs
easier validation
simpler submission payload

Maps are great for lookup but arrays are better for ordered form state.

Not required — just a future improvement.