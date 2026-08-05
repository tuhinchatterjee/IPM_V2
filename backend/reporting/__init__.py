"""
Committee report packs.

Two audiences, one content model:

  SMC  IFRS 9 Credit Committee / Senior Management Committee — the full pack.
  BRC  Board Risk Committee — the concise version, same figures, fewer sections
       and no working-level detail.

Layering:

  content.py  assembles a format-independent report: sections, narrative, tables,
              chart specs, findings, recommended actions and remediation items,
              all computed from the live dataset.
  charts.py   renders each chart spec once as a PNG, so the PDF and the Word file
              show the same picture rather than two drifting implementations.
  writers.py  pours that model into reportlab (PDF) or python-docx (Word).
  store.py    keeps every generated pack so the Archive screen can list and
              re-serve it.

Nothing here computes risk. Every figure comes from data_loader, cockpit_data or
the climate engine, so a number in a board pack is the same number the screen
showed.
"""

from backend.reporting.content import (  # noqa: F401
    REPORT_TYPES,
    build_report,
    report_spec,
    sections_for,
)
from backend.reporting.writers import FORMATS, write  # noqa: F401
