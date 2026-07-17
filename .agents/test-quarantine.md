# Test Quarantine Registry

Owned by the **suite-warden** skill. Every test marked `pytest.mark.quarantined` must
have a row here. No row, no quarantine — a quarantined test with no registry entry is a
deleted test that still looks like it exists.

Quarantined tests are excluded from default runs (`addopts = "-m 'not quarantined'"` in
`pyproject.toml`) and run deliberately with:

```bash
uv run pytest -m quarantined
```

## Rules

- **Every row needs an expiry.** A quarantine without a date is a permanent hiding place.
- On expiry, suite-warden escalates it in the run report. It does not silently extend.
- A test passing 10/10 on a scheduled re-run comes out of quarantine.
- Quarantine is for **flaky or environment-broken** tests. A test that fails
  deterministically because the code is wrong is a bug: it goes to `fix-bug`, and the
  test stays red until the code is fixed. Never quarantine a real failure.
- Same test quarantined twice for the same cause → escalate as a design problem.

## Active quarantine

| test | quarantined | why | owner | expires | issue |
|---|---|---|---|---|---|
| _(none)_ | | | | | |

The suite currently needs no quarantine: the 30 live-server tests are **gated**, not
quarantined (`pytest.mark.live_server` — they run when a dev server is up and skip with a
reason when it isn't), which is a different and better mechanism. Quarantine is for tests
that misbehave on their own, not tests with an honest external dependency.

## Released from quarantine

| test | released | why it's trustworthy now |
|---|---|---|
| _(none yet)_ | | |
