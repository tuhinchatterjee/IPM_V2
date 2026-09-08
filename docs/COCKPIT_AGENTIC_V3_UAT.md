# Cockpit Agentic V3 — UAT

What to run, what to look for, and what this environment could not verify.

## Read this first

**No model credential is configured in this environment.** Everything that
depends on a model — routing accuracy, translation fidelity, plan quality,
repair quality, answer quality, latency, tokens and cost — is **BLOCKED /
UNVERIFIED**. The automated suite uses a labelled mock provider and proves the
application's guarantees: that the gate runs first, that a referral executes
nothing, that five submissions is five, that the repair request carries the
full effective context, that CreditProbe never edits the model's SQL, and that
a stop says something true. It proves nothing about how a real model behaves,
and no deterministic output anywhere in this branch stands in for one.

## Setting up

```sh
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
export COCKPIT_AGENTIC_V3=true
COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_agentic_v3.py --overwrite
```

The build refuses to publish a release that fails any of its 72 integrity
gates, and refuses to write anywhere outside the `cockpit_agentic_v3`
namespace. It takes about a minute and produces ~13 MB of Parquet under
`data/cockpit_agentic_v3/demo-20q-v1/`.

### The configuration this domain requires

```sh
export COCKPIT_AGENTIC_V3_STANDARD_INPUT_TOKENS=36000
export COCKPIT_AGENTIC_V3_DEEP_INPUT_TOKENS=40000
export COCKPIT_AGENTIC_V3_STANDARD_TOTAL_TOKENS=100000
export COCKPIT_AGENTIC_V3_DEEP_TOTAL_TOKENS=200000
```

**Why, and read this before deciding.** The complete field dictionary is about
22,078 tokens and the whole context packet about 28,000 after every permitted
reduction. The specification's own per-call input cap is 12,000 in Standard and
its cumulative ceiling is 35,000, so its numbers cannot hold its own catalogue.
That is measured, not asserted, and it is put here rather than closed quietly
in code. Without these settings the Cockpit returns `CONTEXT_TOO_LARGE` with
the figure and a pointer to
[`CONTEXT_SIZING.md`](cockpit_agentic_v3/CONTEXT_SIZING.md) — which is the
correct behaviour, not a bug.

**The badge on screen shows any raised limit**, so a demonstration run under
these settings can never be mistaken for one run under the specification's own.
The five execution submissions and three analysis rounds cannot be raised at
any level.

### With a credential

```sh
export ANTHROPIC_API_KEY=...           # spends real money
export AI_COCKPIT_PREPROCESS_MODEL=... # a fast model
export AI_COCKPIT_REASONING_MODEL=...  # a strong one
# Configure prices, or the spending ceiling is not a control:
export COCKPIT_AGENTIC_V3_OPUS_INPUT_USD_PER_MTOK=...
export COCKPIT_AGENTIC_V3_OPUS_OUTPUT_USD_PER_MTOK=...
export COCKPIT_AGENTIC_V3_SONNET_INPUT_USD_PER_MTOK=...
export COCKPIT_AGENTIC_V3_SONNET_OUTPUT_USD_PER_MTOK=...
```

No model id is hard-coded anywhere. Verify the ids against the provider's
current documentation before setting them.

## Running

```sh
# Backend
COCKPIT_AGENTIC_V3=true DATABASE_URL=... .venv/bin/uvicorn backend.api.main:app --port 8000
# Frontend
cd frontend && npm ci && npm run dev
```

Then open the Cockpit at `/`.

## The automated suite

```sh
.venv/bin/python -m pytest tests/cockpit_agentic -q     # 233 tests
COCKPIT_AGENTIC_V3=true .venv/bin/python tests/evals/cockpit_agentic/run_ownership_eval.py
```

The eval runner exits **BLOCKED** with no credential rather than reporting an
accuracy figure obtained from a mock.

## The manual script

Check the badge first: domain, release, twenty quarters, and any raised limit.

### A — the ownership gate

| # | Ask | Expect |
|---:|---|---|
| A1 | *Show this borrower's stored rating history over the last eight quarters.* | Answered. Cockpit owns reading recorded ratings. |
| A2 | *Assign this borrower a new credit score.* | **Referred.** Credit Scoring is not implemented here, so **no navigation button** and an honest statement of why. Up to three Cockpit alternatives. **No SQL runs** — check the technical detail shows 0 submissions. |
| A3 | *Why did this borrower's early warning score increase?* | **Referred to Early Warning**, with a working button to `/early-warning`. Zero submissions. |
| A4 | *Increase PD by 20% and recalculate ECL.* | **Referred to Stress Testing** at `/stress` — note the label is Stress Testing, not "What-if Analysis". |
| A5 | *Compare the stored baseline and downside IFRS 9 outputs.* | **Answered.** Reading recorded scenarios is not a new what-if run. |
| A6 | *Validate the scorecard's discrimination.* | Referred to Scorecard Validation. |
| A7 | *Show the stored PD history and then stress it by 200 basis points.* | Mixed: the excluded half is **named**, and a Cockpit-only reformulation is offered. Not silently half-answered. |
| A8 | *What is the weather in Mumbai?* | Unsupported, and **no alternatives** — inventing one would be worse than none. |

### B — the domain boundary

| # | Ask | Expect |
|---:|---|---|
| B1 | *Show me total stage 2 exposure for 2019Q1.* | Answered as a **coverage limitation** — outside the twenty quarters — **not** referred elsewhere. |
| B2 | *Show me the EWS alerts table.* | Refused. The message names only Cockpit relations and no other module's schema. |
| B3 | *What is the average PIT 12-month PD by sector this quarter?* | Answered from `pd_pit_12m`, at facility grain. |
| B4 | *How many facilities does each borrower have, and what is the borrower's total assets?* | Watch for the grain trap: total assets must not be counted once per facility. |

### C — language and fidelity

| # | Ask | Expect |
|---:|---|---|
| C1 | *Show stage 2 exposure by sector, excluding Construction.* | Construction **excluded**. The negation survives. |
| C2 | *Show me the stage-two exposre by secter for the lastest quater.* | Understood despite the spelling. |
| C3 | *पिछली तिमाही में ECL कितना बढ़ा?* | Answered in English (or the requested language); "ECL" kept as written. |
| C4 | *Iska ECL kitna badha hai last quarter mein?* | Same. |
| C5 | *Show me the PD.* | A **clarification**: PIT or TTC, twelve-month or lifetime. Not a silent choice. |

### D — the loop and its limits

| # | Do | Expect |
|---:|---|---|
| D1 | Ask something needing several steps. | Progress names real work: *checking this is a Cockpit question*, *planning*, *executing submission 1 of 5*, *reviewing round 1 of 3*. Never "complete" while running. |
| D2 | Press **Stop** mid-run. | Work stops. The note says charges already incurred are **not** reversed. |
| D3 | Switch to **Deep** and repeat. | Longer budget. Deep is never selected for you. |
| D4 | Open the technical detail. | Submissions used of five, rounds of three, tokens, spend (or `UNKNOWN`). |

### E — thread continuity

| # | Do | Expect |
|---:|---|---|
| E1 | Ask about a borrower, then *and now only Construction*. | The correction overrides; the borrower is retained. |
| E2 | Ask an EWS question, get referred, then ask *what did we just find?* | The referral is remembered **as a referral** — never as if the analysis had been done. |
| E3 | Run twenty exchanges. | The twentieth carries the summary and the three most recent complete pairs, not the whole thread. |

### F — the honest failures

| # | Do | Expect |
|---:|---|---|
| F1 | Unset `ANTHROPIC_API_KEY` and ask anything. | A stop saying no provider is configured. **No tables, no charts, no analysis.** Nothing that could be mistaken for an answer. |
| F2 | Unset the input-token override and ask anything. | `CONTEXT_TOO_LARGE`, the measured figure, and a pointer to the sizing document. Not half a schema and a confident answer. |
| F3 | Stop the release build and ask. | An honest unavailable, not a substitute. |

## What to record

Branch and commit; the release id and its twenty quarters; resolved model ids
with credentials redacted; **which limits were raised**; the ownership eval
report; measured latency, tokens and cost per question; and every case where
the answer was wrong, unsupported, or presented as more certain than the
evidence allowed.

## Known limitations, stated

1. No live-provider verification of anything in this environment.
2. Isolated Python execution is not implemented; it is reported as unavailable
   and a Python step is refused rather than run in-process.
3. The data is the labelled synthetic demonstration. No field is from a real
   source.
4. The specification's own token limits cannot hold its own catalogue; the
   configuration above is required and is reported on screen.
5. The spending ceiling is not a control until prices are configured.
6. Thread state is in-memory and does not yet survive a restart.
