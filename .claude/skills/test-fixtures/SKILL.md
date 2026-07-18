---
name: test-fixtures
description: "Owns the shared factory-boy factories and the seeded two-org/two-user tenant-isolation world that security-audit and e2e-playwright both assume exists. Single source of test data — add a factory here the moment a second test needs the same kind of row, instead of hand-rolling setup again. Use this skill when writing new tests that need an org/user/other seeded row, when a factory is missing, or when new-feature/review-feature/fix-bug need test data for a new model."
---

# Test Fixtures

Before this skill, every test file that needed an org or user redefined its own local
`db` fixture and hand-seeded rows with manual `try/finally` teardown
(`.agents/conventions.md` §6 has the evidence). That works but doesn't compound: the
tenant-isolation world `security-audit` and `e2e-playwright` both need — at least two
orgs, one user each, a "hostile neighbor" to prove queries can't cross — got reinvented
per file instead of shared. This skill is that single source.

Owns `tests/conftest.py` (session-scoped fixtures) and `tests/factories.py`
(factory-boy factories).

## What exists now

- `tests/conftest.py`: `db` fixture (per-test session, closed after) and
  `two_org_two_user` (seeds `org_a`/`org_b` + one user each, tears itself down). A local
  `db` fixture in an existing test file shadows the shared one — nothing had to change
  for old tests to keep passing.
- `tests/factories.py`: `OrganisationFactory`, `UserFactory`. Both wrap the repository
  pattern (`OrganisationRepository.create_org`, `UserRepository.create_user`) rather than
  constructing models directly, per `.agents/conventions.md` §2 — factory-made rows go
  through the same normalization/integrity path as the app.

## Adding a new factory

1. Check `tests/factories.py` first — a close-enough factory with an override
   (`UserFactory(org_id=org.id, role=UserRole.ADMIN)`) beats a new one.
2. New factories follow the same shape: `class Meta: model = <the ORM model>`, declare
   fields as `factory.Sequence`/`factory.Params`, override `_create` to call the
   relevant `<Name>Repository` method rather than `Model(**kwargs)`. If no repository
   method exists for what you need, that's a sign the repository is missing a method —
   add it there, not a bypass in the factory.
3. Anything that must be unique (email, name) uses `factory.Sequence`, never a fixed
   literal — parallel test runs and repeated calls within one test both need this.

## Adding a new seeded-world fixture

Follow `two_org_two_user`'s shape: build it from factories, `yield` a dict keyed by
role/name (not a bare tuple — `two_org_two_user["org_a"]` reads at the call site;
`fixture[0]` doesn't), and tear down everything it created in reverse dependency order
inside the fixture, not in the calling test. If a new fixture composes an existing one
(e.g. "two orgs plus a process in each"), take the existing fixture as a pytest
dependency rather than reseeding orgs/users again.

## Consumers

- **security-audit**: its tenant-isolation checklist item ("write at least one unit test
  per scoped model proving user in org A gets 404 for org B's record") uses
  `two_org_two_user` instead of seeding its own pair.
- **e2e-playwright**: its `tests/e2e/conftest.py` setup step ("seed fixtures: at least
  two orgs and one user per org") imports and reuses `two_org_two_user` /
  `OrganisationFactory`/`UserFactory` rather than redefining seed logic for the browser
  suite. Note for whoever bootstraps `tests/e2e/conftest.py` first: this repo's app
  factory is `create_app()` (no environment-string argument) and reads `ENVIRONMENT` from
  the process env — set `ENVIRONMENT=test` when booting the app under test, don't pass
  `create_app("testing")` as e2e-playwright's own SKILL.md example shows; that signature
  doesn't exist here.
- **new-feature / review-feature / fix-bug**: when a spec introduces a new model that
  other tests will need to seed, add its factory here as part of the build, not inline
  in the feature's own test file.
- **test-author**: the heaviest consumer — it writes core-flow and tenant-isolation tests
  and must use these factories and `two_org_two_user` rather than hand-seeding. When it
  finds no factory for a model it needs (e.g. inventory items, wastage rows, executions),
  the factory gets added here, not inline in the test it happened to be writing.

## Verified against the real test database

`two_org_two_user` round-trips for real: seeds two orgs with one user each, distinct ids,
correct `org_id` linkage, cleaned up after. Confirmed by running it against the test
Postgres on `localhost:8401`, not by import checks.

This section previously recorded a "known limitation" — that a live round-trip couldn't be
run because `host.docker.internal` was unreachable. That diagnosis was right about the
symptom and wrong about the cause, and it is worth knowing why, because the same trap is
still there for the next agent: `test.ini` targets `host.docker.internal` because the test
app runs **inside Docker**, so `ENVIRONMENT=test` from a host shell hangs. With
`ENVIRONMENT` unset the loader falls back to `local` (`app/utils/config_loader.py:16`),
whose ini points at the same test database on `localhost:8401`, and everything works. The
fixture was never broken; the command was. Run `python3 scripts/preflight.py` if a DB
connection ever looks unreachable again — its `test_db` check names this exact trap.

## Rules

- Never duplicate a factory. If you're about to write `Organisation(name=...)` or a
  local `create_org`/`create_user` helper in a test file, use the shared factory instead.
- Factories create through repositories, never bypass them — a factory that skips
  validation the app relies on produces tests that pass against data production could
  never actually contain.
- Teardown lives in the fixture, not scattered `finally` blocks in every test — delete
  in reverse dependency order (children before parents) to respect FK constraints.
