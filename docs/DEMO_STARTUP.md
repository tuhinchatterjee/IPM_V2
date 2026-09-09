# CreditProbe — starting the integrated demonstration

Branch: `claude/creditprobe-integration-plan-vyq22h`. Nothing here is merged to
`main`.

Everything below was run end to end on a container built from an empty
PostgreSQL database. Where a figure appears, it is what the command printed.

## 0. What you need

* Python 3.12 and the project virtual environment at `.venv`
* Node 22 and `frontend/node_modules`
* PostgreSQL 16, running, with a role that can create a database
* No AI provider key is required. The product runs offline; the surfaces that
  need a model say so rather than failing.

## 1. Configuration

```bash
cd /path/to/IPM_V2
cp .env.example .env
```

Then edit `.env` and set these three. Everything else can stay at its default.

```ini
DATABASE_URL=postgresql+psycopg://<user>:<password>@localhost:5432/creditprobe
COCKPIT_AGENTIC_V3=true
NEXT_PUBLIC_API_URL=http://127.0.0.1:8000
```

`COCKPIT_AGENTIC_V3` is off by default. Leave it off and the Cockpit reports
itself unavailable rather than answering from a release it has not got; turn it
on and step 4 gives it one.

`.env` is git-ignored. Put no key in `.env.example`.

## 2. The database

```bash
createdb creditprobe
.venv/bin/alembic upgrade head        # ends at 0049
.venv/bin/alembic heads               # must print exactly one head
```

## 3. The data and the seed

```bash
.venv/bin/python scripts/bootstrap_demo.py
```

Idempotent: it probes the deployment rather than trusting a marker, so running
it twice is safe and running it after a failure resumes. On an empty database it
performs 17 steps (A–R) and ends with

```
17 already in place. The deployment is ready.
All 19 readiness checks passed.
```

having built 80 governed datasets (34 authoritative), 10 business domains, the
corporate book at 3,800 borrowers over 16 quarters Q3 2022 – Q2 2026, 20 Early
Warning monthly snapshots, the Q2 2026 portfolio review, three Playbook
committees and three Playbook workspaces with 30 exported analyses.

If it says a step failed, read the line: it names the step and the remedy, and
you re-run just that one with `--step <name>`.

## 4. The Cockpit's own release

```bash
COCKPIT_AGENTIC_V3=true .venv/bin/python scripts/build_cockpit_agentic_v3.py
```

Prints `integrity: 72 checks, 0 failed` and publishes `demo-20q-v1`.

**Say plainly what this is.** It is the Cockpit's own demonstration book — its
own identifiers, INR in crore, twenty quarters — and it is deliberately separate
from the canonical corporate book the rest of the product reads. Repointing the
Cockpit onto canonical identities is measured, planned and **not** in this
build; see `docs/cockpit_repoint/FIELD_MAPPING.md` and the M4b entry in
`docs/INTEGRATION_LEDGER.md`. Do not present a Cockpit figure as a canonical
Corporate figure.

## 5. Run it

Two terminals.

```bash
# backend
.venv/bin/python -m uvicorn backend.api.main:app --host 127.0.0.1 --port 8000
```

```bash
# frontend — development, and the simplest thing that works
cd frontend
npm run dev
```

For a production build, note that `next.config.ts` sets `output: "standalone"`,
so `next start` prints a warning and the supported command is the standalone
server. Static assets have to be copied beside it once:

```bash
cd frontend
npm run build
cp -r public .next/standalone/ 2>/dev/null || true
cp -r .next/static .next/standalone/.next/
node .next/standalone/server.js        # listens on 3000
```

Open **http://127.0.0.1:3000**.

Check the backend first if anything looks empty:

```bash
curl -s http://127.0.0.1:8000/api/v1/health
```

should report `"status":"ok"`, PostgreSQL connected, and DuckDB serving 83
Parquet datasets.

## 6. Signing in

Every demonstration account uses the password **`creditprobe-demo`**.

| Username | Role |
|---|---|
| `alex.rahman` | Administrator |
| `sara.qahtani` | Data steward |
| `omar.nasser` | Analyst |
| `layla.haddad` | Viewer |

`.venv/bin/python -c "from backend.services.demo_users import DEMO_USERS; print([u['username'] for u in DEMO_USERS])"`
lists them all.

## 7. What to show

| Surface | Route |
|---|---|
| Cockpit | `/` |
| Early Warning V2 | `/early-warning` |
| What-If Analysis | `/what-if` |
| Lenses | `/lenses` |
| Playbook — drafting and the committee cycle on one page | `/playbook` |
| Playbook — exported-analysis library | `/playbook/library` |
| Project Planner | `/projects` |
| Scorecard Validation | `/scorecard-validation` |
| Scorecard Validation — deep monitoring | `/scorecard-validation/monitoring` |
| Borrower 360 | `/borrower-360` |
| Data Builder | `/data-builder` |

Three routes are deliberately retired and redirect rather than 404: `/stress`
goes to `/what-if`, `/early-warning/signals` goes to `/early-warning`, and
`/playbooks` (plural) is gone entirely. No navigation entry points at any of
them.

## 8. Two things to know before you demonstrate

**Do not run the backend test suite against the demonstration database.** The
suite and the demonstration share it, and the suite's fixtures delete seeded
committees and packs as they tear down. If you have run it, re-run
`scripts/bootstrap_demo.py` — it takes seconds.

**Without an AI provider key**, every model-backed surface says so rather than
failing: the Playbook composer explains that generation needs a configured
provider while every seeded workspace, its sources and its Word, PDF and
PowerPoint files stay readable; the Cockpit stops at its first request with
`MODEL_CONFIGURATION_MISSING` rather than at boot. To enable them, set
`COCKPIT_ANTHROPIC_API_KEY`, `AI_COCKPIT_PREPROCESS_MODEL` and
`AI_COCKPIT_REASONING_MODEL` in `.env`. The Cockpit reads its **own** credential
and never `ANTHROPIC_API_KEY`, deliberately, so its calls cannot be billed
against whoever is driving the tooling.
