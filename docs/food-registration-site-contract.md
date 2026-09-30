# Food registrations and site coverage

Food registrations belong to an organisation. Each registration records its programme
(NP1, NP2, NP3 or FCP), reference, registration date, optional end date and document
reference. One registration can explicitly cover manufacturing, storage or selling
at several sites. Site kind and address never imply coverage.

The database enforces organisation boundaries for both site coverage and verification
visits. Mutating APIs require `compliance.manage`, CSRF protection and authenticated
organisation scope. Creating a registration or coverage row commits its audit record
in the same transaction. Scope rows record documentary assertions; they do not verify
an external authority's registration.

National-programme visits, frequency progression and corrective actions are isolated
by registration. Recording a visit locks that registration before reading its latest
visit so simultaneous first visits cannot both claim the initial transition. Existing
visits remain in the unassigned organisation history: no migration guesses their
registration. Registration-scoped visits do not clear the organisation's legacy
booked-visit setting. Module alerts link to the relevant registration; the dashboard
milestone selects the earliest due registration.

FCP registrations and their site coverage can be recorded, but the NP frequency ladder
is not applied to them. Their verification automation still needs the appropriate
plan and verifier schedule. The register currently adds records and explicit coverage;
correction, revocation, historical scope changes and attachment storage remain future
work. Coverage is effective within the registration's recorded date range.

This MR does not activate multi-site operations or change stock movement authority.
Movement findings, replacement of the manual licensed-area flag, and per-CCA excise
accounting remain separate work under plan item 7.1.
