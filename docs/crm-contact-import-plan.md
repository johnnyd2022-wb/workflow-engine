# CRM contacts and notes import plan

## Current position

The Customers page already has **New customer**, a direct edit form, and API routes for local contacts. Each contact can optionally sync to Xero. This work makes bulk onboarding available beside that existing route; direct creation remains the default for one contact.

## Import choices

| Option | Fit | Decision |
| --- | --- | --- |
| Downloadable CSV template and upload | Works with Excel, Google Sheets, Xero exports and most old CRMs. Headers make required fields explicit. | Build now. Required `name`; optional first/last name, email, phone, postal address and one note per row. |
| Paste from spreadsheet | Fast for a short list; avoids saving another file. Tabs and line breaks from Excel/Sheets are predictable. | Build now, using the same preview and validation as CSV. |
| Guided column mapping for arbitrary CSV/XLSX | Useful for a CRM export with different headers; adds mapping ambiguity and spreadsheet parsing risks. | Next step after observing real customer source files. Save reusable mappings only after examples. |
| vCard (.vcf) upload | Useful for individual address books; weak for business notes, account relationships and multiple contacts per company. | Later, if customers ask for it. |
| Direct CRM integrations / scheduled sync | Good for ongoing migrations, but each provider has different identities, permissions and API limits. | Prioritise after a named provider and customer demand; use an explicit link/merge review. |
| Phone contact scan / AI document extraction | Could help one-off trade show cards, but recognition errors and consent make it unsuitable as an unattended bulk path. | Consider as a reviewed draft, not automatic import. |

## Release design

1. Put **Import customers** beside **New customer**. Download a header-only template with exact columns so an example contact cannot be imported accidentally. Also accept a pasted tab-separated table using the same headers.
2. Preview on the server before saving: count ready/problem rows, show row number, name and reason. The import action re-parses and rechecks the submitted data; a stale preview never authorises a write.
3. Treat name as the customer identity for this first release. Reject blank/duplicate names within the file and names already in the current organisation. Do not silently merge notes into an existing contact. Require the operator to resolve those rows deliberately.
4. Create valid rows as local Biz-E contacts with `sync_to_xero=False`, even when the Sales default is on. One optional note becomes a CRM note attached to that new contact. Do not import Xero IDs or overwrite contacts created by Xero.
5. Return created and rejected counts plus row errors. Keep files/text out of persistent storage; limit request size and row count. Respect `sales.record`, CSRF and tenant scope. The actor and source appear in audit events.
6. UI copy explains that importing a contact does not create a Xero contact. The operator can opt in to Xero sync on an individual customer after review.

## Acceptance

- A user with `sales.record` can create a customer directly and can download, preview and import the template or paste spreadsheet rows.
- Name is mandatory; invalid email/overlong fields/duplicate names and malformed headers produce actionable row or file errors.
- Valid contacts and notes belong only to the current org. A reader without `sales.record` cannot import.
- Preview does not write. Import revalidates, skips problem rows, and gives a truthful summary. Re-uploading the same file cannot duplicate names.
- Imported contacts remain local until a person chooses Xero sync.

## Follow-up discovery

Collect three anonymised real contact exports from potential users. Measure how often they contain multiple people per company, labels/tags, consent status, external IDs, addresses and dated notes. That evidence should drive column mapping, richer contact relationships and direct connectors.
