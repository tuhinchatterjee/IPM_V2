# Full-system feature verification matrix

Generated from the build at `f25a7be` by `scripts/feature_matrix.py`.

This inventory is enumerated, not remembered. Every row comes from a page that exists on disk or an endpoint in the live OpenAPI spec, so a route added and forgotten appears here anyway. Three columns cannot be generated and are curated by hand - expected behaviour, defect and remaining limitation - because each is a claim somebody is accountable for, and deriving them from the code would produce a document that agrees with the code by construction and therefore establishes nothing.

## Summary

| | |
|---|---|
| Pages | 42 |
| Reviewed | 42 |
| Not yet reviewed | 0 |
| Carrying a known defect | 2 |
| Not fully OK | 5 |
| API endpoints | 378 across 31 areas |
| Browser-crawled routes | 37 |

## Pages

### agent-operations

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/agent-operations` | Administrator | Agent Operations: runs, workers, schedules, budgets and approvals. | `agentic` (22) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### ai-studio

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/ai-studio/brain-center` | Administrator | The Brain Center: what Brain is running, the Learning Ledger, the three export formats, quarantined imports, the Lift Lab, the Merge Lab, installation history, rollbacks, compatibility and security. | `intelligence` (45) | - | - | OK | - | Imports, Lift Lab, Merge Lab, Installations and Rollbacks read empty on a fresh installation, because nothing has been imported. That is the honest state, not a missing screen: the pipeline, the resolution set and the enforced security rules render regardless so a reviewer can see what would happen before it does. |
| `/ai-studio/continuous-learning` | Administrator, Data Steward or Analyst | Continuous Learning: what was captured since a chosen baseline and — separately — what measurably changed, the six dimensions on development against validation, the measurement timeline, the three evaluation sets and the thresholds behind every figure. | `intelligence` (45) | - | - | OK | - | Reads NO BASELINE on a fresh installation and NOT MEASURED IN THIS WINDOW once a baseline exists but no evaluation has run inside the selected window. Those are different states and are worded differently, because 'nothing to compare against' and 'nobody looked' read identically as a zero. No sealed-holdout question or gold answer appears here, by §58. |
| `/ai-studio/feedback-learning` | Administrator | Feedback and the governed learning queue: observations, candidates, review and releases. | `intelligence` (45) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/ai-studio` | Administrator | AI Intelligence Studio: the six Intelligence Dimensions, the current release, evaluations and health. | `intelligence` (45) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | All 18 tabs the final brief names. Three of them — Continuous Learning, Brain Center and Regulatory Learning — open onto areas with their own tab bars rather than rendering a panel, because eleven tabs nested inside one tab produce a bar nobody reads. |

### analyses

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/analyses` | any signed-in role | Every saved Analysis, filterable, each opening its definition. | `analyses` (7) | 5 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### analysis

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/analysis/[analysisId]` | any signed-in role | One analysis definition: inputs, method, governed datasets, and a run history. | `analyses` (7) | 4 file(s) | `/analysis/approaching_sicr_threshold` ADMIN FAIL, ANALYST pass, VIEWER FAIL | PARTIAL | Opening the page directly logs a console 404: it requests an Assurance record, and Assurance records belong to Investigations rather than to a bare engine run. The page renders correctly. | Reached through Analyses or Trace, this does not arise. |

### cockpit

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/` | any signed-in role | The Cockpit: ask a question, see recent investigations, and see what requires attention. Counts reflect what actually moved this period. | `ask` (5) | 8 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Requires Attention shows Portfolio and Data as empty at Q2 2026 because nothing moved at those levels. Nothing is invented to fill a filter. |

### data-builder

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/data-builder/browse` | Administrator, Analyst | Every governed dataset, searchable. | `data-builder` (51) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/dataset/[name]` | Administrator, Analyst | One dataset: its grain, its fields, its authority and a real data grid. | `data-builder` (51) | 7 file(s) | `/data-builder/dataset/borrower_financials` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/domain/[...domain]` | Administrator, Analyst | One domain and the datasets under it. | `data-builder` (51) | 4 file(s) | - | OK | - | - |
| `/data-builder/inbox` | Administrator | Incoming data, its drift against the contract, and what to do about it. | `data-builder` (51) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/new` | Administrator | Register a new dataset. | `data-builder` (51) | - | ADMIN pass | OK | - | - |
| `/data-builder` | Administrator, Analyst | The governed catalogue: domains, datasets, families and authority. | `data-builder` (51) | 12 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/relationships` | Administrator, Analyst | The governed relationship graph, its cardinalities and its proposals. | `data-builder` (51) | 2 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### documents

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/documents/[id]` | any signed-in role | One document. | none | - | `/documents/ifrs9-committee-pack` ADMIN pass; `/documents/march-2026-cro-review` ADMIN pass | HIDDEN | - | Same placeholder as /documents. |
| `/documents` | any signed-in role | Document authoring. | none | - | ADMIN pass, ANALYST pass, VIEWER pass | HIDDEN | - | A placeholder. Hidden in Demo Mode rather than shown as though it worked. |

### early-warning

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/early-warning/lab` | Administrator | The signal's specification, weights and out-of-time backtest. Model internals are labelled technical. | `early-warning` (10) | - | ADMIN pass | OK | - | - |
| `/early-warning` | Administrator, Analyst | The Forward Risk Signal: which facilities are deteriorating and what is driving each score. | `early-warning` (10) | 2 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### engine-builder

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/engine-builder/[analysisId]` | Administrator, Analyst | One registered analysis. | `engine` (7) | 3 file(s) | - | OK | - | - |
| `/engine-builder/new` | Administrator | Register a new engine analysis. | `engine` (7) | - | - | OK | - | - |
| `/engine-builder` | Administrator, Analyst | Registered engine analyses. | `engine` (7) | 3 file(s) | ADMIN pass | OK | - | - |

### investigations

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/investigations/[id]` | any signed-in role | One Investigation: its thread, its analyses, its Trace, its assurance record and How CreditProbe Performed. | `investigations` (16) | 12 file(s) | `/investigations/4991` ADMIN pass, ANALYST pass, VIEWER pass; `/investigations/4992` ADMIN pass | OK | - | - |
| `/investigations` | any signed-in role | Global Investigations, newest first, with their status. | `investigations` (16) | 12 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/investigations/saved/[id]` | any signed-in role | A saved Investigation at a chosen version, refreshable against a new period. | `investigations` (16) | - | - | OK | - | - |

### lenses

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/lenses/[lensId]` | Administrator, Analyst | One Lens and its panels. | `lenses` (9) | 2 file(s) | `/lenses/cro` ADMIN pass, ANALYST pass, VIEWER FAIL; `/lenses/q2-2026-portfolio-position` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/lenses/cro` | Administrator, Analyst | The CRO Lens: the executive story. | `lenses` (9) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER FAIL | OK | - | - |
| `/lenses` | any signed-in role | Saved dashboards of governed analyses. | `lenses` (9) | 2 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | PARTIAL | A Viewer sees the Lenses link and gets a dashboard of refusals: every tile runs an analysis and running one requires an Analyst. | The permission is deliberate; the invitation is the rough edge. Sign in as Analyst or Administrator. |

### playbooks

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/playbooks` | any signed-in role | Saved sequences of governed analyses. | `playbooks` (8) | - | ADMIN pass, ANALYST pass, VIEWER pass | PARTIAL | - | Manual and on-publication triggers run; scheduled triggers are not wired to a scheduler. |

### projects

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/projects/[id]` | any signed-in role | One Project: its Investigations, its people, its workflow and its Risk Cases. Project-scoped work stays inside it until published. | `workspace` (18) | 4 file(s) | `/projects/2409` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | A Project holds context, threads, analyses and people but not a structured operating plan; the governed Project Plan is not built. |
| `/projects` | any signed-in role | Credit Projects the signed-in user can reach. | `workspace` (18) | 4 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### scorecard-validation

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/scorecard-validation` | Administrator, Data Steward or Analyst | Retail Scorecard Validation: the application and behavioural scorecards, twelve tabs covering discrimination, calibration, stability, variable diagnostics, implementation replication, the model registry with its exact equations, the two agentic diagnostics, trends, findings and the validation policy. | `scorecard` (16) | 1 file(s) | - | OK | - | Every figure is computed over synthetic demonstration data marked SYNTHETIC_DEMO, which describes no real customer. A month whose twelve-month performance window has not closed shows stability only, and says when the window closes rather than showing a zero. Metrics with no approved limit read NO APPROVED LIMIT, which is not a pass and is not the same as NOT MEASURED. The validation opinion is derived by governed policy and is not regulatory certification. |

### settings

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/settings` | any signed-in role | Theme, display preferences and session. | `users` (5) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### stress

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/stress` | Administrator, Analyst | Scenario definitions and their impact. | none | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### studio

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/studio/[methodId]` | Administrator, Analyst | One method: its definition, its validation and its certification. | `studio` (14) | 3 file(s) | `/studio/approaching_sicr` ADMIN pass, ANALYST pass, VIEWER pass; `/studio/new` ADMIN pass | OK | - | - |
| `/studio/new` | Administrator, Analyst | Define a new method for validation. | `studio` (14) | - | ADMIN pass | OK | - | - |
| `/studio` | Administrator, Analyst | Analysis Studio: the certified method library. | `studio` (14) | 3 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/studio/regulatory-intelligence` | Administrator or Data Steward | Regulatory Intelligence: the document library, the sixteen-stage processing pipeline, extracted requirements with their citations and confidence, one-by-one review, contradictions and their governed resolutions, draft method candidates and the audit trail. | `studio` (14) | - | - | OK | - | Reads empty on a fresh installation until a regulatory document has been processed. The pipeline, the fifteen requirement types, the twelve contradiction classes and the ten resolutions render regardless, so a reviewer can see what would happen before it does. Extraction produces proposed requirements only — nothing here changes a method, a policy or the ontology. |

### trace

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/trace/[runId]` | any signed-in role | The Trace for one run: Story, Lineage, Landscape and Audit, with governed and interpretive steps drawn differently. | `trace` (6) | 8 file(s) | `/trace/10265` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/trace` | any signed-in role | Recent analysis runs, each opening its Trace. | `trace` (6) | 8 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### users

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/users` | Administrator | Users, roles and teams. | `users` (5) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### workflow

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/workflow` | any signed-in role | Assigned work, comments and notifications. | `workspace` (18) | 3 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

## Capabilities with no page

Reported rather than omitted: a capability that exists only at the API is one a demonstration cannot show, and that is a fact about this build.

| Capability | Reachable at | What works | Why there is no screen |
|---|---|---|---|
| Regulatory circular knowledge | `/api/v1/regulatory/*` | Ingestion in six formats, SME review, releases, as-of retrieval, citations and five critical Assurance gates. | Reachable at the API and tested. No screen; the Regulatory Intelligence UI is being added in this phase. |
| Teaching corpus import | `/api/v1/teaching-corpus/*` | Template, four-outcome preview and import of 500+ human Q&A. | Works at the API. No screen. |
| Governed XLSX exports | `/api/v1/analysis-runs/{id}/export` | Results Workbook and the 20-sheet Calculation Pack, from every surface that shows a result. | Download buttons exist on every result surface; the export itself has no page of its own, by design. |
| Live AI verification | `scripts/verify-live-ai.ps1` | DryRun, Quick, Critical, Feedback and Regulatory modes against the real provider, run from Windows. | A script, not a screen. Deliberately: it spends API credit and must be run deliberately. |

## API surface

| Area | Endpoints |
|---|---|
| `agentic` | 22 |
| `ai` | 5 |
| `analyses` | 7 |
| `analysis-runs` | 3 |
| `ask` | 5 |
| `auth` | 3 |
| `brain` | 24 |
| `build` | 1 |
| `catalog` | 1 |
| `continuous-learning` | 14 |
| `data-builder` | 51 |
| `demo` | 1 |
| `early-warning` | 10 |
| `engine` | 7 |
| `feedback` | 11 |
| `health` | 1 |
| `intelligence` | 45 |
| `investigations` | 16 |
| `learning` | 24 |
| `lenses` | 9 |
| `playbooks` | 8 |
| `projects` | 7 |
| `regulatory` | 13 |
| `regulatory-intelligence` | 17 |
| `risk-cases` | 11 |
| `scorecard` | 16 |
| `studio` | 14 |
| `teaching-corpus` | 3 |
| `trace` | 6 |
| `users` | 5 |
| `workspace` | 18 |

## What this document does not claim

* The **Test** column is a grep, not a coverage measurement. It says a route is named in a test file somewhere; it does not say the route is well tested, and reading it as coverage would be exactly the false comfort this matrix exists to prevent.
* The **Browser** column reflects the most recent recorded crawl. Where it reads `-`, the route was not visited in that run.
* A row marked OK means no defect is known, not that none exists.

