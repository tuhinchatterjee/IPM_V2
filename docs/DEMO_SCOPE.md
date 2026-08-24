# CreditProbe — Demo Scope & Implementation Sequence

Companion to `PRODUCT_SPEC.md` (what the product is) and `ARCHITECTURE.md` (how it is
built). This document is about **what gets built, in what order, and what fits in the
time available.**

> **Status note.** This was written before Phase 1 as a planning document, and the
> sequence below is the plan that was followed. It is kept as the record of that
> reasoning. For what actually exists now, read the "Current status" section of the
> README; §6 below is a list of decisions that have all since been taken.

---

## 1. An honest statement about scope

The target is a polished demo covering: AI Cockpit, Projects, Investigations, Lenses,
Stress Testing, Blueprints, Engine Builder, Data Builder, Trace, Documents,
Users & Teams, Workflow, Settings/Administration — **plus** real analytical
calculations on real credit data, **plus** premium themes (four at the time of
writing; eight now), **plus** an interactive editable Trace graph.

That is a genuine platform. Building all of it to a standard that survives a CRO's
attention is **not one day of work** — it is several weeks. Anyone who says otherwise
will deliver sixteen empty screens, and empty screens are worse than eight excellent
ones: the moment a senior banker clicks the third dead button, the whole demo loses
credibility, including the parts that were real.

**So the plan below is built on a deliberate trade:** go deep on the things that make
CreditProbe different, and be honest and tidy about the things that are not built yet.

The recommendation is to build in three tiers.

| Tier | Meaning | What the audience sees |
|---|---|---|
| **A — Real** | Fully working, real data, real maths, tested | Genuine capability |
| **B — Real, narrow** | Working on a curated path; the demo path is real, breadth is limited | Genuine capability, clearly scoped |
| **C — Designed shell** | Beautifully designed, correctly structured, populated with real metadata, but not yet interactive | A credible product surface, honestly labelled |

Every Tier C screen is built against the **real** schema and shows **real** governed
metadata. None is a picture. Each carries a discreet, dignified status marker so no
one is misled — which, in front of a Chief Data Officer, is a mark of seriousness, not
weakness.

---

## 2. What was inspected

| | |
|---|---|
| Application | Dash (Python), single `app.py` — 4,557 lines, 82 callbacks, path-based routing |
| Backend | `backend/` — ~70 aggregation functions, climate stressed-PD engine, RAROC engines, reporting, stress presets, AI chat |
| Database | PostgreSQL via SQLAlchemy + Alembic — 4 tables |
| Analytical storage | Parquet, stored as blobs *inside* PostgreSQL; loaded into module-level pandas globals |
| AI | 3 chat backends, 7 hardcoded read-only tools, grounded in `data_loader` |
| Styling | 2,279 lines of hand-written CSS; one light theme; literal-colour tokens |
| Tests | 12 suites, including a 1e-11 golden master for the climate engine |
| CI | GitHub Actions — ruff + pytest on every push |
| Demo data | `Portfolio_Monitoring_Dataset.xlsx` — 10 quarterly snapshots (Q4 2023 → Q1 2026), 6,599 facility rows in total, **53 columns**, plus 389 borrower supplementary rows and a field dictionary |
| Absent | DuckDB, Trace, plans, Engine Builder, Data Builder, projects, blueprints, lenses, workflow, teams, documents, multi-theme |

### The demo data is good

53 columns per facility across 10 quarterly periods is genuinely rich. It carries snapshot date,
customer and account IDs, obligor group, segment, sector, region, product, limit,
exposure, undrawn, CCF, CCF-adjusted EAD, utilisation and prior utilisation,
collateral, internal grade, risk rating **and prior risk rating**, rating bucket,
IFRS 9 stage, DPD, 12-month and lifetime PD, LGD, model ECL, macro overlay, total ECL,
coverage, EIR, RAROC, AI risk score, severity, trigger, reason code, recommended
action, trend, SICR trigger, DSCR, covenant headroom, downgrade probability, news
sentiment, rollover count, watchlist, NPL and appetite-breach flags.

That means all ten demo engine functions can be computed **for real** — stage
migration, DPD migration and rating transitions all have the prior-period fields they
need. No mocked numbers anywhere in the analytical path.

---

## 3. Implementation sequence

Phases are ordered by dependency. Each ends in a working, committed, tested state.

### Phase 0 — Architecture baseline · **COMPLETE**
Repository inspected; `PRODUCT_SPEC.md`, `ARCHITECTURE.md`, `DEMO_SCOPE.md` written.
No code changed.

---

### Phase 1 — Foundations (invisible, and the most important phase)
*Nothing new appears on screen. Everything after this depends on it.*

1. Create the `ipm/` namespace and the import rule (`core` imports nothing above it),
   enforced in CI.
2. Move source workbooks to `data/raw/`.
3. Build the analytical lake: `raw → curated → analytical`, Parquet partitioned by
   reporting period, with the mapping and quality steps recorded as lineage.
4. Build the Data Access Layer: the source interface, the DuckDB/Parquet adapter, and
   catalogue-driven name resolution.
5. Introduce `AnalysisContext` — dataset version, period, filters, user — so no
   function ever reads a global again.
6. Extend the PostgreSQL schema (additive Alembic migrations) for the platform
   entities: teams, roles, permissions, projects, chats, investigations, blueprints,
   lenses, engine definitions/versions/tests, data catalogue, scenarios, analysis runs,
   trace graphs/nodes/edges/versions/modifications, workflow, comments, documents.
7. Load the 69-row Field Dictionary into the Data Builder catalogue as governed
   metadata.
8. Refactor CSS tokens from literal colours to semantic roles.

**Done when:** an engine function can be called with an explicit context, reads Parquet
through DuckDB via the DAL, and the existing Dash app still runs unchanged.

---

### Phase 2 — The Engine and its registry
1. Registry with declarative metadata, versioning and certification status.
2. Contract validation on inputs and outputs.
3. The ten demo functions, each built on the existing `data_loader` maths where it
   already exists, each with declared metadata and its own test suite:
   Portfolio Summary · Stage Distribution · Stage Migration · DPD Migration ·
   Rating Transition Matrix · Sector Concentration · ECL Movement ·
   Top Deteriorating Borrowers · Portfolio Trend · Basic Stress Scenario.
4. All ten marked **CreditProbe Certified** with passing tests and recorded owners.

**Done when:** every function returns a typed, unit-carrying result from real data,
with golden-value tests passing, callable with no UI present.

---

### Phase 3 — Plan · Execute · Trace
1. The `AnalysisPlan` schema.
2. The planner: question → plan, using the registry and the data dictionary.
3. The validator: strict rejection of anything unregistered or non-conforming.
4. The executor: walks the plan, calls the engine, validates outputs.
5. The trace recorder: a node per step, with content hashing.
6. The interpreter: structured results → narrative, quoting engine figures only.

**Done when:** "Why has Stage 2 increased?" produces a real multi-step answer from real
data, with a complete trace graph stored in PostgreSQL — even before any Trace UI exists.

---

### Phase 4 — AI Cockpit and the Trace visualisation
1. AI Cockpit: question input, visible interpretation, visible plan, step-by-step
   progress, results as charts/tables/narrative, follow-up suggestions.
2. **Trace** button on every result.
3. The Trace graph view: a laid-out, pannable, zoomable DAG; governed nodes visually
   distinct from interpretive nodes; every node clickable to a full inspection panel.
4. **Ask / Modify Trace** for a controlled set of modifications:
   change a measure (e.g. borrower count → EAD) · add or remove a filter ·
   change the comparison period · change a grouping dimension.
   Each shows a preview, branches to a new version, re-runs only affected nodes, and
   preserves the original.

**Done when:** a user can ask a question, open the trace, click any node to see exactly
what it did, ask for a change in plain language, see what will change, accept it, and
get a new version alongside the original.

---

### Phase 5 — Engine Builder and Data Builder
1. **Engine Builder:** Analysis Library (all ten functions with full metadata and the
   CreditProbe Certified tick) · Analysis Builder form · Testing & Validation runner ·
   Version & Governance history.
2. **Data Builder:** Data Domains · Dataset Designer · Data Dictionary (the real 69
   fields) · Relationships & Lineage (the real raw→curated→analytical path) ·
   Data Quality & Governance.

Both read and write the same governed metadata the engine and the planner use — so
what a user sees in these screens is genuinely the system's own configuration, not a
parallel description of it.

---

### Phase 6 — The platform capabilities
Projects & Chats · Investigations · Lenses · Blueprints · Stress Testing (built on the
existing scenario presets and climate engine) · Users & Teams · Workflow ·
Settings / Administration including the **Theme Gallery** with all four themes ·
Documents placeholder (Document Library + Document Workspace shell).

---

### Phase 7 — Polish and demo preparation
Seed demo content (a worked Project, saved Investigations, Lenses, Blueprints, a
scenario, a Trace with two versions) · accessibility and contrast validation across
all four themes · empty, loading and error states · performance pass · a written demo
script with the exact questions to ask and what each will show.

---

## 4. If only one working day is available

Recommended cut — the **AI Cockpit → Real Analytics → Trace** vertical slice, because
it is the only part of CreditProbe that no competitor's dashboard can imitate, plus enough
governed surface around it to prove the platform is real.

| Capability | Tier | What it does on the day |
|---|---|---|
| **AI Cockpit / Ask CreditProbe** | **A** | Ask a question, see interpretation → plan → progress → real result + narrative + follow-ups |
| **Engine (10 functions)** | **A** | Real credit-risk maths on the real 10-period dataset, tested |
| **Data layer: Parquet + DuckDB + DAL** | **A** | Real lake, real pushdown, storage genuinely swappable |
| **Trace (view)** | **A** | Full interactive DAG, every node inspectable, on every result |
| **Trace (modify)** | **B** | Four supported modification types, with preview, branch and selective re-run |
| **Engine Builder** | **B** | Library + full metadata + CreditProbe Certified ticks + version history, real and browsable; Builder form read-mostly |
| **Data Builder** | **B** | Domains, datasets, the real 69-field dictionary, real lineage; editing limited |
| **Stress Testing** | **B** | Named scenarios via the engine, with Trace; existing climate model reachable |
| **Themes** | **A** | All four, complete, switchable, in the Theme Gallery |
| **Monitor · Detect** | **B** | Built as Lenses over the certified functions |
| **Projects & Chats** | **B** | Create, name, persist; chats and analyses saved and reopenable |
| **Investigations** | **B** | Persisted multi-step analyses within a project |
| **Lenses** | **B** | Two or three seeded executive lenses, real tiles, each with Trace |
| **Blueprints** | **C** | Real catalogue with real parameter definitions; running limited to seeded ones |
| **Users & Teams** | **C** | Real schema, real users, real roles; administration read-mostly |
| **Workflow** | **C** | Real states and real queue on real objects; transitions limited |
| **Documents** | **C** | Library + Workspace shell, as specified — placeholder by design |
| **Administration** | **C** | Settings surface with the working parts (theme, model, calendar) live |

**What this cut protects:** the demo can withstand being driven off-script in the AI
Cockpit and in Trace, which is exactly where a sceptical CRO or CDO will push. A
question nobody rehearsed still produces a real number with a real trace behind it.

**What this cut concedes:** breadth. Six of eighteen surfaces are designed shells on
day one. They are structurally real, honestly marked, and become Tier A in Phases 5–6.

---

## 5. Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Scope covers 16 capabilities in one day | Sixteen shallow screens destroy credibility | The three-tier cut above; go deep where it counts |
| The planner produces an invalid or unregistered plan | Broken demo moment | Strict validation, deterministic fallback to the nearest registered analysis, and a clear, calm message — never a stack trace |
| LLM latency in front of an audience | Dead air | Stream interpretation and plan first; run engine steps in parallel where independent; show real progress per step |
| Dash cannot stream tokens | The AI feels un-alive | Progressive callback updates per plan step; accept the limit for now, and record the React front end as the planned fix |
| Trace graph layout is unreadable on real analyses | The differentiator falls flat | Deterministic layered layout, collapsible groups, and a tested layout for the specific demo questions |
| Global-DataFrame refactor destabilises working screens | Regression in already-good work | Wrap rather than rewrite; keep existing tests green at every step |
| "GLM 5.2" label on a Claude model | A model-governance finding in front of the exact audience being courted | Correct the display name and record the true model on every run — do this in Phase 1, not later |
| Synthetic data presented as real | Loss of trust | Keep and extend the existing labelling discipline |

---

## 6. Decisions needing your confirmation before Phase 1

1. **The one-day cut.** Is the Tier A/B/C trade in §4 the right one, or would you
   rather have more surfaces working more shallowly?
2. **Front end.** Confirm: Dash now, API-first, React as a planned later replacement —
   or start the React front end now and accept a later demo date?
3. **Theme names.** Executive Light · Midnight · Graphite · Warm Institutional — keep,
   or rename?
4. **Model provider.** Which model should the planner and interpreter use, and shall
   the "GLM 5.2" label be corrected to the true model name?
5. **Demo audience and questions.** Who is watching, and are there specific questions
   they will ask? The planner and the seeded content should be built around those.
6. **Data.** Is `Portfolio_Monitoring_Dataset.xlsx` the dataset for the demo, or is
   there a more representative one to use?
