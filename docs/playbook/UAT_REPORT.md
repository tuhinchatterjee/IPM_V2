# Playbook — UAT report

Everything below happened. Nothing is recorded here that did not run, and a
check that could not run is `BLOCKED` rather than a pass. **Nothing is BLOCKED
any longer**: every live-provider criterion has now been exercised against
`claude-opus-5` with recorded request ids.

## Status

| Dimension | State |
|---|---|
| Standalone implementation | **complete** — chat-first workspace and the Document Intelligence dashboard, back end and front end |
| Deterministic demo and downloads | **passed** — 3 workspaces, 30 exports, 14 real files |
| Live Claude workflows | **all six PASS on live `claude-opus-5` with recorded request ids** — PB-013, PB-015, PB-017, PB-029, PB-030, PB-043. No silent downgrade on any run. |
| Browser and artifact UAT | **passed** — 105 workspace checks, 185 dashboard checks (370 over two cycles), 62 artifact checks |
| Cross-module integration | Cockpit, Early Warning, Scorecard Validation, Lenses **verified**; What If **DEFERRED-INTEGRATION** |
| Human UAT | **pending** — the developer cannot award the user's sign-off. Everything it needs is verified and running; see *Running human UAT* below. |
| Git handoff | committed and pushed to the feature branch; **not merged** |

## Live provider verification

Every criterion that needed a real provider has now been run locally against
this branch. Each carries its served model, its timing and its request id.

| ID | Live check | Result |
|---|---|---|
| PB-015 | `no_template_report` — a complete report from evidence alone, inventing no test | **PASS** — 16 sections; saved report grounded; 0 unsupported financial figures; 0 unsupported tests; required supported figure 22.77 retained; 1 turn, 0 tool calls, Skills off; authoring 86.1s, local rendering 3.7s, check 90.4s; `req_011Cf11GfGASgT27yejEhJVm` |
| PB-017 | `scoped_edit` — a scoped edit changes its scope and nothing else | **PASS** — executive summary edited, unrelated model rewrites discarded by the deterministic scoped merge, V1 preserved, V2 written, supported figures preserved; check 136.6s, authoring 52.9s, local rendering 0.2s |
| PB-030 | `author_model` — the configured AUTHOR model answered and was not swapped | **PASS** — requested `claude-opus-5`, served `claude-opus-5`, no silent downgrade, on every run |
| PB-013 | `coverage_matrix` — a methodology is checked without editing anything | **PASS** — 2 tables produced, the report it checked unedited; check 52.3s, authoring 51.6s, rendering 0.1s; `req_011Cf11d9qC1ChjDNvYfq89c` |
| PB-029 | `seeded_continuation` — a seeded thread continues by calling the real model | **PASS** — `origin=assistant_live`, requests=1, job=1; check 17.5s; `req_011Cf11gwHzRuCLQYt4V7Vt5` |
| PB-043 | `fresh_prompt` — a question absent from every fixture is genuinely answered | **PASS** — answered by the real model; check 20.1s, authoring 19.5s, rendering 0.1s; `req_011Cf11iCUKv9UUfxkinUmSe` |

The final targeted run of the three remaining checks: **3 passed, 0 failed,
suite total 90.3s.** Every provider call on this branch was made from a local
machine by the branch owner; none was made from the development container.

`backend/validation/live_playbook.py` holds the suite in production code rather
than in the test tree, so a deployment can run it without shipping tests —
the lesson `backend/validation/live_smoke.py` was written to record. To repeat
it:

    .venv/bin/python scripts/playbook_live_slice.py     # slice, then the suite
    .venv/bin/python -m pytest tests/playbook/test_live_playbook.py -m live

Run without a credential the slice prints the reason and exits **2**, never 0,
so a run that did not happen can never read as a pass:

```
CANNOT RUN: ANTHROPIC_API_KEY is not set. …
Live generation is therefore UNVERIFIED, not passed.
```

The eight live checks in that suite are the only tests marked `live`; they skip
in the ordinary run, and a skip is counted as a skip.

### What the live runs cost to get right

Three of these passed only after real live failures were root-caused. Recorded
because the failures are the evidence that the checks mean something:

* a 281s read timeout, because one call was authoring *and* driving the document
  Skills — authoring is now text-only by default and rendering is local;
* `10, 11, 13` rejected in a rendered PDF, which were ordered-list markers the
  renderer draws and the canonical document does not store;
* 13 unrelated sections reported changed on a scoped edit, which were a Markdown
  merge base that dropped every citation locator plus a fingerprint sensitive to
  dict key order that JSONB does not preserve;
* `grounding FAILED`, which was the check asserting the state of the model's
  first draft rather than of the saved report, plus an extractor that demanded
  evidence for `CET1`, `IFRS 9`, `v2.1`, `see section 10.2` and `30 June`.

PB-016 is **PASS**, and now so is applying the resulting instruction to a
document: deciding a numbered proposal is implemented, tested at three levels
and driven through a real browser, and the live path that applies it is PB-015.

## Test counts

| Suite | Command | Result |
|---|---|---|
| Playbook backend | `pytest tests/playbook` | **1037 passed, 8 live checks skipped, 0 failed** |
| Affected backend | `pytest tests/api tests/demo tests/exports tests/docs tests/services tests/llm tests/proof tests/validation` | **1113 passed, 8 skipped, 0 failed** |
| Full backend | `pytest -q` | **10,528 passed, 30 skipped, 0 failed** |
| Frontend units | `npm test` | **516 passed, 0 failed** |
| Frontend types | `tsc --noEmit` | clean |
| Frontend lint | `eslint` | clean |
| Frontend build | `next build` | succeeds; `/playbook`, `/playbook/[id]`, `/playbook/[id]/status` and `/playbook/library` emitted |
| Python lint | `ruff check .` | clean repository-wide |

## Browser acceptance

`scripts/acceptance/playbook_browser_acceptance.py` — real Chromium, real front
end, real backend, at 1366×768 and 1600×900. **105 passed, 0 failed.**

What it proved, rather than what it looked at:

- The home screen is in §3's order — the composer above Recent Playbooks above
  Recent Exported Analyses — measured by bounding box, at both viewports.
- The plus button is inside the composer and its menu offers exactly two
  sources.
- A quick prompt fills the composer and **generates nothing**.
- A seeded thread reopens with all 14 of its messages, labelled synthetic.
- The DOCX and PDF downloads are real bytes with the right magic numbers
  (39,189 and 4,361 bytes), not renamed text.
- The picker lists 30 exported analyses; previewing one and coming back leaves
  the selection at "2 selected".
- Escape closes the dialog; no console errors at either viewport.
- A real .docx uploads through the composer, appears as a chip and can be
  removed; with no provider configured Send is refused and the reason is on
  screen, rather than a button that fails after it is pressed.
- An earlier version is restored from the files pane and the restore moves
  forward: v1 comes back as v3, v2 is still there, the change summary says
  where v3 came from, the downloaded file is byte-for-byte the file that was
  reviewed as v1 under a v3 filename, and restoring the version already current
  is refused.
- The answer arrives while it is being written: a page attached to a running
  generation shows what has been written so far, text written on the server
  afterwards appears without a reload, the state moves from "Reading the
  sources" to "Writing" as the work moves, and the Markdown is rendered rather
  than printed as source.
- A refresh mid-generation keeps the answer so far and starts no second
  generation — the same job id is still the one running — and no answer is in
  the thread while the stream is unfinished.
- Stop mid-stream marks the running generation cancelled, the screen says it
  was stopped rather than leaving the half sentence on display, and no artifact
  version was written.
- A source's kind is a control rather than a fixed label: correcting it is
  recorded as a person's decision, reaches the database, survives a reload, and
  a kind that is not one of the five is refused.
- Any version can be read in the application without downloading it, and the
  preview offers the file rather than replacing it. Escape closes it.
- A five-item proposal is decided in the interface: changes 1, 2 and 5 are
  approved and 3 and 4 held; ticking change 3 pulls in change 2, which it rests
  on, rather than accepting an approval that could not stand; the resulting
  instruction names the approved sections and names the held ones as held; and
  after a reload the panel still says the same thing.
- The API refuses an id that was never exported (404), a foreign workspace
  (404), a greeting as an export (422) and Project Planner as a module (422).
- The monitoring Playbooks feature still answers 200.

Screenshots: `docs/playbook/screenshots/`. Evidence:
`docs/playbook/browser_acceptance.json`.


### The Document Intelligence dashboard

`scripts/acceptance/playbook_dashboard_acceptance.py` — real Chromium, at
1366×768, 1440×900 and 430×900. **185 passed, 0 failed**, and **370 passed, 0
failed over two consecutive cycles**.

The second cycle is the point. A run that answers a finding and confirms a
metric suggestion and then stops has changed the demonstration; the harness
restores what it touches, and running it twice is how that claim is tested
rather than asserted. The two cycles produce identical counts.

What it proved, rather than what it looked at:

* Opening a Playbook still shows the conversation first, with the compact
  status panel beside it and a KNOW THE STATUS action stating how ready the
  document is.
* A half-typed sentence, its attachments, the selected analyses and the scroll
  position all survive CHAT → STATUS → CHAT.
* Completion and readiness are shown as two numbers and never combined.
  Readiness is explainable: each component opens to say what it is made of.
* A committee document is asked about meeting dates and committee decisions; a
  non-committee document is not, and no meeting date is invented for it.
* Since Last Time refuses to subtract two readings whose population differs,
  shows both readings, empties the change column, and names the dimension.
* A metric the catalogue suggested stays a suggestion and is counted outside
  coverage until a person confirms it.
* A governance form is a labelled modal dialog, focus moves into it, Escape
  closes it, and focus returns to the control that opened it.
* Re-reading a source writes a new parse revision, supersedes the old one, and
  writes no document version.
* An empty Playbook explains itself instead of showing noughts.
* At all three widths nothing escapes the viewport; wide tables scroll inside
  their own boxes, measured rather than assumed.

Evidence: `docs/playbook/dashboard_acceptance.json`, and the twenty-one
screenshots in `docs/playbook/screenshots/`, each captured in the state the
check beside it had just asserted.
## Artifact verification

`scripts/acceptance/verify_playbook_artifacts.py` — **14 files, 62 checks, 0
failed.**

Every file was reopened with the same parsers Playbook uses on user uploads and
checked against the document it was rendered from. Every PDF page was rasterised
and inspected for blankness, collapse, content past the margin, and missing
fonts. Rendered pages: `docs/playbook/artifact-pages/`.

## The demonstration

| | |
|---|---|
| Workspaces | 3 — IFRS 9 Committee Report, Application Scorecard Model Development Report, Behavioural Scorecard Validation Report |
| Messages | 12, 14 and 14 |
| Input files per workspace | 3, all parsed through the real ingestion |
| Attached analyses | 5, 4 and 5 |
| Versions per report | 2, with different content hashes and a parent link |
| Generated files | 14 (DOCX, PDF, PPTX) |
| Exported analyses | 30 — six each from Cockpit, Early Warning, What If, Scorecard Validation and Lenses |

The IFRS 9 thread carries a five-item change proposal with **four applied and
one held back**, and version 2 does not contain the held change.

Every workspace opens onto a populated dashboard. The IFRS 9 one is the
committee example:

| | |
|---|---|
| Governed metrics | 4 confirmed, 1 left suggested so the review path is visible |
| Since Last Time | 4 rows — 3 compared, 1 refused on a population that moved |
| Findings | 4, across four origins, 1 blocking |
| Decisions | 2 — one recorded, one outstanding |
| Actions | 2 — one in progress, one overdue |
| Sections | reviewed and approved states on the sections a reviewer looked at |
| History | 42 events across all eight kinds |
| Readiness | *blocked*, strictly between 0 and 100, with three named blockers |
| Statistics | page count measured from the rendered file, not declared |

Two properties are held by tests rather than left to chance. It never opens at
100% — a demonstration that opens complete demonstrates nothing. And it shows
a refusal to compare: Stage 2 exposure carries the same label in both packs and
moved from SAR 72.00m to SAR 113.00m, which by label is a 57% jump onto a
committee agenda and is in fact a change of population from the corporate book
to corporate and SME. A demonstration in which every pair happens to be
comparable teaches the reader the opposite of the rule.

## Journeys

| Journey | State |
|---|---|
| 1 — Home and seeded history | **passed** (browser acceptance) |
| 2 — Picker and export boundary | **passed** (browser acceptance + API boundary) |
| 3 — Prior report + methodology + new results | **passed** — sources with correctable roles, the gap manifest and partial approval verified in the browser; the coverage framing sent to the author is asserted; and running the review is now proven live (PB-013, 2 tables, the checked report unedited) |
| 4 — No-template report | **passed** — proven live (PB-015): 16 sections from evidence alone, grounded, inventing no test, both files produced |
| 5 — Continue, revise, present | **passed** — versions, lineage, restore, the in-app preview and a real PPTX verified; and performing the revision is now proven live (PB-017 scoped edit, PB-029 seeded continuation) |
| 6 — Fail safely | **passed** — provider-not-configured, validation failure, stale base, duplicate send, cancellation |
| 7 — Authorization and untrusted content | **passed** — 29 security tests plus the API boundary |
| 8 — Regression and fresh state | **passed** — isolated database, idempotent reseed, edited thread preserved |

## Defects found and fixed during verification

1. **Thirty exports collapsed into five.** With no source identifier, every
   export in a module resolved to the same identity and became a *revision* of
   its predecessor. Found by writing the status check. Fixed: the title is now
   the fallback discriminator.
2. **AUC below 0.5.** The first scorecard fixture used a hand-rolled binary
   search that was wrong, making Gini negative. Found by its own test. Fixed by
   using the standard library.
3. **Source locators read as reported figures.** `fixture://…@1.0.0` put "0"
   into the figure set, so every references appendix failed validation. Fixed:
   locators are stripped before figures are extracted, on both sides.
4. **Live verification call estimates.** Adding the AUTHOR role moved quick mode
   from 15 provider calls to 16; the PowerShell mirror still said 15. Caught by
   `test_the_cost_table_matches_the_python_side`.
5. **Test isolation.** The first Playbook DB fixture committed. Now each test
   runs in a rolled-back transaction, and the API tests remove what they create.
   Two consecutive full runs leave zero rows.
6. **A test suite that wiped the demonstration.** The API tests shared the
   developer's database with the seeded workspaces and cleaned up by truncating
   the Playbook tables, so running them destroyed the demonstration they were
   testing against. Found when the browser acceptance reported nought seeded
   playbooks. Fixed: the tests record a high-water mark and delete only above
   it.
7. **A stale acceptance assertion.** The browser check looked for the word
   "Demo" on the thread page. The product-copy rule forbids that word, so the
   label a user sees is "Synthetic data" — the check was asserting the copy the
   repository bans. Fixed to assert both the badge and the per-message note that
   the reply was not written by a model.
8. **The dashboard named the vendor on screen.** The product forbids any string
   a normal user reads from naming an intelligence provider or model, and the
   dashboard broke it in eight places — four "Ask CreditProbe" buttons that had
   said otherwise, two governance notes, the metric table's action label, and
   the origin shown against a suggested finding. Found by the whole-repository
   suite; every subset being run at the time excluded `tests/release`.

   Two of the eight were beyond the reach of the check that should have caught
   them: its frontend scan reads rendered strings and cannot see a label the
   server sends, and its route scan walks eight fixed routes, none of them
   Playbook's. The rule now also scans the backend's own user-facing label
   tables, which needs no seeded fixture and cannot be outrun by a route the
   list forgets. That immediately found one more — `GET /playbook/capabilities`
   was returning the provider name and the model to the browser, where every
   other surface withholds them; it now goes through the same
   `product_copy.withhold_identity` helper two other routers already use. The
   audit route and the telemetry ledger still record which model produced which
   answer.

## The first live run, and what it found

A real provider run happened locally against `713f99a`. `claude-opus-5` served
with no downgrade, and parsing, the ledger, versioning, DOCX and PDF generation,
validation, persisted bytes, reopening, version 1 preserved, version 2 genuinely
different and 22.77 carried across all held. Four things did not:

| Finding | Root cause | Status |
|---|---|---|
| Word and PDF did not state 19.20 | The assertion was wrong twice over: 19.20 is a scenario INPUT, not a reported result, and the fixture stores it as a float so the evidence carries "19.2". Grounding normalises trailing zeros, so it could never have enforced the difference. | Assertion replaced with the system's own comparison; money now formatted to two decimals on its own merits |
| Scoped revision introduced an unsupported figure | A revision was judged against the sources alone, so restating an approved version-1 figure read as invention; and exact-token matching correctly catches re-rounding (8.95 → 8.9) | Approved version admitted as evidence; prompt forbids re-rounding; grounding untouched |
| The suite hung in the streaming iterator | `timeout=900.0` as a bare float set all four transport phases to 900s, and a read timeout bounds inactivity, not the operation | Four separate transport timeouts plus an enforced wall-clock run deadline |
| `Messages.stream() missing 'model'` | The Messages API has no server-side default model; the code assumed one | `AUTHOR_MODEL_NOT_CONFIGURED` before the client is built |
| **Human UAT:** a real Auto Loan scorecard report was refused with "1 section(s) are missing: *Auto Loan Application Scorecard (AL-AS-v1.0) — Model Development and Validation Report*" — the document's own title | `parse` is given the artifact's label and the author writes the report's title as an H1; when the two differed word for word the H1 became an ordinary empty Section, so the title was in the canonical model twice and the validator looked for a chapter that never existed | Folded back at the canonical boundary: a first heading with no content of its own, followed by more sections, is the title line. The document's wording wins; the artifact label is a separate field |
| **Human UAT, second defect behind the same message:** the DOCX passed and the PDF failed on the identical document | reportlab wraps a long heading, so the PDF text layer holds "…Model Development\nand Validation Report", and the validator's presence test was a raw substring match that cannot see across the break — it would have rejected any genuinely present section whose heading was long enough to wrap | Headings are compared whitespace-flattened on both sides, and the title is checked as a title with its own diagnostic rather than as a section |
| **Human UAT:** an Auto Loan report was refused for stating full-precision floats "in no source" — 0.5593220338983, 0.477011494252873 and six more, all of them cells of the attached workbook | `sheets` recorded `str(cached)` and never read `cell.number_format`, so a cell storing 0.5593220338983 and displaying 0.559 reached the ledger as seventeen digits; grounding matches exactly, so a report writing the readable 0.559 had it removed as unsupported and the only way through was to print the raw float | Ingestion keeps all three — stored value, displayed value and cell address — the ledger admits both readings of one cell, and presentation precision comes from `calc.DISPLAY_DP`, the table that already separates a value from the way it is shown |
| **Human UAT, second defect behind the same message:** the same figure passed in Word and failed in the PDF | validation built its allowed set with `figures()`, which returns only evidence-BEARING numbers, and that classification reads the word before a number. "Note 0.559" is one line canonically, where "Note" makes it a section reference; a PDF puts each cell on its own line, where it is an ordinary count. Present, not allowed | Whether a figure needs evidence is grounding's question and is settled before rendering; validation compares every numeral on both sides, so the two representations can no longer disagree |

None of these were counted as passes when they were found. Each was fixed, given a regression test in the shape of the failure, and then re-run live; the live results are in *Live provider verification* above.

## What is genuinely not done

1. **Human sign-off.** Every live behaviour is now verified — six criteria on
   real `claude-opus-5` calls with request ids — but a developer cannot award
   the user's acceptance. That is what remains, and *Running human UAT* below
   says exactly how to do it.
2. **Nothing about streaming.** Implemented end to end and verified in a real
   browser. Still no percentage anywhere, because there is still no honest
   basis for one.
3. **What If.** DEFERRED-INTEGRATION — the module does not exist here.
4. **CI.** GitHub Actions has never run on this repository, before or after any
   push on this branch. Everything above was run locally.

## What streaming is proven with, and what it is not

The browser journey drives a real SSE connection, the real parser and the real
incremental rendering, against events a fixture writes on the server. That
proves the **transport** and everything around it — replay, reconnect, refresh
safety, cancellation, the refusal to show a partial answer as an answer.

The browser journey itself is not a live generation and is not recorded as
one: what a real provider adds to the path above is `text_delta` events instead
of fixture ones. Live streaming through the real provider is covered separately
by the `streaming` check in `backend/validation/live_playbook.py`. The filter
that decides which of the provider's events may be forwarded is asserted
directly in `tests/playbook/test_streaming.py`, and the live slice exercises the
whole path the moment a key exists.

## Known limitation, stated rather than discovered later

**Grounding proves traceability, not truth.** A figure survives because it
appears in the evidence — and an uploaded document is evidence. A source
asserting "coverage is 41.5 per cent" makes that figure quotable, and a report
citing it is behaving correctly even if the source is wrong. What grounding
removes is the figure that came from nowhere. This is asserted by a test rather
than left implicit.

**The dashboard reports state; it does not judge it.** Readiness is arithmetic
over governed rows — what is outstanding, what is unreviewed, what is
unconfirmed, how much is written. It is not an opinion about whether the paper
is any good, and a document can reach 100% readiness while saying something a
committee should reject. The panel says what is outstanding, never whether the
conclusion is sound.

**Two accessibility findings belong to the application shell, not to Playbook.**
The sidebar marks a non-live navigation item with a coloured dot whose only
word is a hover tooltip, and the shell overflows at 430px — both on every route
in the product, `/playbooks` included. The dashboard's own region is clean on
both counts, and the §32 sweep is scoped to it so that a shell limitation is
neither hidden nor counted as this work's pass.


## Running human UAT

Against this branch, with the isolated development cluster. Nothing here needs a
provider key except the last line, and the application is fully browseable
without one.

```bash
git checkout claude/creditprobe-playbook-plan-ky3m05

scripts/playbook_dev_env.sh start                       # Postgres on 55432
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/bootstrap_demo.py --step playbook

set -a && . ./.env && set +a
.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
npm --prefix frontend run build && npm --prefix frontend run start

# optional, costs money, and was already run:
.venv/bin/python scripts/playbook_live_slice.py
```

Then open **http://127.0.0.1:3000/playbook**.

Three seeded threads are waiting there — the IFRS 9 committee report, the
application scorecard model development report and the behavioural scorecard
validation report — each resumable, each with real generated files. The existing
monitoring feature is unchanged at **/playbooks**, now labelled *Monitoring
Playbooks* so the two are distinguishable on screen.

The branch is pushed and **not merged**. No pull request has been opened.
