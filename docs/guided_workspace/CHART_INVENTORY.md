# CreditProbe chart inventory (P11)

Scope: every analytical chart under `frontend/src`, audited at P11 on branch
`claude/eager-keller-7ue2yk`. A chart shared by several routes is counted once.
Node-link diagrams, icons, status strips and stat tiles are not analytical charts
and are listed at the end.

This inventory is enforced by `frontend/src/lib/viz/chart-inventory.test.ts`
(INV01–INV06). The test fails in any of these cases:
- Recharts spreads beyond the legacy modules below.
- Another chart library appears.
- Plotly is loaded outside the one wrapper.
- A Plotly chart bypasses the governed frame (other than the two sparkline files).
- A file that draws a chart is not named in this document.

| Renderer | Count | Decision |
|---|---|---|
| Plotly (`PlotlyChart` / `ChartCard`) | 32 | Native to the shared contract |
| Recharts | 12 | Legacy. Not applicable while the guided flag is on (swapped or redirected) |
| Hand SVG | 5 | 4 in protected Cockpit core (deferred, needs approval); 1 legacy lab page |
| CSS / div bars, table heatmaps | 18 | 6 in protected Cockpit core; the rest are legacy pages or meters (not applicable) |
| **Total** | **67** | |

## 1. The shared contract (what "migrated" means)

A Plotly chart is on the contract only if it renders through
`components/viz/plotly-chart.tsx` inside `components/viz/chart-card.tsx`. That frame gives it:

- **Hover:** templates carry the label, value and unit, with the raw governed value where rounding hides it.
- **Legend isolate:** visual only; it refetches nothing and changes no total. `uirevision` keeps it, and any zoom, across re-renders.
- **Zoom, pan and reset:** from the mode bar.
- **Selection:** box/lasso only on population charts (`selectable`).
- **Click semantics** (`onPointClick`):
  - click to filter the shared page state, or to drill into the governed server-side grid;
  - a second click clears.
- **View data:** the exact rows the chart was drawn from.
- **Keyboard:** when the chart has click semantics, Enter or Space on a focused data row does the same as the click (`table.onRowActivate`).
- **Export:**
  - CSV with `# release`, `# fingerprint`, `# period`, `# filters` and `# trace` header lines;
  - PNG and SVG from Plotly.
- **Accessibility:** `role="img"` with the title and subtitle as its label; the tabular fallback is always one click away.
- **Theme and palette:** token-driven theming; the stable driver palette (`lib/viz/palette.ts`, 20-component taxonomy).

Aggregation is always server-side:
- `/grid/group` handles one dimension.
- `/grid/group2` handles two dimensions, is capped at 400 cells, and returns totals so the chart can prove it reconciles.
- Evaluators run over persisted objects.

The browser never receives the book.

## 2. Plotly — on the contract (32)

Interactions key: **F** = click filters shared state, **D** = click drills to the governed grid, **S** = box/lasso population selection, **K** = keyboard row activation, **H** = highlight only, **—** = read-only (trend/composition; hover, legend, zoom, data, export only).

| File | Chart | Route | Interactions |
|---|---|---|---|
| components/whatif/portfolio-explorer.tsx | Booked ECL / EAD by chosen dimension | /what-if | F S |
| components/whatif/portfolio-explorer.tsx | Filtered population by stage | /what-if | F |
| components/whatif/portfolio-explorer.tsx | **Heatmap** sector × rating (corporate) / product × score band (retail), EAD or ECL — VIZ12 | /what-if | F K, reconciles |
| components/whatif/portfolio-explorer.tsx | **Stage migration Sankey** prior → current — VIZ08 | /what-if | F K, reconciles |
| components/whatif/macro-tornado.tsx | **Macro-sensitivity tornado** (MAC07): governed MEV → PD / LGD movements for a standard shock, ranked; signs as fitted; SIGN_REVIEW rows marked | /what-if | — (follows the shared filter; hover carries MEV, series, shock, coefficient, parameter, movement, sign, status, method, window) |
| components/whatif/result-view.tsx | Method comparison (unavailable methods not plotted) — VIZ13 | /what-if/result/[id], run panel, Cockpit thread strip | — |
| components/whatif/result-view.tsx | ECL by stage before/after — VIZ09 | same | — |
| components/whatif/result-view.tsx | Largest contributors | same | — |
| components/whatif/result-view.tsx | Dual-scope ECL bridge waterfall (selected + total, one scale) — VIZ07 | same | H (component highlighted in both scopes and table) |
| components/whatif/result-view.tsx | **Pareto** Delta change by segment + cumulative share — VIZ10 | same | — |
| components/whatif/result-view.tsx | **Change distribution** per exposure — VIZ11 | same | — |
| components/whatif/comparison-view.tsx | Components across compared results | /what-if/compare/[id] | — |
| components/scenarios/preview-panel.tsx | Scope EAD by stage | /scenarios/*, /what-if | — |
| components/scenarios/preview-panel.tsx | Scope EAD by band | /scenarios/*, /what-if | — |
| components/guided/issue-detail.tsx | Issue metric over time | /issues/[id] | — |
| components/guided/issue-detail.tsx | Booked ECL over time | /issues/[id] | — |
| components/guided/issue-detail.tsx | Contributions by dimension | /issues/[id] | D K |
| components/guided/issue-detail.tsx | Stage mix of the affected population | /issues/[id] | D K |
| components/guided/early-warning-v4.tsx | High/critical EWS EAD over time | /early-warning | — |
| components/guided/early-warning-v4.tsx | Why exposures are warned (rules tripped) | /early-warning | F K: the reason cross-filters bands, segments, the grid and every handoff |
| components/guided/requires-attention.tsx | Issue-card sparkline (direct `PlotlyChart`, minimal chrome; the card links to the full chart) | / | — |
| components/lenses/lens-view.tsx | Lens metric trend | /lenses/[id] | F (period) |
| components/lenses/lens-view.tsx | Breakdown / stage mix | /lenses/[id] | F S |
| components/lenses/lens-view.tsx | Top obligors | /lenses/[id] | F |
| components/lenses/lens-view.tsx | Scenario results / alerts / other groups | /lenses/[id] | F |
| components/lenses/lens-view.tsx | KPI sparkline (direct `PlotlyChart`, minimal chrome) | /lenses/[id] | — |
| components/metrics/metric-catalogue.tsx | Metric trend per segment | /metrics | — |
| components/metrics/metric-catalogue.tsx | Metric by dimension | /metrics | D |
| components/monitoring/monitoring-centre.tsx | Alerts by severity | /monitoring | F |
| components/monitoring/monitoring-centre.tsx | Alerts by Lens | /monitoring | F |
| components/llm-exchange/llm-exchange-view.tsx | Request composition by component | /trace/llm-exchange/[runId] | — |
| components/llm-exchange/llm-exchange-view.tsx | Context growth per call | /trace/llm-exchange/[runId] | — |

"Investigate selection / What-If selection / Save cohort / Share" act on the shared filter state:
- **What-If explorer:** the selection bar (`whatif-save-cohort`, `whatif-investigate`, `whatif-apply`, `whatif-share`).
- **Early Warning:** Save / Investigate / Export / What-If, each carrying the reason filter.
- **Lens view:** Investigate / What-If on the drilled population.
- **Issue detail:** Investigate / Save cohort.

## 3. Recharts — legacy, not applicable with the guided flag on (12)

All of these are drawn by `components/analytics/charts.tsx` (the only `recharts` import), through the modules below. None was materially revised in this round.

| File | Charts | Route | Why not migrated |
|---|---|---|---|
| components/analytics/result-view.tsx (+ components/analytics/primary-visual.tsx, components/analytics/chart-frame.tsx) | Stage distribution, portfolio trend (×2), sector concentration, ECL movement, stress impact, generic PrimaryVisual, stage composition (8) | /analysis/[id], /engine-builder/[id], /investigations/[id]; /lenses/[id] only with guided **off** | The accepted Engine Builder / Analysis Library result renderer. With guided on, `/lenses/[id]` renders the Plotly `LensView` instead (`if (!guidedEnabled()) return <LegacyLensPage/>`). Not revised in this round. Migrating it would re-baseline accepted flag-off behaviour, which P13 must show unchanged. |
| app/lenses/cro/page.tsx | Coverage/staging trend, exposure by sector, ECL movement by sector (3) | /lenses/cro | With guided on, the route **redirects** to the governed Plotly Lens `lens-01` (CRO Executive Overview). The legacy page renders only with the flag off. |
| app/stress/page.tsx | Incremental ECL by sector (1) | /stress | With guided on, the route **redirects** to `/what-if` (P5). The legacy page renders only with the flag off. |

## 4. Hand SVG (5)

| File | Chart | Route | Decision |
|---|---|---|---|
| components/cockpit-v4/visuals.tsx | Line / step / area / scatter; histogram; bubble; pie/donut (4) | /cockpit/thread/[id] | **Deferred: protected core.** Drawn by the approved AdvancedCockpit renderer via `components/cockpit-v4/chart-frame.tsx`, which already provides tooltip, zoom, legend, ruler, data table and PNG download (`chart-download.ts`). Migrating it means editing protected files, and the round's rules require explicit approval for protected-core scope. Every chart added to the Cockpit thread in this round is Plotly: the What-If strip and decomposition (`components/guided/thread-whatif.tsx` → `ResultView`), Requires Attention sparklines, and issue detail. |
| app/scorecard-validation/page.tsx | ROC curve with AUC | /scorecard-validation | Not applicable: model-validation lab page, not revised in this round, no population semantics (a curve over thresholds). |

## 5. CSS / div bars and table heatmaps (18)

| File | Chart | Decision |
|---|---|---|
| components/cockpit-v4/visuals.tsx | Bar, stacked bar, grouped bar, combo, waterfall, box, matrix (7 incl. matrix table) | Deferred: protected core (as §4). |
| components/analytics/charts.tsx (MatrixHeatmap), components/analytics/terrain.tsx | Migration matrix; sector × period terrain | Legacy analytics renderer (as §3). |
| components/ask/cockpit-v2.tsx, components/ask/cockpit-agentic.tsx | Answer waterfall; answer bars | Legacy Cockpit (v4 off). |
| app/early-warning/page.tsx | Per-facility factor contributions | Legacy Early Warning (shown only when v4 + guided are not both on; the guided page is Plotly, §2). |
| app/early-warning/lab/page.tsx | Factor weights; decile lift | Model lab, not revised. |
| app/lenses/cro/page.tsx | Migration split strip | Redirected with guided on (§3). |
| components/guided/early-warning-v4.tsx | Severity-band strip per segment card | Not applicable: a 100% composition meter inside a card whose numbers are printed beside it; the card's Investigate / Save / Export / What-If buttons are the interactions. |
| components/data-builder/data-grid.tsx | Column-profile share bars | Not applicable: a profile meter in a column panel. |
| components/system/validation-case.tsx | Component-match meters | Not applicable: a status meter. |

## 6. Not analytical charts (excluded)

- **Node-link diagrams (@xyflow/react):**
  - `components/trace/reasoning-map.tsx`
  - `components/data-builder/relationship-canvas.tsx`
- **Ownership network (hand SVG):** `components/borrower-360/relationship-graph.tsx`.
- **Icons:** `app/documents/[id]/page.tsx` and `components/ui/certified-mark.tsx`.
- **Status strip:** `components/trace/health-map.tsx`.
- **Not charts:** stat tiles, playback controls and calibration text rows.
- **Canvas:** used only by the protected `components/cockpit-v4/chart-download.ts`, to rasterise an SVG for download.

## 7. Evidence

- **Interaction** (browser, `GW-P11-01..04`):
  - hover shows the unit;
  - legend isolate makes 0 API calls, leaves the grid total unchanged, and the series stays hidden across a re-render;
  - drag-zoom, then mode-bar reset;
  - a Sankey flow click filters the grid to that flow's count;
  - a heatmap cell via Enter on its data row filters the grid, and Space clears it;
  - an Early Warning reason click narrows the bands and grid, and the saved cohort carries the reason;
  - CSV has release, fingerprint, period and filters, with rows equal to the drawn cells (95 = 95);
  - PNG downloads;
  - Pareto cumulative share closes at 100%;
  - the distribution accounts for unmoved exposures.
- **Accessibility:**
  - every chart on the What-If screen is `role="img"` with a label of more than 10 characters (4 of 4);
  - critical click interactions have a keyboard equivalent (K above);
  - the data table is always available.
- **Performance** (stub API, synthetic books):

  | Aggregate | Payload | Time |
  |---|---|---|
  | `/grid/group2` sector × rating | 9,150 B | 24–41 ms |
  | Prior × current stage | 604 B | — |
  | Retail product × score band | 2,586 B | 34 ms |
  | Retail stage flow | 381 B | 33 ms |

  The book itself is 2,996 corporate and 6,702 retail exposures and is never shipped. The test pins the payload below 40 kB with no row keys (`test_http_aggregate_is_small_and_row_free`).
- **Inventory lock:** `chart-inventory.test.ts` INV01–INV06.
