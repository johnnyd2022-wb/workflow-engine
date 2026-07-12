---
name: security-audit
description: "Audit the Flask codebase (or one feature blueprint) for security vulnerabilities: run semgrep with Flask/OWASP plus custom repo rules, gitleaks, pip-audit, then hunt the class scanners miss, especially tenant isolation and missing auth. Use this skill whenever the user mentions security, vulnerabilities, semgrep, secrets, dependency CVEs, auth review, or tenant isolation, and whenever new-feature or review-feature calls it after a build. Produces a report and patches; writes new semgrep rules so each finding class is caught deterministically next time."
---

# Security Audit

Two layers, and the order matters. Scanners (semgrep, gitleaks, pip-audit) catch known patterns deterministically; run them first and fix what they find. Then do the agent work scanners cannot: logic flaws, missing authorization, and tenant isolation, which in a multi-tenant B2B SaaS is the scariest bug class because a valid-looking query that forgets the org filter leaks customer data with zero scanner signal.

Every audit ends with a rule: when you find a vulnerability class by reading code, write a custom semgrep rule for it so the NEXT occurrence is caught by machine, not by hoping an agent reads carefully. That is how this skill compounds.

## 0. Scope

Called with a feature slug: audit `app/features/<slug>/` plus anything it imports or migrates. Called bare: audit the whole app. Read `.agents/specs/<slug>.md` if it exists; `External surfaces` and `tenant_scoped` tell you where to concentrate.

## 1. Scanner pass (deterministic layer)

```bash
mkdir -p .agents/reports/<slug>
semgrep --config p/python --config p/flask --config p/owasp-top-ten --config .semgrep/ \
  --json --output .agents/reports/<slug>/semgrep.json app/
gitleaks detect --no-banner --report-path .agents/reports/<slug>/gitleaks.json || true
pip-audit -r requirements.txt -f json -o .agents/reports/<slug>/pip-audit.json || true
```

Triage every finding into exactly one bucket:
- **fix**: real issue, patch it now
- **false-positive**: explain why in the report; suppress with a scoped `# nosemgrep: <rule-id>` comment plus justification, never a blanket ignore
- **accepted-risk**: needs user sign-off; do not self-approve

Never bulk-dismiss. A lazy triage is worse than no scan because it trains everyone to ignore the tool.

## 2. Manual pass (what scanners miss)

Work this checklist against the scoped code. For each item, look at actual code paths, not file names:

1. **Auth on every route.** Every route in the blueprint carries the auth decorator (e.g. `@login_required` or the repo's equivalent). List any bare route as a finding even if it "looks harmless"; today's health check is tomorrow's data endpoint.
2. **Tenant isolation.** Every query touching tenant-scoped tables filters by the session's org/tenant ID, and object lookups use `(id, org_id)` not bare `id`. Cross-tenant access must return 404 (not 403, which confirms existence). Write at least one unit test per scoped model proving user in org A gets 404 for org B's record; these tests are the real guarantee.
3. **Mass assignment.** Request JSON is loaded through an explicit schema/allowlist, never `Model(**request.json)` or looped `setattr`.
4. **Injection.** Raw SQL uses bound parameters; templates do not use `| safe` or `Markup()` on user input; `subprocess` never gets user input with `shell=True`; file paths from users go through safe join with traversal checks.
5. **SSRF and uploads.** User-supplied URLs are validated against an allowlist (scheme, host, no internal ranges). Uploads validate content type and size server-side and are stored outside the static root with generated names.
6. **Secrets and config.** No secrets in code or git history (gitleaks covers most); `SECRET_KEY` from env; cookies `Secure`, `HttpOnly`, `SameSite`; debug off outside dev.
7. **CSRF and CORS.** State-changing routes are CSRF-protected (or the API uses token auth consistently); CORS is not `*` with credentials.

## 3. Write the rules (compounding step)

For each manual finding whose pattern is mechanically recognizable, add a rule under `.semgrep/`. Example shape for the missing-org-filter class:

```yaml
rules:
  - id: bize-query-missing-org-scope
    languages: [python]
    severity: ERROR
    message: Query on tenant-scoped model without org filter. Use scoped helper.
    patterns:
      - pattern: $MODEL.query.get($ID)
      - metavariable-regex:
          metavariable: $MODEL
          regex: (Order|Customer|Invoice|WorkOrder)  # keep in sync with scoped models
```

Validate with `semgrep --validate --config .semgrep/`, and confirm the rule fires on the pre-patch code and stays silent after the fix. A rule that never fired against the real bug is untested.

## 4. Report and patch

Write `.agents/reports/<slug>/security.md`:

```markdown
# SECURITY: <slug>
date: <date>
verdict: clean | patched | findings-open
scanned: semgrep(<n> findings), gitleaks(<n>), pip-audit(<n>)
manual_checklist: 7/7 completed

## Findings
- F1 [fix|false-positive|accepted-risk] <file:line> <one-line description>
  repro/evidence: ...
  patch: <commit or diff summary>
  rule_added: .semgrep/<file>.yml#<rule-id> | none (why)

## Attempted but clean
- <what you probed that found nothing, so "clean" is auditable>
```

Patch `fix` items yourself when scoped to the audited feature; for architectural findings that ripple wider, report and hand back to the caller rather than refactoring half the app inside an audit.

## Rules

- Honest verdicts only. `clean` means the checklist completed and scanners ran, not "probably fine". If something could not be checked (e.g. no DB available), list it under a `not_verified:` line.
- Never claim this makes prod invulnerable. Scanners catch known patterns; the tenant tests catch the query-logic class; novel logic flaws remain possible. Report in those terms.
- Secrets found in git history need rotation, not just deletion; tell the user which credential to rotate.
- This skill audits and patches; it does not weaken gates. Suppression comments require written justification in the report.
