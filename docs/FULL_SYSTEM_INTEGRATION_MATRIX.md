# Full-system integration matrix

Where the corporate relationship graph meets everything else, and what each
join actually does. A cell reads OK only where something was run.

**Status: `LOCAL_RUNTIME_VERIFICATION_REQUIRED`** — see
`FULL_CREDITPROBE_FUNCTIONAL_VERIFICATION.md` for why.

---

## The graph against every other subsystem

| Consumer | How it reaches the graph | Verified | Result |
|---|---|---|---|
| Data Builder catalogue | 22 datasets registered with grain, keys, period field, authority and `portfolio_scope`; 7 relationships including 2 FORBIDDEN | build + `test_scope_separation` | OK |
| Governed authority layer | `corporate_connected_group` and `corporate_graph_quality` are governed purposes served by exactly one dataset each | `test_each_declares_a_governed_purpose_that_exists` | OK |
| Engine registry | 4 certified analyses over the derived graph, each with contract, parameters, outputs and validation rules | `test_graph_analyses.py` (24) | OK |
| Analysis runner | every graph analysis executes through `run_analysis` and produces a multi-kind Trace | `test_it_produces_a_trace` | OK |
| Trace | DOMAIN → DATASET → VARIABLES → FILTER → AGGREGATION → CALCULATION nodes recorded per analysis | same | OK |
| Ask routing | 12 named graph questions select the right certified analysis by deterministic overlap | `TestTheTwelveQuestionsRoute` | OK |
| Retrieval / scope | corporate questions lead with a BORROWER_360 dataset; retail and credit-book questions never do | `TestThreeBooksAfterTheGraph` | OK |
| Teaching vocabulary | 18 measures and 12 dimensions added; all 46 governed datasets have at least one of each | import-time `_check()` | OK |
| Borrower 360 API | 8 routes, 4 permissions, every route called as each of 4 roles | `test_corporate_api.py` (39) | OK |
| Borrower 360 screen | 13 tabs, 11 network views, 6 group concepts, server-side ego expansion | browser acceptance, route crawl | OK |
| Export | 18-sheet pack; sentinels survive; people sheets present-but-withheld | `TestThePack` (7) | OK |
| Display contract | every user-facing number through the contract; one allowlisted diagnostic with its reason | `check_decimals.py` | OK |
| Permissions catalogue | 4 named permissions registered with roles and descriptions | `test_the_named_permissions_are_registered` | OK |
| Feature matrix | `/borrower-360` enumerated from the filesystem with a curated expected behaviour and its limitations | `test_feature_matrix.py` | OK |
| Migrations | single head `0029`; no new migration needed — the graph datasets are lake artefacts, not tables | `alembic heads` | OK |
| AI Brain concepts | — | — | **NOT BUILT** |
| Investigation Blueprints | — | — | **NOT BUILT** |
| Graph teaching cases (dev + sealed holdout) | — | — | **NOT BUILT** |
| Docker | — | — | **NOT VERIFIED IN CLAUDE SANDBOX** |
| Live AI | — | — | **NOT VERIFIED** — forbidden here |

## The derivation's own dependency chain

Each stage consumes the one above and refuses when its input was rejected.

```
observed edges (bitemporal, as-of on three clauses)
        │
        ├─ graph data quality ── 15 checks ── REJECT blocks what depends on it
        │                                     scoped per entity where the
        │                                     defect is per entity
        ▼
ownership matrix A ──► effective ownership Ã = A(I−A)⁻¹   [per component]
        │                     │
        │                     ├─ UBO ≥ 25%
        │                     └─ ownership chains, depth 6
        │
        └─► control closure (VOTING, binary, transitive)
                      │
                      ├─ CONTROLS_EFFECTIVELY
                      └─► connected groups ──◄── validated interdependence
                                    │                (8 predicates)
                                    └─► group exposure ─► group limit
exposure network + guarantees
        │
        ├─► DebtRank (all seeds)  ─┐
        ├─► PageRank fwd / rev     ├─► Network Risk Score
        └─► betweenness           ─┘
        └─► Louvain communities
```

`DEPENDS_ON` closes the block set to a fixed point, so a REJECT reaching
DebtRank also reaches the Network Risk Score built from it.

## What each measure is NOT

Carried in code, in the API payload, on the screen and in the export — not
only in this document.

| Measure | What it is not |
|---|---|
| Network Risk Score | not a probability, not a PD, not a rating, not an IFRS 9 stage, not an ECL |
| DebtRank | not an ECL, not a capital methodology, not a regulatory measure |
| Connected group | not a determination — a candidate for assessment |
| Control group | not proportional ownership |
| Effective ownership group | not control |
| Network community | not a group in any legal, economic or regulatory sense |
| SIMILAR_TO | not a relationship — creates no control, no UBO, no group membership |
| Group / single-name limit | UNVERIFIED REGULATORY PARAMETER |
| Synthetic performance | not empirical validation; `origin = SYNTHETIC_DEMO` on every row |

## Entity-resolution error propagation

B54's sixth caveat, made concrete. Entity resolution decides which source
records are one legal entity. A wrong merge or a missed one changes the
ownership matrix, which changes every derived layer above it. The chain is:

`corporate_entity_resolution` → node identity → ownership matrix → effective
ownership → control closure → connected groups → group exposure → group
limit status.

The system's defence is that fuzzy matches are **never auto-acceptable**
(`resolution.METHOD`), source records are never destructively merged, and
`graph_confidence` reports the weakest evidence on the path so a group formed
on a doubtful match says so.
