# batch-start related HTML files — Security & Performance Review

Files reviewed:
- `app/core/frontend/processes/batch-start.html`
- `app/core/frontend/processes/batch-start-hx.html`
- `app/core/frontend/processes/batch-start-fragment.html`
- `app/core/frontend/shared/base_spa.html`
- `app/core/frontend/shared/execution-modal.html`
- `app/core/frontend/shared/execution_modal_stack_scripts.html`
- `app/core/frontend/processes/create-process-step-content-styles.html`

Note: `batch-start-scripts.html` covered in a separate review (all findings already resolved).

---

## Security Findings

### S1 · Alpine.js loaded from CDN with floating version and no SRI hash · MEDIUM

**Location:** `base_spa.html:1094`

```html
<script crossorigin="anonymous" src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
```

`@3.x.x` is a dist-tag on npm that resolves to the latest 3.x release at cache-miss time — not a pinned version. Combined with the absence of a Subresource Integrity (SRI) `integrity=` attribute, this means:

1. The loaded code can change silently when any new Alpine 3.x release is published.
2. A compromised or MITM'd CDN can serve arbitrary JavaScript with no browser-level verification.

An attacker who could influence the unpkg CDN response (supply-chain attack, BGP hijack, or network interception on a corporate network) would gain full script execution in every user's session — including access to the CSRF token in the DOM, auth cookies via same-origin fetch, and the ability to forge API requests.

**Remediation steps:**

- [x] Pin Alpine to an exact version in the URL, e.g. `alpinejs@3.14.9`.
- [x] Generate an SRI hash for the pinned file:
  ```bash
  curl -s https://unpkg.com/alpinejs@3.14.9/dist/cdn.min.js | openssl dgst -sha384 -binary | openssl base64 -A
  ```
  Then set `integrity="sha384-<hash>"` on the `<script>` tag.
- [x] Alternatively (preferred): self-host Alpine by copying the minified file into `app/core/frontend/js/` and serving it via `url_for('core.serve_core_js', filename='alpinejs.min.js')`. This removes the external dependency entirely and makes the file cacheable alongside the rest of the app's static assets. **Done: vendored `alpinejs.min.js` (v3.15.12) and `htmx.min.js` (v1.9.10) to `app/core/frontend/js/`; `base_spa.html` updated to use `url_for` for both.**

---

### S2 · HTMX loaded from CDN without SRI hash · LOW

**Location:** `base_spa.html:1093`

```html
<script src="https://unpkg.com/htmx.org@1.9.10" crossorigin="anonymous"></script>
```

HTMX is version-pinned (`@1.9.10`), which is better than Alpine, but still has no SRI hash. Same CDN-compromise attack path applies, and HTMX has even higher surface area than Alpine — it intercepts all link clicks, reads DOM attributes, and makes every AJAX request in the SPA.

**Remediation steps:**

- [x] Add an SRI hash (same approach as S1).
- [x] Preferred: self-host alongside Alpine — done (see S1 above).
- [x] If keeping the CDN, at minimum verify the hash at build/deploy time via a CI step. *(Not applicable — now self-hosted.)*

---

## Performance Findings

### P1 · ~800 lines of inline CSS in base_spa.html cannot be cached · MEDIUM

**Location:** `base_spa.html:33–826`

The `<style>` block spanning ~800 lines (SPA layout, typography, bee mascot, toggle components, HTMX transitions, notification toast) is inline HTML. The browser:
- Re-parses this CSS on every full page load (including cold loads and hard refreshes).
- Cannot independently cache it — it's bundled into the HTML response.
- Must compute styles before first paint (render-blocking).

Since every page in the SPA that extends `base_spa.html` carries this payload, it affects all routes, not just batch-start.

**Remediation steps:**

- [x] Extract the inline `<style>` block to `app/core/frontend/css/base-spa.css`. Both the main ~800-line block and the small notification toast animation block were extracted together.
- [x] In `base_spa.html` replace both `<style>` blocks with a single `<link>` tag — added as the first entry in the core styles group. `serve_core_css` serves from `frontend/css/` and already accepts `.css`, so no route change needed.
- [x] Confirm the Flask static handler for `serve_core_css` sets `Cache-Control: max-age=...` — added `Cache-Control: public, max-age=3600, stale-while-revalidate=60` to both `serve_core_css` and `serve_core_js` in `backend.py`.
- [x] `base-spa.css` slots in alongside `styles2.css`, `spa-theme.css`, etc. as intended.

---

### P2 · HTMX render-blocking external CDN request on every cold load · LOW

**Location:** `base_spa.html:1093`

HTMX is loaded without `defer` or `async` — intentionally, since page content depends on it. But as an external CDN request it must complete before HTML parsing continues. On slow connections or when unpkg has elevated latency, this directly delays time-to-interactive.

This finding is resolved if S1/S2 are fixed via self-hosting (a local `serve_core_js` request is far faster and already being made for other JS files on the page).

**Remediation steps:**

- [x] Self-host HTMX as described in S2 — done.

---

### P3 · `tagExecAddMissingItemControls` queries entire `document` on every HTMX settle · LOW

**Location:** `base_spa.html:1362–1364`

```js
document.body.addEventListener('htmx:afterSettle', function (evt) {
  tagExecAddMissingItemControls(document);
  ...
```

`tagExecAddMissingItemControls` runs a multi-selector `querySelectorAll` across the entire document on every HTMX settle event (every navigation). It also runs on `htmx:afterSwap` and `htmx:afterOnLoad`. When the settle event fires for a `#page-content` swap, the work is only relevant within `#page-content` — scanning the full document is wasteful and will scale badly as the DOM grows.

**Remediation steps:**

- [x] Scope the `htmx:afterSettle` and `htmx:afterSwap` calls to the swap target — done in `base_spa.html`.
- [x] The `DOMContentLoaded` call (`tagExecAddMissingItemControls(document)`) is fine as-is — full-document scan on initial load is appropriate.

---

### P4 · Inline CSS re-injected into page body on every HTMX navigation to batch-start · LOW

**Location:** `batch-start-hx.html:6`

```html
{% include 'processes/create-process-step-content-styles.html' %}
```

Because HTMX swaps `#page-content` (not `<head>`), CSS cannot be injected into `<head>` via the HTMX response. The workaround is to include the `<style>` block inline in the fragment so the browser applies it after each swap. This means ~260 lines of CSS are re-parsed on every navigation to the batch-start page.

This is a known HTMX architectural tradeoff (not a bug). The correct fix is to load the styles globally at shell-load time.

**Remediation steps:**

- [x] Move `create-process-step-content-styles.html` CSS into `app/core/frontend/css/create-process-step-content.css`.
- [x] Load it from `base_spa.html`'s `<head>` globally — added alongside `batch-start.css` and the other shell stylesheets.
- [x] Removed the `{% include %}` from `batch-start-hx.html`, `batch-start.html`, and `process-flow-spa.html` (also extends `base_spa.html`). `create-process-modal.html` retains its include — it's a standalone modal fragment with no access to `<head>`.

---

## No Action Required

- **`batch-start-fragment.html`**: Fully static HTML + inline SVG. No template variables rendered, no JS. No security or performance concerns.
- **`batch-start.html`**: Thin Jinja2 wrapper. Issues are inherited from included partials (addressed above).
- **`execution-modal.html`**: Modal HTML with hardcoded inline `onclick` handlers (no user data interpolated). The `#ready-date-confirm-body` slot is JS-populated — XSS exposure depends on whether the populating JS uses `textContent` vs `innerHTML`. The JS files are outside this review's scope; confirm in `execution-render-inputs.js`.
- **`execution_modal_stack_scripts.html`**: 14 sequential `<script>` tags without `async`/`defer`. For HTMX-injected scripts, `defer` has no effect (injected scripts execute immediately by spec), so adding those attributes would be misleading. Not actionable.
- **`create-process-step-content-styles.html`**: Pure CSS, no dynamic content.
