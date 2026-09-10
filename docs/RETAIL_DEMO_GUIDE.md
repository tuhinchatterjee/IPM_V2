# Saudi retail demonstration — how to open it, and what to show

> **Synthetic Saudi retail demonstration data — not ANB customer data or
> approved models.** Say this once at the start. Everything below is generated.

---

## 1. Open it

Double-click:

```text
launchers/retail/start-retail.command
```

It resolves its own directory, checks the build identity, runs the readiness
check, verifies the ports are free or already its own, starts the retail backend
and then the retail frontend, and opens the browser only once every check has
passed. On failure it names the log and the cause instead of opening a blank
page.

| | |
|---|---|
| Frontend | <http://localhost:5328> |
| Backend | <http://localhost:8328> |
| Stop | `launchers/retail/stop-retail.command` |
| Check without starting | `.venv/bin/python scripts/check_retail_ready.py` |

The frozen presentations on their own ports are untouched. The stop script only
stops processes whose pids it wrote itself, and leaves anything it cannot
positively identify alone.

## 2. First run only

```bash
uv sync                                                  # dependencies
.venv/bin/python scripts/build_retail_demo.py            # the 25-month book
.venv/bin/python -m alembic upgrade head                 # the retail database
.venv/bin/python scripts/bootstrap_retail_installation.py  # register it in Data Builder
```

The build takes about three and a half minutes and is deterministic: the same
configuration and seed give byte-identical content every time. Ordinary startup
never regenerates it.

## 3. What to show, in order

**Data Builder — one domain.** "Cockpit Data", twenty-five monthly datasets,
August 2024 through August 2026. One joined facility-level table; nothing to
upload and nothing to join by hand. Point out the row count, the customer count
and the SYNTHETIC label.

**Cockpit — the book.** "For August 2026, show retail exposure, customers,
facilities and weighted ECL by product." Then the follow-up: "now only
salary-transfer customers." The month and the intent carry over.

**Cockpit — the impairment bridge.** "Why did ECL increase from July to August?
Separate stage, PD, LGD, EAD, new business and exits." Show that opening plus
every contribution equals closing, that entrants and exits are their own bars,
and that the method is named as sequential replacement with its order published.

**Cockpit — the scorecard.** "Using the latest fully observed 12-month cohorts,
test the personal-finance application scorecard's AUC, Gini and KS." Then ask
for August 2026's next-twelve-month Gini and let the product refuse: those
outcomes do not exist yet. That refusal is the demonstration.

**Cockpit — one customer's score.** "Show the raw input, the transformation and
the points behind this customer's score." Every input, its bin, its weight of
evidence and its points, adding to the score exactly.

**Early Warning — retail signals.** "Which retail customers have missed salary
credits and simultaneously increased card utilisation?" Open one alert: the
measured value, the threshold, what it moved from, and the columns and dates
behind it. Note the wording — evidence of income interruption, not a claim about
a job. Run the evaluation twice and show that no alert duplicates.

**What-If — the same snapshot.** Run a neutral scenario first: the delta is
zero, because it is the same data through the same engine. Then "+20% relative"
against "+2 percentage points" and show they are different arithmetic. Then
reweight the scenarios and show the identity recomputed.

**What-If — the honest limit.** "If we lower the cutoff, how many rejected
applicants will default?" The product names the missing data instead of
answering. That is the moment a risk audience decides whether to trust it.

## 4. Numbers to have ready

Read them from `metadata/retail/retail_dataset_manifest.json`, which is the
record of what was actually published. Do not quote from memory: the manifest
carries the per-month row, customer and facility counts, the exposure, the
allowance and a content hash for every month.

## 5. Questions you will be asked, and the honest answers

**"Is this our data?"** No. It is synthetic, generated from a published
configuration and a fixed seed, and it says so on every row.

**"Are these ANB's models?"** No. The scorecards are demonstration
specifications with every coefficient and bin written down in
`docs/RETAIL_MODEL_AND_TRANSFORM_SPEC.md`.

**"Is the bureau data SIMAH?"** No. It is a synthetic bureau proxy on its own
declared scale. Nothing of SIMAH's score, range, layout, schema or feed is
replicated or claimed.

**"Is the staging policy compliant?"** It is a synthetic demonstration policy.
The thresholds are conservative and recognisable, they are versioned, and every
stage decision traces to the rule that made it — but they are not a statement of
what IFRS 9 or SAMA require.

**"Can we put our own data in?"** Yes, that is what
`metadata/retail/retail_data_contract.json` is for: explicit column mappings,
declared units, stated null handling, and rejection rather than silent repair.
