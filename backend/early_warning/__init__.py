"""
Early Warning: CreditProbe's Forward Risk Signal.

A forward-looking estimate of the chance that a facility will migrate to a worse
IFRS 9 stage over the next reporting quarter. Three targets, because "will this
get worse" means three different things to three different people:

    stage1_to_stage2   a performing facility developing a significant increase
                       in credit risk — the monitoring question
    stage1_to_stage3   a performing facility going straight to credit-impaired —
                       the sudden-default question
    stage2_to_stage3   an already-watched facility failing — the provisioning
                       question

What this is NOT
----------------
It is not a validated model, a production model, or a regulatory model, and the
product never calls it one. It is a PROTOTYPE FORWARD RISK SIGNAL, fitted on
CreditProbe's synthetic demonstration universe, and every screen that shows it
says so. Calling a prototype "validated" is the single most damaging thing a
risk product can do, because the word is what a credit committee relies on when
it stops asking questions.

It is also entirely CreditProbe's own. It does not reproduce, approximate or
reverse-engineer any vendor's methodology. The factor families, the scoring
form, the fitting procedure and the terminology are defined here in the open,
and `docs/EARLY_WARNING_METHODOLOGY.md` sets out the public literature the
approach draws on.
"""

from backend.early_warning.factors import (
    FACTOR_FAMILIES,
    FACTORS,
    FactorDef,
    FactorFamily,
    factors_in,
)
from backend.early_warning.model import (
    ScoredFacility,
    SignalSpecification,
    Weight,
    fit_specification,
    score_frame,
)
from backend.early_warning.targets import TARGETS, TargetDef, target

__all__ = [
    "FACTORS",
    "FACTOR_FAMILIES",
    "TARGETS",
    "FactorDef",
    "FactorFamily",
    "ScoredFacility",
    "SignalSpecification",
    "TargetDef",
    "Weight",
    "factors_in",
    "fit_specification",
    "score_frame",
    "target",
]
