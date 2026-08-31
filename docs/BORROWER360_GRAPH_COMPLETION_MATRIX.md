# Borrower 360 / Corporate Graph — completion matrix

**Verified at** `d7c910f`, branch `claude/vigilant-darwin-eohyi1`, working tree clean,
local and remote identical (0 ahead / 0 behind), Alembic single head `0029`.

Nothing here is inferred from a filename. Every IMPLEMENTED row was confirmed by
running the code and reading what it produced; every NOT_IMPLEMENTED row was
confirmed by searching for the symbol and finding nothing that constructs it.

## How the checkpoint was verified

| Check | Result |
|---|---|
| `git rev-parse HEAD` | `d7c910f96f750dc131056a3290ac286280f0411f` |
| Commits since `d7c910f` | none |
| Working tree | clean |
| `HEAD` vs `origin/claude/vigilant-darwin-eohyi1` | identical |
| `alembic heads` | `0029` (single head) |
| `alembic current` | `0029` — database is at head |
| Migration files | 29 |
| Smoke: corporate + scorecard + Data Builder + teaching + Brain | 965 tests, exit 0 |

Statuses used: **IMPLEMENTED**, **PARTIAL**, **NOT_IMPLEMENTED**, **BROKEN**,
**NOT_VERIFIED**.

---

## Phase 2.1 — Observed vs derived

| Requirement | Status | Evidence |
|---|---|---|
| 12 observed edge types defined | IMPLEMENTED | `graphdata.OBSERVED_EDGE_TYPES` has all 12 |
| Observed edges actually generated | PARTIAL | 11 of 12 present in data: OWNS 7,298; DIRECTOR_OF 16,738; SUPPLIES_TO 7,110; FUNDED_BY 6,800; IN_SECTOR 3,800; REGISTERED_AT 3,800; COVERS 1,459; HOLDS 1,330; PROVIDES 1,096; LENT_TO 410; EXPOSED_TO 380. **`CONTROLS` is declared but nothing constructs it** |
| `valid_from`, `valid_to`, `recorded_at`, `source`, `confidence` | IMPLEMENTED | present on every observed edge frame |
| `source_record_id` on observed edges | NOT_IMPLEMENTED | column absent from all four edge frames |
| `portfolio_scope` on observed edges | NOT_IMPLEMENTED | present on the *dataset* (B44) but not on the edge row |
| `validation status` on observed edges | NOT_IMPLEMENTED | no such column |
| Derived edge types UBO_OF / CONTROLS_EFFECTIVELY / MEMBER_OF / CONNECTED_TO / SIMILAR_TO | NOT_IMPLEMENTED | no constant, no producer, no dataset |
| Derived edge provenance (`computed_at`, `pipeline_version`, `derivation_method`, `inputs`, `policy_version`, validation status) | NOT_IMPLEMENTED | nothing derived exists to carry it |

## Phase 2.2 — Bitemporal point-in-time

| Requirement | Status | Evidence |
|---|---|---|
| Three-clause as-of predicate | IMPLEMENTED | `graphdata.as_of()`, one implementation, imported everywhere |
| Look-ahead test proves the third clause excludes something | IMPLEMENTED | `test_the_third_clause_actually_excludes_something` compares validity-only against the full predicate and asserts the counts differ — a guard that never fires is untested |
| Recording genuinely lags validity | IMPLEMENTED | median lag > 30 days, max > 365, asserted |
| Derived products reproducible as-of | NOT_APPLICABLE yet | no derived products exist |

## Phase 2.3–2.5 — Ownership mathematics and control

| Requirement | Status |
|---|---|
| `ownership_pct` separate from `voting_pct` | IMPLEMENTED — both columns, divergent in ~9% of holdings, tested in both directions |
| Ownership matrix `A` | NOT_IMPLEMENTED |
| `(I−A)X = A` linear solve | NOT_IMPLEMENTED |
| Spectral radius ρ(A) computed before solve | NOT_IMPLEMENTED |
| `GRAPH_DATA_QUALITY_REJECTED` on ρ(A) ≥ 1 | NOT_IMPLEMENTED |
| Ownership chain explanation, depth 6, cycle exclusion | NOT_IMPLEMENTED |
| Matrix-vs-path disagreement warning | NOT_IMPLEMENTED |
| Binary control graph, SCC condensation, reachability | NOT_IMPLEMENTED |
| `CONTROLS_EFFECTIVELY` | NOT_IMPLEMENTED |

Structure to make this non-trivial **is** present and tested: pyramids (>50
intermediate holdings), cross-holdings (>20 corporate→corporate stakes), and a
largest raw-ownership component under 20% of nodes.

## Phase 2.6–2.8 — Connected counterparties, percolation, interdependence

| Requirement | Status |
|---|---|
| Connected-group formation pipeline (control candidates → WCC → interdependence → merge) | NOT_IMPLEMENTED |
| `criterion_hit` preserved | NOT_IMPLEMENTED |
| Giant-component / percolation regression (raw OWNS WCC vs control WCC) | PARTIAL — the raw-OWNS side exists (`test_the_graph_is_not_one_giant_blob`, largest component < 20%); the control side does not exist to compare against |
| Review threshold for large candidate groups | NOT_IMPLEMENTED |
| Economic-interdependence predicates | NOT_IMPLEMENTED |
| Predicate persistence (threshold, source, effective date, policy version, evidence) | NOT_IMPLEMENTED |
| Supply chain never forms a regulatory group | IMPLEMENTED (as a governance declaration) — `corporate_supply_chain → corporate_connected_groups` is registered FORBIDDEN with B21 as the reason, and a caveat is carried on every supply row |

## Phase 2.9–2.11 — Guarantee, supply, exposure networks

| Requirement | Status | Evidence |
|---|---|---|
| Reified Guarantee nodes; Guarantor→PROVIDES→Guarantee→COVERS→Facility | IMPLEMENTED | 1,096 PROVIDES and 1,459 COVERS over reified nodes; a test asserts at least one guarantee covers more than one facility, so reifying it is doing work |
| Cross / shared / joint-and-several guarantees | IMPLEMENTED | `joint_and_several` set when multiple guarantors |
| **Guarantees respect the build window** | **BROKEN** | `build_guarantees` filters facilities on the module constant `QUARTERS[-1]` rather than the periods actually built. A full build yields 2,555 rows; `build(periods=QUARTERS[:2])` yields **0**, silently. Fix scheduled in Phase 2 |
| SUPPLIES_TO with revenue share, COGS share, validity, source, confidence | PARTIAL | `share_of_supplier_revenue` and `share_of_buyer_cogs` present and asymmetric; `annual_value`, `substitutability`, `product/service` absent |
| Exposure network directed and weighted, u→v = u carries exposure to v | IMPLEMENTED | three claim types kept apart; asserted indirect exposure capped below a booked claim |
| Exposure amount/type/currency/as-of/source/confidence | PARTIAL | amount, instrument, as-of, source, confidence present; **currency absent** |

## Phase 2.12–2.16 — Network analytics

Every row here is NOT_IMPLEMENTED. No DebtRank, PageRank (forward, reverse or
personalised), betweenness, Louvain, Network Risk Score, or SIMILAR_TO exists;
no module computes them and no dataset carries them.

Graph confidence is **PARTIAL**: source confidence is persisted and is a
property of the source rather than a per-edge invention (asserted), but no
derived relationship yet shows a weakest-evidence path.

## Phase 2.17 — Graph data quality

NOT_IMPLEMENTED. The `CORPORATE GRAPH DATA QUALITY` domain is declared and the
`corporate_graph_dq` dataset is named in the domain registry and in 5 lineage
entries, but **no rows are produced** and no check runs. None of the fourteen
required checks exists.

## Phase 2.18 — Borrower 360 graph summary

| Requirement | Status |
|---|---|
| 19 GRAPH SUMMARY fields declared with lineage | IMPLEMENTED |
| Populated with validated values | NOT_IMPLEMENTED — **23 snapshot fields are still `NOT COMPUTED`** |
| Truthful placeholder rather than a manufactured value | IMPLEMENTED | the sentinel is `NOT COMPUTED`, never zero, and `snapshot.summary()` reports how many fields are pending. `corporate_limits.group_utilisation_pct` is null with status `NOT YET COMPUTED` for the same reason |

The vocabulary required by the brief is `NOT_AVAILABLE` / `NOT_APPLICABLE` /
`DATA_QUALITY_BLOCKED`. The current single sentinel is truthful but does not
distinguish those three cases; aligning it is Phase 2 work.

## Phase 3 — Borrower 360 user experience

| Requirement | Status | Evidence |
|---|---|---|
| Borrower search by 12 attributes | IMPLEMENTED (service layer) | `search.SEARCHABLE` covers id, customer number, name, alias, Arabic name, group, segment, sector, rating, Stage, region, watchlist, relationship manager |
| Ambiguous names show candidates, never silently chosen | IMPLEMENTED | `ambiguous` / `resolved` in the result contract, tested |
| Missing cohort member disclosed | IMPLEMENTED | `not_found` list plus an explanation, tested |
| Borrower 360 screen and its 13 tabs | NOT_IMPLEMENTED | no route under `frontend/src/app` for borrower/corporate/graph |
| Corporate API router | NOT_IMPLEMENTED | no router under `backend/api/routers` |
| Borrower 360 / Graph permissions | NOT_IMPLEMENTED | no permission constant exists |
| Network views (11 named) | NOT_IMPLEMENTED |
| Group & Connectedness shown as six separate groupings | NOT_IMPLEMENTED |
| DOWNLOAD BORROWER 360 PACK (17 sheets) | NOT_IMPLEMENTED |
| Data Builder graph domains expose scope/grain/keys/lineage/authority | IMPLEMENTED | 20 datasets registered with grain, keys, period field, authority and `portfolio_scope`; 7 declared relationships including 2 FORBIDDEN |

## Phases 4–6 — Ask, Brain, agentic

| Requirement | Status |
|---|---|
| Corporate datasets reachable by Ask without corrupting credit-book retrieval | IMPLEMENTED — `portfolio_scope` separation, 16 tests |
| Corporate teaching vocabulary (so no governed dataset is unteachable) | IMPLEMENTED — 187 measures, 121 dimensions; every catalogue dataset has at least one of each |
| 16 governed graph questions answerable | NOT_VERIFIED |
| ~33 Brain concepts for graph semantics | NOT_IMPLEMENTED |
| 10 Investigation Blueprints | NOT_IMPLEMENTED |
| Development / holdout coverage for 16 graph topics | NOT_IMPLEMENTED |

---

## Summary

| Status | Count |
|---|---:|
| IMPLEMENTED | 21 |
| PARTIAL | 6 |
| BROKEN | 1 |
| NOT_IMPLEMENTED | 34 |
| NOT_VERIFIED | 1 |

**What is genuinely done:** the observed graph, its bitemporal semantics, the
ownership/voting separation, entity resolution, the snapshot with lineage and
its authority discipline, search, the governed catalogue registration, and the
two-book scope separation.

**The one defect found during verification:** `build_guarantees` reads a module
constant instead of the built window, so a partial build silently produces no
guarantees. It is fixed first in Phase 2.

**What remains is the whole derived layer** — every matrix, closure, grouping
and centrality computation, the data-quality checks that gate them, and every
user-facing surface that would show them.
