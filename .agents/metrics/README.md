# Skill metrics — the evaluation layer

This directory is the ledger that lets us answer *"is a skill worth its tokens?"* — the
AER evaluation-layer discipline, implemented as two append-only JSONL files and a
deterministic scorecard. No ML, no service; just written-down truth about what each skill
did and whether it stuck.

Owned by `scripts/skill_metrics.py`. Do not hand-edit these files — append through the
tool so the schema and enums stay honest.

## Files

| File | One line per… | Written by |
|---|---|---|
| `runs.jsonl` | skill run | the skill, when it finishes |
| `outcomes.jsonl` | resolved run/MR | whoever later sees the MR merged/closed/escaped |

A run and its outcome join on **`ref`** — the MR ref (`!123`) or the branch name. They are
written at different times by different agents, which is exactly why the store is
append-only: no run ever rewrites another's line.

## `runs.jsonl` schema

```json
{
  "ts": "2026-07-19T21:04:00+00:00",   // ISO-8601 UTC, set by the tool
  "skill": "security-audit",            // required
  "run_type": "chained",                // chained | scheduled | interactive
  "scope": "inventory",                 // feature slug or area, or null
  "findings": 3,                         // count opened this run (>= 0)
  "verdict": "patched",                 // clean | patched | findings-open |
                                         //   could-not-reproduce | error | skipped
  "ref": "feat/inventory",              // MR ref or branch — join key, or null
  "duration_s": 42.0,                    // wall time if known, else null
  "notes": null
}
```

## `outcomes.jsonl` schema

```json
{
  "ts": "2026-07-21T09:00:00+00:00",
  "ref": "!123",                         // required — matches a run's ref
  "outcome": "merged",                  // merged | closed | amended | escaped | superseded
  "skill": "security-audit",            // optional, for readability
  "notes": null
}
```

Outcome meanings:

- **merged** — the fix/feature shipped. The finding earned its keep.
- **closed** — the MR was rejected without merging. False positive / not worth it.
- **amended** — merged, but a human reworked the diff. Counts as accepted, tracked apart.
- **escaped** — a defect this skill *should* have caught reached prod (attributed later).
- **superseded** — replaced by a newer run before it resolved. Neither credit nor blame.

The **last-written** outcome per `ref` wins, so an MR closed then reopened-and-merged
scores as merged.

## How skills append (one line, no ceremony)

```bash
# on finishing a run
python scripts/skill_metrics.py record --skill security-audit --run-type chained \
    --scope inventory --findings 3 --verdict patched --ref feat/inventory --duration 42

# when the MR's fate is known
python scripts/skill_metrics.py outcome --ref '!123' --outcome merged
```

## Closing the loop automatically (`sweep`)

`outcome` above assumes a human remembers to record the MR's fate — and mostly nobody does,
which is why `outcomes.jsonl` used to sit near-empty while `runs.jsonl` grew. `sweep` closes
that gap: it asks **glab** what became of every ref that has a run but no outcome, and writes
`merged`/`closed` for the ones glab can prove.

```bash
python scripts/skill_metrics.py sweep             # write outcomes for resolved refs
python scripts/skill_metrics.py sweep --dry-run   # show what it would write, write nothing
```

It only writes what glab can prove (merged/closed). `amended` (a human reworked the diff)
and `escaped` (a prod defect blamed on a skill after the fact) are human judgments — the
sweep never manufactures them. A ref that was never an MR (a scheduled scope like
`security-audit/2026-07-17`) stays open, correctly: there is no MR for glab to judge.
Runs unattended-safe — no glab, or an unauthed/rate-limited one, means "resolve nothing",
never a crash. Best run on a schedule (see `.agents/autonomy.md` → Measure yourself).

## Reading it

```bash
python scripts/skill_metrics.py scorecard          # full human table
python scripts/skill_metrics.py scorecard --json    # machine-readable
python scripts/skill_metrics.py digest             # the few learnings worth reading each session
python scripts/skill_metrics.py digest --json       # machine-readable
python scripts/skill_metrics.py --check             # CI: exit 1 if malformed
```

`acceptance_rate = (merged + amended) / (merged + amended + closed)` — escaped and
superseded never enter the denominator. A skill with a low acceptance rate is crying wolf;
a skill with escaped defects missed something it owns. Both are signals for `skill-smith`
to improve or retire it.

The **digest** is the scorecard boiled down to only what a session should change behaviour
over — crying-wolf skills, escaped defects, and refs still awaiting an outcome. It is cheap
(reads the two JSONL files, no glab) and `preflight` surfaces it at the top of every code
workflow, so each session opens already knowing what the last ones learned.
