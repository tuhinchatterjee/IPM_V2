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
``contradictions`` signals that disagree, fifteen recorded diagnostics, and
                 UNRESOLVED as a permitted answer.
``interpretation`` the nine sections an answer may have, what the narrative
                 model is given, and whether what came back is grounded.
``factory``      the eight of them composed into one investigation run, so
                 the failures they each prevent cannot happen in the gaps
                 between them.
``selection``    what a click on a chart means, as structured memory.
``judgment_policy`` when the harder model is worth its cost, and what it may
                 see — never a portfolio, never before the engine ran.
``task_dag``     a blueprint compiled to a bounded graph, and the nine
                 conditions before an investigation may say it is finished.
``presentability`` eighteen dimensions, and the difference between an answer
                 that is wrong and one that is badly written.
``visual_grammar`` what a field MEANS rather than how it is stored, and which
                 picture that permits.
``visual_critic`` twelve checks between choosing a chart and drawing it,
                 including whether its bars add up to the table beside it.

The through-line is that each one produces a STRUCTURED verdict with the
measures that produced it attached, so a reader can disagree with the
measure they think is wrong rather than with the conclusion — and so a model
can explain a finding without being able to invent one.
"""

from backend.judgment import (
    blueprints,
    breadth,
    contradictions,
    drivers,
    evidence,
    factory,
    hypotheses,
    interpretation,
    judgment_policy,
    materiality,
    observations,
    persistence,
    presentability,
    selection,
    task_dag,
    visual_critic,
    visual_grammar,
)

__all__ = ["blueprints", "breadth", "contradictions", "drivers", "evidence",
           "factory",
           "hypotheses", "interpretation", "judgment_policy", "materiality",
           "observations", "persistence", "presentability", "selection",
           "task_dag", "visual_critic", "visual_grammar"]
