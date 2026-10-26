# CSP migration: no inline or evaluated script (GL-S03)

## Where it stands

The enforced policy allows `'unsafe-inline'` and `'unsafe-eval'` in `script-src`. Either one
lets injected markup run script, so the HTML escaping and the semgrep `innerHTML` rules are the
only line of defence against XSS. The goal is a policy where script runs only from our own
files or from an inline block carrying the response's nonce:

```
script-src 'self' 'nonce-…' https://static.cloudflareinsights.com; script-src-attr 'none'
```

`style-src 'unsafe-inline'` stays. About 1,100 `style=""` attributes depend on it, and inline
style can't run script. Moving them is cosmetic work with little security return.

## What blocks it (measured 2026-10-26)

| Blocker | Count | Where |
|---|---|---|
| Inline `<script>` blocks | 28 | Done in step 1: all carry the nonce |
| Inline `on*=""` handlers in templates | 80 | `core2.html` (16), `landing.html` (8), the process wizard and modals (≈35), sidebars, settings |
| `onclick=` written by scripts | 8 | `app.js`, `common.js`, `process-flow-next-steps-steps.js`, `sourcemap.js` |
| Alpine 3.15 standard build (evaluates attribute expressions) | ≈950 attributes in 16 templates | CRM pages (≈800), Tasks board, base shell, integrations, inventory add |
| htmx `allowEval` (`hx-on`, `js:` values) | none in use | Set `allowEval: false` at the end |

## Steps (one MR each)

1. **Foundation** (this MR):
   - per-response nonce on every inline script, and htmx's `inlineScriptNonce` for boosted swaps;
   - the strict policy sent **report-only**, with reports logged by `/csp-report` (no query strings, no fragments);
   - `object-src 'none'`, `base-uri 'self'` and `frame-ancestors` enforced now;
   - the unused `unpkg.com` allowance dropped;
   - a browser walk of every page, full load and boosted, proving nothing is blocked and every inline script passes the nonce policy.
2. **Inline handlers** (done, !588):
   - All 92 lines of `on*=""` handlers (templates and script-built markup) now use `data-action`, run by one delegated listener (`app/ui/shared/actions.js`) with an allowlist of callable names.
   - Stop, dismiss and remove go through `data-action-stop`, `data-dismiss` and `data-remove-ancestor`; forms use `data-submit-action`.
   - Hover styles moved to CSS.
   - `script-src-attr 'none'` is now **enforced**.
   - `tests/test_csp.py` ratchets new handler attributes out, and `tests/e2e/test_actions_dispatch.py` drives the dispatcher.
3. **Alpine.**
   - Swap to `@alpinejs/csp` 3.15.12.
   - Move each inline `x-data="{…}"` object into an `Alpine.data()` component in the page's script.
   - Rewrite expressions the CSP build's parser can't run (arrow functions, template literals) as component methods.
   - Do the CRM pages one at a time (customer detail, overview, tasks, configuration, then the rest), each driven in the browser before the next.
4. **Enforce.**
   - Remove `'unsafe-inline'` and `'unsafe-eval'` from `script-src` and add `script-src-attr 'none'`.
   - Set htmx `allowEval: false` and keep the report endpoint.
   - The browser walk then asserts zero report-only violations as well.
   - Playwright's own `wait_for_function` and `evaluate` count as eval under a strict policy. The e2e context sets `bypass_csp=True` for helpers only, and the walk keeps a CSP-honouring context.

## Checks

- `tests/test_csp.py`:
  - the nonce on every inline script and in the header;
  - a fresh nonce per response;
  - the enforced hardening;
  - report parsing that drops query strings;
  - a template scan for inline scripts without the nonce.
- `tests/e2e/test_csp_browser.py`: every registry page, full load and boosted, with no enforced violation and no inline script failing the nonce policy.
- Production: the `csp_violation` log lines are the remaining work list. Step 4 waits until they stop.
