# Lenses 2.1 — Demo Runbook

Twenty minutes, five screens, no slides. Everything shown is calculated live
against the governed data when the page opens.

**Branch** `claude/lenses-specialist-dashboards-esd591`

---

## 0. Before the room

```bash
# One command brings a deployment to a demonstrable state.
python scripts/bootstrap_demo.py

# It is idempotent; --check reports without changing anything.
python scripts/bootstrap_demo.py --check
```

If this branch is checked out over an existing deployment, the shipped lenses
need reinstalling — the definitions changed:

```bash
python -c "from backend.metrics.lenses import install; print(install(replace=True))"
```

`replace=True` goes through the ordinary revision path, so an edit somebody
made to a shipped lens is kept as an earlier version rather than lost.

Then:

```bash
# Backend
DATABASE_URL=... REQUIRE_LOGIN=true python -m uvicorn backend.api.main:app --port 8000

# Frontend
cd frontend && npm run build && npx next start -p 3000
```

Sign in as **priya.raman** (an analyst). Sign in as an analyst rather than an
administrator with the login gate off: the governance labels and the ownership
rules only mean something as somebody in particular.

**Check before you present:**

```bash
python scripts/bootstrap_demo.py --check
# expect: 15 of 15 readiness checks pass

python scripts/acceptance/lens_journeys.py
# expect: 164 passed, 0 failed
```

**If you have run the test suite against this database**, `--check` will
report the Q2 2026 portfolio review as missing — the suite writes to the same
tables and the review is consumed. It names its own remedy:

```bash
python scripts/bootstrap_demo.py --step review
```

Run the readiness check, not just the journeys. The journeys prove the Lenses
work; the readiness check proves the rest of the product a client will click
into from them still does.

---

## 1. The library — 1 minute

Go to **Lenses**.

Three bands. Say why the split exists:

> A dashboard CreditProbe ships is not one of your lenses. It is the answer to
> "what would a competent head of this portfolio put on one screen". Burying
> it in a list of personal views is how somebody rebuilds a lens that already
> exists.

Each shipped card says who it is for, which governed data domains it reads,
and how many figures and charts are on it — so the choice is made from the
library rather than by opening all four.

---

## 2. Corporate IFRS 9 — 5 minutes

Open it. Forty-three panels, seven bands.

**The provision.** Total exposure, total ECL, coverage — and the ECL and
coverage trends beside them.

**Where the book sits.** Three stage exposures and three shares.

> Point at the three exposures and the total. *These sum. Not approximately —
> to fifteen decimal places, because every tile on this lens was measured in
> the same single pass of the staging dataset. Tiles that resolved their own
> periods separately would each look plausible and would stop summing.*

**What moved between the stages** — the band to spend time on, and new here.

> Stage 1 to Stage 2, Stage 2 back to Stage 1, Stage 2 to Stage 3, new
> defaults, cures. This is not a period-over-period comparison: the staging
> dataset records where each facility sat at the last reporting date, so a
> transition is a property of one row and is measured in the same pass as a
> level.

Point at the three rates.

> The cure rate is 13.3%. That is over the exposure that *started the quarter
> in Stage 3* — not over the book. A cure rate over total exposure would fall
> whenever the book grew, and would not be a cure rate.

**What triggered the move.** Five SICR triggers by exposure.

> The overall SICR rate says whether any trigger fired. A committee asked why
> Stage 2 is up needs to know which. These five overlap on purpose — a
> facility can breach a covenant and be downgraded in the same quarter — and
> each tile says so on its own face.

**Open one info control.** Click the ⓘ on *New Default Rate*.

> Business definition, the formula, the numerator, the denominator, the
> dataset, the grain, the source fields, the filters, the period rule, the
> transformation, the exclusions, the version, and what it is NOT. Nobody
> should have to ask how CreditProbe calculated this.

**The period picker** — top right of the scope bar.

Change it to the previous quarter. Wait for the redraw.

> Every figure moved. Look at the three stage exposures and the total again:
> still summing. The picker offers only quarters the staging dataset actually
> holds rows for — not a date range, which would list quarters that render as
> a screen of dashes.

**Scroll to the bottom.** "Not on this lens."

> Scenario-weighted ECL and the ECL movement bridge, each with the reason and
> what would be needed. A view that quietly omits the number somebody came for
> teaches them not to trust it.

---

## 3. Retail Credit Risk — 3 minutes

**The arrears band.** Each bucket twice — accounts and balance.

> A dashboard showing one of these labelled simply "90+ DPD" is read two ways
> by two people in the same meeting.

**In and out of arrears.**

> A level says how many accounts are behind. The cure rate says whether the
> ones that went behind are coming back — 25% of the accounts that reached 30+
> days past due in the last three months are fully up to date now. Repeat
> delinquency says how many keep going behind, which the arrears buckets
> cannot see: an account current today may have been behind three times since
> January.

**Which accounts are behind.** Three charts — by product, by vintage, and the
default rate down the bureau score bands.

> A portfolio number that is flat can hide a product or a vintage that is not.

**Are the scorecards still working.** Gini, KS, calibration, and the sample
size behind them.

> These read the most recent month whose performance window has closed. A Gini
> for last month is not a low Gini — it does not exist, because none of those
> accounts has had time to default. The tile says which period it used.

If asked about roll rates: the note at the bottom explains why a true roll
rate is a movement between two months that the engine cannot compute in one
pass, and names what is on the lens instead.

---

## 4. Retail Analytics — 2 minutes

The analyst's view rather than the executive's.

**Does the score separate them.** The bad rate down the bureau score bands:
15.2% in the worst band falling to 1.0% in the best.

> This is the picture the Gini summarises in one number. A scorecard that is
> working shows a monotone fall across it. One that is not shows a step, or a
> bump — and the Gini alone would not say where.

**How it was mixed** and **how the cohorts turned out**, read together.

> The channel that grew and the channel that performed are rarely the same
> one.

---

## 5. Create a lens by describing it — 5 minutes

Back on **Lenses**. The page opens with a question — *How do you want to
define a new Lens?* — and a box.

Type: `watchlist exposure and covenant breaches across the corporate book`.
Click **Describe it**.

> Nothing was built from that sentence. It was carried into the builder, which
> shows what it understood *before* anything exists. A box that turns one
> sentence straight into a dashboard leaves whatever it did not understand
> silently absent, and you find out in the meeting.

**Step 1 — the reading.** It says *Read as:* and lists what it recognised.

> No model read that sentence. The catalogue did: the sentence is cut into
> overlapping phrases, longest first, and each is put through the same ranked
> search the typeahead uses. The same words give the same reading on every
> machine — which is what lets a test assert it.

**Step 2 — the data domains.** They are offered as chips to tick, with a box
for one it missed.

> It proposes; you decide. And a domain you were never allowed to read is not
> on this list, because the candidates come from the catalogue as *you* can
> see it.

**Step 3 — the name.** It suggests one. Accept it or type your own.

**Step 4 — what it shows.** Click **Add a metric**. Two ways in: an existing
metric, or a new one.

*The library first.* Type `del`.

> It did not open with the catalogue. Ninety-nine metrics in a scrolling list
> is a list nobody reads, and people rebuild a number they already had — which
> is how two definitions of "default rate" end up on two dashboards. Every
> suggestion says its unit, its definition and its formula, because "30+ DPD"
> by count and by balance have almost the same name and are different numbers.

Type `delinq 30`. The list gets shorter, not longer. Then `bad rate` — it
reaches the default rate, because "NPL rate", "bad rate" and "default rate"
are three names people use for one number.

Add one. It locks straight away — an existing metric is already governed.

*Now a new one.* **Add another metric** → **Define a new metric**. Type
`total exposure to borrowers on the watchlist`. Click **Draft it**.

What comes back is one definition read four ways:

- the **algebra**, with every term's field and conditions written out;
- the **plain-English execution logic**, numbered;
- the **actual SQL** it will run — from the compiler the executor calls, over
  the same validated plan, not a reconstruction;
- the **values bound to it**, printed beside the query.

Change the aggregation in the definition, and watch all four move together.

> They are generated from one tree on every request. Nothing is stored, so
> nothing can be right when it was written and wrong after an edit. And the
> threshold is a *bound parameter*, so a filter value can never become SQL —
> there is a test that drives `Healthcare'); DROP TABLE lenses;--` through this
> route and reads the row count back unchanged.

Click **Preview**. It runs against the real book and walks the calculation:
the dataset, the reporting period, the fields read, the filters, the
numerator, the denominator, the aggregation, the final figure, and a sample of
rows.

Click **Lock metric**.

> It is stored *now*, and stored as a metric like any other — searchable,
> reusable, governed. It arrives as a DRAFT: creating a metric does not confer
> a status. It becomes calculation-ready by calculating and verified only when
> a person compares it with their own number.

**Add another** or **Go back to the lens**. Go back, then **Create the lens**.
It opens, live, with the scope bar showing what you said it was for.

---

## 6. Edit a lens that already exists — 3 minutes

On the lens you just made, click the **pencil** next to its name.

The real cards — with their real numbers on them — become an editable board.

> It did not swap the lens for a list of titles. What you are judging is the
> arrangement of the things you can see, and a list of names reordered well
> often looks wrong as tiles.

Drag one card onto another. Or use the **‹ ›** buttons on a card, which do the
same move without a pointer.

Click the **–** on a card. It asks first, and says the metric stays in the
library.

Click **Add new metric**. It is the same builder — the same library, the same
definition editor, the same preview, the same lock. Come back: still in edit
mode, because you were still arranging.

Click **Save**.

> Nothing was saved until then, so a mis-drag cost nothing. And the save went
> through the same validated, versioned path a change made by asking goes
> through: this is a new version of the lens, the previous arrangement is
> still there, and it can be restored.

Reload the page. The arrangement is the one you saved.

Then use the **Change this lens** box at the bottom: type
`show corporate exposure by region`.

> That is the same interpreter the creation flow uses, so a breakdown asked
> for here comes back as a chart rather than a tile of the same number. And if
> that metric is already charted another way, this *re-cuts* the chart it has
> rather than adding a second one — the change summary says what it was
> before. Like every other change, it is a new version and the previous one
> can be put back.

---

## 7. If asked

**"Can I add a chart?"** — Yes. *Build a chart* on the lens: metric,
dimension, aggregation, period, filters, sort, comparison, type, preview,
save. Show that a *line* across products is refused with the reason — products
have no order, so a line between them would suggest a progression that is not
there — and a bar is offered instead.

**"Can I build my own metric?"** — Yes, and it must be verified against real
data before it is trusted. The builder takes numerator and denominator as
separate multi-term sections, every term names its dataset, field, filter and
aggregation, and nothing is evaluated as text. The verification workspace runs
it against a stored dataset and shows source → filters → terms → numerator →
denominator → final result. If you say the number is not what you expected,
that disagreement is recorded and confers no verified status.

**"How fast is it?"** — The Corporate IFRS 9 lens is forty-three panels and
reads the staging dataset once. It used to read it thirty-four times.

**"Is any of this a stored number?"** — No. Every figure is calculated when
the page opens, against what is published now. There are no stored figures to
go stale.

**"Is this real data?"** — It is synthetic and says so: every row carries
`origin = SYNTHETIC_DEMO` and every catalogue entry is marked synthetic. It
describes no real borrower and no real bank's book.

---

## 8. What not to promise

Be direct if any of these comes up. Each is visible in the product as a
refusal with a reason, not as a missing feature you have to explain away.

- **Scenario ECL (base / upside / downside).** Not available. The staging
  dataset carries one already-weighted ECL, not one per scenario.
- **The ECL movement bridge.** Not available as a lens tile. The stage
  migration band covers the one leg the staging dataset can answer alone.
- **PSI.** Not available as a metric — it compares a period against a
  reference window, and a metric computes one period. The Scorecard Validation
  module reports it against each model's declared reference.
- **Approval rate, booking rate, override rate.** Not available. The
  application dataset records what was applied for and what happened
  afterwards, not the accept/decline decision.
- **Retail IFRS 9 staging and ECL.** Not available. There is no retail
  impairment dataset in this deployment.
- **Month-on-month roll rates.** Not available. The lens carries a three-month
  cure rate and a repeat delinquency rate instead, and says why they are
  different measurements rather than substitutes.
- **Heatmaps, waterfalls, cohort charts, scatter plots.** The renderer draws
  bars and lines. Offering a chart type that renders as something else is the
  defect this branch spent its first commit removing.
- **Natural-language transformation plans.** The safe transformation IR exists
  and the metric builder uses it. A sentence drafts a metric — a measure, an
  aggregation and its filters, editable before it is locked. A sentence
  describing an arbitrary multi-step calculation and getting a plan back is
  not built.
- **Business-language synonyms for column names.** "Probability of default"
  does not reach `pd_12m_pct`. That draft comes back with the measure
  unresolved rather than guessed.

---

## 9. Reset

```bash
python scripts/bootstrap_demo.py --check     # report only
python -c "from backend.metrics.lenses import install; install(replace=True)"
```

Any lens made during the demo can be deleted from its own page; the shipped
eight are reinstalled by the command above and keep their revision history.

A metric locked during the demo stays in the library — that is the point of a
governed catalogue — and the catalogue refuses a second metric of the same
name. Delete it from the metric library, or lock the next one under a
different name.
