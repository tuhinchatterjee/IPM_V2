"""
Climate stressed-PD module — a code reproduction of the Oman Climate Stressed PD
model v5.1 workbook, generalised to be multi-run, auditable and parameterisable
per client/country.

Layering (nothing below ever imports anything above it):

  normal.py      AS241 inverse normal + erfc-based CDF — Excel NORMSINV/NORMSDIST parity.
  defaults.py    The v5.1 Oman dataset as a plain JSON-serialisable model dict.
  engine.py      Pure deterministic calculation: model dict -> result dict.
  checks.py      The 24 live quality checks, run on every calculation.
  sensitivity.py One-way sensitivity over the five control levers.
  store.py       Model versions + immutable runs with full settings snapshots.
  report.py      Self-contained HTML summary report and the Excel regulator pack.

The engine stops at the PD signal. It computes no ECL and no LGD, exactly like
the workbook.
"""

from backend.climate.engine import ENGINE_VERSION  # noqa: F401
