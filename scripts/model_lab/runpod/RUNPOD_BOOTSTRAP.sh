#!/usr/bin/env bash
# CreditProbe Model Lab — RunPod A40 bootstrap (full Model I/O Trace).
#
#   bash RUNPOD_BOOTSTRAP.sh [--storage-check] [--prepare-only] [--skip-browser]
#                            [--skip-probe] [--skip-vllm] [--no-start]
#
# First run: from the directory holding the five bundle files
# (CreditProbe_Model_Lab_RunPod_FullTrace.zip, RUNPOD_BOOTSTRAP.sh,
# runpod_storage.py, DEPLOYMENT_MANIFEST.json, checksums.sha256).
# Every later run, including on a NEW Pod attached to the same volume:
#   bash /workspace-global/creditprobe-model-lab/deployment/RUNPOD_BOOTSTRAP.sh
#
# TWO STORAGE AREAS, never mixed:
#
#   PERSISTENT  <persist>/creditprobe-model-lab   (CREDITPROBE_PERSIST_ROOT)
#     /workspace-global (RunPod Global Volume, fuse.geesefs) first, else a
#     /workspace Network Volume, else STOP: PERSISTENT_STORAGE_NOT_FOUND
#     (exit 3). Durable DATA only: deployment bundle, runtime store and run
#     DB, Model I/O traces, exports, answers, SQL/Python, tables, charts,
#     screenshots, oracles, Opus reference set, checkpoints, reports, logs,
#     pinned identities, model weights and Hugging Face downloads. Nothing
#     there is ever chmod-ed (the Global Volume refuses chmod).
#
#   APP ROOT    /workspace/creditprobe-model-lab  (CREDITPROBE_APP_ROOT)
#     Pod-local EXECUTABLES: unpacked source, .venv, node_modules, vLLM
#     venv, Playwright browsers, compile/build caches, launchers. It may
#     vanish with the Pod; this script rebuilds it from the persistent
#     deployment/ copy while every result stays on the volume. The app root
#     must pass an executable probe (APP_ROOT_NOT_EXECUTABLE, exit 4), and
#     SQLite WAL must work on the persistent runtime
#     (PERSISTENT_SQLITE_UNSUPPORTED, exit 5).
#
# The environment for both areas is written to <persist>/env.sh: `source`
# it in every new shell. It never contains a credential.
#   --storage-check  stop after the storage verdict
#   --prepare-only   stop after deployment + app rebuild (before installs)
#
# Then: GPU check, Python/Node/vLLM installs (app root only), seeding,
# protected-manifest check, offline smoke test, oracle artifacts, pin + A40
# fit, probes (downloads pinned checkpoints into the persistent model
# cache), OPUS REFERENCE preflight, suite plan, lab start.
#
# It makes NO paid call and sends NO benchmark question to any model.
# Building missing Opus references and running the suite are separate,
# deliberate operator steps, in that order: the suite refuses to start a
# candidate until all 15 references are READY.
#
# COCKPIT_ANTHROPIC_API_KEY is read by the frozen Opus provider only from
# the runtime environment (a RunPod secret). Never pass it on a command
# line, never write it to a file (env.sh never contains it); this script
# checks presence only.
set -euo pipefail

SKIP_BROWSER=0; WITH_VLLM=1; START=1; PROBE=1; STORAGE_ONLY=0; PREPARE_ONLY=0
for a in "$@"; do
  case "$a" in
    --storage-check) STORAGE_ONLY=1 ;;
    --prepare-only) PREPARE_ONLY=1 ;;
    --skip-browser) SKIP_BROWSER=1 ;;
    --with-vllm) WITH_VLLM=1 ;;
    --skip-vllm) WITH_VLLM=0 ;;
    --skip-probe) PROBE=0 ;;
    --no-start) START=0 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
ok() { printf '  \033[32mOK\033[0m %s\n' "$*"; }
die() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }
# shellcheck disable=SC2086
storage() { python3 "$1" "${@:2}" ${CREDITPROBE_STORAGE_TEST_ARGS:-}; }

echo "== 1. Persistent storage and Pod-local app root (before anything is written)"
[ -f "$HERE/runpod_storage.py" ] || die "runpod_storage.py is missing next to this script"
if [ -n "${CREDITPROBE_STORAGE_TEST_ARGS:-}" ]; then
  echo "  TEST MODE: storage detection driven by CREDITPROBE_STORAGE_TEST_ARGS (offline tests only)"
fi
STORAGE_RC=0
EXPORTS="$(storage "$HERE/runpod_storage.py" detect --shell)" || STORAGE_RC=$?
case "$STORAGE_RC" in
  0) ;;
  3) echo "  STOP: no persistent volume; nothing was written (exit 3)"; exit 3 ;;
  4) echo "  STOP: the Pod-local app root cannot hold executables (exit 4)"; exit 4 ;;
  5) echo "  STOP: SQLite (WAL) does not work on the persistent runtime (exit 5)"; exit 5 ;;
  *) echo "  STOP: storage detection failed (exit $STORAGE_RC)"; exit "$STORAGE_RC" ;;
esac
eval "$EXPORTS"
{
  echo "# CreditProbe Model Lab on RunPod. source this file in every new shell."
  echo "# Persistent DATA: CREDITPROBE_PERSIST_ROOT. Pod-local EXECUTABLES: CREDITPROBE_APP_ROOT."
  printf '%s\n' "$EXPORTS"
  echo "export COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4"
  echo "export MODEL_LAB_FULL_IO_TRACE=true"
  echo "export MODEL_LAB_PYTHON=\"\$CREDITPROBE_SOURCE_ROOT/.venv/bin/python\""
  echo "export VLLM_BIN=\"\$CREDITPROBE_VENV_DIR/vllm/bin/vllm\""
} > "$CREDITPROBE_PERSIST_ROOT/env.sh"
# shellcheck disable=SC1091
source "$CREDITPROBE_PERSIST_ROOT/env.sh"
APP="$CREDITPROBE_SOURCE_ROOT"
RUNTIME="$MODEL_LAB_RUNTIME_DIR"
DEPLOY="$CREDITPROBE_DEPLOYMENT_DIR"
ok "persistent $CREDITPROBE_PERSIST_ROOT ($PERSIST_KIND); app $CREDITPROBE_APP_ROOT; env: $CREDITPROBE_PERSIST_ROOT/env.sh"
if [ "$STORAGE_ONLY" = 1 ]; then
  echo "storage check only (--storage-check): stopping here"
  exit 0
fi
LOG="$CREDITPROBE_LOG_DIR/bootstrap-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1
echo "  bootstrap log: $LOG"

echo "== 2. Deployment bundle -> persistent $DEPLOY (byte copy, verified; never chmod)"
storage "$HERE/runpod_storage.py" deploy --from "$HERE" || die "deployment copy/verification failed"
(cd "$DEPLOY" && sha256sum -c --quiet checksums.sha256) || die "persistent deployment checksum mismatch"
ok "deployment verified in $DEPLOY (rerun later with: bash $DEPLOY/RUNPOD_BOOTSTRAP.sh)"

echo "== 3. Rebuild the Pod-local app root $CREDITPROBE_APP_ROOT from the persistent bundle"
storage "$DEPLOY/runpod_storage.py" unpack || die "unpack refused"
cd "$APP"
python3 - <<'EOF' || die "unpacked files do not match DEPLOYMENT_MANIFEST.json"
import hashlib, json, pathlib
m = json.loads(pathlib.Path("DEPLOYMENT_MANIFEST.json").read_text())
bad = [p for p, f in m["files"].items()
       if hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() != f["sha256"]]
assert not bad, bad[:5]
print(f"  {len(m['files'])} files match the manifest (source {m['source_commit'][:12]})")
EOF
storage "$DEPLOY/runpod_storage.py" restore-pins || die "pin restore failed"
ok "app source at $APP (executables marked there only)"
if [ "$PREPARE_ONLY" = 1 ]; then
  echo "prepare only (--prepare-only): stopping before installs"
  exit 0
fi

echo "== 3b. GPU"
command -v nvidia-smi >/dev/null || die "nvidia-smi not found: not a GPU pod"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader \
  | tee /dev/stderr | grep -qi "A40" || echo "  WARN GPU is not an A40; the suite's memory arithmetic assumes 48 GB"
ok "NVIDIA GPU present"

echo "== 4. Python and Node dependencies (app root only)"
if ! command -v uv >/dev/null; then python3 -m pip install -q uv || true; fi
if command -v uv >/dev/null; then
  [ -x .venv/bin/python ] || uv venv -q -p 3.12 .venv
  uv pip install -q -p .venv/bin/python -r requirements.txt pytest ruff
else
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt pytest ruff
fi
if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
  curl -fsSL https://nodejs.org/dist/v22.11.0/node-v22.11.0-linux-x64.tar.xz | tar -xJ -C /usr/local --strip-components=1
fi
(cd frontend && npm ci --no-audit --no-fund)
if [ "$SKIP_BROWSER" = 0 ]; then
  (cd frontend && npx --yes playwright install --with-deps chromium) || echo "  WARN browser install failed; UI acceptance will be unavailable"
fi
ok "python $(.venv/bin/python -V 2>&1 | cut -d' ' -f2), node $(node -v)"

echo "== 5. Seed the deterministic synthetic data"
export COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4 MODEL_LAB_FULL_IO_TRACE=true
.venv/bin/python scripts/cockpit_v4/seed_domains.py --verify 2>/dev/null \
  || .venv/bin/python scripts/cockpit_v4/seed_domains.py
.venv/bin/python scripts/cockpit_v4/seed_domains.py --verify
ok "synthetic releases published and verified"

echo "== 6. Protected manifest (frozen AdvancedCockpit unchanged)"
.venv/bin/python scripts/model_lab/protected_manifest.py --check-bundle || die "protected manifest check failed"

echo "== 7. Offline fixture smoke test (no model)"
# The smoke tests use their own temporary stores: never the persistent
# runtime, reference set, evidence directory or pinned identities.
env -u MODEL_LAB_RUNTIME_DIR -u MODEL_LAB_REFERENCE_SET_DIR -u LAB_EVIDENCE_DIR \
  -u MODEL_LAB_PINNED_PROFILES_DIR -u CREDITPROBE_APP_ROOT \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/model_lab/test_model_io_trace.py tests/model_lab/test_observer_neutrality.py \
  tests/model_lab/test_saved_reference.py tests/model_lab/test_assisted_lane.py \
  tests/model_lab/test_benchmark_oracles.py tests/model_lab/test_runpod_suite.py \
  tests/model_lab/test_opus_reference_set.py tests/model_lab/test_runpod_storage.py \
  tests/model_lab/test_runpod_execution_storage.py \
  || die "fixture smoke test failed"
ok "fixture smoke test passed (full Model I/O Trace, oracles, ASSISTED_V1, suite runner, Opus reference gate)"

echo "== 8. Suite preparation: independent oracle artifacts"
mkdir -p "$RUNTIME"
.venv/bin/python -c "
import sys; from pathlib import Path
from backend.model_lab import benchmark_oracles as bo
out = Path(sys.argv[1]) / 'oracles' / bo.ORACLE_SUITE_VERSION
h = bo.materialize(out)
print(f'  {len(h)} oracle artifacts -> {out}; snapshot {bo.snapshot_id()}')
" "$RUNTIME"
ok "oracles materialised (evaluation-side only; never sent to a model)"

echo "== 9. vLLM runtime"
if [ "$WITH_VLLM" = 1 ] || [ "$PROBE" = 1 ]; then
  VENV_VLLM="$CREDITPROBE_VENV_DIR/vllm"
  [ -x "$VENV_VLLM/bin/vllm" ] || { python3 -m venv "$VENV_VLLM" && "$VENV_VLLM/bin/pip" install -q vllm; }
  ok "vLLM $("$VENV_VLLM/bin/python" -c 'import vllm; print(vllm.__version__)' 2>/dev/null) in $VENV_VLLM"
else
  echo "  vLLM not installed (--skip-vllm); serve.sh expects $CREDITPROBE_VENV_DIR/vllm/bin/vllm"
fi

echo "== 10. Checkpoint pin + A40 fit preflight (metadata only, no weights)"
.venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir "$RUNTIME" \
  || echo "  WARN pinning reported errors; see $RUNTIME/pins/ROSTER.json"

if [ "$PROBE" = 1 ]; then
  echo "== 11. Capability probe: pinned, licence-clear, fitting models only"
  echo "   downloads each such checkpoint into $MODEL_CACHE_DIR (HF_HOME=$HF_HOME); dummy tool only; no benchmark question"
  .venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir "$RUNTIME" --probe \
    || echo "  WARN probe step reported errors; see $RUNTIME/pins/ROSTER.json"
else
  echo "== 11. Probe deferred (--skip-probe). Run before the benchmark:"
  echo "   .venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir $RUNTIME --probe"
fi

echo "== 12. Opus reference preflight: OPUS_REFERENCE_SET_V1 (no model call)"
if [ -n "${IMPORT_RUNTIME_FROM:-}" ]; then
  echo "   importing saved comparisons from $IMPORT_RUNTIME_FROM (approvals/probes not copied)"
  .venv/bin/python scripts/model_lab/opus_reference_set.py import-runtime \
    --runtime-dir "$RUNTIME" --from "$IMPORT_RUNTIME_FROM" || echo "  WARN import refused (see message)"
fi
REF_RC=0
.venv/bin/python scripts/model_lab/opus_reference_set.py preflight --runtime-dir "$RUNTIME" || REF_RC=$?
case "$REF_RC" in
  0) REF_STATE=READY; ok "all 15 Opus references READY: the candidate benchmark may start" ;;
  3) REF_STATE=MISSING
     echo "  Opus references are MISSING (listed above). NO candidate may start yet."
     echo "  The bootstrap makes no paid call. After granting a cap that covers the"
     echo "  required spend and injecting COCKPIT_ANTHROPIC_API_KEY as a pod secret, build"
     echo "  them explicitly (one frozen-provider Opus run per missing question):"
     echo "    .venv/bin/python scripts/model_lab/approve.py grant opus_spend --cap-usd <required_cap_usd> --runtime-dir $RUNTIME"
     echo "    .venv/bin/python scripts/model_lab/opus_reference_set.py build --runtime-dir $RUNTIME --confirm-paid-opus-calls"
     echo "  then verify all 15 READY:"
     echo "    .venv/bin/python scripts/model_lab/opus_reference_set.py verify --runtime-dir $RUNTIME" ;;
  *) REF_STATE=ERROR; echo "  WARN Opus reference preflight failed (exit $REF_RC)" ;;
esac

echo "== 13. Suite plan (no model call)"
.venv/bin/python scripts/model_lab/benchmark_suite.py --runtime-dir "$RUNTIME"

if [ "$START" = 1 ]; then
  echo "== 14. Start Model Lab services (127.0.0.1 only)"
  MODEL_LAB_RUNTIME_DIR="$RUNTIME" MODEL_LAB_PYTHON=.venv/bin/python \
    ./launchers/START_MODEL_LAB.command --runtime-dir "$RUNTIME"
  echo "  From your machine: ssh -L 5424:127.0.0.1:5424 -L 8424:127.0.0.1:8424 <pod-ssh>"
  echo "  then open http://127.0.0.1:5424/cockpit/lab"
fi

if [ "$REF_STATE" = READY ]; then
  HEAD_LINE="READY FOR REAL BENCHMARK — NO MODEL BENCHMARK CALLS YET"
else
  HEAD_LINE="OPUS REFERENCES INCOMPLETE — BUILD THEM (step 12) BEFORE THE BENCHMARK; NO MODEL CALLS YET"
fi
cat <<EOF

PERSIST_ROOT: $PERSIST_ROOT ($PERSIST_KIND)
in a new shell first:  source $CREDITPROBE_PERSIST_ROOT/env.sh && cd $CREDITPROBE_SOURCE_ROOT
on a new Pod:          bash $CREDITPROBE_DEPLOYMENT_DIR/RUNPOD_BOOTSTRAP.sh   (rebuilds the app root; keeps all results)
PERSISTENT data  $CREDITPROBE_PERSIST_ROOT
  deployment   $CREDITPROBE_DEPLOYMENT_DIR
  runtime      $MODEL_LAB_RUNTIME_DIR  (store, run DB, Model I/O traces, exports, oracles, checkpoints, reports, probes, logs)
  opus refs    $MODEL_LAB_REFERENCE_SET_DIR
  results      $CREDITPROBE_RESULTS_DIR  (screenshots: $LAB_EVIDENCE_DIR)
  logs         $CREDITPROBE_LOG_DIR
  pins         $MODEL_LAB_PINNED_PROFILES_DIR
  model cache  $MODEL_CACHE_DIR   HF_HOME=$HF_HOME
POD-LOCAL executables  $CREDITPROBE_APP_ROOT  (may vanish with the Pod)
  source       $CREDITPROBE_SOURCE_ROOT  (.venv, node_modules)
  venvs        $CREDITPROBE_VENV_DIR
  caches       VLLM_CACHE_ROOT=$VLLM_CACHE_ROOT  PLAYWRIGHT_BROWSERS_PATH=$PLAYWRIGHT_BROWSERS_PATH

$HEAD_LINE
  opus refs: $REF_STATE (.venv/bin/python scripts/model_lab/opus_reference_set.py verify --runtime-dir $RUNTIME)
  roster:    $RUNTIME/pins/ROSTER.json
  licences:  review each LICENSE_REVIEW_REQUIRED model's terms, then
             .venv/bin/python scripts/model_lab/approve.py grant license:<profile-id> --runtime-dir $RUNTIME
  identities: for a PIN_BLOCKED model, name the official repository and re-pin:
             .venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir $RUNTIME --profile <id> --repo <id>=<Org/Repo> --probe
  run (explicit; only after all 15 Opus references are READY; every qualified
       model, smallest first, checkpointed, resumable):
             .venv/bin/python scripts/model_lab/benchmark_suite.py --runtime-dir $RUNTIME --run --confirm-model-calls --serve
  report:    .venv/bin/python scripts/model_lab/suite_report.py --runtime-dir $RUNTIME
EOF
