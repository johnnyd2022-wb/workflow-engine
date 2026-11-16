# Build review: public MCP 8.2h (OAuth security check)

Advisory Claude review (subagent, security brief: mix-up, open redirect via the return path, session
rotation, clickjacking, token leakage, login CSRF) over `git diff origin/main...HEAD`. Codex was not used
(possibly out of quota). Read-only review; tests were run by the builder.

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | Med | The cookie-size cap counted characters; non-ASCII text escapes to 6 bytes in the session JSON, so a crafted link could push the cookie past 4 KB and the browser would drop the login cookie | **Fixed.** The cap is on the serialised JSON (1800 bytes). Test: `test_ac42_the_size_cap_counts_the_escaped_bytes_of_non_ascii_text`. |
| 2 | Low | A pending request survived signup and was carried over by non-consuming rotations | **Fixed for signup** (cleared there). Rotations on failed sign-ins keep it on purpose, so a retry still returns. 15-minute expiry bounds the rest. |
| 3 | Low | The request is forgotten when the server builds the answer, not when the browser follows it | **Left.** A lost response means the person starts again from the assistant; no data is exposed. |
| 4 | Low | On a shared browser, a later sign-in within 15 minutes goes to an earlier visitor's consent page | **Accepted.** Consent still needs an explicit approve and the request is re-validated; no worse than linking `/oauth/authorize` directly. |

Checked and sound (reviewer): fixed authorize path with URL-encoded values (no open redirect); `iss` on
success, every error redirect and metadata; `carry_over` carries no auth data; logout clears the entry;
client-side guards on `next`; no new detached ORM objects.
