# CP-RA-V2 — running the ten Saudi retail investigation journeys

Synthetic demonstration material throughout. Every customer, employer, project,
score, rate, exposure and policy clause is invented. Nothing here is Arab
National Bank data, actual distress, or bank-approved policy.

---

## What this build is, and what it is not

It is a **fourth** build of this repository, alongside three that are somebody's
presentation:

| Ports | Build | This work's relationship to it |
|---|---|---|
| 5328 / 8328 | the frozen retail presentation | never started, never stopped, never bound |
| 5330 / 8330 | the accepted ANB Requires Attention demonstration | never started, never stopped, never bound |
| 5332 / 8332 | the Agentic Project Planner UAT | never started, never stopped, never bound |
| **5334 / 8334** | **this build** | started and stopped by `launchers/anb2/` |

It also keeps **its own database**. Rebuilding the data, running migrations and
replaying the portfolio review all write to it, and pointing it at the accepted
demonstration's database would do that to a demonstration somebody is about to
give. The launcher refuses to start if it recognises that name in
`DATABASE_URL`.

---

## First run, on a Mac

```bash
cd ~/path/to/IPM_V2                       # a worktree of this branch

git fetch origin claude/anb-ten-journeys
git worktree add ../IPM_V2-CPRA claude/anb-ten-journeys
cd ../IPM_V2-CPRA

uv sync                                   # the Python environment
(cd frontend && npm install)

cp .env.anb2.example .env.anb2
$EDITOR .env.anb2                         # set DATABASE_URL to YOUR OWN database

createdb creditprobe_anb_v2
.venv/bin/alembic upgrade head

# The book: 25 months, ~59,400 facilities in the latest month, and the ten
# episodes inside it. About six minutes.
PYTHONPATH=. .venv/bin/python scripts/publish_retail_bundle.py

# The demonstration login. Choose your own password.
.venv/bin/python scripts/manage_users.py add anb.analyst --role admin

# The cards.
PYTHONPATH=. .venv/bin/python - <<'PY'
from backend.db.engine import get_session
from backend.retail import review
with get_session() as s:
    print(review.run(s, period="").summary()); s.commit()
PY

open launchers/anb2/start-anb2.command
```

The launcher checks its own prerequisites before it binds anything: the virtual
environment, the dataset manifest, the readiness check, the migrations, a
complete published bundle, and that all four ports it cares about are either
free or already this build's. It stops nothing it did not start.

---

## The ten journeys

Open <http://localhost:5334>. The Cockpit's **Requires attention** panel carries
sixteen cases: the ten stories, plus the deterioration and impairment findings
the retail review already raised.

Each story runs the same way:

1. **Click the card.** The drawer opens on one bottom-line conclusion and six
   stacked panels — affected population, normalised pocket, probability of
   default and loss, scores, the rule that was evaluated, and sources. Every
   figure carries its own denominator and its comparator.
2. **Investigate.** The thread opens on the carried drawer context, with five
   prompt chips above the composer and one marked as the suggested next.
3. **Work the five.** S1 breaks the alerts apart and says how many survive
   verification; S2 holds the same identifiers and compares behavioural
   movement against immutable origination; S3 decomposes what moved and dates
   it against the arrears; S4 normalises the pocket; S5 sequences the actions.
   Rephrasing a chip in your own words reaches the same step.
4. **Export customers to Borrower 360** at S0 or any answered step.
5. In Borrower 360: expand a customer to its facilities, select, add a note,
   **Save investigation**, **Export Excel**, **Export to What-If**.
6. Reopen from the **Recent investigations** cards below the list.

| Case | Story | Product |
|---|---|---|
| C01 | Alpha Card early arrears | Credit card |
| C02 | Personal finance acquisition quality | Personal finance |
| C03 | Employer payroll interruption | Personal finance |
| C04 | Top-up debt stacking | Personal finance |
| C05 | Auto balloon funding cliff | Auto finance |
| C06 | Used-auto recovery deterioration | Auto finance |
| C07 | Self-construction cash-flow strain | Home finance |
| C08 | Housing-support reconciliation gaps | Home finance |
| C09 | Salary-to-pension affordability | Personal finance |
| C10 | Restructure redefault and cure governance | Personal finance |

---

## Three things to say out loud in the room

**C06 is a negative control.** Its borrowers' scores move by about three points
and their probability of default barely moves at all, while the loss given
default more than doubles and the expected loss rises. That is the finding: the
loss is in severity, not in the borrower. A demonstration that quietly worsened
the borrower to make the loss move would be manufacturing the evidence this
story exists to reject.

**Every policy clause is a draft.** No approved bank policy was supplied with
this work, so all thirty clauses read `DEMO_DRAFT - NOT BANK APPROVED`, nothing
claims compliance, and nothing is executed on a customer.

**An export says what it has not seen.** A workbook taken at S1 lists S2 to S5
as *Not reached at the exported step*, and its policy sheet says so in the place
the actions would have been.

---

## Rebuilding the data

```bash
PYTHONPATH=. .venv/bin/python scripts/publish_retail_bundle.py
```

Everything is built into a staging tree, validated, and swapped in one move.
Seven checks gate the swap; a failure leaves the previously published bundle
exactly where it was and names the check that failed. The previous tree is kept
beside the live one as `analytics.previous-<timestamp>` until you remove it.

## Re-running the verification

```bash
# The gates
.venv/bin/python -m pytest tests/retail/test_ret_cpra_*.py -q

# The ten browser journeys, against a running build
PYTHONPATH=. .venv/bin/python scripts/cpra_browser_journeys.py \
    --base http://127.0.0.1:5334 --api http://127.0.0.1:8334
```

Screenshots and workbooks land in `var/anb2/acceptance/`; the machine
assertions are kept in `docs/anb-ten-journeys/acceptance/browser_journeys.json`.

## Stopping

```bash
open launchers/anb2/stop-anb2.command
```

It stops only pids recorded in `var/anb2`, and their descendants, and then says
whether 5334 and 8334 are actually free. It prints the state rather than
assuming it: "Done" over a port that is still held is the message that sends a
presenter into the next start with no idea why it refuses.
