# Tastings browser verification

20 new real-browser cases in `tests/e2e/test_tastings_page.py` on private PostgreSQL `workflow-engine-test_tastings_build`. Chromium, real Flask HTTPS server, subscribed org and production templates/scripts. Host `TZ=UTC`; event dates remain Pacific/Auckland. No third-party integrations invoked.

- Desktop and390px phone: book after searching stock before choosing people, one whole700mL bottle, confirm physical dispatch, record150mL sampled and15 samples, assert550mL in the exact returned pool lot, then open reuse from that lot.
- Shared Sales calendar opens the linked tasting; in-app boosted revisit and actual browser Back restore working search/clear handlers.
- Search-to-empty/clear and invalid-end-time retain coherent page/form state.
- Nine concept-only cases (3 styles ×390/1440/1920) assert regions and absence of sideways scroll.
- Five subscribed performance cases assert200, actual query/duration/LCP ceilings; no skipped unavailable route.
- Fractional0.5L line retains name, batch, unit and native validity after searching for a second bottled product, then actually saves both lines with201 and correct allocations. Real old-code execution failed native validity; corrected code passed. Independently graded valid.

Final code: three consecutive full runs, **20/20 passed** each: final7 34.34s, final8 34.23s, final9 34.67s, logs under `~/.cache/tastings/`. Existing limiter/table-cycle warnings remain. Earlier19-case runs were also green before adding the fractional-volume regression; these are not substitutes for the final20-case runs.

Five complete visual passes exercised all3 styles. Final05 has71 PNGs: busy/quiet laptop/phone/wall/dark, detail and lower phone controls, editor and lower phone controls, edit/save, error/loading/empty, boosted return, Home/Suppliers reference pages. Every final PNG was read and no visual defect remained. The screenshot org was purged (`purge-final.log`).

Shared suite: Production layout, page rendering and full registry-driven boosted navigation completed **91 passed,2 failed** in512.47s. The failures were `/core/people` and `/core/sites`, which redirect this member fixture to Dashboard; Back's text-length comparison changed922 vs1189 characters. They did not land on their named pages. The same two tests passed in isolation on unchanged main (2passed/18.20s) and on the feature branch (2passed/18.01s). A full unchanged-main order comparison is recorded in the MR/follow-up below, rather than treating an isolated retry as proof of a fixed bug. No existing assertions were removed or weakened.


Final comparison: unchanged main09ba2abd passed the complete92-case shared run (508.79s; `shared-baseline-full.log`). The final serial feature-branch `test_boosted_navigation.py` run passed **68/68** (438.32s; `shared-boosted-repeat.log`), including the new Tastings route. Production-layout/render cases already passed in the original combined run. An abandoned Home-performance browser process, still running after4h28m from the earlier task, was terminated before the serial repeat. No existing test or application code was changed to make the shared checks pass. This records the original transient failure as well as the final green evidence, rather than presenting a first-run-green claim.

VERDICT: clean

Navigation/model integration follow-up: after grouping Tastings under Tasks, the feature browser suite passed20/20 three consecutive times (35.64s,34.77s,37.69s). The normal link from shared Tasks still loads Tastings and the existing boosted/Back assertions remain. Final visual pass06 covers the same71 scenarios; all images read, no defects found, seed purged.
