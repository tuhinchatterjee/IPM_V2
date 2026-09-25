#!/bin/bash
# Model comparison LAB launcher. Lab-owned; the frozen launchers are untouched.
cd "$(dirname "$0")/.." || exit 1
PY="${MODEL_LAB_PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/model_lab/start.py "$@"
