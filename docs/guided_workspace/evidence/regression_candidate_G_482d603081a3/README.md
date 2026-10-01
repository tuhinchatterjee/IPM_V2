# Regression of candidate G (`482d603081a3f58e888623913d415cb5c22accef`), kept as measured

Run by `final_regression.sh` on a fresh `--no-local` clone detached at G, with no
repository edit while it ran. Copied here unchanged, except the 116 journey
screenshots, which are omitted to keep the repository small; every other file
the run produced is present.

**Result:** 15 PASS, 1 BLOCKED_ENV, **1 FAIL**. G is therefore NOT the UAT
candidate.

- **BLOCKED_ENV, `emulator_artifacts_reproduce`.** Only the component pickle
  bytes differ; every gate, weight, verdict and split reproduces. This is the
  same as F.
- **FAIL, `gw_browser_journeys_clean_store`.** 47 of 48 journeys passed.
  GW-P5-06 timed out waiting for the grid to narrow to Credit Card after a bar
  click.

## Diagnosis of GW-P5-06

The journey and the product path it covers were unchanged from F.

- **Earlier runs all passed it:** F's regression, the diagnostic run and a
  targeted P5 run on G's own code.
- **Not the console errors.** The browser console errors in the UI log
  (`reading 'selectAll'`) occur identically in F's passing run.
- **The cause is the harness.** The `clickBar` helper scrolled the chart only
  "if needed" and then clicked at computed coordinates. The What-If selection
  bar is `sticky top-0 z-10`, so depending on the scroll position it can cover
  the target bar, and the click lands on the overlay.
- **The fix, in candidate H.** The helper centres the chart, re-reads the box
  after layout settles, and asserts that `elementFromPoint` at the click point
  is inside the chart before clicking. It no longer clicks blindly.
- **No product code changed for this.**
