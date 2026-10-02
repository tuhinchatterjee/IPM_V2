# Regression of candidate J (`84b0ca12f140d10619172686d1373e7985f2fabb`): rejected

Run from a fresh detached clone, output outside the repository. The result was 15 PASS, 1 BLOCKED_ENV and 2 FAIL. The step that rejected candidate I (the accepted interpreter) passed.

**FAIL: `gw_browser_journeys_clean_store`, 81/82.** The failing journey is `GW-P5-05`, which existed before this round and passed on candidate I and in every development run. Its record shows `bound: scn-tpl-corp-02 v1`, the library template itself, so the assertion "scope is cohort" read the template.

This was a harness race:
- Once the template is loaded, What-If already previews it on the template's own scope.
- After clicking Apply, the journey waited for `whatif-preview`, which was already on screen.
- It then read the application's scenario id before Apply had saved the selection as a cohort and re-bound to a new object.

The product behaved as designed. The journey now waits for the re-bound object (a new id with the cohort set); it passed three consecutive times after the fix.

**FAIL: `validation_inventory_runtime`.** This failure is derived from the one above: every control, route and handoff the failed journey touched inherits its FAILED status. It is not an independent defect.

**BLOCKED_ENV: `emulator_artifacts_reproduce`.** Only the component pickle bytes differ, as at H and I.

Because a tracked harness file had to change, candidate J is rejected; candidate K carries the fix.
