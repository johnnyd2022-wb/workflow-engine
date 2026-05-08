# batch-start-scripts.html — Security & Performance Review

File reviewed: `app/core/frontend/processes/batch-start-scripts.html`

---

## Security Findings

### S1 · Client-side `returnTo` validation is weaker than server-side · LOW

**Location:** `batch-start-scripts.html:31–38`

The client-side guard allows any path beginning with `/`:

```js
if (
  typeof dest !== 'string' ||
  !dest.startsWith('/') ||
  dest.startsWith('//') ||
  dest.indexOf('://') !== -1 ||
  dest.indexOf('\\') !== -1
) {
  dest = fallback;
}
```

The server (`_safe_flow_return_to`, `backend.py:139`) is stricter: it only allows paths under `/core/flows`. Because the server already validated the value before embedding it via Jinja2 `tojson`, this inconsistency is not directly exploitable today. However it's a maintenance hazard — if a future code path sends `return_to` to the client without going through `_safe_flow_return_to`, the client check won't catch it.

**Remediation steps:**

- [x] Tighten the client-side check to mirror the server's constraint. Replace the current validation block with:

  ```js
  var ALLOWED_PREFIX = '/core/flows';
  if (
    typeof dest !== 'string' ||
    (dest !== ALLOWED_PREFIX && !dest.startsWith(ALLOWED_PREFIX + '/') && !dest.startsWith(ALLOWED_PREFIX + '?'))
  ) {
    dest = fallback;
  }
  ```

- [x] Add a brief inline comment next to `_ALLOWED_RETURN_PREFIX` in `backend.py` noting that the client-side check in `batch-start-scripts.html` must be kept in sync when this prefix changes.

---

### S2 · Raw JS exception messages surfaced to users · LOW

**Location:** `batch-start-scripts.html:137`

```js
window.showNotification('error', 'Record step failed', err && err.message ? err.message : String(err));
```

JavaScript `Error.message` strings can include internal paths, function names, or third-party library details (e.g., `htmx: NetworkError failed to execute 'send' on 'XMLHttpRequest'`). While these are client-side only (no server secrets exposed), they can aid an attacker in fingerprinting the stack and they look unprofessional to users.

**Remediation steps:**

- [x] Replace the raw `err.message` with a generic user-facing string:

  ```js
  window.showNotification('error', 'Record step failed', 'Something went wrong. Please try again.');
  ```

- [x] If developer diagnostics are needed, log the original error to the console only:

  ```js
  console.error('[batch-start] submitExecution error:', err);
  window.showNotification('error', 'Record step failed', 'Something went wrong. Please try again.');
  ```

---

## Performance Findings

### P1 · `els()` re-queries the DOM on every keyboard event · MINOR

**Location:** `batch-start-scripts.html:56–63, 99–106`

`els()` is called inside `onKeyDown`, which fires on every keypress across the entire document. Each call issues 4 `getElementById` lookups. When the confirm dialog is closed (`e.root.hidden === true`) the function returns immediately, but the 4 lookups still ran first.

**Remediation steps:**

- [x] Cache element references in `wire()` and pass them to `onKeyDown` via closure, or store them in a module-level variable set once on `wire()`:

  ```js
  var cachedEls = null;

  function wire() {
    cachedEls = els();
    if (!cachedEls.openBtn || !cachedEls.root) return;
    // ... rest of wire using cachedEls
  }
  ```

  Note: this is safe here because HTMX replaces `#page-content` on each swap, which re-executes the script and re-runs `wire()`, refreshing the cache.

- [x] Update `onKeyDown` and `openConfirm`/`closeConfirm` to use `cachedEls` instead of calling `els()`.

---

### P2 · Global `keydown` listener is never removed · MINOR

**Location:** `batch-start-scripts.html:143–146`

```js
if (!document._batchConfirmKeyBound) {
  document._batchConfirmKeyBound = true;
  document.addEventListener('keydown', onKeyDown);
}
```

The `document._batchConfirmKeyBound` flag prevents duplicate listeners across HTMX swaps, but the listener is never cleaned up when the user navigates away from this page. On a long-lived SPA session this means the `onKeyDown` handler stays attached forever. The quick `!e.root` bail-out keeps it cheap at runtime, but it's a leak in principle and the `_batchConfirmKeyBound` property on `document` is informal namespace pollution.

**Remediation steps:**

- [x] Listen for HTMX's `htmx:beforeSwap` event (or `htmx:beforeHistoryUpdate`) to remove the listener when leaving this page:

  ```js
  function teardown() {
    document.removeEventListener('keydown', onKeyDown);
    document._batchConfirmKeyBound = false;
    document.removeEventListener('htmx:beforeSwap', teardown);
  }

  if (!document._batchConfirmKeyBound) {
    document._batchConfirmKeyBound = true;
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('htmx:beforeSwap', teardown, { once: true });
  }
  ```

- [x] Alternatively, scope the listener to `#batch-record-confirm-root`'s nearest focusable ancestor rather than `document`, so it's automatically garbage-collected when HTMX replaces that subtree.

---

## No Action Required

- **`tojson` usage** (lines 5–9): correct — values are JSON-encoded by Jinja2 before injection, preventing XSS.
- **`return_to` server validation** (`backend.py:139`): thorough — covers percent-encoding bypass, path traversal, protocol-relative URLs, and restricts to `/core/flows`.
- **Script load order** (lines 48–51): in HTMX's innerHTML-swap context, synchronously-injected scripts execute in order regardless of `async`/`defer`; adding those attributes would have no effect.
