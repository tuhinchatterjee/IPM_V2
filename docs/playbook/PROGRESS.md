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
| Database cluster | PostgreSQL 16.13, own cluster at `/var/lib/postgresql/playbook_dev`, **port 55432**. Managed by `scripts/playbook_dev_env.sh` (`start` / `stop` / `status` / `create`). |
| Dev database | `creditprobe_playbook_dev` |
| Test database | `creditprobe_playbook_test` |
| Uploads / artifacts | `.playbook-dev/uploads` (gitignored) |
| Credentials | local `.env`, gitignored, never committed |
| Migration state | `alembic upgrade head` applied — at `0031` before Playbook migrations |

Nothing in this setup touches a default `5432`, a production database, or any
committed data file.

**Resuming after a container restart.** The cluster's data survives; the server
does not, and neither do the two application processes. `scripts/playbook_dev_env.sh start`
brings the database back, and the "Running it" block in `INTEGRATION_NOTES.md`
covers the rest. The port matters more than it looks: this cluster's
`postgresql.conf` sets no `port`, so a bare `pg_ctl start` comes up on 5432 and
every connection string in `.env` is then quietly pointing somewhere else. The
script passes 55432 explicitly so that cannot happen.

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
| M7 — handoff | complete; live verification remains **BLOCKED** |
| M8 — streaming | complete; verified in a real browser |

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
| `pytest tests/playbook` | 392 passed, 8 live checks skipped |
| `pytest tests/playbook tests/api tests/demo tests/services tests/exports tests/docs tests/proof tests/validation tests/llm` | 1373 passed, 8 skipped |
| `pytest` (whole repository) | **9810 passed, 30 skipped, 0 failed** |
| `npm test` | 462 passed |
| `tsc --noEmit`, `eslint`, `next build` | clean |
| `ruff check .` | clean repository-wide |
| `scripts/acceptance/playbook_browser_acceptance.py` | 105 passed, 0 failed |
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

## Correcting a source

The parser guesses at two things about an uploaded file — what kind of document
it is and which period it describes — and until now neither could be overruled.
A methodology document read as "supporting" is evidence the author weighs
wrongly, and there was no way to say so.

Both are now editable, and the correction records that a PERSON set the value,
not just the value: a reader of the evidence can tell an inference from an
instruction, and the parser's confidence is cleared rather than left describing
a guess nobody made. A failed or partial parse offers a retry that re-reads the
stored bytes rather than asking for the file again — the bytes are already
there, and a second upload would prove nothing the first did not.

## Streaming, and why it needed a different shape

The first pass reported real milestones and held the request open until the
document was finished. That is not the streamed conversation the specification
asks for, and the obvious fix — stream from inside the request that started the
work — fails the requirements around it. A reload would kill the run, the user
would see a blank thread, and pressing send again would start a second billable
generation of the same turn.

So the generation moved out of the request:

* it runs in a **worker**, owned by the job rather than by any connection;
* every event it produces is **appended to `playbook_job_events`** with a
  monotonic `seq` (migration `0034`);
* a connection is a **reader** of that log — it replays from the client's
  cursor and then tails.

A reload therefore reconnects to the same job and replays what it missed. The
workspace payload carries `running_job` so a page that has just loaded knows
what to attach to without having to send the message again to find out. Two
browsers can watch the same generation. A dropped connection costs nothing, and
the client reconnects from its cursor rather than replaying the answer.

`EventSource` was not usable: it cannot send the `X-IPM-Role` header this
deployment identifies callers with. The stream is read with `fetch` and a
reader, and `src/lib/stream.ts` is the incremental parser — which is the part
worth testing, because a parser that assumes one read is one event drops text
at random under load and is perfect in a demonstration.

**What is streamed, and what never is.** Only user-visible answer text and real
job states. The provider's stream also carries reasoning blocks, tool inputs
and the code the sandbox is about to run; the filter in `provider._stream_once`
forwards a delta only when the event is a `content_block_delta` AND the delta is
a `text_delta`, so none of that leaves the function. The system prompt and the
evidence ledger stay on the server. A test asserts the log contains none of it.

**An interrupted stream is not an answer.** The assistant's message and the
artifact version are written when the run completes, so a partial stream lives
in the event log and nowhere a user can act on: no message with a document, no
version, no file to download. On failure the client discards the fragment
rather than leaving half an answer on screen as though it were the answer.

Cancel and retry stayed where they were and now have somewhere to bite. Retry
derives a new key — `:retry2`, `:retry3` — so each press stands for exactly one
attempt and the failed attempt remains findable.

## What the first live run found

`claude-opus-5` served, with no downgrade. Parsing, the ledger, versioning,
DOCX and PDF generation, validation, persisted bytes, reopening, version 1
preserved, version 2 genuinely different and 22.77 carried across — all held on
the first real provider run. Four things did not, and each was a real defect
rather than a flaky assertion.

**19.20 — the assertion was wrong, twice.** `19.20` is
`DECLARED["base_ecl"]["current"]`: a scenario INPUT to the probability-weighted
ECL, not a reported result. The fixture workbook writes it as a Python float, so
openpyxl stores 19.2 and `sheets.py` renders `str(19.2)` — the string "19.20"
appears nowhere in the evidence the model is given. Meanwhile `validate.figures()`
strips trailing zeros, so grounding treats 19.2 and 19.20 as one figure and could
never have enforced the difference. The check demanded a formatting choice using
a rule the product does not apply. It now compares with the system's own rule:
every figure in the generated file must trace to the evidence, and the reported
weighted ECL must be present. Separately and on its own merits, the authoring
prompt now asks for money at two decimal places, matching the repository's
existing two-decimal display contract — 20.90 beside 19.2 in a board paper reads
as sloppy.

**The "invented" figure in the scoped revision — two causes.** A revision was
judged against the sources alone, so restating a figure the approved version
already carried read as inventing it; `service.add_current_version` now admits
the approved version as evidence, which is sound because version 1's own figures
were grounded when version 1 was written. And matching is exact-token, so a model
told to be "more concise" re-rounds 8.95 to 8.9 and is caught — correctly, since
a committee paper saying 9 per cent where the calculation says 8.95 has
misstated the result. The prompt now forbids re-rounding in as many words.
Grounding itself is untouched: no tolerance was added, and a test pins that.

**The hang.** `anthropic.Anthropic(timeout=900.0)` — a bare float, which httpx
collapses to all four phases, so connect waited fifteen minutes and so did every
read. Worse, a read timeout bounds inactivity between reads, not the operation:
a stream trickling one token a minute never trips one and runs until somebody
presses Ctrl+C, which is exactly what happened. Now four separate transport
timeouts, plus the bound that actually matters — a wall-clock deadline for the
whole run, checked between stream events and between turns. A timeout is never
retried automatically; the user has a retry button, and the product does not
spend money on its own initiative.

**The missing model.** `if model: kwargs["model"] = model` — and the Messages API
has no server-side default, so omitting the field is an error, not a fallback.
The comment claiming otherwise was simply wrong, and `.env.example` ships
`AI_AUTHOR_MODEL=` blank, so the shipped example config reproduced the crash.
`status()` now reports `AUTHOR_MODEL_NOT_CONFIGURED` and `author()` refuses
before the client is built.

## The targeted live re-run

PB-030 **passed for real**: `claude-opus-5` requested and served, no downgrade, 76.5s, with a
recorded request id. PB-017 and PB-015 failed, and the provider log carried a
latency that could not describe the attempt beside it.

**PB-017 — nothing structurally enforced the scope.** "Revise only the executive
summary" was a sentence in a prompt plus two checks afterwards; whether the rest
of the document survived was left to the model. The failing conjunct was
`grounding.ok` — the only one that could be — and the check could not say so,
because its detail string was built from a regex matching two-decimal figures
only, which a re-rounded or integer invention never trips. Now the scope is
enforced by construction: `merge.scoped_merge` takes only the requested section
from the model's reply and carries every other section forward as the same
object. Unrelated sections are identical because they were never replaced, and
grounding only scrutinises what actually changed.

**PB-015 — one call was doing two jobs.** The authoring run also drove the
document Skills and server-side code execution, and while the sandbox builds a
file no text deltas arrive; 281s is ~161s of streaming then the full 120s read
timeout. Evidence size was ruled out by measurement — 26 chunks, 34 ledger
items, ~2,517 prompt tokens, 0 omissions, 631 of 120,000 budget tokens. Nothing
was truncated. Authoring is now text-only and bounded, the files are rendered
deterministically from the approved document, and the document Skills are
retained behind `PLAYBOOK_SKILL_RENDERING=1` with their own longer read timeout.

**The timing inconsistency — two defects.** `_check_clock` guarded
`if started is None`, so a `0.0` origin passed through and measured
`time.monotonic()` itself: container uptime, which is what 1636923 ms is shaped
like. And nothing could correlate the two numbers anyway — failures carried no
request id, `Call` carries no run or check id, `Outcome.latency_ms` was written
by three mechanisms on two clocks, `AuthoringTimeout` was re-raised with no
telemetry at all, and abandoned workers kept writing to a process-global ledger
after their check line had printed. Durations are now named separately —
`provider_ms`, `authoring_ms`, `render_ms`, `check_ms`, `suite_ms` — measured on
one clock, and a test asserts they nest.

## The second targeted live re-run

Against `c68dfa1`. The latency architecture held — PB-015 completed in 90.6s
where it had timed out at 281s, with authoring and rendering timed separately —
and both remaining failures turned out to be comparison defects rather than
model behaviour. Neither was diagnosed by reading; both were reproduced by
executing the real parser, renderers and readers.

**PB-017 — the pipeline destroyed the sections it claimed to carry forward.**
Thirteen unrelated sections were reported as changed with before/after snippets
that read identically. Two independent causes, and the answer to "did the
canonical content actually change" is yes for the first and no for the second.

*The merge base was not the approved version.* `_current_document` returned the
stored version re-rendered to Markdown, and `_markdown_of` never re-emits the
`[[locator]]` citation markers, `subtitle` or `meta`; parsing it back with the
title already supplied also injected an empty section named after the document.
Measured on a twelve-section report: eight citation locators in, zero out,
`subtitle` and `meta` gone, thirteen sections where there had been twelve, and
seven sections whose first differing field was `block[0].sources`. `scoped_merge`
deep-copies its base, so that damage was carried forward and written to
canonical storage as version 2. The base is now the stored canonical
`Document` — `from_dict(as_dict(...))` is exact, verified by content hash and by
every section fingerprint — and the Markdown remains what it always should have
been, a rendering for the prompt and the thread. `parse` now consumes a leading
H1 that matches the supplied title instead of making a section of it.

*`_fingerprint` compared `repr(block.data)`.* Dict `repr` is sensitive to key
insertion order; PostgreSQL's JSONB is not, and returns object keys in its own
order. So every section holding a table reported as changed after a round-trip
through storage, with nothing about the document altered — a pure representation
difference. The comparison now serialises `data` with sorted keys, exactly as
`Document.content_hash` always has. Values are still compared exactly; only the
key order, which the canonical model does not preserve, is normalised.

*And grounding had no scope.* It walked every section and mutated in place, so a
revision whose ledger differed from the create-time ledger deleted figures from
sections nobody touched — demonstrated: a bullet reading "CET1 closed at 14.9
per cent" removed outright from an untouched section. `check()` now takes the
set of headings the model actually drafted and records the rest as `attested`.
Nothing about the draft is checked less strictly: sections carried forward are
byte-identical to an approved version that was grounded when it was written, and
re-checking them against a different ledger is a false test, not a stricter one.

The live check now compares stored canonical against stored canonical, and
prints for each differing section the canonical hash on both sides, the rendered
text hash on both sides, the first differing field, the first differing
character with its codepoint, and a verdict of canonical drift or render
normalisation.

**PB-015 — 10, 11 and 13 were structural numerals, not claims.** Reproduced
byte-identically: a thirteen-item numbered list whose prose happened to carry 1
to 9 and 12. They are the tenth, eleventh and thirteenth *markers* of that list.
`pdf_writer` draws them as literal text (`f"{i}."`), `pypdf` reads them back as
prose, and the canonical `Document` stores list items without their ordinals —
so a marker can never be in the allowed set. Markers 1 to 9 and 12 escaped only
because those digits appeared elsewhere in the report. Word was never affected:
it writes ordinals as a list style and page numbers as `PAGE` fields, which come
back as "Page  of" with no digits at all. Two further channels of the same class
were found and fixed with it: `Page {n}` furniture on any PDF long enough, and
`doc.meta`, which every writer renders and `plain_text()` omitted.

The distinction is positional and never by value. A numeral is structural only
when it is a leading ordinal whose line is a heading or ordered-list item **of
this document**, or a line that is nothing but page furniture. Everything else
on every line still has to be supported — in "10. SAR 10 million was drawn" the
marker goes and the claim stays. `SAR 10 million`, `10%`, `Stage 10`, `10 basis
points`, `10 accounts` and `10.0` are all still rejected when the document does
not state them, and each has a test saying so beside the test that accepts the
same digits as a marker.

## What is genuinely not done

Stated here rather than left to be discovered.

1. **Every live behaviour.** `ANTHROPIC_API_KEY` is not set in this
   environment, checked repeatedly through the work and again at the end. Six
   requirements are BLOCKED on it and nothing else: PB-013, PB-015, PB-017,
   PB-029, PB-030, PB-043. The pipeline around the provider is tested against a
   scripted one; that is not live verification and is nowhere reported as
   though it were.

   The suite that closes them is written and waiting.
   `backend/validation/live_playbook.py` holds eight checks — one per blocked
   requirement, plus live streaming and all four file formats — as production
   code, so a deployment can run them without shipping the test suite.
   `tests/playbook/test_live_playbook.py` drives them and skips honestly
   without a key; `scripts/playbook_live_slice.py` runs the vertical slice and
   then the suite, and exits 2 rather than 0 when there is no credential. The
   whole thing is about twelve provider calls, declared before any is spent,
   against synthetic evidence only.

   Eight structural tests run everywhere and guard the suite itself: that every
   blocked requirement still has a check, that every check has a runner, that
   the cost stays bounded, and that it refuses to run rather than passing when
   there is no credential.
2. **Nothing about streaming.** Implemented end to end and verified in a real
   browser. There is still no percentage anywhere, because there is still no
   honest basis for one — the states are real steps, not a bar on a timer.
3. **What If.** DEFERRED-INTEGRATION. No such module exists on this baseline.
   The adapter contract, a payload example, a contract test and six labelled
   fixture exports ship; `INTEGRATION_NOTES.md` names the hook a future branch
   must call. No live cross-module claim is made.
4. **CI.** GitHub Actions has never run on this repository — `total_count: 0`
   before and after every push on this branch. CI is not a source of
   verification here; everything recorded above was run locally and the
   commands are in this file.

## Next action

Human UAT, and the live slice once a credential is in the environment. Nothing
in the implementation is waiting on a decision.
