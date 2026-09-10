# Retail-only conversion — progress log

Contract: `docs/RETAIL_ONLY_MASTER_SPEC.md`, saved byte-identical to the supplied
specification (md5 `5d3e34abcabb9456d17d9a3ccdf4d3f2`, 1,377 lines).

> **Synthetic Saudi retail demonstration data — not ANB customer data or
> approved models.**

---

## Phases

| Phase | Scope | Status |
|---|---|---|
| 0 | Source verification, branch, isolation | DONE |
| 1 | Baseline inventory, canonical schema, taxonomy, registries | DONE |
| 2 | Longitudinal generator, 25-month publication, score reconstruction | DONE |
| 3 | Retail ECL/scenario engine and numerical fixtures | DONE |
| 4 | Catalogue and domain routing, blueprint catalogue, retail API | DONE |
| 5 | Retail EWS rulebook, alerts, lifecycle | DONE |
| 6 | What-If retail dependencies and baseline parity | DONE |
| 7 | Retail-only sweep, exports, security | DONE |
| 8 | Regression, real-browser UAT, handover | DONE |

## What was built

| Module | Purpose |
|---|---|
| `backend/retail/config.py` | The pinned 25-month chronology and scenario set |
| `backend/retail/taxonomy.py` | Four product families, Saudi subsegments, geography |
| `backend/retail/policy.py` | Versioned synthetic staging, affordability, cutoff and recovery policy |
| `backend/retail/scorecards.py` | The scoring engine and the exact reconstruction identity |
| `backend/retail/models_registry.py` | Eight models; every configured input, bin and coefficient |
| `backend/retail/ecl.py` | Hazard curves, stage horizons, scenario and weighted ECL |
| `backend/retail/generate.py` | The longitudinal simulation and atomic publication |
| `backend/retail/schema.py` | The data dictionary and machine-readable contract |
| `backend/retail/catalogue.py` | One domain, 25 monthly members |
| `backend/retail/guard.py` | Refusal by default for any non-retail target |
| `backend/retail/ews.py` | Twenty retail rules plus two segment rules |
| `backend/retail/whatif.py` | Twelve implemented methodologies, exact baseline parity |
| `backend/retail/movement.py` | The sequential-replacement ECL bridge |
| `backend/retail/monitoring.py` | Discrimination, calibration, stability, insufficient evidence |
| `backend/retail/exports.py` | Formula-injection escaping and non-finite JSON safety |
| `backend/retail/profile.py` | The retail-only product surface and retired identifiers |
| `backend/api/routers/retail.py` | The retail API the screens read |

## Defects found by the gates, and fixed

| Found by | Defect | Fix |
|---|---|---|
| RET-007 | External credit obligations drifted per FACILITY, so one customer with three loans had three different debt burden ratios and three disposable incomes | Obligations moved to customer-level state |
| RET-003 | The guard matched whole path segments, so a directory named `creditprobe_5318` passed the protected-path check | Substring match within each segment |
| RET-018 | The weighted ECL was computed from unrounded scenario values while the published scenario values were rounded, so the identity a reader could check drifted by real riyals across twenty thousand rows | Scenario ECLs rounded first, then weighted |
| RET-025 | The bridge anchored on a recomputed opening rather than the published one, leaving a small unexplained residual | Anchor recomputed against the published opening and closing |
| RET-052 | CSV formula escaping checked for `object` dtype, which pandas 3 no longer uses for strings, so every text cell went out unescaped | Check string dtype as well |
| RET-051 | The frontend read `NEXT_PUBLIC_API_URL`; the launcher set `NEXT_PUBLIC_API_BASE_URL`, so the browser showed "Backend offline" while every API check passed | Launcher corrected; the browser UAT now navigates with `networkidle` so a client-rendered shell cannot pass as a rendered page |
| RET-046 | The navigation still offered "Borrower 360", a corporate module | Repurposed in the same slot to "Customer 360", backed by a real retail endpoint |
| Product mix | Booking the target mix as applications produced a card-heavy book, because a card revolves for years while a two-year personal finance matures inside the window | Application mix measured and inverted from each product's survival and booking rate |
| Default rate | The first calibration produced a 16% twelve-month default rate | Named delinquency constants, tuned to ~3.3% |

## Assumptions register

| # | Assumption | Why | How to overturn |
|---|---|---|---|
| A1 | Base commit is the tip of the What-If lineage, not the recovery tag | The tip contains the tag; the tag would discard twelve later What-If commits | `git rebase --onto 0558f267 80e74a4e claude/funny-dirac-6n8f0o` |
| A2 | Retail ports 5328 / 8328 | Spec §1.3 suggestion; no port is in use in this environment | `.env.retail` and the launcher |
| A3 | `demo_as_of_month` = 2026-08, giving 2024-08 to 2026-08 | Spec §4.2 | `config/retail_demo_config.json`, then rebuild |
| A4 | ~20,000 active facilities in the latest month | Spec §10.1 sizing suggestion | `--facilities` on the build command |
| A5 | Behavioural score is facility-level | Its inputs are facility facts; replicating one customer score across facilities with different behaviour would be less honest | `models_registry.py` subject grain |
| A6 | Lifetime curves capped at 120 months | The discounted tail beyond ten years is immaterial; every row records the horizon it used | `ecl.LIFETIME_HORIZON_CAP_MONTHS` |
| A7 | Playbook, Lenses and Planner seeded examples were not converted | Out of scope for this pass; they are structurally intact and are recorded as remaining work | see the handover |
