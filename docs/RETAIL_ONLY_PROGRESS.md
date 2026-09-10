# Retail-only conversion — progress log

Contract: `docs/RETAIL_ONLY_MASTER_SPEC.md` (saved byte-identical to the
supplied specification, md5 `5d3e34abcabb9456d17d9a3ccdf4d3f2`).

Status key: DONE / IN PROGRESS / BLOCKED / NOT RUN.

| Phase | Scope | Status |
|---|---|---|
| 0 | Source verification, branch, isolation | DONE |
| 1 | Baseline inventory, canonical schema, taxonomy, registries | IN PROGRESS |
| 2 | Longitudinal generator, 25-month publication, score reconstruction | NOT STARTED |
| 3 | Retail ECL/scenario engine and numerical fixtures | NOT STARTED |
| 4 | DataBuilder/Cockpit domain routing and blueprints | NOT STARTED |
| 5 | Retail EWS | NOT STARTED |
| 6 | What-If retail dependencies and baseline parity | NOT STARTED |
| 7 | Retail-only sweep, reports, performance, security | NOT STARTED |
| 8 | Regression, browser UAT, handover | NOT STARTED |

## Phase 0 — DONE

- Read the full 1377-line specification; saved to `docs/RETAIL_ONLY_MASTER_SPEC.md`.
- Established that no WHATIF_5318/5308 installation exists in this execution
  environment; recorded the exact missing evidence rather than guessing a base.
- Identified the proven What-If lineage and based the retail branch on
  `80e74a4e` (contains `recovered-sep8-whatif` `0558f267`).
- Wrote `docs/RETAIL_SOURCE_PROVENANCE.md`.

## Assumptions register

| # | Assumption | Why | How to overturn |
|---|---|---|---|
| A1 | Base = tip of the What-If lineage, not the recovery tag | Tip contains the tag; choosing the tag would discard 12 What-If commits | `git rebase --onto 0558f267 80e74a4e claude/funny-dirac-6n8f0o` |
| A2 | Retail runtime ports 5328 (frontend) / 8328 (backend) | Spec §1.3 suggestion; no port is in use in this container | Change `.env.retail` |
| A3 | `demo_as_of_month` = 2026-08 giving 2024-08..2026-08 | Spec §4.2 | `config/retail_demo_config.json` |
