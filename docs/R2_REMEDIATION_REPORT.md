# Second acceptance remediation — what was done and what is still open

Branch `claude/vigilant-darwin-eohyi1`. Eight commits, `ac50f2f` … `8b9fc4f`.

A real Mac + live-AI acceptance test exposed material product defects across
the data architecture, conversational context, Early Warning UX, Borrower 360
relationship intelligence, visualisation policy, ranking correctness,
data-domain grounding and AI economics. This is what changed, what it was
measured at, and what is still wrong.

---

## 1. Data architecture — 9 of 9 domains (§1)

| Domain | Datasets | Rows | Installed |
|---|---:|---:|---|
| Core Portfolio / Facility | 32 | 3,674,925 | yes |
| Liquidity and Cash Flow | 14 | 1,412,070 | yes |
| External Intelligence | 10 | 75,212 | yes |
| IFRS 9 / ECL | 6 | 302,424 | yes |
| Corporate Ratings | 8 | 240,953 | yes |
| Retail / SME Scorecards | 4 | 1,237,290 | yes |
| CreditProbe Operational Metadata | 3 | 10,402 | yes |
| Documents | 0 | 0 | **no** |
| Policies / Knowledge | 0 | 0 | **no** |

**77 datasets** across 9 registered domains, 7 of them installed. Every
dataset is registered, published, marked authoritative or not, carries a
dictionary and relationships, declares its periods and row counts, and appears
on the Trace.

Two domains — Documents and Policies/Knowledge — are **registered and empty**.
They are shown as not installed rather than hidden.

The **"What this deployment cannot watch for" box is gone**. Unavailability is
now disclosed where it is relevant to the question being asked: a signal that
could not be tested says so on the signal, a story section whose data is
absent says so in the section, and a measure with no governed source says so
instead of showing zero.

The MECHANISM behind the box remains, deliberately. `taxonomy.UNAVAILABLE`
still holds one governed entry — the covenant a waiver was granted against,
which the waiver file does not record — and a deployment that does not install
the liquidity or external-intelligence domains reports those gaps again. An
empty list is a statement about THIS deployment, not a claim that nothing is
ever missing.

## 2. Borrower 360 relationship graph (§2)

`backend/corporate/relationships.py` reads the same governed ownership,
control and guarantee edges as **UPSTREAM**, **DOWNSTREAM** and **LATERAL**,
by the directed path from the centre rather than by the edge type. `A OWNS B`
read from B is a parent and read from A is a subsidiary — the same row of the
same dataset — so the traversal runs twice, once following edges in and once
following them out, and anything reachable only by a path that changes
direction is lateral. That last clause is the definition of a sister company:
up to the shared owner, back down to the sibling.

Worked example, `CORP-103608` at Q2 2026: 5 parties above (holding company at
depth 1 with a controlling 91.4% stake, three ultimate beneficial owners at
depth 2), 2 below (guarantees given), **10 sister companies** each naming the
owner it is shared with, group exposure **SAR 4,953.87m across 9 borrowers**
of which SAR 262.08m is the centre's own.

Ownership and voting are carried and read separately, because 51% of 51% is
26% of the economics and 100% of the control. A relationship carries control
when the voting stake is a majority or the edge is an explicit control edge,
whatever the ownership column says.

The screen draws upstream above, downstream below and lateral level with the
borrower in one row — "beside" has to mean beside, since a sister drawn even
half a node lower reads as a subsidiary at a glance. Directional arrows,
relationship type and stake on each node, solid edges for control and dashed
for economics without it, zoom, pan, depth selector, direct/full-network
toggle, click for detail, and a deep link into that party's own Borrower 360.

## 3. Early Warning UX (§3, §5, §10, §25)

**Severity means risk, not rule count.** `backend/early_warning/priority.py`
decides ACT_NOW / REVIEW / MONITOR / ROUTINE from materiality, exposure,
signal severity, persistence, trajectory, breadth, IFRS 9 relevance, covenant
breach, delinquency and collateral shortfall. Only facts reach ACT_NOW. A
collateral shortfall alone does not: over half the book carries one because
corporate lending is often unsecured by design, so a shortfall is a lending
policy choice until the borrower is distressed on evidence outside the
collateral family. Resulting mix: **ACT_NOW 16.6%, REVIEW 48.1%, MONITOR
33.1%, ROUTINE 2.2%**.

**Currency and units.** Every monetary figure is `SAR 75.4m` / `SAR 1.2bn`,
never a bare number. Ratio covenants stay ratios (`Minimum DSCR: 1.25x`).
Units are derived from the field and the test rather than hand-typed.

**The landing leads on business risk.** High-priority borrowers, newly at
risk, exposure at stake, Stage 2 candidates, covenant breaches, collateral
shortfall, liquidity stress, rating movement — then top borrowers requiring
attention, portfolio hotspots and recent material changes. Signal counts moved
into a collapsed diagnostics panel. A measure with no governed source says so
rather than showing zero.

**The detail is a credit story, not seventeen conditions.**
`backend/early_warning/story.py` composes ten sections in the order a person
asks the questions — why this borrower is here, the risk that matters most,
new / worsening / persistent / cured, the eight families in credit-file order,
external and macro context, connected group, what argues the other way, what
to go and look at. The recommendation follows what actually fired: a covenant
breach and no delinquency is a different visit from 90 days past due and clean
covenants.

**Deep link.** Early Warning → Borrower 360 preserves `customer_id` and
`reporting_period` (`/borrower-360?customer_id=CORP-100376&period=Q2-2026`),
same tab, no new search.

## 4. Conversation context (§6) — release-blocking

The §26 thread now works end to end. Writing it down found three defects:

1. **A clarification threw away the population it had just read.** Turn one
   asks why Shipping deteriorated; CreditProbe asks which figure to measure
   and forgets which sector. Settling nothing on a clarified turn is right
   almost everywhere and wrong on the first turn, where there is nothing to
   continue from. Population and period now survive a clarification.
2. **Carrying a population was gated on having carried a plan.** One flag
   governed both. Right for a modification, wrong for a population: the user
   said Shipping whether or not a plan was ever built.
3. **The catalogue reader disowned "Which reporting periods do we hold?"** —
   the adjective between "which" and "periods" was enough.

## 5. Portfolio calibration and the shipping scenario (§7, §8, §24)

17 sectors. **Financial Services 7.6%** (was ~2.5%), Oil & Gas 6.0%, Shipping
3.8%. Covenant breach **33.8% → 12.8%**. Stage 1/2/3 **77.9 / 17.5 / 4.6**
(corporate) and 79.0 / 14.4 / 6.5 (core). The DPD ladder runs 30/60/120/150/
210/240/300/330 with no pile-up at 450. Shipping S2 30.0% / S3 19.9%.

`backend/scenarios.py` holds one governed **Strait of Hormuz shipping
disruption scenario**, read by both generators, applying a sector impact
overlay with a four-quarter ramp. Every row of it is labelled SYNTHETIC
DEMONSTRATION SCENARIO. Four events are live at Q2 2026 and name Shipping.

Four latent defects the recalibration exposed were fixed at the mechanism:
a 196% ownership register over-claim, an internally inconsistent RAROC row,
an ECL decomposition that did not subtract to its own movement, and a
"Retail Trade" grounding failure caused by a regex that could not span an
ampersand.

## 6. AI economics (§16–§22)

**Measured before anything was changed** (`scripts/measure_ai_cost.py`,
16 questions, no live call, no credits):

| | Before | After | |
|---|---:|---:|---|
| Model calls, 16 questions | 64 | **24** | −63% |
| Cost units | 3,955.9 | **523.8** | −87% |
| Cost units per question | 247.2 | **32.7** | −87% |

By class:

| Class | Calls/q before | after | Input tokens/q before | after | Units/q before | after |
|---|---:|---:|---:|---:|---:|---:|
| A — data and metadata | 4.00 | **0.00** | 14,731 | **0** | 247.1 | **0.0** |
| A — data query | 4.00 | **0.00** | 14,740 | **0** | 247.3 | **0.0** |
| B — orchestration | 4.00 | 4.00 | 14,753 | **5,047** | 247.5 | **35.0** |
| C — judgement | 4.00 | 4.00 | 14,737 | **5,032** | 247.2 | **113.5** |

**What the instrumentation found.** Every question cost the same. "How many
data domains are there?" took four deep-tier model calls and 14,731 input
tokens, exactly as much as "Why did Shipping deteriorate this quarter?".
7,676 of those tokens were the catalogue, re-sent identically every turn in
the user message where no cache can reach it; 6,963 were the evidence ledger,
re-rendered whole each turn. `POST /ask` ran the deterministic orchestrator
AND the whole analyst loop for every question. Nothing detected a repeated
tool call.

**Routing policy.** Class A is answered from the governed catalogue or the
governed runtime with **zero model calls** and the analyst is not run
alongside. Class B is served by a configurable `investigator` role
(orchestration); class C by an `analyst` role (judgement). Both fall back to
the existing planner roles, so a deployment that configures neither is
unchanged. An ambiguous reading comes out B, never A. **The model serving a
request is not shown in the product** — `Meter.to_dict()` omits model ids and
only the administrator's cost trace includes them.

**Token savings.** The rules and tool catalogue became a cacheable prefix
(§17). Older evidence is rendered summarised while the ledger itself is
untouched, so grounding still checks every figure against the whole of it
(§21): evidence tokens per question 6,963 → 4,951. The same query is not run
twice, refused by name so the loop knows why (§18). Normal tool planning
stops after four loops (§18). Asked a second time, ten of sixteen came back
from the run-key store having spent nothing — **523.8 cost units avoided**
(§20), priced at what a question of that class actually cost.

**Budgets** are asserted in tests with scripted providers (§22): a catalogue
question costs 0 calls, a governed figure costs 0, a judgement question is
allowed its investigation, and the same question twice costs 0 the second
time.

`GET /api/v1/ask/cost` is the administrator's cost trace, rendered in
Settings: cost by class, and the recent questions with calls, tokens, cached
share and refused repeats. No prompt text, no tool arguments, no borrower
identifiers, no model id.

## 7. Analytical latitude (§9, §23)

The analyst may form a hypothesis and must label it. Four fields, kept apart
from the answer: `interpretation`, `alternatives`, `confirm_or_refute`,
`external_context`. Grounding treats them differently from the answer — a
hypothesis may say anything about meaning and may not invent a number, so an
interpretation carrying an untraceable figure has that sentence dropped and
keeps the rest. Running the reading through the grounding filter whole would
have deleted every interpretation, which is the same as never offering one.

External evidence is read from the **event's own live window** rather than the
link table's snapshot stamp, and a borrower-level link is never shown in the
same voice as a sector-level one. Two things in the same quarter is a
coincidence until something links them.

## 8. Visualisation, ranking, metadata (§11, §12, §13, §14, §15)

Data first, graph optional — the default result view is a table. A metadata
answer declares `visualization.kind = "table"` at source. PD ranking orders
numerically with a deterministic tie-break, asserted on the rows rather than
on a checker's verdict. One authoritative metadata service with reconciliation
tests. 67 metadata-understanding regression questions (§14 asked for 50).

---

## Verification

| Gate | Result |
|---|---|
| Full backend suite (`tests/`, incl. legacy) | **9,382 pass, 0 fail, 22 skip**, exit 0 |
| Frontend `npm test` | **380 pass, 0 fail** |
| `tsc --noEmit` | **clean** |
| `eslint --max-warnings=0` | **clean** |
| `next build` (production) | **exit 0**, all routes built |
| `ruff check backend/ tests/ scripts/` | **clean** |
| R2 §26 acceptance | **36 pass, 0 skip** |
| Docker | **NOT VERIFIED IN CLAUDE SANDBOX** |
| Live-AI browser acceptance | **NOT RUN** — no live provider call was made |

Tests added by this remediation: **330** backend across 11 new files, plus 45
frontend across 3 new files. Counted as collected, so a parametrised case
counts once per parameter — which is what actually runs.

The first run of the full suite failed six cases in
`tests/validation/test_live_smoke_contract.py` and
`tests/validation/test_live_verify.py`. The cause was real and belongs to
this work: §16 split the single analyst role into a cheap `investigator` and
a deep `analyst`, taking `roles.ACTIVE_ROLES` from five to seven, so a quick
live verification now pings seven roles and makes 15 calls rather than 13.
The production estimate derives that number from the catalogue and was
already correct; the four literal expectations in those two modules were
stale, and the runbooks still quoted `~13 calls`. Both were corrected to the
mechanism's number rather than the mechanism being bent back to the
literal — a role the product calls in anger must be reachable before a run
may call itself live-verified.

---

## What is still open

These are defects and gaps that remain. None is hidden.

1. **Docker was not verified.** The sandbox cannot run it. The compose stack
   is unchanged by this work but has not been exercised.
2. **No live model was called.** Every measurement, every acceptance question
   and every routing test ran against scripted providers and the deterministic
   engine. The cost figures are sound for comparing architectures and are not
   a forecast of a bill; the §26 questions prove the governed paths and not a
   live model's phrasing.
3. **Prompt caching is modelled, not observed.** The harness charges a cache
   write on the first call and a read thereafter. No real cache hit has been
   seen, because no request left the process.
4. **The external-intelligence domain is keyed to the core portfolio.**
   `borrower_external_event_link` carries `SA-` customer ids while the
   corporate book runs on `CORP-` ids, so no borrower-level external link can
   join for a corporate borrower. The story falls back to sector-level
   evidence and says so explicitly, which is honest but weaker than the
   borrower-level link the schema implies. Resolving it needs either an entity
   resolution across the two populations or a rebuild of the link table
   against the corporate universe.
5. **The link table covers one period.** It is built at the core portfolio's
   latest reporting date (Q4 2025). The story works around this by reading the
   event's own live window, which is the correct reading, but the link table
   itself is still a single snapshot.
6. **Two domains are registered and empty.** Documents and
   Policies/Knowledge carry no datasets. They are shown as not installed.
7. **The hypothesis renders only when a live analyst produced one.** The
   `Hypothesis` block is wired into the answer view and reads
   `run.analyst.*`, so §9's four labelled parts appear on screen when the
   analyst path ran. With no provider configured — which is how every gate in
   this remediation was run — the analyst does not run, so nothing has been
   seen on screen. The contract is tested; the rendering is not.
8. **Cost units are a declared weighting, not currency.** Light 1, standard
   4, deep 16; output tokens weigh 5× input, cache reads 0.1×, cache writes
   1.25×. Conservative, so a saving computed with them understates.
9. **Class C questions cost more per question than class B**, and that is the
   intended shape rather than a regression: before the change everything was
   served at one rate, so a catalogue lookup subsidised nothing and a forensic
   question was under-served.
10. **The §26 acceptance run is offline by construction.** It skips nothing,
    but it exercises the deterministic reader rather than a live analyst.
