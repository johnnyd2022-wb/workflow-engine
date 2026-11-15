## What it delivers

Public MCP 8.2e: **Settings → AI assistants** (`/core/ai-assistants`), the UI over the 8.2b settings and grants API.

- **Access** card (admins only): the on/off switch ("Let people connect their own AI assistant (Claude, ChatGPT, …) to read this organisation's data"), off by default, and a checkbox per built-in and custom role, disabled while the switch is off. Explicit Save, enabled only when something changed.
- **Connected apps** (admins see every grant in the org; everyone else sees "Your connections", their own): client, "Unverified app" badge, person, connected and last-used dates, Revoke. Revoke asks in a bottom-sheet dialog.
- **How to connect**: the MCP URL with a copy button.
- A non-admin whose org has assistants off, or whose role isn't ticked, is told so (same wording as the consent page, shared `connect_block_reason`).
- Admin controls are never sent to non-admins (template) and the API refuses them (403). Untrusted strings use `textContent`.
- New Settings tab "AI assistants" for everyone; page registry, policy row (`SIGNED_IN`, session only).
- No migration.

## AC → test

| AC | Tests |
|---|---|
| AC33 | `tests/mcp_oauth/test_settings_page.py::test_ac33_*`; `tests/e2e/test_mcp_settings_browser.py::test_ac33_*` (off for a new org; roles + on saves, reload shows same state; off keeps roles; empty-roles hint; failed save keeps input) |
| AC34 | `test_settings_page.py::test_ac34_*`, `test_a_hostile_client_name_*`; e2e `test_ac34_*` (lists a grant, bottom-sheet revoke removes the row, cancel/Escape keeps it, hostile name as text, verified has no badge, empty and error states, member sees only own) |
| AC35 | e2e `test_ac35_*` at 375 px, light and dark, including the open sheet and a member view |

Also updated: `tests/e2e/test_settings_tabs.py` (tab row), page lists in `test_pages_render.py` and `test_mobile_page_audit.py`.

## Assumptions

- Page path `/core/ai-assistants`; tab visible to everyone.
- Turning the switch on does **not** pre-tick roles (spec: new org has no roles); the page says "Tick at least one role" until one is.
- Roles are kept when the switch is turned off, so turning it back on restores the same set.
- One explicit Save, not autosave.

## Review

Claude code review (high): no defects; details in `.agents/reports/public-mcp/build-review-mcp-settings.md`. One nit (copy fallback) rejected with reason there.

## Verification

tests/mcp_oauth, test_access_policy, test_page_registry, test_navigation: 545 passed (private DB). e2e `test_mcp_settings_browser.py`: 16 passed. ruff and semgrep clean. Full chain deliberately not run (reviewed at the end of the feature).

## Screenshots (desktop 1440, phone 390; light and dark)

![on-desktop](/uploads/63f5b8473e95c42d9d9dca8f2fbaa569/on-desktop.png)
![dark-desktop](/uploads/eac52217c55ad3a952b21af49625f624/dark-desktop.png)
![on-phone](/uploads/72bde2773b91f381ff054fb9e4bde4d6/on-phone.png)
![dark-phone](/uploads/92ad71d03f1c2252e6d7fb49b92b11b0/dark-phone.png)
![sheet-desktop](/uploads/f33f8622a3786b97cde5e6e673a869a6/sheet-desktop.png)
![sheet-phone](/uploads/a1345d8454593afe29238f56b6c73d56/sheet-phone.png)
![member-phone](/uploads/5bb116bc328ebd1ce13818db09d9e1e2/member-phone.png)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
