# CreditProbe — Architecture

> **The analytical runtime supersedes parts of §5.** CreditProbe no longer
> answers only from a fixed list of registered analyses: a question with no
> prebuilt answer is composed as an Analytical IR plan, validated against the
> governed catalogue, compiled to parameterised SQL and executed. The layers,
> the data architecture and the governance boundary below are unchanged —
> what changed is that the planner's output is now a *plan* rather than a
> *choice*. See [ANALYTICAL_RUNTIME.md](ANALYTICAL_RUNTIME.md).

Companion to `PRODUCT_SPEC.md`. This document covers **how** CreditProbe is built: the layers,
the data architecture, the repository structure, and the reasoning behind each choice.

Status: **target architecture + migration path.** Section 2 records what exists today
and where it conflicts with the target.

---

## 1. Architectural principles

1. **The engine is framework-free.** Analytical code imports no web framework, no UI
   library, no HTTP. It can be run from a test, a notebook, a script, an API or a UI.
2. **The engine does not know where data physically lives.** It asks the Data Access
   Layer for a governed dataset; the DAL decides whether that is DuckDB over Parquet,
   PostgreSQL, or a bank lakehouse.
3. **Governed metadata is data, not code.** Datasets, fields, definitions, functions
   and their versions live in PostgreSQL and are editable through Data Builder and
   Engine Builder — not by editing Python.
4. **State is explicit.** No module-level mutable data. Every call carries its dataset
   version, period and filters.
5. **The plan is a document.** The LLM produces a validated structure; the executor
   runs it. Nothing else crosses that boundary.
6. **Trace is a byproduct of execution**, emitted by the executor, never authored.
7. **Nothing is deleted, only versioned.** Datasets, functions, traces, scenarios.

---

## 2. What exists today, and how it conflicts

### 2.1 What exists (and is worth keeping)

| Asset | Assessment |
|---|---|
| `backend/data_loader.py` — ~70 pure aggregation functions | **High value.** Real, working credit-risk maths over the real dataset. Becomes the implementation body behind registered engine functions. |
| `backend/climate/` — Oman Climate Stressed-PD model v5.1 | **Exceptional.** Deterministic engine, 24 quality checks, immutable versioned runs, and a golden-master test suite matching the source workbook to 1e-11. This is exactly the standard the whole engine layer should meet. Becomes a certified stress capability. |
| `backend/cockpit_data.py` — health index, sector matrix, benchmarks, obligor screens | Solid derived analytics. Becomes Monitor/Detect functions. |
| `backend/raroc_data.py`, `raroc2_data.py` | Working RAROC / post-deal RAROC engines. Keep as certified functions. |
| `backend/reporting/` — charts, content, writers (PDF/Word) | Directly reusable as the export path for Documents. |
| `backend/stress_lab.py` — named scenario presets | The right instinct (named parameterised scenarios, not free text). Becomes the Scenario object. |
| PostgreSQL + SQLAlchemy + Alembic | Correct database already in place, with migrations. |
| Parquet codec, versioned dataset lifecycle, one-active-version constraint | Good governance instincts already implemented. |
| Flask-Login + Argon2id auth, every page and callback behind login | Correct baseline; needs extending to teams/roles/permissions. |
| Tool-calling AI grounded in `data_loader` (not raw data) | **The right architectural instinct** — the model already calls functions rather than seeing records. It is simply too small: 7 hardcoded tools, no planner, no trace. |
| `tests/` — 12 suites incl. a golden master | Real test discipline. Keep and extend. |
| CI (ruff + pytest on every push) | Keep. |
| `Portfolio_Monitoring_Dataset.xlsx` — 10 quarterly snapshots (Q4 2023 → Q1 2026), 6,599 facility rows, 53 columns | **Excellent demo data.** Rich enough for genuine stage migration, rating transitions, DPD migration, ECL attribution and deterioration ranking. |

### 2.2 Conflicts with the target architecture

| # | Conflict | Why it matters | Resolution |
|---|---|---|---|
| 1 | `data_loader` holds the portfolio in **module-level global DataFrames** and functions read those globals | Blocks per-request dataset selection, multi-tenancy, concurrent users on different periods, and any clean Data Access Layer. It is the single biggest structural blocker. | Introduce an explicit `AnalysisContext` (dataset version, period, filters, source) passed into every function. Wrap existing functions during migration so nothing breaks. |
| 2 | **No DuckDB.** Parquet exists, but as binary blobs stored *inside* PostgreSQL, loaded wholesale into memory | Exactly inverted from the target. Fine at 7,000 rows; impossible at bank scale (millions of facilities × monthly history). | Write Parquet as *files* in a layered lake; query with DuckDB, pushing filters and aggregation down. Keep the PostgreSQL dataset-version registry as the governance record. |
| 3 | Analytical contracts are **implicit** — a Python signature is the only specification | Engine Builder needs declared inputs, parameters, outputs, validation rules, versions, owners and certification. A signature carries none of it. | Registry with declarative metadata; the Python function becomes the bound implementation. |
| 4 | The **data dictionary is a spreadsheet tab** (`Field Dictionary`), not a governed catalogue | Definitions cannot be queried, versioned, governed or shown in Explain. | Load it into the Data Builder catalogue in PostgreSQL as the single source of field meaning. |
| 5 | PostgreSQL schema has **4 tables** (users, dataset_versions, dataset_sheets, ai_usage_log) | The platform needs ~30 entities: teams, roles, permissions, projects, chats, investigations, blueprints, lenses, engine definitions/versions/tests, data catalogue, scenarios, analysis runs, trace graphs/nodes/edges/versions/modifications, workflow, comments, documents. | New Alembic migrations, additive. Existing tables are kept as-is. |
| 6 | The UI is **one 4,557-line `app.py`** with 82 callbacks and `if pathname == ...` routing | Will not scale to 16 capabilities, and no one can safely change it. | Decompose into one view module per capability behind a route registry. |
| 7 | CSS tokens are **literal colours** (`--navy-900`, `--teal`) not semantic roles | Four themes are impossible while the interface names paint instead of purpose. | Rename to role tokens (`--surface`, `--text-primary`, `--accent`, `--negative`, `--chart-N`); themes become value sets. Mechanical but must happen before the themes. |
| 8 | AI layer: **three near-duplicate chat backends** each re-implementing the same 7 tools; no planner, no plan schema, no trace, no streaming | The AI is a Q&A helper, not an investigation engine. Duplication triples the cost of every change. | One provider abstraction; one planner; one executor; one interpreter. |
| 9 | A model is **branded "GLM 5.2" in the UI while actually calling Claude Haiku** | This is a control failure, not a cosmetic issue. A bank's model-risk function must know which model produced an output; a mislabelled model would fail model-governance review and is precisely the kind of finding that discredits a demo in front of a CRO. | Display the true provider and model everywhere, and record it on every analysis run. |
| 10 | Roles are a single `admin \| analyst` string | No teams, no object-level or data-level permissions. | Users / Teams / Roles / Permissions model with capability, object and data scoping. |
| 11 | **Dash** is weak for token-streaming chat and for interactive graph editing | The AI Cockpit and Trace are the two most important surfaces in the product, and they are the two Dash handles worst. | See §7. Keep Dash for the near-term demo; put every capability behind an HTTP API so the UI can be replaced without touching the engine. |
| 12 | Large source workbooks (2.3 MB) committed at the **repository root** | Source data mixed with source code; no raw/curated/analytical separation. | Move to `data/raw/`. |
| 13 | `requires-python = ">=3.14"` | Narrow; this build environment runs 3.11. | Relax to `>=3.11` unless a 3.14-only feature is genuinely used. |

**Nothing in §2.1 is deleted.** The migration wraps and re-homes existing code; it does
not rewrite the working maths.

---

## 3. Layered architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│  PRESENTATION                                                        │
│  AI Cockpit · Monitor · Detect · Investigate · Stress · Trace ·       │
│  Projects · Blueprints · Lenses · Documents · Engine Builder ·        │
│  Data Builder · Users · Workflow · Settings                          │
│  Design tokens · 4 themes                                            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  HTTP / JSON  (typed contracts)
┌───────────────────────────────┴──────────────────────────────────────┐
│  APPLICATION SERVICES        (stateful, governed, permissioned)      │
│  projects · chats · investigations · blueprints · lenses ·           │
│  scenarios · workflow · users/teams/roles · comments · documents     │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────┴──────────────────────────────────────┐
│  ORCHESTRATION               (the ONLY place the LLM is used)        │
│                                                                      │
│   question ─▶ PLANNER ─▶ AnalysisPlan ─▶ VALIDATOR ─▶ EXECUTOR       │
│                (LLM)      (structured)    (strict)     (deterministic)│
│                                                          │            │
│   narrative ◀─ INTERPRETER ◀────── structured results ◀──┘            │
│                  (LLM)                                                │
│                                        └──▶ TRACE RECORDER            │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  only registered functions, validated params
┌───────────────────────────────┴──────────────────────────────────────┐
│  CreditProbe ENGINE                  (deterministic · versioned · tested)    │
│  registry · contracts · functions · calculations · stress            │
│  NO LLM.  NO framework.  NO knowledge of physical storage.           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │  governed dataset + field names
┌───────────────────────────────┴──────────────────────────────────────┐
│  DATA ACCESS LAYER (DAL)                                             │
│  one interface · catalogue-driven name resolution · pushdown         │
└──────┬──────────────────────┬────────────────────────┬───────────────┘
       │                      │                        │
┌──────┴──────┐      ┌────────┴────────┐      ┌────────┴────────────────┐
│  DuckDB     │      │  PostgreSQL     │      │  Future lakehouse       │
│  over       │      │  application &  │      │  Databricks / Delta /   │
│  Parquet    │      │  governance     │      │  Unity Catalog,         │
│  (analytics)│      │  (metadata)     │      │  Snowflake, or          │
│             │      │                 │      │  bank-approved platform │
└─────────────┘      └─────────────────┘      └─────────────────────────┘
```

### Why the DAL matters

The CreditProbe Engine never writes `duckdb.query(...)`. It writes:

```python
frame = dal.fetch(
    dataset="portfolio_facility",
    period="2026-Q1",
    fields=["ead", "ifrs9_stage", "sector"],
    filters={"segment": "Corporate"},
)
```

The DAL resolves `portfolio_facility` and `ead` through the Data Builder catalogue,
translates the request into whatever the configured backend speaks, and pushes filters
and aggregation **down** to the source so only summarised data comes back.

Plain English: **when the bank moves its data to Databricks or Snowflake, we write one
new adapter. Not a single line of credit-risk maths changes.** That is the entire
purpose of the layer, and it is the difference between a demo and a platform.

---

## 4. Data architecture

### 4.1 Two databases, two jobs

| | PostgreSQL | Parquet + DuckDB |
|---|---|---|
| **Holds** | Application & governance metadata | Large analytical banking data |
| **Shape** | Many small related records | Few very wide, very tall tables |
| **Access** | Transactional reads/writes | Columnar scan and aggregate |
| **Examples** | Users, projects, chats, engine definitions, data dictionary, traces, workflow | Monthly facility snapshots, ECL detail, rating history |
| **Grows with** | Users and activity | Portfolio size × months of history |

PostgreSQL holds: users, teams, roles, permissions, projects, chats, investigations,
blueprints, lens definitions, engine definitions, engine versions, engine tests, data
builder metadata, datasets, data dictionary, mappings, quality rules, workflow,
comments, stress scenarios, analysis runs, trace graphs, trace versions, document
metadata, and audit.

Plain English: PostgreSQL is the **filing cabinet** — everything the bank has decided,
configured or recorded. Parquet + DuckDB is the **warehouse floor** — the raw tonnage
of monthly loan data.

**Large monthly banking data is not put into PostgreSQL.**

### 4.2 The three analytical layers

```
data/
  raw/          ORIGINAL FILES AS RECEIVED — never modified
                Portfolio_Monitoring_Dataset.xlsx, Macro_GCC_Compact.xlsx,
                Oman_Climate_StressedPD_v5 1.xlsx, RAROC samples

  curated/      MAPPED AND VALIDATED CreditProbe DATA
                Source columns mapped to governed field names, types enforced,
                quality rules applied, rejects quarantined with reasons.
                Parquet, partitioned by reporting period.

  analytical/   BUSINESS-READY
                Datasets and views the engine functions consume directly.
                Pre-joined where it helps, partitioned by period, typed and
                documented in the Data Dictionary.
                Parquet, queried by DuckDB.
```

Each hop is a recorded lineage step: which raw file, which mapping version, which
quality rules, which transform. Data Builder's Lineage view reads that record.

**Why raw is never modified:** when a number is challenged nine months later, the only
way to answer is to re-derive it from exactly what the source system sent. An
overwritten raw file makes that impossible.

### 4.2b Governed purposes, and how demo data is replaced

An engine function does not name a file, and it does not really name a dataset. It
names a **governed purpose** — `credit_facility_position`, `borrower_financials` — and
`backend/data_access/authority.py` resolves that purpose to whichever published dataset
is marked **authoritative** for it.

Resolution has exactly three outcomes, and there is no fourth branch where something
plausible is substituted:

| Situation | Outcome |
|---|---|
| A client dataset is authoritative | Use it |
| Only CreditProbe's bundled demonstration data is authoritative | Use it, and **say** it is demo data |
| Neither | **Refuse**, and say what is missing |

Client data always outranks demonstration data for the same purpose. When a steward
marks a client dataset authoritative in Data Builder, every certified analysis follows
immediately — no analysis code changes — and the redirect is recorded on the Trace's
DATASET node with its reason. That is why "CreditProbe is quietly still reading the demo book"
is not a state the product can be in without saying so.

Each dataset also carries an **origin** (`demo` / `client` / `supplementary`) and a
**family**. The family is what makes replacing one dataset with another a governed act
rather than an unrelated table appearing: `backend/services/governance.py` compares the
two schemas field by field and refuses a replacement that drops a field the outgoing
dataset supplies, unless the caller acknowledges exactly what is lost.

**Dependency checks.** Before a dataset is archived, CreditProbe lists what reads it — the
purposes it is the only authoritative source for, the certified analyses that would
stop being answerable, the relationships joining to it, and the saved investigations
produced from it. An archive with blocking dependants is refused until acknowledged.

**Archived domains leave resolution.** A whole data **domain** can be archived, and an
archived domain's datasets stop being eligible above. An analysis quietly going on
reading a book the data office has withdrawn — and somebody finding out nine months
later — is exactly the audit finding this product exists to prevent, so resolution
refuses and names the archived domain rather than reporting that nothing is
authoritative, which would send a steward hunting for a dataset that is sitting right
there.

Archiving is **not** deletion. The rows stay on disk, the Data Builder viewer still
serves them to anybody authorised to look, and restoring the domain puts it straight
back into resolution. Deleting a domain that still holds datasets is refused outright:
remap, replace or archive them first.

Which domains are archived lives in PostgreSQL, and `data_access` may not read it — it
sits at the bottom of the import order and stays there. So the application registers a
provider at start-up (`backend/services/domain_status.py`) and the authority resolver
asks it. The answer is cached, because resolution happens on every step of every
analysis; the cache is cleared the moment a domain's status changes, so the decision
takes effect immediately rather than at the next restart. With nothing registered — a
script, a test, a run with no database — nothing is archived, and a failed governance
read **fails open** for the same reason: the archive is a curation decision, not a
security boundary, and treating an unreachable database as "everything is retired"
would take the whole product down.

### 4.3 Dataset versioning

Today's model — one `DatasetVersion` per uploaded workbook, exactly one `active` at a
time, with a validation report — is **correct and is kept**. The change is where the
bytes live: Parquet files in `data/`, with PostgreSQL holding the version record,
validation report, lineage and the pointer.

Every analysis run records the dataset version it used. Re-running a Trace against the
same version reproduces the number exactly; running it against a newer version and
getting a different answer is itself a finding.

---

## 5. The analytical path, end to end

```
1  User asks:  "Why has Stage 2 increased?"
                                │
2  PLANNER (LLM)  ──────────────┤  Reads: the Engine Registry (what analyses exist),
                                │  the Data Dictionary (what fields mean), the current
                                │  context (project, period, active filters).
                                │  Writes: an AnalysisPlan — a structured document.
                                ▼
3  AnalysisPlan   { steps: [
                      { fn: "stage_distribution",  v: "1.2.0", params: {...} },
                      { fn: "stage_migration",     v: "1.1.0", params: {...} },
                      { fn: "stage_migration_drivers", v: "1.0.0", params: {...} } ],
                    dataset_version: 7, period: "2026-Q1", compare: "2025-Q4" }
                                │
4  VALIDATOR      ──────────────┤  Every fn exists? Every version exists and is not
                                │  deprecated? Every parameter satisfies its contract?
                                │  User permitted for these datasets and fields?
                                │  FAIL → rejected and reported. Never silently fixed.
                                ▼
5  EXECUTOR       ──────────────┤  Walks the plan. For each step: resolve datasets via
   (deterministic)              │  the DAL, apply filters, call the registered engine
                                │  function, validate the output against its contract.
                                │  Emits a TraceNode per step as it goes.
                                ▼
6  CreditProbe ENGINE     ──────────────┤  Pure functions. Same inputs → same outputs, always.
                                ▼
7  Structured results  { values, units, precision, row counts, warnings }
                                │
8  INTERPRETER (LLM) ───────────┤  Receives ONLY the structured results — never raw
                                │  records. Writes narrative, quoting engine figures.
                                │  Proposes follow-up questions.
                                ▼
9  RESULT + TRACE ──────────────▶  Charts · tables · narrative, with a Trace button
                                   that opens the graph recorded at step 5.
```

Steps 2 and 8 are the only places an LLM appears. Step 4 is the wall between them and
the numbers.

### Trace modification path

```
"Use EAD rather than borrower count"
        │
        ▼
INTERPRET  →  a structured ChangeSet against the existing plan
        │      (which node, which parameter, what new value)
        ▼
IMPACT     →  re-hash affected nodes; walk downstream; mark what must re-run
        │
        ▼
PREVIEW    →  show the user: nodes added / changed / removed, before applying
        │
        ▼
BRANCH     →  new TraceVersion; the original graph is never mutated
        │
        ▼
RE-EXECUTE →  only nodes whose content hash changed; the rest reuse recorded results
        │
        ▼
NEW RESULT →  with a version selector: v1 · v2 · compare
```

---

## 6. Recommended repository structure

A new `ipm/` namespace is introduced. The existing `backend/`, `frontend/` and
`app.py` **keep running throughout**; modules move into the new structure one at a
time, each move covered by tests. Nothing is deleted.

```
IPM_V2/
├── docs/
│   ├── PRODUCT_SPEC.md          what the product is
│   ├── ARCHITECTURE.md          this file
│   ├── DEMO_SCOPE.md            what is being built, in what order
│   └── deploy.md                existing operations runbook
│
├── ipm/
│   ├── core/                    ← framework-free. No Dash, no Flask, no HTTP.
│   │   ├── context.py           AnalysisContext: dataset version, period, filters, user
│   │   ├── dal/
│   │   │   ├── protocol.py      the interface every data source must satisfy
│   │   │   ├── duckdb_source.py Parquet via DuckDB, with pushdown
│   │   │   ├── postgres_source.py
│   │   │   └── catalog.py       business name → physical location, from Data Builder
│   │   ├── engine/
│   │   │   ├── registry.py      registered functions, versions, certification
│   │   │   ├── contracts.py     input/output schemas and validation
│   │   │   └── functions/       one module per analytical function
│   │   │       ├── portfolio_summary.py
│   │   │       ├── stage_distribution.py
│   │   │       ├── stage_migration.py
│   │   │       ├── dpd_migration.py
│   │   │       ├── rating_transition.py
│   │   │       ├── sector_concentration.py
│   │   │       ├── ecl_movement.py
│   │   │       ├── top_deteriorating.py
│   │   │       ├── portfolio_trend.py
│   │   │       └── stress_basic.py
│   │   ├── plan/
│   │   │   ├── schema.py        the AnalysisPlan contract
│   │   │   ├── validator.py     rejects anything not in the registry
│   │   │   └── executor.py      walks the plan; emits trace nodes
│   │   ├── trace/
│   │   │   ├── model.py         TraceGraph / Node / Edge / Version / Modification
│   │   │   ├── recorder.py      execution → graph
│   │   │   ├── hashing.py       content hashes for selective re-execution
│   │   │   └── modify.py        controlled edits → new version
│   │   └── stress/              scenario definitions and shock application
│   │
│   ├── ai/                      ← LLM orchestration ONLY. Never arithmetic.
│   │   ├── provider.py          one abstraction over model providers
│   │   ├── planner.py           question → AnalysisPlan
│   │   ├── interpreter.py       structured results → narrative
│   │   ├── modifier.py          "Ask / Modify Trace" → ChangeSet
│   │   └── prompts/
│   │
│   ├── platform/                ← application services (stateful, permissioned)
│   │   ├── db/
│   │   │   ├── models/          one module per entity group
│   │   │   └── migrations/      Alembic
│   │   ├── services/            projects, chats, investigations, blueprints,
│   │   │                        lenses, scenarios, workflow, users, teams,
│   │   │                        permissions, comments, documents
│   │   └── api/                 the HTTP surface every UI consumes
│   │
│   └── ui/
│       ├── theme/
│       │   ├── tokens.py        the semantic token contract
│       │   └── themes/          executive_light · midnight · graphite · warm_institutional
│       ├── components/          shared, themed primitives
│       ├── views/               one module per capability
│       │   ├── cockpit.py  monitor.py  detect.py  investigate.py
│       │   ├── stress.py   trace.py    projects.py  blueprints.py
│       │   ├── lenses.py   documents.py engine_builder.py data_builder.py
│       │   └── users.py    workflow.py  settings.py
│       └── routes.py            route registry — replaces the if/else chain
│
├── data/
│   ├── raw/                     source files as received (workbooks move here)
│   ├── curated/                 mapped + validated Parquet
│   └── analytical/              business-ready Parquet, partitioned by period
│
├── backend/   frontend/   app.py   assets/     ← existing app, kept running
├── scripts/                     seed, migrate, build the lake, manage users
├── tests/
│   ├── engine/                  one suite per function, with golden values
│   ├── trace/                   graph construction, hashing, modification
│   ├── plan/                    validator rejection cases
│   └── ...existing suites
├── alembic/  alembic.ini  pyproject.toml  requirements.txt
└── docker-compose.yml  Dockerfile  .env.example
```

### Why `core/` imports nothing framework-shaped

An import rule, enforced in CI:

```
ipm.ui        →  may import  ipm.platform, ipm.ai, ipm.core
ipm.platform  →  may import  ipm.ai, ipm.core
ipm.ai        →  may import  ipm.core
ipm.core      →  may import  NOTHING above it
```

Plain English: **the credit-risk maths cannot accidentally become dependent on the
screen it happens to be shown on.** That one rule is what lets the UI be replaced, the
API be added, and the storage be swapped, without touching the calculations.

---

## 7. The user-interface technology decision

**Recommendation: keep Dash for the immediate demo, and put every capability behind an
HTTP API from day one so the front end can be replaced without touching the engine.**

The honest position:

**Where Dash is fine.** Server-rendered analytical screens, tables, Plotly charts,
filter panels, forms, catalogue browsers. Engine Builder, Data Builder, Monitor,
Lenses, Users and Workflow are all comfortably within what Dash does well. The
existing app already carries 2,279 lines of hand-written CSS, so a token refactor and
four themes are achievable without a rewrite.

**Where Dash fights back.** Two surfaces — and they are the two that matter most:

1. **AI Cockpit.** Dash's callback model does not naturally stream. An AI-native
   product where the answer arrives as a single block after 20 seconds feels
   fundamentally different from one where reasoning and results appear progressively.
2. **Trace.** An interactive, pannable, zoomable, clickable, editable graph is a
   React-shaped problem. `dash-cytoscape` gets a usable clickable DAG; it does not get
   the polish of a purpose-built canvas.

**Why not rewrite the front end now.** A React/Next.js front end is the right long-term
answer, but it is weeks of work, and doing it *first* would mean spending that time
before a single new analytical capability exists. The engine, the DAL, the plan and
Trace are what make CreditProbe a product; the front end is how it is shown.

**So:** build the API-first spine now, use Dash to demonstrate it, and treat the React
front end as a scheduled, planned replacement — not an emergency. Because the UI talks
to the platform over HTTP rather than calling Python functions directly, that
replacement is a project with a clear boundary rather than a rewrite of everything.

---

## 8. Theming implementation

```
tokens (semantic role names)          themes (value sets)
─────────────────────────────         ─────────────────────────────────
--bg-canvas                           Executive Light   · paper, high contrast
--surface                             Midnight          · deep navy-black
--surface-raised                      Graphite          · neutral low-chroma dark
--surface-sunken                      Warm Institutional· warm off-white, ink
--border  --border-strong
--text-primary  --text-secondary
--text-muted    --text-inverse
--accent  --accent-hover  --accent-muted
--positive  --warning  --negative  --info
--chart-1 … --chart-8
--chart-sequential-*  --chart-diverging-*
```

Rules:

- Component CSS references **only** role tokens. A literal hex in a component is a bug.
- Every theme defines **every** token — no fallbacks, no gaps.
- Layout, typography scale, spacing scale, radii and motion are **theme-invariant**.
- Chart palettes are defined per theme and validated for contrast against that theme's
  surfaces and for colour-vision accessibility. Positive/negative must stay
  distinguishable without relying on hue alone.
- Theme is applied by a single attribute on the root element and stored per user.

The current `assets/style.css` tokens are literal colours (`--navy-900`, `--teal`).
Renaming them to roles is the prerequisite for all four themes, and must happen before
theme work starts rather than alongside it.

---

## 9. Security, governance and controls

| Control | Implementation |
|---|---|
| Authentication | Existing Flask-Login + Argon2id, retained |
| Authorisation | Capability-level, object-level and data-level checks in the service layer — never in the UI alone |
| Data sensitivity | Field-level classification in the Data Dictionary; the DAL refuses fields the caller may not read |
| Prompt injection | Tool and engine output is treated as data, never as instruction — the existing defence, extended to the planner |
| Model transparency | The true provider and model are displayed to the user and recorded on every analysis run |
| Reproducibility | Every run records dataset version, function versions, parameters and content hashes |
| Immutability | Traces, certified engine versions, and approved scenarios are append-only |
| Audit | Who ran what, when, against which data, with which result — including rejected plans |
| Synthetic-data labelling | Datasets carry a flag; the UI surfaces it wherever their figures appear |

---

## 10. Testing strategy

| Layer | Approach |
|---|---|
| Engine functions | Golden values per function, computed independently and asserted exactly. Plus property tests: zero shock returns baseline; scale invariance; distributions sum to the total; a transition matrix's rows sum to 1. |
| Plan validator | Rejection cases are the point: unknown function, deprecated version, missing parameter, out-of-range value, unpermitted dataset. Each must fail loudly. |
| Executor & Trace | Every executed step produces exactly one node; edges match declared dependencies; hashes are stable across runs and change when and only when inputs change. |
| Trace modification | For each supported modification: correct nodes marked affected, correct nodes re-executed, unaffected results reused, original version unchanged. |
| DAL | The same query against DuckDB and against in-memory pandas returns identical results — this is what proves the abstraction holds. |
| Climate engine | The existing golden master stays, unchanged, at 1e-11. |
| Question scoping | One PRIMARY step per plan, and it is the one that answers the question. A narrow question returns one analysis, not a briefing. |
| Period clarification | A two-period analysis with no governed default and no period in the question RETURNS A QUESTION rather than an answer; a point-in-time question is never interrogated; every option offered resolves to two real published periods. |
| Fact vs interpretation | Every answer carries a `direct_answer` whose figures came from an engine result, and interpretation stated separately. The interpretation may not assert causation. |
| Saved investigations | A refresh re-executes rather than reloading; identical figures are reported as recalculated, not copied; a metric present on only one side is not reported as a movement. |
| Workflow | Every permitted transition is taken and every forbidden one is refused with the list of what is allowed; the event history is append-only; the reviewer and the requester are each notified at the right moment. |
| Data control plane | Archiving the only authoritative source for a purpose is refused and names the analyses that would break; an incompatible replacement is refused; a steward's client-data marking survives a re-sync of the bundled catalogue. |
| Metadata assistants | They answer from governed metadata, refuse a portfolio question and send it to Ask CreditProbe, and report an undefined field as undefined rather than guessing. |
| UI | Route registry completeness; every theme defines every token; no literal colours in component CSS. |
| Themes | Per theme, on that theme's own surfaces: body text ≥ 7:1, secondary ≥ 4.5:1, every status colour legible on the surface AND on its own tint, every chart slot ≥ 2.6:1 on the surface, and adjacent chart slots ≥ 18 ΔE apart in CIELAB. |
