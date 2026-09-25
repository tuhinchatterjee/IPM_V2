"""Published maps, read as data: grades, scorecards, sectors and stages.

Section 8 is about a family of changes that look like arithmetic and are not.
"Downgrade one notch" is not "PD times 1.2". "Reduce the score by 50 points"
is not "reduce the score by 50 per cent". "Move these to Stage 2" is not "use
the lifetime number". Each is a step along a **published map**, and the map is
in the release rather than in this code.

So every module here reads rows and refuses to invent one:

* **`ratings.py`** — the masterscale in its own published order. A notch move
  steps that order; it is never a string increment, never a lexical sort and
  never a PD multiplier. Boundaries, unrated obligors and the default grade
  are answered explicitly rather than clamped quietly.
* **`scores.py`** — the behavioural and application scorecards, kept apart.
  They are different scores, calibrated on different populations at different
  moments, and substituting one for the other is the error this module exists
  to refuse.
* **`sectors.py`** — the categories the book actually holds, with their
  counts and totals. `Unknown` is a category, stays in every total and every
  export, and a Retail product is never relabelled an employer sector.
* **`stages.py`** — frozen by default. An explicit stage move needs a
  declared horizon contract or reports unsupported; a lifetime figure is
  never a twelve-month figure multiplied by a number of years.

None of these fits anything, and none of them reaches the lake. They take the
rows a governed query returned and answer questions about them, which is what
makes them safe to call in a chat turn.
"""

from __future__ import annotations

#: The two Retail scorecards, named so that a caller has to say which.
BEHAVIOURAL = "BEHAVIOURAL"
APPLICATION = "APPLICATION"

#: What a book calls a row it could not classify. Retained in totals and
#: exports; section 8's *"do not silently drop unmapped"*.
UNKNOWN = "Unknown"
UNMAPPED = "Unmapped"
RESIDUAL = (UNKNOWN, UNMAPPED)

__all__ = ["APPLICATION", "BEHAVIOURAL", "RESIDUAL", "UNKNOWN", "UNMAPPED"]
