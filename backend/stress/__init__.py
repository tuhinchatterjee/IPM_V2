"""
Stress testing and simulation.

Scenarios are named, versioned, parameterised objects — never free text — so a
stressed result can be reproduced exactly and defended in a committee.

Existing assets this package will build on rather than replace:
  * backend/stress_lab.py — named scenario presets with stated rationales
  * backend/climate/      — the Oman climate stressed-PD model (golden-mastered
                            to 1e-11 against the source workbook)

Phase 2 registers a basic stress scenario as a certified engine function; Phase 6
adds scenario management, comparison and reverse stress.
"""
