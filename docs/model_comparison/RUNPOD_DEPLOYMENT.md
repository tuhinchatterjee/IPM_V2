# RunPod A40 deployment (Model Lab, full Model I/O Trace, suite v2)

**Status: PREPARED.** No benchmark question has been sent to any model.

## Build the bundle (clean checkout of this branch)

```bash
.venv/bin/python scripts/model_lab/runpod/build_bundle.py
```

This writes `artifacts/model_comparison/deployment/` (gitignored):

- `CreditProbe_Model_Lab_RunPod_FullTrace.zip`
- `RUNPOD_BOOTSTRAP.sh`
- `runpod_storage.py` (persistent-volume detection; runs before unpacking)
- `DEPLOYMENT_MANIFEST.json`
- `checksums.sha256`

**How contents are chosen.** The bundle is derived from an audit-hook closure run plus the static imports of every shipped backend package. Bytes come from `HEAD`.

**Excluded:** `.git`, `.venv`, `node_modules`, `.env*`, credentials, model weights, the generated lake (the pod re-seeds it) and runtime state.

**Build checks:**
- a secret scan;
- a git-free protected-manifest check of the extracted bundle.

## Persistent storage (checked first)

The RunPod Global Volume `creditprobe-model-lab` is mounted at `/workspace-global`. `runpod_storage.py` picks the persistent root in this order:

1. `/workspace-global`, when it is a real Global Volume mount;
2. `/workspace`, when it is a real Network Volume;
3. otherwise **`PERSISTENT_STORAGE_NOT_FOUND`** (exit 3). Nothing is written.

**A candidate counts only when all of these hold** (from `/proc/self/mountinfo`):
- it is its own mount point;
- it is not overlay, tmpfs or ramfs;
- it is not on the container root device;
- it is mounted read-write;
- a write + fsync + read-back probe succeeds;
- for `/workspace` only: it is a network filesystem. A local pod volume disk is refused unless the operator sets `CREDITPROBE_ACCEPT_POD_VOLUME=1`.

The container overlay or root disk is never used.

The bootstrap prints `PERSIST_ROOT:`, `filesystem:`, `free_space:` and `persistence_verified: YES`, plus a volume marker that shows when state survived a restart. It then writes `<root>/creditprobe-model-lab/env.sh`. **Source that file in every new shell**; `serve.sh` refuses to run without it.

All state lives under `<root>/creditprobe-model-lab/`:

| Path | Contents | Variable |
|---|---|---|
| `source/` | the unpacked lab, its `.venv` and `node_modules` | `CREDITPROBE_SOURCE_DIR` |
| `runtime/` | lab store; Full Model I/O Traces; comparison exports; oracle artifacts; suite checkpoints and reports; pins; run and vLLM logs | `MODEL_LAB_RUNTIME_DIR` |
| `reference_sets/` | `OPUS_REFERENCE_SET_V1.json` and its answer snapshots | `MODEL_LAB_REFERENCE_SET_DIR` |
| `results/`, `results/screenshots/` | results and browser screenshots | `CREDITPROBE_RESULTS_DIR`, `LAB_EVIDENCE_DIR` |
| `logs/` | bootstrap logs | `CREDITPROBE_LOG_DIR` |
| `cache/models` | vLLM `--download-dir` | `MODEL_CACHE_DIR` |
| `cache/huggingface` | Hugging Face | `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE` |
| `cache/vllm` | vLLM | `VLLM_CACHE_ROOT` |
| `cache/{torch,triton,pip,uv,npm,ms-playwright,xdg}` | tool caches | their standard variables |
| `venvs/vllm` | the vLLM virtualenv | `VLLM_BIN` |

`env.sh` never contains `COCKPIT_ANTHROPIC_API_KEY`.

## On the pod

```bash
cd <directory holding the bundle files> && bash RUNPOD_BOOTSTRAP.sh   # --storage-check: stop after the storage verdict; --skip-probe: defer weight downloads
source /workspace-global/creditprobe-model-lab/env.sh               # or the root it printed
```

1. **Persistent storage.** Detects the root as above and stops with `PERSISTENT_STORAGE_NOT_FOUND` if there is none. It then tees the bootstrap log to `logs/`, checks for the A40 GPU, verifies the checksums, unpacks into `source/`, and re-verifies every file.
2. Installs Python 3.12 (uv), Node 22, `npm ci` and Playwright.
3. Seeds and verifies the synthetic releases.
4. Runs the protected-manifest check (`--check-bundle`).
5. Runs the offline fixture smoke test: trace, neutrality, saved reference, ASSISTED_V1, oracles and suite runner.
6. **Prepares the suite.** It materialises the independent oracle artifacts to `<runtime>/oracles/lab-oracle-suite-1/`: one JSON per question plus `ORACLE_MANIFEST.json` with the code hash and the snapshot id.
7. Installs vLLM into `$CREDITPROBE_VENV_DIR/vllm`; checkpoints download into `$MODEL_CACHE_DIR`.
8. **Pins checkpoints and checks A40 fit** (`pin_and_probe_models.py`): metadata only, no weights.
9. **Probes each model** (`--probe`) that is pinned, licence-clear and fits the A40. Each is served with vLLM from its pinned revision, which downloads that checkpoint, and gets the harmless dummy-tool probe. The result is `READY_E2E` or `PROBE_FAILED` with the exact failure, and the next model follows.
10. **Opus reference preflight** (`opus_reference_set.py preflight`, no model call). It prints which of Q01–Q15 have a valid saved Opus reference, the missing ones, the current `opus_spend` cap, the available and the required spend, and whether the key is present.
    - Set `IMPORT_RUNTIME_FROM=<dir>` to import a prior runtime, for example the Mac runtime holding Q01 `cmp-f364d8b6901a`, into the empty pod runtime first.
    - If references are missing, it prints the explicit grant, build and verify commands. **It never runs the paid build itself.**
11. Prints the suite plan, starts the lab on 127.0.0.1, and stops at one of two banners:
    - **READY FOR REAL BENCHMARK — NO MODEL BENCHMARK CALLS YET** when all 15 references are READY;
    - **OPUS REFERENCES INCOMPLETE** otherwise.

**API key.** The frozen Opus provider reads `COCKPIT_ANTHROPIC_API_KEY` only from the runtime environment: set it as a RunPod secret.
- Never put it on a command line, in a file, in the manifest or in the bundle.
- The scripts check presence only.
- The Model I/O Trace, the reference set, the store and the export packs never contain it; the secret-scrubbing tests cover this.

## Gates (nothing is substituted or run silently)

| Gate | Status when it fails | How to clear it |
|---|---|---|
| Exact identity | `PIN_BLOCKED` (no unique official match, unreachable, no immutable sha) | Operator names the repository with `--repo <id>=<Org/Repo>` and re-pins |
| Immutable revision | not runnable (`NOT_INSTALLED`, "not pinned") | Pinning records the commit sha; "main" or "latest" is never used |
| Licence | `LICENSE_REVIEW_REQUIRED`, which shows as `NEEDS_APPROVAL` | Review the terms, then `approve.py grant license:<profile-id>` |
| A40 fit | `RESOURCE_BLOCKED_A40` (weights + KV cache at the served context + 3 GB overhead > 90 % of 48 GB) | Only a separately registered quantised variant, e.g. `qwen3.8-27b-runpod--awq-4bit`, with its own pin |
| Tool calling | `PROBE_FAILED` (no parser, forced tool use, round trip, stop mapping, identity) | Fix the parser or template per the model card, then re-probe |

A blocked model is skipped with its reason, and the suite continues.

## Opus references, then run and report

```bash
source /workspace-global/creditprobe-model-lab/env.sh && cd "$CREDITPROBE_SOURCE_DIR"
.venv/bin/python scripts/model_lab/opus_reference_set.py preflight --runtime-dir "$MODEL_LAB_RUNTIME_DIR"
.venv/bin/python scripts/model_lab/approve.py grant opus_spend --cap-usd <required_cap_usd> --runtime-dir "$MODEL_LAB_RUNTIME_DIR"
.venv/bin/python scripts/model_lab/opus_reference_set.py build --runtime-dir "$MODEL_LAB_RUNTIME_DIR" --confirm-paid-opus-calls
.venv/bin/python scripts/model_lab/opus_reference_set.py verify --runtime-dir "$MODEL_LAB_RUNTIME_DIR"   # all 15 READY
.venv/bin/python scripts/model_lab/benchmark_suite.py --runtime-dir "$MODEL_LAB_RUNTIME_DIR" --run --confirm-model-calls --serve
.venv/bin/python scripts/model_lab/suite_report.py --runtime-dir "$MODEL_LAB_RUNTIME_DIR"
```

- **Model order:** smallest first.
- **Per model:** re-probe, FROZEN_BASELINE Q01, then Q02–Q15, then ASSISTED_V1 Q01–Q15.
- **Checkpointing:** after every question, and a re-run resumes.
- **Evidence per result:** each is exported with its Full Model I/O Trace; the VRAM peak is sampled.
- **Report:** covers every model (variant, parameters, quantisation, exact revision, licence status, runtime, context, VRAM peak) and every cell. Each cell has the answer, S1–S4, independent correctness and, separately, the saved-Opus agreement (reference id, revision, S1–S4 and FINAL) for every question, the trace, tables and charts, and for ASSISTED_V1 the packet hash and the stage-by-stage change against the baseline. No overall winner is declared.
