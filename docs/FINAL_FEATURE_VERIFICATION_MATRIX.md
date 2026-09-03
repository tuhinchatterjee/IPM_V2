# Full-system feature verification matrix

Generated from the build at `0b6181a` by `scripts/feature_matrix.py`.

This inventory is enumerated, not remembered. Every row comes from a page that exists on disk or an endpoint in the live OpenAPI spec, so a route added and forgotten appears here anyway. Three columns cannot be generated and are curated by hand - expected behaviour, defect and remaining limitation - because each is a claim somebody is accountable for, and deriving them from the code would produce a document that agrees with the code by construction and therefore establishes nothing.

## Summary

| | |
|---|---|
| Pages | 51 |
| Reviewed | 51 |
| Not yet reviewed | 0 |
| Carrying a known defect | 2 |
| Not fully OK | 6 |
| API endpoints | 498 across 39 areas |
| Browser-crawled routes | 98 |

## Pages

### agent-operations

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/agent-operations` | Administrator | Agent Operations: runs, workers, schedules, budgets and approvals. | `agentic` (22) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### ai-studio

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/ai-studio/brain-center` | Administrator | The Brain Center: what Brain is running, the Learning Ledger, the three export formats, quarantined imports, the Lift Lab, the Merge Lab, installation history, rollbacks, compatibility and security. | `intelligence` (45) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Imports, Lift Lab, Merge Lab, Installations and Rollbacks read empty on a fresh installation, because nothing has been imported. That is the honest state, not a missing screen: the pipeline, the resolution set and the enforced security rules render regardless so a reviewer can see what would happen before it does. |
| `/ai-studio/continuous-learning` | Administrator, Data Steward or Analyst | Continuous Learning: what was captured since a chosen baseline and — separately — what measurably changed, the six dimensions on development against validation, the measurement timeline, the three evaluation sets and the thresholds behind every figure. | `intelligence` (45) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Reads NO BASELINE on a fresh installation and NOT MEASURED IN THIS WINDOW once a baseline exists but no evaluation has run inside the selected window. Those are different states and are worded differently, because 'nothing to compare against' and 'nobody looked' read identically as a zero. No sealed-holdout question or gold answer appears here, by §58. |
| `/ai-studio/feedback-learning` | Administrator | Feedback and the governed learning queue: observations, candidates, review and releases. | `intelligence` (45) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/ai-studio` | Administrator | AI Intelligence Studio: the six Intelligence Dimensions, the current release, evaluations and health. | `intelligence` (45) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | All 18 tabs the final brief names. Three of them — Continuous Learning, Brain Center and Regulatory Learning — open onto areas with their own tab bars rather than rendering a panel, because eleven tabs nested inside one tab produce a bar nobody reads. |

### analyses

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/analyses` | any signed-in role | Every saved Analysis, filterable, each opening its definition. | `analyses` (7) | 6 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### analysis

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/analysis/[analysisId]` | any signed-in role | One analysis definition: inputs, method, governed datasets, and a run history. | `analyses` (7) | 4 file(s) | `/analysis/approaching_sicr_threshold` ADMIN pass, ANALYST pass, VIEWER pass | PARTIAL | Opening the page directly logs a console 404: it requests an Assurance record, and Assurance records belong to Investigations rather than to a bare engine run. The page renders correctly. | Reached through Analyses or Trace, this does not arise. |

### borrower-360

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/borrower-360` | Every role can open it; the relationship graph is Administrator, Data Steward or Analyst; the named natural persons behind a borrower are Administrator or Data Steward; the export is separate again. | Borrower 360: one corporate borrower and everything the bank knows about it, across thirteen tabs, with eleven views of its relationship network, the six ways of grouping it shown side by side rather than reconciled, its hidden-relationship candidates, the graph data-quality register, and a seventeen-sheet export. | none | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Every figure is computed over synthetic demonstration data marked SYNTHETIC_DEMO, which describes no real company and no real ownership structure. The connected counterparty groups are CANDIDATES for assessment, not determinations - graph connectivity is not regulatory connectedness. The Network Risk Score is a relative ranking within this population and is not a probability, a rating, an IFRS 9 stage or an expected credit loss. The group and single-name limit thresholds are UNVERIFIED REGULATORY PARAMETERS. A quarter the derivation has not been run for reads NOT COMPUTED rather than showing a blank. |

### cockpit

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/` | any signed-in role | The Cockpit: ask a question, see recent investigations, and see what requires attention. Counts reflect what actually moved this period. | `ask` (8) | 11 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Requires Attention shows Portfolio and Data as empty at Q2 2026 because nothing moved at those levels. Nothing is invented to fill a filter. |

### data-builder

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/data-builder/browse` | Administrator, Analyst | Every governed dataset, searchable. | `data-builder` (58) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/dataset/[name]` | Administrator, Analyst | One dataset: its grain, its fields, its authority and a real data grid. | `data-builder` (58) | 8 file(s) | `/data-builder/dataset/borrower_cash_flow` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/domain/[...domain]` | Administrator, Analyst | One domain and the datasets under it. | `data-builder` (58) | 6 file(s) | `/data-builder/domain/Core%20Portfolio%20/%20Facility` ADMIN pass; `/data-builder/domain/Corporate%20Ratings` ADMIN pass | OK | - | - |
| `/data-builder/inbox` | Administrator | Incoming data, its drift against the contract, and what to do about it. | `data-builder` (58) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/new` | Administrator | Register a new dataset. | `data-builder` (58) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder` | Administrator, Analyst | The governed catalogue: domains, datasets, families and authority. | `data-builder` (58) | 16 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/data-builder/relationships` | Administrator, Analyst | The governed relationship graph, its cardinalities and its proposals. | `data-builder` (58) | 2 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### delivery

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/delivery/[id]` | any signed-in role | One delivery project across seven tabs — Overview, Plan, Milestones, RAID, People, Updates, Brief — with the export and workbook import, the chase drafts, and an AI brief whose every line is labelled Fact, Reading, Suggested or Not recorded. | none | - | - | PARTIAL | - | Risks and milestones can be raised and added here but not edited here: closing a risk or marking a milestone achieved is still API-and-workbook only. There is no Gantt or timeline renderer, and the critical-path flag is a marker rather than a computed longest path — the engine refuses to present a critical path it has not calculated. |
| `/delivery/my-work` | any signed-in role | Every task with your name on it, across every delivery project, in six buckets ordered by what needs you first. Clicking one opens the quick update: status, progress, a sentence, and blocked with a reason. | none | - | - | OK | - | Owner and due date are deliberately absent from the quick update. Reporting progress and moving a commitment are different acts, the second needs editor access, and a field that can only ever produce a 403 is worse than no field. The drawer says so rather than leaving it to be discovered. |
| `/delivery` | any signed-in role | The delivery portfolio: every project you are a participant on, with its health and the sentence behind it, weighted progress, overdue and blocked counts, next milestone and manager. An Attention panel above the table names the projects that need somebody, with the reason for each, and a portfolio read labels every claim as a fact or a reading of the facts. | none | - | - | OK | - | A project nobody has put you on is not listed and cannot be opened by its URL. That is the access boundary, not a gap: CreditProbe is single-tenant, so participation IS the boundary. |

### documents

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/documents/[id]` | any signed-in role | One document. | none | - | `/documents/ifrs9-committee-pack` ADMIN pass; `/documents/march-2026-cro-review` ADMIN pass | HIDDEN | - | Same placeholder as /documents. |
| `/documents` | any signed-in role | Document authoring. | none | - | ADMIN pass, ANALYST pass, VIEWER pass | HIDDEN | - | A placeholder. Hidden in Demo Mode rather than shown as though it worked. |

### early-warning

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/early-warning/lab` | Administrator | The signal's specification, weights and out-of-time backtest. Model internals are labelled technical. | `early-warning` (21) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/early-warning` | Administrator, Analyst | The Forward Risk Signal: which facilities are deteriorating and what is driving each score. | `early-warning` (21) | 5 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/early-warning/signals` | Administrator, Analyst | The governed early-warning taxonomy, borrower by borrower: which named conditions fire, in which families, with the threshold each crossed and who owns it. Deliberately carries no score, and names both what could not be tested and what this deployment cannot watch for at all. | `early-warning` (21) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### engine-builder

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/engine-builder/[analysisId]` | Administrator, Analyst | One registered analysis. | `engine` (7) | 4 file(s) | `/engine-builder/approaching_sicr_threshold` ADMIN pass; `/engine-builder/arrears_position` ADMIN pass | OK | - | - |
| `/engine-builder/new` | Administrator | Register a new engine analysis. | `engine` (7) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/engine-builder` | Administrator, Analyst | Registered engine analyses. | `engine` (7) | 4 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### investigations

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/investigations/[id]` | any signed-in role | One Investigation: its thread, its analyses, its Trace, its assurance record and How CreditProbe Performed. | `investigations` (16) | 16 file(s) | `/investigations/11806` ADMIN pass; `/investigations/11807` ADMIN pass | OK | - | - |
| `/investigations` | any signed-in role | Global Investigations, newest first, with their status. | `investigations` (16) | 16 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/investigations/saved/[id]` | any signed-in role | A saved Investigation at a chosen version, refreshable against a new period. | `investigations` (16) | - | - | OK | - | - |

### lenses

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/lenses/[lensId]` | Administrator, Analyst | One Lens and its panels. | `lenses` (9) | 3 file(s) | `/lenses/cro` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/lenses/cro` | Administrator, Analyst | The CRO Lens: the executive story. | `lenses` (9) | 2 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/lenses` | any signed-in role | Saved dashboards of governed analyses. | `lenses` (9) | 3 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | PARTIAL | A Viewer sees the Lenses link and gets a dashboard of refusals: every tile runs an analysis and running one requires an Analyst. | The permission is deliberate; the invitation is the rough edge. Sign in as Analyst or Administrator. |

### messages

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/messages/[threadId]` | any signed-in role | One conversation: every message in order, the attachments as cards that open the object, the review actions the state machine permits, and the append-only status history. Opening it marks it read and the unread count falls immediately. | `messages` (18) | 10 file(s) | - | OK | - | Forwarding is not implemented; reply and reply-to-thread are. Whether an attachment's share grant should travel with a forward is a permission decision nobody has made. |
| `/messages` | any signed-in role | The message centre: Inbox, Action required, Sent, Drafts and Archived over one set of messages, with search and an unread filter. Composing offers the governed directory on focus and shares analyses, investigations and files as access-checked cards. | `messages` (18) | 10 file(s) | - | OK | - | Unread counts conversations rather than individual messages: one Inbox row is one conversation, and opening it reads everything currently in it. |

### playbooks

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/playbooks` | any signed-in role | Saved sequences of governed analyses. | `playbooks` (8) | - | ADMIN pass, ANALYST pass, VIEWER pass | PARTIAL | - | Manual and on-publication triggers run; scheduled triggers are not wired to a scheduler. |

### projects

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/projects/[id]` | any signed-in role | One Project: its Investigations, its people, its workflow and its Risk Cases. Project-scoped work stays inside it until published. | `workspace` (18) | 8 file(s) | `/projects/6403` ADMIN pass; `/projects/6404` ADMIN pass | OK | - | A Project holds context, threads, analyses and people but not a structured operating plan; the governed Project Plan is not built. |
| `/projects` | any signed-in role | Credit Projects the signed-in user can reach. | `workspace` (18) | 8 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### reviews

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/reviews` | any signed-in role | One person's own review queue: what has been sent to them for review, approval, sign-off or comment, what they are waiting on, where they were named, what is due, and what is closed. Every decision writes to an append-only history. | none | 1 file(s) | - | OK | - | A Viewer may read a decision history and reply, but not decide; the decision buttons are hidden rather than shown and refused. |

### scorecard-validation

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/scorecard-validation` | Administrator, Data Steward or Analyst | Retail Scorecard Validation: the application and behavioural scorecards, twelve tabs covering discrimination, calibration, stability, variable diagnostics, implementation replication, the model registry with its exact equations, the two agentic diagnostics, trends, findings and the validation policy. | `scorecard` (28) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Every figure is computed over synthetic demonstration data marked SYNTHETIC_DEMO, which describes no real customer. A month whose twelve-month performance window has not closed shows stability only, and says when the window closes rather than showing a zero. Metrics with no approved limit read NO APPROVED LIMIT, which is not a pass and is not the same as NOT MEASURED. The validation opinion is derived by governed policy and is not regulatory certification. |

### settings

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/settings` | any signed-in role | Theme, display preferences and session. | `users` (5) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### stress

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/stress` | Administrator, Analyst | Scenario definitions and their impact. | none | 2 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### studio

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/studio/[methodId]` | Administrator, Analyst | One method: its definition, its validation and its certification. | `studio` (14) | 4 file(s) | `/studio/approaching_sicr` ADMIN pass, ANALYST pass, VIEWER pass; `/studio/new` ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/studio/new` | Administrator, Analyst | Define a new method for validation. | `studio` (14) | - | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/studio` | Administrator, Analyst | Analysis Studio: the certified method library. | `studio` (14) | 4 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |
| `/studio/regulatory-intelligence` | Administrator or Data Steward | Regulatory Intelligence: the document library, the sixteen-stage processing pipeline, extracted requirements with their citations and confidence, one-by-one review, contradictions and their governed resolutions, draft method candidates and the audit trail. | `studio` (14) | 1 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Reads empty on a fresh installation until a regulatory document has been processed. The pipeline, the fifteen requirement types, the twelve contradiction classes and the ten resolutions render regardless, so a reviewer can see what would happen before it does. Extraction produces proposed requirements only — nothing here changes a method, a policy or the ontology. |

### trace

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/trace/[runId]` | any signed-in role | The Trace for one run: Story, Lineage, Landscape and Audit, with governed and interpretive steps drawn differently. | `trace` (6) | 9 file(s) | - | OK | - | - |
| `/trace` | any signed-in role | Recent analysis runs, each opening its Trace. | `trace` (6) | 9 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### users

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/users` | Administrator | Users, roles and teams. | `users` (5) | 4 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | - |

### workflow

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/workflow` | Administrator | Administrative oversight of message and review activity across every account: who is active, who has unread work, whose requests are overdue, who has stopped signing in, with a link to Users. Counts and status only. | `workspace` (18) | 4 file(s) | ADMIN pass, ANALYST pass, VIEWER pass | OK | - | Deliberately carries no subject line and no message body. Reading a conversation requires being in it, and administering an account is not being in it; governance reads the audit log, which records acts rather than contents. |

### workspace

| Route | Role | Expected behaviour | API area | Test | Browser | Status | Defect | Remaining limitation |
|---|---|---|---|---|---|---|---|---|
| `/workspace` | any signed-in role | My workspace: what is waiting on this person, what colleagues have shared with them, and what they have recently worked on. Every tile is a count of real rows that can be clicked through to. | `workspace` (18) | 4 file(s) | - | OK | - | Reads the same attention summary as the header badge and the mailbox tabs, so the four cannot disagree. |

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
| `ai` | 7 |
| `analyses` | 7 |
| `analysis-runs` | 3 |
| `ask` | 8 |
| `auth` | 3 |
| `brain` | 24 |
| `build` | 1 |
| `catalog` | 1 |
| `continuous-learning` | 14 |
| `corporate` | 17 |
| `data-builder` | 58 |
| `demo` | 1 |
| `domain-intelligence` | 3 |
| `early-warning` | 21 |
| `engine` | 7 |
| `feedback` | 11 |
| `health` | 1 |
| `intelligence` | 45 |
| `investigations` | 16 |
| `learning` | 24 |
| `lenses` | 9 |
| `messages` | 18 |
| `metadata` | 6 |
| `planner` | 31 |
| `playbooks` | 8 |
| `preferences` | 3 |
| `projects` | 7 |
| `readiness` | 1 |
| `regulatory` | 13 |
| `regulatory-intelligence` | 17 |
| `risk-cases` | 11 |
| `scorecard` | 28 |
| `studio` | 14 |
| `teaching-corpus` | 3 |
| `trace` | 6 |
| `users` | 5 |
| `whatif` | 6 |
| `workspace` | 18 |

## What this document does not claim

* The **Test** column is a grep, not a coverage measurement. It says a route is named in a test file somewhere; it does not say the route is well tested, and reading it as coverage would be exactly the false comfort this matrix exists to prevent.
* The **Browser** column reflects the most recent recorded crawl. Where it reads `-`, the route was not visited in that run.
* A row marked OK means no defect is known, not that none exists.

