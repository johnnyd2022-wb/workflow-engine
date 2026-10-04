# Session-signing secrets

Every environment requires a stable, private session-signing key. The application
rejects missing keys, keys shorter than 32 bytes, and the former public development
key. There is no development or test fallback, and keys are never generated during
app startup: every worker must use the same key.

`FLASK_SECRET_KEY` takes precedence in every environment. Local host runs fall back
to the Password field of the configured KeePassXC entry under `[app]`:

| Environment | `keepass_session_secret_entry` |
| --- | --- |
| Dev (`local`) | `workflow-engine/FLASK_SECRET_KEY_LOCAL` |
| Test | `workflow-engine/FLASK_SECRET_KEY_TEST` |

Keep independently generated random keys in those entries. The test Docker startup
scripts resolve the test entry on the host and inject `FLASK_SECRET_KEY`; containers
do not access the host KeePassXC database. CI deployments must supply a protected,
masked `FLASK_SECRET_KEY`. Production requires this environment variable too.
Never put key values in tracked config files or Docker images.

Rotating the key invalidates existing sessions, CSRF tokens and outstanding OAuth
flows. Users sign in again after rotation. Do not retain the old public key as a
fallback. Pytest uses a private ephemeral key shared within its process; it does not
need the real deployment secret.
