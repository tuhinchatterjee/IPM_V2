#!/usr/bin/env bash
#
# Build a RELEASE-tagged CreditProbe image, and refuse to if the intelligence
# has not been certified.
#
# The rule
# --------
# A release image must carry a frozen Intelligence Release that PASSED against
# the sealed holdout, and that certification must name the commit being built.
# Anything else is a development image: still buildable with the ordinary
# `docker compose up --build`, still perfectly usable, and honest about
# reporting UNCERTIFIED on its build page.
#
# What this does NOT do
# ---------------------
# Touch the API key. Certification runs against the deterministic governed
# reader unless a provider is configured in the shell that runs it, and the key
# is never passed as a build argument — a build argument is recorded in the
# image history, where anyone who pulls the image can read it.
#
#   ./scripts/release.sh              certify, then build if it passed
#   ./scripts/release.sh --check      certify and report; build nothing
#
set -euo pipefail

cd "$(dirname "$0")/.."

CHECK_ONLY=0
[[ "${1:-}" == "--check" ]] && CHECK_ONLY=1

PYTHON="${PYTHON:-.venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="python3"

GIT_SHA="$(git rev-parse --short=8 HEAD 2>/dev/null || echo unknown)"
MANIFEST="intelligence_release/manifest.json"

echo "==> Certifying ${GIT_SHA} against the sealed holdout"
echo

# The working tree has to match what is being certified. Evidence gathered
# against uncommitted edits describes code that is not in the image.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "REFUSED: the working tree has uncommitted changes." >&2
  echo "A certification run measures the code it can see; an image built from" >&2
  echo "a dirty tree is not the code that was measured. Commit first." >&2
  exit 2
fi

set +e
PYTHONPATH=. "$PYTHON" -m intelligence_factory.certify --certify
CERTIFY_STATUS=$?
set -e

echo
if [[ $CERTIFY_STATUS -ne 0 ]]; then
  echo "REFUSED: certification did not pass." >&2
  echo "No release-tagged image will be produced. The blockers are printed" >&2
  echo "above; a local development image can still be built with" >&2
  echo "'docker compose up --build' and will report UNCERTIFIED." >&2
  exit 1
fi

# The manifest has to be about THIS commit. A stale manifest left behind by an
# earlier run is the exact mistake this check exists for.
CERTIFIED_SHA="$("$PYTHON" - "$MANIFEST" <<'PY'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as handle:
        print(json.load(handle).get("build_sha") or "")
except Exception:
    print("")
PY
)"

if [[ "$CERTIFIED_SHA" != "$GIT_SHA" ]]; then
  echo "REFUSED: ${MANIFEST} certifies '${CERTIFIED_SHA}', not '${GIT_SHA}'." >&2
  echo "The evidence describes different code." >&2
  exit 3
fi

echo "Certified ${GIT_SHA}. Manifest at ${MANIFEST}."

if [[ $CHECK_ONLY -eq 1 ]]; then
  echo "--check: stopping before the build."
  exit 0
fi

TAG="creditprobe:${GIT_SHA}"
echo
echo "==> Building ${TAG}"
docker build \
  --file docker/backend.Dockerfile \
  --build-arg GIT_SHA="${GIT_SHA}" \
  --build-arg BUILD_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  --tag "${TAG}" \
  --tag "creditprobe:release" \
  .

echo
echo "Built ${TAG} carrying the frozen Intelligence Release."
