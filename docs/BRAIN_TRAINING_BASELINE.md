# Brain training — frozen baseline

**Written before any tuning in this phase. Never regenerated. Never
overwritten.** Everything the Brain training claims to have improved is
measured against what is recorded here, and a number that appears here and
nowhere else is a number that did not move.

Taken: 2026-08-29, at commit `62517522d729bda6272e17128ff03b3cfa416f3f`.

---

## 1. Repository and build

| | |
|---|---|
| Branch | `claude/vigilant-darwin-eohyi1` |
| HEAD | `62517522d729bda6272e17128ff03b3cfa416f3f` |
| Expected starting commit | `6251752` |
| Match | **exact** — HEAD is the expected release candidate |
| `origin/…` | identical |
| Working tree | **clean** |
| Alembic head | **0023**, current at head |

## 2. Tests

| | |
|---|---|
| Backend collected | **4,106** |
| Frontend | **265 passed, 0 failed** |

## 3. Schema versions

| Component | Version |
|---|---|
| Teaching review pack | 1.0.0 |
| Feedback event | 1.0.0 |
| Learning observation | 1.0.0 |
| Candidate learning case | 1.0.0 |
| Learning release | 1.0.0 |
| Replay | 1.0.0 |
| Local auxiliary models | 1.0.0 |
| Raw-feedback guard | 1.0.0 |
| Regulatory schema | 1.0.0 |
| Regulatory intent | 1.0.0 |
| Demo Mode | 1.0.0 |
| Demo workspace | 1.0.0 |
| Demo questions | 1.0.0 |
| Demo Safe Mode | 1.0.0 |
| Feature proof matrix | 1.0.0 |
| Live verification | 1.0 |

**Brain schema: does not exist at baseline.** There is no Brain Pack, no
Learning Bundle, no installation identity, no Brain Release and no component
metric series. This phase creates all of them, so their baseline is *absent*
rather than zero.

## 4. Corpus at baseline

**Teaching library: 2,525 cases.**

| Review status | Count |
|---|---|
| `AUTO_VALIDATED` | 2,469 |
| `SME_REVIEW_REQUIRED` | 40 |
| `DRAFT` | 16 |
| **`HUMAN_APPROVED`** | **0** |
| **Production-retrievable** | **0** |

| Authoring method | Count |
|---|---|
| `BLUEPRINT` | 1,359 |
| `MIGRATED` | 1,083 |
| `DERIVED_FROM_CONTRACT` | 83 |

**There is no canonical training corpus at baseline in the sense this phase
requires.** The teaching library is a retrieval corpus of question/answer
structure. It carries no `expected_officer_level`, no `expected_agents`, no
`expected_task_DAG_properties`, no `independent_reference_spec` and no
`case_family` in the sense §3 and §5 define. The count of canonical cases
under the §5 contract is therefore **0**.

**Sealed holdout: the Intelligence Factory holdout exists** and is isolated
factory→backend only. It is not a §8 canonical holdout under the new contract;
that count is likewise **0** at baseline.

**Critical safety suite under §9: 0 cases.** Individual safety properties are
asserted across `tests/proof/test_safety.py` and elsewhere, but there is no
single suite with the 23 named classes and a zero-tolerance gate.

## 5. Learning and Brain state

Every table is empty:

| Table | Rows |
|---|---|
| Learning observations | 0 |
| Feedback events | 0 |
| Candidate learning cases | 0 |
| Learning releases | 0 |
| Learning release activations | 0 |
| Local training runs | 0 |
| Replay runs | 0 |
| Regulatory releases | 0 |

**No Brain Release exists.** No installation identity exists. Nothing has been
activated, so there is nothing to roll back to and no lift has ever been
measured on any installation.

## 6. Agentic and assurance measurements

From `docs/post_final_agentic.json`, 15 probes, **no provider call**:

| Metric | Baseline |
|---|---|
| Probes completed | 15 of 15, 0 raised |
| Officer selection accuracy | **100.0%** (6 scored) |
| Outcome accuracy | **100.0%** (9 scored) |
| Unnecessary specialists | **0** |
| Missed specialists | **0** |
| Mean specialists per request | 0.67 |
| Mean tasks per request | 0.67 |
| Mean model-call estimate | 0.0 |
| Mean latency | 187 ms |
| p95 latency | 807 ms |
| Requests that executed an analysis | 33.3% |
| Invariants passed, of executed | **100.0%** |
| Grounded | **not measured** (grounding did not run on these probes) |
| Mean assurance coverage | 93.4% |
| Records scored / UNVERIFIED / FAILED | 15 / 0 / 0 |
| Critical failures | **0** |
| Critical checks with no signal | **0** |
| Mandatory checks unresolved | **0** |
| Officer-ladder verdict | MATERIAL, 0 decorative, monotonic |

**Caveat that matters.** Officer accuracy is 100% over **six scored probes**.
Six is a small number and this phase must not present it as though it were
six hundred. The whole reason for building 1,200 canonical cases is that the
current evidence base cannot distinguish a good router from a lucky one.

## 7. Component accuracy at baseline

Measured where a measurement exists; recorded as NOT MEASURED where none does.
Nothing here is estimated.

| Component | Baseline | How |
|---|---|---|
| Capability / intent accuracy | NOT MEASURED | no per-component corpus |
| Conversation-action accuracy | NOT MEASURED | " |
| Multi-question decomposition | **NOT BUILT** | no objective decomposition exists |
| Objective coverage | NOT MEASURED | " |
| Officer accuracy | 100% (n=6) | agentic probes |
| Specialist selection precision | 100% (0 unnecessary, 0 missed, n=15) | agentic probes |
| Unnecessary-agent rate | 0.0 | agentic probes |
| Dataset selection | NOT MEASURED | asserted per-probe, not scored |
| Relationship selection | NOT MEASURED | — |
| Period / grain / population | NOT MEASURED as a rate | grain contract asserted in tests |
| Tool / method selection | NOT MEASURED | — |
| Plan validity | NOT MEASURED as a rate | IR validator enforces it per run |
| Deterministic result correctness | NOT MEASURED as a rate | invariants 100% of executed |
| Grounding | NOT MEASURED | did not run on these probes |
| Abstention correctness | 100% (n=9 outcomes) | question set + probes |
| Project-scope accuracy | asserted, not scored | parity tests |
| Regulatory retrieval / citation | NOT MEASURED | no active Regulatory Release |
| Answer-quality rubric | NOT MEASURED | needs a live model |
| Follow-up suggestion quality | NOT MEASURED | `follow_up_quality` asserts scope only |
| Prompt / token footprint | NOT MEASURED | — |

## 8. Demonstration readiness at baseline

`docs/DEMO_READINESS_REPORT.md`: **CONDITIONAL GO — REQUIRES LOCAL CHECKS.**

| Evidence | Baseline |
|---|---|
| Browser acceptance | **252 / 252**, 0 failed |
| Route crawl | **88 / 95**, 3 failed, 4 refused as intended |
| Demo question set | **14 / 15**, 0 blocking |
| Feature matrix | 71 features: 41 PROVEN, 23 BACKEND_ONLY, 0 THIN, 4 LIMITED, 3 DEFERRED |

Demo workspace: clean, no test residue. 1 Project, 2 Investigations, 3 saved
Analyses, 5 Risk Cases, 1 workflow item, 1 Lens.

## 9. Demo scope at baseline

| Scope | Routes |
|---|---|
| core | `/`, `/projects`, `/investigations`, `/analyses`, `/studio`, `/data-builder`, `/trace`, `/workflow` |
| optional | `/lenses`, `/early-warning`, `/playbooks`, `/stress` |
| admin | `/agent-operations`, `/ai-studio`, `/users`, `/settings` |
| **hidden** | `/documents` |

## 10. Known limitations carried in

1. **A Viewer is offered Lenses and cannot open one** — every tile executes an
   analysis and executing requires ANALYST.
2. **`/analysis/{id}` logs a console 404** — it requests an Assurance record
   that cannot exist for a bare engine run.
3. **Regulatory knowledge and the teaching-corpus importer have no screen** —
   API only, recorded `BACKEND_ONLY`.
4. The governed **Project Plan** is not built.
5. **Arabic and RTL** are out of scope.
6. **Shadow Mode** is not built.
7. The export download buttons were never exercised by a browser.
8. 23 of 95 assurance subcomponents report `NOT_AVAILABLE`.
9. **99.99% accepted-answer precision is not demonstrated and is
   statistically unproven.**

## 11. What has never been measured in this environment

| | Why |
|---|---|
| Any live-model metric | No key; live calls forbidden here |
| The Docker stack running | No daemon |
| A browser file download | The sandbox browser cannot accept one |
| PowerShell executed on Windows | Parsed and policy-checked only |

---

## The honest summary of this baseline

CreditProbe's deterministic behaviour is well evidenced. Its **intelligence
layer is barely evidenced at all**: officer accuracy rests on six scored
probes, most component accuracies have never been measured, multi-question
decomposition does not exist, and there is no Brain, no portability and no
lift measurement of any kind.

That is the starting point, and every improvement claimed in this phase is
measured from it.
