#!/usr/bin/env bash
# CreditProbe Model Lab — RunPod A40 bootstrap (full Model I/O Trace).
#
#   bash RUNPOD_BOOTSTRAP.sh [--skip-browser] [--with-vllm] [--no-start]
#
# Run from the directory holding CreditProbe_Model_Lab_RunPod_FullTrace.zip,
# checksums.sha256 and DEPLOYMENT_MANIFEST.json. It verifies the GPU and
# /workspace, unpacks and installs the lab, seeds the deterministic synthetic
# data, runs the protected-manifest check and an offline fixture smoke test,
# starts the lab services on 127.0.0.1, and prepares the benchmark runner.
#
# It performs NO model inference and downloads NO model weights. Serving a
# model (scripts/model_lab/runpod/serve.sh) and running the suite
# (scripts/model_lab/benchmark_suite.py --run --confirm-model-calls) are
# separate, deliberate operator steps.
set -euo pipefail

SKIP_BROWSER=0; WITH_VLLM=0; START=1
for a in "$@"; do
  case "$a" in
    --skip-browser) SKIP_BROWSER=1 ;;
    --with-vllm) WITH_VLLM=1 ;;
    --no-start) START=0 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
WS="${WORKSPACE:-/workspace}"
APP="$WS/creditprobe-model-lab"
RUNTIME="$WS/lab-runtime"
ok() { printf '  \033[32mOK\033[0m %s\n' "$*"; }
die() { printf '  \033[31mFAIL\033[0m %s\n' "$*"; exit 1; }

echo "== 1. GPU"
command -v nvidia-smi >/dev/null || die "nvidia-smi not found: not a GPU pod"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader \
  | tee /dev/stderr | grep -qi "A40" || echo "  WARN GPU is not an A40; the suite's memory arithmetic assumes 48 GB"
ok "NVIDIA GPU present"

echo "== 2. Persistent storage"
[ -d "$WS" ] && [ -w "$WS" ] || die "$WS is missing or not writable (attach a network/persistent volume)"
FREE_GB=$(df -BG --output=avail "$WS" | tail -1 | tr -dc 0-9)
[ "${FREE_GB:-0}" -ge 60 ] || echo "  WARN only ${FREE_GB} GB free on $WS; model weights need 60+ GB across the suite"
ok "$WS writable (${FREE_GB} GB free)"

echo "== 3. Verify and unpack"
cd "$HERE"
sha256sum -c checksums.sha256 || die "bundle checksum mismatch"
mkdir -p "$APP"
python3 -c "import zipfile,sys; zipfile.ZipFile('CreditProbe_Model_Lab_RunPod_FullTrace.zip').extractall(sys.argv[1])" "$WS"
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
.venv/bin/python -m pytest -q -p no:cacheprovider \
  tests/model_lab/test_model_io_trace.py tests/model_lab/test_observer_neutrality.py \
  tests/model_lab/test_saved_reference.py || die "fixture smoke test failed"
ok "fixture smoke test passed (full Model I/O Trace on)"

echo "== 8. Benchmark runner (plan only)"
mkdir -p "$RUNTIME"
.venv/bin/python scripts/model_lab/benchmark_suite.py --runtime-dir "$RUNTIME"
.venv/bin/python scripts/model_lab/verify_checkpoints.py || echo "  WARN checkpoint lookup failed (network?)"
if [ "$WITH_VLLM" = 1 ]; then
  python3 -m venv "$WS/vllm-venv" && "$WS/vllm-venv/bin/pip" install -q vllm
  ok "vLLM installed in $WS/vllm-venv (no model served)"
else
  echo "  vLLM not installed (pass --with-vllm); serve.sh expects $WS/vllm-venv/bin/vllm"
fi

if [ "$START" = 1 ]; then
  echo "== 9. Start Model Lab services (127.0.0.1 only)"
  MODEL_LAB_RUNTIME_DIR="$RUNTIME" MODEL_LAB_PYTHON=.venv/bin/python \
    ./launchers/START_MODEL_LAB.command --runtime-dir "$RUNTIME"
  echo "  From your machine: ssh -L 5424:127.0.0.1:5424 -L 8424:127.0.0.1:8424 <pod-ssh>"
  echo "  then open http://127.0.0.1:5424/cockpit/lab"
fi

cat <<EOF

READY — no model has been called.
Next, one model at a time:
  1. .venv/bin/python scripts/model_lab/verify_checkpoints.py --pin <profile>=<repo>@<sha>
  2. scripts/model_lab/runpod/serve.sh <profile>            (downloads that checkpoint)
  3. LAB_VLLM_OPENAI_URL=http://127.0.0.1:8000/v1 .venv/bin/python scripts/model_lab/probe.py --profile <profile> --runtime-dir $RUNTIME
  4. .venv/bin/python scripts/model_lab/benchmark_suite.py --runtime-dir $RUNTIME --model <profile> --lane FROZEN_BASELINE --run --confirm-model-calls
EOF
