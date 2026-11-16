# Build review: public MCP 8.2e (Settings, AI assistants)

Reviewer: Claude code review (high effort), advisory. Codex out of quota until 17 Nov 2026.
Brief: admin-only controls server-side, CSRF, XSS via client names, revoke confirmation.

Result: no defects found on any of the five focus areas.

| Area | Finding | Disposition |
|---|---|---|
| Admin-only | `mcp.get_settings` / `update_settings` need `users.manage` in POLICY; template renders switch and roles only under `can_manage`; script binds admin handlers only then; grants list is own-only without `users.manage` | confirmed, nothing to fix |
| CSRF | `X-CSRFToken` sent on every non-GET from the page's script; dialog form never submits natively | confirmed |
| XSS | every untrusted string (client name, person, role label) set with `textContent`/`setAttribute`; e2e test shoots a hostile client name | confirmed |
| Revoke | two-step bottom sheet; server checks owner or `users.manage`, org-scoped, 404 otherwise | confirmed |
| Nit: copy button if `execCommand` throws | rejected: Copy is a convenience, the address is selected for manual copy; failing silently is acceptable | rejected |
| Nit: non-admin sees blocked note plus empty list | accepted as intended | no change |
| Reviewer asked to eyeball the legend spacing change | checked in screenshots | fine |
