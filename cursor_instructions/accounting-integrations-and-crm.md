# Biz-e Xero Integration + Lightweight CRM Implementation Brief

## Objective

Design and implement a production-grade integration between the Biz-e platform and Xero that is robust enough for long-term maintenance and eventual submission to the Xero App Marketplace.

The implementation must prioritize:

- Clean architecture
- Reliability
- Security
- Observability
- Testability
- Idempotency
- Graceful error handling
- Marketplace-readiness
- Maintainability for future developers

The system should integrate tightly with Biz-e’s existing source-to-sale tracing workflows while introducing a lightweight CRM experience powered primarily by synchronized Xero data.

---

# High-Level Goals

## 1. Xero Integration

Implement a secure OAuth2 integration with Xero that allows Biz-e users to:

- Connect their Xero organization from `/integrations`
- Authorize via a simple one-click OAuth flow
- Sync customers (Contacts)
- Sync invoices
- Refresh and maintain tokens automatically
- Disconnect Xero cleanly
- Handle pagination and large datasets gracefully
- Handle revoked tokens and expired connections safely
- Support re-syncing and incremental syncs
- Maintain marketplace-quality UX and reliability

---

## 2. Lightweight CRM

Build a lightweight CRM interface using the existing `base_spa.html` template.

The CRM should:

- Present customer/contact records synced from Xero
- Allow browsing/searching/filtering customers
- Provide dedicated customer profile pages
- Show customer invoices
- Prepare the platform for future sales and workflow correlation features
- Ability to add notes, tasks and a way to view a schedule for tasks - a calendar type gantt chart style view that can be zoomed in daily, weekly, monthly would be neat
- Ability to see total sales for the month using invoice totals, breakdown totals per customer and see customers repeat purchase cadence to highlight potential churn and where to focus contact points - whatever else you think works here

This CRM is not intended to replace Xero — it is a Biz-e operational view optimized for source-to-sale tracing and workflow visibility.

---

## 3. Product Correlation / Matching System

Implement a flexible product matching layer that allows Biz-e workflow outputs to correlate against Xero invoice line items.

Example:

A Biz-e final product:

- `Whistlebird Wildflower Gin`

May need to map to multiple Xero invoice item descriptions such as:

- `Whistlebird Wildflower Gin 700ml`
- `Whistlebird Wildflower Gin Retail`
- `Whistlebird WF Gin`
- `Wildflower Gin Promo`
- `Wildflower Gin 44%`

This mapping system must support:

- One-to-many matching
- Many-to-one matching
- Manual overrides
- Editable mappings
- Historical persistence
- Future automation/scoring possibilities

The goal is to improve traceability between manufacturing workflows and downstream customer sales.

---

# Required Deliverables

The implementation process should begin with:

## Phase 1 — Planning

Claude should first:

1. Review the existing codebase architecture
2. Identify existing auth/session patterns
3. Identify current Flask blueprints/services/models
4. Identify existing frontend patterns and SPA conventions
5. Produce:
   - Technical implementation plan
   - Architecture proposal
   - Database schema proposal
   - API design proposal
   - UI flow proposal
   - Risk assessment
   - Testing strategy
   - Marketplace-readiness checklist

---

## Phase 2 — Execution Tracking

Claude should maintain:

- A running implementation checklist
- Progress tracking
- Notes on architectural decisions
- Notes on tradeoffs
- Migration notes
- Any deferred work
- Known technical debt

This should be continuously updated throughout implementation.

---

# Technical Requirements

## Stack Assumptions

Current stack includes:

- Flask backend
- Python services
- Existing SPA frontend using `base_spa.html`
- Existing auth/session framework
- SQLAlchemy
- Existing API architecture
- Existing observability patterns

Follow existing project conventions wherever sensible.

---

# Xero Integration Requirements

## OAuth2 Flow

Implement secure OAuth2 authorization flow:

### Requirements

- OAuth connect button on `/integrations`
- Redirect to Xero auth
- Callback handler
- Secure token storage
- Refresh token handling
- Token rotation handling
- Revoked token handling
- Graceful reconnect support

### Security

Must follow marketplace-grade practices:

- CSRF protection
- State validation
- Secure token encryption at rest
- No token leakage in logs
- Least privilege scopes
- Session safety
- Idempotent callbacks

---

# Xero Data Sync Requirements

## Customers / Contacts

Sync:

- Contact ID
- Name
- Email
- Phone
- Addresses
- Tax numbers where available
- Contact status
- Updated timestamps

Requirements:

- Pagination support
- Incremental sync support
- Rate limit awareness
- Retry handling
- Soft failure handling
- Duplicate prevention
- Sync timestamp tracking

---

## Invoices

Sync:

- Invoice metadata
- Invoice status
- Invoice totals
- Currency
- Due dates
- Line items
- Quantities
- Unit amounts
- Tracking categories where available

Requirements:

- Incremental syncs
- Pagination
- Line-item normalization
- Historical preservation
- Partial sync resilience

---

# Database Design Requirements

Design normalized models for:

- Xero tenants
- OAuth tokens
- Contacts/customers
- Invoices
- Invoice line items
- Product mappings
- Sync jobs
- Sync states
- Audit history where appropriate

Include:

- Foreign keys
- Indexing strategy
- Uniqueness constraints
- Soft-delete strategy if appropriate
- Multi-tenant readiness considerations

---

# CRM Requirements

## CRM Navigation

Add CRM area to SPA navigation.

Potential routes:

- `/crm`
- `/crm/customers`
- `/crm/customers/<id>`

---

## Customer List View

Requirements:

- Paginated customer list
- Search
- Sorting
- Status indicators
- Last sync indicators
- Loading/error states

Should use existing SPA patterns/components.

---

## Customer Profile View

Customer page should display:

### Customer Details

- Name
- Email
- Phone
- Address
- Xero status
- Last synced

### Invoice Section

- Invoice list
- Status
- Totals
- Invoice dates
- Invoice line items

### Product Correlation Section

Ability to:

- View matched products
- Add mappings
- Edit mappings
- Remove mappings
- Handle multiple mappings

---

# Product Matching System Requirements

## Matching Capabilities

Support:

- Exact matching
- Alias matching
- Manual mapping
- Multiple Xero line items → single Biz-e product
- Single Xero line item → multiple Biz-e products if needed later

---

## Matching UX

Need a usable admin workflow for:

- Searching products
- Searching Xero invoice line items
- Creating mappings
- Viewing mapping usage
- Editing mappings safely

---

## Future-Proofing

Design the system so future enhancements can include:

- AI-assisted matching
- Fuzzy matching
- Confidence scoring
- Auto-suggested mappings
- Workflow analytics
- Revenue analytics
- Batch operations

---

# API Requirements

Design clear internal APIs/services for:

- Xero auth
- Xero sync
- Contact retrieval
- Invoice retrieval
- Product matching
- CRM queries

Requirements:

- Separation of concerns
- Service-layer architecture
- Avoid fat Flask routes
- Clear DTOs/serialization boundaries
- Pagination support
- Idempotent sync operations

---

# Background Jobs / Syncing

Strongly consider async/background processing for:

- Large syncs
- Incremental syncs
- Token refreshes
- Reconciliation jobs

Requirements:

- Retry handling
- Visibility into failures
- Job logging
- Sync status visibility
- Idempotent re-runs

---

# Error Handling Requirements

The implementation must gracefully handle:

- Expired tokens
- Revoked permissions
- Xero outages
- Partial sync failures
- Pagination interruptions
- Rate limiting
- Invalid customer records
- Duplicate invoices
- Tenant disconnects

The UI should clearly communicate:

- Sync health
- Last sync status
- Reconnect requirements
- Failed operations

---

# Observability Requirements

Implement structured observability for:

- OAuth events
- Sync runs
- Sync durations
- API failures
- Pagination performance
- Rate limiting
- Retry counts
- Customer sync counts
- Invoice sync counts

Follow existing Datadog/logging conventions.

Avoid logging sensitive data.

---

# Marketplace Readiness Requirements

The implementation should be designed with Xero Marketplace expectations in mind.

This includes:

- Secure auth handling
- Stable reconnect flow
- Clear disconnect flow
- Data privacy awareness
- Reliable token management
- User-friendly authorization
- Graceful degradation
- Clear auditability
- Minimal required scopes
- Professional UX
- Robust documentation

Claude should identify:

- Additional marketplace requirements
- Missing compliance considerations
- Production hardening opportunities

---

# UI/UX Expectations

The UI should feel:

- Lightweight
- Fast
- Professional
- Operationally useful
- Consistent with existing SPA styling

Avoid overengineering frontend complexity.

Prefer pragmatic, maintainable interfaces.

---

# Testing Requirements

Comprehensive testing is required.

## Backend Tests

Cover:

- OAuth flow
- Token refresh
- Token expiry
- Revoked token handling
- Contact sync
- Invoice sync
- Pagination handling
- Retry behavior
- Mapping creation
- Mapping updates
- Disconnect flow
- Idempotency
- Duplicate prevention

---

## Frontend Tests

Cover:

- CRM navigation
- Customer loading
- Customer detail rendering
- Invoice rendering
- Mapping workflows
- Error states
- Empty states
- Loading states

---

## Integration Tests

Include:

- End-to-end Xero sync flow
- Mocked Xero API testing
- Multi-page sync testing
- Incremental sync testing
- Reconnect testing

---

# Performance Expectations

The system should scale reasonably for:

- Thousands of contacts
- Thousands of invoices
- Large invoice line-item datasets

Avoid:

- N+1 query patterns
- Full re-sync dependence
- Blocking UI operations

Implement sensible caching and batching where appropriate.

---

# Code Quality Expectations

The implementation should prioritize:

- Clean service boundaries
- Small focused functions
- Type hints where possible
- Consistent naming
- Strong comments where necessary
- Minimal technical debt
- Marketplace-grade professionalism

Avoid:

- God services
- Monolithic routes
- Tight frontend/backend coupling
- Hidden side effects
- Duplicate sync logic

---

# Documentation Requirements

Claude should maintain and/or generate:

- Architecture notes
- API documentation
- Sync flow documentation
- OAuth flow explanation
- Database schema notes
- Operational troubleshooting notes
- Future enhancement notes

---

# Suggested Implementation Order

1. Planning + architecture
2. Database schema
3. OAuth flow
4. Token persistence
5. Xero API client/service layer
6. Contact sync
7. Invoice sync
8. Incremental sync logic
9. CRM customer list UI
10. CRM customer profile UI
11. Product mapping system
12. Background jobs/retries
13. Observability
14. Testing hardening
15. Marketplace hardening/review

---

# Important Notes

- Prioritize maintainability over speed of implementation
- Favor explicitness over magic
- Keep integration boundaries clean
- Design for long-term extensibility
- Ensure graceful failure handling everywhere
- Assume eventual marketplace scrutiny/review
- Avoid introducing unnecessary framework complexity
- Reuse existing platform conventions wherever possible

Claude should continuously update implementation progress and maintain a living checklist/documentation trail throughout development.

REMEMBER TO USE OUR AUDIT LOGGING / TEMPORAL FUNCTIONALITY FOR THIS!!!