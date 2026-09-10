"""
Exports: the same numbers as the screen, in a file that cannot execute.

Two hazards, both handled here rather than in each caller.

The first is spreadsheet formula injection. A cell that begins `=`, `+`, `-` or
`@` is a formula to Excel and to Sheets, and a value that reached the export
from user-controlled text — a scenario name, a filter label, a comment — can
therefore run when someone opens the file. Every such cell is prefixed with an
apostrophe, which the spreadsheet strips on display and does not execute.

The second is non-finite JSON. `NaN` and `Infinity` are not JSON, and a client
that receives them either throws or silently reads a null as a zero. Anything
non-finite becomes an explicit null with the reason recorded alongside it.
"""

from __future__ import annotations

import io
import json
import math
from typing import Any

import numpy as np
import pandas as pd

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

DISCLOSURE = (
    "Synthetic Saudi retail demonstration data — not ANB customer data or approved models."
)


def escape_cell(value: Any) -> Any:
    """Neutralise a cell a spreadsheet would otherwise treat as a formula."""
    if not isinstance(value, str):
        return value
    if value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def to_csv(frame: pd.DataFrame, *, disclosure: bool = False) -> str:
    """A CSV of the frame, with every text cell made inert.

    Numeric and date columns pass through untouched: escaping a number would
    turn a figure into text and break the reader's own arithmetic.
    """
    safe = frame.copy()
    for column in safe.columns:
        # pandas 3 gives string columns a dedicated `str` dtype rather than
        # `object`, so checking for `object` alone would quietly let every text
        # cell through unescaped.
        if (pd.api.types.is_object_dtype(safe[column])
                or pd.api.types.is_string_dtype(safe[column])):
            safe[column] = safe[column].map(escape_cell)
    buffer = io.StringIO()
    if disclosure:
        buffer.write(f"# {DISCLOSURE}\n")
    safe.to_csv(buffer, index=False)
    return buffer.getvalue()


def json_safe(value: Any) -> Any:
    """Recursively replace non-finite numbers with null.

    An unavailable ratio is null. It is not zero, and it is not infinity.
    """
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if value is pd.NaT:
        return None
    return value


def to_json(payload: Any, **kwargs: Any) -> str:
    """Serialise with no NaN and no Infinity, and fail loudly if any survive."""
    text = json.dumps(json_safe(payload), allow_nan=False, default=str, **kwargs)
    return text
