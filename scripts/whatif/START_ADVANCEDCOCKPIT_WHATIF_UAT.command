#!/bin/bash
# Double-click me on macOS to run the What-If candidate UAT.
#
# THIS IS NOT THE ACCEPTED LAUNCHER, and it does not replace one. The accepted
# launchers in scripts/cockpit_v4/ are untouched, as is the earlier candidate
# launcher START_ADVANCED_COCKPIT_WHATIF_CANDIDATE.command. This one adds the
# preflight a UAT needs: it refuses to start on the wrong revision, on the
# wrong interpreter, or without the candidate data and models, because every
# one of those failures looks like a product defect from the audience.
#
# INSTALLATION -- this file has NOT been installed or run on a Mac. It was
# prepared in this repository on Linux, where /Users/... does not exist. To
# install it:
#
#   1. Copy it beside the accepted launchers WITHOUT replacing any of them:
#        cp scripts/whatif/START_ADVANCEDCOCKPIT_WHATIF_UAT.command \
#           ~/Desktop/CreditProbe_Launchers/
#   2. Make it executable:
#        chmod +x ~/Desktop/CreditProbe_Launchers/START_ADVANCEDCOCKPIT_WHATIF_UAT.command
#   3. Set REPO below if this checkout is not two directories above the file.
#   4. Build the candidate environment and data ONCE (about ten minutes):
#        cd <REPO>
#        python3 -m venv --system-site-packages .venv-whatif
#        .venv-whatif/bin/pip install --ignore-installed -r requirements-whatif.txt
#        .venv-whatif/bin/python scripts/whatif/seed_candidate.py --domain all
#        .venv-whatif/bin/python scripts/whatif/train_emulator.py --domain all
#   5. For a LIVE-PROVIDER UAT, export the credential in the shell you launch
#      from -- never in this file, and never in a .env that outlives the run:
#        export COCKPIT_ANTHROPIC_API_KEY='...'
#      Without it the candidate still starts and still serves both books; it
#      refuses each analytical turn at preflight instead of answering from a
#      stub, which is the honest failure but is not a live UAT.
#   6. Double-click.
#
# Ports are DISCOVERED, never taken: start_candidate.py walks upward from
# 8424/5424 and steps over any port already held, reporting the holder. An
# accepted Cockpit already running is not disturbed -- different interpreter,
# different ports, different state database, and the What-If flags are set
# only in this run's child processes.

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

# THE PREFLIGHT IS A GATE, NOT A REPORT. A non-zero exit stops here.
"$PY" scripts/whatif/uat_preflight.py "$@"
status=$?
if [ $status -ne 0 ]; then
  echo
  echo "The UAT was NOT started. Nothing was changed and no port was taken."
  read -r -p "Press return to close this window. "
  exit $status
fi

"$PY" scripts/whatif/start_candidate.py
status=$?
echo
read -r -p "Press return to close this window. "
exit $status
