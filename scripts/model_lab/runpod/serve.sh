#!/usr/bin/env bash
# Serve ONE RunPod profile with vLLM on 127.0.0.1:8000 (OpenAI-compatible).
#
#   scripts/model_lab/runpod/serve.sh qwen3.5-4b-runpod
#
# Downloads the pinned checkpoint on first use (a deliberate operator action)
# into $MODEL_CACHE_DIR on the persistent volume. Needs the environment from
# <persist_root>/creditprobe-model-lab/env.sh (written by RUNPOD_BOOTSTRAP.sh)
# and refuses to run without it, so nothing lands on the container disk.
# Refuses a profile without a pinned revision or without
# a tool-call parser, and never substitutes another checkpoint. Stop with
# Ctrl-C; one resident model at a time on the A40.
set -euo pipefail
cd "$(dirname "$0")/../../.."
PID="${1:?usage: serve.sh <profile-id>}"
PY="${MODEL_LAB_PYTHON:-.venv/bin/python}"
: "${CREDITPROBE_HOME:?not set: source <persist_root>/creditprobe-model-lab/env.sh (RUNPOD_BOOTSTRAP.sh writes it)}"
: "${MODEL_CACHE_DIR:?not set: source \$CREDITPROBE_HOME/env.sh}"
: "${MODEL_LAB_RUNTIME_DIR:?not set: source \$CREDITPROBE_HOME/env.sh}"
: "${HF_HOME:?not set: source \$CREDITPROBE_HOME/env.sh}"
: "${CREDITPROBE_VENV_DIR:?not set: source \$CREDITPROBE_HOME/env.sh}"
# The vLLM executable is Pod-local (app root); the weights it downloads go
# to the persistent model cache on the volume.
VLLM="${VLLM_BIN:-$CREDITPROBE_VENV_DIR/vllm/bin/vllm}"

read -r REPO REV CTX PARSER EXTRA < <("$PY" - "$PID" <<'EOF'
import json, sys
p = json.load(open(f"profiles/{sys.argv[1]}.json"))
a, r = p.get("artifact") or {}, p.get("runpod") or {}
if p.get("status") in ("DISCOVERED", "BLOCKED_RESOURCE", "DISABLED", "PIN_BLOCKED"):
    sys.exit(f"refusing: {sys.argv[1]} is {p['status']}: {p.get('status_reason')}")
if not a.get("repository") or not a.get("revision"):
    sys.exit("refusing: no pinned repository@revision (runpod/pin_and_probe_models.py)")
if not r.get("suggested_tool_call_parser"):
    sys.exit("refusing: TOOL_PARSER_MISSING (no registered tool-call parser "
             "assigned; pin_and_probe_models.py assigns and verifies it)")
import os, pathlib
man = pathlib.Path(os.environ["MODEL_LAB_RUNTIME_DIR"]) / "vllm_runtime" / "RUNTIME_MANIFEST.json"
if man.exists():
    v = json.loads(man.read_text())["verdict"]
    if v["status"] != "COMPATIBLE":
        sys.exit(f"refusing: VLLM_HOST_DRIVER_INCOMPATIBLE: driver "
                 f"{v['driver_version']} < {v['minimum_required_driver']} "
                 f"for vLLM {v['vllm_version']} (CUDA {v['vllm_cuda']}); "
                 f"{v['remediation']}")
extra = list(r.get("extra_args") or [])
if r.get("reasoning_parser"):
    extra += ["--reasoning-parser", r["reasoning_parser"]]
print(a["repository"], a["revision"], p["context_tokens"],
      r["suggested_tool_call_parser"], " ".join(extra) or "-")
EOF
)
[ "$EXTRA" = "-" ] && EXTRA=""
# Hardware-specific server environment recorded by the runtime preflight
# (e.g. VLLM_USE_FLASHINFER_SAMPLER=0 on Blackwell SM120); printed, then
# exported for vLLM. Nothing is applied that the manifest does not record.
SERVER_ENV="$("$PY" - <<'EOF'
import json, os, pathlib, shlex
man = pathlib.Path(os.environ["MODEL_LAB_RUNTIME_DIR"]) / "vllm_runtime" / "RUNTIME_MANIFEST.json"
se = (json.loads(man.read_text()).get("server_env") or {}) if man.exists() else {}
for k, v in (se.get("env") or {}).items():
    print(f"export {k}={shlex.quote(str(v))}")
sb = se.get("sampling_backend") or {}
if sb.get("flashinfer_sampler") == "disabled":
    print(f"echo {shlex.quote('workaround: FlashInfer sampler disabled (' + str(sb.get('reason')) + '; fallback ' + str(sb.get('fallback')) + ')')}")
EOF
)"
eval "$SERVER_ENV"
mkdir -p "$MODEL_CACHE_DIR" "$MODEL_LAB_RUNTIME_DIR/logs"
echo "serving $REPO@$REV (max_model_len=$CTX, tool parser=$PARSER) on 127.0.0.1:8000"
# shellcheck disable=SC2086
exec "$VLLM" serve "$REPO" --revision "$REV" --served-model-name "$REPO" \
  --host 127.0.0.1 --port 8000 --max-model-len "$CTX" \
  --download-dir "$MODEL_CACHE_DIR" --enable-auto-tool-choice \
  --tool-call-parser "$PARSER" $EXTRA
