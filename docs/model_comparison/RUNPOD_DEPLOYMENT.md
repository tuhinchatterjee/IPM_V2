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

The bootstrap prints `PERSIST_ROOT:`, `filesystem:`, `free_space:` and `persistence_verified: YES`, plus a volume marker that shows when state survived a restart.

## Two storage areas: persistent data, Pod-local executables

On the live Global Volume the filesystem is `fuse.geesefs`, and `chmod` there fails with "Operation not permitted". So the volume holds **data only**, and nothing on it is ever chmod-ed. Executables live on the Pod's own `/workspace`. They may vanish with the Pod, and the bootstrap rebuilds them from the bundle copy kept on the volume.

**Persistent data:** `<persist>/creditprobe-model-lab` (`CREDITPROBE_PERSIST_ROOT`).

| Path | Contents | Variable |
|---|---|---|
| `deployment/` | zip, bootstrap, `runpod_storage.py`, manifest, checksums; earlier bundles in `deployment/archive/` | `CREDITPROBE_DEPLOYMENT_DIR` |
| `runtime/` | lab store and frozen run DB (SQLite WAL); Model I/O traces; exports; answers; SQL/Python; tables; charts; oracles; checkpoints; reports; probes; resource samples; run and vLLM logs | `MODEL_LAB_RUNTIME_DIR` |
| `reference_sets/` | `OPUS_REFERENCE_SET_V1.json` and its answer snapshots | `MODEL_LAB_REFERENCE_SET_DIR` |
| `results/`, `results/screenshots/` | results and screenshots | `CREDITPROBE_RESULTS_DIR`, `LAB_EVIDENCE_DIR` |
| `logs/` | bootstrap logs | `CREDITPROBE_LOG_DIR` |
| `state/pinned_profiles/` | pinned model identities | `MODEL_LAB_PINNED_PROFILES_DIR` |
| `cache/models` | model weights (vLLM `--download-dir`) | `MODEL_CACHE_DIR` |
| `cache/huggingface` | Hugging Face downloads | `HF_HOME`, `HF_HUB_CACHE`, `TRANSFORMERS_CACHE` |
| `env.sh` | the environment for both areas; never contains `COCKPIT_ANTHROPIC_API_KEY` | |

**Pod-local executables:** `/workspace/creditprobe-model-lab` (`CREDITPROBE_APP_ROOT`). When the persistent root is the `/workspace` Network Volume itself, the app root is `<persist>/creditprobe-model-lab/app`; `CREDITPROBE_APP_ROOT` overrides both.

| Path | Contents | Variable |
|---|---|---|
| `source/` | the unpacked lab, `.venv`, `frontend/node_modules`, launchers | `CREDITPROBE_SOURCE_ROOT` |
| `venvs/vllm` | the vLLM executable environment | `VLLM_BIN` |
| `cache/{vllm,torch,triton}` | compiled kernels (loaded as code) | `VLLM_CACHE_ROOT`, `TORCH_HOME`, `TRITON_CACHE_DIR` |
| `cache/{pip,uv,npm,ms-playwright,xdg}`, `tmp/` | build caches, Playwright browsers, temporary files | their standard variables |

**Guards, each with its own exit code:**
- No persistent volume: `PERSISTENT_STORAGE_NOT_FOUND` (exit 3).
- The app root fails the executable probe (write, `chmod +x`, run), or it overlaps the persistent root: `APP_ROOT_NOT_EXECUTABLE` (exit 4).
- SQLite in WAL mode does not work on the persistent runtime: `PERSISTENT_SQLITE_UNSUPPORTED` (exit 5).

**Bootstrap flow:**
1. Detect and verify the volume, probe the app root and SQLite, and write `env.sh`.
2. Byte-copy and verify the bundle into `deployment/`. A different earlier bundle is archived, never overwritten.
3. Rebuild `source/` on the app root. It unpacks into `source.new`, carries over a same-Pod `.venv` and `node_modules`, and swaps them in.
4. Set the executable bit only under the app root.
5. Verify the manifest, then restore pinned identities from the volume.
6. Run the GPU check and the installs (app root only), seeding, tests, pin/fit and probe (weights download to the volume), and the Opus reference preflight.
7. Stop before any paid call.

**Pins are kept.** An already pinned profile is never re-resolved, so a resumed suite keeps the exact revisions it started with; `--repin` is an explicit operator decision.

**A new Pod on the same volume** (empty `/workspace`) runs:

```bash
bash /workspace-global/creditprobe-model-lab/deployment/RUNPOD_BOOTSTRAP.sh
```

The app root is rebuilt, and every checkpoint, reference, result, model download and probe on the volume is kept. The suite runner then resumes from its checkpoint.

## On the pod

```bash
cd <directory holding the five bundle files> && bash RUNPOD_BOOTSTRAP.sh   # --storage-check | --prepare-only | --skip-probe
source /workspace-global/creditprobe-model-lab/env.sh && cd "$CREDITPROBE_SOURCE_ROOT"
```

1. **Storage, deployment, app.** Detects the volume and probes the app root and SQLite. It tees the bootstrap log to `logs/`, installs and verifies the bundle in `deployment/`, rebuilds `source/` on the app root and re-verifies every file, then checks for the A40 GPU.
2. Installs Python 3.12 (uv), Node 22, `npm ci` and Playwright.
3. Seeds and verifies the synthetic releases.
4. Runs the protected-manifest check (`--check-bundle`).
5. Runs the offline fixture smoke test: trace, neutrality, saved reference, ASSISTED_V1, oracles and suite runner.
6. **Prepares the suite.** It materialises the independent oracle artifacts to `<runtime>/oracles/lab-oracle-suite-1/`: one JSON per question plus `ORACLE_MANIFEST.json` with the code hash and the snapshot id.
7. **GPU driver / CUDA gate** (`vllm_runtime.py host`). It runs before vLLM is installed and before any model is served. It records the GPU, driver and host CUDA in the runtime manifest. If the driver is too old, it stops vLLM install and probing with `VLLM_HOST_DRIVER_INCOMPATIBLE`; pinning and the Opus preflight still run.
8. **vLLM environment** (Pod-local `$CREDITPROBE_VENV_DIR/vllm`):
   - Python 3.12;
   - the vLLM 0.30.0 wheel, with its sha256 verified;
   - `vllm-0.30.0-constraints.txt`.
9. **Pins checkpoints and checks A40 fit** (`pin_and_probe_models.py`): metadata only, no weights. It also does the following:
   - assigns each model's tool parser (see below);
   - records licence evidence;
   - verifies the identity of any repository found by publisher and name.
   A pin that already exists is kept.
9b. **Runtime preflight** (`vllm_runtime.py preflight`, no model, no weights):
   - records the installed versions;
   - reads the tool and reasoning parser registries of the installed vLLM and loads every assigned parser class;
   - imports each pinned architecture's vLLM model module;
   - initialises CUDA from torch.
   The results go to `runtime/vllm_runtime/RUNTIME_MANIFEST.json` on the volume.
9c. **Probes** (`--probe`) each runtime-ready, pinned, licence-clear model that fits. Each is served from its pinned revision; the weights download into the persistent `MODEL_CACHE_DIR`. Each model gets the harmless dummy-tool probe and ends `READY_E2E` or one of the failure classes below. The next model always follows.
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

## vLLM runtime on RunPod (live findings and how they are handled)

**What the live A40 host showed.** The host had NVIDIA driver 570.211.01, which supports CUDA 12.8. The standard vLLM 0.30.0 wheel pins `torch==2.13.0`, and its PyPI build depends on `cuda-toolkit==13.0.3`, a CUDA 13.0 runtime. Every model therefore failed with "The NVIDIA driver on your system is too old (found version 12080)". CUDA 13.0 requires Linux driver **>= 580.65.06** (NVIDIA CUDA Toolkit release notes).

**How it is handled now:**
- The bootstrap stops before installing or probing vLLM and prints:
  - `VLLM_HOST_DRIVER_INCOMPATIBLE`;
  - `driver_version`, `host_cuda`, `vllm_version`, `vllm_cuda` and `minimum_required_driver`;
  - remediation: redeploy the Pod on a RunPod host with a compatible driver.
- Nothing is worked around:
  - no CUDA compatibility package is installed;
  - the driver is not changed;
  - vLLM is not downgraded;
  - no other engine is used.
- The verdict is also checked empirically: the preflight initialises CUDA from the installed torch, without loading a model.

**Ministral / Transformers.**
- vLLM 0.30.0 declares only `transformers >= 5.10.4`, so an unpinned install takes the newest version.
- Transformers 5.17.0 removed `PixtralRotaryEmbedding` and `position_ids_in_meshgrid`, which vLLM's `pixtral.py` imports. That removal caused the live Ministral `ImportError`. Every 5.10.4–5.18.0 wheel was checked.
- vLLM's own CI lock for cu130 / Python 3.12 (`requirements/test/cuda.txt` at v0.30.0) pins `transformers==5.16.1`, which still exports both names. The constraints file pins that full CI set: torch 2.13.0, transformers 5.16.1, tokenizers 0.23.1, huggingface-hub 1.31.0, mistral-common 1.11.6, xgrammar 0.2.3 and safetensors 0.8.0.
- This is one environment for every model; nothing is model-specific.
- The preflight imports `PixtralForConditionalGeneration` and `Mistral3ForConditionalGeneration` before any download. If an import fails, the model is `TRANSFORMERS_INCOMPATIBLE` and the other models continue.

**Tool parsers.** Every name below is registered in vLLM 0.30.0 and documented there for the family. Each is re-read from the installed vLLM on the Pod and must still pass the READY_E2E probe.

| Model | Tool parser | Reasoning parser | Note |
|---|---|---|---|
| MiniCPM5-2B | `minicpm5` (MiniCPM5 XML) | none | |
| LFM2.5-VL-3B | `lfm2` | none | |
| Qwen3.5-4B, Qwen3.5-9B | `qwen3_coder` or `hermes` | `qwen3` | Chosen by the markers in the model's own chat template (`<function=`/`<parameter=` for XML; `<tool_call>` for JSON) |
| Fin-R1 | `hermes` | none | |
| Granite 4.2-8B | `granite4` | none | vLLM documents it for Granite 4.x; the old `granite` setting was for 3.x |
| Ministral 3 8B | `mistral` | none | Uses `--tokenizer-mode mistral` |
| Gemma 4 12B | `gemma4` | `gemma4` | vLLM does not require a separate chat template |
| Ornith-1.5-9B | detected from its template markers after identity verification | none | |

**Repository identity (Ornith).** A repository found by publisher and name, or named by the operator, is pinned only after all of these hold:
- the Hub author equals the organisation;
- the organisation lists the repository;
- a model card at the pinned revision names the model;
- the card does not declare a same-named `base_model` elsewhere, which would make it a re-upload.

The externally reported `ornith-ai/Ornith-1.5-9B` is recorded as `expected_repository` and is never accepted on that basis alone. Hugging Face is unreachable from the build environment, so this check runs on the Pod.

**Licences.** The pin records the source as `license_evidence`:
- the model card's licence id, name and link;
- the Hub licence tags;
- links to the LICENSE files at the pinned revision.

Only a machine-readable OSI-style id is `LICENSE_OK`. Anything else stays `LICENSE_REVIEW_REQUIRED`, and the exact evidence is printed for human review.

**Failure classes (never a generic `PROBE_FAILED`).**

| Class | Meaning |
|---|---|
| `HOST_DRIVER_INCOMPATIBLE` | The host's NVIDIA driver is too old for the CUDA 13.0 runtime. |
| `VLLM_RUNTIME_INCOMPATIBLE` | The installed environment differs from the lock, an architecture is unsupported, or the runtime preflight has not run. |
| `TRANSFORMERS_INCOMPATIBLE` | The model's vLLM module fails to import because of Transformers. |
| `TOOL_PARSER_MISSING` | No parser is assigned, or the assigned parser is not registered or not loadable. |
| `MODEL_SERVER_START_FAILED` | vLLM did not start for another reason. |
| `MODEL_DOWNLOAD_FAILED` | The download failed (Hub or network errors, or a full disk) and the pinned files are incomplete. |
| `MODEL_TOOL_ROUNDTRIP_FAILED` | The server started but the dummy-tool probe failed. |
| `RESOURCE_BLOCKED` | The model does not fit the A40. |
| `LICENSE_REVIEW_REQUIRED` | The licence needs human review before the model runs. |
| `PIN_BLOCKED` | The repository identity or revision could not be pinned. |

**geesefs chmod warnings.** Hugging Face's "Could not set the permissions … Continuing without setting permissions" lines come from the Global Volume refusing chmod. They are ignored. A download counts as valid when every pinned weight file is present at the pinned revision with the pinned size.

**Fit results.** Measured A40 fit results recorded on the Pod are kept, for example `gpt-oss-20b` and Qwen ~27B bf16 as `RESOURCE_BLOCKED_A40`. A quantised model is only ever a separate child profile.

## Gates (nothing is substituted or run silently)

| Gate | Status when it fails | How to clear it |
|---|---|---|
| Exact identity | `PIN_BLOCKED` (no unique official match, unreachable, no immutable sha) | Operator names the repository with `--repo <id>=<Org/Repo>` and re-pins |
| Immutable revision | not runnable (`NOT_INSTALLED`, "not pinned") | Pinning records the commit sha; "main" or "latest" is never used |
| Licence | `LICENSE_REVIEW_REQUIRED`, which shows as `NEEDS_APPROVAL` | Review the terms, then `approve.py grant license:<profile-id>` |
| A40 fit | `RESOURCE_BLOCKED_A40` (weights + KV cache at the served context + 3 GB overhead > 90 % of 48 GB) | Only a separately registered quantised variant, e.g. `qwen3.8-27b-runpod--awq-4bit`, with its own pin |
| Host driver | `HOST_DRIVER_INCOMPATIBLE` (driver below 580.65.06 for the CUDA 13.0 runtime) | Redeploy the Pod on a host with a compatible driver |
| Runtime | `VLLM_RUNTIME_INCOMPATIBLE` / `TRANSFORMERS_INCOMPATIBLE` (environment differs from the lock; model module fails to import) | Rebuild the Pod-local vLLM venv from the bundle; never patch site-packages |
| Tool calling | `TOOL_PARSER_MISSING` / `MODEL_TOOL_ROUNDTRIP_FAILED` (no registered parser; forced tool use, round trip, stop mapping) | Fix the parser assignment per the model card and the vLLM registry, then re-probe |

A blocked model is skipped with its reason, and the suite continues.

## Opus references, then run and report

```bash
source /workspace-global/creditprobe-model-lab/env.sh && cd "$CREDITPROBE_SOURCE_ROOT"
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
