"""Stored macro sensitivities: fitted offline, retrieved in chat, never both.

Section 7.1 is explicit about the order: *"Precompute available sensitivities
during candidate preparation and an explicit versioned data/model refresh, not
on every chat request... Training work is never an unannounced side effect of
asking a question."*

So this package has two halves that never run together:

* **`estimate.py`** fits. It is called by `scripts/whatif/build_sensitivities.py`
  during candidate preparation, writes its results into the candidate
  release's `whatif_*_sensitivity` relation, and is not imported by anything
  a chat turn reaches.
* **`artifact.py`** reads. A methodology question is an ordinary retrieval
  from a published relation, and a scenario translation is arithmetic over
  numbers that were already fitted.

**`readiness.py` is the honest half.** Twenty quarters repeated across three
thousand facilities are still twenty quarters, and section 7.3's gates are
what stop that being forgotten. Most factors in a twenty-period book do not
support a joint estimate, and the statuses this package publishes say so
rather than filling twenty rows with coefficients.
"""

from __future__ import annotations

#: The risk parameters a sensitivity can be fitted for. PD and LGD are
#: section 7.4's mandatory targets where the data support them; CCF and EAD
#: are included only when independently supported, which in these books they
#: are not -- the candidate release publishes a CCF but its variation is a
#: facility characteristic rather than a macro response.
PARAMETERS: tuple[str, ...] = ("pd_pit_12m", "pd_lifetime", "lgd_pct")

#: Which storage each parameter is published in, so a native-unit slope can
#: be expressed in the right units. `units.py` owns the vocabulary.
STORAGE: dict[str, str] = {
    "pd_pit_12m": "fraction", "pd_lifetime": "fraction", "lgd_pct": "percent"}

__all__ = ["PARAMETERS", "STORAGE"]
