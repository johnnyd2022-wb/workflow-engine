# Architecture Review Checklist (CTO / Software Architect)

Run before approving any consequential Biz-E design. Verdict = approve / approve-with-
conditions / rework.

## Correctness & fit
- [ ] Problem and constraints restated accurately.
- [ ] 2–3 options considered; chosen option justified.
- [ ] Simplest thing that could work for a small founder-led codebase.

## Security (non-negotiable)
- [ ] Every route and query scoped to `g.org_id` — no cross-tenant leakage.
- [ ] Authn/authz enforced on every new endpoint (role checks where needed).
- [ ] Secrets/tokens encrypted at rest in DB; **never** in session cookies.
- [ ] Session holds only non-sensitive IDs/names.
- [ ] TOTP/lockout behaviour unaffected or improved.
- [ ] File paths use `safe_join`; reject `..`, `/`, `\`.
- [ ] Env vars override config for credentials.

## Data & migrations
- [ ] Schema changes have constraints + indexes where needed.
- [ ] Alembic migration is reversible (rollback path exists).
- [ ] No destructive migration without a backup/rollback plan.

## Operability
- [ ] Failure modes identified; graceful degradation.
- [ ] Observability: logs/metrics to detect the failure modes.
- [ ] Rollback plan for the feature (flag / revert).

## Testing
- [ ] Test strategy defined (pytest integration coverage for the new paths).
- [ ] Multi-tenant isolation has a test.

## Output
- [ ] ADR written for the decision.
- [ ] Verdict + conditions + next actions (owner/date).
- [ ] Release gates handed to **Release Manager**; scope issues to **Biz-E PM**.
