#!/usr/bin/env bash
#
# One What-If readiness cycle: run everything that can fail, record what did.
#
#     scripts/whatif_readiness_cycle.sh <cycle-number>
#
# A cycle is not a test run. It is the question "if I stopped here, what would
# somebody find?" asked in every way the repository knows how to ask it — lint,
# the unit and property suites, the evaluation corpus, the red team, the fifteen
# browser journeys against a real Chromium, the manual-failure journeys, the
# performance budgets, and the integration contract against the book on disk.
#
# It does NOT stop at the first failure. A cycle that halts on lint tells you
# nothing about the journeys, and the whole point is the full picture: three
# cycles are only evidence if each one saw everything.
#
# Preconditions, and they are checked rather than assumed: the API on :8000 and
# the web app on :3000 must be up. A cycle that skipped the browser journeys
# because Chromium was missing is the exact report that lets a broken feature
# ship, so this fails instead.
set -uo pipefail

CYCLE="${1:-1}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${ROOT}/docs/readiness"
API="${CREDITPROBE_API:-http://127.0.0.1:8000}"
WEB="${CREDITPROBE_WEB:-http://127.0.0.1:3000}"
PY="${ROOT}/.venv/bin/python"

mkdir -p "${OUT}"
LOG="${OUT}/cycle-${CYCLE}.log"
: > "${LOG}"

failed=0
declare -a RESULTS=()

step() {
  local name="$1"; shift
  echo "" | tee -a "${LOG}"
  echo "=== ${name}" | tee -a "${LOG}"
  local started; started=$(date +%s)
  if "$@" >> "${LOG}" 2>&1; then
    local took=$(( $(date +%s) - started ))
    echo "    PASS (${took}s)" | tee -a "${LOG}"
    RESULTS+=("PASS|${name}|${took}")
  else
    local code=$?
    local took=$(( $(date +%s) - started ))
    echo "    FAIL exit ${code} (${took}s)" | tee -a "${LOG}"
    RESULTS+=("FAIL|${name}|${took}")
    failed=$((failed + 1))
  fi
}

reachable() {
  curl -sf -o /dev/null -H "X-IPM-Role: ANALYST" "$1" 
}

echo "What-If readiness cycle ${CYCLE} — $(date -u +'%Y-%m-%d %H:%M UTC')" \
  | tee -a "${LOG}"
echo "API ${API} · WEB ${WEB}" | tee -a "${LOG}"

# The preconditions are a STEP, not a guard: a cycle that could not reach the
# product has to be reported as a failed cycle, not as a shorter one.
step "the API is reachable" reachable "${API}/api/v1/whatif/periods"
step "the web app is reachable" curl -sf -o /dev/null "${WEB}/what-if"

step "ruff" "${ROOT}/.venv/bin/ruff" check "${ROOT}"
step "typecheck" bash -c "cd '${ROOT}/frontend' && npx tsc --noEmit"
step "eslint" bash -c "cd '${ROOT}/frontend' && npx eslint src/"

step "What-If unit and invariant suites" \
  "${PY}" -m pytest "${ROOT}/tests/whatif/" -q
step "the evaluation corpus" \
  "${PY}" -m pytest "${ROOT}/tests/evals/test_whatif_evaluation.py" -q
step "the API surface" \
  "${PY}" -m pytest "${ROOT}/tests/api/" -q
step "the red team" \
  "${PY}" -m pytest "${ROOT}/tests/whatif/test_whatif_red_team.py" -q

step "the fifteen browser journeys" \
  node "${ROOT}/scripts/acceptance/whatif_journeys.mjs"
step "the manual-failure journeys" \
  node "${ROOT}/scripts/acceptance/whatif_manual_failures.mjs"

step "performance against budget" "${PY}" "${ROOT}/scripts/whatif_performance.py"
# The book's ECONOMICS, not only its schema. A cycle that checked the columns
# were present and the totals tied would have passed every one of the four
# defects this step exists to catch.
step "the book's economic coherence" \
  "${PY}" "${ROOT}/scripts/whatif_economic_validation.py"
step "What-If scenario economics" \
  "${PY}" "${ROOT}/scripts/whatif_scenario_economics.py"
step "the integration contract against the book on disk" \
  bash -c "curl -sf -H 'X-IPM-Role: ANALYST' '${API}/api/v1/whatif/integration/readiness' \
    | ${PY} -c 'import json,sys; b=json.load(sys.stdin); print(b[\"verdict\"]); sys.exit(0 if b[\"ready\"] else 1)'"
# `healthy` lives under `installation`: the endpoint serves the CONTRACT with
# how this installation compares nested inside it, and reading the top level
# for it silently found nothing and reported a healthy book as a failure.
step "the schema contract against the book on disk" \
  bash -c "curl -sf -H 'X-IPM-Role: ANALYST' '${API}/api/v1/whatif/schema' \
    | ${PY} -c 'import json,sys; b=json.load(sys.stdin)[\"installation\"]; print(\"healthy:\", b[\"healthy\"]); sys.exit(0 if b[\"healthy\"] else 1)'"

echo "" | tee -a "${LOG}"
echo "================================================================" | tee -a "${LOG}"
printf '%-56s %s\n' "step" "result" | tee -a "${LOG}"
for row in "${RESULTS[@]}"; do
  IFS='|' read -r status name took <<< "${row}"
  printf '%-56s %s (%ss)\n' "${name}" "${status}" "${took}" | tee -a "${LOG}"
done
echo "" | tee -a "${LOG}"
if [ "${failed}" -eq 0 ]; then
  echo "CYCLE ${CYCLE}: every step passed." | tee -a "${LOG}"
else
  echo "CYCLE ${CYCLE}: ${failed} step(s) failed. See ${LOG}" | tee -a "${LOG}"
fi

{
  echo "{"
  echo "  \"cycle\": ${CYCLE},"
  echo "  \"at\": \"$(date -u +'%Y-%m-%dT%H:%M:%SZ')\","
  echo "  \"failed\": ${failed},"
  echo "  \"steps\": ["
  first=1
  for row in "${RESULTS[@]}"; do
    IFS='|' read -r status name took <<< "${row}"
    [ ${first} -eq 1 ] || echo ","
    first=0
    printf '    {"step": "%s", "status": "%s", "seconds": %s}' \
      "${name}" "${status}" "${took}"
  done
  echo ""
  echo "  ]"
  echo "}"
} > "${OUT}/cycle-${CYCLE}.json"

exit "${failed}"
