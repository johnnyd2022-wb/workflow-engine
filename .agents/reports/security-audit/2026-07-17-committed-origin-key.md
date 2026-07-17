# SECURITY ESCALATION: CloudFlare Origin private key committed to git

date: 2026-07-17
found_by: security-audit (incidental, during the skill-buildout that added §5 remediation)
class: secret-in-history → **escalate + rotate** (never patched by an agent)
verdict: findings-open — needs a human action an agent must not take

## Finding

`app/tls/app_cert.key` is a private key tracked in git. It is not a throwaway dev key.

Evidence (no secret material printed, per `.agents/autonomy.md`):

| check | result |
|---|---|
| `git ls-files app/tls/` | `app_cert.cer`, `app_cert.key`, `app_cert.pem` all tracked |
| `git check-ignore app/tls/app_cert.key` | not ignored |
| `semgrep --config=auto` | `detected-private-key` on that path |
| `openssl x509 -in app_cert.pem -subject` | `O = "CloudFlare, Inc.", OU = CloudFlare Origin CA, CN = CloudFlare Origin Certificate` |
| validity | `notBefore=Jan 14 08:27:00 2025 GMT` → `notAfter=Jan 14 08:27:00 2028 GMT` |
| key ↔ cert modulus (MD5 of modulus, not the key) | identical — `85bcd768e7ae4577aa2e075a12c5a9f5` — the committed key **is** that certificate's private key |
| `git log --follow app/tls/app_cert.key` | 3 commits, earliest `05aaee7 initial-app-storange-in-git` — present since the repo began |

## Why it matters

A CloudFlare Origin Certificate authenticates the **origin server to CloudFlare**. Whoever
holds this key can present itself as the legitimate origin for the domains the cert
covers, to anyone who trusts the CloudFlare Origin CA for that hostname. It is a live
production-shaped credential with ~18 months of validity remaining, readable by anyone
with repo access — including anyone who has ever cloned it.

Deleting the file does **not** fix this. The key is in git history, in every clone, and in
GitLab's stored objects. History rewriting also does not fix it: assume it is disclosed.

## Required action (human — an agent must not do these)

1. **Reissue the origin certificate at CloudFlare** and revoke the current one
   (CloudFlare dashboard → SSL/TLS → Origin Server → revoke + create new). This is the
   step that actually closes the exposure.
2. Install the new key on the origin **out of band** — not in git. It belongs in the
   deployment's secret store (this repo already has the KeePassXC pattern for local and
   env vars for CI, `app/utils/config_loader.py`).
3. Remove `app/tls/*.key` from the working tree and add it to `.gitignore`. Cosmetic
   relative to step 1, but it stops recurrence.
4. Decide on history: rewriting (`git filter-repo`) is optional once the key is revoked,
   and disruptive on a shared repo. Revocation is what matters.

## Notes and open questions for the human

- `ci/setup_server.sh:13-14` **generates a fresh self-signed cert** into these same paths,
  so CI does not depend on the committed key. Local dev (`app/app.py:173-174`,
  `app/main.py:20-21`, `app/cli/api.py:22-23`) reads whatever is at those paths and would
  work with a self-signed cert too.
- **Unverified, and the thing to check first:** whether the live deployment currently
  serves this exact key. If yes, step 1 is urgent and needs a coordinated swap. If the
  origin was reconfigured at some point and this key is stale, revoke it anyway — a
  disclosed unused key costs nothing to kill.
- Why an agent stops here: rotating a credential is irreversible, coordinated, and
  outside the repo. `.agents/autonomy.md` forbids it, and this report is the escalation
  path that policy prescribes.

## Not done

- No key material was printed, logged, or copied anywhere. The modulus MD5 above is a
  fingerprint used to prove key↔cert correspondence; it does not disclose the key.
- No file was deleted, no history rewritten, no `.gitignore` change made — all of that
  should follow the rotation, not precede it, or it just creates a false sense of closure.
