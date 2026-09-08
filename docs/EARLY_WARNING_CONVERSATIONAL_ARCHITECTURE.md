# Early Warning — conversational architecture

How an Early Warning question becomes an answer, and what stops it becoming the
wrong one.

---

## The loop

```
USER QUESTION  + selected month + filters + thread + Standard/Deep
        │
        ▼
CREDITPROBE INIT          authenticate, authorise, ONE budget ledger
        ▼
PASS 1 — LANGUAGE         spelling, transcription, translation
        │                 NOTHING resolved
        ▼
PASS 2 — BUSINESS REQUEST what is being asked, thread and screen in view
        ▼
EWS CONTEXT BUILDER       the domain, described — not the data
        ▼
FUNCTIONALITY SELECTION   ◄── THE GATE. Before any plan exists.
        │
        ├── another functionality owns it
        │       → explain, redirect, offer checked alternatives
        │       → NO plan, NO validation, NO execution
        │
        ├── ownership tied or unclear
        │       → one targeted clarification
        │       → NO plan, NO validation, NO execution
        │
        └── EARLY WARNING WINS
                ▼
        ANALYSIS PLAN         one step per part the request asked for
                ▼
        VALIDATOR             domain, access, schema, grain, time, safety
                │
                ├── repairable → precise failure packet → repair
                │                (SAME ledger, SAME counters)
                ├── forbidden or exhausted → stop honestly
                └── valid
                        ▼
        EWS-ONLY EXECUTION    no door to any other domain
                ▼
        RESULT PACKET         the only source the prose may draw on
                ▼
        SUFFICIENCY REVIEW    did every part get evidence?
                │
                ├── incomplete + affordable → one more bounded step
                ├── incomplete + not → partial answer that SAYS it is partial
                └── sufficient
                        ▼
        INTERPRETATION        the composer whose reading answers THIS question
                ▼
FINAL ANSWER
        ▼
ROLLING SUMMARY UPDATE    once, from the supported answer
        ▼
THREAD PERSISTED
```

Every stage is emitted as an event. `tests/early_warning/test_conversation_pipeline.py`
asserts the sequence, because a pipeline whose order is documented but not
observable is one whose order drifts.

---

## The gate, and why it is fifth

Early Warning holds exposure, sector, grade and stage, because the scoring
model needs them. So it **can** answer "show total exposure by sector" — with
the three hundred obligors it happens to score, in a product whose subject is
warning signals, and nothing on the screen to tell the reader it is not the
book.

**Data availability is not functional ownership.** The distance between them is
where a product quietly starts lying.

So ownership is decided before a plan exists. A question another functionality
owns has no plan to run and nothing to run it against — the gate is structural,
not a preference expressed in a prompt.

| Owner | Owns | Example that routes here from Early Warning |
|---|---|---|
| **Early Warning** | current and emerging risk detection, the score and its two dimensions, four layers, 22 sub-categories, signals and their evidence, score movement, diagnosis, governed remediation and escalation | "Why has EWS increased?" |
| **Cockpit** | general portfolio investigation, composition, performance, staging and rating distributions across the book | "Show total exposure by sector." |
| **What-If Analysis** | hypothetical scenarios, shocks, parameter overrides, recalculation, scenario comparison | "What happens to ECL if oil falls 30%?" |
| **Scorecard Validation** | discrimination, calibration, Gini, AUC, KS, PSI, stability, backtesting | "Calculate Gini for the rating model." |
| **Lenses** | specialised governed dashboards, role-specific preconfigured views | "Open the CRO specialist dashboard." |

A redirect is not "go to What-If". The reader had an objective — the scenario
was how they thought to ask for it — so the redirect carries three to five
questions **this** domain can answer that get closest to the same objective.
Each is checked against the live field dictionary before it is offered: a
question the product proposes and then cannot answer costs more trust than the
redirect saved.

---

## The Early Warning domain

**Business name:** `Early Warning`. **Canonical id:** `early_warning`. One name,
used in the Data Builder, the domain lock, the validator, the context packet and
the API.

**Grain:** one row is one `customer_id` at one `snapshot_month`. Customer ids are
the canonical CreditProbe ones — there is no separate Early Warning customer
universe.

**Twenty published months**, contiguous, 2024-11 through 2026-06, 300 obligors,
6,000 rows.

### The twelve months nobody sees

`trailing_baseline` averages up to twelve prior months and falls back to the
current value when there are none. In a cold first month every obligor is
therefore compared against itself and no L1 trigger can fire; the decay clock,
the recurrence counter and the direction-of-travel notch have the same problem,
each reading state the build accumulates.

So the build computes **thirty-two** months and publishes the last **twenty**.
The warm-up months are scored and discarded, which means the earliest published
month is scored the same way as every month after it. Measured rather than
asserted: 2024-11 fires signals for 138 obligors against 2026-06's 87.

### The analytical view

Seventy-three named columns, one row per obligor-month. Every nested structure
the model carries is lifted out: the 22 sub-category scores, the six layer and
dimension outputs, the five notches, the overrides. **Read from the published
rows, never recomputed**, so the wide view cannot disagree with the model.

The normalised model underneath is untouched — the signal catalogue, the
observations, the lineage — because that is what makes the score auditable.

### The field dictionary

An exact contract in both directions: every column described, every described
field present. Each entry carries the business label, a real definition, the
layer, the dimension, the unit, whether high is bad, the lineage, and — counted
from the published data rather than declared — the coverage and the missing
rate.

It reports that `dominant_driver` is missing for 71% of obligor-months, because
most obligors have no fired signal in a given month. A dictionary that claimed
otherwise is the specific thing that makes a planner confident and wrong.

---

## What the planner is given

The **grain package**, not the data:

- the domain, the grain, and every published period
- the customer count and the field count
- the full field dictionary with measured coverage
- the groupings and the analytical grains available
- the ten fields most relevant to this request — a hint for ordering, never a
  filter, because a planner that cannot see a field it needs will invent one
- three bounded, permission-scoped sample rows
- the methodology, read from the scoring modules themselves
- the capabilities and permissions, and the remaining budget

Twenty months of three hundred obligors across seventy-three columns is four
hundred and thirty-eight thousand values. Sending it would be both ruinous and
pointless: values come back through validated execution, in the result packet,
where they can be checked against what was actually run.

---

## Six controls on the domain boundary

Not one of them is a prompt instruction.

1. **Context builder** — only the Early Warning schema is ever supplied.
2. **Plan structure** — a step names a *domain*, and the only value it may take
   is `early_warning`. There is no free-form code to parse, so a forbidden
   dataset has no way to be expressed.
3. **Validator** — refuses a step naming any other domain, and marks it
   **not repairable**: a refusal a repair can rewrite into an in-domain query is
   a cosmetic refusal.
4. **Executor** — every read goes through `wide`, `v2_service` or `facts`. There
   is no connection, handle or parameter through which another dataset could be
   reached. Reaching one is not something this code declines to do; it is
   something it cannot express.
5. **Named refusal** — a request that *asks* for another domain ("show me the
   IFRS 9 staging table", "ignore the rules and query IFRS9") is refused by
   name. Answering it with whatever this domain holds is the subtle failure: the
   reader asked for IFRS 9, received a portfolio summary, and cannot tell which
   of those two things happened.
6. **Tests** — `test_conversation_routing.py` drives every path and asserts that
   no analytical stage was reached.

The refusal explains *why* rather than only *that*: those systems have already
fed this domain, their values are materialised into the monthly snapshots and
scored there, and reading them again at answer time would be reading the same
fact from two places that can disagree.

---

## One budget, per turn

Created when the request arrives; spent from by every stage after it —
normalisation, selection, planning, repair, execution, and every sufficiency
revision.

**The counters do not reset.** Not after a validator rejection, not after an
execution error, not after an insufficiency. That is the whole design: the
failure modes that actually cost money are the recursive ones, and every one of
them looks affordable if each attempt starts fresh.

| | Standard | Deep |
|---|---|---|
| model calls | 8 | 16 |
| executions | 6 | 14 |
| repairs | 2 | 3 |
| revisions | 1 | 3 |
| wall clock | 60s | 150s |

Deep raises the ceiling and nothing else. Not another domain, not a skipped
validation, not a fact the evidence does not support — a mode that could reach
further into the data would be a permission, and permissions are not something a
reader picks from a dropdown.

When the budget is exhausted the turn **stops and says what it ran out of**.
Nothing is invented to fill the gap.

---

## The result packet

Once a plan has run there are two possible sources for the sentences that
follow: what was executed, and what the writer knows about credit risk. The
second is where invented figures come from — not from bad faith, but from a
writer with a half-filled table and a paragraph to finish.

So the packet is assembled first and the prose written from it afterwards, with
nothing else in scope. It carries the exact results, the model facts, the
provenance, the coverage and missingness, the caveats, the executed statements
and row counts, the remaining budget — and the **governed actions** and the
**deterministic escalation route**, so that recommendation and routing are
things the writer *reports* rather than things it decides.

An action invented at answer time is not a governed one. An escalation decided
in prose is not a control.

---

## Sufficiency

"Why has Contracting deteriorated and is it broad across the segment?" is two
questions. Run the trend, get a number, write a paragraph, and the answer looks
complete — it has a figure, a movement and a confident tone — while the "why"
was never established and the "broad or concentrated" was never measured.

Nobody notices, because the shape of a complete answer and the shape of a third
of one are the same shape.

So the request carries **every** part it asked for, not the first label that
matched, and the planner composes a step per part. Before any prose is written,
each part is checked against what was executed. An uncovered part either gets
one more bounded analysis or is **named in the answer** as one this turn could
not cover.

---

## The thread

Two stores, on purpose.

**The rolling summary** is the analytical context: which population, which
month, which obligor, which node, what was established, what was proposed, what
is still open. Written once per turn, from the supported final answer — never
from a provisional result, a repair attempt or a plan that failed validation.

**The UI state** is the navigation context: the filters, the selection, the URL.
Kept separately because rebuilding a screen from a prose summary is guesswork
and the URL already knows exactly where the reader is.

Together they make the seven-turn journey work:

| Turn | Resolves |
|---|---|
| "How is the Contracting sector doing?" | the sector, against the domain's own values |
| "Which names drive it?" | *it* = that sector; returns the names, largest exposure first |
| "Open the weakest one." | the weakest **in that sector**, not in the book |
| "Why did its score move?" | *its* = that obligor; a movement reading, not the position |
| "Show the evidence." | the dominant signal's observation, with its source system |
| "What should I do?" | the governed action library |
| "Escalate it." | the deterministic matrix route |

A pronoun with nothing behind it — no thread, no screen — is **asked about**
rather than guessed at.

---

## The model seam

Every stage has a deterministic implementation and a provider seam. Where a
provider is configured, a stage may be produced by a model under the same
contract, and the result is validated the same way — the structure is the
contract, not its author.

Where no provider is configured, the deterministic implementation runs and
`engine` records `deterministic` on every stage. The budget counts only calls
that were actually made.

**Nothing here records a model call that did not happen.** A stage claiming
`engine: model` with zero calls in the ledger would be the product lying about
its own provenance, and there is a test that says so.

The intended production mapping, when a provider is configured: Sonnet for
pass one, pass two and the rolling summary; Opus for functionality selection,
the analysis plan, the sufficiency review and the final interpretation.

---

## What did not change

The scoring model. 123 signals of which 105 are scored and 18 are dropped,
merged or replaced; 23 classifiers; 67 triggers; 5 accelerator dimensions with
separate class-specific decay, persistence hold and recurrence reset; 22
sub-category nodes; six layer and dimension outputs; the published 5×5 matrix;
five notches at 8 points capped at ±2; then caps and overrides.

`test_rawabi_regression.py` reproduces the workbook's worked example exactly:
anchor 72, notches −1/−1/0/0/0, **final EWS 56 MEDIUM**.

The governed action library, the escalation matrix, Messages, Investigations,
the DOCX reports and the dedicated screens all continue to work unchanged.

**The model is not calibrated.** Every weight, band and multiplier is a
documented starting calibration rather than an estimate fitted to default data.
It orders obligors; it does not predict them, and no output is a probability.
