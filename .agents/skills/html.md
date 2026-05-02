# HTML / Jinja2 Review Skill

You are reviewing Jinja2 HTML templates in a **multi-tenant SaaS** that uses Flask, vanilla JS, HTMX, and a shared design system. The SPA shell is `app/core/frontend/shared/base_spa.html`. All shared partials and macros live in `app/core/frontend/shared/`.

Every template you write or modify must satisfy the rules below. Flag violations before completing any implementation and fix them.

---

## STRUCTURE

### 1. Extend `base_spa.html` — Never Write Standalone HTML

`base_spa.html` provides the shell, sidebar, CSRF meta tag, global CSS, font loading, theme initialisation, and the `#page-content` HTMX swap target. Any new SPA page that bypasses it will silently break one or more of those things.

**BAD**:
```html
<!DOCTYPE html>
<html>
<head>
  <link rel="stylesheet" href="/static/styles.css">
  <meta name="csrf-token" content="{{ csrf_token() }}">
</head>
<body>
  <!-- reimplementing the sidebar... -->
```

**GOOD**:
```html
{% extends "shared/base_spa.html" %}

{% block title %}Inventory{% endblock %}

{% block head_extras %}
  <link rel="stylesheet" href="{{ url_for('core.serve_core_css', filename='inventory-spa-header.css') }}">
{% endblock %}

{% block content %}
  <div id="page-content" class="page-content">
    ...
  </div>
{% endblock %}
```

---

### 2. Use Shared Partials and Macros — Never Duplicate Their Markup

These components already exist. Duplicating them creates inconsistency and silently diverges when the shared version is updated.

| Need | What to use |
|---|---|
| Page title + subtitle + optional CTA | `{% from 'shared/page_header.html' import page_header %}` → `{{ page_header(title, subtitle, href, label) }}` |
| Content card with heading | `{% from 'shared/primary_card.html' import primary_card %}` → `{% call primary_card(title) %}…{% endcall %}` |
| Sidebar | Already in `base_spa.html` — never `{% include %}` it again |
| Delete confirmation modal | `{% include 'shared/delete-doc-confirm-modal.html' %}` |
| Execution modal | `{% include 'shared/execution-modal.html' %}` |
| Sticky bottom action bar | Set `spa_fixed_action_right_html`, then `{% include 'shared/spa-fixed-action-bar.html' %}` |
| Back link | `{% include 'shared/back_link.html' %}` |
| Notifications banner | `{% include 'shared/notifications_hub_banner.html' %}` |
| System findings banner | `{% include 'shared/system-findings-banner.html' %}` |

**BAD** — hand-rolling a page header:
```html
<div style="display: flex; justify-content: space-between; align-items: center;">
  <div>
    <h1 style="font-size: 1.5rem; font-weight: 600;">Inventory</h1>
    <p style="color: #6b7280;">Manage your stock</p>
  </div>
  <a href="/inventory/add" class="btn btn-primary">Add Item</a>
</div>
```

**GOOD**:
```html
{% from 'shared/page_header.html' import page_header %}
{{ page_header(
    title="Inventory",
    subtitle="Manage your stock",
    primary_action_href="/inventory/add",
    primary_action_label="Add Item"
) }}
```

---

## SECURITY

### 3. Never Use `| safe` on User-Supplied Values — XSS

Jinja2 autoescapes `{{ var }}` by default. Using `| safe` on anything that originated from user input disables that protection.

**BAD**:
```html
<h2>{{ user.name | safe }}</h2>
<p>{{ item.description | safe }}</p>
```

**GOOD** — autoescaping is on by default, nothing to change:
```html
<h2>{{ user.name }}</h2>
<p>{{ item.description }}</p>
```

`| safe` is only acceptable for **known-safe, developer-controlled HTML** (e.g. rendered icon SVG passed from Python, or a hardcoded string literal).

---

### 4. Don't Put Sensitive Data in `data-*` Attributes or Hidden Inputs

`data-*` attributes and `<input type="hidden">` are fully visible in the DOM and browser devtools. Never put session tokens, API keys, org secrets, or raw internal IDs that confer privilege there.

**BAD**:
```html
<div data-user-token="{{ session_token }}" data-org-secret="{{ org_api_key }}">
<input type="hidden" name="org_id" value="{{ current_org_id }}">
```

**GOOD**: The backend reads `g.current_org_id` from the session — it never trusts a client-submitted `org_id` field. IDs that are only used for display or UI correlation (not privilege checks) are fine in `data-*`.

---

### 5. Feature-Gated Pages Must Be Gated Server-Side, Not Only in Templates

Template conditionals are cosmetic — a user can craft a direct request to bypass them.

**BAD**:
```html
{% if current_user.org.crm_enabled %}
  <a href="/crm">CRM</a>
{% endif %}
{# /crm routes still accessible if blueprint was registered unconditionally #}
```

**GOOD**: `crm_bp` is only registered in the app factory when `crm_enabled` is `True`. The template nav link is an additional UX hint, not the access gate. Never add routes inside a blueprint and rely on a template check to hide them.

---

## DESIGN SYSTEM

### 6. Use CSS Variables and Design-System Classes — No Hardcoded Colours

Hardcoded hex values don't respect dark mode and diverge from the visual language.

**BAD**:
```html
<button style="background: #3b82f6; color: white; border-radius: 8px; padding: 8px 16px;">Save</button>
<p style="color: #6b7280; font-size: 14px;">No results</p>
```

**GOOD**:
```html
<button class="btn btn-primary">Save</button>
<p class="page-subtitle">No results</p>
```

Key CSS variables:

| Token | Purpose |
|---|---|
| `var(--primary)` | Brand blue — interactive elements |
| `var(--text-primary)` | Body text |
| `var(--text-secondary)` | Muted / secondary text |
| `var(--text-tertiary)` | Hints, placeholders |
| `var(--bg-card)` | Card backgrounds |
| `var(--bg-app)` | Page background |
| `var(--border-default)` | Default border colour |
| `var(--error)` | Destructive / error state |
| `var(--success)` | Positive / success state |
| `var(--radius-md)` / `var(--radius-lg)` / `var(--radius-xl)` | Border radii |
| `var(--shadow-lg)` | Elevated shadow |

Utility classes: `btn btn-primary`, `btn btn-secondary`, `btn btn-glass`, `card`, `glass-card`, `page-title`, `page-subtitle`, `card-title`, `card-content`.

---

### 7. Scope Page-Specific CSS — Don't Add Unscoped Rules to Global Stylesheets

Unscoped rules in `styles2.css`, `spa-theme.css`, or the `base_spa.html` `<style>` block affect every page.

**BAD** — added to a global stylesheet:
```css
.table-row { background: var(--bg-card); }
.action-btn { padding: 4px 8px; }
```

**GOOD** — scoped in `{% block head_extras %}`:
```html
{% block head_extras %}
<style>
  .inventory-view .table-row { background: var(--bg-card); }
  .inventory-view .action-btn { padding: 4px 8px; }
</style>
{% endblock %}
```

Rules that genuinely need to be global (e.g. used across multiple HTMX page swaps) belong in a dedicated CSS file loaded by `base_spa.html`, with a comment explaining why.

---

## HTMX

### 8. Always Swap Into `#page-content`

HTMX SPA navigation uses `#page-content` as the swap target. Swapping into a different container breaks the sidebar, theme, and scroll position.

**BAD**:
```html
<a href="/inventory" hx-get="/inventory" hx-target="#main" hx-swap="innerHTML">Inventory</a>
```

**GOOD**:
```html
<a href="/inventory" hx-get="/inventory" hx-target="#page-content" hx-swap="innerHTML">Inventory</a>
```

For intentional full-page navigation across blueprints (e.g. `/core` from the workflow-engine blueprint), use `hx-boost="false"` to opt out of HTMX entirely:
```html
<a href="/core" hx-boost="false">Core</a>
```

---

## ACCESSIBILITY

### 9. Labels, Roles, and `aria-*` on Interactive Elements

Every form control needs an associated `<label>`. Every icon-only button needs `aria-label`. Modals need `role="dialog"` and `aria-labelledby`.

**BAD**:
```html
<input type="text" placeholder="Search...">
<button onclick="deleteItem(id)"><svg>…</svg></button>
<div class="modal-overlay" style="display:block;">…</div>
```

**GOOD**:
```html
<label for="search-input">Search</label>
<input id="search-input" type="text" placeholder="Search…">

<button onclick="deleteItem(id)" aria-label="Delete item">
  <svg aria-hidden="true">…</svg>
</button>

<div class="modal-overlay" role="dialog" aria-modal="true" aria-labelledby="modal-title">
  <h2 id="modal-title">Confirm deletion</h2>
  …
</div>
```

---

## CHECKLIST

- [ ] Page extends `shared/base_spa.html` — no standalone `<!DOCTYPE html>`
- [ ] Shared partials/macros used instead of hand-rolled markup
- [ ] No `| safe` on user-supplied Jinja2 values
- [ ] No sensitive data in `data-*` attributes or `<input type="hidden">`
- [ ] Feature gates enforced server-side (blueprint registration), not only in template conditionals
- [ ] No hardcoded hex colours — CSS variables and design-system classes used
- [ ] Page-specific CSS is scoped to a component class, not added globally
- [ ] HTMX swaps target `#page-content`; cross-blueprint links use `hx-boost="false"`
- [ ] Every `<input>` has an associated `<label>`; icon buttons have `aria-label`
