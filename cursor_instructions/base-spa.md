We are now going to modernuse the UI using htmx and alpine css
We are going to change the UI to emulate a performant SPA

The Correct Strategy for our Platform

Instead of:

"Make every modal a page"

Think:

Make every modal a routeable screen, but keep HTMX fragments for speed.

This gives you:

SPA-like navigation

Clean URLs

Deep linking

No heavy frontend framework

No complex client state

The Architecture I Recommend
1. Create a Shared SPA Layout Template in app/core/frontend/shared/

Your base layout becomes something like:

base_spa.html

Structure:

<body>

  sidebar
  topbar
  system_findings_banner

  <main id="page-content">
      {% block content %}
      {% endblock %}
  </main>

</body>

Then HTMX swaps only #page-content.

2. Every Page Gets Two Render Modes

Each route should support:

Full Page Render

Normal navigation.

Example:

GET /executions/123

Returns full page with layout.

Partial HTMX Render

If request contains:

HX-Request: true

Return only the page fragment.

Example return:

execution_detail_fragment.html

HTMX swaps it into:

#page-content
3. Navigation Uses HTMX Boost

Add to your layout:

<body hx-boost="true" hx-target="#page-content" hx-push-url="true">

This automatically converts links into AJAX navigation.

Result:

Clicking:

<a href="/executions/123">

Will:

• Fetch fragment
• Replace #page-content
• Update browser URL
• Maintain history

It feels exactly like an SPA.

4. Convert Modals → Dedicated Screens

You are 100% correct here.

Modals cause problems:

state confusion

poor mobile UX

broken back button

accessibility issues

Your current rule:

No modal forms, only screens

is excellent product design.

Examples:

Instead of:

Modal: Add Inventory

Use:

/inventory/add

Instead of:

Execution modal

Use:

/executions/{id}

These still load inside the SPA container via HTMX.

5. Use Alpine Only for Local Interactions

Use Alpine.js only for small UI behaviour:

Examples:

dropdowns

collapsible panels

tab switching

small UI state

Do not use Alpine for:

data fetching

application state

routing

HTMX already handles that.

6. Preserve Real URLs Everywhere

Every screen should have a real route.

Example structure for your product:

/inventory
/inventory/add
/inventory/item/{id}

/processes
/processes/{id}
/processes/{id}/step/{id}

/executions
/executions/{id}
/executions/{id}/evidence

HTMX loads fragments, but URL remains canonical.

This is very important for SaaS reliability.

7. Global Loading Indicators

Add one small UX improvement:

.htmx-indicator

Example:

<div id="loading-indicator" class="htmx-indicator">
  Loading...
</div>

Then:

hx-indicator="#loading-indicator"

Your UI instantly feels modern.

8. Animate Page Transitions

Optional but powerful.

CSS example:

#page-content {
  transition: opacity 0.15s ease;
}

HTMX events:

htmx:beforeSwap
htmx:afterSwap

Fade out → swap → fade in.

9. Why This Is Perfect For Your Platform

Your product already:

• server-renders
• uses Flask routes
• has strong domain logic
• avoids heavy JS frameworks

Using HTMX keeps everything aligned with that architecture.

One Important UX Tip For Your Platform

Because your system shows:

inventory

executions

compliance warnings

sourcemaps

You should never reload the entire page when navigating.

Only update:

#page-content

This preserves:

sidebar state

banner state

system findings

navigation

Which makes the platform feel much more professional.

Page content structure

SPA-style layout should look like this:

Sidebar (persistent)
Top Bar (persistent)
System Findings Banner (persistent)

---------------------------------
Main Content Area (changes)
---------------------------------

HTMX should only swap:

#page-content

This ensures:

navigation feels instant

system banner stays visible

sidebar state is preserved

page transitions feel smooth

Inside the Page Content Area

Inside #page-content, you should use consistent UI containers, but each page should be free to structure itself logically.

Think of a design system, not a fixed page template.

Example pattern:

#page-content

Page Header
---------------------------------
Title
Actions (buttons)

Main Card
---------------------------------
Primary content

Secondary Cards
---------------------------------
Supporting information
Example From Your Product
Inventory Page
Inventory
---------------------------------
+ Add to Inventory

[ Raw Materials Column ]
[ Intermediate Products Column ]
[ Final Products Column ]
Execution Page
Execution: Fermentation Step
---------------------------------

Step Details Card

Input Materials Card

Output Materials Card

Evidence Upload Card
Process Step Editor
Process Step
---------------------------------

Step Configuration Card

Output Definitions Card

SOP Documentation Card

Expiry / Ready Date Rules Card
Why This Works Best

If every page uses identical containers you get:

artificial layouts

wasted space

awkward UX

If every page is totally different you get:

confusing UI

cognitive overload

The correct approach is:

shared layout + reusable components

The 5 UI Components You Should Standardize

Across your platform, consistently use:

1. Page Header
Title
Description
Primary action
2. Cards / Panels

For grouped content.

border
rounded
shadow
padding
3. Tables / Grids

For:

inventory

executions

logs

system checks

4. Status Indicators

For things like:

expired

ready date not met

untracked items

warnings

These should always look identical.

5. Action Bars

Consistent placement for:

Save
Cancel
Execute
Add
Upload

Usually top-right of the page header.

The Mental Model

Think of your app like:

Linear

GitHub

Notion

They share:

sidebar

top navigation

design system

But each page is optimized for its task.

One UX Rule That Will Improve Your Platform

For operational software like yours:

Never hide important actions inside deep containers.

Your users need to:

execute steps

add inventory

reconcile items

Those actions should always be visible near the page header.

Final Recommendation

Structure your UI like this:

Persistent
---------
Sidebar
Top Bar
System Findings Banner

Dynamic
---------
#page-content
    Page Header
    Cards / Tables / Grids

Use consistent container styles, but allow page layouts to adapt to the workflow.