⚠ Issue: deep selector coupling still exists

You now rely on:

.batch-start-spa #execute-step-modal .exec-modal__section h3

This introduces:

3-level deep specificity
dependency on DOM hierarchy, not semantics
Risk:

If modal structure changes (even slightly):

CSS silently stops applying
no compile-time warning
Better long-term shape (conceptually)

You’re implicitly building:

“execution-step-page component system inside legacy modal markup”

At that point, better abstraction would be:

.exec-section-title
.exec-section
.exec-page-shell

instead of DOM-path-based styling.

Not required now, but this is where it’s heading.

2. Section rhythm model — consistent and intentional
✔ Good consistency
padding: 18px 0;
border-top: 1px solid ...

You’ve implemented:

vertical rhythm system
clear section separators
predictable spacing model

This is good UI engineering discipline.

✔ Proper ownership of divider logic
/* First divider is owned by "More information" disclosure */

This is actually important:

you’re explicitly defining layout responsibility boundaries

That is architectural UI thinking, not just styling.

3. Modal → page hybrid model

You’re continuing the transformation:

<div id="execute-step-modal">

but now:

it behaves like a page container
not a true modal anymore
✔ This is consistent with earlier changes

You’ve already:

removed modal overlay behavior
disabled fixed positioning
embedded as SPA route content

So CSS now correctly reflects reality:

this is no longer a modal system, it’s a page shell reused under a legacy ID

⚠ Naming mismatch risk (important)

You still call it:

id="execute-step-modal"

but it behaves like:

execution-step-page-container

This creates long-term confusion:

developers will assume modal semantics
CSS will contradict expectations

This is the largest architectural smell in this layer

4. Typography reset consistency

You are standardising:

text-transform: uppercase;
letter-spacing: 0.04em;

This is good design system alignment:

matches “wizard / create flow” language
enforces hierarchy consistency across app

No issues here.

5. HTML structure review (important coupling point)
✔ Good semantic grouping

You now have clean structural blocks:

docs
inputs
compliance
outputs

This is a pipeline-aligned UI model, which matches your execution domain.

⚠ Hidden coupling: IDs as API surface

These are effectively now UI API contracts:

#exec-section-inputs
#exec-section-compliance
#exec-section-outputs

Problem:

JS likely depends on these
CSS depends on these
backend may indirectly assume order

This creates:

implicit UI schema without versioning

6. One subtle risk: duplication of modal CSS + SPA CSS

You referenced:

/* Page shell lives in execution-modal.css */

But now you also have:

SPA overrides in batch-start.css
modal structural CSS
execution-specific CSS
Risk pattern:

competing style ownership across 2+ layers

This tends to evolve into:

“why does this override exist?”
increasing !important usage (you already have some earlier)
7. Overall assessment
What you’ve done well
✔ moved toward SPA-first rendering model
✔ isolated execution-step UI scope
✔ created consistent section rhythm system
✔ clarified layout responsibility boundaries
✔ reduced modal behavior dependency
What is still structurally fragile
1. Naming mismatch

modal ID used as page container

This is the most important unresolved issue.

2. Deep CSS coupling

Still relies on DOM hierarchy instead of semantic UI classes.

3. implicit UI schema via IDs

These IDs are now de facto API between:

JS render logic
CSS layout
backend payload shape
Net verdict

This is a good transitional architecture, not a final one.

You are currently in:

“legacy modal system being refactored into SPA page shell”

And you’ve executed that transition cleanly so far — but you haven’t yet completed the abstraction layer cleanup.