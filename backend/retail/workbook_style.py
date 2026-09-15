"""How a CreditProbe workbook looks, and why a number is written that way.

The defect this exists for
--------------------------
Formats used to be chosen by sniffing the column's DISPLAY LABEL:

    if name.endswith("_sar"):   return money
    if name in ("lgd", "ccf"):  return ratio

The cohort sheet built its rows with labels as keys — "Exposure (SAR)",
"PIT 12-month PD", "LGD" — so `"exposure (sar)"` did not end in `_sar` and
fell through to General, while `"lgd"` happened to match and got a 4-decimal
ratio. One column in a table was formatted and the next was not, for no
reason a reader could see:

    Exposure (SAR)   71118341.24      <- General
    PIT 12-month PD  0.034823         <- General
    LGD              0.8132           <- ratio

A probability written as 0.034823 is the §2.4 complaint exactly, and the
unformatted money beside it is the same defect wearing different clothes.

So a table declares its columns. `Col("ecl_weighted_sar", "Weighted ECL",
MONEY)` says what the value IS, and the heading is free to read however it
should. Nothing is inferred from a string.

Two units that look alike and are not
-------------------------------------
`RATE` is a proportion in [0, 1] — a PD of 0.0348. Excel's percent format
multiplies by 100, so it shows 3.48%.

`PERCENT` is a number the engine has ALREADY multiplied by 100 — a coverage of
0.9176 meaning 0.9176%. Formatting that as a percent would show 91.76%, out by
two orders of magnitude. Those cells are divided back to a proportion on the
way in, so one visual convention covers both and the stored value is still a
number rather than a string.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

#: A restrained navy and teal, per §12.1. Amber, red and green are reserved
#: for changes that mean something; nothing decorative uses them.
NAVY = "#1F3864"
NAVY_LIGHT = "#2E5090"
TEAL = "#1B6B6B"
BAND = "#F2F5FA"
RULE = "#D6DCE5"
INK = "#24292F"
MUTED = "#5B636B"
BAD_INK, BAD_FILL = "#9C0006", "#FFE3E3"
GOOD_INK, GOOD_FILL = "#0B6B37", "#E3F5EA"
WARN_INK, WARN_FILL = "#7F5F00", "#FFF6DA"

#: §12.1: counts, probabilities, money, and negatives in parentheses.
F_MONEY = '#,##0.00;(#,##0.00)'
F_MONEY0 = '#,##0;(#,##0)'
F_COUNT = '#,##0;(#,##0)'
F_RATE = '0.00%;(0.00%)'
F_RATE4 = '0.0000%;(0.0000%)'
F_POINTS = '#,##0.0;(#,##0.0)'
F_DATE = 'yyyy-mm-dd'
F_TEXT = '@'

MONEY, MONEY0, COUNT, RATE, RATE4 = "money", "money0", "count", "rate", "rate4"
PERCENT, POINTS, TEXT, DATE, WRAP = "percent", "points", "text", "date", "wrap"

#: Body type, per §12.1's 10–11pt.
BODY_PT = 10
BODY_FONT = "Calibri"

WIDTH_MIN, WIDTH_MAX = 9, 46


@dataclass(frozen=True)
class Col:
    """One column: what it holds, what it is called, and how wide."""

    key: str
    heading: str
    kind: str = TEXT
    width: int | None = None
    #: Colour the cell by the sign of its value. Only for real changes.
    signed: bool = False
    note: str = ""

    def width_for(self, rows: list[dict[str, Any]]) -> int:
        if self.width:
            return self.width
        widest = len(self.heading)
        for row in rows[:400]:
            widest = max(widest, len(_plain(row.get(self.key))))
        return max(WIDTH_MIN, min(WIDTH_MAX, widest + 3))


def _plain(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)


def styles(workbook: Any) -> dict[str, Any]:
    """Every format this workbook uses, built once."""
    base = {"font_name": BODY_FONT, "font_size": BODY_PT, "font_color": INK}
    rule = {"border": 1, "border_color": RULE}

    def make(**kw: Any) -> Any:
        return workbook.add_format({**base, **kw})

    out = {
        "title": make(bold=True, font_size=16, font_color=NAVY),
        "subtitle": make(font_size=11, font_color=MUTED),
        "note": make(italic=True, font_size=9, font_color=MUTED,
                     text_wrap=True, valign="top"),
        "section": make(bold=True, font_size=12, font_color=TEAL),
        "head": make(bold=True, bg_color=NAVY, font_color="#FFFFFF",
                     text_wrap=True, valign="vcenter", align="left",
                     border=1, border_color=NAVY),
        "head_num": make(bold=True, bg_color=NAVY, font_color="#FFFFFF",
                         text_wrap=True, valign="vcenter", align="right",
                         border=1, border_color=NAVY),
        "link": make(font_color=NAVY_LIGHT, underline=1),
        "kpi_label": make(font_size=9, font_color=MUTED),
        "kpi_value": make(bold=True, font_size=14, font_color=NAVY,
                          num_format=F_MONEY0),
        "kpi_text": make(bold=True, font_size=12, font_color=NAVY),
    }
    # Body cells, in a plain and a banded variant, per kind.
    for suffix, fill in (("", None), ("_band", BAND)):
        extra = {"bg_color": fill} if fill else {}
        out[f"text{suffix}"] = make(**rule, **extra, valign="top")
        out[f"wrap{suffix}"] = make(**rule, **extra, text_wrap=True,
                                    valign="top")
        out[f"money{suffix}"] = make(**rule, **extra, num_format=F_MONEY)
        out[f"money0{suffix}"] = make(**rule, **extra, num_format=F_MONEY0)
        out[f"count{suffix}"] = make(**rule, **extra, num_format=F_COUNT)
        out[f"rate{suffix}"] = make(**rule, **extra, num_format=F_RATE)
        out[f"rate4{suffix}"] = make(**rule, **extra, num_format=F_RATE4)
        out[f"percent{suffix}"] = make(**rule, **extra, num_format=F_RATE)
        out[f"points{suffix}"] = make(**rule, **extra, num_format=F_POINTS)
        out[f"date{suffix}"] = make(**rule, **extra, num_format=F_DATE)
    # Signed money, for changes that mean something.
    out["money_up"] = make(**rule, num_format=F_MONEY, font_color=BAD_INK,
                           bg_color=BAD_FILL)
    out["money_down"] = make(**rule, num_format=F_MONEY, font_color=GOOD_INK,
                             bg_color=GOOD_FILL)
    out["rate_up"] = make(**rule, num_format=F_RATE, font_color=BAD_INK,
                          bg_color=BAD_FILL)
    out["rate_down"] = make(**rule, num_format=F_RATE, font_color=GOOD_INK,
                            bg_color=GOOD_FILL)
    out["total_text"] = make(bold=True, top=2, top_color=NAVY)
    out["total_money"] = make(bold=True, top=2, top_color=NAVY,
                              num_format=F_MONEY)
    out["total_count"] = make(bold=True, top=2, top_color=NAVY,
                              num_format=F_COUNT)
    out["warn"] = make(**rule, bg_color=WARN_FILL, font_color=WARN_INK,
                       text_wrap=True, valign="top")
    return out


def cell_style(column: Col, value: Any, styling: dict[str, Any], *,
               banded: bool = False) -> Any:
    """The format one cell takes, from its COLUMN rather than its heading."""
    if column.signed and isinstance(value, (int, float)) and value:
        if column.kind in (RATE, PERCENT):
            return styling["rate_up" if value > 0 else "rate_down"]
        return styling["money_up" if value > 0 else "money_down"]
    suffix = "_band" if banded else ""
    kind = column.kind if column.kind in (
        MONEY, MONEY0, COUNT, RATE, RATE4, PERCENT, POINTS, DATE, WRAP) else TEXT
    return styling[f"{kind}{suffix}"]


def cell_value(column: Col, value: Any) -> Any:
    """The number that goes in the cell.

    A PERCENT column carries a figure the engine already multiplied by 100.
    Excel's percent format multiplies again, so 0.9176 — meaning 0.9176% —
    would render as 91.76%. It is divided back here, so the cell holds the
    proportion it claims to and one visual convention covers both kinds.
    """
    if value is None:
        return None
    if column.kind == PERCENT and isinstance(value, (int, float)):
        return float(value) / 100.0
    return value
