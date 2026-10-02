# Regression of candidate I (`fc8754a19e72f274ec518a7fb2f5a47b37bc820e`): rejected

Run from a fresh detached clone, output outside the repository. The result was 16 PASS, 1 BLOCKED_ENV and 1 FAIL.

**FAIL: `v4_backend_and_frontend_py_accepted`.** There were 4 failures; three are the known, environment-bound baseline failures. The fourth is not on the known list: `test_multilingual_and_evidence_labels.py::test_no_test_in_this_suite_claims_a_live_provider_measurement`.
- The three new test modules described their evidence in words outside the allowed label vocabulary.
- Only the alphabetically first module is reported, because the assertion stops there.

The fix is docstring-only, but a tracked test file had to change. Under the round's rule that rejects candidate I; candidate J carries the fix.

**BLOCKED_ENV: `emulator_artifacts_reproduce`.** As at candidate H, only the component pickle bytes differ (refit nondeterminism). Weights, gates, verdicts, versions, seeds and splits all reproduced.

Every other step passed. That includes the guided browser suite (`gw_journeys.json`: every journey, including the 22 BACK and 10 GOLD), the inventory runtime step, the What-If candidate browser suite and the flags-OFF accepted browser suite.

Screenshots and the rebuilt sensitivity libraries are not copied; the logs, junit files and summary are.
