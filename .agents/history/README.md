# Historical-findings store — compounding review memory

Review skills used to start every run cold: re-surfacing findings a human already rejected
(which trains everyone to skim the report) and failing to notice when a fixed bug came
back. This store is their memory. Owned by `scripts/finding_history.py`.

`findings.jsonl` is append-only — do not hand-edit; append through the tool so signatures
and the verdict vocabulary stay consistent.

## The signature

Every finding is keyed by a stable, tool-agnostic 12-char signature:

```
sig = sha1( area | kind | normalised(evidence) )[:12]
```

- **area** — a path or feature slug, never a line number (so the signature survives code
  moving up and down the file)
- **kind** — the semgrep rule id or the vulnerability/defect class
- **evidence** — the offending snippet; normalisation lowercases, collapses whitespace,
  and masks numeric literals / uuids / addresses, so literal churn doesn't fork one
  finding into many

A variable *rename* deliberately produces a new signature — that's a real code change and
deserves a fresh look.

## Verdict vocabulary

| verdict | meaning | effect on next run |
|---|---|---|
| `confirmed` | a real defect, surfaced and actioned | `known-confirmed` — surface with prior context |
| `fixed` | confirmed and since patched | a reappearance decides `recurring` (regression) |
| `false-positive` | a human ruled it not a real issue | `suppress` — don't re-raise |
| `accepted-risk` | a human accepted it knowingly | `suppress` until conditions change |

**Suppression is only ever earned by a recorded human verdict.** A skill may record
`confirmed`/`fixed` itself, but `false-positive` and `accepted-risk` reflect a human call —
same rule as `.agents/autonomy.md`: an agent recommends accepted-risk, only a human grants
it. The **last** recorded verdict for a signature wins, so a re-review can overturn an
earlier call.

## How skills use it

```bash
# before surfacing a finding, ask what to do with it
python scripts/finding_history.py decide --area app/features/crm --kind sql-injection \
    --evidence 'session.execute(f"...")'
#   new | known-confirmed | recurring | suppress

# after ruling on it, record the verdict (feeds the next run and the metrics ledger)
python scripts/finding_history.py record --area app/features/crm --kind sql-injection \
    --evidence 'session.execute(f"...")' --verdict false-positive --skill security-audit \
    --ref '!123' --notes 'constant query, no user input'
```

`decide` returning `suppress` means the finding stays out of the report body (log it under
a "suppressed by prior verdict" line for auditability — a suppression that's invisible is a
lie of omission). `recurring` means surface it *loudly*: a regression is worse news than a
new finding.

This store is the accepted-vs-rejected signal behind the Phase 1 scorecard
(`.agents/metrics/`): a skill whose findings keep landing as `false-positive` is crying
wolf, and now that's measurable instead of anecdotal.
