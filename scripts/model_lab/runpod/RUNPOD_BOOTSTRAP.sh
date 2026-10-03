#!/usr/bin/env bash
# CreditProbe Model Lab — RunPod GPU bootstrap (full Model I/O Trace; A40 48 GB, RTX PRO 6000 96 GB, ...).
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
#   --smoke-only     deployment + app rebuild + offline smoke gate + gated
#                    pin restore, then stop; on a fresh Pod it first builds
#                    the Pod-local offline Python env (no GPU, no Node)
#
# OFFLINE SMOKE GATE. The offline tests run against the PRISTINE committed
# bundle (verified file by file against DEPLOYMENT_MANIFEST.json before and
# after), in a clean environment (env -i), with isolated HOME/TMPDIR.
# Persistent pinned identities are restored into the source profiles ONLY
# after the gate passes (restore-pins refuses otherwise). A failure prints
# OFFLINE_SMOKE_TEST_FAILED and stops before any vLLM install or probe.
#
# Then: GPU + hardware identity (RTX PRO 6000 96 GB, A40 48 GB, ...),
# Python/Node installs (app root only), seeding, protected-manifest check,
# the offline smoke gate, the gated pin restore, oracle artifacts, the
# GPU DRIVER / CUDA gate for vLLM 0.30.0 (VLLM_HOST_DRIVER_INCOMPATIBLE stops
# before any vLLM install or probe; nothing is worked around), the vLLM
# environment (verified wheel, CI-locked dependencies), pin + CURRENT-HOST
# fit (historical A40 evidence kept separately), the
# runtime preflight (versions, parser registry, model imports; manifest on
# the volume), probes (downloads pinned checkpoints into the persistent
# model cache), OPUS REFERENCE preflight, suite plan, lab start.
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
SMOKE_ONLY=0
for a in "$@"; do
  case "$a" in
    --storage-check) STORAGE_ONLY=1 ;;
    --prepare-only) PREPARE_ONLY=1 ;;
    --smoke-only) SMOKE_ONLY=1 ;;
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
ok "app source at $APP: the committed bundle, pristine (persistent pins NOT applied yet)"
if [ "$PREPARE_ONLY" = 1 ]; then
  echo "prepare only (--prepare-only): stopping before installs"
  exit 0
fi

# Pod-local Python environment for the lab and its offline tests (app root
# only; never the persistent volume). Idempotent.
install_python_env() {
  if ! command -v uv >/dev/null; then python3 -m pip install -q uv || true; fi
  if command -v uv >/dev/null; then
    [ -x .venv/bin/python ] || uv venv -q -p 3.12 .venv
    uv pip install -q -p .venv/bin/python -r requirements.txt pytest ruff
  else
    [ -x .venv/bin/python ] || python3 -m venv .venv
    .venv/bin/pip install -q -r requirements.txt pytest ruff
  fi
}

# ---- offline smoke gate: pristine source, isolated environment ----------------
# The smoke tests must see exactly the committed bundle: no persistent pins,
# approvals, probes, reference sets, runtime state or operator variables.
# Persistent pinned identities are applied ONLY after this gate passes.
smoke_gate() {
  local py="${CREDITPROBE_SMOKE_PYTHON:-$APP/.venv/bin/python}"
  local targets="${CREDITPROBE_SMOKE_TARGETS:-tests/model_lab --ignore=tests/model_lab/browser}"
  local tmp="$CREDITPROBE_APP_ROOT/tmp/smoke-$(date -u +%Y%m%dT%H%M%SZ)"
  mkdir -p "$tmp/home" "$tmp/tmp"
  if ! storage "$DEPLOY/runpod_storage.py" verify-pristine; then
    echo "OFFLINE_SMOKE_TEST_FAILED: source is not pristine before the smoke tests"
    echo "  stopping before vLLM install and probe; no model call, no Opus call"
    exit 11
  fi
  echo "  running in a clean environment (env -i), HOME/TMPDIR under $tmp"
  local rc=0
  # shellcheck disable=SC2086
  (cd "$APP" && env -i PATH="$PATH" HOME="$tmp/home" TMPDIR="$tmp/tmp" \
      LANG=C.UTF-8 LC_ALL=C.UTF-8 \
      COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4 MODEL_LAB_FULL_IO_TRACE=true \
      "$py" -m pytest -q -p no:cacheprovider --junitxml="$tmp/junit.xml" \
      $targets) || rc=$?
  if ! storage "$DEPLOY/runpod_storage.py" smoke-pass --junit "$tmp/junit.xml"; then
    echo "OFFLINE_SMOKE_TEST_FAILED (pytest exit $rc; report $tmp/junit.xml)"
    echo "  stopping before vLLM install and probe; no model call, no Opus call"
    exit 11
  fi
  ok "offline smoke tests passed on the pristine bundle"
  echo "== 7b. Restore persistent pinned identities (only now, after the smoke gate)"
  storage "$DEPLOY/runpod_storage.py" restore-pins || die "pin restore refused"
}

if [ "$SMOKE_ONLY" = 1 ]; then
  echo "== 7. Offline smoke gate (--smoke-only: no GPU, no Node; Pod-local Python env built if missing)"
  SMOKE_PY="${CREDITPROBE_SMOKE_PYTHON:-$APP/.venv/bin/python}"
  if [ ! -x "$SMOKE_PY" ]; then
    # a fresh Pod: build the minimum offline environment (Pod-local only;
    # it reads nothing from the volume, so the gate stays first)
    echo "  fresh Pod: installing the Pod-local offline Python environment"
    install_python_env || die "offline Python environment install failed"
  fi
  [ -x "$SMOKE_PY" ] || die "no Python for the offline tests at $SMOKE_PY"
  if [ -f scripts/cockpit_v4/seed_domains.py ]; then
    # the tests need the deterministic synthetic data (never persistent state)
    (export COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4
     "$SMOKE_PY" scripts/cockpit_v4/seed_domains.py --verify >/dev/null 2>&1 \
       || "$SMOKE_PY" scripts/cockpit_v4/seed_domains.py >/dev/null) \
      || die "seeding the synthetic data failed"
  fi
  smoke_gate
  echo "smoke only (--smoke-only): stopping after the gated restore"
  exit 0
fi

echo "== 3b. GPU and hardware identity (persisted; drives the current-host fit)"
command -v nvidia-smi >/dev/null || die "nvidia-smi not found: not a GPU pod"
python3 scripts/model_lab/runpod/hardware.py detect --runtime-dir "$RUNTIME" \
  || die "GPU memory could not be detected"
ok "hardware recorded in $RUNTIME/hardware/CURRENT_HOST.json"

echo "== 4. Python and Node dependencies (app root only)"
install_python_env
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

echo "== 7. Offline smoke gate: ALL offline lab tests on the pristine bundle (no model)"
smoke_gate

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

echo "== 9. GPU driver / CUDA preflight for vLLM (before any vLLM install or probe; no model)"
VLLM_STATE=READY; HOST_RC=0
.venv/bin/python scripts/model_lab/runpod/vllm_runtime.py host --runtime-dir "$RUNTIME" || HOST_RC=$?
if [ "$HOST_RC" = 7 ]; then
  VLLM_STATE=VLLM_HOST_DRIVER_INCOMPATIBLE
  echo "  STOP before vLLM install and model probe: VLLM_HOST_DRIVER_INCOMPATIBLE"
  echo "  (recorded in $RUNTIME/vllm_runtime/RUNTIME_MANIFEST.json; pinning and the Opus preflight still run)"
elif [ "$HOST_RC" != 0 ]; then
  VLLM_STATE=HOST_CHECK_FAILED; echo "  WARN host check failed (exit $HOST_RC); no probe"
fi

VENV_VLLM="$CREDITPROBE_VENV_DIR/vllm"
if [ "$VLLM_STATE" = READY ] && { [ "$WITH_VLLM" = 1 ] || [ "$PROBE" = 1 ]; }; then
  echo "== 9b. vLLM 0.30.0 environment (Pod-local; Python 3.12; verified wheel; CI-locked dependencies)"
  [ -x "$VENV_VLLM/bin/python" ] || uv venv -q -p 3.12 "$VENV_VLLM"
  WHEEL="$(.venv/bin/python scripts/model_lab/runpod/vllm_runtime.py fetch-wheel --dest "$CREDITPROBE_APP_ROOT/cache/wheels")" \
    || die "vLLM wheel sha256 does not match the recorded identity"
  uv pip install -q -p "$VENV_VLLM/bin/python" "$WHEEL" \
    -c scripts/model_lab/runpod/vllm-0.30.0-constraints.txt || die "vLLM environment install failed"
  ok "vLLM installed in $VENV_VLLM (wheel $(basename "$WHEEL"), sha256 verified)"
elif [ "$VLLM_STATE" = READY ]; then
  echo "  vLLM not installed (--skip-vllm); serve.sh expects $VENV_VLLM/bin/vllm"
fi

echo "== 10. Checkpoint pin + CURRENT-HOST fit (metadata only, no weights; historical A40 evidence kept)"
.venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir "$RUNTIME" \
  || echo "  WARN pinning reported errors; see $RUNTIME/pins/ROSTER.json"

if [ "$VLLM_STATE" = READY ] && [ -x "$VENV_VLLM/bin/python" ]; then
  echo "== 10b. vLLM runtime preflight: versions, parser registry, model imports (no model, no weights)"
  PRE_RC=0
  .venv/bin/python scripts/model_lab/runpod/vllm_runtime.py preflight --runtime-dir "$RUNTIME" \
    --venv-python "$VENV_VLLM/bin/python" || PRE_RC=$?
  case "$PRE_RC" in
    0) ;;
    7) VLLM_STATE=VLLM_HOST_DRIVER_INCOMPATIBLE; echo "  STOP before model probe: VLLM_HOST_DRIVER_INCOMPATIBLE (CUDA init on this host)" ;;
    9) VLLM_STATE=VLLM_RUNTIME_INCOMPATIBLE; echo "  STOP before model probe: installed environment differs from the lock" ;;
    *) VLLM_STATE=VLLM_RUNTIME_INCOMPATIBLE; echo "  STOP before model probe: runtime preflight failed (exit $PRE_RC)" ;;
  esac
fi

if [ "$PROBE" = 1 ] && [ "$VLLM_STATE" = READY ]; then
  echo "== 11. Capability probe: runtime-ready, pinned, licence-clear, fitting models only"
  echo "   downloads each such checkpoint into $MODEL_CACHE_DIR (HF_HOME=$HF_HOME); dummy tool only; no benchmark question"
  .venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir "$RUNTIME" --probe \
    || echo "  WARN probe step reported errors; see $RUNTIME/pins/ROSTER.json"
elif [ "$PROBE" = 1 ]; then
  echo "== 11. Capability probe NOT run: $VLLM_STATE"
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

if [ "$VLLM_STATE" != READY ]; then
  HEAD_LINE="$VLLM_STATE — NO MODEL PROBED; NO MODEL CALLS"
  .venv/bin/python scripts/model_lab/runpod/vllm_runtime.py show --runtime-dir "$RUNTIME" 2>/dev/null | sed 's/^/  /' || true
elif [ "$REF_STATE" = READY ]; then
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
  vLLM runtime: $VLLM_STATE ($RUNTIME/vllm_runtime/RUNTIME_MANIFEST.json)
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
  failures:  .venv/bin/python scripts/model_lab/runpod/pin_and_probe_models.py --runtime-dir $RUNTIME --summary
             (class, repository@revision, server log path, return code, root cause, workaround)
EOF
