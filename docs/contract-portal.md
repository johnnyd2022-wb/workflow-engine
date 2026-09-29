# Customer portal foundation (7.2e/f)

Staff open **Customer portal sharing** on a contract order. People managers create,
revoke and reissue invitations. Production recorders upload document copies and publish
order updates. Customers use their producer's sign-in link and see current and past
published orders for their customer account only. No existing order is published by
migration or on creation.

## Identity and session boundary

PortalPrincipal is a separate table: no staff User, role, organisation membership or
staff user_id is created. Matching a staff email does not link the identities. Google
portal sign-in is deferred until its verifier and trust policy are ready; there is no
staff-account resolver fallback.

Invitations have 256-bit random bearer tokens, stored only as SHA-256 hashes. They expire
in 72 hours, are locked and consumed once, and can be revoked. Reissuing revokes unused
invitations for the same customer/email. The link carries its token in a fragment; the
portal removes it from the browser URL immediately. No token appears in an event or
server request URL. Staff invitation output explicitly blocks/masks session replay.
No email is sent by this slice; staff provide the invite and sign-in links.

Invitation acceptance sets a bcrypt password (12 characters minimum, 72 UTF-8 bytes
maximum) and creates a fresh opaque session. The __Host-contract_portal_session cookie
is host-only, Secure, HttpOnly, SameSite=Strict, with path /. Only its hash is stored in
the database. Sessions expire after 12 hours or 30 minutes without activity. Login
rotates the cookie and revokes its predecessor; logout and staff access revocation
invalidate tokens server-side. Reinvitation of a revoked person cannot resurrect old
sessions. Customer deactivation is checked on every request.

Portal credentials are rejected before tenant resolution on every staff route, even
with a simultaneous staff cookie. Every authenticated portal route has requires_portal
and an explicit portal requirement in the central policy. Staff roles cannot satisfy
that requirement. The normal Flask session carries only CSRF state and a non-authorising
customer sign-in hint. A URL/customer header never grants access.

All writes, including invitation acceptance, login and logout, use Flask-WTF CSRF
protection. IP limits apply to sign-in, acceptance, logout and staff invitation creation;
five failed logins lock a principal for ten minutes in shared database state. IP limits
inherit the application's shared rate-limit storage configuration. Portal responses are
private/no-store; same-origin referrers preserve Flask-WTF's HTTPS check and do not leave
the origin.

## What customers see

Publishing creates a new immutable snapshot, with both writer and reader allowlists.
PostgreSQL guards prevent edits to published payloads or copied document content. An
order withdrawal hides the latest revision without falling back to an older one.
Document withdrawal immediately blocks downloads, including references in older updates.

The ten portal sections show: shared stage/step/progress, unavailable ready forecasts,
ordered product quantities with production/dispatch quantities unavailable, linked batch
IDs and explicitly shared bottling dates, shared ABV/spec with QC status unavailable,
materials and yield unavailable, delivery unavailable, selected documents, and approvals
and messages unavailable. Due dates are labelled requested due dates. ABV and progress
are producer-entered shared facts; automated milestones remain 7.2d.

Portal reads query publications by authenticated organisation AND customer. They never
serialize live execution_data, recipes, specification references, stock costs, CRM
contacts, other customers, staff audit events or arbitrary internal document paths.
Shared documents are dedicated copies (PDF/PNG/JPEG/plain text, up to 5 MB), opt-in per
published update, and served as attachments through the same order/customer checks.
No raw staff-file URL or remote URL is accepted.

## Delivery boundaries

contract_portal_001 initially follows contract_orders_001. It adds five portal tables,
indexes, an order/customer composite FK seam and immutability guards; no backfill.
Restack into the single sites/orders/planner migration chain before release. Downgrade
removes portal access and shared copies.

This is the read-only portal foundation. It does not complete 7.2: scheduler dates,
quantified fulfilment, customer stock ownership, duty/removal integration, derived
milestones, approvals/messages, reorders, notification delivery and org-to-org grants
remain separate work. Operational rollout follows the second-producer pilot.

## Verification

PostgreSQL tests cover one-use invites, revocation and session expiry, immutable shared
copies, foreign customer/organisation routes, CSRF and rate limits. A route walk rejects
portal credentials on every staff route, including simultaneous staff credentials.
`tests/e2e/test_contract_portal.py` exercises publishing, invitations, downloads and
sign-in/out at 390 px over real HTTPS with CSRF enabled; Chromium stays in the E2E suite.
