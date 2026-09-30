# RunPod A40 deployment (Model Lab, full Model I/O Trace, suite v2)

**Status: PREPARED.** No benchmark question has been sent to any model.

## Build the bundle (clean checkout of this branch)

```bash
.venv/bin/python scripts/model_lab/runpod/build_bundle.py
```

This writes `artifacts/model_comparison/deployment/` (gitignored):

- `CreditProbe_Model_Lab_RunPod_FullTrace.zip`
- `RUNPOD_BOOTSTRAP.sh`
- `DEPLOYMENT_MANIFEST.json`
- `checksums.sha256`

**How contents are chosen.** The bundle is derived from an audit-hook closure run plus the static imports of every shipped backend package. Bytes come from `HEAD`.

**Excluded:** `.git`, `.venv`, `node_modules`, `.env*`, credentials, model weights, the generated lake (the pod re-seeds it) and runtime state.

**Build checks:**
- a secret scan;
- a git-free protected-manifest check of the extracted bundle.

## On the pod

```bash
cd /workspace && bash RUNPOD_BOOTSTRAP.sh          # --skip-probe to defer weight downloads
```

1. Checks for the A40 GPU and a writable `/workspace`, verifies checksums, unpacks, and re-verifies every file.
2. Installs Python 3.12 (uv), Node 22, `npm ci` and Playwright.
3. Seeds and verifies the synthetic releases.
4. Runs the protected-manifest check (`--check-bundle`).
5. Runs the offline fixture smoke test: trace, neutrality, saved reference, ASSISTED_V1, oracles and suite runner.
6. **Prepares the suite.** It materialises the independent oracle artifacts to `<runtime>/oracles/lab-oracle-suite-1/`: one JSON per question plus `ORACLE_MANIFEST.json` with the code hash and the snapshot id.
7. Installs vLLM into `/workspace/vllm-venv`.
8. **Pins checkpoints and checks A40 fit** (`pin_and_probe_models.py`): metadata only, no weights.
9. **Probes each model** (`--probe`) that is pinned, licence-clear and fits the A40. Each is served with vLLM from its pinned revision, which downloads that checkpoint, and gets the harmless dummy-tool probe. The result is `READY_E2E` or `PROBE_FAILED` with the exact failure, and the next model follows.
10. Prints the suite plan, starts the lab on 127.0.0.1, and stops at **READY FOR REAL BENCHMARK — NO MODEL BENCHMARK CALLS YET**.

## Gates (nothing is substituted or run silently)

| Gate | Status when it fails | How to clear it |
|---|---|---|
| Exact identity | `PIN_BLOCKED` (no unique official match, unreachable, no immutable sha) | Operator names the repository with `--repo <id>=<Org/Repo>` and re-pins |
| Immutable revision | not runnable (`NOT_INSTALLED`, "not pinned") | Pinning records the commit sha; "main" or "latest" is never used |
| Licence | `LICENSE_REVIEW_REQUIRED`, which shows as `NEEDS_APPROVAL` | Review the terms, then `approve.py grant license:<profile-id>` |
| A40 fit | `RESOURCE_BLOCKED_A40` (weights + KV cache at the served context + 3 GB overhead > 90 % of 48 GB) | Only a separately registered quantised variant, e.g. `qwen3.8-27b-runpod--awq-4bit`, with its own pin |
| Tool calling | `PROBE_FAILED` (no parser, forced tool use, round trip, stop mapping, identity) | Fix the parser or template per the model card, then re-probe |

A blocked model is skipped with its reason, and the suite continues.

## Run and report

```bash
.venv/bin/python scripts/model_lab/benchmark_suite.py --runtime-dir /workspace/lab-runtime --run --confirm-model-calls --serve
.venv/bin/python scripts/model_lab/suite_report.py --runtime-dir /workspace/lab-runtime
```

- **Model order:** smallest first.
- **Per model:** re-probe, FROZEN_BASELINE Q01, then Q02–Q15, then ASSISTED_V1 Q01–Q15.
- **Checkpointing:** after every question, and a re-run resumes.
- **Evidence per result:** each is exported with its Full Model I/O Trace; the VRAM peak is sampled.
- **Report:** covers every model (variant, parameters, quantisation, exact revision, licence status, runtime, context, VRAM peak) and every cell. Each cell has the answer, S1–S4, independent correctness, Opus agreement for Q01, the trace, tables and charts, and for ASSISTED_V1 the packet hash and the stage-by-stage change against the baseline. No overall winner is declared.
