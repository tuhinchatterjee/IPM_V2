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
VLLM="${VLLM_BIN:-$CREDITPROBE_HOME/venvs/vllm/bin/vllm}"

read -r REPO REV CTX PARSER EXTRA < <("$PY" - "$PID" <<'EOF'
import json, sys
p = json.load(open(f"profiles/{sys.argv[1]}.json"))
a, r = p.get("artifact") or {}, p.get("runpod") or {}
if p.get("status") in ("DISCOVERED", "BLOCKED_RESOURCE", "DISABLED", "PIN_BLOCKED"):
    sys.exit(f"refusing: {sys.argv[1]} is {p['status']}: {p.get('status_reason')}")
if not a.get("repository") or not a.get("revision"):
    sys.exit("refusing: no pinned repository@revision (runpod/pin_and_probe_models.py)")
if not r.get("suggested_tool_call_parser"):
    sys.exit("refusing: no tool-call parser qualified for this family")
print(a["repository"], a["revision"], p["context_tokens"],
      r["suggested_tool_call_parser"], " ".join(r.get("extra_args") or []) or "-")
EOF
)
[ "$EXTRA" = "-" ] && EXTRA=""
mkdir -p "$MODEL_CACHE_DIR" "$MODEL_LAB_RUNTIME_DIR/logs"
echo "serving $REPO@$REV (max_model_len=$CTX, tool parser=$PARSER) on 127.0.0.1:8000"
# shellcheck disable=SC2086
exec "$VLLM" serve "$REPO" --revision "$REV" --served-model-name "$REPO" \
  --host 127.0.0.1 --port 8000 --max-model-len "$CTX" \
  --download-dir "$MODEL_CACHE_DIR" --enable-auto-tool-choice \
  --tool-call-parser "$PARSER" $EXTRA
