# Performance and budgets

Measured in this container, not estimated. Where a figure is an estimate it
says so.

---

## 1. Offline preparation — what the candidate costs to build

Everything below runs **once**, outside any chat turn, and is the whole
reason §7.1 and §11.2 insist on precomputation: a reader asking a
methodology question triggers a `SELECT`, not a refit.

| Step | Command | Measured |
|---|---|---|
| Candidate environment | `python3 -m venv --system-site-packages .venv-whatif` + pip install | ~90s, ~1.1 GB (nvidia-nccl is 351 MB of it) |
| Seed both releases, with sensitivities | `scripts/whatif/seed_candidate.py --domain all` | **36s Corporate, 46s Retail** |
| Fit sensitivities | inside the seed, `sensitivity.build.attach` | **2.3s Corporate**, included above |
| Train both emulators | `scripts/whatif/train_emulator.py --domain all` | **~7 min** (see below) |
| Sensitivity cards | `scripts/whatif/build_sensitivities.py` | rebuilds both books and re-verifies against the published release, ~90s |
| Requirement matrix | `scripts/whatif/build_matrix.py` | <1s |

**Total cold build: about ten minutes.**

### Training, by component

| Book | Component | 12 configs × 3 folds | Best fold WAPE |
|---|---|---|---|
| Corporate | XGBoost | 78s | 0.03039 |
| Corporate | LightGBM | 97s | 0.04281 |
| Corporate | additive spline | 37s | 0.32173 |
| Retail | XGBoost | 135s | 0.07675 |
| Retail | LightGBM | 181s | 0.09733 |
| Retail | additive spline | 121s | 1.81797 |

Corporate is 59,920 rows × 42 features; Retail is 127,936 × 39. Both run at
`n_jobs=2`, which is a deliberate cap: this is a demonstration build, not a
throughput exercise.

### Reproducibility, measured

Both books were trained **twice** with unchanged code. Every fold WAPE, every
gate and every blend weight reproduced to the digit — 0.03039 and 0.07675 on
the second run as on the first. Seeds are fixed per component, every library
is pinned exactly, and the blend weights are solved by enumerating the faces
of the simplex rather than by an iterative optimiser, so no SciPy minor
version enters the answer.

## 2. Release sizes

| | Corporate | Retail |
|---|---|---|
| Rows published | 1,064,654 | ~1,650,000 |
| Relations | 11 | 12 |
| Exposure-periods | 59,920 | 127,936 |
| Term-structure rows | 799,836 | 1,040,040 |
| Sensitivity rows | 60 | 60 |
| Model-metric rows | 86 | 80 |

Smaller than the accepted books on purpose. The candidate exists to carry a
macro panel, a term structure and a trainable target, not to restate the
accepted population.

## 3. Chat-turn cost — what a reader would pay

**Not measured end to end**, because the execution path does not exist
(`KNOWN_LIMITATIONS.md` §1). What can be stated is what each governed step
would cost, from the shapes that are built:

| Operation | Shape | Expected cost |
|---|---|---|
| Read a published sensitivity | one `SELECT` over 60 rows | negligible; one SQL step |
| Read a model card metric | one `SELECT` over 80–86 rows | negligible |
| Read the MEV registry | one `SELECT` over 20 rows | negligible |
| Freeze a cohort | one `SELECT` plus a SHA-256 over the ids | sub-second on 3,000 facilities |
| Delta over a frozen cohort | one row-wise pass in Decimal | ~3,000 rows; sub-second |
| ML inference | two model calls on the cohort's feature frame | milliseconds per thousand rows |
| Exact Shapley, ≤8 groups | 2^n population passes | 256 passes at 8 groups |
| Sampled Shapley, >8 groups | 200 paired permutations | `permutations × 2 × groups` coalition evaluations — 3,600 at 9 groups |

The attribution budget is the one that needs declaring, and it is declared:
`attribution.EXACT_LIMIT = 8`, `PERMUTATIONS = 200`, `SAMPLE_SEED = 20261001`,
with the standard error published per contribution and a `NOT CONVERGED`
verdict above 10% relative error.

## 4. Budgets the candidate does not change

None of the accepted runtime's bounds were touched:

* `execution_submissions = 5` per run. Three methods plus a repair is four,
  so a three-method comparison fits without a sixth tool.
* The run deadline, the spend ceiling and the call ledger are the accepted
  ones. `scenario/` adds no provider call of its own.
* SQL step artifacts still store 100 preview rows
  (`execute_tool.py:767-769`).
* The Python sandbox's limits — memory, CPU, output, `RLIMIT_NPROC 0` — are
  unchanged, and §1's limitation is a consequence of them rather than a
  complaint about them.

## 5. Test suite

| Suite | Count | Time |
|---|---|---|
| What-If (`test_whatif_*.py`) | **785 passed** | 132s |
| Full V4 backend + frontend, flags OFF | **4189 passed, 4 skipped** | 1439s (23m 59s) |
| Accepted browser journeys, real Chromium | **76/76 passed** | ~6 min |

The full regression is the expensive one and it is the one that matters: it
is what proves the three flag-gated protected-core extensions are inert.

## 6. Memory

The training run is the peak. Retail's 127,936 × 39 frame plus a LightGBM
booster sits comfortably under 4 GB; nothing in this build needed a limit
raised. The seed scripts hold one book's frames in memory at a time — about
1.6 million rows for Retail — which is why they run per book rather than
both at once.

---

## The scenario turn, measured through the product

Thirteen of the fourteen journeys on each book take **under six seconds** end to
end, and that figure includes the browser navigating, the page rendering, the
turn settling and the assertions running — not just the engine. Measured in this
container against the candidate releases, with a scripted analyst (so no
provider latency is in these numbers, which is stated rather than hidden).

| Journey | Corporate | Retail | What it does |
|---|---|---|---|
| J01 preview | 3.3s | 4.1s | investigation, then a preview over a frozen cohort |
| J02 confirm and run | 4.4s | 4.3s | the same, then approval and a full Delta run |
| J03 methodology | 2.1s | 2.1s | a `SELECT` over a published sensitivity, no engine |
| J04 every method | 3.8s | 4.0s | Delta + emulator + assumption on one contract |
| J05 assumption | 3.8s | 3.4s | a reader's own figure, labelled as theirs |
| J06 reopen | 5.6s | 5.7s | two approvals, reproducing the same figures |
| J07 cross-book | 3.3s | 3.4s | the other book refused with 409 |
| J08 chart refusal | 4.3s | 4.6s | a form the renderer cannot draw, named |
| J09 export | 4.4s | 4.6s | run, export CSV, reconcile against the chat |
| J10 model status | 3.9s | 3.2s | the emulator's gate verdict |
| J11 unseen category | 2.0s | 2.0s | refused before a cohort is frozen |
| J12 out of range | 2.3s | 2.4s | the bound reported, not clipped |
| J13 cancel | 1.6s | 1.7s | stopped between actions |
| J14 double Run | 5.5s | 5.7s | two approvals, one result |
| **whole suite** | **50.3s** | **51.2s** | 14 journeys, real browser |

**Where the time goes on a scenario turn.** The cohort read is bounded by the
engine and the declared cap (`MAX_COHORT_ROWS = 250_000`); the arithmetic runs in
the worker process under a monotonic guard set to `DEADLINE_SHARE = 0.9` of the
step's own budget, because `_run_step` computes a per-step budget and enforces
none of it — each arm enforces its own, and this arm declares its bounds.

**What is NOT in these numbers:** a provider round trip. A live model would add
its own latency to the action and answer turns, and no live journey has been run
— see row V01 of the requirement matrix.

## Offline explanation documents

| Book | Command | Measured |
|---|---|---|
| Corporate | `build_explanations.py --domain corporate` | 41s, 41,944 development rows, 12 curves |
| Retail | `build_explanations.py --domain retail` | 41s, 88,160 development rows, 12 curves |

Two builds of each are byte-identical. This is why the response relationships
are offline: evaluating the blend over an 11-point grid for every one of 39
features is not work a chat turn may do.

## Artifact verification

| Command | Measured |
|---|---|
| `verify_artifacts.py --domain corporate` | refit 184s, every published hash, weight, gate and metric reproduced |
| `verify_artifacts.py --domain retail` | refit ~4 min, same |

The verification refits from scratch into a temporary directory and compares
component hashes, blend weights, every gate's measured value and verdict, the
seeds, the library versions and the three period splits. Nothing published is
touched, and a mismatch is reported rather than regenerated away.
