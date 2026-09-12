# Early Warning — pre-UAT continuation checklist

Durable working state for the pre-UAT exercise. **If the session compacts:**
reread `docs/EARLY_WARNING_PRE_UAT_REPORT.md`, reread
`docs/early_warning_pre_uat_results.json`, reread this file, and continue from
the first line that is not `done`.

Branch `claude/early-warning-rebuild-v2-3lnttn`. Continuing from `d683881`.
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
| 27 | Full final regression, then classify A / B / C | wip |


## Run 2 outcome

**B — READY EXCEPT FOR LOCAL PROVIDER CERTIFICATION.**

78 scenarios run, 78 passing. Nineteen defects found and fixed (the three P1s
carried from run 1, plus sixteen new). Zero P0 and zero P1 remain under this
environment's control. Two P2s documented rather than fixed, both with a
reason: the MEDIUM band stays thin because the matrix makes it so, and there
is no escalate button on the Early Warning screen.

The only thing outstanding is `scripts/certify_early_warning_live.py`, run on
a machine that has the Anthropic key.
