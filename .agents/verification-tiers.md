# Risk-tiered verification (the lean flow)

The contract for the **lean-change** front door. It runs *alongside* the original chain
(`.agents/verification-chain.md`), which is unchanged and still what `/new-feature`, `/fix-bug`
and `/review-feature` run when named. `/entrypoint` sends unnamed code requests here while
`.agents/workflow-mode.json` says `"mode": "lean"`. Set it to `"classic"` to go back.

Source: the !671 proposal and research, adjusted by its review (MR note on !671).

## 1. Pick the tier before building, and say why

```bash
python3 scripts/risk_tier.py --base origin/main      # the floor, from paths and added lines
```

The script sets the **minimum**; you may always go higher, never lower. Re-run it on the final
diff: if the floor rose while you built, the work moves up a tier before review.

| Tier | Typically | Must do | Review |
|---|---|---|---|
| **A** mechanical | Docs, copy, CSS-only, images | Read your own diff; formatters/link checks that apply; CI as usual | Author check. No separate model. |
| **B** ordinary | A bounded behaviour change outside the Tier C list | Acceptance checks, the relevant PostgreSQL tests, a regression test for a bug, lint/scanners for touched files, a browser check if UI behaviour changed, CI | **One** independent consolidated review (`.agents/templates/lean-review.md`) |
| **C** high risk | Auth/roles, `org_id` scope, inventory quantities/units/lineage, money and compliance maths (excise, invoices, wine claims, export register, holds, recalls), locking, migrations, public ingest, CI/deploy/config, dependencies | Tier B, plus explicit attack/invariant tests for the risk the script named, `migration-safety` on a private DB for migrations, the wider dependent suite when shared code changed | One independent **deep** review. Add a specialist (`security-audit`, `perf-guardrails`, …) only for a named gap. |

An unknown blast radius is B until inspected. A small change to a tenant-scoped query is still C.

## 2. What never changes, whatever the tier

- No weakened assertions or scanners to get green; no fabricated results; no production writes as a test.
- The agent never accepts a security risk on the founder's behalf.
- One writer per checkout. Merge and deploy follow the existing authorisation rules.
- Skipped, blocked and no-tests are reported as exactly that (`scripts/receipt.py` records it).
- Repro-test-first for a reproducible bug stays the norm.

## 3. The flow

1. **Tier** (above), recorded in the handoff.
2. **Build** with one implementer. Write the failing test first for a bug.
3. **Check** with receipts, so evidence is tied to the tree it ran on:
   `python3 scripts/receipt.py run --name unit -- <test command>`; `receipt.py status` before review.
4. **Review** (B and C): send `.agents/templates/lean-review.md`, filled in, to **one** reviewer:
   - preferred: the other provider (Codex), read-only, medium effort for B and high for C;
   - if that pool is out of quota: an **independent agent of the same provider that didn't write
     the diff** (another Claude pane), and say so in the MR. Never the author reviewing itself.
   The review is consolidated: correctness, test adequacy (would the tests fail if the code
   broke?) and tenant/data boundaries, in one pass, ranked by impact.
5. **Fix and re-review only the fixes** and their blast radius. Stop after 3 rounds and list what's
   left in the MR (the existing two- and three-round rules still apply).
6. **MR** through `merge-request`, with the tier, its reasons, the receipts and the reviewer named.
7. **Record** the run for the trial:
   `python3 scripts/skill_metrics.py record --skill lean-change --run-type interactive --verdict patched --ref '!<n>' --findings <n> --duration <s> --notes "workflow=lean kind=bug tier=B rounds=1 reviewer=codex"`.

Browser tests run when rendering or interaction changed; perf when query counts or data size
plausibly changed; observability when the change needs a new signal. None is automatic.

## 4. Handoff

Use `.agents/templates/handoff.md`: one page, the facts a reviewer or the next session needs,
not a transcript.

## 5. Measuring it

`python3 scripts/workflow_trial.py` compares lean and classic runs from the metrics ledger (bize_dev):
runs, review rounds, findings, outcomes and elapsed time by tier. Keep the lean flow if it
matches classic on acceptance and required checks with less effort; otherwise flip the switch.
