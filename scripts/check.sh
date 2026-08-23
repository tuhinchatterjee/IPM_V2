#!/usr/bin/env bash
#
# Run every quality gate. Use this before committing.
#
#     ./scripts/check.sh
#
# Checks, in order:
#   1. Python linting (ruff)
#   2. Python tests (pytest)
#   3. Frontend type checking (TypeScript)
#   4. Frontend linting (ESLint)
#   5. Frontend production build (Next.js)
#
# Exits non-zero if anything fails, and says which one.
#
set -uo pipefail
cd "$(dirname "$0")/.."

BOLD=$'\033[1m'; GREEN=$'\033[32m'; RED=$'\033[31m'; RESET=$'\033[0m'
FAILED=()

run() {
  local name="$1"; shift
  echo; echo "${BOLD}▸ $name${RESET}"
  if "$@"; then
    echo "  ${GREEN}✓ $name passed${RESET}"
  else
    echo "  ${RED}✗ $name FAILED${RESET}"
    FAILED+=("$name")
  fi
}

PY=".venv/bin/python"
[ -x "$PY" ] || PY=".venv/Scripts/python.exe"
[ -x "$PY" ] || PY="python3"

run "Python lint (ruff)"       "$PY" -m ruff check .
run "Python tests (pytest)"    "$PY" -m pytest -q
run "Frontend typecheck"       npm --prefix frontend run typecheck
run "Frontend lint"            npm --prefix frontend run lint
run "Frontend build"           npm --prefix frontend run build

echo
if [ ${#FAILED[@]} -eq 0 ]; then
  echo "${GREEN}${BOLD}All checks passed.${RESET}"
  exit 0
fi
echo "${RED}${BOLD}${#FAILED[@]} check(s) failed:${RESET}"
printf '  %s\n' "${FAILED[@]}"
exit 1
