# SECURITY: CloudFlare Origin private key committed to git — ACCEPTED RISK

date: 2026-07-17
found_by: security-audit (incidental, during the skill-buildout that added §5 remediation)
class: secret-in-history
verdict: **accepted-risk** — signed off by the repo owner (johnny), 2026-07-17
review_by: on any change to the conditions below, else before the cert expires 2028-01-14

## Decision

The owner has accepted this risk and declined rotation. That is a human call, correctly
made by a human: `.agents/autonomy.md` forbids an agent from granting `accepted-risk` or
rotating a credential. No further action — do **not** re-raise this signature on future
sweeps unless a condition below changes.

**Owner's stated basis was that this is a self-generated local dev cert. That is not what
it is** (see Findings). The decision still holds on the risk math, but for a different
reason than the one given — which is why the real conditions are written down below
rather than left implicit.

## Why the risk is low *today*

| Factor | State |
|---|---|
| Repo visibility | **private** (`glab api projects/:id` → `visibility: private`) |
| Forks | **0** |
| Members with access | **1** (`johnny105` — the owner) |

Nobody but the owner holds the key. There is no disclosure to remediate. Rotation would
protect against an exposure that has not occurred.

## Findings (the facts, since the basis was mistaken)

Evidence, no secret material printed:

| check | result |
|---|---|
| `git ls-files app/tls/` | `app_cert.cer`, `app_cert.key`, `app_cert.pem` tracked |
| `git check-ignore app/tls/app_cert.key` | not ignored |
| `semgrep --config=auto` | `detected-private-key` |
| issuer | `O = "CloudFlare, Inc.", OU = CloudFlare Origin SSL Certificate Authority` |
| subject | `CN = CloudFlare Origin Certificate` |
| **SAN** | **`DNS:*.whistlebird.co.nz, DNS:whistlebird.co.nz`** — the live domain, not `localhost` |
| validity | `Jan 14 2025` → **`Jan 14 2028`** |
| key ↔ cert modulus (MD5 of modulus) | identical (`85bcd768…`) — the committed key is that certificate's private key |
| history | 3 commits, earliest `05aaee7 initial-app-storange-in-git` |

Two corrections to the record, because they change *when* this should be revisited:

1. **It was not self-generated.** CloudFlare Origin certificates are issued by CloudFlare
   (dashboard → SSL/TLS → Origin Server). This one is a wildcard for the production zone.
2. **It cannot be what silences Chrome on localhost.** Chrome does not trust the
   CloudFlare Origin CA, and the cert's SAN does not cover `localhost` — it would fail
   on both trust *and* hostname. `app/app.py:173-174` does load it for local HTTPS, so
   the warning is presumably being clicked through.

## Conditions that void this acceptance

Re-raise immediately if any becomes true — the key stays valid until **2028-01-14**:

- The repo gains **any** additional member, or is forked.
- The repo becomes **public** or is mirrored anywhere.
- A clone, backup, or CI artifact containing it leaves the owner's control.
- The key is deployed to, or reused by, the live origin (see open question).

## Open question (not blocking, worth knowing)

Whether the live origin currently serves this same key. If yes, an exposure would be
directly usable to impersonate the origin to CloudFlare for `*.whistlebird.co.nz`; if the
origin was reconfigured at some point, this copy is stale and the acceptance is even safer.
Nobody has checked. `ci/setup_server.sh:13-14` generates its own self-signed cert, so CI
does not depend on this key.

## Zero-effort alternative, if ever wanted

Local HTTPS is the only thing in this repo using it (`app/app.py:173-174`,
`app/main.py:20-21`, `app/cli/api.py:22-23`). A self-signed `localhost` cert would serve
that purpose *better* — correct hostname, no production credential involved — and
`ci/setup_server.sh` already contains the openssl invocation that generates one. Noted as
an option, not a recommendation to action; the owner has decided.
