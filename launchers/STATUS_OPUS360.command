#!/bin/bash
# Opus360 certification — status. Double-click in Finder or run from Terminal.
cd "$(dirname "$0")/.." || exit 1
PY=$(command -v python3 || command -v python)
if [ -z "$PY" ]; then echo "Python 3 was not found."; read -r -p "Press return to close. "; exit 1; fi
"$PY" scripts/opus360/control.py status "$@"
status=$?
echo
[ -t 0 ] && read -r -p "Press return to close this window. "
exit $status
