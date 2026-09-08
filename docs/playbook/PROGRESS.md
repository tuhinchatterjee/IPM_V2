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
| `pytest tests/playbook` | 216 passed |
| `pytest tests/playbook tests/demo tests/api tests/services` | 830 passed |
| `npm test` | 442 passed |
| `tsc --noEmit`, `eslint`, `next build` | clean |
| `ruff check .` | clean repository-wide |
| `scripts/acceptance/playbook_browser_acceptance.py` | 84 passed, 0 failed |
| `scripts/acceptance/verify_playbook_artifacts.py` | 14 files, 62 checks, 0 failed |
| `scripts/playbook_live_slice.py` | **exit 2 — cannot run, no credential** |

## GitHub Actions

`list_workflow_runs` for `ci.yml` returns `total_count: 0` before and after
pushing this branch. Actions appear to be disabled on this repository, so CI has
never run and did not run on this work either. That is a fact about the
repository, not about this branch — and it means CI is not a source of
verification here. Everything above was run locally.

## Deciding proposed changes (PB-016)

The last piece of interactive behaviour to land. A numbered proposal now has a
panel: tick the changes to make, leave the rest, and the decision is recorded
against stable ids rather than display numbers, so "hold 4" still means change 4
after a reload.

Three things it deliberately does:

- **It refuses rather than resolves.** A change approved while the change it
  rests on is excluded produces a 409 that names the dependency, and nothing is
  written. In the interface the same rule appears earlier and more kindly:
  ticking a dependent change ticks what it rests on and says so.
- **It does not rewrite the document.** Recording a decision produces an
  instruction — "apply only these, return everything else unchanged, and do not
  make these others even partially" — which the user sends. A tick box does not
  start a generation.
- **It keeps a decided proposal on screen.** "Which of the five did we hold?" is
  a question asked long after the decision.

## Restoring a version, and stopping a run

Two controls the specification asks for that the first pass left at the service
layer.

**Restore moves forward.** Restoring v1 over v3 writes a v4 carrying v1's
content and v1's exact bytes; v3 stays where it is. A restore that deleted the
versions after it would destroy the record of what was tried, which is what
version history is for. The files are copied rather than re-rendered, so the
download from v4 is byte-for-byte the file that was reviewed as v1.

**Stop sets a flag rather than killing anything.** The generating request reads
it between steps, and because a version is written last, a stopped run leaves
the previous version exactly as it was. The generation is synchronous, so the
send request has no job id to offer until the work is over — the browser mints
the idempotency key before it sends and asks `GET /playbook/jobs/by-key/{key}`
which job that key became. That is what makes Stop a control that can act
rather than a button that arrives too late to.

Cancelling something that already finished changes nothing and says so. A
version that landed is not withdrawn by a stop pressed after it landed.

## Reading a version without downloading it

A preview rendered from the CONTENT that was persisted, not from the generated
file and not from what the model first replied. Two consequences worth naming:
it shows what grounding actually left in the document, and it works for a
version whose files a browser cannot display inline anyway. It is not a
substitute for the file — the download stays the authoritative artifact and is
offered inside the preview — it is how somebody reads version 1 before deciding
whether to bring it back.

## The task framings, and the document a revision is revising

Two gaps the first pass left. `backend/playbook/prompts.py` carried all six of
§8's framings — create, update, coverage, propose, edit, present — and nothing
called them: every instruction went to the author as written. And no request
ever carried the CURRENT DOCUMENT.

The second is the more serious of the two. A revision that never sees what it
is revising cannot leave the other sections alone; it can only write them again
from memory, which is how a scoped edit quietly rewrites a figure three
sections away. The document now travels with every run against an existing
artifact, framed so it cannot be mistaken for evidence, and it says plainly
that anything omitted is deleted.

The framing carries the rules that make one job different from another: return
the complete document, never soften a negative finding, produce a coverage
matrix and do not revise the report, propose changes and do not apply them. An
unknown or absent framing passes the instruction through untouched rather than
guessing — guessing would apply "return the complete document" to a request
that was never about a document.

`task` and `scope` are optional on the message API, and the follow-up chips
carry theirs, so a chip's meaning does not depend on the wording of its
sentence. Typing over the chip's text clears the framing with it.

## Next action

M7: the handoff summary. The only outstanding verification is the live
authoring path, which needs `ANTHROPIC_API_KEY` in the environment.
`scripts/playbook_live_slice.py` runs the whole vertical slice the moment one
is present.
