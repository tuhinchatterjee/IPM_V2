# Retail Demo · AdvancedCockpit candidate — handoff

**Status: READY FOR MAC ACCEPTANCE — provider test still required.**

Every deterministic gate that can run in this container has run. No provider
call was made, and none was possible: the credential is unset and the shipped
price card is a placeholder that fails closed. So nothing here claims anything
about answer *quality*. What it claims about the architecture, the numbers and
the isolation is measured, and the measurements are named below.

---

## 1. Candidate commit

The tip of **`claude/modest-rubin-cm037o`**. Take the branch tip rather than
a SHA written here: this document is committed on that branch, so any SHA it
names is necessarily one commit behind itself.

    git fetch origin claude/modest-rubin-cm037o
    git rev-parse origin/claude/modest-rubin-cm037o

Thirteen commits this session, starting from `ec8835d4`. Nothing merged, no
pull request opened, and the branch is not based on anything but the
candidate line you approved.

## 2. The release

| | |
|---|---|
| Release id | `cockpitdata-r1.2.0-c1.0.0-s20260910-p7` |
| Fingerprint | `d680f22767c64699` (`…b0adcb60da31d98fd1efe1267c59ef2daff5af33b8785a89`) |
| Projected from | `retail_facility_month` `r1.2.0-c1.0.0-s20260910`, manifest `3268b725456df9c4…` |
| Shape | 5 relations, 4,163,524 rows, 302 fields, 25 months 2024-08 → 2026-08 |
| Size | 518 MB |

`p1`, `p5` and `p6` are retained untouched. `p1` is the millions-only release
kept as failed evidence.

## 3. What changed

**Blocker 1 — money steering.** The rule now reaches the analyst before its
first action, carried in each relation's manifest `grain`. That is the one
piece of manifest prose `context.build` puts in the starting packet, and it
lands twice — in the catalogue index and on every canonical measure. It is
also the right field on the merits: grain says what one row *is*, and "a
facility is a small fraction of a million, so read the riyal column" is a
fact about money on one row. Measured, not assumed: 25 occurrences in a real
packet, on a question whose readiness says go straight to `execute_analysis`
— which is exactly the path that never called `inspect_catalog`. No core
edit. `origin`, `not_client_data` and `ui_filters` were considered and
rejected.

**Blocker 2 — the Home feed.** `retail_customer_month.score_migration` is
derived to the definition the engine's own generator uses: the unweighted
mean of the customer's facility scores, a dead band of ±2 score points,
`IMPROVED` / `STABLE` / `DETERIORATED`. One stated difference — the previous
mean is taken over the *same* facilities from the column this book publishes
for the purpose, rather than carried across months, so a customer who opened
a facility does not register a movement they did not have. Five behavioural
columns come with it so the label is auditable from the release. The feed
computes: 5 cards, no `BinderException`, no xfail.

**V3 startup.** The engine no longer needs a pre-domain release. The host
defines the two `cockpit_agentic` settings the ported package reads (write
switch off), and a candidate bootstrap assembles the `Runtime` from the
domain release and installs it through `routes.install`.

**Host and UI.** Engine as its own process; retail API proxy at
`/api/v1/cockpit-v4/*`; identity forwarded from the session the app already
authenticated, with a per-launch shared secret; `CockpitV4Home` mounted in
`app/page.tsx` as a sibling of the legacy Cockpit, never a branch inside it.

**Also fixed:** `frontend/src/components/layout/content-width.tsx` did not
exist and the ported tree imports it — frontend typecheck and `next build`
were **broken on this branch** before this session.

## 4. Protected-core diff

    backend/cockpit_v4/catalog.py    C2
    backend/cockpit_v4/domains.py    C1

Unchanged from what you approved. **No third core edit was needed.**
`backend/cockpit_agentic` is byte-identical. `scripts/retail_cockpit/verify_port.py`
reports **291 of 291 ported files unchanged, 0 missing, PORT VERIFIED**.

## 5. Evidence the analyst architecture is preserved

**The frozen suite, run against this book.** `COCKPIT_V4_TEST_RELEASE=…-p7`:
**793 passed, 1,501 skipped, 21 failed, 6 errored.** No ported test edited,
deselected or weakened. Every failure triaged in `PORTED_SUITE_TRIAGE.md`;
all are book-, deployment- or environment-specific, and one that was real was
fixed. The 793 include the action state machine, tool contracts, intent
validation, SQL safety, join-grain refusal, repair, clarification, evidence
binding, display and precision policy, chart forms, event-contract parity and
budget envelopes.

**Seven chains over Cockpit Data** (`tests/retail_cockpit/test_chains.py`),
real worker, real store, real event stream, real DuckDB, only `converse`
scripted: an analysis runs and binds its claim to its artifact; three chart
forms are carried when three are asked for; a facility-level answer renders
`SAR 102,340` and not `SAR 0 million`; SQL naming an unpublished relation
never reaches the database; a broken query is repaired and the reader sees
the repaired answer; a declared ambiguity has execution taken away **by the
server**, the next turn offered exactly one tool; a follow-up stays in the
thread, carries the first question's original wording, and stands on its own
artifact.

## 6. Cockpit Data only

`tests/retail_cockpit/test_isolation.py`, **16 passed**. Eight SQL attempts —
the corporate relation, the same through `UNION`, `ATTACH`, `read_parquet` on
the source lake, `read_csv_auto('/etc/passwd')`, `COPY` to a file,
`INSTALL httpfs`, `glob('/**')` — each refused in the session.
`enable_external_access` is false and locked.

Stronger than asserted at the outset: the governance columns are **consumed
by the materialisation filter and are not in the session at all**. There is
no `dataset_release_id` to write a predicate against. Row counts match the
manifest exactly.

Also: the catalogue the model sees names this book only; a corporate field id
comes back without its definition; a run may not name its own release;
another tenant's thread and artifact are unreadable.

**The retail app's own default-deny covers the Cockpit.** With
`REQUIRE_LOGIN=true`, every proxied route answers 401 without a session —
`/cockpit-v4/domains`, `/session`, `/attention` and `POST /threads` — while
`/api/v1/health` stays public. Measured, on a server started for the purpose.
The proxy is inside the app's security boundary, not beside it.

The retail suite's own allowlist sweep (`test_no_route_answers_that_is_not_on_the_allowlist`)
skips parameterised paths, so it would not have caught a mistake here either
way; this is why it was checked directly rather than assumed from a green
suite.

## 7. Numerical oracles

**28 of 28 agree.** Each computed with pandas from the *source book* by a
different implementation, compared against the engine's own session. Every
monetary case asserts both denominations; every ratio is a ratio of sums;
customer-grain figures are de-duplicated first. Q19 carries the de-duplication
defect alongside the answer so the gap is a number, not a claim. Q21 runs the
**ECL panel itself** against an independently attributed movement; components
reconcile to a residual of 5.6e-15. Output: `docs/retail_cockpit/evidence/oracles.txt`.

## 8. Attention

Full feed computes: 5 cards on 2026-08 vs 2026-07, all nine retail families
bind and execute. The xfail is promoted to a passing assertion.

## 9. ECL

Panel and movement both work. Stages (SAR million): 1 → EAD 5,977.7 / ECL
19.50; 2 → 396.3 / 16.80; 3 → 52.0 / 22.31. Movement 51.908 → 58.608.

## 10. Multi-turn

Section 5 above. Live conversational quality is **NOT VERIFIED** — it needs a
provider.

## 11. Browser

`tests/retail_cockpit/browser/candidate.browser.mjs`, **five cycles: 135 of
135 checks passed.** (27 checks a cycle since F2 added the ask-and-watch
journey: the question reaches the thread, the process panel renders, it lists
the stages the run went through, and the thread never reads "0 messages".) The badge reads *Retail Cockpit · Retail Credit ·
monthly · 25 months 2024-08–2026-08 · SAR million · cockpitdata-…-p7*, every
value from the release. The legacy Cockpit's requests never fire. Every
Cockpit call goes to the retail origin; the browser never reaches the
engine's port. ECL panel and attention feed compute. The shell still offers
Projects, Investigations, Data Builder and What-If; Data Builder loads;
navigation away and back, and reload, all survive.

    CANDIDATE_CYCLES=5 CANDIDATE_UI_URL=http://localhost:5329 \
    CANDIDATE_API_URL=http://127.0.0.1:8329 \
    CANDIDATE_ENGINE_URL=http://127.0.0.1:8415 \
    node tests/retail_cockpit/browser/candidate.browser.mjs

The five checks that used to fail were one defect, now closed (§19.1). The
ECL caption on the page reads, in full:

    4 distinct ECL developments — by product and across the book.

## 12. Retail non-regression

`tests/retail`, same environment, same book, run at HEAD and at the session
baseline `ec8835d4`:

| | passed | skipped | failed | errored |
|---|---|---|---|---|
| baseline `ec8835d4` | 1,172 | 1,500 | 48 | 60 |
| HEAD | 1,176 | 1,484 | 62 | 58 |

The two failure sets differ **in both directions** — four tests fail at HEAD
and not at the baseline, and several fail at the baseline and not at HEAD.
That asymmetry is the signature of order- and state-dependence, not of a
regression, and it was chased down rather than explained away.

The cause: during the HEAD run an ad-hoc backend was up on 8328 with
`REQUIRE_LOGIN=false`, and the workspace was partially seeded. The baseline
run had neither. The access-control tests reach out to a live backend and
**skip** when none is answering, so they can only fail when one is running
open.

Re-run at HEAD with nothing else running:

- `TestTheAPIIsDefaultDeny` — every test passes or skips. Neither
  `test_bank_content_needs_a_signed_in_caller` nor
  `test_no_route_answers_that_is_not_on_the_allowlist` fails.
- `TestTheWorkspaceIsNotEmpty` — one failure,
  `test_the_seeder_reports_ready` ("retail working messages: 0 of 3"), which
  is the **identical single failure the baseline produces** when run the same
  way. An unseeded workspace, at both commits.

**So none of the four is caused by this integration.** The proxy is also
covered directly rather than inferred: with `REQUIRE_LOGIN=true` every
Cockpit route answers 401 without a session (§6).

One caveat worth stating: this container has no seeded workspace and no
Early Warning model records, so a large block of `tests/retail` cannot pass
here at either commit. The comparison is like-for-like and that is what makes
it meaningful; it is not a claim that the retail suite is green.

## 13. Export / save / project / investigation

Routes are proxied and reachable; their persistence is exercised by the
ported suite's `test_collaboration_and_threads.py` and `test_export.py`
(passing). End-to-end through the browser needs a real answer to save, so it
is **NOT VERIFIED LIVE**.

## 13b. The boundary between the proxy and the engine

`tests/retail_cockpit/test_host.py`, **19 passed**, no server needed. No
secret is not a principal; a wrong secret is not a principal; a principal
without an id is not a principal whatever the body looks like; the tenant
comes from the deployment rather than the caller, because a caller who could
choose it could read another deployment's rows; and a caller cannot
contribute either boundary header under any spelling — the outbound header
dict is lowercased as it is built and the two names are dropped before they
are written, so the property does not depend on the framework underneath
normalising names.

## 14. SSE, Stop, reconnect

`scripts/retail_cockpit/check_transport.py`: **PASS, 0 findings**. Through
the retail origin, against an analyst that thinks for 8 s: `model.requested`
at 0.72 s, heartbeat at 5.75 s, terminal at 8.67 s — a **7.96 s gap** a
buffering proxy could not produce, with the heartbeat inside it as an
independent witness. `text/event-stream`, `X-Accel-Buffering: no` and
`Cache-Control: no-transform` all cross intact; ids monotonic; a reconnect
from a cursor replays exactly the tail; Stop cancels a run in `MODEL_RUNNING`
and a second Stop is idempotent.

## 15. Memory

Re-measured on `p7` — the §11 figures are void, the release grew.

| Limit | Cold open | Materialised | Spill | Peak RSS |
|---|---|---|---|---|
| 1536MB (engine default) | 14.7 s | 1,392 MiB | 1,096 MiB | **1,994 MiB** |
| 2048MB | 11.3 s | 1,881 MiB | 862 MiB | **2,324 MiB** |

Query latency is flat either way: 4.0 ms simple, 58 ms diagnostic.

**Recommendation for the Mac: no override.** Your machine reported 3,033 MiB
available; the engine default needs ~1,994 MiB resident, leaving ~1,039 MiB.
2048MB would leave ~709 MiB, which is too tight beside a browser. The
decision rule stands: ≥3,500 MiB available → 2048MB; below that → leave it
unset.

## 16. Launcher

`launchers/retail/start-retail-candidate.command` and
`stop-retail-candidate.command`. Ports 5329 / 8329 / 8415 — the demo's
5328 / 8328 untouched. Refuses a port in use rather than reclaiming it;
refuses to start without `node_modules` rather than symlinking one; generates
the boundary secret per launch; waits for the book to materialise; and prints
READY only after `scripts/retail_cockpit/check_ready.py` confirms the whole
path — book open, boundary refusing unauthenticated calls, a question
accepted, and the event stream opening with its no-buffering headers. The
stopper kills only pids it wrote.

`START_CREDITPROBE_RETAIL_DEMO.command` is not replaced.

## 17. What to run on the Mac

    git fetch origin claude/modest-rubin-cm037o
    git worktree add ../ipm-candidate claude/modest-rubin-cm037o
    cd ../ipm-candidate && uv sync && npm --prefix frontend ci

    # 1. publish the release from YOUR book, read-only
    .venv/bin/python scripts/retail_cockpit/publish_release.py --revision 7

    # 2. check it against independent oracles
    .venv/bin/python scripts/retail_cockpit/check_oracles.py \
        --release cockpitdata-r1.2.0-c1.0.0-s20260910-p7

    # 3. memory, at the two limits that are safe on 3 GB available
    .venv/bin/python scripts/retail_cockpit/benchmark_session.py \
        --limits 1536MB,2048MB --repeat 3

    # 4. start it
    cp .env.retail-candidate.example .env.retail-candidate   # then edit
    launchers/retail/start-retail-candidate.command

Do **not** run 2560MB or above on that machine. The benchmark refuses a limit
the machine cannot hold, but the rule is worth stating anyway.

## 18. Live provider work still required

`docs/retail_cockpit/LIVE_UAT_PLAN.md`: 12 runs, standard mode, hard
cumulative cap **USD 15.00**, with the twelve questions, the oracle each is
checked against, and what counts as success. It needs the real price card and
the credential, and your approval, before anything runs.

The single most important question it settles: **does the analyst choose the
riyal column at facility grain without being told twice?** The grain seam is
measured to be in the packet; whether it changes the analyst's behaviour is
not something a scripted provider can tell us.

## 19. Every known defect

1. ~~**A corporate caption on a retail book.**~~ **CLOSED — approved as F1.**
   `attention-panel.tsx` hard-coded *"by sector, by borrower and across the
   book"* on a retail book. You approved the smallest frontend-only exception
   after five host seams were traced and none reached it: the component takes
   only `{ onOpen, domain }` with no slot and no context; the V2 feed carries
   no caption field and adding one edits protected core **and still** needs
   this same frontend edit; the sole import is relative so no module alias
   fires, and a redirect could not wrap because `Card` is module-private; there
   is no i18n layer at all; and a CSS overlay would leave the wrong string in
   the DOM and still fail the check that reads `textContent`. The caption now
   reads the dimension the server actually cut the cards by
   (`attention_v2.py:918`), per book, with corporate output unchanged
   character for character. Full audit, diff and hashes in `PORTED_FILES.md`;
   held by `tests/retail_cockpit/test_retail_vocabulary.py` and by the browser
   suite at five cycles. The analytical-core diff is unchanged: C1 + C2 only.
2. **Failure injection is not covered on this book.** The ported matrix needs
   a pre-domain release; its sentinel correctly refuses to call a partial run
   evidence. Recorded as a gap, not a pass.
3. **`python_analysis_ready` is false.** `pyrunner` reports UNAVAILABLE in the
   frozen source. A source limitation, disclosed, not fixed here.
4. **`/health` on the engine reports stale capability flags.** `create_app`
   closes over the runtime it built (`app.py:125-132`, read by the `/health`
   closure at `app.py:184-196`) and the candidate installs its own afterwards
   through `bootstrap.install`; the route-level guards read `routes._STATE`,
   which bootstrap does update, and are correct. So under
   `RETAIL_COCKPIT_OFFLINE` you will see `release_ready: false` and
   `sql_analysis_ready: false` on `/health` while the Cockpit accepts runs —
   `check_ready.py` handles exactly this, raising the missing-flags finding
   only when the run is *also* not 202 (`check_ready.py:175`). Cosmetic, but
   it will mislead anyone who curls it, and it did mislead during the
   offline-capability diagnosis below.
5. **Two engine processes must not share a runtime directory.** Fixed for the
   candidate entrypoint (each engine gets a spill directory named for its
   port), but the underlying `catalog.py` default is still one directory per
   runtime dir. Anyone running the frozen engine twice will hit it.
6. **`lib/runtime.ts` is a trap.** `servedByCurrentRuntime` is dead code here
   and must stay dead: wiring it, as the ported test asks, would make every
   non-Cockpit retail call throw. See `PORTED_SUITE_TRIAGE.md`.
7. **Frontend lint fails, 16 problems, none of them new.** 4 in
   `what-if/retail-whatif.tsx`, unchanged from the live baseline `c0db151f`;
   12 in the frozen ported tree. Re-run after F1: still exactly 16.
8. **`backend/api/main.py` fails ruff's import-order rule at the baseline
   too.** Pre-existing; not touched.
9. ~~**Offline acceptance was blocked by the live price card.**~~ **CLOSED.**
   A Mac launch from `.env.retail-candidate.example` refused every question
   with `503 CAPABILITY_UNVERIFIED: the price card
   config/cockpit_v4/price_card.json carries no entry for model '…'`. Cause:
   `--offline` sets `verify_model=False`, and `service.load_capability` reads
   that flag at one place only — the live probe at `service.py:141`. The
   price card is read unconditionally at `service.py:136`, so offline removed
   the need for a *credential* but not for a *price*, and a run that calls
   nothing was blocked by the absence of a price for a call it could not
   make. `bootstrap.install` caught the `PreflightFailed`, the runtime became
   `None`, and every analytical route refused. Two template defects of mine
   made it certain on a fresh clone: an `AI_COCKPIT_REASONING_MODEL` I had
   invented (the engine defaults none, and that id is not in
   `model_capabilities.REGISTRY`), and a Mac step that copied the
   fail-closed placeholder card onto a fixture path. Fixed in
   `backend/retail_cockpit_host/offline.py` + a four-line branch in
   `bootstrap.build_runtime`: a provider that **cannot reach a paid API**
   gets an in-process capability that names no model and declares no price.
   The gate is the provider object, never `verify_model` and never an
   environment variable — a real provider with verification off is still
   refused by a card that does not carry its model, proved by
   `tests/retail_cockpit/test_offline_capability.py` (13 tests). Nothing in
   the repository had exercised `capability.load_price_card` before; it does
   now, against the shipped card.

10. ~~**A settled run was invisible on the thread page.**~~ **CLOSED — approved
   as F2.** Asking a question opened a thread reading **"0 messages"** with the
   book's opening chips and no sign anything had been asked. Everything
   upstream was correct: the run was accepted, driven by the real worker and
   settled, with all its events persisted and streamed. The thread page read
   the run's status on mount and returned on a terminal one
   (`thread-view.tsx`), on the assumption that a settled run left a TURN for
   the transcript reload to speak for it. That holds for a run that answered
   and fails for every run that did not — `worker.py` guards `append_turn`
   with `outcome.response is not None` — and `GET /threads/{id}` carries turns
   and no run, with no thread→runs endpoint to fall back on. Measured on this
   candidate's own store: an offline run reaches `FAILED` /
   `PROVIDER_UNAVAILABLE` **0.8 s** after creation, so the page always arrives
   after it is terminal. A **frozen-source defect**, not an integration one:
   it hits the standalone identically for any fast failure (bad credential,
   rate limit, refusal), and no ported test covered reopening a thread whose
   run failed. Fixed by removing the early return, so every recalled run is
   followed — the stream replays a terminal run from cursor 0 and closes on
   `run.settled`, so the panel shows the stages and the reason. Held by
   `tests/retail_cockpit/test_terminal_run_visibility.py` (8 tests) and by a
   new browser check per cycle.

11. ~~**The cumulative spend cap had no mechanism.**~~ **CLOSED.**
   `LIVE_UAT_PLAN.md` promised a hard USD 15.00 cap. Nothing enforced one:
   `budgets.spend_ceiling_usd` bounds a single run at 1.50 and every spend
   query in `run_store.py` is scoped `WHERE run_id=?`, so twelve runs had
   eighteen dollars of headroom against a fifteen dollar cap and nothing
   stopped the thirteenth. Now enforced by the retail proxy on `POST /runs`
   from the engine's own ledger, `SUM(COALESCE(settled_usd, reserved_usd))`,
   counting an unsettled reservation at what it reserved so a burst cannot
   walk through. `RETAIL_COCKPIT_SPEND_CAP_USD` unset means no cap and no
   read, so the offline path is untouched. Proved end to end: a cap below the
   recorded spend refuses with 402 `SPEND_CAP_REACHED` naming both figures.
12. ~~**A live launcher start bought a run.**~~ **CLOSED.**
   `check_ready.py` submits a real question with a fresh idempotency key and
   the launcher runs it on every start. Offline that is free; live it is a
   billed analysis, so every live start bought one — while the script's own
   docstring said "No provider call is made", which was true only offline. It
   now skips that step unless the engine is offline or `--allow-paid-run` is
   given, and reports a skipped question as skipped rather than passed.
13. ~~**The SDK retried outside the ledger.**~~ **CLOSED.**
   `provider.py` says "the SDK is not allowed to retry behind our back", but
   `allow_retry=False` bounds only the adapter's loop and
   `anthropic_provider` builds its client without `max_retries`, so the SDK
   default of 2 applied: a 429 or an overload could be billed three times
   against one reservation the ledger counted once, which a spend cap cannot
   see. The candidate bootstrap now pins the client with `max_retries=0`
   before the adapter builds its own, so every HTTP attempt passes through
   the ledger as the design intends. Host-side; `anthropic_provider.py` stays
   verbatim, and an injected test transport is left alone.

14. ~~**The live UAT's first question returned 503 with no provider call.**~~
   **CLOSED.** `check_live.py` read `os.environ` and reported the price card
   the operator had EXPORTED; the launcher then sourced
   `.env.retail-candidate` under `set -a`, where every line was an
   unconditional `VAR=value`, and the file's
   `COCKPIT_V4_PRICE_CARD=config/cockpit_v4/price_card.json` overwrote it.
   The engine inherited the placeholder, `load_price_card` found no
   `claude-opus-5`, `bootstrap.install` installed no runtime and `POST /runs`
   refused with the typed 503. Spend stayed at $0 because nothing reached a
   provider. The operator's evidence pinned it further: the engine's message
   named the model but not the card, which is only possible with the OLD
   template where the model line was commented out (so the export survived)
   and the card line was not.

   Three changes, none in the engine: every template line is now
   `VAR=${VAR:-default}` so an export wins; `check_live.py --env-file`
   resolves the file the way the launcher does, and the launcher runs it on
   the environment it has ALREADY resolved before starting anything live; and
   `check_ready.py` reads `/diagnostics` and fails READY when the RUNNING
   engine's model, card or book disagrees with what was resolved.
   `/diagnostics` had been reporting the answer all along and nothing asked
   it. Held by `tests/retail_cockpit/test_engine_configuration.py` (11),
   three of which interrogate a started engine.

15. **The `ecl.py` stage traceback was stale.** `ValueError: invalid literal
   for int() with base 10: 'Auto Finance'` in `stage_profile`/`_stage_rows`
   does **not** reproduce on p7: the `stage` column is `BIGINT` holding only
   1, 2 and 3 (1,168,518 / 146,043 / 32,453) and `stage_profile` returns
   cleanly. `_stage_rows` takes no dimension parameter -- it groups on the
   `stage` column itself -- so the message means that column once held a
   product label, which it does not now. The launcher appends to
   `engine.log` (`>>`), so a candidate log holds every run since the first,
   including the p5/p6 era. No `ecl.py` patch and no adapter change: there is
   nothing wrong to correct on the current release.

## 20. Status

**READY FOR MAC ACCEPTANCE — PROVIDER TEST STILL REQUIRED.**

The retail regression comparison in §12 is complete: no test fails because of
this integration.

Not "done", and not "verified": no answer this Cockpit would give a credit
officer has been produced, because no model was called. The architecture that
would produce it is tested; the numbers it would draw on agree with 28
independent oracles; the book it can reach is one book and the ways out of it
are closed.
