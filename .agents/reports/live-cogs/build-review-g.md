# Build review: live-cogs 8.1g (advisory Codex review)

**Not run.** The review was launched with `agent_launch.py launch build-review --scope live-cogs-g`
(prompt: `build-review-g.prompt.md`, tab `w29:t3G`, 14 Nov 2026). Codex's session ended after one
second with `usage_limit_exceeded` ("try again at Nov 17th, 2026 8:49 AM"), so it produced no
findings. Nothing was fixed or rejected on its account.

The whole feature gets reviewed together at the end, and the prompt file is kept so the review can
be re-run against this diff once Codex is available again. Areas the prompt asks it to attack:
the stored-movement identity and `rounding`, as-at-cutoff quantity reconstruction, month-end
automation under concurrency, the bridge tie-out and P&L parsing, tenancy and CSV injection, and
the UI's handling of unknown cost.

Known limits the builder already accepts (see the MR description): manual snapshots are cut by
timestamp but compared with Xero by date; a lot's closing cost is the one known when the snapshot
is taken; a lot's movement kinds come from the entity-event and wastage ledgers, with anything they
don't explain landing in `variance`.
