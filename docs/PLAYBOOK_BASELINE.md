# Playbook — protected baseline

Recorded before the first line of Playbook code changed anything that already
existed, so that every later regression run has something honest to be compared
against.

## The run

```
git rev-parse HEAD                    # d55f625
git status --porcelain                # clean
.venv/bin/python -m pytest tests -rs -q --tb=short
```

Executed as a real, verified pytest process — not a wrapper — on branch
`claude/playbook-committee-intelligence` at HEAD `d55f625`, which is the
final HEAD of the protected release candidate `claude/vigilant-darwin-eohyi1`.

## The result

| | |
|---|---|
| Passed | **12,075** |
| Skipped | **35** |
| Failed | **0** |
| Errors | **0** |
| Exit code | **0** |
| Alembic head | `0038` (single head) |

There are **no pre-existing failures**. Any failure in a later run is
attributable to this work.

### Why the counts were derived from the progress output

`pyproject.toml` sets `addopts = "-q"`. Passing `-q` again on the command line
makes it `-qq`, which suppresses pytest's own `N passed` summary line. The
tally above was counted from the progress characters in the captured log
(`.` = passed, `s` = skipped) and cross-checked against the exit code and
against the zero `FAILED`/`ERROR` lines in the same log. It is recorded here
rather than quietly corrected because the next person to run the suite will hit
the same missing line.

## The 35 skips, and why each is a skip rather than a failure

| Count | Where | Reason |
|---:|---|---|
| 12 | `tests/scripts/test_powershell_script.py` | No PowerShell runtime in this environment |
| 5 + 1 + 1 + 1 | `tests/llm/test_live_smoke.py` | No AI provider key is configured |
| 3 | `tests/orchestration/test_multi_condition.py:309` | The shape does not compile through the multi builder |
| 3 | `tests/orchestration/test_multi_condition.py:345` | The question is answered from one dataset |
| 1 each ×4 | `tests/orchestration/test_multi_condition.py` | The planner stopped to ask: `covenant_tests` does not carry `days_past_due` |
| 2 | `tests/api/test_user_administration.py` | This database has more than one administrator |
| 1 | `tests/evals/test_ask_evaluation.py` | Set `RUN_LIVE_LLM_EVALS=1` to run these |
| 1 | `tests/multi/test_relationship_assistant.py` | No multiplying candidate in this data |
| 1 | `tests/orchestration/test_query_validation.py` | The result is limited, so absence proves nothing |

Every one of these is an environment or data condition the test itself detects
and reports. None is a suppressed failure.

## What this baseline is for

Phase 1 of the Playbook build **removes** the earlier Playbooks feature at the
user's direction. That removal deletes the tests that tested the removed
feature, which is legitimate; it must not change the result of any test that
covers behaviour CreditProbe keeps. The regression run at the end of the build
is compared against this record, and the difference is accounted for
test by test.
