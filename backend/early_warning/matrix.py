"""The published 5x5 anchor matrix — Tab 06 Section D of the corrected
workbook.

Not a formula: a table lookup, deliberately (the S&P-style precedent Tab 06
Section B cites — "a structured anchor, then discrete adjustments, then
caps"). This replaces the earlier, incorrect draft's multiplicative
Classifier Context Multiplier (`EWS = MIN(100, T&A * CCM)`), which does not
exist in the corrected workbook.

Reading the matrix (Tab 06 Section D):
  - The T&A band drives: moving down a row changes the anchor far more than
    moving across a column.
  - The Classifier band scales: it widens the outcome most in the middle of
    the T&A range, where judgement actually matters.
  - At the extremes it does less: an obligor with no live signal is not an
    alert (row VERY_LOW tops out at 22), and one with a very high T&A score
    is an alert regardless (row VERY_HIGH starts at 65).
"""

from __future__ import annotations

BAND_ORDER: tuple[str, ...] = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")

#: ANCHOR_MATRIX[ta_band][classifier_band] -> anchor score. Tab 06 Section D,
#: transcribed verbatim.
ANCHOR_MATRIX: dict[str, dict[str, int]] = {
    "VERY_LOW":  {"VERY_LOW": 5,  "LOW": 8,  "MEDIUM": 12, "HIGH": 16, "VERY_HIGH": 22},
    "LOW":       {"VERY_LOW": 15, "LOW": 20, "MEDIUM": 26, "HIGH": 33, "VERY_HIGH": 40},
    "MEDIUM":    {"VERY_LOW": 28, "LOW": 35, "MEDIUM": 43, "HIGH": 52, "VERY_HIGH": 60},
    "HIGH":      {"VERY_LOW": 45, "LOW": 54, "MEDIUM": 63, "HIGH": 72, "VERY_HIGH": 80},
    "VERY_HIGH": {"VERY_LOW": 65, "LOW": 74, "MEDIUM": 83, "HIGH": 90, "VERY_HIGH": 95},
}

for _row in BAND_ORDER:
    assert set(ANCHOR_MATRIX[_row]) == set(BAND_ORDER), _row


def anchor(ta_band: str, classifier_band: str) -> int:
    """Tab 06 Section D: read the anchor off the published matrix."""
    try:
        row = ANCHOR_MATRIX[ta_band]
    except KeyError:
        raise ValueError(f"unknown T&A band {ta_band!r}") from None
    try:
        return row[classifier_band]
    except KeyError:
        raise ValueError(f"unknown Classifier band {classifier_band!r}") from None
