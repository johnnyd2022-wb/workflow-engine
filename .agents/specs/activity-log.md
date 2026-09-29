# SPEC: activity-log
status: reviewed
name: Activity Log — event-sourced audit trail reader (story, summary, org activity feed)
slug: activity-log
blueprint: core_bp — routes in `app/features/activity_log/routes/activity_routes.py`
url_prefix: /api/core/entities

## Description

Reads back the append-only `entity_events` stream (written by the platform-layer
`EventWriter`, `app/core/backend/event_writer.py`, out of scope for this review) as
human-readable audit history. Three read surfaces:

- **Story**: full chronological event timeline for one entity (used when drilling into an
  inventory item's card — "Audit history").
- **Summary**: pre-computed per-entity summary (`entity_event_summaries`, upserted on every
  write) plus the 10 most recent raw events, for a detail-view card.
- **Activity feed**: org-wide, newest-first, filterable by entity type and date range —
  powers the sourcemap Activity tab.

All three share ~450 lines of diff-humanisation presentation logic (`_human_summary`,
`_event_diff_rows` → `_build_diff_rows`/`_smart_list_diff_rows`, `_fmt_field_value`,
`_fmt_sub_val`) that turns a raw `diff`/`payload` JSONB into a human sentence and structured
before/after rows, switched on `event_type`. This logic lives in the API layer, not a
service — flagged in the feature index as a extraction candidate, not fixed in this review
(Rule: don't refactor beyond what findings require).

A second historical audit format is blended into the `story` endpoint for inventory items
only: `_merge_inventory_legacy_audit` reads `InventoryItem.extra_data["inventory_audit_history"]`
(a JSON array stored directly on the item row, pre-dating event-sourcing) and interleaves
entries with no matching `entity_event` (matched by created_at within 10s) as synthetic
`inventory_item.legacy_entry` timeline items.

ASSUMPTION: No spec existed at `.agents/specs/activity-log.md` before this review. This spec
is reconstructed from `.agents/feature-index.md`'s `activity-log` block and the routes/models
as they exist on `review/activity-log` (cut from `main`) at review time (2026-08-09).

ASSUMPTION: A third historical format, the `audit_logs` SQL table (`AuditLog` model, written
via `app/core/utils/log_action.py` → `AuditRepository.write_log`), is written to on actions
like `org.settings_updated` (confirmed via `tests/test_org_routes.py`) but is **never read
back by any endpoint in this slice or elsewhere** — `AuditRepository.list_logs_for_org`
(the one properly tenancy-enforced reader) has zero callers in `app/`. The feature index's
note that `_merge_inventory_legacy_audit` "blends pre-event-sourcing AuditLog rows" is
inaccurate: it blends `extra_data.inventory_audit_history`, a different legacy format, not
`AuditLog` rows. Treated as a documentation-vs-reality gap to report, not a bug to fix —
whether `audit_logs` writes should be wired into a read path or retired is a product
decision out of this review's scope.

## Users & permissions
- roles: any authenticated user of the org. No `@requires_role` gate on any route in this
  surface — read access to audit history is not role-restricted.
- tenant_scoped: **no** — one confirmed gap (AC7 below). The other two routes correctly
  resolve `org_id = UUID(g.org_id)` from session-derived tenant-context middleware and filter
  every query by it.

## Routes

| Route | Method | Purpose |
|---|---|---|
| `/api/core/entities/<entity_type>/<entity_id>/story` | GET | Full event timeline for one entity |
| `/api/core/entities/<entity_type>/<entity_id>/summary` | GET | Pre-computed summary + 10 most recent events |
| `/api/core/entities/activity` | GET | Org-wide activity feed, filterable |

`entity_type` is validated against a fixed set: `inventory_item`, `execution`, `process`,
`user`, `org` (`_parse_entity_type`).

## Acceptance criteria

### Entity story — `GET /api/core/entities/<entity_type>/<entity_id>/story`
- AC1: An `entity_type` outside the valid set returns 400 `"Invalid entity_type"`.
- AC2: A non-UUID `entity_id` returns 400 `"Invalid entity_id"`, never a 500.
- AC3: Events are filtered by both `EntityEvent.org_id == caller's org` and
  `EntityEvent.entity_id == eid`, ordered oldest-first, paginated (`limit` capped at 500,
  default 200; `offset`). A cross-tenant `entity_id` returns an empty, valid `events: []`
  list — cross-org existence is not distinguishable from non-existence, same standard as
  the traceability slice's AC2.
- AC4: `total` reflects the same org+entity-scoped count, independent of pagination.
- AC5: Each event dict carries `summary` (`_human_summary`) and `diff_rows`
  (`_event_diff_rows`) alongside the raw fields.
- AC6: For `entity_type == "inventory_item"` only, legacy `extra_data.inventory_audit_history`
  entries are merged in via `_merge_inventory_legacy_audit`, itself org-scoped (`InventoryItem`
  looked up by `id == eid AND org_id == caller's org`) — a cross-tenant `eid` yields no item,
  so no legacy entries leak. `user_id` is always stripped from merged entries.
- AC-gap: `limit`/`offset` use a bare `int(request.args.get(...))` with no try/except — a
  non-numeric value (e.g. `?limit=abc`) raises an unhandled `ValueError`, propagating to an
  uncaught 500 (no global `ValueError`→400 handler is registered in `app_factory.py`). Same
  bug class as traceability's AC20/F3, fixed there by wrapping in try/except.

### Entity summary — `GET /api/core/entities/<entity_type>/<entity_id>/summary`
- AC7 **(confirmed cross-tenant leak — this review)**: The pre-computed summary lookup,
  `db.query(EntityEventSummary).filter(EntityEventSummary.entity_id == eid).first()`
  (`backend.py:5538`), has **no `org_id` filter**, while `eid` is parsed directly from the
  URL path with no ownership check anywhere in the route. `entity_id` is
  `entity_event_summaries`'s primary key (one row per entity, globally unique), so any
  authenticated user of any org who obtains another org's entity UUID gets that entity's
  full `summary` JSONB back, cross-tenant. Unlike the inventory-list enrichment case
  (`.agents/reports/inventory/review.md`, ruled non-exploitable because the ids it filtered
  on were already org-scoped upstream), `eid` here is fully attacker-controlled with zero
  upstream scoping — a live, confirmed BOLA/IDOR (CWE-639), not defense-in-depth.
  Severity is raised by `entity_type` including `user` and `org`: `_update_user_summary`
  puts `email`, `role`, `login_count`, `failed_login_count`, `last_login_at` in the summary;
  `_update_org_summary` puts `name`, `status`, `last_changed_by`. So the same bug leaks
  another org's user PII (email, login/failed-login counts) and org metadata, not just
  inventory data. The route has **zero frontend callers** (confirmed: no reference to this
  path anywhere under `app/*/frontend`) — live, authenticated, unreachable-by-design, exactly
  the "dead branch, still fix it" precedent from traceability AC10/F2. Fix: add
  `EntityEventSummary.org_id == org_id` to the filter, matching the second query in the same
  handler (`recent_events`, which is already correctly org-scoped).
- AC8: `recent_events` (the 10 most recent raw events) is correctly filtered by
  `EntityEvent.org_id == org_id AND EntityEvent.entity_id == eid` — only AC7's summary lookup
  is affected.
- AC9: `entity_type`/`entity_id` validation matches AC1/AC2.
- AC10: When no summary row exists for the entity, `summary` is `{}` (not a 404 — the route
  always returns 200 with whatever data exists, matching `entity_story`'s "no data" shape).

### Org activity feed — `GET /api/core/entities/activity`
- AC11: Events are filtered by `EntityEvent.org_id == caller's org` only — no
  cross-tenant gap.
- AC12: `entity_types` (comma-separated) restricts to that set when present; unknown values
  are silently ignored (no validation against `_parse_entity_type`'s valid set — an unknown
  type just matches zero rows, not an error).
- AC13: `from_date`/`to_date` (`YYYY-MM-DD`) filter `created_at` inclusive of the whole
  `to_date` day (`23:59:59`); a malformed date string is silently ignored (`except ValueError:
  pass`), not a 400 — inconsistent with AC1/AC2's strict validation elsewhere in this slice,
  but not a security issue, just a UX inconsistency worth naming.
- AC14: `total`/pagination (`limit` capped at 500, default 150; `offset`) match the org-scoped
  query, same shape as `entity_story`.
- AC-gap: same unhandled `int()` parse issue as AC-gap above, on `limit`/`offset`.

### Cross-cutting
- AC15: All three routes return 401 for an unauthenticated request (`@requires_auth`), before
  touching any org data.
- AC16: `_human_summary`/`_event_diff_rows` never raise on an unrecognized `event_type` —
  unknown types fall through to a generic `"type — subtype".replace("_", " ").capitalize()`
  rendering (`_human_summary`'s final line) rather than a `KeyError`/`AttributeError`.

## Non-goals / explicitly out of scope
- `EventWriter` (`app/core/backend/event_writer.py`) and everything under
  `app/core/utils/{emit_event,log_action}.py` — the write side, platform layer, per the
  feature index's "Writer down, reader up" split. `_upsert_summary` and its per-entity-type
  updaters are read here only to establish blast radius for AC7, not audited for their own
  correctness.
- `/api/core/sourcemap/*` (`sourcemap_objects`, `sourcemap_trace`) — traceability slice,
  already reviewed (`.agents/reports/traceability/review.md`), even though
  `sourcemap_trace`'s temporal branch calls this slice's `_human_summary`.
- `_dashboard_event_counts_by_day` (`backend.py:4433`) — dashboard slice's own direct query
  against `EntityEvent`, flagged in the feature index as dashboard's debt (bypasses a repo),
  not this slice's to fix; confirmed org-scoped as read during this review.
- The `audit_logs` table / `AuditRepository` dead-read-path gap (see ASSUMPTION above) —
  named as a finding, not remediated (product decision, not a bug fix).
