"""A sheet that already obeys the presentation standard before anything is on it.

§12.1 asks for gridlines off on EVERY sheet, readable number formats, frozen
headings, filters, capped widths, print setup and a Contents page that links
to the rest. Every one of those is a thing somebody has to remember on every
new sheet, and the sheet that gets added next week is the one where it is
forgotten — the previous workbook had gridlines on all thirteen because
nothing ever called `hide_gridlines`.

So a sheet is opened through `Sheet`, which does all of it on creation, and
the callers write content.
"""

from __future__ import annotations

from typing import Any

from backend.retail import workbook_style as ST

#: Rows written before a table is banded. Banding a two-row table is noise.
BAND_FROM = 4

#: Text that is a missing value wearing a string's clothes.
#:
#: `str(float("nan"))` is "nan" and `str(None)` is "None", and both reach a
#: cell through an innocent-looking `str(value or "")` — `or` does not catch
#: nan, which is truthy. A validation sweep found 'nan' in a score-band column
#: and 'None' on the summary. §12.1 is explicit that a missing value is blank
#: with a reason, never zero and never the text "nan", so the check lives here
#: as well as at each call site: one of the two will be forgotten.
_NULLISH = frozenset({"nan", "none", "null", "nat", "inf", "-inf", "<na>"})


def blankish(value: Any) -> bool:
    """True when this value should be written as an empty cell."""
    if value is None:
        return True
    if isinstance(value, float) and (value != value or value in (
            float("inf"), float("-inf"))):
        return True
    return isinstance(value, str) and value.strip().lower() in _NULLISH


class Sheet:
    """One worksheet, set up the way every sheet in this book is set up."""

    def __init__(self, book: Any, styles: dict[str, Any], name: str,
                 title: str, note: str = "", *, landscape: bool = True,
                 tab: str = ST.NAVY) -> None:
        self.page = book.add_worksheet(name[:31])
        self.styles = styles
        self.name = name[:31]
        self.at = 0
        # §12.1, on every sheet rather than on the ones somebody remembered.
        self.page.hide_gridlines(2)          # screen AND print
        self.page.set_tab_color(tab)
        self.page.set_landscape() if landscape else self.page.set_portrait()
        self.page.set_paper(9)               # A4
        self.page.set_margins(0.4, 0.4, 0.5, 0.5)
        # Fit the width, let the height run: a long data sheet must not be
        # squeezed onto one page until it is unreadable.
        self.page.fit_to_pages(1, 0)
        self.page.set_header(f"&L{title}&R&P of &N")
        self.page.set_footer("&LSynthetic Saudi retail demonstration data "
                             "— not ANB customer data or approved models"
                             "&R&D")
        self.page.set_row(0, 22)
        self.page.write(0, 0, title, styles["title"])
        self.at = 1
        if note:
            self.page.merge_range(1, 0, 1, 11, note, styles["note"])
            self.page.set_row(1, 30)
            self.at = 3
        else:
            self.at = 2

    # -- content ---------------------------------------------------------

    def section(self, text: str) -> None:
        self.page.write(self.at, 0, text, self.styles["section"])
        self.at += 1

    def line(self, text: str, style: str = "note") -> None:
        self.page.merge_range(self.at, 0, self.at, 11, text,
                              self.styles[style])
        self.page.set_row(self.at, 26)
        self.at += 2

    def kpis(self, pairs: list[tuple[str, Any, str]]) -> None:
        """A row of headline figures: label above, value below."""
        for index, (label, value, kind) in enumerate(pairs):
            column = index * 2
            self.page.write(self.at, column, label, self.styles["kpi_label"])
            if blankish(value):
                self.page.write_blank(self.at + 1, column, None,
                                      self.styles["kpi_text"])
            elif isinstance(value, (int, float)):
                style = self.styles["kpi_value"]
                self.page.write_number(self.at + 1, column, float(value), style)
            else:
                self.page.write(self.at + 1, column, str(value),
                                self.styles["kpi_text"])
            self.page.set_column(column, column, 22)
        self.page.set_row(self.at + 1, 22)
        self.at += 3

    def pairs(self, rows: list[tuple[str, Any]], *,
              width: int = 34) -> dict[str, str]:
        """A label/value block, returning where each value landed.

        The reference matters: a caller that wanted "Scenario minus baseline"
        counted rows by hand and wrote `=B9-B8` when the two values were on
        rows 9 and 10. The cached result was right — it is passed in — so the
        file LOOKED correct and would have recalculated to the baseline minus
        an empty cell the moment anybody pressed F9. Formulas are built from
        these references now, never from arithmetic on `self.at`.
        """
        where: dict[str, str] = {}
        for label, value in rows:
            where[str(label)] = f"B{self.at + 1}"
            self.page.write(self.at, 0, str(label), self.styles["text"])
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                self.page.write_number(self.at, 1, float(value),
                                       self.styles["money0"])
            elif blankish(value):
                self.page.write_blank(self.at, 1, None, self.styles["text"])
            else:
                self.page.write(self.at, 1, str(value), self.styles["wrap"])
            self.at += 1
        self.page.set_column(0, 0, width)
        self.page.set_column(1, 1, 52)
        self.at += 1
        return where

    @staticmethod
    def column_letter(index: int) -> str:
        """A1-style column letter for a zero-based index."""
        letters = ""
        index += 1
        while index:
            index, part = divmod(index - 1, 26)
            letters = chr(65 + part) + letters
        return letters

    def table(self, columns: list[ST.Col], rows: list[dict[str, Any]], *,
              empty: str = "Nothing to show for this scenario.",
              total: dict[str, Any] | None = None,
              autofilter: bool = True, formula_totals: bool = True) -> None:
        """One table, headed, banded, frozen, filtered and sized."""
        if not rows:
            self.page.merge_range(self.at, 0, self.at, 5, empty,
                                  self.styles["note"])
            self.at += 2
            return
        head_at = self.at
        for index, column in enumerate(columns):
            numeric = column.kind in (ST.MONEY, ST.MONEY0, ST.COUNT, ST.RATE,
                                      ST.RATE4, ST.PERCENT, ST.POINTS)
            self.page.write(head_at, index, column.heading,
                            self.styles["head_num" if numeric else "head"])
            self.page.set_column(index, index, column.width_for(rows))
        self.page.set_row(head_at, 32)

        banded = len(rows) >= BAND_FROM
        for offset, row in enumerate(rows):
            stripe = banded and offset % 2 == 1
            for index, column in enumerate(columns):
                raw = row.get(column.key)
                value = ST.cell_value(column, raw)
                style = ST.cell_style(column, raw, self.styles, banded=stripe)
                at = head_at + 1 + offset
                # §12.1: a missing value is BLANK, never zero and never the
                # text "nan". A zero is a measurement; a blank is the absence
                # of one, and a workbook that writes the first for the second
                # is stating a fact it does not have.
                if blankish(value):
                    self.page.write_blank(at, index, None, style)
                elif isinstance(value, bool):
                    self.page.write(at, index, "Yes" if value else "No", style)
                elif isinstance(value, (int, float)):
                    self.page.write_number(at, index, float(value), style)
                else:
                    self.page.write(at, index, str(value), style)
        last = head_at + len(rows)

        if total:
            last += 1
            first_data, last_data = head_at + 2, head_at + 1 + len(rows)
            for index, column in enumerate(columns):
                value = total.get(column.key)
                if index == 0 and value is None:
                    self.page.write(last, 0, "Total",
                                    self.styles["total_text"])
                elif value is None:
                    self.page.write_blank(last, index, None,
                                          self.styles["total_text"])
                elif isinstance(value, str):
                    self.page.write(last, index, value,
                                    self.styles["total_text"])
                else:
                    style = ("total_count" if column.kind == ST.COUNT
                             else "total_money")
                    number = float(ST.cell_value(column, value))
                    # §12.1: a total is a FORMULA over the rows above it, so
                    # a reader can click the cell and see where it came from,
                    # and so filtering the table narrows the total with it.
                    # SUBTOTAL(109) is SUM that ignores filtered-out rows;
                    # writing the value as well means the number is right
                    # before Word or Excel has recalculated anything.
                    if formula_totals:
                        letter = self.column_letter(index)
                        self.page.write_formula(
                            last, index,
                            f"=SUBTOTAL(109,{letter}{first_data}:"
                            f"{letter}{last_data})",
                            self.styles[style], number)
                    else:
                        self.page.write_number(last, index, number,
                                               self.styles[style])

        if autofilter and len(rows) > 2:
            self.page.autofilter(head_at, 0, head_at + len(rows),
                                 len(columns) - 1)
        # Freeze the heading, and the first column with it where the table is
        # wide enough that a reader scrolling right loses which row they are on.
        self.page.freeze_panes(head_at + 1, 1 if len(columns) > 6 else 0)
        self.page.print_area(0, 0, last, len(columns) - 1)
        self.page.repeat_rows(head_at, head_at)
        self.at = last + 2

    def check(self, label: str, formula: str, value: Any,
              *, kind: str = ST.MONEY) -> str:
        """A reconciliation line the reader can audit in the cell.

        §12.1 asks for formulas on totals, changes and CHECKS. A residual
        written as a number is a claim; written as the subtraction it came
        from, it is something a reader can disagree with.
        """
        self.page.write(self.at, 0, label, self.styles["text"])
        self.page.write_formula(
            self.at, 1, formula,
            self.styles[kind if kind in self.styles else "money"],
            float(value) if isinstance(value, (int, float)) else 0.0)
        self.page.set_column(0, 0, 34)
        self.page.set_column(1, 1, 24)
        at = f"B{self.at + 1}"
        self.at += 1
        return at

    def chart(self, book: Any, spec: dict[str, Any], *, at: str = "",
              width: int = 760, height: int = 300) -> None:
        """A chart, placed where it cannot sit on top of the data."""
        figure = book.add_chart({"type": spec["type"],
                                 "subtype": spec.get("subtype")}
                                if spec.get("subtype")
                                else {"type": spec["type"]})
        for series in spec["series"]:
            figure.add_series(series)
        figure.set_title({"name": spec.get("title", ""),
                          "name_font": {"size": 11, "color": ST.NAVY}})
        figure.set_legend({"position": spec.get("legend", "bottom")})
        figure.set_size({"width": width, "height": height})
        figure.set_style(2)
        if spec.get("x_axis"):
            figure.set_x_axis(spec["x_axis"])
        if spec.get("y_axis"):
            figure.set_y_axis(spec["y_axis"])
        self.page.insert_chart(at or f"A{self.at + 1}", figure)
        self.at += max(16, height // 20)
