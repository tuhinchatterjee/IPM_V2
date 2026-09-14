# How to demo the retail Early Warning → What-If journey

*Synthetic Saudi retail demonstration data and a synthetic demonstration
model. Not an ANB model, not an ANB policy, not a SAMA requirement, not
independently validated. Say so once, at the start — every screen also says it.*

Twelve minutes, one straight line, no backtracking. Each step says what to
click, what will be on screen, and the one sentence worth saying over it.

---

## Before you start

```bash
set -a && . ./.env.retail && set +a
.venv/bin/python scripts/bootstrap_retail_installation.py --check
bash scripts/retail_uat/restart_backend.sh
```

Then open the workspace once and leave it for a minute. The first request
after a restart computes every level while the warm-up thread is also
computing them; after that everything serves in about a millisecond. Opening
cold in front of an audience is the one avoidable way to make this look slow.

---

## 1 · The portfolio, and why Credit Card (90 seconds)

**Early Warning Score.**

On screen: total Retail with its headline figures, the four product cards, and
the AI Interpretation paragraph underneath.

> "The model reads the book and says which portfolio it is most worried about
> and why. It names Credit Card, and the reason is in the paragraph — not a
> label somebody attached."

Press **Why this ranking?** The six criteria and their published weights.

> "Six criteria, each weighted, each measured. The ranking follows the marks
> and the marks follow the data."

---

## 2 · Down to a cohort (90 seconds)

Click **Credit Card** → **Salaried** → **Platinum Card**.

On screen at each level: the score, the warned counts, the six-month trends,
the top warning signals, and the **materiality** block — what this level is as
a share of its parent, its product and total Retail.

> "Every level says what it is a share of. A sub-product that looks alarming on
> its own may be one per cent of the book, and the reader needs both numbers to
> decide anything."

---

## 3 · Export to What-If (60 seconds)

Press **Export to What-If Analysis**.

On screen: the thread opens. The source card names the selection, the model
version and the exact counts. Below it the IFRS 9 baseline, then the cohort
drawn as charts, then the composer at the bottom with twelve chips.

> "The selection carries an exact list of customers and facilities — not a
> filter that gets re-derived. These are the people that get stressed, and the
> thread can show you every one of them."

Press **View selected customers** briefly, then close it.

---

## 4 · A scenario, and the mechanism (3 minutes)

Choose **Run both** beside the composer. Then press the chip:

**Reduce verified income by 10%**

On screen, in order:

1. the summary — customers, exposure, ECL before and after, the change;
2. **How the number moved** — the waterfall, as a chart and a table;
3. before-and-after on PD, LGD and coverage;
4. the same movement at five widths;
5. impact by level;
6. the challenger comparison;
7. the AI interpretation.

> "This is the part worth slowing down on. The waterfall is not an allocation
> of the total across the things we asked for — the IFRS 9 identity multiplies
> its inputs, so splitting the total would invent steps. Every step here is the
> scenario re-run with one more shock applied. That is why they sum exactly."

Point at the five levels.

> "Same riyal figure at every level. Stressing a cohort cannot change anything
> outside it. What changes is how big it looks — alarming inside the
> sub-product, immaterial across the book."

---

## 5 · The thread is a thread (60 seconds)

Type or press:

**Move 15% of Stage 1 exposure to Stage 2**

> "The first answer is still there. You build a comparison rather than
> replacing one."

Scroll up to show the income result still in place, then back down.

---

## 6 · It understands the cohort (90 seconds)

Press:

**Stress only the forward-risk customers in this selection**

The thread asks what to apply — naming a cohort is not a change.

Then type:

**Increase PIT 12-month PD by 20% for forward-risk customers only**

> "The sentence narrows the selection. It never widens it — asked as a fresh
> filter this would stress every forward-risk customer in the book and report a
> number four times the size."

Point at the narrowing badge on the result.

Optional, if there is time — type something deliberately ambiguous:

**Increase PD by 2**

> "Two per cent of the PD and two percentage points added to it are different
> scenarios. It will not guess: it asks, and both readings are buttons that run
> exactly what they say."

---

## 7 · The workbook (60 seconds)

Press **Download detailed Excel** on any result. Open it.

> "Thirteen sheets. The scenario, the waterfall, the cohort, every level, the
> affected customers and facilities before and after, the parameters, and the
> method. Nothing in it is recomputed — it is the result you are looking at, in
> the tool you would work in."

Show the **Waterfall** sheet and the **Facility pre-post** sheet.

---

## 8 · Model governance (2 minutes)

Back to **Early Warning Score** → **Model Log**.

> "Two versions, both measured on today's book over the same facilities, months
> and outcomes. The retired one is rescored, not remembered."

Open **3.0.0**.

> "Performance is cut by the state a facility was in when it was scored,
> because a model measured including customers already ninety days down is
> measuring its own inputs. The hard-trigger cohort reports operational capture
> and not discrimination — its ROC would be a real number that misleads."

Point at the tied deciles.

> "Sixty per cent of the book scores zero, so six deciles sit inside one score.
> They read the same, and the table says why. A table that showed them
> differing would be reporting the order the rows arrived in."

Press **Development report (.docx)**.

> "Twenty-nine sections, forty-one tables, thirty charts, generated from the
> published panel on request. Every figure computed."

---

## 9 · The standalone page (60 seconds)

**What-If Analysis** in the sidebar.

> "The same engine without a cohort. Seven guided journeys — delinquency
> movement and behavioural score movement instead of a rating you do not have,
> product and sub-product instead of a sector, and PD, LGD, CCF and collateral
> together as risk parameters."

Open **Product & Sub-product Stress** and press a prompt.

---

## If something asks a question instead of answering

That is the product working. It refuses to guess a unit or a cohort, and it
tells you what it did understand. Press one of the chips it offers.

## If a page is slow

The warm-up after a restart. Everything serves in about a millisecond once it
has finished; give it a minute before the first click.

## What not to claim

Not approved by ANB or SAMA. Not independently validated. Not a production
model. The Early Warning Score is a ranking score, not a calibrated
probability — calibration is declared not applicable on the Model Log, in those
words. The challenger is fitted on this book for comparison and is never the
calculation of record.
