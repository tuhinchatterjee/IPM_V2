#!/bin/bash
# Double-click on macOS: STATUS the Guided Risk Workspace live-provider UAT.
# See docs/guided_workspace/MAC_LIVE_UAT.md. Prepared and dry-run on Linux;
# the live run on a Mac is the user's acceptance gate (P14).
REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || { echo "Could not find the repository."; exit 1; }
PY="$REPO/.venv-whatif/bin/python"
if [ ! -x "$PY" ]; then
  echo "Build the candidate environment first (docs/guided_workspace/MAC_LIVE_UAT.md, step 2)."
  read -r -p "Press return to close. "; exit 1
fi
"$PY" scripts/cockpit_v4/status.py --runtime-dir "$HOME/.creditprobe/guided_workspace_uat" "$@"
status=$?
echo
read -r -p "Press return to close this window. "
exit $status
