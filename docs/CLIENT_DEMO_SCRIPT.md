# Client demo script

Twenty minutes on the main path, thirty with the deep sections. Every click
and every question is exact. Sign in as **alex.rahman** unless a step says
otherwise.

Before you start: `.\scripts\demo-check.ps1` must say **GO**.

The questions are asked live, against the presenter's own key. Nothing here is
pre-answered — §26 forbids preloading a model answer, and a demonstration of
cached answers is a demonstration of a cache.

---

## A. Thirty seconds — what this is

> "CreditProbe is a credit portfolio intelligence platform. You ask a question
> in plain language; it plans the analysis, runs it on governed data, and shows
> you exactly how it got there. The language model plans and explains. It never
> calculates — every figure comes from the deterministic engine."

Point at the **DEMO — SYNTHETIC DATA** chip in the header.

> "This is a synthetic Saudi corporate book generated for demonstration. None
> of it is anyone's real data."

**Do not say:** "it's AI-powered" as a headline. The audience has heard it.
The differentiator is the Trace.

---

## B. Two minutes — the Cockpit, and a straightforward question

Ask, exactly:

> **What is total EAD by sector in the latest quarter?**

**Expect:** a table, one row per sector, Q2 2026. The officer badge reads
**Credit Analyst**.

> "Note the badge. This is a straightforward aggregation, and it was done by
> the equivalent of a credit analyst. Watch what happens when I ask something
> harder."

**Fallback if slow:** talk over the working indicator — it shows real stages,
not a fake percentage. If it fails, move to section D and come back.

---

## C. Two minutes — conversation memory

Ask, in the same thread, exactly:

> **Show only the five largest.**

**Expect:** the same analysis, five rows. It did not ask what "five largest"
means.

Then:

> **Show each one's share of portfolio EAD.**

**Expect:** a share column. Then:

> **Show as a graph.**

**Expect:** the same figures as a chart. Nothing recomputed.

> "Four questions, one thread. It carried the sector, the period and the
> measure forward, and the last one changed only how it is drawn."

---

## D. Three minutes — escalation, and the agentic layer

Ask, exactly:

> **Review the latest portfolio and tell me what genuinely requires CRO
> attention.**

**Expect:** the badge reads **Chief Orchestrator**. Three or more specialists.
The working indicator names them.

> "Different question, different machinery. It selected a Chief Orchestrator,
> engaged specialists across IFRS 9, ratings and delinquency, and ran their
> analyses as a coordinated investigation. That badge is not decoration — I can
> show you what each one read."

**The point to land:** the officer level predicts the execution path. A
different badge over the same work would be theatre.

---

## E. Four minutes — the Trace. The heart of it.

Open **Trace** on the portfolio review.

1. **STORY** — readable without a click. "This is what it did, in order."
2. **LINEAGE** — the DAG. "Every step, clustered."
3. Open the **mathematical query node**. Show the SQL. **Copy Query**.
   > "That is the actual query. Not a description of one. You can run it
   > yourself against the same data and get the same number."
4. **AUDIT** — the complete non-spatial view.
5. Show the **Assurance** panel.
   > "This is Operational Assurance — did the process hold. It is not an
   > accuracy score and we never label it as one."

**The sentence that matters:**
> "This is why a CRO can sign off on it. Not because the AI said so, but
> because every number traces to a query over a governed dataset."

---

## F. Two minutes — Requires Attention

Back to the **Cockpit**. Scroll to **Requires Attention**.

**Expect:** five cases from the Q2 2026 review — one Segment, four Borrower.
The filters read ALL / PORTFOLIO / SEGMENTS / BORROWERS / DATA.

Open the Segment case.

> "These were not written by a model. A deterministic screen ran over the whole
> book, found what moved materially, and the specialists enriched only what
> survived it."

**Be ready for:** "why is PORTFOLIO empty?"
> "Because nothing at portfolio level moved materially this quarter, and
> nothing at all is wrong with the data. It shows zero rather than inventing
> something to fill the filter."

That is a strong answer. Do not apologise for it.

Click **Investigate** on the Borrower case. It opens an Investigation on that
borrower.

---

## G. Three minutes — Projects and scope

Open **Projects** → **Contracting sector deep dive**.

Show: the Project-only Investigation, the three saved Analyses, the status.

Open the Project-only Investigation and ask a follow-up in it.

> "This thread lives inside the Project. It is not visible globally, and it
> stays that way until somebody publishes it deliberately."

Open an Analysis from the Project, then **Trace**, then **Back**.

> "It returned me to the exact place in the Project thread I left. Losing your
> place is how people stop using a tool like this."

---

## H. Two minutes — Workflow

Still in the Project, **Send for Review** to **Omar Nasser**.

Then sign out and in as **omar.nasser** / `creditprobe-demo`.

**Expect:** the review in the inbox, with a notification and a deep link
straight to the Project.

Add a comment. **Approve**.

> "Append-only history. Who sent it, who opened it, who approved it and when."

Sign back in as **alex.rahman**.

---

## I. Two minutes — Data Builder

Open **Data Builder**.

Show: the **Domain Library**, the twenty governed datasets, the periods, the
row counts, the field dictionary.

Open **Relationships**.

> "These are governed objects, not guesses. When CreditProbe joins ratings to
> IFRS 9 staging, it uses this path, and the Trace names it."

Open one dataset and show the data grid and its publication state.

---

## J. Two minutes — Analysis Studio

Open **Analysis Studio**.

Show a **certified** method — the double blue tick. Open it: what it measures,
the methodology, the inputs, the validation pack, the version and governance.

> "A method is certified when its validation pack passes, not when somebody
> ticks a box. Forty-three of these are certified today. Anything not
> certified says so on its face."

---

## K. Two minutes — Excel

Back to the EAD-by-sector Analysis.

1. **Download Results** → open it.
   RESULTS first, SUMMARY present. Check one figure against the screen.
2. Open **Trace** → **Download Full Calculation** → open it.
   COVER first, FINAL RESULTS last. Scroll: data sources, profiles, joins, row
   counts, filters, transformations, SQL and IR, validations, invariants, the
   Trace ledger, the interpretation evidence.

> "That is the whole calculation, in a workbook, for a model validator or an
> auditor. It reconciles to what is on the screen."

**Have both files already downloaded** as a fallback. If a download is slow,
open the saved copy and say you prepared it earlier.

---

## L. Two minutes — trust

Back to the last answer.

1. **Answer Assurance** — the coverage, the checks, the critical gates.
2. **"Was this answer accurate and useful?"** — the feedback prompt.
   Answer **Partly**, pick a category, close it.
   > "That is recorded as evidence. It changes nothing automatically. No
   > production behaviour, no assurance verdict, no score. Improvement goes
   > through reviewed teaching cases and a governed release."
3. The **AI panel** in the header — provider, model roles, live-verification
   status.
   > "It tells you whether this exact build has been verified against the live
   > model, and it says STALE when the code has moved on."

Then, if the audience is technical, ask exactly:

> **What does the circular say about provisioning for Stage 2?**

**Expect:** a refusal. It says it answers such questions only from an approved
Regulatory Knowledge Release, that none is active, and that it will not answer
from the analytical data instead.

> "That is the behaviour that matters most. It had data about provisioning and
> about Stage 2 and it still refused, because you did not ask what the numbers
> are — you asked what the regulator requires, and nobody has approved a source
> for that here."

---

## The deep path — ten more minutes

Insert after E.

**E2. The hard question.** Ask exactly:

> **Which large Real Estate customers have worsening DPD, increasing ECL, a
> downgrade and covenant headroom below 15%?**

Four conditions across four domains. Chief Orchestrator, four specialists,
five datasets. **This is the slowest question in the set** — say what it is
doing while it runs.

**E3. Ambiguity.** Ask exactly:

> **Show me exposure.**

**Expect:** a clarification. It asks which measure.

> "Limit, drawn, EAD and net exposure are four different amounts. Guessing
> would have produced a confident wrong answer, and you would have had no way
> to know."

**E4. The limit of the data.** Ask exactly:

> **Which borrowers had their CEO resign?**

**Expect:** it says it holds no governed data about that, and names what it
looked for.

> "Not an error. An answer. It did not run something adjacent and hope."

**E5. Agent Operations** (Admin only). The twelve specialists, the runs, the
costs, the approval queue.

---

## What not to say

* Do not say **"accurate"** about the Assurance figure. It is Operational
  Assurance — whether the process held.
* Do not claim **99.99% accuracy**. It is not demonstrated and is
  statistically unproven. See `docs/DEMO_KNOWN_LIMITATIONS.md`.
* Do not say **"it learns from your feedback"** without the rest of the
  sentence. Feedback is evidence; a governed release is what changes anything.
* Do not promise **Arabic**, **document authoring** or a **Regulatory screen**.
  None of those is built. The earlier Playbooks feature — a standing
  instruction that ran certified analyses — no longer exists at all; the
  name now belongs to the committee pack system at `/playbook`.
* Do not promise that the Playbook **chases people automatically**. The
  committee sweep shows what it would send; opening the screen sends
  nothing.
* Do not say the model **calculated** anything. It planned and explained.
* Do not present past a **NO-GO**.

---

## Timing

| Section | Minutes |
|---|---|
| A intro | 0.5 |
| B first question | 2 |
| C conversation memory | 2 |
| D escalation | 3 |
| E Trace | 4 |
| F Requires Attention | 2 |
| G Projects | 3 |
| H Workflow | 2 |
| I Data Builder | 2 |
| J Analysis Studio | 2 |
| K Excel | 2 |
| L trust | 2 |
| **Main path** | **~20** |
| E2–E5 deep path | +10 |
