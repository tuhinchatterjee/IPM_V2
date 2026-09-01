# Phase-start snapshot — final consolidation and client-readiness phase

This file is written **before** any behaviour changes in this phase. It is the
fixed point the final report is measured against. Nothing in it is edited
later: if a number here turns out to have been wrong, the correction goes in
the final report with the reason, and this file stays as it was recorded.

Recorded 2026-08-29, on branch `claude/vigilant-darwin-eohyi1`.

---

## 1. Repository state (§11)

| Question | Answer |
| --- | --- |
| Current branch | `claude/vigilant-darwin-eohyi1` |
| Exact HEAD | `e967c6aa08be4c39ae07b99624f7bf3ba15b52d7` |
| Is HEAD exactly `e967c6a`? | **Yes** — the expected starting commit, unchanged |
| Local / remote SHA match | **Yes** — `origin/claude/vigilant-darwin-eohyi1` is the same SHA |
| Clean working tree | **Yes** — `git status --porcelain` is empty |
| Alembic head | **0021** (`0021_assurance_records`), the expected head |

The six commits between the Part A–F master report (`a89bbfc`) and here are the
agentic hardening phase: `c5a881f`, `204331b`, `451d9fa`, `f8b38d4`, `dc34e69`,
`e967c6a`.

## 2. Test counts (§11)

Measured, not remembered.

| Suite | Command | Result |
| --- | --- | --- |
| Backend | `.venv/bin/python -m pytest` | **3,851 collected · 3,835 passed · 16 skipped · 0 failed** (252s) |
| Frontend | `npm test` (`node --test`) | **254 tests · 28 suites · 254 pass · 0 fail** |

The 16 skips are the pre-existing environment-gated tests (no Docker daemon, no
provider key); none of them are skipped because they would fail.

## 3. Schema versions (§11)

| Area | Constant | Value |
| --- | --- | --- |
| Assurance | `backend.assurance.record.RECORD_VERSION` | `1.0.0` |
| Teaching | `backend.teaching.schema.SCHEMA_VERSION` | `1.0.0` |
| Feedback (Part E) | `backend.feedback.schema.FEEDBACK_VERSION` | `1.0.0` |
| Feedback components | `backend.feedback.components.COMPONENT_VERSION` | `1.0.0` |
| Agentic proof | `backend.proof.probe.PROBE_VERSION` | `1.0.0` |
| Regulatory | — | **none — no regulatory schema exists** |

There is no `backend/regulatory` package, no regulatory model, no regulatory
migration and no regulatory version constant. That is recorded here as a fact
rather than as a gap to be discovered later: **Part G's regulatory half has not
been built.**

## 4. Known open defects (§11)

**Eight** entries in `docs/DEFECTS_HARDENING.md` are not marked FIXED. Six of
them are the ones the hardening report carried forward; two more (D4, D5) were
recorded OPEN in the defect log but described in the hardening report as
accepted behaviour rather than as defects, and are re-counted here honestly.

| ID | Severity | What is wrong |
| --- | --- | --- |
| D4 | medium | The two broad investigations execute no analysis at all |
| D5 | low | A metadata answer reports no datasets |
| D6 | medium | Officer selection is one level high on the two-domain case |
| D7 | medium | Invariants pass on none of the executed analyses (they are compiled but not recorded as passed) |
| D15 | **high (Tier 1)** | A portfolio question returns account-grain rows; contained by the invariant, not corrected |
| D17 | low | Table columns are not in the governed rank order |
| D19 | medium | A coordinated review reports nothing about what its specialists read |
| D20 | medium | A coordinated review registers no evidence facts |
| D21 | medium | Nine of the fifteen review-pack risk classes have no teaching cases |

D8, D9 and D10 are recorded OPEN in the defect log but were the subject of the
hardening work itself and are closed by it (coverage went 9.5% → 93.3%,
mandatory unresolved 356 → 0, Project parity proven by six Project probes).
They are re-verified in this phase rather than assumed.

## 5. Teaching-case counts, by source and status (§11, §6)

Measured against the seeded library, after re-seeding following the test run
(the suite truncates `teaching_cases`).

| Dimension | Value |
| --- | --- |
| **Total cases** | **2,453** |
| — authored by blueprint (system-generated) | 1,287 |
| — migrated from historical evaluation content | 1,083 |
| — derived from a contract | 83 |
| — imported by a human from a reviewed corpus | **0** |
| — generated from a regulatory circular | **0** |
| **AUTO_VALIDATED** | **2,453** |
| **SYSTEM_REFERENCE_VALIDATED** | **0** |
| **HUMAN_REVIEWED** | **0** |
| **HUMAN_APPROVED** | **0** |
| **Production-retrievable** | **0** |
| Sealed holdout (isolated in the Intelligence Factory) | not counted here — it is deliberately not reachable from the backend |

The honest sentence, which §6 requires and which this phase must not weaken:

> 2,453 system-generated / auto-validated development cases; 0 human-approved
> production teaching cases.

Production retrieval is gated on `teaching.status.RETRIEVABLE`, which admits
`APPROVED` and — only when `system_validated_enabled` is set —
`SYSTEM_VALIDATED`. Neither status has a single case in it, so **no teaching
case reaches production retrieval today.**

## 6. Measured agentic and Assurance state (§1, §2)

From `docs/POST_TUNING_AGENTIC.md`, the 15-probe proof set at `e967c6a`:

| Metric | Value |
| --- | --- |
| Probes completed / raised | 15 / 0 |
| Officer selection accuracy | 83.3% (of 6 scored) |
| Outcome accuracy (answer / clarify / refuse) | 100.0% |
| Mean Assurance coverage | 93.3% |
| Records that received a score | 15 |
| Records UNVERIFIED / FAILED | 0 / 0 |
| Critical failures | 0 |
| Critical checks with no signal | 0 |
| Mandatory checks unresolved | 0 |
| Officer-badge verdict | **MATERIAL** (2 material, 0 decorative, monotonic) |
| Coverage Map | 95 mapped · 72 wired (75.8%) · 18 planned · 5 out of band · **17/17 critical wired** |
| Browser acceptance | 231 / 231 (11 screens × 3 viewports × 7 checks) |

## 7. What is not true today, stated plainly

- **Operational Assurance is not independent answer accuracy.** They are
  separate numbers on separate scales and the product says so.
- **99.99% accepted-answer precision is not demonstrated.** No statistically
  powered measurement of it exists.
- **No human has approved any teaching case.**
- **No regulatory corpus exists**, and no circular has been ingested.
- **No user Q&A corpus has been imported.**
- **Docker build and health are unverified** in this sandbox — the daemon is
  unavailable. `docker compose config -q` is valid; nothing beyond that is
  claimed.
- **No live Anthropic call has been made and no credits consumed.** Every probe
  runs inside `assert_no_provider_calls`, which replaces every provider entry
  point with something that raises.

## 8. What this phase intends to change

In the order the brief gives them: close the open defects (§3); permanently fix
the grain defect D15 (§4); build Part G — regulatory knowledge and the human
teaching corpus (§5); make every question a Learning Observation and every
answer feedback-collectable (§7–§12); build the governed learning pipeline,
review workbench, Replay Lab, local auxiliary models and Learning Releases
(§13–§24); re-run the full regression, browser acceptance and quality gates
(§40–§48); and report all of it against the numbers above.

Nothing in §8 is a claim about what was achieved. The final report is where the
achieved state is recorded, and it will be measured the same way this was.
