# Supply-chain security: two layers, two different jobs

This repo runs two dependency-scanning CI jobs that look similar but catch different
things. Neither replaces the other.

## `uv_audit` — known-vulnerability scanning (reactive)

Checks the locked dependency tree (`uv.lock`) against the OSV vulnerability database for
**already-published** CVEs and advisories. This is the same category of tool pip-audit
was (uv_audit replaced it — see `.agents/plans/repo-modernisation-plan.md` §1): it can
only flag a vulnerability once someone has found it, reported it, and it's been entered
into a database. That lag between disclosure and database entry is typically days to
weeks — during which a known-bad package looks completely clean to this scan.

Blocking (`allow_failure: false`): a real CVE in a resolved dependency stops the
pipeline. Findings route to the **dependency-update** skill.

## `socket_security` — supply-chain behaviour analysis (proactive)

Socket doesn't wait for a CVE. It inspects what a package's installed code *actually
does* — does a minor patch-version bump suddenly add network access, an install script,
obfuscated code, or telemetry that wasn't there before? That's the zero-day-relevant
signal: a compromised or malicious package is dangerous from the moment it's published,
not from the moment someone notices and files a CVE.

Diff-based: only alerts on issues newly introduced by the current commit/MR against the
repo's existing head scan, so it doesn't re-litigate the entire pre-existing dependency
tree on every merge request.

Soaking (`allow_failure: true` initially, same reasoning `pip_audit` started with):
behavioural heuristics can flag a legitimate package doing something unusual for
legitimate reasons — that's a judgement call, not a deterministic CVE match, so this
job needs a soak period before it blocks merges. Flip to blocking once that's clear.

## Why both, not one

| | `uv_audit` | `socket_security` |
|---|---|---|
| Catches | Known, published CVEs | Behavioural red flags, incl. zero-days |
| Data source | OSV database (community-reported) | Static/dynamic analysis of the actual package code |
| Timing | Only after disclosure + database entry | At publish time |
| False-positive risk | Near zero (it's a database match) | Non-zero (behaviour can be legitimate) |

A supply-chain attack (a maintainer account takeover, a malicious dependency
confusion package, a compromised build step) is exactly the case where `uv_audit` stays
silent — there's no CVE yet — and Socket is the only one of the two with a chance of
catching it before it ships.

## Socket pricing (as of this write-up, 2026-07)

Running on the **Free tier**: 1,000 scans/month, all 70+ behavioural risk-detection
categories — this covers everything described above at $0. Paid tiers exist for
capabilities this repo doesn't need yet:

- **Team** (~$20-25/seat/mo): adds reachability analysis (fewer false positives) + Slack alerts.
- **Business** (~$40-50/seat/mo): adds **SBOM generation** and **SSO/SAML**.

Upgrade trigger, not a default: move to Business only when a customer or compliance
requirement actually asks for an SBOM or SSO, not preemptively.
