# Release {{version / date}} — Biz-E

## Release readiness — {{GO / NO-GO}}
| Check | Status | Notes |
|---|---|---|
| Tests green on release path | ✅/❌ | |
| Migration reversible + rollback plan | ✅/❌ | |
| Feature flags set | ✅/❌ | |
| Docs updated | ✅/❌ | |
| Monitoring can detect main failure mode | ✅/❌ | |
| CTO security/tenant gates met | ✅/❌ | |

**Blockers:** {{none / list}}

## Internal release notes (technical)
- {{change}} — MR !{{id}} — {{author}}
- Migrations: {{files}}
- Config/env changes: {{e.g. XERO_* vars}}

## Customer changelog (plain language — value, not diff)
> **{{Feature name}}** — {{what it lets the customer do and why it matters}}.

## Post-release watch (next 24–48h)
- [ ] {{metric / log to monitor}}

## Downstream handoffs (if customer-visible)
- → **Marketing Director:** brief stub — topic `{{feature}}`, audience `{{ICP}}`, key message
  `{{value}}`, channels `{{LinkedIn/newsletter}}`.
- → **Sales Manager:** enablement note — "{{one-line value}}; use in outreach to {{segment}}."
- → **Customer Success:** update onboarding/help for `{{feature}}`.
