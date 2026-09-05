# The Retail Credit Risk demonstration

Four programmes, one agentic scenario, and a seven-minute story. Everything
below is produced by the rules rather than staged: the colours are calculated,
the reminder fires because a date and a percentage say it should, and the
critical path is arithmetic over the dependency network.

```
.venv/bin/python scripts/seed_retail_portfolio.py            # build
.venv/bin/python scripts/seed_retail_portfolio.py --check    # report only
.venv/bin/python scripts/seed_retail_portfolio.py --reset    # rebuild
```

`--reset` refuses to run unless `ENV` is a development value or Synthetic Data
Mode is on, and it removes only the four programmes named in the script.

Every date is an offset from the day it is seeded, so the demonstration is as
true in November as in March. Nothing is pinned to a month.

---

## The portfolio

| Code | Programme | Health | Why |
|---|---|---|---|
| `RET-IFRS9` | Retail IFRS 9 — current month ECL production | **AMBER** | Overdue data exceptions, three near-term tasks nobody has updated, an open high risk on the overlay sign-off, and unresolved dependencies |
| `RET-SCORECARD` | Retail Application Scorecard Redevelopment | **AMBER** | One overdue analysis and two high-severity items open |
| `RET-COLLECTIONS` | Retail Collections Strategy Optimisation | **GREEN** | Nothing overdue, blocked or stale, and no milestone at risk |
| `RET-DATA-REM` | Retail Credit Risk Data Remediation Programme | **RED** | Three critical tasks overdue and two critical dependencies unresolved |

130 tasks and subtasks, 30 workstreams, 22 milestones, 58 dependencies and 16
RAID items. Each programme carries work that is complete, in progress, due
today, due soon, overdue, blocked with a reason, stale and awaiting review —
because a plan without the awkward parts in it proves nothing.

## The cast

Ten people, at five different access levels, because a demonstration where
everybody can change everything proves nothing about the permission model.

| Person | Role | Where they matter |
|---|---|---|
| Ananya Shah | Head of Retail Credit Risk | Sponsor on all four; hears when one turns red |
| Priya Raman | Retail Risk Transformation Lead | Manages the scorecard redevelopment |
| Rohan Mehta | Retail Credit Modelling Lead | Owns the modelling chain on two programmes |
| Neha Kapoor | IFRS 9 / Provisioning Lead | Manages the monthly ECL run |
| Sameer Iqbal | Retail Risk Data Lead | Manages remediation; owns the blocked chain |
| Fatima Khan | Finance Controller | Owns **Management Overlay Sign-off** — the scenario |
| Daniel Lee | Independent Model Validation Lead | **Viewer** access: reads everything, changes nothing |
| Maya Singh | Collections Strategy Lead | Manages collections |
| Omar Rahman | Technology / Decision Engine Lead | Contributor on three |
| Kavita Rao | Retail Credit Policy Lead | Reviewer; **viewer** access on two |

They share the demonstration password, so a presenter can sign in as Fatima
and see *her* work rather than an administrator's view of everybody's. That is
the whole point of My Work and it cannot be shown from one account.

---

## The agentic scenario

**Management Overlay Sign-off** (`T-503` on `RET-IFRS9`) is owned by Fatima
Khan, IN_PROGRESS at 30%, due in three days. Three is one of the project's
reminder thresholds, so the sweep reminds her — nobody presses a button.

It is also genuinely on the calculated critical path:

```
T-503 → T-604 → T-606 → T-703 → T-704 → M-6 Month-End Posting
```

which is why the reminder matters rather than merely existing.

**What happens, in order:**

1. The worker offers a governed schedule tick every minute. The tick fires the
   hourly *Project Planner commitment sweep*, which enqueues a `planner_sweep`
   job.
2. The sweep reads the plan deterministically. `T-503` is due in three days
   and three is a reminder threshold, so Fatima is told — once, because the
   reminder is fingerprinted on the date and the threshold.
3. She receives **"Action required — Management Overlay Sign-off"**, with the
   date, the progress, and the line *"Please update your progress, blocker and
   next step."* It deep-links to the task, not to the portfolio.
4. Fatima signs in, opens it from the notification, and moves it to 80% with
   *"Overlay calculation is complete. Finance review is underway."* and a next
   step of *"Obtain Finance approval and submit for CRO sign-off."*
5. That one save writes the history row, the audit record, her own
   `last_update_at`, the workstream percentage, the project percentage, and —
   because it is a material change — enqueues a re-evaluation of the project.
   The recalculated health and the chase eligibility both move with it.
6. Neha asks **"What changed on Retail IFRS 9 since I last checked?"** and
   gets the actual movement, 30% to 80%, from the append-only history rather
   than from a diff of two snapshots.
7. Neha asks **"If T-503 slips by two days, what gets affected?"** and gets the
   answer by recomputation: the downstream tasks that move, by how many days,
   and whether the month-end posting date moves with them.

Nothing in that sequence needed a person to remember anything.

---

## The seven-minute story

**Scene 1 — the estate (60s).** Open Project Planner. Four Retail Risk
programmes, one green, two amber, one red, each with the reason written out
beside it. *"Nobody typed these colours. They are what the rules make of the
dates."*

**Scene 2 — what needs me (45s).** Ask: *"Which Retail Risk projects need my
attention today?"* The Attention panel and the answer agree, because both come
from the same engine.

**Scene 3 — the reminder (60s).** Show Fatima's notification. *"Nobody had to
remember to chase her. CreditProbe watches the commitments — the date, the
progress, how long since anybody said anything, and whether anything is
waiting behind it."*

**Scene 4 — the owner replies (60s).** Sign in as Fatima. Open the task from
the notification. 80%, the narrative, the next step. Save.

**Scene 5 — what changed (45s).** Back as Neha: *"What changed since I last
looked?"* The movement, named, with who said it and when.

**Scene 6 — the management questions (90s).**
*"Who owes us an update across Retail Risk?"* ·
*"What is due in the next seven days?"* ·
*"Which project has the greatest schedule risk?"* ·
*"Prepare my Retail Credit Risk project review."*

**Scene 7 — the governance point (60s).** Ask: *"Move CRO Sign-off out by two
weeks."* CreditProbe does not. There is no registered capability that moves a
due date, and the refusal says so and says where to do it instead. *"The AI
tells you what is true and asks people for what it needs. It does not change
what the bank has committed to."*

---

## What is calculated and what is written down

Calculated from the rules, and therefore liable to change if the data does:
health and its reason, weighted progress, what is overdue, blocked or stale,
who gets chased and why, the critical path, float, and downstream impact.

Written down by people: every status, every percentage, every date, every
owner, every risk. The seed writes them through the same service a person
would, so every row is subject to the same validation and lands in the same
history.
