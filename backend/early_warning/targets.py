"""
What the Forward Risk Signal is predicting.

Three separate targets rather than one "risk score". A single number would have
to answer three different questions at once — is this performing loan starting
to deteriorate, is it about to fail outright, and is this already-watched loan
about to be written down — and it would answer none of them well, because the
factors that predict each are not the same and neither are the base rates.

Each target names:

  * the stage it starts from, so only facilities that could actually make the
    transition are scored or fitted on;
  * the stage it ends in;
  * the horizon, which is one reporting quarter throughout — the book is
    quarterly, so a shorter horizon would be a fiction and a longer one would
    need multi-period labels the demonstration universe does not claim to
    support.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TargetDef:
    """One thing the signal predicts."""

    id: str
    label: str
    #: Displayed wherever the target is chosen. Says what the number means.
    definition: str
    #: Only facilities in this stage are eligible.
    from_stage: int
    #: The stage that counts as an event.
    to_stage: int
    #: What a credit officer would do about a high score.
    action: str
    horizon: str = "one reporting quarter"

    @property
    def shown_horizon(self) -> str:
        """The horizon as this installation's book actually measures it.

        The corporate book is quarterly and the label says so. This one is
        monthly: the outcome the model is fitted against is the stage at the
        NEXT MONTH-END, and calling that "one reporting quarter" on screen
        would be a claim about the model that is not true of it.
        """
        from backend.retail import profile

        if profile.is_retail() and self.horizon == "one reporting quarter":
            return "one reporting month"
        return self.horizon

    @property
    def eligible_note(self) -> str:
        return f"Scored only for facilities currently in Stage {self.from_stage}."

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "definition": self.definition,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "horizon": self.shown_horizon,
            "action": action_for(self.id, self.action),
            "eligible_note": self.eligible_note,
        }


#: What a credit officer does about a high score, in a RETAIL book.
#:
#: The corporate actions below name an annual review, a covenant package and a
#: collateral position — three things a retail book does not have. A Head of
#: Retail Risk reading "check the covenant package" on a personal-finance
#: facility learns that this screen was written for somebody else's portfolio.
RETAIL_ACTIONS: dict[str, str] = {
    "stage1_to_stage2":
        "Put the customer into pre-delinquency contact before the missed "
        "payment, and check whether the salary is still arriving.",
    "stage1_to_stage3":
        "Verify the affordability position now. A performing facility "
        "scoring high here is the one nobody is watching, and on an "
        "unsecured book there is nothing behind it.",
    "stage2_to_stage3":
        "Review the provision and whether forbearance is the right answer. "
        "This is the population already carrying a lifetime ECL.",
}


def action_for(target_id: str, corporate: str) -> str:
    """The action this installation would actually take."""
    from backend.retail import profile

    if not profile.is_retail():
        return corporate
    return RETAIL_ACTIONS.get(target_id, corporate)


TARGETS: tuple[TargetDef, ...] = (
    TargetDef(
        id="stage1_to_stage2",
        label="Stage 1 to Stage 2",
        definition=(
            "The chance that a performing facility develops a significant "
            "increase in credit risk within the next reporting period and "
            "moves to Stage 2."
        ),
        from_stage=1,
        to_stage=2,
        action=(
            "Bring the annual review forward and check the covenant package "
            "before the trigger fires rather than after."
        ),
    ),
    TargetDef(
        id="stage1_to_stage3",
        label="Stage 1 to default",
        definition=(
            "The chance that a performing facility becomes credit-impaired "
            "within the next reporting period without first being flagged as "
            "Stage 2. Rare, and expensive when it happens."
        ),
        from_stage=1,
        to_stage=3,
        action=(
            "Verify the exposure and the collateral position now. A performing "
            "facility with a high score here is the one nobody is watching."
        ),
    ),
    TargetDef(
        id="stage2_to_stage3",
        label="Stage 2 to default",
        definition=(
            "The chance that a facility already carrying a significant "
            "increase in credit risk becomes credit-impaired within the next "
            "reporting period."
        ),
        from_stage=2,
        to_stage=3,
        action=(
            "Review the provision and the recovery strategy. This is the "
            "population where the lifetime ECL is already being carried."
        ),
    ),
)

_BY_ID = {t.id: t for t in TARGETS}


class UnknownTargetError(LookupError):
    """A target that does not exist. The message names the ones that do."""


def target(target_id: str) -> TargetDef:
    try:
        return _BY_ID[target_id]
    except KeyError:
        raise UnknownTargetError(
            f"'{target_id}' is not a Forward Risk Signal target. "
            f"Available: {', '.join(_BY_ID)}."
        ) from None


__all__ = ["TARGETS", "TargetDef", "UnknownTargetError", "target"]
