"""
Genuine ECL factor attribution, and the additive movement tools. Brief §5.

`decompose_ecl_factors` is the mandatory one and it is NOT
`decompose_movement`. A movement breakdown answers WHERE a total changed —
which sector, which borrower. A factor decomposition answers WHICH PARAMETER
moved it: the PD curves, the recovery assumptions, the exposure path, the
measurement horizon, the scenario weights, the discounting. A sector table is
not an answer to the second question, and the Cockpit must never offer one as
though it were.

How the factor bridge works
---------------------------
For every account present at BOTH dates, the opening and closing parameter sets
are evaluated through the governed calculator in `backend.cockpit_v2.ecl`
itself. A factor group is a switch: evaluate this group's inputs at the closing
date and every other group at the opening date, and the calculator returns what
the ECL would have been. With `n` groups there are `2**n` such combinations, and
the exact Shapley value of group `i` is

    phi_i = sum over subsets S not containing i of
              |S|! * (n - |S| - 1)! / n!  *  ( v(S + i) - v(S) )

which allocates the interactions symmetrically and — this is the property that
matters — sums exactly to `v(all) - v(none)`, the whole continuing-account
change. No ordering is chosen, so no waterfall has to be passed off as an
economic explanation, and there is no unexplained plug.

Six groups is 64 evaluations per account. That is exact, not sampled, and the
oracle fixtures in `tests/cockpit_v2/test_ecl_oracle.py` check it against
independently computed numbers.

What sits OUTSIDE the continuing-account bridge
------------------------------------------------
Entry, exit, overlays, FX and a changed measurement method are not parameter
moves on a comparable account, so they are reported as their own reconciled
lines rather than smuggled into a factor:

    closing = opening
            + entry + exit
            + sum(continuing-account factor contributions)
            + overlay change
            + fx effect
            + method change

The identity is asserted, not hoped for: `reconciled` is False and the residual
is reported if it ever fails.

What this is not
----------------
An attribution under a stated model. It is not evidence of real-world
causation, and the answer layer may say "under this decomposition PD changes
contributed X" and may not say "PD rose because the economy weakened". It is
also a HISTORICAL attribution between two actual dates, not a forward
sensitivity; `forward_sensitivity` below is the separate thing, and it says so.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from itertools import combinations
from typing import Any, Callable, Iterable, Sequence

from backend.cockpit_v2 import ATTRIBUTION_VERSION
from backend.cockpit_v2 import ecl as ecl_mod

# ------------------------------------------------------------ factor groups

#: The PD curves — conditional default hazards, and therefore survival,
#: marginal default probabilities and cumulative PD over the window.
FACTOR_PD = "pd_curves"
#: Recovery and loss severity — secured/unsecured LGD, collateral recognition,
#: haircuts, realisation costs and timing, as they reach the severity path.
FACTOR_LGD = "recovery_lgd"
#: The exposure path — drawn, undrawn, CCF and the amortisation of EAD.
FACTOR_EAD = "exposure_ead"
#: Staging, expressed as the measurement horizon it selects.
FACTOR_STAGING = "staging_horizon"
#: The scenario probability weights.
FACTOR_WEIGHTS = "scenario_weights"
#: Discounting — the effective interest rate the loss is brought back at.
FACTOR_DISCOUNT = "discounting"

#: Ordered for presentation only. The allocation itself is order-independent.
FACTOR_GROUPS: tuple[str, ...] = (
    FACTOR_PD, FACTOR_LGD, FACTOR_EAD, FACTOR_STAGING, FACTOR_WEIGHTS,
    FACTOR_DISCOUNT)

FACTOR_LABEL: dict[str, str] = {
    FACTOR_PD: "PD curves",
    FACTOR_LGD: "Recovery and LGD",
    FACTOR_EAD: "Exposure and EAD path",
    FACTOR_STAGING: "Staging and measurement horizon",
    FACTOR_WEIGHTS: "Scenario weights",
    FACTOR_DISCOUNT: "Discounting",
}

FACTOR_MEANING: dict[str, str] = {
    FACTOR_PD: ("The conditional default hazards, and so the survival and "
                "marginal default probabilities over the measurement window."),
    FACTOR_LGD: ("Loss severity given default: the secured and unsecured "
                 "components, recognised collateral after haircuts and "
                 "allocation, and the cost and timing of realisation."),
    FACTOR_EAD: ("Exposure at default over the window: drawn balance, undrawn "
                 "commitment, the credit conversion factor and amortisation."),
    FACTOR_STAGING: ("The measurement window the stage selects — twelve months "
                     "for Stage 1, remaining life for Stage 2."),
    FACTOR_WEIGHTS: "The probabilities attached to each scenario.",
    FACTOR_DISCOUNT: ("The effective interest rate the expected loss is "
                      "discounted back at."),
}

METHOD_SHAPLEY = "exact_shapley_over_factor_groups"

#: Structural lines outside the continuing-account bridge.
LINE_ENTRY = "portfolio_entry"
LINE_EXIT = "portfolio_exit"
LINE_OVERLAY = "overlay_change"
LINE_FX = "fx_effect"
LINE_METHOD = "method_change"

LINE_LABEL: dict[str, str] = {
    LINE_ENTRY: "New accounts",
    LINE_EXIT: "Accounts leaving the book",
    LINE_OVERLAY: "Separately identified overlay",
    LINE_FX: "Foreign exchange",
    LINE_METHOD: "Measurement method change",
}


# --------------------------------------------------------------- the switch


def _switched(opening: ecl_mod.FacilityMeasurement,
              closing: ecl_mod.FacilityMeasurement,
              groups: frozenset[str]) -> ecl_mod.FacilityMeasurement:
    """One facility with the named factor groups taken from the closing date.

    Every other group stays at its opening value. Building a real
    `FacilityMeasurement` rather than a shortcut means the combination is
    measured by exactly the same calculator as the endpoints, which is what
    makes the bridge reconcile.
    """
    take_weights = FACTOR_WEIGHTS in groups
    take_pd = FACTOR_PD in groups
    take_lgd = FACTOR_LGD in groups
    take_ead = FACTOR_EAD in groups
    take_df = FACTOR_DISCOUNT in groups
    horizon = (closing.horizon_periods if FACTOR_STAGING in groups
               else opening.horizon_periods)

    by_id_close = {s.scenario_id: s for s in closing.scenarios}
    scenarios: list[ecl_mod.ScenarioInput] = []
    for open_s in opening.scenarios:
        close_s = by_id_close.get(open_s.scenario_id, open_s)

        def pick(o: Sequence[float], c: Sequence[float], take: bool, n: int
                 ) -> tuple[float, ...]:
            src = list(c if take else o)
            if not src:
                src = [0.0]
            # A closing path can be shorter or longer than the opening one when
            # the facility has amortised a quarter closer to maturity. Holding
            # the last value flat is the stated convention rather than an
            # accident, and it never invents a period beyond the window.
            return tuple((src + [src[-1]] * n)[:n])

        n = max(open_s.periods, close_s.periods, horizon)
        scenarios.append(ecl_mod.ScenarioInput(
            scenario_id=open_s.scenario_id,
            weight=(close_s.weight if take_weights else open_s.weight),
            hazard=pick(open_s.hazard, close_s.hazard, take_pd, n),
            lgd=pick(open_s.lgd, close_s.lgd, take_lgd, n),
            ead=pick(open_s.ead, close_s.ead, take_ead, n),
            discount=pick(open_s.discount, close_s.discount, take_df, n)))

    # Weights are switched as a set, so they still sum to one either way.
    ecl_mod.check_weights(s.weight for s in scenarios)

    return ecl_mod.FacilityMeasurement(
        facility_id=opening.facility_id, borrower_id=opening.borrower_id,
        reporting_date=closing.reporting_date, stage=opening.stage,
        horizon_periods=max(1, min(horizon, max(s.periods for s in scenarios))),
        scenarios=tuple(scenarios), overlay=0.0,
        currency=opening.currency, fx_rate=opening.fx_rate,
        method=opening.method, model_version=opening.model_version)


def _shapley_weights(n: int) -> dict[int, float]:
    """`|S|! (n-|S|-1)! / n!` for each subset size, computed once per n."""
    total = math.factorial(n)
    return {k: math.factorial(k) * math.factorial(n - k - 1) / total
            for k in range(n)}


def shapley_contributions(
    value: Callable[[frozenset[str]], float],
    groups: Sequence[str],
) -> dict[str, float]:
    """Exact Shapley values of `groups` under the coalition function `value`.

    Generic on purpose: the oracle fixtures drive it with a two-factor
    `PD x LGD x EAD` function and the demo book drives it with the full
    calculator, and both must be the same allocation rule.
    """
    names = list(groups)
    n = len(names)
    if n == 0:
        return {}
    coefficient = _shapley_weights(n)

    # Every coalition is evaluated once and reused across the n marginal sums.
    cache: dict[frozenset[str], float] = {}

    def v(s: frozenset[str]) -> float:
        if s not in cache:
            cache[s] = float(value(s))
        return cache[s]

    out: dict[str, float] = {}
    for name in names:
        rest = [g for g in names if g != name]
        acc = 0.0
        for size in range(len(rest) + 1):
            w = coefficient[size]
            for subset in combinations(rest, size):
                s = frozenset(subset)
                acc += w * (v(s | {name}) - v(s))
        out[name] = acc
    return out


# ----------------------------------------------------------------- results


@dataclass
class FactorContribution:
    factor: str
    label: str
    meaning: str
    contribution: float
    share_of_net_change: float | None

    def to_dict(self) -> dict[str, Any]:
        return {"factor": self.factor, "label": self.label,
                "meaning": self.meaning, "contribution": self.contribution,
                "share_of_net_change": self.share_of_net_change}


@dataclass
class StructuralLine:
    line: str
    label: str
    amount: float
    accounts: int
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"line": self.line, "label": self.label, "amount": self.amount,
                "accounts": self.accounts, "note": self.note}


@dataclass
class FactorDecomposition:
    """The reconciled opening-to-closing ECL bridge."""

    opening_date: str
    closing_date: str
    opening_ecl: float
    closing_ecl: float
    net_change: float
    factors: list[FactorContribution] = field(default_factory=list)
    structural: list[StructuralLine] = field(default_factory=list)
    #: Per-facility factor contributions, for drill-down and "which borrower
    #: explains most of that".
    by_facility: list[dict[str, Any]] = field(default_factory=list)
    continuing_accounts: int = 0
    entered_accounts: int = 0
    exited_accounts: int = 0
    method: str = METHOD_SHAPLEY
    method_version: str = ATTRIBUTION_VERSION
    model_version: str = ecl_mod.MODEL_VERSION
    currency: str = "INR"
    unit: str = "INR crore"
    reconciled: bool = False
    residual: float = 0.0
    limitations: list[str] = field(default_factory=list)
    #: Set when the net change is too close to zero for shares to mean
    #: anything. Brief §5.1: return null and explain, do not divide.
    shares_available: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "opening_date": self.opening_date,
            "closing_date": self.closing_date,
            "opening_ecl": self.opening_ecl,
            "closing_ecl": self.closing_ecl,
            "net_change": self.net_change,
            "factors": [f.to_dict() for f in self.factors],
            "structural": [s.to_dict() for s in self.structural],
            "by_facility": self.by_facility,
            "continuing_accounts": self.continuing_accounts,
            "entered_accounts": self.entered_accounts,
            "exited_accounts": self.exited_accounts,
            "method": self.method,
            "method_version": self.method_version,
            "model_version": self.model_version,
            "currency": self.currency,
            "unit": self.unit,
            "reconciled": self.reconciled,
            "residual": self.residual,
            "limitations": list(self.limitations),
            "shares_available": self.shares_available,
            "attribution_is_not_causation": (
                "These are contributions under the stated attribution method "
                "and model version. They quantify how much of the movement is "
                "allocated to each parameter group; they are not evidence of a "
                "real-world cause."),
        }

    def factor(self, name: str) -> FactorContribution | None:
        for f in self.factors:
            if f.factor == name:
                return f
        return None


#: Below this, in currency units, the net change is treated as no net change
#: and shares are withheld rather than computed. Brief §5.1.
NEAR_ZERO = 1e-9


def _share(amount: float, net: float) -> float | None:
    if abs(net) <= NEAR_ZERO:
        return None
    return amount / net * 100.0


def decompose_ecl_factors(
    opening: Sequence[ecl_mod.FacilityMeasurement],
    closing: Sequence[ecl_mod.FacilityMeasurement],
    *, opening_date: str = "", closing_date: str = "",
    groups: Sequence[str] = FACTOR_GROUPS,
    currency: str = "INR", unit: str = "INR crore",
    top_facilities: int = 25,
) -> FactorDecomposition:
    """Reconcile opening ECL to closing ECL by factor. Brief §5.4."""
    open_by_id = {f.facility_id: f for f in opening}
    close_by_id = {f.facility_id: f for f in closing}

    open_results = {k: ecl_mod.measure(v) for k, v in open_by_id.items()}
    close_results = {k: ecl_mod.measure(v) for k, v in close_by_id.items()}

    opening_total = sum(r.reported_ecl for r in open_results.values())
    closing_total = sum(r.reported_ecl for r in close_results.values())
    net = closing_total - opening_total

    continuing = sorted(set(open_by_id) & set(close_by_id))
    entered = sorted(set(close_by_id) - set(open_by_id))
    exited = sorted(set(open_by_id) - set(close_by_id))

    entry_amount = sum(close_results[k].reported_ecl for k in entered)
    exit_amount = -sum(open_results[k].reported_ecl for k in exited)

    totals: dict[str, float] = {g: 0.0 for g in groups}
    overlay_change = 0.0
    fx_effect = 0.0
    method_change = 0.0
    method_changed_accounts = 0
    per_facility: list[dict[str, Any]] = []

    for fid in continuing:
        o, c = open_by_id[fid], close_by_id[fid]
        o_res, c_res = open_results[fid], close_results[fid]

        overlay_change += c.overlay - o.overlay

        # FX is separated before the parameter bridge so a translation movement
        # is never allocated to PD. Both endpoints are restated at the opening
        # rate for the factor evaluation; the difference is its own line.
        if not math.isclose(o.fx_rate, c.fx_rate, rel_tol=0.0, abs_tol=1e-12):
            fx_effect += c_res.weighted_model_ecl * (
                (c.fx_rate - o.fx_rate) / o.fx_rate if o.fx_rate else 0.0)

        if o.method != c.method:
            # A performing account that became credit-impaired is not a
            # parameter move: the measurement itself changed. Brief §5.4 says
            # to return an explicit reconciled method-change block rather than
            # invent PD precision, so the whole movement goes on that line.
            method_change += c_res.weighted_model_ecl - o_res.weighted_model_ecl
            method_changed_accounts += 1
            per_facility.append({
                "facility_id": fid, "borrower_id": o.borrower_id,
                "opening_ecl": o_res.reported_ecl,
                "closing_ecl": c_res.reported_ecl,
                "net_change": c_res.reported_ecl - o_res.reported_ecl,
                "method_change": True,
                "opening_method": o.method, "closing_method": c.method,
                "factors": {}})
            continue

        def value(subset: frozenset[str], _o=o, _c=c) -> float:
            return ecl_mod.measure(_switched(_o, _c, subset)).weighted_model_ecl

        contributions = shapley_contributions(value, groups)
        for g, amount in contributions.items():
            totals[g] += amount

        per_facility.append({
            "facility_id": fid, "borrower_id": o.borrower_id,
            "opening_ecl": o_res.reported_ecl,
            "closing_ecl": c_res.reported_ecl,
            "net_change": c_res.reported_ecl - o_res.reported_ecl,
            "method_change": False,
            "factors": dict(contributions)})

    shares_available = abs(net) > NEAR_ZERO

    factors = [
        FactorContribution(
            factor=g, label=FACTOR_LABEL.get(g, g),
            meaning=FACTOR_MEANING.get(g, ""), contribution=totals[g],
            share_of_net_change=_share(totals[g], net) if shares_available else None)
        for g in groups]

    structural = [
        StructuralLine(LINE_ENTRY, LINE_LABEL[LINE_ENTRY], entry_amount,
                       len(entered),
                       "Accounts present at the closing date only. Their whole "
                       "closing ECL is new; there is no opening comparator to "
                       "attribute it against."),
        StructuralLine(LINE_EXIT, LINE_LABEL[LINE_EXIT], exit_amount,
                       len(exited),
                       "Accounts present at the opening date only. Their whole "
                       "opening ECL leaves the book. Repayment, write-off and "
                       "sale all appear here and none of them implies recovery."),
        StructuralLine(LINE_OVERLAY, LINE_LABEL[LINE_OVERLAY], overlay_change,
                       sum(1 for f in continuing
                           if not math.isclose(open_by_id[f].overlay,
                                               close_by_id[f].overlay,
                                               abs_tol=1e-12)),
                       "Management overlay, identified separately from the "
                       "modelled result at both dates."),
        StructuralLine(LINE_FX, LINE_LABEL[LINE_FX], fx_effect,
                       sum(1 for f in continuing
                           if not math.isclose(open_by_id[f].fx_rate,
                                               close_by_id[f].fx_rate,
                                               abs_tol=1e-12)),
                       "Translation into the reporting currency, separated "
                       "before the parameter bridge."),
        StructuralLine(LINE_METHOD, LINE_LABEL[LINE_METHOD], method_change,
                       method_changed_accounts,
                       "Accounts whose measurement method changed between the "
                       "dates. The common factor engine cannot represent that "
                       "as a parameter move, so the whole movement is reported "
                       "here rather than attributed."),
    ]

    accounted = (sum(totals.values())
                 + sum(s.amount for s in structural))
    residual = net - accounted

    limitations: list[str] = []
    if not shares_available:
        limitations.append(
            "The net change is effectively zero, so no contribution share is "
            "reported. The offsetting positive and negative movements "
            "underneath it are shown instead.")
    if method_changed_accounts:
        limitations.append(
            f"{method_changed_accounts} account(s) changed measurement method "
            f"between the two dates. Their movement is reported on the method "
            f"change line and is not attributed to a parameter.")
    if entered or exited:
        limitations.append(
            f"{len(entered)} account(s) entered and {len(exited)} left the "
            f"book. Entry and exit are reported as their own lines; no zero "
            f"comparator was manufactured for either.")

    decomposition = FactorDecomposition(
        opening_date=opening_date, closing_date=closing_date,
        opening_ecl=opening_total, closing_ecl=closing_total, net_change=net,
        factors=factors, structural=structural,
        by_facility=sorted(per_facility,
                           key=lambda r: abs(r["net_change"]),
                           reverse=True)[:max(0, int(top_facilities))],
        continuing_accounts=len(continuing), entered_accounts=len(entered),
        exited_accounts=len(exited), currency=currency, unit=unit,
        reconciled=ecl_mod.close_enough(residual, 0.0),
        residual=residual, limitations=limitations,
        shares_available=shares_available)

    if not decomposition.reconciled:
        decomposition.limitations.append(
            f"The bridge did not reconcile: a residual of {residual:.10f} "
            f"{unit} is unexplained. The decomposition is reported with that "
            f"residual visible rather than absorbed into a factor.")
    return decomposition


def forward_sensitivity(
    base: ecl_mod.FacilityMeasurement,
    *, factor: str, shocked: ecl_mod.FacilityMeasurement,
) -> dict[str, Any]:
    """What ECL WOULD be if one factor group took a hypothetical value.

    Explicitly not an attribution: nothing here happened. Kept separate from
    `decompose_ecl_factors` so a forward what-if can never be reported as a
    historical explanation of an actual movement.
    """
    before = ecl_mod.measure(base)
    after = ecl_mod.measure(_switched(base, shocked, frozenset({factor})))
    return {
        "kind": "forward_hypothetical_sensitivity",
        "is_historical_attribution": False,
        "factor": factor, "label": FACTOR_LABEL.get(factor, factor),
        "base_ecl": before.weighted_model_ecl,
        "shocked_ecl": after.weighted_model_ecl,
        "difference": after.weighted_model_ecl - before.weighted_model_ecl,
        "method_version": ATTRIBUTION_VERSION,
        "note": ("A hypothetical sensitivity computed by re-running the "
                 "governed calculator with this factor group replaced. It "
                 "describes what would happen, not what did."),
    }


# ------------------------------------------------- additive movement (§5.1)


def decompose_movement(
    opening: dict[str, float], closing: dict[str, float], *,
    measure_name: str = "", unit: str = "", opening_date: str = "",
    closing_date: str = "", top: int = 0,
) -> dict[str, Any]:
    """WHERE an additive metric changed, by member of one dimension.

    Currency stays currency: this returns amounts in `unit` and a signed share
    of the net movement. It does not convert a currency movement into basis
    points, which would be a unit that does not exist for it.
    """
    members = sorted(set(opening) | set(closing))
    o_total = float(sum(opening.values()))
    c_total = float(sum(closing.values()))
    net = c_total - o_total
    shares = abs(net) > NEAR_ZERO

    rows: list[dict[str, Any]] = []
    positive = negative = 0.0
    for m in members:
        o = float(opening.get(m, 0.0))
        c = float(closing.get(m, 0.0))
        change = c - o
        if change > 0:
            positive += change
        else:
            negative += change
        rows.append({
            "member": m, "opening": o, "closing": c, "change": change,
            # Shares can exceed 100% where other members offset them. Brief
            # §5.1 is explicit that they must not be clipped.
            "share_of_net_change": (change / net * 100.0) if shares else None,
            "membership": ("continuing" if m in opening and m in closing
                           else "new" if m in closing else "exited"),
        })

    rows.sort(key=lambda r: abs(r["change"]), reverse=True)
    reconciled = ecl_mod.close_enough(
        sum(r["change"] for r in rows), net, tolerance=1e-6)

    return {
        "tool": "decompose_movement",
        "measure": measure_name, "unit": unit,
        "opening_date": opening_date, "closing_date": closing_date,
        "opening_total": o_total, "closing_total": c_total, "net_change": net,
        "rows": rows[:top] if top and top > 0 else rows,
        "rows_returned": min(top, len(rows)) if top and top > 0 else len(rows),
        "rows_total": len(rows),
        "truncated": bool(top and 0 < top < len(rows)),
        "positive_contributions": positive,
        "negative_contributions": negative,
        "matched": sum(1 for r in rows if r["membership"] == "continuing"),
        "new": sum(1 for r in rows if r["membership"] == "new"),
        "exited": sum(1 for r in rows if r["membership"] == "exited"),
        "shares_available": shares,
        "shares_note": ("" if shares else
                        "The net movement is effectively zero, so no "
                        "contribution share is meaningful. The offsetting "
                        "positive and negative totals are reported instead."),
        "reconciled": reconciled,
        "method": "additive_member_change",
        "limitations": ([] if shares else
                        ["No net change: shares withheld deliberately."]),
    }


# ---------------------------------------------------- ratio movement (§5.2)


def decompose_ratio(
    *, numerator_opening: float, numerator_closing: float,
    denominator_opening: float, denominator_closing: float,
    ratio_name: str = "", as_basis_points: bool = True,
    opening_date: str = "", closing_date: str = "",
) -> dict[str, Any]:
    """Split a ratio movement into a numerator and a denominator effect.

    The exact symmetric two-factor decomposition of brief §5.2:

        numerator effect   = (N1 - N0) * (1/D0 + 1/D1) / 2
        denominator effect = (N0 + N1) * (1/D1 - 1/D0) / 2

    They sum to `N1/D1 - N0/D0` exactly. There is no third "mix" term, because
    these two already account for the entire change and inventing a third would
    make the parts sum to more than the whole.
    """
    n0, n1 = float(numerator_opening), float(numerator_closing)
    d0, d1 = float(denominator_opening), float(denominator_closing)

    if d0 == 0 or d1 == 0:
        return {
            "tool": "decompose_ratio", "ratio": ratio_name,
            "opening_date": opening_date, "closing_date": closing_date,
            "available": False,
            "reason": ("A ratio movement cannot be decomposed when a "
                       "denominator is zero: the opening or closing ratio is "
                       "undefined, so there is no change to attribute."),
            "numerator_opening": n0, "numerator_closing": n1,
            "denominator_opening": d0, "denominator_closing": d1,
            "method": "symmetric_two_factor", "reconciled": False,
        }

    r0, r1 = n0 / d0, n1 / d1
    numerator_effect = (n1 - n0) * (1.0 / d0 + 1.0 / d1) / 2.0
    denominator_effect = (n0 + n1) * (1.0 / d1 - 1.0 / d0) / 2.0
    change = r1 - r0
    scale = 10_000.0 if as_basis_points else 1.0

    return {
        "tool": "decompose_ratio", "ratio": ratio_name, "available": True,
        "opening_date": opening_date, "closing_date": closing_date,
        "opening_ratio": r0, "closing_ratio": r1, "change": change,
        "numerator_opening": n0, "numerator_closing": n1,
        "denominator_opening": d0, "denominator_closing": d1,
        "numerator_effect": numerator_effect,
        "denominator_effect": denominator_effect,
        "unit": "basis points" if as_basis_points else "ratio",
        "change_scaled": change * scale,
        "numerator_effect_scaled": numerator_effect * scale,
        "denominator_effect_scaled": denominator_effect * scale,
        "method": "symmetric_two_factor",
        "method_note": ("Exact symmetric two-factor decomposition. The two "
                        "effects sum to the whole change; there is no separate "
                        "mix term because there is nothing left for one to "
                        "explain."),
        "reconciled": ecl_mod.close_enough(
            numerator_effect + denominator_effect, change, tolerance=1e-12),
    }


def decompose_rate_mix(
    opening: dict[str, tuple[float, float]],
    closing: dict[str, tuple[float, float]],
    *, rate_name: str = "", as_basis_points: bool = True,
) -> dict[str, Any]:
    """Within-rate and mix effects for `R = sum(w_i * r_i)`. Brief §5.2.

    Each entry maps a segment to `(weight, rate)`. Weights are renormalised to
    one at each date, and the symmetric midpoint decomposition is

        within-rate_i = (w0_i + w1_i)/2 * (r1_i - r0_i)
        mix_i         = (w1_i - w0_i)   * ((r0_i + r1_i)/2 - R_mid)

    A SEPARATE VIEW from `decompose_ratio`, offered when the question is about
    segment composition rather than about a numerator and a denominator. The
    two are never added together.
    """
    members = sorted(set(opening) | set(closing))

    def norm(src: dict[str, tuple[float, float]]) -> dict[str, tuple[float, float]]:
        total = sum(max(float(w), 0.0) for w, _ in src.values())
        if total <= 0:
            return {m: (0.0, float(r)) for m, (_, r) in src.items()}
        return {m: (float(w) / total, float(r)) for m, (w, r) in src.items()}

    o = norm(opening)
    c = norm(closing)
    r0 = sum(w * r for w, r in o.values())
    r1 = sum(w * r for w, r in c.values())
    mid = (r0 + r1) / 2.0
    scale = 10_000.0 if as_basis_points else 1.0

    rows = []
    for m in members:
        w0, rate0 = o.get(m, (0.0, 0.0))
        w1, rate1 = c.get(m, (0.0, 0.0))
        entering = m not in o
        exiting = m not in c
        # An entering segment has no opening rate; using zero would report a
        # rate improvement that did not happen, so its whole effect is mix.
        if entering:
            rate0 = rate1
        if exiting:
            rate1 = rate0
        within = (w0 + w1) / 2.0 * (rate1 - rate0)
        mix = (w1 - w0) * ((rate0 + rate1) / 2.0 - mid)
        rows.append({
            "member": m, "opening_weight": w0, "closing_weight": w1,
            "opening_rate": (None if entering else rate0),
            "closing_rate": (None if exiting else rate1),
            "within_rate_effect": within, "mix_effect": mix,
            "within_rate_effect_scaled": within * scale,
            "mix_effect_scaled": mix * scale,
            "membership": ("new" if entering else
                           "exited" if exiting else "continuing"),
        })

    total_within = sum(r["within_rate_effect"] for r in rows)
    total_mix = sum(r["mix_effect"] for r in rows)
    change = r1 - r0
    return {
        "tool": "decompose_rate_mix", "rate": rate_name,
        "opening_rate": r0, "closing_rate": r1, "change": change,
        "change_scaled": change * scale,
        "within_rate_total": total_within, "mix_total": total_mix,
        "within_rate_total_scaled": total_within * scale,
        "mix_total_scaled": total_mix * scale,
        "unit": "basis points" if as_basis_points else "rate",
        "rows": sorted(rows,
                       key=lambda r: abs(r["within_rate_effect"] + r["mix_effect"]),
                       reverse=True),
        "method": "symmetric_midpoint_rate_mix",
        "reconciled": ecl_mod.close_enough(total_within + total_mix, change,
                                           tolerance=1e-9),
        "method_note": ("A segment rate/mix view. It is not the numerator/"
                        "denominator decomposition and the two are never "
                        "combined."),
    }


# ------------------------------------------------------------ history (§5.3)


def metric_history(points: Sequence[tuple[str, float | None]], *,
                   measure_name: str = "", unit: str = "") -> dict[str, Any]:
    """A measure over its actual reporting periods, with honest statistics.

    The z-score compares the LATEST observation to the ones before it only —
    including the latest in its own mean and standard deviation would flatten
    exactly the outlier it is supposed to detect. With a short history the
    measure is reported as descriptive and the observation count is stated,
    because eight quarters cannot establish statistical abnormality and the
    Cockpit must not claim it can.
    """
    series = [(str(p), None if v is None else float(v)) for p, v in points]
    observed = [(p, v) for p, v in series if v is not None]
    values = [v for _, v in observed]

    out: dict[str, Any] = {
        "tool": "metric_history", "measure": measure_name, "unit": unit,
        "points": [{"period": p, "value": v} for p, v in series],
        "observations": len(observed),
        "missing_periods": [p for p, v in series if v is None],
        "latest_period": observed[-1][0] if observed else None,
        "latest": values[-1] if values else None,
        "prior_period": observed[-2][0] if len(observed) > 1 else None,
        "prior": values[-2] if len(values) > 1 else None,
        "change": (values[-1] - values[-2]) if len(values) > 1 else None,
        "z_score": None, "z_score_basis": "", "mean": None, "std_dev": None,
        "comparator_periods": max(0, len(values) - 1),
        "is_statistically_robust": False,
        "limitations": [],
    }

    if len(values) < 3:
        out["limitations"].append(
            f"Only {len(values)} observation(s) are available, so no z-score "
            f"is reported. A change can be described but not called unusual.")
        return out

    prior = values[:-1]
    mean = sum(prior) / len(prior)
    variance = sum((x - mean) ** 2 for x in prior) / (len(prior) - 1)
    sd = math.sqrt(variance)
    out["mean"] = mean
    out["std_dev"] = sd
    out["z_score_basis"] = (
        f"the latest observation against the {len(prior)} preceding "
        f"observations, which are not included in it")

    if sd <= 0:
        out["limitations"].append(
            "Every preceding observation is identical, so the standard "
            "deviation is zero and a z-score cannot be computed. The change is "
            "reported as an amount instead.")
        return out

    out["z_score"] = (values[-1] - mean) / sd
    out["limitations"].append(
        f"This z-score is a descriptive comparison against {len(prior)} prior "
        f"observations. That is far too short a history to establish "
        f"statistical abnormality, and no seasonality adjustment is applied.")
    return out


__all__ = [
    "ATTRIBUTION_VERSION", "FACTOR_DISCOUNT", "FACTOR_EAD", "FACTOR_GROUPS",
    "FACTOR_LABEL", "FACTOR_LGD", "FACTOR_MEANING", "FACTOR_PD",
    "FACTOR_STAGING", "FACTOR_WEIGHTS", "FactorContribution",
    "FactorDecomposition", "LINE_ENTRY", "LINE_EXIT", "LINE_FX", "LINE_METHOD",
    "LINE_OVERLAY", "METHOD_SHAPLEY", "StructuralLine", "decompose_ecl_factors",
    "decompose_movement", "decompose_ratio", "decompose_rate_mix",
    "forward_sensitivity", "metric_history", "shapley_contributions",
]
