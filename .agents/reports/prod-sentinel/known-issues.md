# Prod Sentinel — Known Error Signatures

Owned by the **prod-sentinel** skill. Every error signature it has seen goes here,
actioned or not, so the next run doesn't re-triage what a previous run already
understood.

`scripts/error_scan.py --known <this file>` parses the **backticked 12-char fingerprint**
out of the table below and treats those signatures as already-known. Keep the format:
a fingerprint that isn't in a `| \`abc123def456\` |` cell is invisible to the deduper and
will be re-reported as new every run.

## Statuses

| status | meaning |
|---|---|
| `fix in flight` | an MR is open against it — check the MR, don't re-triage |
| `fixed` | merged; if it reappears, that's a regression and gets a NEW row |
| `accepted` | known and tolerated, with a written reason and a review date |
| `deferred` | logged but not actioned (one-MR-per-run cap); candidate for next run |

## Active signatures

| fingerprint | first seen | count | signature | status | issue |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

No signatures recorded: production is not currently exporting telemetry
(`grafana_data_enabled = false` in `app/config/prod.ini`, and its collector endpoint is
still the `localhost:4317` placeholder), so prod-sentinel has had no source to scan. This
table fills in once prod telemetry is wired, or immediately if the skill is pointed at a
JSON log file with `--source file --path`.

## Resolved

| fingerprint | resolved | how |
|---|---|---|
| _(none yet)_ | | |
