# CP-RA-V2 — freeze and handoff

Everything described here is **SYNTHETIC demonstration material**. Every
customer, employer, housing project, score, rate, exposure, action and policy
clause is invented. None of it is Arab National Bank data, actual customer
distress, or bank-approved policy. Every policy clause the product shows
carries `DEMO_DRAFT - NOT BANK APPROVED`, and the compliance predicate behind
them returns false for all of them by construction.

---

## 1. What was built, and on what

| | |
|---|---|
| Branch | `claude/anb-ten-journeys` |
| Last code commit | `f1e7069e` — *"A card that names a pocket is a card the Cockpit cannot group"*. The head moves as this document and the evidence under `docs/anb-ten-journeys/` are committed on top of it; `git rev-parse claude/anb-ten-journeys` is the head. |
| Baseline SHA | `c0db151f62c34e84b4f7df5faf81e5c9b0c9f647` — *"The workbook the UAT downloaded, kept as evidence"* |
| Ancestry | `c0db151f` **is** an ancestor of the head. The branch was created from it and has never been reset to it, rebased onto anything, or merged with `main`. |
| Commits | 28 on top of the baseline |
| Diff against the baseline | 107 files changed, ~30,700 insertions, 357 deletions |
| Ports | **5334 / 8334** |
| Database | its own, named in `.env.anb2`, never the accepted demonstration's |

### The three builds this one does not touch

| Ports | Build | What this work did to it |
|---|---|---|
| 5328 / 8328 | the frozen retail presentation | never started, never stopped, never bound, never migrated |
| 5330 / 8330 | the accepted ANB Requires Attention demonstration | never started, never stopped, never bound, never migrated |
| 5332 / 8332 | the Agentic Project Planner UAT | never started, never stopped, never bound, and **not** the branch this work is based on |
| 5528, 5538, 5548, 5558, 5568 | Docker database ports | never reused, never stopped |

`launchers/anb2/start-anb2.command` holds the three protected pairs in a
written-down list (`PROTECTED_PORTS="5328 8328 5330 8330 5332 8332"`) separate
from the two it binds, so editing the pair at the top cannot quietly make the
check pass. It stops nothing it did not start: a port held by another process
produces a refusal that names the holder and says explicitly that nothing was
stopped. The database string is read from `.env.anb2` rather than written into
the launcher, and a connection string it recognises as the accepted
demonstration's is refused outright — rebuilding the book, migrating it and
replaying the review all write there.

No password appears in this document, in the repository, or in any log. The
demonstration login is created by the product's own CLI at setup time and its
password is chosen then.

### A remote container is not the user's Mac

This was built and verified in a remote Linux container. Nothing in this work
opened, changed, started, stopped or inspected anything on the user's Mac, and
nothing here claims to have. The launcher, the environment example and the
runbook are delivered as a **setup artifact** to be run there.

---

## 2. The data bundle

One version of six datasets, staged, validated, then swapped atomically. A
partial swap is not reachable: validation runs against the staged tree, and the
previous tree survives byte-for-byte if any check fails.

| | |
|---|---|
| Bundle id | `RB-0E277E3A36345B43` |
| As of | `2026-08` |
| Created | `2026-09-17T23:29:50+00:00` |
| Seed | `20260910` |
| Generator | `retail-gen-1.2.0` |
| Demo config | `1.0.0` |
| Episode config | `retail-episodes-1.0.0` |

### Dataset manifest

| Dataset | Periods | sha256 (first 16) |
|---|---|---|
| `retail_facility_month` | 25 | `f8d959638a7239f2` |
| `retail_ews_panel` | 25 | `4b0c6128d38ed271` |
| `retail_ews_score` | 20 | `12342815b023028d` |
| `retail_early_warning` | 25 | `44083b28f22313b5` |
| `retail_credit_scorecard` | 25 | `0738074af01006b2` |
| `retail_whatif` | 25 | `cf4f73543fd1ecc1` |

### The book itself

| | |
|---|---|
| Months | 25, `2024-08` → `2026-08` |
| Rows, all months | 1,345,633 |
| Rows, latest month | 59,416 facilities |
| Customers, latest month | 42,899 |
| Columns | 595 |
| Gross carrying amount, latest month | SAR 6,492,937,833 |
| Weighted ECL, latest month | SAR 110,924,405 |

### The seven publication checks

All seven passed on the published tree:

| Check | Detail |
|---|---|
| every dataset present | 6 datasets, all with published periods |
| Early Warning ends where the book ends | book `2026-08`, panel `2026-08` |
| every pocket exists in both the Cockpit and Early Warning | all 10 pockets present at `2026-08` |
| the Early Warning join is grain-safe | total ECL 110,924,404.87 before the join and 110,924,404.87 after |
| a facility-month is unique | 59,416 rows, 59,416 facilities |
| the manifest describes this tree | manifest says 59,416 rows and SAR 110,924,405; the tree holds 59,416 rows and SAR 110,924,405 |
| the five registrations survive publication | `retail_credit_scorecard`, `retail_early_warning`, `retail_ews_score`, `retail_facility_month`, `retail_whatif` |

The sixth check exists because an earlier publication passed while the manifest
still described the book it had replaced — 59,412 rows and SAR 70.4m against a
tree holding 59,416 and SAR 110.9m. The manifest is now derived from the tree
(`manifest_from_tree()`) and the swap is gated on the two agreeing. The
seventh exists because the publisher's `write_catalog` replaces rather than
merges, and one run reduced five governed registrations to one.

---

## 3. Model and contract versions

| Contract | Version | Size |
|---|---|---|
| Metric contract | `retail-metric-contract-1.0.0` | 16 metrics |
| Cohort snapshot | `retail-cohort-snapshot-1.0.0` | steps S0–S5 |
| Episode overlay | `retail-episode-overlay-1.0.0` | 50 columns |
| Episode definitions | `retail-episodes-1.0.0` | 10 episodes |

Scorecards, IFRS 9 staging and ECL are the existing retail models at
`retail-gen-1.2.0`; the episodes change the *inputs* those models read
(missed-payment odds, catch-up odds, recovery haircut, recovery delay) and
never the models themselves. Nothing in this work moves a threshold to make a
card turn red: a story whose measured figures do not reach a severity band does
not get that band, and the ten distribute across three bands rather than all
being critical.

---

## 4. Migrations

| | |
|---|---|
| Alembic head | `0043` |
| Added by this work | `0043_cohort_snapshot` — `cohort_snapshots`, `saved_investigations`, `investigation_notes` |

```bash
createdb creditprobe_anb_v2          # or your own name; not creditprobe_retail
.venv/bin/alembic upgrade head
```

The migration is additive. It creates three tables and touches no existing one.

---

## 5. Setting it up on the Mac

```bash
cd ~/path/to/IPM_V2

git fetch origin claude/anb-ten-journeys
git worktree add ../IPM_V2-CPRA claude/anb-ten-journeys
cd ../IPM_V2-CPRA

uv sync
(cd frontend && npm install)

cp .env.anb2.example .env.anb2
$EDITOR .env.anb2                    # set DATABASE_URL to YOUR OWN database

createdb creditprobe_anb_v2
.venv/bin/alembic upgrade head

# The book: 25 months, 59,416 facilities in the latest month, the ten
# episodes inside it. About six minutes.
PYTHONPATH=. .venv/bin/python scripts/publish_retail_bundle.py

# The demonstration login. Choose your own password at the prompt.
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

| Path | What it is |
|---|---|
| `launchers/anb2/start-anb2.command` | starts 5334/8334 after checking the venv, the dataset manifest, the readiness check, the migrations, a complete published bundle, and all four ports |
| `launchers/anb2/stop-anb2.command` | stops only what it started; reports both ports free and names the three protected pairs it did not touch |
| `.env.anb2.example` | the environment to copy and edit; `.env.anb2` itself is git-ignored |
| `docs/anb-ten-journeys/RUNBOOK.md` | how to give the demonstration |

**Verified in this container:** stopped → start → stop → start → stop → start.
Every start reached HTTP 200 on the frontend and on the health endpoint; every
stop reported both ports free and named the three protected pairs it had not
touched. On the final start, under the launcher's own defaults, an
unauthenticated read of `/api/v1/risk-cases` answers 401.

### The state the database is handed over in

| | |
|---|---|
| Risk cases | 16 — entities `Auto Finance`, `Credit Card`, `Home Finance`, `Personal Finance` |
| Statuses | 15 NEW; 1 UNDER_INVESTIGATION (the Alpha card, attached to a seeded workspace investigation) |
| Cohort snapshots | 0 |
| Saved investigations | 0 |

The verification runs leave tracks — nine cards moved to UNDER_INVESTIGATION
with a thread attached, and a snapshot and a saved investigation per journey.
A presenter should open the Cockpit on cards nobody has touched and create
those objects themselves, so the harness's tracks were removed and the review
replayed before the freeze.

---

## 6. The ten demonstration questions

The Cockpit's **Requires attention** panel carries sixteen cases: the ten
stories below plus the six deterioration and impairment findings the retail
review already raised. Open a card, read the drawer, press **Investigate**,
then ask the question in the third column — it is also the first of the five
chips above the composer, so it can be clicked rather than typed.

| | Product | Story | The question to ask |
|---|---|---|---|
| C01 | Credit Card | Alpha Card early arrears | Split 1–29 DPD into 1–9, 10–19 and 20–29 days and show the six-month trend. Is this merely short payment timing? |
| C02 | Personal Finance | Personal finance acquisition quality | Compare booking vintages at exactly month-on-book 6. Split first-default timing into MOB1–2 and MOB3–6, retaining the original eligible population. |
| C03 | Personal Finance | Employer payroll interruption | Split apparent payroll shortfalls into account switches, calendar/posting effects and verified multi-cycle interruptions. Compare matched payroll dates. |
| C04 | Personal Finance | Top-up debt stacking | Split monthly obligations into this bank, other lenders and verified BNPL installments. Separate real growth from reporting-lag and duplicate-line effects. |
| C05 | Auto Finance | Auto balloon funding cliff | Show 0–30, 31–60 and 61–90 day final-payment ladders with liquid funding, sale plans and actually approved refinancing. |
| C06 | Auto Finance | Used-auto recovery deterioration | Reconcile ECL change into PD, LGD, EAD, stage, recovery timing and interaction effects. Which component is actually material? |
| C07 | Home Finance | Self-construction cash-flow strain | Split construction stages and delay bands, then distinguish households paying rent alongside finance from those without overlap. |
| C08 | Home Finance | Housing-support reconciliation gaps | Separate eligibility changes, payable-but-unmatched support, settlement delay and unverified claims; compare one-cycle and repeated gaps. |
| C09 | Personal Finance | Salary-to-pension affordability | Show the verified transition-date ladder and pension projections; separate contracts with an affordable step-down from unchanged payments. |
| C10 | Personal Finance | Restructure redefault and cure governance | Match restructures at six months of observation, then split redefaults by payment holiday, installment relief and cure evidence. |

Each story's named pocket — the concentration the card is about — is on the
drawer under its own heading, in the conclusion's own sentence, and as the
first signal. The card's **entity** is the retail product, because that is what
the Cockpit groups and filters by and every other rule in the product puts a
product there.

---

## 7. What was verified, and how

### Ten journeys in a real browser

`scripts/cpra_browser_journeys.py`, driving Chromium against a running
5334/8334: Cockpit → card → drawer → Investigate → five chips in order →
export at a step → Borrower 360's imported list → save → reopen → workbook
download → What-If handoff.

**10 of 10 journeys, 340 of 340 checks**, at `http://localhost:5334` against
`http://localhost:8334`. 42 screenshots and 10 workbooks in
`var/anb2/acceptance/`; the machine assertions in
`docs/anb-ten-journeys/acceptance/browser_journeys.json`.

The harness drives `localhost` rather than `127.0.0.1`, which is the origin
the launcher prints. Two things break silently otherwise: Next.js in
development serves `/_next/*` only to `localhost` unless a host is added to
`allowedDevOrigins`, so a page opened at `127.0.0.1` renders as an empty
document; and the session cookie is host-only and `SameSite=Lax`, so a page
served from one host calling an API on the other is cross-site and the cookie
is withheld.

The harness authenticates with the product's documented role headers
(`X-IPM-Role`, `X-IPM-User-Id`), which requires the deployment it drives to
have `REQUIRE_LOGIN=false`. The demonstration itself runs with sign-in **on**,
which is the launcher's default, and the presenter signs in as the seeded
account.

The run found three real defects that the pytest gates could not: the case
seed omitted `entity_id`, so the thread opened on the generic segment
question; `_question_for` had no `retail_episode` branch; and `_s3_decompose`
crashed on a missing column. Two of its own assertions were wrong rather than
the pages — chips in a sticky footer are absent from `inner_text` — and were
rewritten against locators.

### Acceptance, row by row

`docs/anb-ten-journeys/acceptance/ACCEPTANCE.md`, generated by
`scripts/cpra_acceptance_manifest.py` from the workbook's own Tests sheet:
**90 pass, 0 fail, 0 not run.** The workbook labels all ninety `NOT RUN IN
APP` because it is a specification and a 100-observation fixture rather than
installed software; this is the same ninety executed against the implemented
SHA. The fixture's expected counts sit *beside* this book's measured ones
rather than being asserted against them, which is the specification's own
instruction: a book of 59,416 facilities computes its own counts.

### The gates this work added

| File | Gates |
|---|---|
| `test_ret_cpra_p1_contracts.py` | 34 |
| `test_ret_cpra_p2_episodes.py` | 22 |
| `test_ret_cpra_p3_bundle.py` | 8 |
| `test_ret_cpra_p4_p6_cards_threads.py` | 25 |
| `test_ret_cpra_p7_p9_workspace.py` | 31 |
| `test_ret_cpra_p10_crosscutting.py` | 26 |
| | **146** |

Among them, `test_every_stage_of_every_story_exports_and_admits_its_cap`
builds **sixty workbooks** — all ten stories at each of the six stages — and
asserts on each that every visited step is marked visited, every later step
reads *Not reached at the exported step*, and the sheets that only exist
downstream carry no rows until the reader has been there.

Several are negative controls, written to fail loudly if the thing they guard
starts happening: a temporal-leakage check that reads the months a step
actually touched, a hostile note that tries to grant itself compliance, a
second reader refused on both the cohort and the investigation.

### Regression attribution

The whole `tests/retail` suite was run file by file **twice on the same
published book**: once on this branch, and once at the accepted ANB head
checked out beside it, with the data, metadata and catalogue directories
pointed at the identical tree. Different code, identical data — a failure
that repeats under both is not this work's.

| | Failures |
|---|---|
| Accepted ANB head | 31 |
| This branch | 29 |
| Fail under both (pre-existing) | 29 |
| **Fail only on this branch** | **0** |
| Fail only at the accepted head (fixed here) | 2 |

The two this work fixes are `test_every_case_names_a_retail_product` and
`test_a_threshold_is_labelled_synthetic_and_configurable` — the card entity
and the threshold wording described above.

Getting to zero took three rounds, and each round's finding is worth
recording because each looked like something it was not:

1. **Forty-five files the surface gate had never been told about.** It
   enumerates what a retail conversion may touch; a new file is a failure by
   design. Extended file by file rather than by loosening the rule.
2. **Two genuine regressions**, both in `episode_cases.py`, both fixed above.
3. **An attribution run that was silently useless.** The accepted worktree's
   fixture reads a hard-coded `data/retail/analytics`, so every test in it
   skipped and the "baseline" was an empty set. Fixed by symlinking the data
   and metadata trees into the accepted checkout, after which the baseline
   was real.

The 29 that fail under both are, by file: `test_ret_adversarial_cockpit` (10),
`test_ret_metrics_library` (7), `test_ret_overnight_completion` (4, the
workspace seeder refusing a database whose URL does not name a retail one),
`test_ret_ews_wiring` (3), and one each in `test_ret_039_045_whatif`,
`test_ret_customer_360`, `test_ret_retail_only_surfaces`,
`test_ret_whatif_fidelity` and `test_ret_whatif_integration`.

---

## 8. What this build deliberately does not claim

- **No compliance claim.** `episode_policy.claims_compliance()` returns false
  for every clause, and every clause is labelled `DEMO_DRAFT - NOT BANK
  APPROVED`. Nothing here is an approved policy, a regulatory position, or an
  ANB decision.
- **No real customer, employer or project.** The employers and housing
  projects carry `DEMO` in their own names for the same reason.
- **Thresholds are demonstration thresholds.** Every card says so in its own
  evidence: *"Synthetic demo thresholds, bank-configurable: at least 20
  affected observations and at least 1.5 times the comparator."*
- **An export admits what it has not seen.** The workbook caps at the step the
  reader actually reached, and a sheet for a step not reached says *"Not
  reached at the exported step"* rather than filling it in.
- **A refusal reads like an absence.** Reading another user's cohort or saved
  investigation returns the same words as reading one that does not exist, so
  the refusal does not confirm the object.
