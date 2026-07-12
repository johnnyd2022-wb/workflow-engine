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

## Known limitation

Verified by static/import checks and `ruff`; a live round-trip against the test Postgres
instance could not be run in the environment this skill was built in (`host.docker.internal`
was unreachable from the sandbox — confirmed pre-existing and unrelated to this skill by
reproducing the same failure on an existing, previously-passing test). Run
`ENVIRONMENT=test uv run pytest tests/ -v` in a normal dev environment before relying on
`two_org_two_user` in a real feature build.

## Rules

- Never duplicate a factory. If you're about to write `Organisation(name=...)` or a
  local `create_org`/`create_user` helper in a test file, use the shared factory instead.
- Factories create through repositories, never bypass them — a factory that skips
  validation the app relies on produces tests that pass against data production could
  never actually contain.
- Teardown lives in the fixture, not scattered `finally` blocks in every test — delete
  in reverse dependency order (children before parents) to respect FK constraints.
