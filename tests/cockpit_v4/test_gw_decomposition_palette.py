"""P6 — the decomposition taxonomy is ONE list: the server's ids and order
are the frontend palette's, so a component's colour and label cannot drift
between the engine, a chart, a reopened result and an export.

EVIDENCE LABEL: UNIT (the shared taxonomy and palette); NO MODEL.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.cockpit_v4.scenario import decomposition as dc

PALETTE = Path(__file__).resolve().parents[2] / "frontend/src/lib/viz/palette.ts"


def _drivers() -> list[tuple[str, str]]:
    text = PALETTE.read_text(encoding="utf-8")
    block = text[text.index("export const DRIVERS"):text.index("] as const")]
    return re.findall(r'\{ id: "([a-z0-9_]+)", label: "([^"]+)"', block)


def test_palette_ids_and_order_are_the_server_taxonomy():
    assert [i for i, _ in _drivers()] == list(dc.ORDER)


def test_palette_labels_are_the_server_labels():
    assert {i: label for i, label in _drivers()} == \
        {c.id: c.label for c in dc.TAXONOMY}
