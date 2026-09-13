# Early Warning — pre-UAT continuation checklist

Durable working state for the pre-UAT exercise. **If the session compacts:**
reread `docs/EARLY_WARNING_PRE_UAT_REPORT.md`, reread
`docs/early_warning_pre_uat_results.json`, reread this file, and continue from
the first line that is not `done`.

Branch `claude/early-warning-rebuild-v2-3lnttn`. From `d683881` to `5ea9f1e`.
Nothing here is merged to main.

Legend: `todo` · `wip` · `done` · `blocked-external` (needs the Mac provider
run) · `n/a`.

| # | Item | State |
|---|---|---|
| 1 | Checklist created, environment re-established | done |
| 2 | P1-A — external intelligence understood as L3 | done |
| 3 | P1-B — governed band-transition analysis | done |
| 4 | P2 — band distribution states period and total | done |
| 5 | P2 — "across 1 obligors" pluralisation | done |
| 6 | P2 — measure labels, units, empty-state wording | done |
| 7 | Data realism — classify cause A–E, fix the input if generator | done |
| 8 | Level 2 questions | done |
| 9 | Level 3 questions | done |
| 10 | Level 4 questions | done |
| 11 | Level 5 questions | done |
| 12 | Thread chain A | done |
| 13 | Thread chain B | done |
| 14 | Clarification UAT | done |
| 15 | Noisy / misspelled / mixed-language UAT | done |
| 16 | Messaging UAT (through the actual UI) | done |
| 17 | Escalation / decision-layer UAT | done |
| 18 | Investigations UAT | done |
| 19 | Report / export UAT | done |
| 20 | Navigation and history UAT | done |
| 21 | 10 new adversarial questions | done |
| 22 | Performance review over >= 10 turns | done |
| 23 | Progress UX across all paths | done |
| 24 | `scripts/certify_early_warning_live.py` | done |
| 25 | Live summary truncation assertion in the cert script | done |
| 26 | Update report + results JSON (update, never replace) | done |
| 27 | Full final regression, then classify A / B / C | done |


## Run 2 outcome

**B — READY EXCEPT FOR LOCAL PROVIDER CERTIFICATION.**

78 scenarios run, 78 passing. Nineteen defects found and fixed (the three P1s
carried from run 1, plus sixteen new). Zero P0 and zero P1 remain under this
environment's control. Two P2s documented rather than fixed, both with a
reason: the MEDIUM band stays thin because the matrix makes it so, and there
is no escalate button on the Early Warning screen.

Full final regression run on the finished tree: backend 22 failed / 10,589
passed / 27 skipped, the 22 identical line for line to the recorded baseline
and none of them in `tests/early_warning/` or `tests/api/`; frontend 429 of
429; typecheck, lint and production build clean.

The only thing outstanding is `scripts/certify_early_warning_live.py`, run on
a machine that has the Anthropic key.


## Run 3 — live provider certification remediation

The Mac run returned **3/8 certified, VERDICT: NOT_CERTIFIED**. Five cases
failed on three defects, none of which any deterministic test could reach:
every one needed a model to actually answer.

| # | Item | State |
|---|---|---|
| 28 | Trace the provenance of every rejected figure, A / B / C | done |
| 29 | Grounding: a figure the packet holds, however English writes it | done |
| 30 | Grounding: the governed derived-claim contract | done |
| 31 | Grounding: the numeral scanner reads a hyphen as a hyphen | done |
| 32 | `sonnet_pass_2` real-model vocabulary conformance | done |
| 33 | Ownership: an observed-state question is not a scenario | done |
| 34 | Preserve LIVE-1, LIVE-4 and LIVE-6 as non-regression cases | done |
| 35 | Certification diagnostics, without weakening acceptance | done |
| 36 | Focused tests, full regression, baseline comparison | done |
| 37 | Second Mac certification run | blocked-external |

Run 3 commit `7bc3c0f`. Backend 22 failed / 10,754 passed / 27 skipped, the
22 identical to the recorded baseline. Frontend 429 of 429; typecheck, lint
and production build clean.


## Run 4 — LIVE-5 remediation and certification hardening

The second Mac run returned **7/8**. LIVE-5 alone failed, on one ungrounded
figure: `25`.

| # | Item | State |
|---|---|---|
| 38 | Capture the semantic context of every rejected token | done |
| 39 | Classify `25` with evidence, A / B / C / D / E | done |
| 40 | Ranking composer answers by the measure it ranked on | done |
| 41 | Planner ranks a movement question by movement, unfiltered | done |
| 42 | "Which one improved most?" is a request for a name | done |
| 43 | Certification: a missing required stage can never pass | done |
| 44 | Certification: What-If has its own required stage set | done |
| 45 | Certification: the false-premise check tests arithmetic | done |
| 46 | Certification: case isolation asserted and reported | done |
| 47 | `--case LIVE-5`, with the identical checks | done |
| 48 | Focused tests, EWS suite, baseline regression | done |
| 49 | Third Mac certification run | blocked-external |

Backend 22 failed / 10,810 passed / 27 skipped, the 22 identical to the
recorded baseline. `tests/early_warning` and `tests/api` clean. Frontend 429 of
429; typecheck, lint and production build clean. Against the stub the
certification returns 8/8.

## Run 5 — LIVE-3 derived-claim remediation

The third Mac run returned **7/8**. LIVE-3 alone failed, on `-4.86` and
`6,301.85`.

| # | Item | State |
|---|---|---|
| 50 | Reconstruct LIVE-3 and classify both figures with evidence | done |
| 51 | Publish a fact index the writer selects its refs from | done |
| 52 | One rule for sign: the declared value is signed | done |
| 53 | Direction checked against the sign, in prose | done |
| 54 | Common EWS derivations owned by the server | done |
| 55 | Prompt priority: direct, then derived, then declared | done |
| 56 | Pass two's merge keeps the headline precedence | done |
| 57 | Certification: direction and derivation assertions added | done |
| 58 | Focused tests, EWS/API suites, baseline regression | done |
| 59 | Fourth Mac certification run | blocked-external |

`-4.86` was right — `L1.points_contributed` + `L4.points_contributed` over the
2024-11 to 2026-06 Contracting movement — and declared with the size instead of
the signed value. `6,301.85` is reproducible from nothing in the packet and
stays rejected.

Backend 22 failed / 10,843 passed / 27 skipped, the 22 identical to the
recorded baseline. `tests/early_warning` and `tests/api` clean. Frontend 429 of
429; typecheck, lint and production build clean. Against the stub, 8/8.

## Run 6 — LIVE-5 direction disambiguation

The fourth Mac run returned **7/8**. LIVE-5 alone failed, on a true sentence:
the guard bound direction to the size `8.0`, which this population carries
both ways.

| # | Item | State |
|---|---|---|
| 60 | Prove the ±8.0 collision from the real frame | done |
| 61 | Governed metric semantics: is it a move, which way is worse | done |
| 62 | Direction binds to a fact, not a magnitude | done |
| 63 | `movement_claims` — the reading names the fact it means | done |
| 64 | `movement_census` published with names and signed changes | done |
| 65 | Follow-ups held to the same grounding rules | done |
| 66 | Certification: declared movements must agree with their fact | done |
| 67 | Focused tests, EWS/API suites, baseline regression | done |
| 68 | Fifth Mac certification run | blocked-external |

±8.0 both exist: two Contracting obligors improved by 8.0 and five
deteriorated by 8.0. The largest deterioration is +8.0 (Sahara Development
first of five tied); the largest improvement is −10.0 (Al Rajhi Logistics 8).
The reading was right; the guard was not.

Backend 22 failed / 10,900 passed / 27 skipped, the 22 identical to the
recorded baseline. `tests/early_warning` and `tests/api` clean. Against the
stub, 8/8. No frontend file changed.

## Run 7 — ranking coverage

The fifth Mac run returned **7/8**. LIVE-5 alone failed, on `20` — the count
of obligors a ten-row ranking omitted from a population of thirty.

| # | Item | State |
|---|---|---|
| 69 | Prove 30 − 10 = 20 from the reconstructed packet | done |
| 70 | `ranking_coverage` computed server-side, after the step's filters | done |
| 71 | Coverage published to the writer's fact index | done |
| 72 | Prompt: quote the counts, never subtract one from another | done |
| 73 | Truncation caveat demoted below the answer | done |
| 74 | Grounding unchanged — `20` not whitelisted | done |
| 75 | Focused tests, EWS/API suites, baseline regression | done |
| 76 | Sixth Mac certification run | blocked-external |

Backend 22 failed / 10,918 passed / 27 skipped, the 22 identical to the
recorded baseline. `tests/early_warning` and `tests/api` clean. Against the
stub, 8/8. No frontend file changed.
