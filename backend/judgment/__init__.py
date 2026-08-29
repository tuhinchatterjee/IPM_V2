"""
The Analytical Judgment & Investigation Factory. Part B.

What this package is for
------------------------
Part A taught CreditProbe how to READ a question and plan an analysis. This
package is about what happens after the numbers come back: deciding what they
mean, whether they matter, whether they hold up, and what may honestly be said
about them.

Every module here exists because §65-§96 identify a judgement a model will make
plausibly and unaccountably if nobody stops it:

``evidence``     what may be said at all — only registered validated facts.
``drivers``      what moved, reconciled to the total, offsets included.
``breadth``      broad or concentrated, from measures rather than from prose.
``persistence``  a trend or a movement, with the required history stated.
``materiality``  the band, from a versioned policy, never from a model.
``observations`` structured claims with templates, not paragraphs.
``blueprints``   what a competent analyst would look at, and what may be
                 omitted only with a recorded reason.
``hypotheses``   the candidate explanations, and the fourteen questions a
                 conclusion has to survive before it is said out loud.

The through-line is that each one produces a STRUCTURED verdict with the
measures that produced it attached, so a reader can disagree with the
measure they think is wrong rather than with the conclusion — and so a model
can explain a finding without being able to invent one.
"""

from backend.judgment import (
    blueprints,
    breadth,
    drivers,
    evidence,
    hypotheses,
    materiality,
    observations,
    persistence,
)

__all__ = ["blueprints", "breadth", "drivers", "evidence", "hypotheses",
           "materiality", "observations", "persistence"]
