# Build review: public MCP 8.2c (bize_mcp: discover, docs, execute)

Reviewer: Claude (a subagent, high effort; Codex is out of quota until 17 Nov 2026), on `git diff origin/main...HEAD`.
Brief: token only in the Authorization header, no token in logs, error mapping per spec, row caps, no `app`
import, prompt-injection wording on tool descriptions. Verdict: nothing exposes a token or breaks tenant
isolation; two real bugs and several hardening items, all fixed or answered below. Regression tests are in
`tests/mcp_server/test_review_findings.py` (F-numbers match).

| # | Finding | Disposition |
|---|---|---|
| F1 | Redacting the *JSON text* made data containing "Bearer x" crash or silently lose keys | **Fixed.** Redaction walks the object (`redact_value`); the bearer pattern stops at JSON punctuation. |
| F2 | The HTTP client logged full request URLs (query values) at INFO | **Fixed.** `httpx2`/`httpcore2` loggers set to WARNING; a test proves a sentinel query value never reaches a log. |
| F3 | A bearer value with non-ASCII or control characters was an internal error or "Biz-E had a problem" instead of a 401 | **Fixed.** `_bearer` accepts only token syntax (up to 512 chars); the client also treats `ValueError` as a transport failure. |
| F4 | `format: uuid/date` in the OpenAPI schemas was not enforced, so a sibling static route name could be sent as an id | **Fixed.** `FormatChecker` on; dead unused helpers removed from `validation.py`; the test transport now passes the raw (encoded) path. Residual: a path parameter with no pattern, format or enum is only restricted to one encoded segment. The app's policy still limits a token to read routes the person holds. |
| F5 | `discover` and `docs` unlimited; per-query CPU | **Fixed.** Document word sets cached, query capped at 12 words, 120 calls a minute per grant for every tool, response body cap lowered to 4 MB. |
| F6 | `execute` budget keyed on the token; refused runs not audited | **Fixed.** Keyed on the grant; limiter windows are per app; every execute (including refused ones) writes `mcp.execute`. |
| F7 | A malformed parameter schema failed the whole batch | **Fixed.** It fails only its own call. |
| F8 | Trimmed lists kept a cursor that would skip rows; `page_size` unclamped | **Fixed.** No cursor is offered once rows were cut; `page_size` is clamped like `limit`. Residual: the 256 KB budget is measured on `results` while text and structured content both carry it (about 2x on the wire); accepted, a client uses one copy. |
| F9 | `[*].field` projections dropped nulls, so a cost could pair with the wrong lot | **Fixed.** Projections keep nulls in place (a deliberate difference from JMESPath, documented in `select.py`). |
| F10 | Misc | **Fixed:** token out of `repr`; `jsonschema` declared in the extra; server refuses to start with no knowledge docs; drift test for `READ_PERMISSIONS`; concurrent-callers test; selector rule covers the new tests. **Rejected:** (a) a 404 on an operation with no id says "Not available for your organisation", not "Not found": that is the spec's own sentence about features that are off, and operations with an id answer "Not found". (b) A negative cache for bad tokens: the app is the throttle and each miss is one cheap call. (c) A body-size cap on `/mcp`: the SDK's session manager already caps requests at 4 MiB. |

The reviewer also noted that `/api/openapi.json` arrives with 8.2f. Until it merges,
`tests/mcp_server/test_integration.py` skips with that reason. It was run against the 8.2f branch
(9 passed) before this MR was opened.
