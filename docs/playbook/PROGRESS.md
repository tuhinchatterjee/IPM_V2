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
| M0 — safe foundation | in progress |
| M1 — live vertical slice | not started |
| M2 — home and thread UX | not started |
| M3 — exported-analysis flow | not started |
| M4 — intelligent reporting | not started |
| M5 — demo completeness | not started |
| M6 — verification and hardening | not started |
| M7 — handoff | not started |

## Next action

Complete M0: record the baseline test run, decide the Anthropic SDK version
against current official documentation, add `python-pptx`, and write migrations
`0032` and `0033`.
