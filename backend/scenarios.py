"""The governed demonstration scenarios that move the synthetic book.

One scenario, in one place, read by both portfolio generators.

R2 §8 asked for the headline portfolio story to be a shipping disruption
rather than a Financial Services artefact, and R2 §26's acceptance thread
opens with "Why did Shipping deteriorate this quarter?". Neither is answerable
unless the deterioration is IN THE DATA: the external-intelligence domain was
already publishing Strait of Hormuz events against a sector whose borrowers
showed no sign of them, which is worse than publishing nothing — it invites
the analyst to assert a connection the portfolio cannot support.

So the scenario is applied to latent credit quality at generation time, and
every consequence the credit officer sees — the PD, the grade, the arrears,
the utilisation, the covenant headroom, the stage migration — is that one
shift travelling through the same machinery as everything else. Nothing is
written directly onto an outcome column.

Clearly synthetic
-----------------
`SCENARIO_STATUS` travels with every event row in the external-intelligence
domain and says so in words. This is a demonstration scenario constructed for
this deployment. It is not a report of a real current event, and no answer
built on it may present it as one.

Fact and hypothesis stay apart
------------------------------
The scenario says what was DONE to the book. It does not say that any
particular borrower's arrears were CAUSED by it: a borrower in an affected
sector may be weak for reasons of its own, and the generator deliberately
leaves that ambiguity in. Which observations are facts in the data and which
are analytical readings beside it is recorded per event, not here.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

#: Stable identity, so an answer can name the scenario it is standing on.
SCENARIO_ID = "SCEN-HORMUZ"
SCENARIO_NAME = "Strait of Hormuz shipping disruption"
SCENARIO_STATUS = "SYNTHETIC DEMONSTRATION SCENARIO"

#: The shift in latent credit quality at the peak of the disruption, by
#: sector. Negative is weaker. Shipping carries the disruption directly;
#: logistics and the trades that move goods through the strait carry it at
#: second hand; Oil & Gas is barely touched, because a producer selling into a
#: tighter freight market is not in the same position as the operator carrying
#: the cargo. A sector absent from this map is not affected at all, which is
#: what makes a sector comparison worth running.
SECTOR_IMPACT: dict[str, float] = {
    "Shipping": -0.95,
    "Transport & Logistics": -0.45,
    "Petrochemicals": -0.35,
    "Wholesale & Retail Trade": -0.30,
    "Manufacturing": -0.22,
    "Oil & Gas": -0.12,
}

#: How the disruption builds, over the final quarters of the window. A shock
#: that arrives fully formed in the last quarter has no BEFORE to compare it
#: with, and "why did this deteriorate" is not a question anyone can answer
#: from a single observation.
RAMP: tuple[float, ...] = (0.15, 0.45, 0.80, 1.00)


def quality_overlay(sectors: Sequence[str], periods: int) -> np.ndarray:
    """The scenario's effect on latent quality, entity by quarter.

    Additive and exogenous: a disruption changes what a borrower is coping
    with, not the kind of borrower it is, so it shifts the observed level
    rather than the mean the borrower reverts to.
    """
    impact = np.array([SECTOR_IMPACT.get(str(name), 0.0) for name in sectors])
    ramp = np.zeros(periods)
    tail = min(len(RAMP), periods)
    if tail:
        ramp[periods - tail:] = RAMP[len(RAMP) - tail:]
    return np.outer(impact, ramp)


def affected_sectors() -> tuple[str, ...]:
    """Named worst-first, which is the order a portfolio answer wants them."""
    return tuple(name for name, _ in
                 sorted(SECTOR_IMPACT.items(), key=lambda pair: pair[1]))
