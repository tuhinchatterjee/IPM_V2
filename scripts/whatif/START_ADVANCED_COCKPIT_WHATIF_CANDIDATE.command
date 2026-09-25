#!/bin/bash
# Double-click me on macOS. Runs ONLY the What-If candidate.
#
# It does not touch an accepted Cockpit that is already running: different
# ports (discovered at runtime, never taken from a holder), a different
# interpreter and a different state database.
#
# INSTALLATION -- this file has NOT been installed or tested on a Mac.
# It was prepared in this repository on Linux. To install it:
#
#   1. Copy this file to the launcher folder, e.g.
#        cp scripts/whatif/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command \
#           ~/Desktop/CreditProbe_Launchers/
#   2. Make it executable:
#        chmod +x ~/Desktop/CreditProbe_Launchers/START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command
#   3. Edit REPO below to the absolute path of this checkout on the Mac.
#   4. Build the candidate environment once:
#        cd <REPO>
#        python3 -m venv --system-site-packages .venv-whatif
#        .venv-whatif/bin/pip install --ignore-installed -r requirements-whatif.txt
#   5. Build the candidate data once (about three minutes):
#        .venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all
#        .venv-whatif/bin/python scripts/whatif/train_emulator.py --domain all
#   6. Double-click.
#
# The accepted launchers in scripts/cockpit_v4/ are unchanged. Do not
# replace them with this one.

REPO="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO" || { echo "Could not find the repository."; exit 1; }

PY="$REPO/.venv-whatif/bin/python"
if [ ! -x "$PY" ]; then
  echo "The candidate environment is not built at:"
  echo "    $PY"
  echo
  echo "Build it once with:"
  echo "    cd $REPO"
  echo "    python3 -m venv --system-site-packages .venv-whatif"
  echo "    .venv-whatif/bin/pip install --ignore-installed -r requirements-whatif.txt"
  echo
  echo "The accepted Cockpit does not need this and is unaffected."
  read -r -p "Press return to close. "
  exit 1
fi

"$PY" scripts/whatif/start_candidate.py "$@"
status=$?
echo
read -r -p "Press return to close this window. "
exit $status
