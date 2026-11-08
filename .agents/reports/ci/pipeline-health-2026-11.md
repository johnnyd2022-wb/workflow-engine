# Pipeline health — why pipelines go red (2026-11-06)

Board task: PIPELINE-HEALTH. Data: the last 100 MRs (!523–!622, 380 MR pipelines,
2026-10-13 → 11-06) and the last 200 main pipelines (2026-09-29 → 11-06), with every failed
job's trace tail. All of it is in bize_dev, schema `ci`:

```bash
python3 scripts/ci_health.py refresh            # re-pull from GitLab, classify, store (~6 min)
python3 scripts/ci_health.py refresh --offline  # reclassify stored traces after a rule change
python3 scripts/ci_health.py report             # the cause table below
wb sql "SELECT * FROM ci.cause_summary"         # same, as SQL
```

`ci.pipelines`, `ci.failed_jobs` (with `cause`, `detail` = failing test ids or the telling
line, and `trace_tail`), `ci.pipeline_blocked` (each pipeline → next green on the same
MR/ref), `ci.cause_summary`. "Blocked hours" = pipeline creation → next green pipeline for the
same MR (or main), capped at 24 h; a pipeline with two causes counts under both.

## Headline

- **MRs: 82 red pipelines with job data. 49 (60%) failed only on causes outside the MR**: main
  mid-pipeline, main already red, or a newly published advisory. **27 (33%) failed only on the
  two gates fixed here** (!623, !626), so they would have been green.
- **main: 55 of 181 finished pipelines red.** 42 of those came from the two-day CD bootstrap
  (2026-09-29/30, already fixed). Since 2026-10-16: **13 of 81 red (16%)**. Every red main
  then fails `main_green` on every MR, so main's reds multiply.

## Cause table

| cause | jobs | pipelines | main | MRs | blocked h | seen | status |
|---|---:|---:|---:|---:|---:|---|---|
| `deploy_bootstrap` — rollback to `:test-stable` before one existed | 32 | 31 | 31 | 0 | 320 | 09-29..09-30 | one-off, fixed |
| `new_advisory` — uv_audit on a freshly published CVE | 33 | 32 | 2 | 17 | 239 | 10-20..11-02 | **fixed: !626** |
| `ci_bootstrap` — `pip: command not found` in cd_e2e | 17 | 17 | 17 | 0 | 239 | 09-29..09-30 | one-off, fixed |
| `main_red_inherited` — MR red because main was red (main_green, or the same test failing on main within 3 days) | 34 | 28 | 0 | 14 | 156 | 10-17..10-28 | reduced: !625, !624; see remaining |
| `test_failure` — real unit/integration failures | 13 | 13 | 5 | 7 | 86 | 10-05..11-06 | CI doing its job |
| `ci_env_db` — test DB :8401 refused in cd_e2e | 14 | 14 | 14 | 0 | 82 | 09-30 | one-off, fixed |
| `stale_main_gate` — main_green while main was **running** | 27 | 25 | 0 | 18 | 53 | 10-16..11-06 | **fixed: !623** |
| `e2e_assertion` — E2E failing (e.g. !612 sales overview) | 7 | 5 | 1 | 1 | 52 | 10-17..11-06 | FIX-SALES-E2E (Codex) |
| `selection_stale_nodeid` / `no_tests_collected` — relevant_tests collected nothing: a TIA-selected node id the MR renamed or removed (!598, !600), or an id split on spaces (!542, fixed by f2b9564a) | 8 | 7 | 0 | 3 | 36 | 10-19..10-27 | fixed: f2b9564a (spaces), 810f3d2f (stale ids, 10-28) |
| `xdist_collection_mismatch` — workers collected different tests (!586) | 1 | 1 | 0 | 1 | 0.3 | 10-26 | one-off |
| `timeout` — `test_cutover_failures…` subprocess timeouts | 3 | 3 | 0 | 3 | 25 | 11-02 | fixed: !616 |
| `terraform_review_gate` — apply refused on changed/unapproved plan | 6 | 4 | 4 | 0 | 25 | 10-09..10-17 | by design |
| `ci_image_missing` — `CI_IMAGE_TAG` image not built yet | 7 | 1 | 0 | 1 | 24 | 11-02 | see remaining |
| `deploy_env` — missing docker network / container name in use | 7 | 7 | 7 | 0 | 21 | 09-30..10-27 | mostly one-off |
| `deploy_not_ready` — smoke hit :8001 before the app listened | 3 | 3 | 3 | 0 | 3 | 09-30..10-25 | see remaining |
| `lint_format` — one unformatted file, same file in 5 MRs on 10-24 | 6 | 6 | 0 | 5 | 2 | 10-24 | inherited from main |
| `third_party_fonts` — Google Fonts `ERR_NETWORK_CHANGED` in cd_e2e | 3 | 3 | 3 | 0 | 0.4* | 10-27..11-06 | **fixed: !625** (architect) |
| `security_gate`, `shared_db_migration_drift`, `unclassified` | 7 | 6 | 3 | 3 | 6 | | small |

\* The fonts flake's own blocked hours look small because main went green on the next merge.
Its real cost is in `main_red_inherited`: every MR whose pipeline ran while main was red from
it failed main_green.

Ranked by recurring cost (excluding the 09-29/30 bootstrap): **new advisories → inherited
red main → main_green on a busy main → real failures → E2E rot / CI-only E2E.**

## What was fixed (one MR each)

| MR | fix | cause it removes |
|---|---|---|
| !623 | `main_green` judges main by its **newest finished** pipeline. When head is running or not created yet, it walks back up to 10 first parents. A red/cancelled finished pipeline still blocks, `fixes-main` still passes, and it fails closed. | `stale_main_gate` (27 jobs, 18 MRs) |
| !626 | `uv_audit` on an MR also audits the target branch's lockfile at the diff base. Advisories **already on main** are a warning (exit 3); advisories the MR **introduces** still block; an unauditable base fails closed. main stays fully blocking. | `new_advisory` on MRs (31 of 33 jobs, 17 MRs) |
| !624 | `nightly_e2e`: the whole `tests/e2e/` (80 files) on a nightly schedule against main. The deploy chain opts out of that pipeline, and a test pins it. Warn-only until its first green run. | E2E rot found only when an unrelated MR touches it (the !612 pattern) |
| `ci_health` MR (this report) | `scripts/ci_health.py` + `ci` schema: the data and classifier, re-runnable. | makes the next round measurable |
| !625 (architect-claude) | Self-host Roboto + Momo Trust Display. | `third_party_fonts`, and the main reds it caused |

## Decisions made

- **Data in Postgres, not git** (`bize_dev.ci`), so reruns never conflict and anyone can
  query it. The classifier is ordered regexes with a post-pass for "the same test failed on
  main within 3 days" → `main_red_inherited`. Unmatched jobs stay `unclassified` and show
  in the table instead of being counted as real bugs.
- **No merge trains / merged-results pipelines**: the namespace is on GitLab **Free**, which
  has neither. See the remaining items for the free-tier substitute.
- **main's uv_audit stays blocking** (founder decision). Only the MR fan-out changed.
- **nightly_e2e is warn-only at first.** While it runs, the schedule pipeline is main's head
  pipeline, so a red first run would block every MR through main_green.
- **Didn't touch `~/.local/bin/mr-train`** (architect-claude's). The recommendation below is
  for them.

## What remains

1. **Inherited red main / semantic conflicts (biggest remaining).** Two MRs are each green,
   and main goes red once both land (e.g. `test_config_production_secrets` 10-27,
   `test_staff_site_roles` 10-05 and 10-28, the 10-24 ruff file). Free tier has no
   merged-results pipelines. Substitute for **mr-train**: before merging, if
   `origin/main` has moved since the MR pipeline's base (`diff_refs.base_sha` ≠ main head),
   rebase and re-run, or at least re-run `relevant_tests`, then merge. Merges are already
   serial, so that closes the window. *(For architect-claude: w29:p1 owns mr-train.)*
2. **CI_IMAGE_TAG drift / missing image.** On 11-02 an MR pointed at a CI image main hadn't
   built yet (7 jobs). `ci_image_current` warns on every MR until someone bumps the tag
   (!620). A self-updating option: main's `ci_image_build` opens a one-line bump MR labelled
   `ci::fast` when the hash changes, so the tag never drifts silently. Not done here, to keep
   CI token scope unchanged (that needs a project access token with `api`).
3. **cd_e2e started before the deployed app listened** (`deploy_not_ready`, 3 main reds).
   `deploy_test` should wait on the health endpoint before `cd_e2e` starts. Small; recent
   deploy-script MRs (!616) touch this area, so it's left to whoever owns deploy next.
4. **Flip `nightly_e2e` to blocking** after its first green run (SUITE-GREEN).
5. ~~Long e2e traces~~ **Corrected (2026-11-07):** those 9 "unreadable" jobs weren't truncated.
   pytest collected nothing: a TIA-selected node id that the MR had renamed or removed
   (`ERROR: not found: tests/test_sites.py::test_default_cannot_change…`), an id split on
   spaces (fixed by f2b9564a), and one xdist collection mismatch. `ci_health` now keeps each
   job's FAILED/collection-error lines and pytest summary from the whole trace
   (`ci.failed_jobs.failed_lines`) and names these causes. The stale-id case was already
   fixed by 810f3d2f (10-28): TIA runs a changed test module whole instead of its recorded ids.
6. **Re-run this monthly**: `python3 scripts/ci_health.py refresh`, then compare the table.

## Known examples from the brief, mapped

- main cd_e2e Google Fonts `ERR_NETWORK_CHANGED` → `third_party_fonts`, fixed by !625.
- main unit_tests ui_shots sync Playwright in asyncio → `e2e_assertion`/`test_failure` 11-06, fixed by !622.
- MR main_green fails while main mid-pipeline → `stale_main_gate`, fixed by !623.
- !612 sales overview E2E CI-only → `e2e_assertion`; FIX-SALES-E2E (Codex) owns it.
- ci_image_current stale tag → allow_failure, so it never turned a pipeline red. The real
  cost was 11-02's missing image; see remaining item 2.
- findings-sweep MRs conflicting → 8 of the 100 MRs. 5 red pipelines among them: 4 had
  `new_advisory` (one of them also `main_red_inherited`), 1 a TIA-selected test id that no longer existed. None was a merge
  conflict, so their cost is review churn and re-fixing (memory: check open MRs for the
  finding id first), not red CI.
