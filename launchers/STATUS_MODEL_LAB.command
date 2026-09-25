#!/bin/bash
cd "$(dirname "$0")/.." || exit 1
PY="${MODEL_LAB_PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3
exec "$PY" scripts/model_lab/status.py "$@"
