# Migrations — crm-contact-sync — 2026-10-16

| Revision | Tables | Destructive | up / down / up |
|---|---|---|---|
| `crm_contacts_created_in_bize_001` | `xero_contacts`: adds `source` (default `xero`), `sync_to_xero`, `xero_push_status`, `xero_push_error`, `xero_pushed_at`; `xero_contact_id` and `xero_tenant_id` become nullable; check `ck_xero_contacts_xero_id_unless_bize` keeps the Xero id required for rows from Xero | No (relaxes NOT NULL behind a check constraint) | Pass on scratch DB `scratch_crm_contact_sync` |
| `crm_contact_sync_default_001` | `crm_sales_traceability_config`: adds `sync_contacts_to_xero` (default false) | No | Pass |

Rehearsal: a Xero row survived up/down/up unchanged and read `source=xero` after upgrade; a
`bize` row without a Xero id was accepted and a `xero` row without one was refused by the
check. With a Biz-E-only row present, downgrade stopped with a message naming the count
instead of inventing ids or deleting rows; after removing it, downgrade restored NOT NULL and
dropped the columns.
