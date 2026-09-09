"""
One model, or one per Stage — whichever the numbers chose, served the same way.

Why this is not a preference
-----------------------------
"Should the ML methodology use one model with Stage as a feature, or a separate
model per Stage?" is a question with an empirical answer, and the answer is a
property of the BOOK rather than of anybody's taste. So the training run fits
both designs, scores them on the same out-of-time quarters, and this module
serves whichever won. The verdict is recorded on the model card with the
figures that produced it, so a reader can disagree with it on evidence.

It has already changed once. On the earlier fourteen-point book the single
stage-aware model reproduced the Stage 1 to Stage 2 measurement step more
faithfully, and separate models over-jumped it — which mattered more than their
slightly better fit, because moving names across that boundary is most of what
a What-If does. On the rebuilt nineteen-point book, with three genuinely
distinct PDs and a coherent Stage 3, that reversed: the per-Stage design
reproduces the step to within 0.07% against the single model's 0.73%, and wins
on exposure-weighted error and WAPE besides. The design followed.

What the ensemble is
--------------------
A dictionary of boosters keyed by Stage, plus the all-book model as a fallback.
A row is scored by the model for its Stage; a Stage that had too few rows to
support one of its own is scored by the fallback, which is why the fallback is
always fitted and always stored. When the verdict is the single design, the
members are empty and every row goes to the fallback — the same code path,
serving a different answer.

Why the artifact is still JSON
-------------------------------
`brain/security.py` refuses `.pkl`, `.joblib` and `.pt` on import because a
pickle is a program. An ensemble does not change that: it is stored as one JSON
document whose values are each booster's own native JSON. Nothing here
deserialises code, and the whole document is sealed with the card exactly as a
single booster was.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd

ENSEMBLE_VERSION = "1.0.0"

SINGLE = "single_stage_aware"
PER_STAGE = "per_stage"
DESIGNS: tuple[str, ...] = (SINGLE, PER_STAGE)

#: The column a row is routed on. It is a model FEATURE as well, which is what
#: lets the fallback stand in for a Stage with no model of its own.
ROUTE_ON = "stage"

STAGES: tuple[int, ...] = (1, 2, 3)


class EnsembleError(ValueError):
    """An ensemble that cannot be built, stored or read back."""


class StageEnsemble:
    """The served model, whichever design won.

    Deliberately not a dataclass: it holds live boosters, and the equality and
    repr a dataclass would generate are meaningless for those.
    """

    def __init__(self, fallback: Any, members: dict[int, Any] | None = None,
                 design: str = SINGLE):
        if design not in DESIGNS:
            raise EnsembleError(
                f"'{design}' is not a model design. The two are "
                f"{', '.join(DESIGNS)}.")
        if fallback is None:
            raise EnsembleError(
                "An ensemble always carries the all-book model: it scores any "
                "Stage that could not support one of its own.")
        self.fallback = fallback
        self.members: dict[int, Any] = dict(members or {})
        self.design = design if members else SINGLE

    # ---------------------------------------------------------- scoring

    @property
    def routes(self) -> bool:
        return self.design == PER_STAGE and bool(self.members)

    def model_for(self, stage: Any) -> Any:
        """The booster that scores this Stage."""
        if not self.routes:
            return self.fallback
        try:
            return self.members.get(int(stage), self.fallback)
        except (TypeError, ValueError):
            return self.fallback

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        """Score every row on the model for its Stage, in the caller's order.

        Order is preserved by writing into a positional array rather than
        concatenating per-Stage results: a prediction that came back in a
        different order than the frame it was asked about would silently
        attribute one borrower's provision to another.
        """
        if not self.routes or ROUTE_ON not in X.columns:
            return np.asarray(self.fallback.predict(X), dtype=float)
        out = np.empty(len(X), dtype=float)
        stage = pd.to_numeric(X[ROUTE_ON], errors="coerce").fillna(1).astype(int)
        seen = np.zeros(len(X), dtype=bool)
        for number, model in sorted(self.members.items()):
            mask = (stage == number).to_numpy()
            if not mask.any():
                continue
            out[mask] = np.asarray(model.predict(X.loc[mask]), dtype=float)
            seen |= mask
        if not seen.all():
            out[~seen] = np.asarray(
                self.fallback.predict(X.loc[~seen]), dtype=float)
        return out

    def get_booster(self) -> Any:
        """The booster TreeSHAP explains when no Stage is in play.

        Per-row explanation routes properly through `explain.contributions`;
        this is the whole-book summary's model, and it is the fallback because
        the fallback is the only member fitted on every row.
        """
        inner = self.fallback
        return inner.get_booster() if hasattr(inner, "get_booster") else inner

    # ------------------------------------------------------- storing it

    def artifact(self) -> bytes:
        """One JSON document. Never a pickle."""
        body = {
            "ensemble_version": ENSEMBLE_VERSION,
            "design": self.design,
            "route_on": ROUTE_ON,
            "fallback": _raw(self.fallback),
            "members": {str(k): _raw(v) for k, v in sorted(self.members.items())},
        }
        return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()

    def describe(self) -> dict[str, Any]:
        return {
            "ensemble_version": ENSEMBLE_VERSION,
            "design": self.design,
            "routes": self.routes,
            "route_on": ROUTE_ON,
            "members": sorted(self.members),
            "statement": (
                "One model per Stage, served by routing each row on its own "
                "Stage." if self.routes else
                "One model with Stage as a feature, serving every row."),
        }


def _raw(model: Any) -> str:
    """A booster as its own native JSON string."""
    booster = model.get_booster() if hasattr(model, "get_booster") else model
    return bytes(booster.save_raw(raw_format="json")).decode()


def _regressor(raw: str) -> Any:
    from xgboost import XGBRegressor

    model = XGBRegressor()
    model.load_model(bytearray(raw.encode()))
    return model


def load(artifact: bytes) -> StageEnsemble:
    """Read an ensemble back, or a single booster stored the old way.

    A model sealed before the ensemble existed is one booster's own JSON, and
    it still loads: an artifact with no `design` key is the single design with
    no members, which is exactly what it was.
    """
    text = artifact.decode() if isinstance(artifact, bytes | bytearray) else str(artifact)
    try:
        body = json.loads(text)
    except json.JSONDecodeError as e:
        raise EnsembleError(
            "The stored model is not JSON. Only native JSON is read — a "
            "pickle is a program, not data.") from e
    if not isinstance(body, dict) or "design" not in body:
        return StageEnsemble(fallback=_regressor(text), design=SINGLE)
    members = {int(k): _regressor(v)
               for k, v in (body.get("members") or {}).items()}
    return StageEnsemble(fallback=_regressor(body["fallback"]),
                         members=members,
                         design=str(body.get("design") or SINGLE))


__all__ = ["DESIGNS", "ENSEMBLE_VERSION", "PER_STAGE", "ROUTE_ON", "SINGLE",
           "STAGES", "EnsembleError", "StageEnsemble", "load"]
