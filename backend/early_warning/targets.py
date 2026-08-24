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
    def eligible_note(self) -> str:
        return f"Scored only for facilities currently in Stage {self.from_stage}."

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "definition": self.definition,
            "from_stage": self.from_stage,
            "to_stage": self.to_stage,
            "horizon": self.horizon,
            "action": self.action,
            "eligible_note": self.eligible_note,
        }


TARGETS: tuple[TargetDef, ...] = (
    TargetDef(
        id="stage1_to_stage2",
        label="Stage 1 to Stage 2",
        definition=(
            "The chance that a performing facility develops a significant "
            "increase in credit risk within the next reporting quarter and "
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
            "within the next reporting quarter without first being flagged as "
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
            "The chance that a facility already carrying a significant increase "
            "in credit risk becomes credit-impaired within the next reporting "
            "quarter."
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
