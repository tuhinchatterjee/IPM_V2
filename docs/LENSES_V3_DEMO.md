# Lenses V3 — the demonstration

Seventeen minutes, one screen, no slides. §56.

The whole point is that nothing here is staged: the formula is typed live, the
code is generated live, the numbers come off the real book, and the change in
the second half is a change to the source data that every figure downstream
recomputes from.

---

## Before you start

```bash
./scripts/dev.sh                                   # the stack
python scripts/lens_demo_change.py --status        # should say "original"
```

If it says `CHANGED`, run `--restore`. A book that is already deteriorated
makes the second half of the demonstration say "no material change", and the
question you will be asked is why the product is broken.

Sign in as an analyst. Open **Lenses → CRO Portfolio**.

> **The CRO Portfolio Lens is the one to use.** It carries Stage 2 Ratio from
> the Cockpit domain and the watchlist, deteriorating and covenant metrics
> from Early Warning, which is what makes step 15 possible. The other shipped
> Lenses work; they tell half the story.

---

## Part one — a formula becomes a governed metric

**1. Show what is already there.** The Lens opens on twenty tiles: exposure,
limits, staging, ECL coverage, the early-warning rates. Point out that every
one of them names a governed metric — the info control on any tile shows the
formula, the dataset and the grain.

**2. Say what is missing.** "There is no quarter-on-quarter exposure change on
this screen, and the CRO asks for it every quarter."

**3. Type the formula.** Click **Edit**, then **Add metric**. In the formula
box:

```
Add QoQ Exposure Change: (Current Quarter Exposure / Previous Quarter Exposure) - 1
```

Click **Write the code**.

**4. Read what came back — slowly.** This is the part worth dwelling on. The
definition card shows:

- **Your formula**, character for character. Not a normalised version of it.
- **Interpreted formula** — what CreditProbe understood it to mean in terms of
  governed metrics.
- **Plain English** — the numbered steps somebody would follow with a pencil.
- **The code** — read-only SQL over the governed dataset names.
- **Dataset, grain, period logic, aggregation, unit.**
- A badge saying **who wrote the code**. With no AI provider configured it
  says CreditProbe assembled it; with one it says CreditProbe AI wrote it.

Expand **"The statement CreditProbe will run"**. Say the sentence that
matters:

> *The model writes the code. CreditProbe validates it. You approve it.
> CreditProbe runs its own compiled plan. The model's SQL is never sent to a
> database.*

**5. Approve it.** Type what you checked in the note box — "checked against
the quarterly pack" — and click **Approve Code & Preview**.

**6. Read the preview.** This is §12's list, on screen:

```
Current Quarter Exposure · Q2 2026     74,017.555
Previous Quarter Exposure · Q1 2026    74,352.67
(74,017.555 / 74,352.67) − 1 × 100 = −0.4507
```

Point at the two periods. The metric read two quarters, and it says which.
Below it: the population, the datasets, the data version and the code version.

**7. Lock it.** The metric goes onto the Lens.

**8. Reload the page.** It is still there. It is now a governed user metric
with its whole approval record stored beside it — the formula as typed, the
generated code, the validation report, and the note you wrote.

### Optional, if somebody asks about the formula direction (2 minutes)

Add another metric and type the formula backwards:

```
Previous Quarter Exposure / Current Quarter Exposure - 1
```

CreditProbe does not correct it. It flags it:

> *You entered Previous Quarter Exposure / Current Quarter Exposure - 1. That
> divides the PREVIOUS period by the CURRENT one, which is the inverse of the
> conventional growth calculation.*

with three buttons: **Keep My Formula**, **Use Conventional Formula**, **Edit
Formula**. Keep theirs. The number comes out **+0.45%** where the conventional
one gives **−0.45%** — genuinely different, pointing opposite ways. That is
what makes the flag worth having rather than a formality.

### Optional, if somebody asks about the domain boundary (1 minute)

Type a formula that reaches for the Scorecard domain — "Gini divided by total
exposure". CreditProbe refuses it by name:

> *'pd_model_performance' is not available to a Lens. Model performance
> belongs to the Scorecard domain, which a Lens may not read. Gini, KS and PSI
> are Scorecard Validation's to publish.*

And it is not a repairable refusal — a model asking for another product's
domain does not get another try at writing a query.

---

## Part two — the Lens notices what changed

**9. Show the What Changed panel.** At the top of the Lens:

- Reporting period · Q2 2026
- Last refreshed · just now
- Compared with · the refresh before this one
- Data changes detected · Cockpit unchanged, Early Warning unchanged
- **No material changes were detected since the previous comparable refresh.**

Then read the three facts underneath it: the reporting period is unchanged, no
source dataset was republished, no metric definition changed.

> *A dashboard that produced an interesting narrative every morning would be
> producing it whether or not anything happened. This one says nothing
> happened, and says how it knows.*

**10. Move the book.** In a terminal:

```bash
python scripts/lens_demo_change.py --apply
```

It reports what it did:

```
Moved 220 facilities in Q2 2026:
  stage 2                   2,359  ->       2,579
  on watchlist              8,563  ->       8,783
  high/critical EWS         1,183  ->       1,403
  covenant breached             7  ->           8
  ifrs9 stage 2             2,359  ->       2,579   (ifrs9_staging)
```

Say what that is: a cohort of facilities with the least covenant headroom has
deteriorated, coherently, in both the facility position and the impairment
staging table. Nothing was written into a results table — this is the source
data the engine reads.

**11. Reload the Lens.**

**12. Read the header.** It now says:

- Data changes detected · **Cockpit changed**, **Early Warning changed**
- Classification · **Source data changed, values changed**

**13. Read what changed.** Stage 2 Ratio from 13.30% to 14.58%. Watchlist
Exposure Rate, Deteriorating Exposure Rate and Covenant Breach Exposure Rate
all up. Each movement carries both figures and the difference.

**14. Point at the evidence chips.** Every sentence carries the rung of the
evidence ladder it stands on — FACT, CHANGE, CORRELATION, INTERPRETATION. If a
claim was downgraded from "confirmed driver" for want of a mechanism, the chip
carries an arrow and the tooltip says why.

> *It may say Stage 2 and the early-warning signals moved together. It may not
> say one caused the other, unless the data contains a figure that IS the
> mechanism.*

**15. The corroboration.** This is the credit point, and it is why the CRO
Lens is the right one:

> *The Cockpit domain says the book's own view of the risk moved — 220
> facilities into Stage 2. The Early Warning domain says the signals moved
> with it — more names on the watchlist, more covenant headroom gone, more
> deteriorating trends. Those are two independent readings of the same
> quarter, and they agree.*

The panel reports them separately, so a reader can see the corroboration
rather than being told about it.

**16. Open a metric's history.** Click **History** under Stage 2 Ratio. Two
lists, labelled apart:

- **Refresh history** — what this metric said each time the Lens ran
- **Reporting period history** — what it said for each business period

Three refreshes today, one reporting period. Say why that matters:

> *Those are different questions. Three refreshes of one quarter is a
> restatement. Three reporting periods is the book moving. A screen that
> showed one under the other's heading would be read with complete confidence
> and be wrong.*

**17. Put it back.**

```bash
python scripts/lens_demo_change.py --restore
```

---

## The four sentences to land

1. **The user owns what their formula means.** CreditProbe locates it, never
   rewrites it, and flags an unconventional one rather than correcting it.

2. **The model writes the code and CreditProbe validates it.** Nine checks,
   all run together, each refusal carrying what would fix it — and the model's
   SQL is never executed.

3. **Nobody's metric runs until they have read the code and said so.** The
   approval is bound by a checksum to exactly what was approved.

4. **A Lens knows what it said last time, and can tell a restatement from a
   movement.** Because it records when it was calculated and which period it
   describes as two different things.

---

## If something goes wrong

| what you see | why | what to do |
|---|---|---|
| "No material changes" after `--apply` | the Lens was opened between the change and the reload, so this refresh compares against one that already saw it | `--restore`, reload, `--apply`, reload |
| The formula builder is not on the Lens | you are not in edit mode | click **Edit**, then **Add metric** |
| "Assembled by CreditProbe" on the code | no `ANTHROPIC_API_KEY` is configured | expected in this environment; say so — the feature works either way and the badge is honest about which |
| The metric will not lock | the preview has not run | approve and preview first; a metric nobody has seen a number for is a metric nobody has checked |
| "Baseline refresh recorded" | the Lens has no history yet | that is correct on a first open; refresh once more |
