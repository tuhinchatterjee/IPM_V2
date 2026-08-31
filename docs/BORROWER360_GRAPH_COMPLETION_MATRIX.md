# Borrower 360 / Corporate Graph — completion matrix

**Verified by running the code in this commit**, branch
`claude/vigilant-darwin-eohyi1`. The previous edition of this file was verified
at `d7c910f`, before any of the derived layer existed; every row that changed
below changed because code was written and run, not because a plan was
written down.

Nothing here is inferred from a filename. Every IMPLEMENTED row was confirmed
by running the code and reading what it produced; every NOT_IMPLEMENTED row
was confirmed by searching for the symbol and finding nothing that constructs
it.

Statuses used: **IMPLEMENTED**, **PARTIAL**, **NOT_IMPLEMENTED**, **BROKEN**,
**NOT_VERIFIED**.

---

## Phase 2.1 — Observed vs derived

| Requirement | Status | Evidence |
|---|---|---|
| 12 observed edge types defined | IMPLEMENTED | `graphdata.OBSERVED_EDGE_TYPES` has all 12 |
| Observed edges actually generated | PARTIAL | 11 of 12 present in data. **`CONTROLS` is declared but nothing constructs it** — control is *derived* here, from voting percentages, and the observed assertion channel exists (`control_closure(explicit=…)`) but no source system in this synthetic book files one |
| `valid_from`, `valid_to`, `recorded_at`, `source`, `confidence` | IMPLEMENTED | present on every observed edge frame |
| `source_record_id` on observed edges | NOT_IMPLEMENTED | column absent from all four edge frames |
| `portfolio_scope` on observed edges | NOT_IMPLEMENTED | present on the *dataset* (B44) but not on the edge row |
| `validation status` on observed edges | NOT_IMPLEMENTED | no such column; the *derived* products carry one |
| Derived edge types UBO_OF / CONTROLS_EFFECTIVELY / MEMBER_OF / CONNECTED_TO / SIMILAR_TO | IMPLEMENTED | `graphmath.DERIVED_EDGE_TYPES` names all five; `network.SIMILAR_TO` is produced with its own edge payload |
| Derived edge provenance (`computed_at`, `pipeline_version`, `derivation_method`, `inputs`, `policy_version`, validation status) | IMPLEMENTED | `EffectiveOwnership.provenance()`, `ControlClosure.provenance()`, `ConnectedGroups.provenance()`, `DebtRankResult.to_dict()`, `SimilarityCandidate.to_edge()` each carry method, policy version, as-of and validation status |

## Phase 2.2 — Bitemporal point-in-time

| Requirement | Status | Evidence |
|---|---|---|
| Three-clause as-of predicate | IMPLEMENTED | `graphdata.as_of()`, one implementation, imported everywhere |
| Look-ahead test proves the third clause excludes something | IMPLEMENTED | validity-only vs. full predicate counts asserted different — a guard that never fires is untested |
| Recording genuinely lags validity | IMPLEMENTED | median lag > 30 days, max > 365, asserted |
| Derived products reproducible as-of | IMPLEMENTED | every derived object carries `as_of`; `GQ-07` REJECTS if any edge in an as-of view was recorded after that date, and it passes on the real book |

## Phase 2.3–2.5 — Ownership mathematics and control

| Requirement | Status | Evidence |
|---|---|---|
| `ownership_pct` separate from `voting_pct` | IMPLEMENTED | both columns, divergent in ~9% of holdings, tested both ways |
| Ownership matrix `A` | IMPLEMENTED | `build_ownership_graph`, 9,333 nodes as at Q2 2026 |
| `(I−A)X = A` linear solve | IMPLEMENTED | per weakly connected component; 2.6s over the full book |
| Spectral radius ρ(A) computed before solve | IMPLEMENTED | per component, recorded in provenance |
| `GRAPH_DATA_QUALITY_REJECTED` on ρ(A) ≥ 1 | IMPLEMENTED | refusal is per component; `stake()` and `owners_of()` raise rather than return the zero block |
| Ownership chain explanation, depth 6, cycle exclusion | IMPLEMENTED | `ownership_chains`, `MAX_CHAIN_DEPTH = 6` |
| Matrix-vs-path disagreement warning | IMPLEMENTED | `CHAIN_DISAGREEMENT_PCT = 1.0`, reported on the explanation |
| Binary control graph, SCC condensation, reachability | IMPLEMENTED | iterative Tarjan, condensation, Warshall per component — 2.5s, down from >600s for the dense form |
| `CONTROLS_EFFECTIVELY` | IMPLEMENTED | `ControlClosure.effective` |
| Integrated stake above 100% under reciprocity | IMPLEMENTED | reported and FLAGGED, never capped; a >100% stake in an acyclic component would be a genuine defect and the regression asserts it never happens |

## Phase 2.6–2.8 — Connected counterparties, percolation, interdependence

| Requirement | Status | Evidence |
|---|---|---|
| Connected-group formation pipeline (control candidates → WCC → interdependence → merge) | IMPLEMENTED | `connected_groups`; never weak components over raw OWNS, and the docstring says why |
| `criterion_hit` preserved | IMPLEMENTED | `criterion_hits` per member, `evidence` per group |
| Giant-component / percolation regression | IMPLEMENTED | `GIANT_COMPONENT_SHARE = 0.05`; raw-OWNS and control components both measured |
| Review threshold for large candidate groups | IMPLEMENTED | `REVIEW_GROUP_SIZE = 60`, `needs_review` on the provenance |
| Economic-interdependence predicates | IMPLEMENTED | 8 predicates, each with threshold, inputs, source, as-of, policy version and VALIDATED / CANDIDATE / REJECTED |
| Supply chain never forms a regulatory group | IMPLEMENTED | `corporate_supply_chain → corporate_connected_groups` registered FORBIDDEN with B21 as the reason |

## Phase 2.9–2.11 — Guarantee, supply, exposure networks

| Requirement | Status | Evidence |
|---|---|---|
| Reified Guarantee nodes; Guarantor→PROVIDES→Guarantee→COVERS→Facility | IMPLEMENTED | and now actually resolvable — see the defect below |
| **Facility nodes exist for COVERS to point at** | IMPLEMENTED (was BROKEN) | `FACILITY` was a declared node type and `COVERS` edges always pointed at facility ids, but the node table never contained them: **1,303 of 2,274 guarantee edges pointed at nothing**. Found by `GQ-04` on its first run. `build_facility_nodes` now emits one node per distinct facility |
| Cross / shared / joint-and-several guarantees | IMPLEMENTED | `joint_and_several` set when multiple guarantors |
| Guarantees respect the build window | IMPLEMENTED (was BROKEN) | fixed at `e28bf63`; uses the built window's last quarter, not the module constant |
| SUPPLIES_TO with revenue share, COGS share, validity, source, confidence | PARTIAL | shares present and asymmetric; `annual_value`, `substitutability`, `product/service` absent |
| Exposure network directed and weighted, u→v = u carries exposure to v | IMPLEMENTED | convention stated in `exposure_graph`, because the opposite one silently inverts every downstream answer |
| Exposure amount/type/currency/as-of/source/confidence | PARTIAL | **currency absent** |
| **FUNDED_BY draws distinct channels** | IMPLEMENTED (was defective) | drawn with replacement, so a borrower could be funded by the same channel twice. Duplicate assertions fell 1.34% → 0.07% |

## Phase 2.12–2.16 — Network analytics

| Requirement | Status | Evidence |
|---|---|---|
| DebtRank, deterministic, three states, propagate once | IMPLEMENTED | verified against hand-computed values (A→B→C, capital 100: B=0.5, A=0.25, impact 0.375); the cycle case terminates in 2 iterations at 1.0 without amplifying |
| DebtRank persists seed, shock, iterations, distress, impact, versions, as-of, validation status | IMPLEMENTED | `DebtRankResult.to_dict()` |
| DebtRank labelled as not ECL / not capital | IMPLEMENTED | `DEBTRANK_CAVEAT` on every payload, asserted |
| PageRank forward (transmitters), reverse (hurt), personalised | IMPLEMENTED | the tests assert forward and reverse **disagree** — a run where they agree has lost the direction |
| Dangling nodes do not leak mass | IMPLEMENTED | redistributed; sum asserted 1.0 |
| Betweenness, deterministic, exploits components, no heavy dependency | IMPLEMENTED | Brandes per component, numpy only |
| Louvain: terminates, deterministic, improves modularity, handles disconnected and isolated nodes | IMPLEMENTED | all five asserted separately |
| Network Risk Score = 100·(0.45·nDebtRank + 0.35·nFwdPageRank + 0.20·nBetweenness) | IMPLEMENTED | weights are constants, components stored not discarded, flat population normalises to 0 rather than to the top |
| NRS banner: RANKING / NOT PD / NOT A RATING / NOT IFRS 9 STAGE / NOT ECL | IMPLEMENTED | `NRS_LABEL` on every payload and on every row of `corporate_connected_groups`, asserted phrase by phrase |
| SIMILAR_TO via Jaccard on shared evidence, dotted, distinct, "HIDDEN RELATIONSHIP CANDIDATE" | IMPLEMENTED | found through an inverted index rather than 7.2M pairwise comparisons |
| SIMILAR_TO never creates control, UBO or group membership | IMPLEMENTED | three explicit `False` flags on the edge, asserted |
| Graph confidence with weakest evidence path | IMPLEMENTED | `WEAKEST_EVIDENCE_ON_PATH`; the tests assert it is not the mean and not the product, and that length alone does not reduce it |

## Phase 2.17 — Graph data quality

| Requirement | Status | Evidence |
|---|---|---|
| ≥14 checks | IMPLEMENTED | 15: GQ-01 … GQ-15 |
| PASS / FLAG / REJECT | IMPLEMENTED | `STATUSES` |
| **REJECT blocks the dependent computation** | IMPLEMENTED | `QualityReport.blocked()`, closed over `DEPENDS_ON` to a fixed point so a two-step chain cannot leave the far end computing on blocked input |
| Rejects are scoped | IMPLEMENTED | 4 impossible registers out of 4,179 block effective ownership for the 12 entities in their contaminated components and for nobody else. A gate that blanks the whole book over four rows gets switched off |
| The register is persisted | IMPLEMENTED | `corporate_graph_dq`, one row per check per quarter |
| A check that raises does not take the gate down | IMPLEMENTED | becomes a REJECT naming its own failure; the other checks still run |

Current verdict on the real book as at Q2 2026: **1 REJECT** (GQ-01, the two
deliberately planted defective register groups, 12 entities), **2 FLAG**
(GQ-11 evidence recency 64%, GQ-14 one component holds 95% of borrowers),
**12 PASS**.

## Phase 2.18 — Borrower 360 graph summary

| Requirement | Status | Evidence |
|---|---|---|
| 20 graph fields declared with lineage | IMPLEMENTED | |
| Populated with validated values | IMPLEMENTED (was NOT_IMPLEMENTED) | **all 24 graph and graph-dependent fields carry values for a derived quarter**; the census asserts none reads `NOT COMPUTED` |
| `NOT_AVAILABLE` / `NOT_APPLICABLE` / `DATA_QUALITY_BLOCKED` vocabulary | IMPLEMENTED (was a single sentinel) | all three appear, and a test fails if any one of them never does — a distinction nothing exercises is a distinction not being made |
| `corporate_connected_groups` produced | IMPLEMENTED | 3,253 borrower-quarter rows for Q2 2026, 36 columns |
| `corporate_graph_dq` produced | IMPLEMENTED | 15 issues per quarter |
| `corporate_limits.group_utilisation_pct` | IMPLEMENTED (was `NOT YET COMPUTED`) | filled for derived quarters only, never back-filled into a quarter the derivation did not cover. 157 groups now read INVESTIGATE against the group limit — a finding only the graph could produce |
| **Blank strings treated as measurements** | IMPLEMENTED (was a latent defect) | `group_id` and `group_name` were written as `""` by the customer master and the sentinel filler tested only for null, so those two fields left the assembler blank — the exact "blank reads as a measurement" failure the module exists to prevent |

Timings, full book, one quarter: ownership graph 4.3s, effective ownership
2.6s, control closure 2.5s, connected groups 0.2s, DebtRank all-seeds 4.0s,
centrality 1.2s, NRS 1.3s, quality gate 1.0s — **18s per quarter**, about five
minutes for all sixteen.

## Phase 3 — Borrower 360 user experience

| Requirement | Status | Evidence |
|---|---|---|
| Borrower search by 12 attributes | IMPLEMENTED (service layer) | `search.SEARCHABLE` |
| Ambiguous names show candidates, never silently chosen | IMPLEMENTED | `ambiguous` / `resolved`, tested |
| Missing cohort member disclosed | IMPLEMENTED | `not_found` plus an explanation, tested |
| Borrower 360 screen and its 13 tabs | IMPLEMENTED | `frontend/src/app/borrower-360/page.tsx`; `service.TAB_KEYS` has 13; browser acceptance at 4 viewports |
| Corporate API router | IMPLEMENTED | `backend/api/routers/corporate.py`, 9 routes; `test_corporate_api.py` (39) |
| Borrower 360 / Graph permissions | IMPLEMENTED | 4 named permissions; every route called as each of 4 roles with the status read |
| Network views (11 named) | IMPLEMENTED | `service.NETWORK_VIEWS`, server-side ego expansion with exact omitted counts |
| Group & Connectedness shown as six separate groupings | IMPLEMENTED | `service.GROUP_CONCEPTS` — six cards, each with Answers / Basis / **Is NOT** |
| DOWNLOAD BORROWER 360 PACK | IMPLEMENTED | `backend/corporate/pack.py`, 18 sheets (COVER + 17); sentinels survive the export |
| Pinning, saved cohorts, Data Builder graph-domain viewer | NOT_IMPLEMENTED | the remaining Borrower 360 interactions |
| Data Builder graph domains expose scope/grain/keys/lineage/authority | IMPLEMENTED | 20 datasets registered; 7 declared relationships including 2 FORBIDDEN |

## Phases 4–6 — Ask, Brain, agentic

| Requirement | Status |
|---|---|
| Corporate datasets reachable by Ask without corrupting credit-book retrieval | IMPLEMENTED — `portfolio_scope` separation, 16 tests |
| Corporate teaching vocabulary | IMPLEMENTED — 187 measures, 121 dimensions |
| 16 governed graph questions answerable | IMPLEMENTED — 4 certified analyses; 12 named questions route by deterministic overlap, `TestTheTwelveQuestionsRoute` |
| Brain concepts for graph semantics | IMPLEMENTED — 22 Concepts (62 total), each resolving to a governed field |
| Semantic contracts for the graph measures | IMPLEMENTED — 8 contracts (45 total), each stating a boundary and forbidding an operation |
| 10 Investigation Blueprints | IMPLEMENTED — 29 blueprints / 29 families, all graph ones usable |
| Development coverage for graph topics | IMPLEMENTED — 17 families, 578 cases, no family short |
| Sealed-holdout coverage for graph topics | IMPLEMENTED — 328 cases, isolation proved and proved able to fail |
| A specialist that owns the graph | IMPLEMENTED — `relationship_graph`, scoped to 3 data domains |

---

## Summary

Counted from the status column of every table row in this document, not
from memory:

| Status | Count | Previous revision | First revision |
|---|---:|---:|---:|
| IMPLEMENTED | 74 | 51 | 21 |
| PARTIAL | 3 | 3 | 6 |
| BROKEN | 0 | 0 | 1 |
| NOT_IMPLEMENTED | 4 | 8 | 34 |
| NOT_VERIFIED | 0 | 1 | 1 |

The four remaining NOT_IMPLEMENTED rows are `source_record_id` on observed
edges, `portfolio_scope` on the edge row (it is on the dataset), a validation
status on observed edges (the DERIVED products carry one), and the remaining
Borrower 360 interactions — pinning, saved cohorts and the Data Builder
graph-domain viewer. Each is a statement about work that does not exist,
not about work that was not checked.

**What the derived layer now does:** integrated ownership with a per-component
refusal, control closure that is binary and transitive and refuses to be
confused with proportional ownership, connected-counterparty candidate groups
built from control rather than from raw shareholdings, eight interdependence
predicates that record their own test, five families of network measure with
their disclaimers attached, fifteen quality checks that actually block, and
twenty Borrower 360 fields that say which kind of absent they are when they
are absent.

**Three real defects the new checks found, all fixed:**

1. Facility nodes were never emitted, so 1,303 of 2,274 guarantee edges
   pointed at a node that did not exist. Invisible to every edge-first query.
2. `FUNDED_BY` drew funding channels with replacement, producing duplicate
   assertions that double-count wherever funding edges are aggregated.
3. `group_id` and `group_name` left the snapshot as blank strings rather than
   sentinels, because the filler tested for null and the customer master
   writes `""`.

**What remains is the user-facing surface** — the Borrower 360 screen, its
tabs and network views, the corporate API router and its permissions, the
export pack, and the Ask/Brain integration over the graph.
