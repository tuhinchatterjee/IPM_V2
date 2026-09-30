#!/usr/bin/env bash
# CreditProbe Model Lab — RunPod A40 bootstrap (full Model I/O Trace).
#
#   bash RUNPOD_BOOTSTRAP.sh [--storage-check] [--skip-browser] [--skip-probe]
#                            [--skip-vllm] [--no-start]
#
# Run from the directory holding CreditProbe_Model_Lab_RunPod_FullTrace.zip,
# runpod_storage.py, checksums.sha256 and DEPLOYMENT_MANIFEST.json.
#
# STORAGE FIRST. The persistent root is detected before anything is written:
#   1. /workspace-global  a RunPod Global Volume (e.g. creditprobe-model-lab)
#   2. /workspace         a RunPod Network Volume
#   otherwise STOP: PERSISTENT_STORAGE_NOT_FOUND (exit 3). The container
#   overlay / root disk is never used. ALL benchmark state then lives under
#   <persist_root>/creditprobe-model-lab/: source, runtime store, Model I/O
#   traces, exports, oracles, Opus reference set, checkpoints, reports,
#   screenshots, logs, and the Hugging Face / vLLM / model / pip / npm /
#   Playwright caches and virtualenvs. The exports are written to
#   <persist_root>/creditprobe-model-lab/env.sh: `source` it in every new
#   shell before using the lab, serve.sh or the benchmark.
#   --storage-check stops after printing the storage verdict.
#
# Then it verifies the GPU, unpacks and installs the lab, seeds the
# deterministic synthetic data, runs the protected-manifest check and an
# offline fixture smoke test, materialises the independent oracle artifacts,
# installs vLLM, PINS every suite checkpoint to an immutable revision with an
# A40 fit preflight, PROBES each pinned, licence-clear, fitting model with the
# harmless dummy tool (this downloads those checkpoints), runs the OPUS
# REFERENCE preflight (OPUS_REFERENCE_SET_V1: which of Q01-Q15 already have a
# valid saved Opus reference, which are missing, the approved and the
# required spend), starts the lab on 127.0.0.1 and prints the suite plan.
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

SKIP_BROWSER=0; WITH_VLLM=1; START=1; PROBE=1; STORAGE_ONLY=0
for a in "$@"; do
  case "$a" in
    --storage-check) STORAGE_ONLY=1 ;;
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

echo "== 1. Persistent storage (before anything is written)"
[ -f "$HERE/runpod_storage.py" ] || die "runpod_storage.py is missing next to this script"
if [ -n "${CREDITPROBE_STORAGE_TEST_ARGS:-}" ]; then
  echo "  TEST MODE: storage detection driven by CREDITPROBE_STORAGE_TEST_ARGS (offline tests only)"
fi
STORAGE_RC=0
# shellcheck disable=SC2086
EXPORTS="$(python3 "$HERE/runpod_storage.py" --shell ${CREDITPROBE_STORAGE_TEST_ARGS:-})" || STORAGE_RC=$?
if [ "$STORAGE_RC" != 0 ]; then
  echo "  STOP: no persistent volume; nothing was written (exit 3)"
  exit 3
fi
eval "$EXPORTS"
{
  echo "# CreditProbe Model Lab on RunPod: persistent paths. source this file."
  printf '%s\n' "$EXPORTS"
  echo "export COCKPIT_AGENTIC_V3_NAMESPACE=cockpit_v4"
  echo "export MODEL_LAB_FULL_IO_TRACE=true"
  echo "export MODEL_LAB_PYTHON=\"\$CREDITPROBE_SOURCE_DIR/.venv/bin/python\""
  echo "export VLLM_BIN=\"\$CREDITPROBE_VENV_DIR/vllm/bin/vllm\""
} > "$CREDITPROBE_HOME/env.sh"
# shellcheck disable=SC1091
source "$CREDITPROBE_HOME/env.sh"
APP="$CREDITPROBE_SOURCE_DIR"
RUNTIME="$MODEL_LAB_RUNTIME_DIR"
ok "persistent root $PERSIST_ROOT ($PERSIST_KIND); env: $CREDITPROBE_HOME/env.sh"
if [ "$STORAGE_ONLY" = 1 ]; then
  echo "storage check only (--storage-check): stopping here"
  exit 0
fi
LOG="$CREDITPROBE_LOG_DIR/bootstrap-$(date -u +%Y%m%dT%H%M%SZ).log"
exec > >(tee -a "$LOG") 2>&1
echo "  bootstrap log: $LOG"

echo "== 2. GPU"
command -v nvidia-smi >/dev/null || die "nvidia-smi not found: not a GPU pod"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader \
  | tee /dev/stderr | grep -qi "A40" || echo "  WARN GPU is not an A40; the suite's memory arithmetic assumes 48 GB"
ok "NVIDIA GPU present"

echo "== 3. Verify and unpack into $APP"
cd "$HERE"
sha256sum -c checksums.sha256 || die "bundle checksum mismatch"
mkdir -p "$APP"
# Unpack into the persistent source dir (strip the zip's top-level folder);
# the existing .venv and node_modules there are kept across restarts.
python3 - "$APP" <<'EOF'
import sys, zipfile
from pathlib import Path
dest = Path(sys.argv[1])
with zipfile.ZipFile("CreditProbe_Model_Lab_RunPod_FullTrace.zip") as z:
    for m in z.infolist():
        name = m.filename.split("/", 1)[1] if "/" in m.filename else ""
        if not name or m.is_dir():
            continue
        out = dest / name
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(z.read(m))
EOF
cd "$APP"
# zipfile does not restore Unix modes: make the launchers executable again.
find . -type f \( -name '*.sh' -o -name '*.command' \) -exec chmod +x {} +
python3 - <<'EOF' || die "unpacked files do not match DEPLOYMENT_MANIFEST.json"
import hashlib, json, pathlib
m = json.loads(pathlib.Path("DEPLOYMENT_MANIFEST.json").read_text())
bad = [p for p, f in m["files"].items()
       if hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest() != f["sha256"]]
assert not bad, bad[:5]
print(f"  {len(m['files'])} files match the manifest (source {m['source_commit'][:12]})")
EOF
ok "unpacked to $APP"

echo "== 4. Python and Node dependencies"
if ! command -v uv >/dev/null; then python3 -m pip install -q uv || true; fi
if command -v uv >/dev/null; then
  uv venv -q -p 3.12 .venv && uv pip install -q -p .venv/bin/python -r requirements.txt pytest ruff
else
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt pytest ruff
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
# runtime, reference set or evidence directory.
env -u MODEL_LAB_RUNTIME_DIR -u MODEL_LAB_REFERENCE_SET_DIR -u LAB_EVIDENCE_DIR \
  .venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/model_lab/test_model_io_trace.py tests/model_lab/test_observer_neutrality.py \
  tests/model_lab/test_saved_reference.py tests/model_lab/test_assisted_lane.py \
  tests/model_lab/test_benchmark_oracles.py tests/model_lab/test_runpod_suite.py \
  tests/model_lab/test_opus_reference_set.py tests/model_lab/test_runpod_storage.py \
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
persistent paths (all under $CREDITPROBE_HOME; in a new shell: source $CREDITPROBE_HOME/env.sh):
  source       $CREDITPROBE_SOURCE_DIR
  runtime      $MODEL_LAB_RUNTIME_DIR  (store, Model I/O traces, exports, oracles, checkpoints, reports, pins, run logs)
  opus refs    $MODEL_LAB_REFERENCE_SET_DIR
  results      $CREDITPROBE_RESULTS_DIR  (screenshots: $LAB_EVIDENCE_DIR)
  logs         $CREDITPROBE_LOG_DIR
  model cache  $MODEL_CACHE_DIR   HF_HOME=$HF_HOME   VLLM_CACHE_ROOT=$VLLM_CACHE_ROOT
  venvs        $CREDITPROBE_VENV_DIR

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
