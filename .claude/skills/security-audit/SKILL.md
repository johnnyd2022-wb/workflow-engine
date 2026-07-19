---
name: security-audit
description: "Audit the Flask codebase (or one feature blueprint) for security vulnerabilities: run semgrep with Flask/OWASP plus custom repo rules, gitleaks, pip-audit, then hunt the class scanners miss, especially tenant isolation and missing auth. Findings don't stop at a report — this skill drives remediation to an MR (itself when scoped, via fix-bug/dependency-update when wider), through the normal adversarial verification. Use this skill whenever the user mentions security, vulnerabilities, semgrep, secrets, dependency CVEs, auth review, or tenant isolation, whenever new-feature or review-feature calls it after a build, or on a scheduled security sweep. Autonomous: opens at most one MR per finding class; the MR is the human gate."
---

# Security Audit

Two layers, and the order matters. Scanners (semgrep, gitleaks, pip-audit) catch known patterns deterministically; run them first and fix what they find. Then do the agent work scanners cannot: logic flaws, missing authorization, and tenant isolation, which in a multi-tenant B2B SaaS is the scariest bug class because a valid-looking query that forgets the org filter leaks customer data with zero scanner signal.

Every audit ends with a rule: when you find a vulnerability class by reading code, write a custom semgrep rule for it so the NEXT occurrence is caught by machine, not by hoping an agent reads carefully. That is how this skill compounds.

And every audit ends with **remediation, not a report**. A findings list nobody actions is a record of known-unfixed vulnerabilities — arguably worse than not looking, because it converts ignorance into documented negligence. Section 5 is not optional.

Read `.agents/autonomy.md`: this skill runs unattended, ships via MR, and never merges.

## 0. Scope and preflight

```bash
python3 scripts/preflight.py --json    # tools.absent tells you which scanners exist
```

If `semgrep` or `gitleaks` is absent, **say which layer didn't run** rather than reporting a clean scan. (`gitleaks` is not currently installed here — an audit that skips it has not checked for secrets, and must say so.) Pass `decisions.verification_mode` down to whatever you hand remediation to.

Called with a feature slug: audit `app/features/<slug>/` plus anything it imports or migrates. Called bare: audit the whole app. Read `.agents/specs/<slug>.md` if it exists; `External surfaces` and `tenant_scoped` tell you where to concentrate.

## 1. Scanner pass (deterministic layer)

```bash
mkdir -p .agents/reports/<slug>
semgrep --config p/python --config p/flask --config p/owasp-top-ten --config .semgrep/ \
  --json --output .agents/reports/<slug>/semgrep.json app/
gitleaks detect --no-banner --report-path .agents/reports/<slug>/gitleaks.json || true
uv pip install pip-audit && uv run pip-audit -f json -o .agents/reports/<slug>/pip-audit.json || true
```

Triage every finding into exactly one bucket:
- **fix**: real issue, patch it now
- **false-positive**: explain why in the report; suppress with a scoped `# nosemgrep: <rule-id>` comment plus justification, never a blanket ignore
- **accepted-risk**: needs user sign-off; do not self-approve

Never bulk-dismiss. A lazy triage is worse than no scan because it trains everyone to ignore the tool.

## 2. Manual pass (what scanners miss)

Work this checklist against the scoped code. For each item, look at actual code paths, not file names:

1. **Auth on every route.** Every route in the blueprint carries `@requires_auth` (`app/core/security/permissions.py`). List any bare route as a finding even if it "looks harmless"; today's health check is tomorrow's data endpoint. Note: `@requires_org_scope` exists but is barely used outside `org_routes.py` — org scoping is actually enforced by `tenant_context` middleware setting `g.current_org_id`/`g.org_id` before the route runs (see `.agents/conventions.md` §3). Don't flag its absence as a finding on its own; check that the middleware ran and the route actually reads the tenant id it set.
2. **Tenant isolation.** Every query touching tenant-scoped tables filters by the session's org/tenant ID, and object lookups use `(id, org_id)` not bare `id`. Cross-tenant access must return 404 (not 403, which confirms existence). Write at least one unit test per scoped model proving user in org A gets 404 for org B's record; these tests are the real guarantee. Use the **test-fixtures** skill's `two_org_two_user` fixture (`tests/conftest.py`) for the org-A/org-B pair rather than seeding your own — it's the single source other stages share too.
3. **Mass assignment.** Request JSON is loaded through an explicit schema/allowlist, never `Model(**request.json)` or looped `setattr`.
4. **Injection.** Raw SQL uses bound parameters; templates do not use `| safe` or `Markup()` on user input; `subprocess` never gets user input with `shell=True`; file paths from users go through safe join with traversal checks.
5. **SSRF and uploads.** User-supplied URLs are validated against an allowlist (scheme, host, no internal ranges). Uploads validate content type and size server-side and are stored outside the static root with generated names.
6. **Secrets and config.** No secrets in code or git history (gitleaks covers most); `SECRET_KEY` from env; cookies `Secure`, `HttpOnly`, `SameSite`; debug off outside dev.
7. **CSRF and CORS.** State-changing routes are CSRF-protected (or the API uses token auth consistently); CORS is not `*` with credentials.

## 3. Write the rules (compounding step — now an enforced loop)

For each manual finding whose pattern is mechanically recognizable, add a rule so the NEXT
occurrence is caught by machine. Finding-born rules live in **`.semgrep/rules/learned.yml`**
(not scattered), and each one ships with a **fixture pair** that proves it works — this is
the AER learning loop, and `scripts/rule_candidates.py` makes "prove it fires on the bug
and stays silent on the fix" a gate instead of a promise an agent skips at 3am.

Workflow:

```bash
# 1. scaffold the fixtures + get a rule template
python scripts/rule_candidates.py scaffold --id bize-<name> --lang python

# 2. fill in .semgrep/fixtures/bize-<name>/vulnerable.py (the real pre-patch shape)
#    and fixed.py (the patched shape), then paste the rule into .semgrep/rules/learned.yml
#    with its metadata block (born-from, finding, date, fixture)

# 3. prove it: FIRES on vulnerable, SILENT on fixed — exit 1 if not
python scripts/rule_candidates.py verify
```

A rule that never fired against the real bug is untested, and an untested rule is a false
sense of security. The `semgrep_learned_rules` CI job runs `verify` on every MR, so a
broken or over-matching learned rule blocks the pipeline. The worked seed to copy is
`bize-mass-assignment-from-request` (rule + fixtures already in the tree). Record the rule
you added under each finding's `rule_added:` line in the report (§4).

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

Patch `fix` items yourself when scoped to the audited feature; for architectural findings that ripple wider, route them per section 5 rather than refactoring half the app inside an audit.

## 5. Remediate to an MR (the step that makes this real)

Every `fix`-bucket finding gets routed. Which route depends on the finding, not on convenience:

| Finding class | Route | Why |
|---|---|---|
| Scoped to the audited feature, small patch | **fix it here**, with a test proving the hole is closed | you have the context; a round trip costs more than the fix |
| Tenant isolation / auth bypass / data leak | **fix-bug**, flagged as security | it needs a red-then-green repro test *first* — "org A can read org B's row" must fail before it passes, or the fix isn't proven |
| CVE / vulnerable or outdated package | **dependency-update** | it owns changelog reading, the bump, and the affected-chain rerun |
| Architectural (auth model, session design, a pattern repeated app-wide) | **escalate** — report with hypotheses, don't fix | this is a design decision; `.agents/autonomy.md`'s escalation ladder, not a 3am refactor |
| Secret in git history | **escalate immediately, and name the credential to rotate** | deletion doesn't unpublish it. Never paste the value into the report, MR, or commit message |

Invoke the target skill with the finding as its input:

```
symptom/finding: <F-id> <file:line> <one-line description>
evidence: <repro command, scanner rule id, or the query that leaks>
severity: <why this matters — what an attacker gets>
report: .agents/reports/<slug>/security.md
```

**The adversarial flow comes for free, and that's the point.** `fix-bug` and `dependency-update` both run their own verification chain, and inside Herdr with a Codex partner they route it through `herdr-multi-agent-collab` — so the Architect writes the security fix and the Breaker attacks it, in a pane that didn't write it. A security patch reviewed only by its author is the weakest link in this whole system; this is how it gets a hostile second reader without a human in the loop. Outside Herdr the same work happens via subagents. Don't re-derive which — preflight's `verification_mode` already said.

Then: **write the semgrep rule first, fix second** where the class is mechanically detectable (section 3). A rule that fires on the pre-patch code and goes silent after is a regression test for the vulnerability class, and it's the artifact that stops the same hole reappearing in the next feature.

Caps and honesty, per `.agents/autonomy.md`:

- **At most one MR per finding class per run.** Ten instances of a missing org filter is one MR ("scope these ten queries"), not ten. Unbounded MR generation on a schedule is how a security tool gets muted.
- Log every finding you did not action — with its bucket and why — to the report. A deferred finding is tracked debt; an unrecorded one is a lie of omission.
- Never mark a finding `false-positive` or `accepted-risk` to clear the board. `accepted-risk` needs a human; you may recommend it, not grant it.

## 6. Scheduled sweeps

Suited to a weekly routine (`/schedule`). A sweep run:

1. preflight → scanners → `.agents/reports/security-audit/<date>.md`
2. diffs against the previous sweep — **new** findings are the signal; a standing count that never moves is what people stop reading
3. remediates the top new finding class (one MR), logs the rest
4. reports the standing total honestly, including what it couldn't scan

The standing count matters: at the time of writing, a bare `semgrep --config=auto` over this repo reports **68 findings**, all pre-existing. It sat unread because nobody diffed the count. That is what a sweep is for.

The worked example — and the whole loop, including the ending an agent doesn't get to write — is `app/tls/app_cert.key` (`detected-private-key`), tracked since the initial commit, whose modulus matches `app/tls/app_cert.pem`: a **CloudFlare Origin Certificate** for `*.whistlebird.co.nz`, valid to Jan 2028. Escalated as `escalate + rotate` class. The owner then **accepted the risk and declined rotation** — correctly, on facts the audit hadn't weighed: the repo is private, unforked, single-member, so the key has never been disclosed and rotation would protect against nothing.

Three things that generalise from it:

- **`accepted-risk` is granted by a human, never taken by you.** The audit's job ended at handing over accurate facts. Recommending rotation was right; the owner overriding it was also right; an agent self-approving would have been wrong even though the outcome matches.
- **Check the blast radius before you price the severity.** "Private key in git" reads as critical until you learn the repo is private with one member. Report visibility, forks, and member count alongside any secret finding — severity without exposure is theatre, and an audit that cries critical at a non-exposure is an audit people stop reading.
- **Verify the owner's basis, not just their verdict.** The stated reason here ("self-generated local dev cert") was wrong — the SAN is the production domain and the issuer is CloudFlare's Origin CA. The decision survived the correction; the *conditions under which it should be revisited* only exist because someone checked. Record those conditions, and don't re-raise an accepted signature until one trips.

Full write-up, including what voids the acceptance: `.agents/reports/security-audit/2026-07-17-committed-origin-key.md`.

## Rules

- Honest verdicts only. `clean` means the checklist completed and scanners ran, not "probably fine". If something could not be checked (e.g. no DB available), list it under a `not_verified:` line.
- Never claim this makes prod invulnerable. Scanners catch known patterns; the tenant tests catch the query-logic class; novel logic flaws remain possible. Report in those terms.
- Secrets found in git history need rotation, not just deletion; tell the user which credential to rotate.
- This skill audits and patches; it does not weaken gates. Suppression comments require written justification in the report.
