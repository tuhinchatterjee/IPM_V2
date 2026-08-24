# IPM — Credit Portfolio Intelligence & Monitoring

An AI-native credit-risk analytical platform for banks.

The language model interprets the question, plans the investigation and writes the
explanation. **Every figure is produced by a deterministic, versioned, tested
engine** — and every result is fully traceable back to the data, filters,
parameters and function version that produced it.

> **New here?** Jump straight to
> [How to run IPM locally — for a non-developer](#how-to-run-ipm-locally--for-a-non-developer).

| Document | What it covers |
|---|---|
| [docs/PRODUCT_SPEC.md](docs/PRODUCT_SPEC.md) | What the product is: the 16 capabilities, the LLM/engine boundary, the Trace model |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | How it is built: layers, data architecture, repository structure |
| [docs/DEMO_SCOPE.md](docs/DEMO_SCOPE.md) | What is being built, in what order, and what is honestly not built yet |

---

## The governing rule

**The language model is not the calculator and is not the source of truth.**

| The language model does | The IPM Engine does |
|---|---|
| Understand the question | Retrieve, filter and aggregate data |
| Interpret intent | Compute portfolio metrics |
| Build an investigation plan | Compute stage and DPD migration |
| Choose approved IPM analyses | Compute rating transition matrices |
| Select parameters | Analyse ECL and deterioration |
| Interpret returned results | Run stress scenarios |
| Write the narrative | Return structured numerical output |

Enforced mechanically, not merely requested: the model's only numeric-facing
output is a **plan**, validated against the engine registry. It may name only
registered analyses, with parameters that satisfy each analysis's declared
contract. Anything else is **rejected before execution**.

*The model can order from the menu. It cannot cook.*

---

## Run IPM on Windows with Docker — no Node.js or Python required

**This is the easiest way to run IPM, and the one to use if your company blocks
software installation.** Everything IPM needs — the interface, the analytics and
the database — runs inside Docker. The only thing on your own machine is Docker
Desktop.

### Before you start

Install **Docker Desktop** once, from
https://www.docker.com/products/docker-desktop/, and open it. Wait until it says
**Running** in the bottom-left corner. That is the only installation required.

### Start IPM

Open **PowerShell** (press Start, type `PowerShell`, press Enter), then:

```powershell
cd C:\Users\T.Chatterjee\IPM_V2
docker compose up --build
```

Or use the helper script, which checks Docker first and tells you when IPM is
actually ready rather than only started:

```powershell
cd C:\Users\T.Chatterjee\IPM_V2
.\scripts\start-docker.ps1
```

### What to wait for

The **first** run downloads the base images, installs everything and compiles the
interface. **Expect 5 to 10 minutes.** Every run after that takes about 15
seconds, because Docker reuses what it already built.

You will see a lot of scrolling text. These are the lines that matter:

```
ipm-backend  | [ipm] PostgreSQL is ready.
ipm-backend  | [ipm] Applying database migrations...
ipm-backend  | [ipm] Database schema is up to date.
ipm-backend  | [ipm] Building the analytical layer from data/raw (first run only, ~20 seconds)...
ipm-backend  | [ipm] Analytical layer built.
ipm-backend  | [ipm] Starting the IPM API on 0.0.0.0:8000
ipm-frontend | ✓ Ready
```

When you see `Ready`, IPM is up.

### Open it

> ### http://localhost:3000

Also available:

| | |
|---|---|
| The application | http://localhost:3000 |
| API health check | http://localhost:8000/api/v1/health |
| API documentation | http://localhost:8000/docs |

Everything works with no AI key: Ask IPM reads your questions with its own
built-in planner and still runs the real analytical engine.

### Stop it

Press **Ctrl + C** in the PowerShell window, then:

```powershell
docker compose down
```

Or:

```powershell
.\scripts\stop-docker.ps1
```

Your database is kept, so your saved investigations are still there next time.
To erase it and start completely fresh, use `.\scripts\stop-docker.ps1 -EraseData`
(or `docker compose down -v`).

### Rebuild after pulling new code

```powershell
git pull
docker compose up --build
```

If something seems stale, force a clean rebuild:

```powershell
docker compose build --no-cache
docker compose up
```

### If something goes wrong

| What you see | What it means | What to do |
|---|---|---|
| `Cannot connect to the Docker daemon` | Docker Desktop is not running | Open Docker Desktop, wait for **Running**, try again |
| `port is already allocated` | Something else is using port 3000 or 8000 | Close it, or set `WEB_PORT=3001` / `API_PORT=8001` in `.env` |
| The page loads but says **Cannot reach the IPM backend** | The backend is still starting | Wait a minute. If it persists: `docker compose logs backend` |
| `Could not connect to PostgreSQL after 60 seconds` | The database did not start | `docker compose logs db` |
| `env: 'bash\r': No such file or directory` and the backend exits with 127 | The repository was checked out with Windows line endings before `.gitattributes` pinned them | `git pull`, then `docker compose build --no-cache backend`. To tidy the working tree as well: `git add --renormalize .` then `git checkout -- .` |
| The build fails downloading packages | A corporate proxy is inspecting HTTPS traffic | Ask IT for your proxy's certificate authority file, then see the note at the top of `docker/backend.Dockerfile` about the `PYTHON_IMAGE` and `NODE_IMAGE` build arguments |

To see what every part is doing:

```powershell
docker compose logs -f
```

### How it fits together

```
your browser  ──►  frontend container (Next.js, port 3000)
                        │  forwards /api/... over Docker's internal network
                        ▼
                   backend container (FastAPI, port 8000)
                        │                       │
                        ▼                       ▼
                   db container            data\ on your machine
                   (PostgreSQL)            (Parquet, read by DuckDB)
```

The browser only ever talks to **one** address, `localhost:3000`. The frontend
passes API calls through to the backend inside Docker, so there is no second
address to configure and nothing to get wrong. The analytical data stays in the
`data\` folder in your repository rather than being copied into a container, so
it is never duplicated and the Parquet layer IPM builds on first start is still
there next time.

---

## How to run IPM locally — for a non-developer

The alternative to Docker: IPM running directly on your machine, which gives
instant reload when code changes. Written for someone who does not write
software. Every step is spelled out. If a step fails, the error message tells
you exactly what to do.

> If you only want to *use* IPM rather than change it, use
> [Run IPM on Windows with Docker](#run-ipm-on-windows-with-docker--no-nodejs-or-python-required)
> above instead — it needs nothing installed but Docker Desktop.

### What you need to install first

Three things, once. Install each one and accept all the defaults.

| # | What | Where to get it | How to check it worked |
|---|---|---|---|
| 1 | **Docker Desktop** — runs the database for you, so you never have to install or configure a database yourself | https://www.docker.com/products/docker-desktop/ | Open it. Wait until it says **Running** in the bottom-left corner. |
| 2 | **Node.js** (version 20 or newer) — runs the user interface | https://nodejs.org/ (choose the **LTS** version) | Open a terminal and type `node -v`. You should see something like `v22.x.x`. |
| 3 | **Python** (version 3.11 or newer) — runs the analytics | https://www.python.org/downloads/ | Type `python --version`. You should see `3.11` or higher. |

> **Windows users:** when installing Python, tick the box that says
> **"Add python.exe to PATH"** on the very first screen. It is easy to miss and
> everything else depends on it.

**"Open a terminal" means:**
- **Windows** — press the Start button, type `Windows Terminal`, press Enter.
- **Mac** — press ⌘ + Space, type `Terminal`, press Enter.

Then move into the IPM folder by typing `cd ` (with a space) and dragging the IPM
folder onto the terminal window, then pressing Enter.

---

### Step 1 — Set it up (once)

**Mac or Linux:**
```bash
./scripts/setup.sh
```

**Windows:**
```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
cd frontend
npm install
cd ..
copy .env.example .env
.venv\Scripts\python scripts\build_data_lake.py
```

This installs everything IPM needs and converts the sample credit data into the
format the analytics engine reads. It takes a few minutes the first time.

---

### Step 2 — Set your database password (once)

Open the file called **`.env`** in the IPM folder with any text editor (Notepad
is fine). Find these two lines:

```
POSTGRES_PASSWORD=change_me_local_dev_password
DATABASE_URL=postgresql+psycopg://ipm_app:change_me_local_dev_password@localhost:5432/ipm
```

Replace **`change_me_local_dev_password`** in *both* places with a password of
your choosing. It must be identical in both lines. This password only protects
the database running on your own computer.

Save the file and close it.

> **Never share or commit the `.env` file.** It is already excluded from git, so
> it will not be uploaded anywhere.

---

### Step 3 — Start IPM

Make sure **Docker Desktop is open and running**, then:

**Mac or Linux:**
```bash
./scripts/dev.sh
```

**Windows:**
```powershell
.\scripts\dev.ps1
```

You will see it start each part in turn, checking each one is ready:

```
> Checking prerequisites
  [ok] Docker is running
  [ok] Node.js v22.22.2
  [ok] Python packages installed

> Starting PostgreSQL
  [ok] PostgreSQL is ready on port 5432

> Applying database migrations
  [ok] Database schema is up to date

> Checking the analytical data
  [ok] Analytical layer already built (10 Parquet files)

> Starting the backend API
  [ok] API ready at http://127.0.0.1:8000

> Starting the frontend
  [ok] Frontend ready

  IPM is running.

    Open this in your browser:   http://localhost:3000
```

### Step 4 — Open it

Go to **http://localhost:3000** in your browser.

The top-right corner shows the live system status. If everything is working it
says **All systems operational**.

**What to try first**

1. On the opening screen, click one of the suggested questions — for example
   *"What deteriorated this period?"* — or type your own and press Enter.
2. IPM shows what it is doing, then returns an executive summary, headline
   metrics, key findings, the drivers behind them, and every chart and table
   underneath.
3. Press **Trace** on the answer. That opens the **Analytical Reasoning Map** —
   every step from your question to the figures, with the boundary between
   IPM's judgement and the deterministic engine drawn differently.
4. On the map, type a change into **Ask / Modify Trace** — *"Exclude Real
   Estate"*, *"Use borrower count instead of EAD"*, *"Add ECL Movement"*. IPM
   shows you exactly what would change before anything runs. Press
   **Apply & re-run** and it creates **Version 2**, leaving the original intact
   and switchable at the top of the page.
5. Change the look at any time with the **theme switcher in the top-right**:
   Executive Ivory, Midnight Boardroom, Graphite and Warm Sand. It applies
   instantly, is remembered, and never changes the layout.

**Does IPM need an AI key?** No. If no `ANTHROPIC_API_KEY` is set in `.env`,
IPM reads questions with its own built-in planner and says so under the question
box. Either way the *answers* are identical in kind: every figure is produced by
running real, certified IPM Engine analyses against the published data. Nothing
is pre-written and no number is invented. Adding a key changes only how freely
worded a question can be.

---

### Stopping IPM

Press **Ctrl + C** once in the terminal. That stops the interface and the
analytics. The database keeps running quietly in the background; to stop that
too:

```
docker compose down
```

Your data is kept. To erase the database entirely and start fresh, use
`docker compose down -v`.

---

### If something goes wrong

Every failure message names the fix. The most common ones:

| Message | What it means | What to do |
|---|---|---|
| `Docker is not installed or not running` | Docker Desktop is closed | Open Docker Desktop, wait for **Running**, try again. (If you already run your own PostgreSQL, `dev.sh` will use it instead of Docker.) |
| `No .env file found` | Step 2 was skipped | `cp .env.example .env` (Windows: `copy .env.example .env`) |
| `The Python packages are not installed` | Step 1 did not finish | Re-run `./scripts/setup.sh` |
| `PostgreSQL did not become ready` | The database failed to start | Run `docker compose logs db` to see why |
| `Cannot reach the IPM backend` in the browser | The backend stopped | Look in `logs/api-dev.log` |
| `port is already allocated` | Something else is using port 5432 | Change `POSTGRES_PORT=5433` in `.env` (and in `DATABASE_URL`) |

Two log files hold the detail: **`logs/api-dev.log`** and **`logs/web-dev.log`**.

---

## What each part does

| Part | What it is | Why IPM uses it |
|---|---|---|
| **PostgreSQL** | A database | The filing cabinet: users, projects, chats, analysis runs, traces, and the Engine Builder / Data Builder definitions. Everything the bank has *decided* or *recorded*. |
| **Parquet** | A file format for large tables | Stores data column by column, so totalling one column of millions of rows reads only that column. This is where the monthly credit data lives — **not** in PostgreSQL. |
| **DuckDB** | A query tool | Runs SQL directly against those Parquet files, with no server to install. Filtering and totalling happen inside DuckDB; only the summary comes back. |
| **FastAPI** | The backend | Exposes every capability over the web so the interface never reaches into the analytics directly. That boundary is what lets either side be replaced independently. |
| **Next.js / React** | The frontend | The user interface: an enterprise-grade application with four themes, the AI Cockpit and the interactive Analytical Reasoning Map.  |

---

## Everyday commands

| What you want | Command |
|---|---|
| Start everything | `./scripts/dev.sh` (Windows: `.\scripts\dev.ps1`) |
| Run every quality check | `./scripts/check.sh` |
| Rebuild the analytical data | `.venv/bin/python scripts/build_data_lake.py` |
| Update the database schema | `.venv/bin/python -m alembic upgrade head` |
| Start only the database | `docker compose up -d db` |
| Stop the database | `docker compose down` |
| Browse the database in a web page | `docker compose --profile tools up -d` then http://localhost:5050 |
| Read the API documentation | http://127.0.0.1:8000/docs while IPM is running |

---

**With Docker (nothing installed but Docker Desktop):**

| What you want | Command |
|---|---|
| Start everything | `docker compose up --build` |
| Start in the background | `docker compose up --build -d` |
| Watch what it is doing | `docker compose logs -f` |
| Stop it | `docker compose down` |
| Stop and erase the database | `docker compose down -v` |
| Rebuild from scratch | `docker compose build --no-cache` |
| Open a shell in the backend | `docker compose exec backend bash` |
| Browse the database | `docker compose --profile tools up -d` then http://localhost:5050 |

## Repository structure

```
backend/
  api/              FastAPI — the HTTP surface the frontend talks to
  data_access/      the Data Access Layer: governed names in, DataFrames out.
                    The ONLY place that knows about DuckDB.
  engine/           the deterministic IPM Engine: contracts, registry, functions
  trace/            the Trace graph — nodes, edges, content hashing
  orchestration/    the only place a language model is used (Phase 3)
  stress/           stress scenarios (Phase 2+)
  models/           PostgreSQL tables for the platform
  climate/          the Oman climate stressed-PD engine (validated to 1e-11)
  data_loader.py    ~70 proven credit-risk calculations (become engine functions)
  reporting/        PDF and Word writers

frontend/           Next.js + TypeScript + Tailwind + shadcn/ui + Recharts
  src/app/          one route per capability
  src/components/   ui/ (shadcn primitives), layout/, system/
  src/lib/          api client, themes, navigation

data/
  raw/              source files exactly as received — never modified
  curated/          mapped to governed field names, typed and validated
  analytics/        business-ready Parquet, read by DuckDB (generated)

metadata/           the governed data catalogue (generated)
alembic/            database migrations
tests/              engine, trace, data_access, api, and the legacy Dash suites
legacy/dash_app/    the original Dash application, preserved and still tested
docs/               product spec, architecture, demo scope
docker/             the Dockerfiles and the backend start-up script
scripts/            setup.sh, dev.sh, dev.ps1, check.sh, build_data_lake.py,
                    start-docker.ps1, stop-docker.ps1
```

### The import rule

```
frontend       → talks to backend only over HTTP
backend/api    → may use everything below
backend/engine → may use data_access;  never api, never an LLM, never duckdb
data_access    → may use nothing above it
```

The credit-risk maths must never become dependent on the screen it is shown on.
That one rule is what lets the interface be replaced, the API be extended, and
the storage move to a lakehouse — without touching a calculation.

---

## The data

The bundled portfolio is **synthetic**: 6,599 facility positions across ten
quarterly reporting periods from Q4 2023 to Q1 2026, with 53 attributes each,
plus 389 borrower financial records.

It is rich enough for genuine stage migration, DPD migration, rating transitions,
ECL attribution and deterioration ranking — it carries the prior period's rating
and utilisation, so movement is measured rather than estimated.

Every dataset carries a `synthetic` flag through the governed catalogue, and the
interface labels it wherever its figures appear.

---

## Quality gates

```bash
./scripts/check.sh
```

| Gate | Covers |
|---|---|
| `ruff` | Python linting |
| `pytest` | Data Access Layer, engine contracts, Trace graph, question scoping and period clarification, saved investigations and refresh, workflow and notifications, the data control plane, the metadata assistants, theme contrast, the API, and the preserved Dash suites including the climate golden master |
| `tsc --noEmit` | TypeScript type checking |
| `eslint` | Frontend linting |
| `next build` | Frontend production build |

CI runs the Python gates on every push (`.github/workflows/ci.yml`).

---

## The original Dash application

The previous Dash application is preserved, working and still under test, in
**`legacy/dash_app/`**. It is no longer the product front end — Next.js is — but
it contains proven analytical screens worth referring back to while the React
interface is built. Its seven test suites still run as part of `pytest`.

Its backend analytics were **not** moved to legacy: `backend/data_loader.py`,
`backend/climate/`, the RAROC engines and the report writers are all retained and
become the implementations behind registered engine functions in Phase 2.

---

## Current status

**Phase 5 — product quality: the answer, the workspace and the control plane.**

* **Ask IPM answers the question that was asked.** Each recognised intent names
  one primary analysis and at most a couple of supporting ones. "Which sectors
  deteriorated the most?" returns the sector attribution and nothing else — it
  no longer returns total exposure, the NPL ratio and the stage distribution
  alongside it.
* **IPM asks before it guesses.** An analysis that measures change between two
  periods will not run until the periods are settled. When the question does not
  say, IPM asks, with options built from the real published periods — a
  quarterly book is never offered "last 3 months". A point-in-time question
  ("what is our NPL ratio?") is answered, never interrogated.
* **Fact and interpretation are kept apart.** Every answer opens with one
  sentence whose figures were quoted unchanged from an engine result, and states
  IPM's reading of them separately, labelled as a reading. The reading describes
  where a movement sits; it does not claim what caused it.
* **The Analytical Reasoning Map** now records the whole chain: the question, how
  IPM read it, the plan, the governed data domain, the dataset with its family,
  version, period and origin, the variables with their definitions, the filters
  with row counts, the transformations, the aggregations, the certified function
  and its version, the result, IPM's reading of it, and the visual. The two
  interpretive moments — reading the question, reading the result — are named
  separately, because they answer to different things.
* **Investigations you keep.** A saved investigation has a name, an owner and
  versions, and can be refreshed: the same plan runs again against whatever is
  published now. No figure is carried forward — a refresh that produces
  identical numbers says so, because "identical" and "copied" mean very
  different things to a reviewer.
* **Review, comments and notifications.** Send an investigation to a colleague;
  the decision and its comment become an append-only history. The Workflow Inbox
  separates what you have to do from what you are waiting on.
* **Data Builder is a control plane.** It states, purpose by purpose, which
  dataset is answering IPM right now and whether that dataset is your data or the
  bundled demonstration book. Archiving the only authoritative source for a
  purpose is refused and names the analyses that would stop working. Replacing
  demonstration data with your own is a governed act: the schemas are compared
  field by field first, and on handover every certified analysis follows with no
  code change.
* **Two assistants that only read metadata.** One answers questions about the
  data dictionary, one about the analysis library. Neither can see portfolio
  data, state a figure, or change anything; a portfolio question is refused and
  sent to Ask IPM, where it produces a Trace.
* **Eight themes** — four light, four dark — switchable in one click. Every
  palette's contrast is asserted by a test, not judged by eye.

Phases 1–4 built what this rests on: the Data Access Layer and Parquet lake, the
eleven registered analyses, Data Builder, Engine Builder, the Trace model, the
interactive map and controlled Trace modification. See
[docs/DEMO_SCOPE.md](docs/DEMO_SCOPE.md) for the sequence and what remains
(Documents authoring and production authentication).

Every screen in the application states its own honest status. IPM does not
present unbuilt functionality as if it were finished, and never shows invented
figures.
