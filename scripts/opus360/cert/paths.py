"""Filesystem locations. One place, so no module guesses a path."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CERT_DIR = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts" / "opus360"
CONFIG = ROOT / "config" / "opus360"
DOCS = ROOT / "docs" / "opus360"
ARTIFACTS = ROOT / "artifacts" / "opus360"

BANK_PATH = CONFIG / "question_bank.v1.yaml"
BANK_SHA_PATH = CONFIG / "question_bank.v1.sha256"
PROTECTED_MANIFEST = CONFIG / "protected_manifest.v1.json"
SUITE_PATH = CONFIG / "suite.architecture-v1.yaml"


def ensure_import_path() -> None:
    """Make `backend` (the frozen product) and `cert` importable."""
    for p in (str(ROOT), str(SCRIPTS)):
        if p not in sys.path:
            sys.path.insert(0, p)
