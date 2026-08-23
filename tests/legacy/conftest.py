"""
Test configuration for the preserved Dash application (`legacy/dash_app/`).

The Dash UI is no longer the product front end — Next.js is (see
docs/ARCHITECTURE.md §7). The application is kept, working and tested, because
it contains proven analytical screens and behaviour worth referring back to
while the React front end is built.

These tests import `app` and `frontend.*`, which live inside legacy/dash_app/.
Putting that directory on sys.path lets them keep passing unchanged rather than
rewriting seven working suites for a directory move.
"""

import sys
from pathlib import Path

LEGACY_DASH_APP = Path(__file__).resolve().parents[2] / "legacy" / "dash_app"
if str(LEGACY_DASH_APP) not in sys.path:
    sys.path.insert(0, str(LEGACY_DASH_APP))
