# JavaScript Review Skill: Security, Performance & Correctness

You are reviewing JavaScript in a **multi-tenant SaaS** that uses vanilla JS (no React/Vue), HTMX, and a shared `CoreAPI` client. Every JS file or `<script>` block you write or modify must satisfy the rules below. Flag violations before completing any implementation and fix them.

---

## SECURITY

### 1. Use `CoreAPI.request()` — Never Raw `fetch()` for API Calls

`CoreAPI` (`app/core/frontend/js/core-api.js`) handles CSRF token injection, `Content-Type`, JSON serialisation, error normalisation, and network-error detection. Raw `fetch()` silently skips the CSRF header on mutating requests, causing 400/403 failures.

**BAD**:
```javascript
const resp = await fetch('/api/core/processes', {
    method: 'POST',
    body: JSON.stringify(data)
    // no CSRF header — will 400
});
const json = await resp.json(); // no error handling
```

**GOOD**:
```javascript
const result = await CoreAPI.request('/processes', {
    method: 'POST',
    body: data   // CoreAPI handles stringify + CSRF
});
```

For endpoints outside `/api/core` (CRM, workflow-engine), read the token from the meta tag explicitly:
```javascript
const csrf = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
const resp = await fetch('/crm/invoices', {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf, 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
});
```

---

### 2. XSS — Never Inject User-Supplied Data via `innerHTML`

`innerHTML` parses its argument as HTML. Any user-controlled string passed to it is an XSS vector.

**BAD**:
```javascript
// user.name / user.email come from the API
card.innerHTML = `<h2>${user.name}</h2><p>${user.email}</p>`;
row.innerHTML = `<td>${item.sku}</td><td>${item.description}</td>`;
```

**GOOD** — use `textContent` for plain text:
```javascript
const h2 = document.createElement('h2');
h2.textContent = user.name;   // never parsed as HTML
card.appendChild(h2);
```

**GOOD** — or set the element then text separately:
```javascript
const td = row.insertCell();
td.textContent = item.sku;
```

`innerHTML` is acceptable **only for static markup strings with no user data**:
```javascript
container.innerHTML = '<p class="page-subtitle">No items found.</p>';  // safe
```

---

### 3. Always `encodeURIComponent` User Values in Query Strings

Building a URL with user input without encoding it allows injection into the URL structure.

**BAD**:
```javascript
const url = `/api/core/inventory?q=${searchValue}&category=${category}`;
```

**GOOD**:
```javascript
const params = new URLSearchParams({ q: searchValue, category });
const url = `/api/core/inventory?${params}`;
```

---

## ERROR HANDLING

### 4. Always Handle Fetch Errors and Show User Feedback

Uncaught promise rejections leave the UI in a broken blank state with no indication of what happened.

**BAD**:
```javascript
async function loadItems() {
    const data = await CoreAPI.request('/inventory');
    renderItems(data.items);
}
```

**GOOD**:
```javascript
async function loadItems() {
    container.innerHTML = '<p class="page-subtitle">Loading…</p>';
    try {
        const data = await CoreAPI.request('/inventory');
        renderItems(data.items);
    } catch (err) {
        container.innerHTML = '<p style="color: var(--error);">Failed to load. Please refresh.</p>';
        console.error('loadItems failed:', err);
    }
}
```

---

### 5. Show Loading States — Never Leave the UI Blank During a Fetch

A container with no content while a request is in-flight feels broken and gives no feedback.

**BAD**:
```javascript
async function openModal(id) {
    const data = await CoreAPI.request(`/executions/${id}`);
    populateModal(data);
    modal.style.display = 'flex';
}
```

**GOOD**:
```javascript
async function openModal(id) {
    modal.style.display = 'flex';
    modalBody.innerHTML = '<p class="page-subtitle">Loading…</p>';
    try {
        const data = await CoreAPI.request(`/executions/${id}`);
        populateModal(data);
    } catch (err) {
        modalBody.innerHTML = '<p style="color: var(--error);">Failed to load.</p>';
    }
}
```

---

## PERFORMANCE

### 6. Debounce Search and Filter Inputs — No Request Per Keystroke

Live search without debouncing fires a network request for every character typed.

**BAD**:
```javascript
searchInput.addEventListener('input', () => {
    CoreAPI.request(`/inventory?q=${searchInput.value}`).then(render);
});
```

**GOOD**:
```javascript
let searchTimer;
searchInput.addEventListener('input', () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        const params = new URLSearchParams({ q: searchInput.value });
        CoreAPI.request(`/inventory?${params}`).then(render).catch(console.error);
    }, 300);
});
```

---

### 7. Batch DOM Updates with `DocumentFragment`

Appending nodes one at a time inside a loop causes a reflow on every append. Batch into a fragment first.

**BAD**:
```javascript
items.forEach(item => {
    const row = buildRow(item);
    tableBody.appendChild(row);  // reflow per iteration
});
```

**GOOD**:
```javascript
const fragment = document.createDocumentFragment();
items.forEach(item => fragment.appendChild(buildRow(item)));
tableBody.appendChild(fragment);  // single reflow
```

---

### 8. Cancel In-Flight Requests When the User Moves On

If a user triggers a new search or navigation before the previous fetch completes, the stale response can overwrite fresh UI.

**BAD**:
```javascript
async function search(q) {
    const data = await CoreAPI.request(`/inventory?q=${q}`);
    render(data);  // may arrive after a newer search
}
```

**GOOD** — abort the previous request:
```javascript
let activeController = null;

async function search(q) {
    if (activeController) activeController.abort();
    activeController = new AbortController();
    try {
        const data = await CoreAPI.request(`/inventory?q=${q}`, {
            signal: activeController.signal
        });
        render(data);
    } catch (err) {
        if (err.name !== 'AbortError') {
            showError(err);
        }
    }
}
```

---

## CORRECTNESS

### 9. Guard Against `null` DOM Elements Before Accessing Properties

`document.querySelector` returns `null` if the element doesn't exist. This is common after HTMX swaps.

**BAD**:
```javascript
const btn = document.querySelector('#submit-btn');
btn.addEventListener('click', handleSubmit);  // TypeError if not found
```

**GOOD**:
```javascript
const btn = document.querySelector('#submit-btn');
if (btn) btn.addEventListener('click', handleSubmit);
```

Or, for initialisation that runs after every HTMX swap:
```javascript
document.addEventListener('htmx:afterSwap', () => {
    const btn = document.querySelector('#submit-btn');
    if (btn) btn.addEventListener('click', handleSubmit);
});
```

---

### 10. Remove Event Listeners Before Re-Attaching

Attaching the same listener multiple times (e.g. inside a function called on each HTMX swap) stacks handlers and fires them N times.

**BAD**:
```javascript
function init() {
    document.querySelector('#form').addEventListener('submit', handleSubmit);
    // called on every swap → N listeners by swap N
}
```

**GOOD**:
```javascript
function init() {
    const form = document.querySelector('#form');
    if (!form) return;
    form.removeEventListener('submit', handleSubmit);  // idempotent
    form.addEventListener('submit', handleSubmit);
}
```

---

### 11. Never Store Sensitive Values in `localStorage` or `sessionStorage`

Both are accessible to any JS on the page (including injected scripts). Never put session tokens, CSRF secrets, or full org credentials there.

**BAD**:
```javascript
localStorage.setItem('authToken', token);
sessionStorage.setItem('csrfSecret', csrf);
```

**GOOD**: The CSRF token is read from `<meta name="csrf-token">` on each request. Auth state is managed server-side via the session cookie. UI preferences (theme, sidebar state) are fine in `localStorage`.

---

## CHECKLIST

- [ ] All mutating API calls use `CoreAPI.request()` (not raw `fetch`) — CSRF handled
- [ ] Non-`/api/core` mutating fetches read CSRF from `meta[name="csrf-token"]` explicitly
- [ ] No `innerHTML` with user-supplied data — use `textContent` or DOM node creation
- [ ] User values in query strings go through `URLSearchParams` / `encodeURIComponent`
- [ ] Every async function has a `try/catch` with visible user feedback
- [ ] Loading state shown before the fetch, error state shown on failure
- [ ] Search/filter inputs debounced (300ms)
- [ ] Large list renders use `DocumentFragment`
- [ ] Long-lived searches use `AbortController` to cancel stale requests
- [ ] DOM element existence checked before property access
- [ ] Event listeners not stacked on repeated `init()` calls
- [ ] No sensitive values in `localStorage` or `sessionStorage`
