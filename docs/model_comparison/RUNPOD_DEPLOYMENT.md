# RunPod A40 deployment (Model Lab with full Model I/O Trace)

**Status: PREPARED.** No model has been served or called.

## Build the bundle (on a clean checkout of this branch)

```bash
.venv/bin/python scripts/model_lab/runpod/build_bundle.py
```

This writes `artifacts/model_comparison/deployment/` (gitignored):

- `CreditProbe_Model_Lab_RunPod_FullTrace.zip`
- `RUNPOD_BOOTSTRAP.sh`
- `DEPLOYMENT_MANIFEST.json`
- `checksums.sha256`

**Contents are derived.** An audit-hook closure run does the following and records every repository file it imports or opens:

- starts the lab app;
- runs an offline fixture comparison with export and trace;
- imports the seeding code.

The backend packages it touched are shipped whole. Other backend applications are not shipped.

**Also shipped:** the frontend (a single Next.js app), `scripts/model_lab`, `scripts/cockpit_v4` (seeding), `tests/model_lab`, `profiles`, `launchers`, `docs/model_comparison`, `config/cockpit_v4`, `requirements.txt` and `pyproject.toml`.

**Excluded:** `.git`, `.venv`, `node_modules`, `.env*`, credentials, model weights, the generated lake (the pod re-seeds it) and runtime state.

**Build safeguards:**
- A secret scan fails the build on key-like content.
- The builder refuses to run with uncommitted lab-owned changes; bytes come from `HEAD`.
- It unpacks the zip and runs the git-free protected-manifest check before finishing.

## On the pod

```bash
cd /workspace && bash RUNPOD_BOOTSTRAP.sh --with-vllm
```

1. Checks for an NVIDIA GPU (A40 expected) and a writable `/workspace` with free space.
2. Verifies the checksums, unpacks to `/workspace/creditprobe-model-lab`, and re-verifies every file against the manifest.
3. Installs Python 3.12 dependencies (uv), Node 22, `npm ci` and Playwright Chromium.
4. Seeds and verifies the deterministic synthetic releases.
5. Runs `protected_manifest.py --check-bundle`, which confirms the frozen files it carries are byte-identical to `245c50e`.
6. Runs an offline fixture smoke test: trace, neutrality and saved reference.
7. Prints the benchmark plan as a dry run, reports checkpoint lookups and optionally installs vLLM into `/workspace/vllm-venv`.
8. Starts the lab on 127.0.0.1. Reach it through an SSH tunnel.

## Suite (`profiles/_runpod_suite.json`)

**Models and lanes.** 11 analyst models × 2 lanes × 15 questions. Julia-1 and Saaras V4 are excluded from the analyst benchmark.

**Model profiles.** Each model has a `*-runpod` profile. A vLLM-served Hugging Face checkpoint is a different artifact from any Ollama tag, so nothing is substituted.

| State | Models | Condition to become runnable |
|---|---|---|
| **NOT_INSTALLED** | Known repository | Runnable only after (a) the exact revision is pinned with `verify_checkpoints.py --pin`, and (b) `probe.py` passes on the served endpoint. |
| **DISCOVERED** | MiniCPM5-2B, LFM2.5-VL-3B, Ornith-1.5-9B | Never runnable as-is. The exact repositories could not be verified from the build environment (no Hugging Face access); pin one explicitly on the pod. |
| **BLOCKED_RESOURCE** | Qwen3.8-27B | bf16 weights of about 55 GB exceed 48 GB. A quantised checkpoint is a different artifact and must be registered separately. |

**Tool-call parsers** are suggestions until the probe qualifies them. Gemma's is not set, so `serve.sh` refuses to serve it.

**Lanes:**
- **FROZEN_BASELINE** is the unchanged frozen engine.
- **ASSISTED_V1 is BLOCKED.** No assistance packet or delivery mechanism has been specified or approved, so running it would silently equal the baseline.

**Questions:**
- Q01 has the independent oracle and the saved Opus reference `cmp-f364d8b6901a`.
- Q02–Q14 need oracles; until then they are scored by frozen validation, claim binding and human review.
- Q15 is review-only by design (an under-specified question).

**Runner.** `benchmark_suite.py` plans by default. `--run` requires `--confirm-model-calls` and tracing on, runs exactly one ready model at a time, and refuses ASSISTED_V1.
