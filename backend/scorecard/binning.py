"""
Binning and weight of evidence. §10, §26.

The approved binning specification is what turns a raw value into the number
the equation multiplies by a coefficient. It is *frozen at development* and
applied unchanged to every validation month.

The rule that makes validation mean anything
---------------------------------------------
§10: "Do not recalculate WoE from the current validation month unless
analysing recalibration."

Recomputing WoE on the month you are validating makes the model fit that
month by construction. Discrimination would look stable while the thing that
actually shipped drifts, because the measurement moved with the data. So
`Spec.apply()` only ever *looks up* — it has no path that computes a WoE, and
`fit()` (which does compute) is a separate call a caller has to reach for
deliberately.

Missing and unseen values
--------------------------
Two special bins, and they mean different things:

* **MISSING** — the value was absent. Its WoE is fitted like any other bin,
  because "declined to state income" is itself predictive and pretending
  otherwise throws that away.
* **UNSEEN** — a category that did not exist at development. It cannot have
  a fitted WoE, so it maps to 0.0 (neutral) and is *counted*. A month where
  4% of a variable lands in UNSEEN is a finding; silently scoring it as
  neutral and saying nothing is the failure this counting prevents.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

BINNING_VERSION = "1.0.0"

MISSING_BIN = "MISSING"
UNSEEN_BIN = "UNSEEN"
SPECIAL_BINS: tuple[str, ...] = (MISSING_BIN, UNSEEN_BIN)

#: Laplace smoothing. A bin with zero bads gives an infinite WoE, which then
#: propagates through every score in that bin. Half an observation on each
#: side keeps the number finite and is visible in the spec rather than being
#: an unexplained epsilon in the arithmetic.
SMOOTHING = 0.5


class BinningError(Exception):
    """A binning specification that may not be built or applied."""


@dataclass
class Bin:
    """One bin, and the evidence that set its WoE."""

    bin_id: str
    label: str
    #: Numeric bins carry (lower, upper]; categorical bins carry members.
    lower: float | None = None
    upper: float | None = None
    members: tuple[str, ...] = ()
    count: int = 0
    good_count: int = 0
    bad_count: int = 0
    bad_rate: float = 0.0
    woe: float = 0.0
    iv_contribution: float = 0.0
    special: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "bin_id": self.bin_id, "label": self.label,
            "lower": self.lower, "upper": self.upper,
            "members": list(self.members),
            "count": self.count, "good_count": self.good_count,
            "bad_count": self.bad_count,
            "bad_rate": round(self.bad_rate, 6),
            "woe": round(self.woe, 6),
            "iv_contribution": round(self.iv_contribution, 6),
            "special": self.special,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Bin:
        return cls(
            bin_id=str(payload["bin_id"]), label=str(payload.get("label", "")),
            lower=payload.get("lower"), upper=payload.get("upper"),
            members=tuple(payload.get("members") or ()),
            count=int(payload.get("count", 0)),
            good_count=int(payload.get("good_count", 0)),
            bad_count=int(payload.get("bad_count", 0)),
            bad_rate=float(payload.get("bad_rate", 0.0)),
            woe=float(payload.get("woe", 0.0)),
            iv_contribution=float(payload.get("iv_contribution", 0.0)),
            special=bool(payload.get("special", False)))


@dataclass
class VariableBinning:
    """The approved binning of one variable."""

    variable: str
    kind: str
    bins: list[Bin] = field(default_factory=list)
    monotonic: bool = False

    @property
    def information_value(self) -> float:
        return round(sum(b.iv_contribution for b in self.bins), 6)

    @property
    def strength(self) -> str:
        """The conventional IV reading, labelled as a convention.

        These cut-offs are a rule of thumb from scorecard practice, not a
        regulatory threshold, and the label says so wherever it is shown.
        """
        iv = self.information_value
        if iv < 0.02:
            return "UNPREDICTIVE"
        if iv < 0.1:
            return "WEAK"
        if iv < 0.3:
            return "MEDIUM"
        if iv < 0.5:
            return "STRONG"
        return "SUSPICIOUSLY STRONG — CHECK FOR LEAKAGE"

    def bin_for(self, value: Any) -> Bin:
        """Which bin a value falls in. Lookup only — never a computation."""
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return self._special(MISSING_BIN)
        if self.kind == "CATEGORICAL":
            text = str(value)
            for one in self.bins:
                if text in one.members:
                    return one
            return self._special(UNSEEN_BIN)
        try:
            number = float(value)
        except (TypeError, ValueError):
            return self._special(UNSEEN_BIN)
        for one in self.bins:
            if one.special:
                continue
            lower = -math.inf if one.lower is None else one.lower
            upper = math.inf if one.upper is None else one.upper
            if lower < number <= upper:
                return one
        return self._special(UNSEEN_BIN)

    def _special(self, bin_id: str) -> Bin:
        for one in self.bins:
            if one.bin_id == bin_id:
                return one
        # UNSEEN is neutral by necessity: nothing at development observed it,
        # so there is no evidence to give it. It is still counted.
        return Bin(bin_id=bin_id, label=bin_id, woe=0.0, special=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "variable": self.variable, "kind": self.kind,
            "bins": [b.to_dict() for b in self.bins],
            "information_value": self.information_value,
            "iv_strength": self.strength,
            "iv_strength_is_a_convention": (
                "The weak/medium/strong reading of Information Value is a "
                "scorecard rule of thumb, not a regulatory threshold."),
            "woe_monotonic": self.monotonic,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> VariableBinning:
        return cls(
            variable=str(payload["variable"]),
            kind=str(payload.get("kind", "NUMERIC")),
            bins=[Bin.from_dict(b) for b in payload.get("bins", [])],
            monotonic=bool(payload.get("woe_monotonic", False)))


@dataclass
class Spec:
    """A whole approved binning / WoE specification."""

    spec_version: str
    scorecard_type: str
    development_population: str = ""
    development_rows: int = 0
    development_bads: int = 0
    variables: dict[str, VariableBinning] = field(default_factory=dict)

    def apply(self, frame: pd.DataFrame, *,
              variables: list[str] | None = None) -> pd.DataFrame:
        """Map raw columns to their WoE columns. Lookup, never a fit.

        Returns a frame with `<name>_woe`, `<name>_bin` added for each
        requested variable. Anything the spec does not cover is refused
        rather than passed through unscored.
        """
        wanted = variables if variables is not None else list(self.variables)
        missing = [v for v in wanted if v not in self.variables]
        if missing:
            raise BinningError(
                "no approved binning exists for: " + ", ".join(sorted(missing))
                + ". Scoring a variable with no approved WoE would mean "
                  "inventing the mapping at validation time.")

        out = frame.copy()
        for name in wanted:
            binning = self.variables[name]
            column = frame[name] if name in frame.columns else pd.Series(
                [None] * len(frame), index=frame.index)
            picked = [binning.bin_for(v) for v in column]
            out[f"{name}_woe"] = [b.woe for b in picked]
            out[f"{name}_bin"] = [b.bin_id for b in picked]
        return out

    def special_bin_rates(self, frame: pd.DataFrame,
                          variables: list[str]) -> dict[str, dict[str, float]]:
        """§38's special-bin rates. What share landed somewhere unfitted."""
        rates: dict[str, dict[str, float]] = {}
        total = max(len(frame), 1)
        for name in variables:
            column = f"{name}_bin"
            if column not in frame.columns:
                continue
            counts = frame[column].value_counts()
            rates[name] = {
                MISSING_BIN: round(int(counts.get(MISSING_BIN, 0)) / total, 6),
                UNSEEN_BIN: round(int(counts.get(UNSEEN_BIN, 0)) / total, 6),
            }
        return rates

    def to_dict(self) -> dict[str, Any]:
        return {
            "binning_version": BINNING_VERSION,
            "spec_version": self.spec_version,
            "scorecard_type": self.scorecard_type,
            "development_population": self.development_population,
            "development_rows": self.development_rows,
            "development_bads": self.development_bads,
            "variables": {k: v.to_dict()
                          for k, v in sorted(self.variables.items())},
            "frozen": (
                "This specification was fitted on the development population "
                "and is applied unchanged to every validation month. "
                "Recomputing it on the month under validation would make the "
                "model fit that month by construction."),
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Spec:
        return cls(
            spec_version=str(payload["spec_version"]),
            scorecard_type=str(payload["scorecard_type"]),
            development_population=str(
                payload.get("development_population", "")),
            development_rows=int(payload.get("development_rows", 0)),
            development_bads=int(payload.get("development_bads", 0)),
            variables={k: VariableBinning.from_dict(v)
                       for k, v in (payload.get("variables") or {}).items()})


# ----------------------------------------------------------------- fitting


def _woe_and_iv(good: int, bad: int, good_total: int,
                bad_total: int) -> tuple[float, float]:
    good_share = (good + SMOOTHING) / (good_total + SMOOTHING * 2)
    bad_share = (bad + SMOOTHING) / (bad_total + SMOOTHING * 2)
    woe = math.log(good_share / bad_share)
    return woe, (good_share - bad_share) * woe


def fit_variable(frame: pd.DataFrame, variable: str, target: str, *,
                 kind: str, max_bins: int = 8,
                 min_bin_share: float = 0.03) -> VariableBinning:
    """Fit one variable's bins on a development population.

    Quantile bins for numerics, one bin per observed level for categoricals,
    and a MISSING bin whenever anything is absent — because "declined to
    state" is itself predictive and dropping it throws that away.
    """
    if target not in frame.columns:
        raise BinningError(f"{target!r} is not in the development frame")
    bad_total = int(frame[target].sum())
    good_total = int(len(frame) - bad_total)
    if bad_total == 0 or good_total == 0:
        raise BinningError(
            f"the development population has {bad_total} bad(s) and "
            f"{good_total} good(s). Weight of evidence is undefined without "
            "both, and a spec fitted here would score every future month "
            "with a constant.")

    column = frame[variable] if variable in frame.columns else pd.Series(
        [None] * len(frame), index=frame.index)
    present = column.notna()
    bins: list[Bin] = []

    if kind == "CATEGORICAL":
        levels = sorted(str(v) for v in column[present].unique())
        for index, level in enumerate(levels):
            mask = present & (column.astype("string") == level)
            bins.append(_bin_from(f"B{index + 1}", level, frame[target], mask,
                                  good_total, bad_total, members=(level,)))
    else:
        numbers = pd.to_numeric(column[present], errors="coerce")
        edges = _edges(numbers, max_bins=max_bins,
                       min_bin_share=min_bin_share)
        for index in range(len(edges) - 1):
            lower, upper = edges[index], edges[index + 1]
            mask = present & (pd.to_numeric(column, errors="coerce") > lower) \
                & (pd.to_numeric(column, errors="coerce") <= upper)
            bins.append(_bin_from(
                f"B{index + 1}", _range_label(lower, upper), frame[target],
                mask, good_total, bad_total,
                lower=None if lower == -math.inf else float(lower),
                upper=None if upper == math.inf else float(upper)))

    absent = (~present)
    if int(absent.sum()) > 0:
        bins.append(_bin_from(MISSING_BIN, "Missing", frame[target], absent,
                              good_total, bad_total, special=True))

    binning = VariableBinning(variable=variable, kind=kind, bins=bins)
    binning.monotonic = _is_monotonic(binning)
    return binning


def _bin_from(bin_id: str, label: str, target: pd.Series, mask: pd.Series,
              good_total: int, bad_total: int, *, lower: float | None = None,
              upper: float | None = None, members: tuple[str, ...] = (),
              special: bool = False) -> Bin:
    count = int(mask.sum())
    bad = int(target[mask].sum())
    good = count - bad
    woe, iv = _woe_and_iv(good, bad, good_total, bad_total)
    return Bin(bin_id=bin_id, label=label, lower=lower, upper=upper,
               members=members, count=count, good_count=good, bad_count=bad,
               bad_rate=(bad / count if count else 0.0),
               woe=woe, iv_contribution=iv, special=special)


def _edges(numbers: pd.Series, *, max_bins: int,
           min_bin_share: float) -> list[float]:
    """Quantile edges, merged until every bin carries a usable share.

    A bin holding 0.4% of the population produces a WoE nobody should rely
    on and a bad rate that swings on three accounts. Merging is preferable
    to reporting it.
    """
    clean = numbers.dropna()
    if clean.empty:
        return [-math.inf, math.inf]

    # Counts and flags defeat quantile binning. A variable that is 85% zero
    # has the same value at the 10th and the 80th percentile, so the edges
    # collapse to one bin and the WoE becomes a constant — which then makes
    # the coefficient unidentified rather than merely weak. Where the
    # variable takes few distinct values, split between them instead.
    distinct = sorted(float(v) for v in clean.unique())
    if 1 < len(distinct) <= max_bins + 1:
        cuts = [(a + b) / 2.0 for a, b in zip(distinct, distinct[1:],
                                              strict=False)]
        return [-math.inf, *cuts, math.inf]

    quantiles = np.linspace(0, 1, max_bins + 1)
    raw = sorted(set(float(v) for v in clean.quantile(quantiles)))
    if len(raw) < 2:
        return [-math.inf, math.inf]

    edges = [-math.inf] + raw[1:-1] + [math.inf]
    minimum = max(int(len(clean) * min_bin_share), 1)
    while len(edges) > 2:
        counts = [int(((clean > edges[i]) & (clean <= edges[i + 1])).sum())
                  for i in range(len(edges) - 1)]
        smallest = int(np.argmin(counts))
        if counts[smallest] >= minimum:
            break
        drop = smallest + 1 if smallest == 0 else smallest
        edges.pop(drop)
    return edges


def _range_label(lower: float, upper: float) -> str:
    left = "-inf" if lower == -math.inf else f"{lower:,.2f}"
    right = "inf" if upper == math.inf else f"{upper:,.2f}"
    return f"({left}, {right}]"


def _is_monotonic(binning: VariableBinning) -> bool:
    """Whether WoE moves in one direction across the ordinary bins.

    Reported rather than enforced. A non-monotonic WoE is sometimes right —
    very low and very high utilisation can both be risky — and forcing
    monotonicity would hide that.
    """
    ordinary = [b for b in binning.bins if not b.special]
    if len(ordinary) < 3:
        return False
    woes = [b.woe for b in ordinary]
    ups = all(b >= a for a, b in zip(woes, woes[1:], strict=False))
    downs = all(b <= a for a, b in zip(woes, woes[1:], strict=False))
    return ups or downs


def fit(frame: pd.DataFrame, *, scorecard_type: str, spec_version: str,
        target: str, kinds: dict[str, str],
        development_population: str = "") -> Spec:
    """Fit a whole specification on a development population."""
    spec = Spec(spec_version=spec_version, scorecard_type=scorecard_type,
                development_population=development_population,
                development_rows=len(frame),
                development_bads=int(frame[target].sum()))
    for variable, kind in kinds.items():
        spec.variables[variable] = fit_variable(
            frame, variable, target, kind=kind)
    return spec
