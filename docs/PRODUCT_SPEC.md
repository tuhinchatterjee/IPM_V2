# CreditProbe — Product Specification

**CreditProbe** = **Credit Portfolio Intelligence & Monitoring** — an AI-native credit-risk
analytical platform for banks.

Status: **specification / architecture baseline.** This document defines what the
product is. It does not describe what is currently built (see
`DEMO_SCOPE.md` for that).

---

## 1. What CreditProbe is, and what it is not

CreditProbe is **not** a dashboard with a chatbot bolted onto the side. A dashboard answers
questions someone anticipated when they built the screen. CreditProbe answers questions
nobody anticipated, by planning and running a real analysis on governed data.

A credit officer should be able to type:

- "What deteriorated this month?"
- "Why has Stage 2 increased?"
- "Which sectors deteriorated most?"
- "Show me the rating transition matrix."
- "Stress the Real Estate portfolio."

…and get back a **defensible answer**: real numbers, produced by tested code, with a
complete, inspectable record of how they were produced.

The test of the product is not "did it answer?" It is: **could the Head of Credit Risk
put this number in a Board pack and defend it under challenge?**

---

## 2. The governing rule: the LLM is not the calculator

This is the single most important rule in the product. Everything else follows from it.

### The LLM is responsible for

| Responsibility | Meaning |
|---|---|
| Understanding the question | Parse natural language into a structured intent |
| Interpreting intent | Resolve "this month", "deteriorated", "Real Estate" against the governed catalogue |
| Creating an investigation plan | Decide *which* approved analyses to run, in what order |
| Choosing approved CreditProbe functions | Select from the **registry only** — it cannot invent a calculation |
| Selecting parameters | Reporting dates, filters, groupings, thresholds |
| Orchestrating multiple steps | Chain analyses; feed one result into the next |
| Interpreting returned results | Turn numbers into a narrative a human can read |
| Recommending follow-ups | Propose the next question worth asking |

### The deterministic CreditProbe Engine is responsible for

| Responsibility | Meaning |
|---|---|
| Retrieving data | Reading from the governed analytical layer |
| Filtering | Applying period, segment, sector, region, rating filters |
| Aggregating | Sums, weighted averages, counts, distributions |
| Portfolio metrics | EAD, NPL, coverage, utilisation, concentration |
| Migrations | Stage migration, DPD migration |
| Transition matrices | Rating transition over any lookback |
| ECL analysis | ECL movement and attribution |
| Deterioration analysis | Ranking and driver decomposition |
| Stress scenarios | Applying shocks and re-deriving outcomes |
| Structured numeric output | Typed results with units, precision, and provenance |

### The hard boundary

> **Every material number displayed in CreditProbe must be produced by deterministic,
> testable, version-controlled engine code. The LLM never performs arithmetic
> and is never the source of truth for a figure.**

Mechanically enforced, not merely requested:

1. The LLM's only numeric-facing output is an **Analysis Plan** — a structured
   document validated against a strict schema.
2. The plan may reference **only** function IDs that exist in the Engine Registry,
   with parameters that satisfy each function's declared contract.
3. Anything else is **rejected before execution**, not fixed up silently.
4. The narrative layer receives the engine's structured results and is instructed to
   quote them; it never sees raw records it could sum itself.

Plain English: *the AI can only order from the menu. It cannot cook.*

---

## 3. Core capabilities

### 1. AI Cockpit / Ask CreditProbe
The primary entry point. A conversational surface where a user asks a question in
plain language. CreditProbe shows its interpretation, its plan, its progress through the plan,
then the result: charts, tables and a narrative. Every result carries a **Trace**
button and suggested follow-up questions.

### 2. Monitor
Standing, scheduled surveillance of the portfolio: period-over-period movement in
exposure, stage distribution, ECL, coverage, NPL, concentration and limit utilisation.
Answers "what is the state of the book, and what moved?"

### 3. Detect
Rule- and signal-driven identification of emerging problems before they are
delinquent: SICR triggers, rating downgrades, covenant headroom erosion, utilisation
spikes, DPD entry, sector-level drift. Produces a ranked, explained watchlist.

### 4. Investigate
Multi-step root-cause work. Where Detect says "Stage 2 rose 180bps", Investigate
decomposes it: which sectors, which borrowers, which trigger, how much each
contributed, and what changed upstream. An Investigation is a persisted, named,
shareable object containing its chats, analyses, traces and conclusions.

### 5. Stress Testing & Simulation
Applying shocks (rate, property price, sector demand, macro paths, climate) and
re-deriving portfolio outcomes. Scenarios are **named, versioned, parameterised
objects** — not free text — so a result can be reproduced exactly. Supports
sensitivity, scenario comparison and reverse stress.

### 6. Trace
See section 4. The differentiator.

### 7. Explain
Contextual "what does this mean?" at any level: a metric definition, a field's
business meaning and lineage, a function's methodology, a specific number's
derivation, or a regulatory concept. Explain draws on the Data Dictionary and the
Engine Registry, so definitions come from governed metadata rather than model memory.

### 8. The work hierarchy: Analysis &lt; Investigation &lt; Project

Three levels, and each is a different unit of work:

| | What it is | What makes it that |
|---|---|---|
| **Analysis** | One certified calculation, kept | A single engine function, stated parameters, a stated period, one result, and the `analysis_run_id` that ties it to its Trace |
| **Investigation** | A conversation | A question, its answer, and the follow-ups it led to. Every answer keeps the analyses that produced it |
| **Project** | A body of work | The investigations that explore one question and the analyses kept as evidence for it, over weeks |

An Investigation remembers what it has SETTLED — the domain and period it has
agreed — so a clarifying question is asked once per thread and never again. A
Project carries standing instructions into every investigation opened inside it,
so "answer for the corporate book" is said once rather than in every question.

A Project's status is governed: DRAFT, ACTIVE, IN REVIEW, COMPLETED, ARCHIVED.
Four of the five are a person's declaration. **IN REVIEW is not**: it appears
only while there is a genuinely open review item against the project, and it is
left when the reviewer decides. A status badge anyone can apply to themselves
means nothing to the person reading it, and "In review" is the badge most likely
to be trusted without checking.

### 9. Playbooks

A **Playbook** is a standing instruction the platform carries out. Five parts:
a **trigger** (on demand, on publication, on a schedule), a **scope** over
governed dimensions, the **analyses** to run, the **conditions** worth somebody's
attention, and the **actions** to take.

Playbooks replaced Blueprints. A Blueprint was a template of a document —
something you filled in. A Playbook RUNS. The work a credit team repeats every
quarter is not writing the same document; it is asking the same questions of new
data and noticing when an answer has changed.

A playbook cannot invent an analysis, write a query, or compute a metric of its
own. A condition whose metric no analysis produced reports as **untestable**,
which is a different fact from being false — and a run that finds nothing says
so rather than reaching for something to report.

### 10. Lenses

A **Lens** is a live view of the book for one audience, made of panels. Two
things distinguish it from a dashboard somebody configured once:

- **It is live.** Opening a Lens executes its analyses against what is published
  now. There are no stored figures, so a Lens cannot quietly go stale, and every
  panel carries its own Trace.
- **It is changed by asking.** "Add obligor concentration", "drop the stress
  panel". Each applied change is a new revision with a sentence saying what
  changed, and restoring an earlier one moves FORWARD as a new revision rather
  than rewinding — so the history of what was tried survives.

The request is matched against the analysis **names**, not their descriptions,
and needs two words to land before anything counts as a match. A request the
library has nothing for changes nothing and says so, rather than being
approximated with the nearest available panel.

### 10b. Early Warning — the Forward Risk Signal

A forward-looking estimate of the chance a facility moves to a worse IFRS 9
stage next quarter, fitted separately for three transitions: Stage 1 to Stage 2,
Stage 1 to default, and Stage 2 to default.

The scoring form is additive and logistic, chosen so that **every score
decomposes exactly** into one contribution per factor, and those contributions
add up to the score. That is what makes the explanation screen a decomposition
rather than a story.

Eighteen factors in six families — Behaviour, Capacity, Rating dynamics,
Structure, Sentiment, Cycle sensitivity — each declaring the governed fields it
reads and the direction a credit officer would expect. A fitted weight that
disagrees with that expectation is flagged rather than hidden.

**It is a prototype and the product never calls it anything else.** The words
*validated*, *production model* and *regulatory model* are derived in code from a
validation record carrying who validated it, when, and the report reference; they
are unreachable without one. Fitting and activating a model is
administrator-only — deliberately the narrowest permission in the product.

See `docs/EARLY_WARNING_METHODOLOGY.md` for the full specification and the public
literature it draws on.

### 11. Documents
*Placeholder for the current demo.* Eventually: a document workspace where Board and
committee papers are authored with live analytical content — paragraph-by-paragraph
editing, embedded charts and tables that stay linked to their Trace, comments,
version history, workflow approval, and export to Word / PowerPoint / PDF.

### 12. Engine Builder
Where authorised users define and govern analytical capability. Four areas:

1. **Analysis Library** — browse every registered analytical function.
2. **Analysis Builder** — define a new one: inputs, datasets, variables, parameters,
   calculation logic, validation rules, outputs, supported visualisations.
3. **Testing & Validation** — run each function against test cases and expected
   results before it may be used.
4. **Version & Governance** — versioning, ownership, review, approval, certification.

**Certification marking:**
- Pre-built, validated capability → **CreditProbe Certified**, shown with a blue verification tick.
- User-created capability → **User Defined / Custom**, **no** tick until it passes certification.

The tick is a control, not decoration. It tells a reader whether a number came from
something the bank has validated.

### 13. Data Builder
Where the bank defines what data exists and what it means. Five areas:

1. **Data Domains** — the top-level organisation of data.
2. **Dataset Designer** — datasets, grain, keys, fields, types.
3. **Data Dictionary** — business names, definitions, allowed values, units, sensitivity.
4. **Relationships & Lineage** — how datasets join; where each field came from.
5. **Data Quality & Governance** — rules, thresholds, owners, status, version.

Initial domains:

| Domain | Contents |
|---|---|
| Core Portfolio / Facility | Facilities, limits, exposure, utilisation, collateral |
| IFRS 9 / ECL | Staging, PD, LGD, EAD, ECL, overlays, coverage |
| Corporate Ratings | Internal grades, external ratings, notch gaps, transitions |
| Retail / SME Scorecards | Scorecard outputs and behavioural indicators |
| Documents | Document metadata and links |
| Policies / Knowledge | Policy text, limits framework, methodology notes |
| CreditProbe Operational Metadata | Runs, traces, versions, usage, audit |

### 14. User Management
Users, teams, roles, permissions. Access is enforced at three levels: **capability**
(may this user open Engine Builder?), **object** (may this user see this project?),
and **data** (may this user see this portfolio / segment / sensitive field?).

### 15. Workflow
Review and approval of things that carry institutional weight: engine function
certification, dataset publication, scenario approval, document sign-off, blueprint
promotion. States, assignees, comments, and an immutable decision record.

### 16. Administration
Tenant configuration, reporting calendar, defaults, model provider settings, usage
and cost, retention, and the system-wide audit view.

---

## 4. Trace — the differentiator

### 4.1 What Trace is

Trace is **not** primarily an audit log. An audit log tells you *that* something
happened. Trace shows **how a particular analysis was created**, as a visual graph you
can inspect, question, and change.

Every analytical result in CreditProbe has a **Trace** button in its top-right corner.

### 4.2 The conceptual chain

```
USER QUESTION
     ↓
INTERPRETATION OF THE QUESTION      ← what CreditProbe understood was being asked
     ↓
INVESTIGATION PLAN
     ↓
DATA DOMAIN                         ← the governed purpose, and how it resolved
     ↓
DATASET  (family · version · period · origin)
     ↓
VARIABLES  (governed field, business name, unit, definition)
     ↓
FILTERS  (rows before → rows after)
     ↓
TRANSFORMATIONS
     ↓
AGGREGATIONS
     ↓
CERTIFIED ENGINE FUNCTION  (id · version · certification)
     ↓
RESULT
     ↓
INTERPRETATION OF THE RESULT        ← the answer, and CreditProbe's reading of it
     ↓
VISUAL
```

**The two interpretations are different things and the map names them separately.**
The first happens BEFORE anything is computed and is answerable to the question: did
CreditProbe understand what was asked, and did it choose the right periods and filters? The
second happens AFTER the engine has run and is answerable to the result: does the
reading follow from the figures?

The result node itself carries both a **direct answer**, whose every figure was quoted
unchanged from an engine result, and CreditProbe's **reading** of those figures, marked as
interpretation. The reading may describe where a movement sits; it may not claim what
caused it, because a decomposition is not an attribution of cause.

Neither interpretive node contains chain-of-thought. There is none to show: the planner
selects from a fixed library and the figures come from tested code.

The chain is a simplification. A real analysis **branches and re-joins**:

```
                      User Prompt
                           |
                    LLM Interpretation
                           |
                     Analysis Plan
                      /         \
            Portfolio Dataset    ECL Dataset
              /    |    \           |
           EAD   Stage  Sector      ECL
              \    |    /           |
              Intermediate Aggregations
                         |
                   Stage Migration
                         |
                     Drivers
                         |
                   Engine Result
                         |
                  LLM Explanation
                    /          \
                 Chart       Narrative
```

### 4.3 The design principle

> **Trace is emitted by execution. It is never written afterwards, and it is never
> written by the LLM.**

If the model describes what it did, that is a story. If the executor records what it
did as it did it, that is evidence. CreditProbe does the second: the executor walks the plan
and every step registers its own node — its inputs, parameters, function identity and
version, row counts, timings, and outputs. **The graph is the execution record.**

### 4.4 Node inspection

Every node is clickable. Depending on type, a node exposes:

- dataset(s) used
- variables / fields read
- reporting date(s) and comparison period
- filters applied, with row counts before and after
- parameters, with their source (user, default, or LLM-selected)
- aggregation logic
- engine function ID **and version**
- intermediate result (previewable)
- final result
- execution time and a content hash

### 4.5 Trace is editable

Inside Trace there is an **Ask / Modify Trace** prompt. Examples:

- "Use EAD rather than borrower count."
- "Exclude Real Estate."
- "Compare March against December."
- "Remove this filter."
- "Add ECL movement."
- "Use a 12-month rating transition matrix."

The system then:

1. Interprets the requested modification.
2. Identifies which nodes are affected.
3. **Shows the proposed change before applying it** — added, removed, changed nodes.
4. Creates a new Trace version / branch on confirmation.
5. Re-runs only the affected downstream steps.
6. Regenerates the result.
7. **Preserves the original Trace**, unchanged, forever.

Selective re-execution works by **content hashing**: each node's hash is derived from
its function version, its parameters, and its upstream nodes' hashes. Change one
parameter and only nodes whose hash changed re-run; everything else reuses its
recorded result. This is what makes modification fast, and it is also what lets the UI
highlight exactly what the change affected.

### 4.6 Trace data model

| Concept | Purpose |
|---|---|
| `AnalysisRun` | One execution of one plan: who, when, which project/chat, status |
| `TraceGraph` | The graph belonging to a run |
| `TraceNode` | One step: type, label, config, inputs, outputs, hash, timing, status |
| `TraceEdge` | A directed dependency between two nodes |
| `TraceVersion` | A named version/branch of a graph, with its parent |
| `TraceModification` | A requested change: text, interpretation, affected nodes, before/after, decision |

Node types:

```
USER_PROMPT · LLM_INTENT · PLAN · DATASET · VARIABLE · FILTER ·
TRANSFORMATION · AGGREGATION · ENGINE_FUNCTION · CALCULATION ·
RESULT · LLM_EXPLANATION · VISUALIZATION
```

Node colour and iconography distinguish **governed** nodes (dataset, engine function,
calculation — the ones carrying numbers) from **interpretive** nodes (LLM intent,
explanation). A reader must be able to see at a glance where the AI's judgement
ends and the deterministic engine begins.

---

## 5. Engine Builder — analytical metadata contract

Every registered analytical function declares:

| Field | Purpose |
|---|---|
| `id`, `name`, `description` | Identity and plain-English purpose |
| `category` | Monitor / Detect / Investigate / Stress / Reference |
| `inputs` | Typed input contract |
| `required_datasets` | Which governed datasets it reads |
| `required_variables` | Which fields, by business name |
| `parameters` | Name, type, default, allowed values, description, required |
| `engine_function` | The code entry point it binds to |
| `calculation_description` | The methodology, in language a risk officer can review |
| `validation_rules` | Pre- and post-conditions the result must satisfy |
| `outputs` | Typed output schema, with units and precision |
| `supported_visualizations` | Which chart/table forms are valid for this output |
| `version` | Semantic version; results record the version that produced them |
| `owner` | Accountable person/team |
| `certification` | `certified` \| `user_defined` \| `draft` \| `deprecated` |
| `test_cases` | Inputs and expected outputs, run on every change |

### Functions required for the demo

| # | Function | Answers |
|---|---|---|
| 1 | Portfolio Summary | "What is the state of the book?" |
| 2 | Stage Distribution | "How is exposure split across IFRS 9 stages?" |
| 3 | Stage Migration | "What moved between stages, and how much?" |
| 4 | DPD Migration | "What moved between delinquency buckets?" |
| 5 | Rating Transition Matrix | "How did ratings migrate over N months?" |
| 6 | Sector Concentration | "Where is the book concentrated?" |
| 7 | ECL Movement | "Why did ECL change, and what drove it?" |
| 8 | Top Deteriorating Borrowers | "Who got worse, and why?" |
| 9 | Portfolio Trend | "How have key metrics moved over time?" |
| 10 | Basic Stress Scenario | "What happens under this shock?" |

All ten are **CreditProbe Certified** for the demo: each has declared metadata, a versioned
implementation, and passing tests.

---

## 6. Data Builder — dataset metadata contract

| Level | Attributes |
|---|---|
| Dataset | name, purpose, domain, grain, primary keys, refresh frequency, owner, sensitivity, version, status |
| Field | technical name, business name, business definition, data type, unit, allowed values, nullability, sensitivity, source system, source field |
| Relationship | from/to dataset, join keys, cardinality, description |
| Lineage | source system → raw → curated → analytical, with the transform at each hop |
| Quality rule | rule type, expression, severity, threshold, owner, last result |

The Data Dictionary is **the** definition of a field. The Explain capability, the LLM's
resolution of business terms, and the Data Builder UI all read the same catalogue, so
there is exactly one definition of "EAD" in the system.

---

## 7. Design and user-experience principles

The UI must be credible in front of a global-bank CRO, Head of Credit Risk, Chief Data
Officer, CEO and Board Risk Committee.

**Required:** restraint, density with clarity, consistent hierarchy, precise
typography and numeric alignment, calm colour used only to carry meaning, and instant
legibility of what is a fact versus what is an interpretation.

**Prohibited:** generic admin-template design, childish colour, neon, crypto-dashboard
styling, excessive gradients, excessive glassmorphism, visual clutter.

### Theming

A **design-token** system: the interface is written against semantic role names
(`--surface`, `--text-primary`, `--accent`, `--negative`, `--chart-1`), never literal
colours. A theme is one set of values for those roles.

Eight premium themes — four light, four dark:

| Theme | Mode | Character |
|---|---|---|
| **Executive Ivory** | Light | Default. Paper-like, high contrast, print-credible. |
| **Warm Sand** | Light | Warm off-white and ink. Traditional, document-like. |
| **Alpine** | Light | Cool glacial light with a deep teal accent. The crispest. |
| **Porcelain** | Light | Near-white, almost chroma-free. Only the data is saturated. |
| **Midnight Boardroom** | Dark | Deep navy-black. Long sessions and presentation rooms. |
| **Graphite** | Dark | Neutral dark grey. Sober, engineering-toned, low chroma. |
| **Oxblood** | Dark | Deep wine and brass. Warm and closed; the panelled room. |
| **Forest** | Dark | Deep pine with a eucalyptus accent. The calmest at low light. |

Themes may change: background, surface, elevated surface, border, text, muted text,
accent, positive, warning, negative, and the chart palette.

Themes must **not** change: layout, typography system, spacing scale, hierarchy, or
interaction model. Switching theme changes how the product looks, never how it works.

Every palette is **asserted, not judged by eye**. `tests/frontend/test_theme_contrast.py`
reads `globals.css` and checks, per theme: body text at 7:1 and secondary at 4.5:1 on
that theme's own surfaces; every status colour legible both on the surface and on its
own tint; every chart slot separated from the surface it is drawn on; and adjacent chart
slots separated perceptually in CIELAB rather than by contrast ratio — a good categorical
palette is deliberately close in lightness, so a luminance test would fail exactly the
palettes that are correct.

A **Theme Gallery** under Settings lets a user preview and select their theme; the
choice is stored per user. The header carries a one-click switcher grouped by light and
dark.

### Explanation without furniture

A screen opens on its title and its content. The paragraph explaining what the screen is
for lives behind a small **"i"** next to the title, not underneath it. Fourteen screens
of standfirst is fourteen paragraphs between a reader and the figures, read once and
skipped for ever after.

---

## 8. Non-negotiables

1. No material number is produced by an LLM.
2. Every result is traceable to data, parameters, function and version.
3. Every analysis is reproducible — same inputs and versions, same output.
4. The original Trace is never mutated; modification creates a version.
5. Certification status is always visible where a number is displayed.
6. Field definitions come from the governed Data Dictionary, not from model memory.
7. The AI model in use is always accurately identified to the user.
8. Synthetic, proxied or illustrative data is labelled as such in the UI.
