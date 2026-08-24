"""
The factors the Forward Risk Signal is built from, and the families they sit in.

Why families
------------
A score built from twenty loose variables is impossible to argue with, because
nobody can hold twenty things in mind at once. Six families of three or four can
be discussed: "the behaviour factors are driving this, the structure factors are
not". So every factor belongs to exactly one family, and the scoring output
reports the contribution of each family as well as each factor.

The families are also a governance device. A reviewer can ask "why is there no
market family here?" and get an answer, which is harder when the model is a list.

Every factor declares
---------------------
  * the governed fields it reads, so the Data Access Layer serves it and the
    Trace can name the lineage;
  * how it is derived, in one sentence a credit officer can check;
  * its DIRECTION — whether a higher value means more risk or less — which is
    what lets the fitted weights be read as agreeing or disagreeing with prior
    expectation rather than as arbitrary numbers.

Nothing here is a vendor methodology. These are ordinary credit-monitoring
observables, of the kind any bank's watchlist policy already names, chosen
because the demonstration universe records them and a reviewer can reason about
them. `docs/EARLY_WARNING_METHODOLOGY.md` sets out the public literature.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FactorFamily:
    id: str
    label: str
    definition: str

    def to_dict(self) -> dict:
        return {"id": self.id, "label": self.label, "definition": self.definition}


FACTOR_FAMILIES: tuple[FactorFamily, ...] = (
    FactorFamily(
        "behaviour",
        "Behaviour",
        "How the facility is actually being used and serviced. The earliest "
        "things to move, and the hardest for a borrower to present differently.",
    ),
    FactorFamily(
        "capacity",
        "Capacity",
        "Whether the borrower can service what it owes: cash cover and the room "
        "left inside its covenants.",
    ),
    FactorFamily(
        "rating_dynamics",
        "Rating dynamics",
        "The direction the internal rating is already travelling, and how far it "
        "has come since the facility was written.",
    ),
    FactorFamily(
        "structure",
        "Structure",
        "How the exposure is put together — security, size and utilisation "
        "headroom — which decides how much a deterioration costs.",
    ),
    FactorFamily(
        "sentiment",
        "Sentiment",
        "Outside-in signals about the borrower that the bank's own records do "
        "not contain.",
    ),
    FactorFamily(
        "cycle",
        "Cycle sensitivity",
        "The borrower's exposure to the economy it operates in, as the sector's "
        "historic sensitivity multiplied by where the cycle currently is.",
    ),
)

FAMILY_BY_ID = {f.id: f for f in FACTOR_FAMILIES}


@dataclass(frozen=True)
class FactorDef:
    """One input to the signal."""

    id: str
    family: str
    label: str
    #: One sentence, checkable by a credit officer.
    definition: str
    #: Governed fields this factor reads. Named so the Trace can show lineage.
    fields: tuple[str, ...]
    #: "up-is-worse" or "up-is-better" — the expectation the fit is read against.
    direction: str
    unit: str = ""
    #: Winsorisation bounds applied before standardising, in the factor's own
    #: units. One facility with a covenant headroom of -4,000% would otherwise
    #: decide the whole model's scale.
    clip: tuple[float, float] | None = None
    notes: str = ""
    #: Set for factors that are computed rather than read straight off a column.
    derived: bool = field(default=False)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "family": self.family,
            "family_label": FAMILY_BY_ID[self.family].label,
            "label": self.label,
            "definition": self.definition,
            "fields": list(self.fields),
            "direction": self.direction,
            "unit": self.unit,
            "derived": self.derived,
            "notes": self.notes,
        }


FACTORS: tuple[FactorDef, ...] = (
    # ------------------------------------------------------------- behaviour
    FactorDef(
        "utilisation", "behaviour", "Utilisation",
        "How much of the committed limit is drawn at the reporting date.",
        ("utilisation_pct",), "up-is-worse", "%", clip=(0.0, 130.0),
    ),
    FactorDef(
        "utilisation_change", "behaviour", "Utilisation change",
        "Percentage points of utilisation added since the previous reporting "
        "date. A borrower drawing down is a borrower short of cash.",
        ("utilisation_pct", "prev_utilisation_pct"), "up-is-worse", "pp",
        clip=(-40.0, 40.0), derived=True,
    ),
    FactorDef(
        "days_past_due", "behaviour", "Days past due",
        "Days the facility has been in arrears at the reporting date.",
        ("dpd_days",), "up-is-worse", "days", clip=(0.0, 180.0),
    ),
    FactorDef(
        "rollovers", "behaviour", "Rollovers",
        "Times the facility has been rolled rather than repaid. Repeated "
        "rollovers are a repayment problem being deferred.",
        ("rollover_count",), "up-is-worse", "count", clip=(0.0, 12.0),
    ),
    # -------------------------------------------------------------- capacity
    FactorDef(
        "dscr", "capacity", "Debt service coverage",
        "Cash available for debt service divided by debt service due.",
        ("dscr",), "up-is-better", "x", clip=(0.0, 6.0),
    ),
    FactorDef(
        "covenant_headroom", "capacity", "Covenant headroom",
        "Percentage room left before the tightest financial covenant is "
        "breached. Negative means it already has been.",
        ("covenant_headroom_pct",), "up-is-better", "%", clip=(-60.0, 90.0),
    ),
    # ------------------------------------------------------- rating dynamics
    FactorDef(
        "notch_move", "rating_dynamics", "Notches moved",
        "Internal grades the borrower has moved since the previous reporting "
        "date. Positive is deterioration.",
        ("internal_grade", "prev_risk_rating"), "up-is-worse", "notches",
        clip=(-4.0, 5.0), derived=True,
    ),
    FactorDef(
        "pd_level", "rating_dynamics", "Twelve-month PD",
        "The current twelve-month probability of default, as the rating system "
        "records it.",
        ("pd_12m_pct",), "up-is-worse", "%", clip=(0.0, 45.0),
    ),
    FactorDef(
        "downgrade_probability", "rating_dynamics", "Downgrade probability",
        "The rating system's own estimate of the chance of a downgrade.",
        ("downgrade_prob_pct",), "up-is-worse", "%", clip=(0.0, 100.0),
    ),
    FactorDef(
        "pd_deterioration", "rating_dynamics", "PD deterioration",
        "The current twelve-month PD divided by the PD recorded when the "
        "facility was written. This is the quantity the IFRS 9 significant-"
        "increase test is measured on, so a facility approaching the threshold "
        "is approaching a stage migration by definition.",
        ("pd_12m_pct", "pd_at_origination_pct"), "up-is-worse", "x",
        clip=(0.0, 8.0), derived=True,
        notes="Falls back to 1.0 where the origination PD is not recorded, "
              "which leaves the factor carrying no information rather than a "
              "guess.",
    ),
    # ------------------------------------------------------------- structure
    FactorDef(
        "collateral_shortfall", "structure", "Collateral shortfall",
        "Exposure at default less collateral value, as a share of exposure at "
        "default. High means little to recover against.",
        ("ead", "collateral_value"), "up-is-worse", "%", clip=(-50.0, 100.0),
        derived=True,
    ),
    FactorDef(
        "loss_given_default", "structure", "Loss given default",
        "The share of exposure the bank expects to lose if the borrower "
        "defaults.",
        ("lgd_pct",), "up-is-worse", "%", clip=(0.0, 100.0),
    ),
    FactorDef(
        "exposure_size", "structure", "Exposure size",
        "Exposure at default on a log scale, so a facility ten times larger "
        "counts as one step rather than ten.",
        ("ead",), "up-is-worse", "log USD mn", clip=(-3.0, 8.0), derived=True,
    ),
    # ------------------------------------------------------------- sentiment
    FactorDef(
        "news_sentiment", "sentiment", "News sentiment",
        "Sentiment of external coverage of the borrower over the quarter, from "
        "-1 (hostile) to +1 (favourable).",
        ("news_sentiment",), "up-is-better", "score", clip=(-1.0, 1.0),
    ),
    # ----------------------------------------------------------------- cycle
    FactorDef(
        "cycle_exposure", "cycle", "Cycle exposure",
        "The sector's historic sensitivity to the credit cycle multiplied by "
        "where the cycle currently sits. Positive means the economy is "
        "currently working against this borrower.",
        ("sector",), "up-is-worse", "z", clip=(-4.0, 4.0), derived=True,
    ),
)

FACTOR_BY_ID = {f.id: f for f in FACTORS}


class UnknownFactorError(LookupError):
    pass


def factor(factor_id: str) -> FactorDef:
    try:
        return FACTOR_BY_ID[factor_id]
    except KeyError:
        raise UnknownFactorError(
            f"'{factor_id}' is not a Forward Risk Signal factor. "
            f"Available: {', '.join(FACTOR_BY_ID)}."
        ) from None


def factors_in(family_id: str) -> list[FactorDef]:
    return [f for f in FACTORS if f.family == family_id]


#: Fields that live in the IFRS 9 staging table rather than in the facility
#: snapshot. Declared here so the facility read does not ask for them and fail:
#: they are joined on afterwards, and are absent when that table is not
#: published.
JOINED_FIELDS: tuple[str, ...] = ("pd_at_origination_pct",)

#: Every governed field the factor set reads from the facility book. The Data
#: Access Layer is asked for exactly these, so a factor that is added without
#: declaring its fields fails loudly at read time rather than silently producing
#: zeros.
REQUIRED_FIELDS: tuple[str, ...] = tuple(sorted(
    ({
        field_name
        for f in FACTORS
        for field_name in f.fields
    } | {"account_id", "customer_id", "period", "ifrs9_stage", "sector", "segment",
         "borrower_name", "ead", "region"})
    - set(JOINED_FIELDS)
))


# ============================================================== computation


def _series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        raise KeyError(
            f"The factor set needs '{column}', which the frame does not have. "
            "Every factor declares its fields; read them with REQUIRED_FIELDS."
        )
    return pd.to_numeric(frame[column], errors="coerce")


def compute_factors(frame: pd.DataFrame,
                    cycle_by_sector: dict[str, float] | None = None) -> pd.DataFrame:
    """Turn one period of the facility book into the factor matrix.

    Derived factors are computed here and nowhere else, so the definition a
    reviewer reads on screen is the arithmetic that actually ran. Missing values
    become the factor's median rather than zero: zero is a real utilisation and
    a real headroom, and treating "unknown" as "zero" would score a facility
    with a gap in its data as though something were known about it.
    """
    cycle_by_sector = cycle_by_sector or {}
    out = pd.DataFrame(index=frame.index)

    out["utilisation"] = _series(frame, "utilisation_pct")
    out["utilisation_change"] = (
        _series(frame, "utilisation_pct") - _series(frame, "prev_utilisation_pct")
    )
    out["days_past_due"] = _series(frame, "dpd_days")
    out["rollovers"] = _series(frame, "rollover_count")

    out["dscr"] = _series(frame, "dscr")
    out["covenant_headroom"] = _series(frame, "covenant_headroom_pct")

    out["notch_move"] = _series(frame, "internal_grade") - _prev_grade(frame)
    out["pd_level"] = _series(frame, "pd_12m_pct")
    out["downgrade_probability"] = _series(frame, "downgrade_prob_pct")
    if "pd_at_origination_pct" in frame.columns:
        origination = _series(frame, "pd_at_origination_pct").clip(lower=0.01)
        out["pd_deterioration"] = _series(frame, "pd_12m_pct") / origination
    else:
        out["pd_deterioration"] = 1.0

    ead = _series(frame, "ead")
    collateral = _series(frame, "collateral_value")
    out["collateral_shortfall"] = np.where(
        ead > 0, 100.0 * (ead - collateral) / ead, 0.0
    )
    out["loss_given_default"] = _series(frame, "lgd_pct")
    out["exposure_size"] = np.log1p(ead.clip(lower=0))

    out["news_sentiment"] = _series(frame, "news_sentiment")

    out["cycle_exposure"] = frame["sector"].map(cycle_by_sector).astype(float)

    for definition in FACTORS:
        column = out[definition.id]
        if definition.clip:
            column = column.clip(*definition.clip)
        median = column.median()
        out[definition.id] = column.fillna(0.0 if pd.isna(median) else median)
    return out[[f.id for f in FACTORS]]


#: CP-3 is grade 3. The previous rating is stored as a symbol, so the numeric
#: move has to be recovered from it rather than assumed.
def _prev_grade(frame: pd.DataFrame) -> pd.Series:
    if "prev_risk_rating" not in frame.columns:
        return _series(frame, "internal_grade")
    return (
        frame["prev_risk_rating"].astype(str).str.extract(r"(\d+)", expand=False)
        .astype(float)
        .fillna(_series(frame, "internal_grade"))
    )


__all__ = [
    "FACTORS",
    "FACTOR_BY_ID",
    "JOINED_FIELDS",
    "FACTOR_FAMILIES",
    "FAMILY_BY_ID",
    "REQUIRED_FIELDS",
    "FactorDef",
    "FactorFamily",
    "UnknownFactorError",
    "compute_factors",
    "factor",
    "factors_in",
]
