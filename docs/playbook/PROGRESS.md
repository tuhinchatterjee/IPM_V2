# Playbook — progress and safe-resumption record

Update this file at every milestone boundary. On a context compaction, read
`MASTER_SPEC.md`, `IMPLEMENTATION_PLAN.md`, this file and `REQUIREMENTS_MATRIX.md`,
then resume from the first incomplete item below. Do not restart, re-scaffold,
change the base, or merge another branch.

## Branch and base

| | |
|---|---|
| Working branch | `claude/creditprobe-playbook-plan-ky3m05` |
| Base commit | `3855f9b6f6b231beb6f2193c8a1e219d01596421` |
| Base branch | `main` (the session branch was created at, and equals, this commit) |
| Merge status | **not merged, must not be merged** |

## Isolated development environment

Git isolation is not database isolation, so both are separated.

| Concern | Value |
|---|---|
| Python | 3.12.11, fetched by `uv` into `.venv` |
| Database cluster | PostgreSQL 16.13, own cluster at `/var/lib/postgresql/playbook_dev`, **port 55432** |
| Dev database | `creditprobe_playbook_dev` |
| Test database | `creditprobe_playbook_test` |
| Uploads / artifacts | `.playbook-dev/uploads` (gitignored) |
| Credentials | local `.env`, gitignored, never committed |
| Migration state | `alembic upgrade head` applied — at `0031` before Playbook migrations |

Nothing in this setup touches a default `5432`, a production database, or any
committed data file.

## Baseline findings recorded before any Playbook change

These are pre-existing facts about the base commit, not defects introduced here.

1. **`uv sync` cannot resolve on this baseline.** `pyproject.toml` declares
   `requires-python = ">=3.11"` while `numpy==2.5.0` requires `>=3.12`, so
   resolution over the declared range is unsatisfiable. There is no `uv.lock`.
   CI (`.github/workflows/ci.yml`) runs `uv sync` and would hit the same failure.
   **This branch does not change `requires-python`** — that is a repository-wide
   decision outside Playbook's scope. Local installation uses
   `uv venv --python 3.12` + `uv pip install -r pyproject.toml --group dev`,
   which resolves against one concrete interpreter and succeeds.
2. **CI has never run.** `list_workflow_runs` for `ci.yml` returns
   `total_count: 0`, so there is no green CI baseline to compare against.
3. **`requirements.txt` cannot run the test suite** — `pytest` and `ruff` are in
   `pyproject.toml`'s dev group only, and the `requirements-dev.txt` its comment
   references does not exist.
4. **`GET /api/v1/playbooks` and `GET /api/v1/playbooks/{id}` resolve no
   `Principal`**, so `REQUIRE_LOGIN` is not enforced on those two reads. Reported,
   not silently altered — it belongs to the pre-existing monitoring feature.

## Milestones

| Milestone | State |
|---|---|
| M0 — safe foundation | complete |
| M1 — live vertical slice | implemented; live run **BLOCKED** on a credential |
| M2 — home and thread UX | complete |
| M3 — exported-analysis flow | complete; What If DEFERRED-INTEGRATION |
| M4 — intelligent reporting | implemented; live behaviours **BLOCKED** |
| M5 — demo completeness | complete |
| M6 — verification and hardening | complete except the live suite |
| M7 — handoff | in progress |

## Baseline test run

Run on the isolated test database with all three data universes built, after the
additive migrations and before any behavioural Playbook code:

    DATABASE_URL=…creditprobe_playbook_test .venv/bin/python -m pytest -q --tb=no

**One failure, and it was ours, not the baseline's:**
`tests/scripts/test_powershell_script.py::test_the_cost_table_matches_the_python_side`.
Adding the AUTHOR model role moved quick live verification from 15 provider
calls to 16, and `scripts/verify-live-ai.ps1` mirrors that number so it is
visible before a run spends credit. The script was updated and the test passes.
That test did its job.

The two `tests/exports` failures seen earlier were an artefact of running that
suite before the corporate universe had finished building. They do not occur
once the lake is complete.

## Anthropic SDK decision

**No SDK change.** The pinned `anthropic==0.112.0` already carries everything
Playbook's runtime needs, through the beta namespace:

* `BetaContainerParams.skills` and `BetaSkillParams` — `{skill_id, type, version}`,
  matching the current published shape;
* all four code-execution tool types, including `code_execution_20260120`;
* `client.beta.files` for upload, metadata, download and delete.

Only the GA namespaces (`client.files`, `client.skills`) need ≥1.2.0, and
Playbook does not require them. Leaving the pin alone means CreditProbe's
analytical runtime is untouched by this work, which is worth more than a tidier
import path. Verified against the installed SDK rather than from memory, and
re-checked against the provider's current documentation.

## Verification actually run

| What | Result |
|---|---|
| `pytest tests/playbook` | 196 passed |
| `pytest tests/playbook tests/demo tests/api tests/services` | 830 passed |
| `npm test` | 430 passed |
| `tsc --noEmit`, `eslint`, `next build` | clean |
| `ruff check .` | clean repository-wide |
| `scripts/acceptance/playbook_browser_acceptance.py` | 63 passed, 0 failed |
| `scripts/acceptance/verify_playbook_artifacts.py` | 14 files, 62 checks, 0 failed |
| `scripts/playbook_live_slice.py` | **exit 2 — cannot run, no credential** |

## GitHub Actions

`list_workflow_runs` for `ci.yml` returns `total_count: 0` before and after
pushing this branch. Actions appear to be disabled on this repository, so CI has
never run and did not run on this work either. That is a fact about the
repository, not about this branch — and it means CI is not a source of
verification here. Everything above was run locally.

## Next action

M7: the handoff summary. The only outstanding verification is the live
authoring path, which needs `ANTHROPIC_API_KEY` in the environment.
`scripts/playbook_live_slice.py` runs the whole vertical slice the moment one
is present.
