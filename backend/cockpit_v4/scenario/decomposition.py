"""The universal ECL decomposition contract (v3.1 §10.3, §11; UAT-02, UAT-09).

EVERY ECL decomposition CreditProbe shows -- a scenario's selected scope, the
total active book, a method comparison, a period movement -- is expressed in
ONE taxonomy: the same component id, label, definition, order and colour
identity everywhere. A component a decomposition cannot measure is still
listed, as N/A with the reason, or as ZERO when it was measured and did not
move. Definitions are never silently changed to make a chart look complete.

Mathematics, checked before a decomposition is published:

    opening + sum(components) + residual = closing          (each scope)
    selected delta + rest-of-book delta = total-book delta  (cross-scope)

Both scopes are built from the SAME execution object (`bridge.Computed`),
never one estimated from the other (§11). The rest of the book keeps its
booked ECL exactly -- a scenario restricted to a cohort moves nothing outside
it -- so its delta is zero and the reason is published beside it.

Accounting decomposition answers "why did ECL move under this scenario?".
The ML emulator's SHAP explanation answers "why did the model predict this?"
and is NEVER placed in this contract (§10.4, DECOMP10).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from backend.cockpit_v4.scenario import ledger as lg

CONTRACT_VERSION = "gw-decomposition-1.0.0"

#: Kinds of taxonomy entry. `total` is an anchor bar, `flow` a movement of
#: the book between periods, `driver` a scenario/driver effect.
TOTAL, FLOW, DRIVER = "total", "flow", "driver"


@dataclass(frozen=True)
class Component:
    id: str
    label: str
    kind: str
    definition: str


#: THE TAXONOMY, in its one order. The frontend colour map keys on `id`.
TAXONOMY: tuple[Component, ...] = (
    Component("opening", "Opening ECL", TOTAL,
              "Booked (reported) ECL of the scope before the movement."),
    Component("new_originations", "New originations", FLOW,
              "ECL of exposures that entered the book between the periods."),
    Component("repayment_amortisation", "Repayment / amortisation", FLOW,
              "ECL released as exposure was repaid or amortised."),
    Component("stage_1_to_2", "Stage 1 → 2", FLOW,
              "Change from exposures migrating Stage 1 to Stage 2 (SICR)."),
    Component("stage_2_to_3", "Stage 2 → 3", FLOW,
              "Change from exposures migrating Stage 2 to Stage 3."),
    Component("cures", "Cures", FLOW,
              "ECL released by exposures curing to a better stage."),
    Component("new_defaults", "New defaults", FLOW,
              "Change from exposures newly defaulting."),
    Component("pd", "PD", DRIVER,
              "Effect of the probability-of-default moves."),
    Component("lgd", "LGD", DRIVER,
              "Effect of the loss-given-default moves."),
    Component("ccf_ead", "CCF / EAD / utilisation", DRIVER,
              "Effect of exposure moves: CCF, drawn balance, utilisation, "
              "EAD."),
    Component("collateral", "Collateral", DRIVER,
              "Effect of collateral value moves, via their governed LGD "
              "translation."),
    Component("rating_score", "Rating / score migration", DRIVER,
              "Effect of rating-notch or score-band moves via the governed "
              "masterscale / scorecards."),
    Component("macro", "Macro (MEV)", DRIVER,
              "Effect of macroeconomic moves via the governed sensitivity "
              "library."),
    Component("sector_segment", "Sector / segment rule", DRIVER,
              "Effect of a rule whose driver is a sector or segment "
              "selection rather than a parameter."),
    Component("management_overlay", "Management overlay / user-defined",
              DRIVER, "The reader's own stated impact (Method 3) or a "
                      "management overlay."),
    Component("recoveries", "Recoveries / write-offs", FLOW,
              "ECL released through recoveries and write-offs."),
    Component("unattributed_method_effect", "Method effect (not attributable)",
              DRIVER, "A method's total scenario effect that the method "
                      "cannot split by driver (the ML emulator predicts the "
                      "whole move)."),
    Component("calibration_gap", "Calibration gap", DRIVER,
              "Difference between a method's own baseline and booked ECL; "
              "never hidden inside scenario effects (§11)."),
    Component("residual", "Interaction / residual", DRIVER,
              "What the driver bars do not explain. Shown, never spread."),
    Component("closing", "Closing ECL", TOTAL,
              "ECL of the scope after the movement."),
)

BY_ID: dict[str, Component] = {c.id: c for c in TAXONOMY}
ORDER: tuple[str, ...] = tuple(c.id for c in TAXONOMY)

MEASURED, ZERO, NOT_APPLICABLE = "MEASURED", "ZERO", "N/A"

#: Why a between-period flow is not part of a scenario decomposition.
SCENARIO_FLOW_REASON = ("A scenario revalues the frozen book at one period; "
                        "movements BETWEEN periods (originations, "
                        "repayments, cures, defaults, recoveries) are not "
                        "part of it.")

#: A field a shock moved -> the taxonomy component its effect belongs to.
FIELD_COMPONENT = {
    "pd_pit_12m": "pd", "pd_lifetime": "pd", "lgd_pct": "lgd",
    "ccf": "ccf_ead", "ccf_pit": "ccf_ead", "ead_sar_mn": "ccf_ead",
    "drawn_sar_mn": "ccf_ead", "undrawn_sar_mn": "ccf_ead",
    "balance_sar_mn": "ccf_ead", "utilisation_pct": "ccf_ead",
    "ecl_overlay_sar_mn": "management_overlay",
}


def _d(value: Any) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value or 0))


def _stage_na(stage_policy: str) -> str:
    return ("Stages are held at their reported values (stage policy "
            "'frozen'), so no exposure migrates." if stage_policy == "frozen"
            else "A stage re-test was requested; this book publishes no "
                 "lifetime ECL curve for re-staged exposures, so migrating "
                 "ECL is not invented (DECOMP11/12).")


def scope_decomposition(*, scope: str, label: str, opening: Decimal,
                        closing: Decimal, contributions: Mapping[str, Decimal],
                        detail: Mapping[str, Sequence[Mapping[str, Any]]],
                        not_applicable: Mapping[str, str],
                        measured: Sequence[str] = (),
                        kpis: Mapping[str, Any] | None = None,
                        tolerance: Decimal = lg.CURRENCY) -> dict[str, Any]:
    """One scope's bridge, every taxonomy component present, reconciled.

    `contributions` holds the measured driver values by component id;
    `measured` names components that were measured (a measured zero is ZERO,
    not N/A); `not_applicable` gives the reason for the rest. The residual is
    computed, never supplied, so a bridge cannot be made to close by hand.
    """
    opening, closing = _d(opening), _d(closing)
    change = closing - opening
    explained = sum((_d(v) for k, v in contributions.items()
                     if k != "residual"), Decimal(0))
    residual = change - explained
    rows: list[dict[str, Any]] = []
    for comp in TAXONOMY:
        if comp.id == "opening":
            rows.append(_row(comp, opening, MEASURED))
        elif comp.id == "closing":
            rows.append(_row(comp, closing, MEASURED))
        elif comp.id == "residual":
            rows.append(_row(comp, residual,
                             MEASURED if residual != 0 else ZERO,
                             reason="" if residual != 0 else
                             "the driver bars explain the whole change"))
        elif comp.id in contributions:
            value = _d(contributions[comp.id])
            rows.append(_row(comp, value, MEASURED if value != 0 else ZERO,
                             detail=list(detail.get(comp.id, []))))
        elif comp.id in measured:
            rows.append(_row(comp, Decimal(0), ZERO))
        else:
            rows.append(_row(comp, None, NOT_APPLICABLE,
                             reason=not_applicable.get(
                                 comp.id, "not part of this decomposition")))
    total = opening + sum((r["value_decimal"] for r in rows
                           if r["kind"] != TOTAL
                           and r["value_decimal"] is not None), Decimal(0))
    reconciles = abs(total - closing) <= tolerance
    if not reconciles:  # pragma: no cover - the residual makes this exact
        raise ValueError(f"{scope} bridge does not close: {total} != "
                         f"{closing}")
    for r in rows:
        r.pop("value_decimal")
    drivers = [r for r in rows if r["kind"] != TOTAL
               and r["status"] == MEASURED and r["id"] != "residual"]
    largest = max(drivers, key=lambda r: abs(Decimal(r["value"])),
                  default=None)
    return {
        "scope": scope, "label": label,
        "opening": str(opening), "closing": str(closing),
        "change": str(change),
        "change_pct": (str((change / opening * 100).quantize(Decimal("0.0001")))
                       if opening else None),
        "components": rows, "residual": str(residual),
        "reconciles": reconciles,
        "identity": "opening + components + residual = closing",
        "kpis": {"opening": str(opening), "closing": str(closing),
                 "change": str(change),
                 "change_pct": (str((change / opening * 100)
                                    .quantize(Decimal("0.0001")))
                                if opening else None),
                 "largest_driver": largest["label"] if largest else None,
                 "largest_driver_value": largest["value"] if largest
                 else None,
                 **dict(kpis or {})},
    }


def _row(comp: Component, value: Decimal | None, status: str, *,
         reason: str = "", detail: list[Any] | None = None
         ) -> dict[str, Any]:
    return {"id": comp.id, "label": comp.label, "kind": comp.kind,
            "definition": comp.definition, "order": ORDER.index(comp.id),
            "value": None if value is None else str(value),
            "value_decimal": value, "status": status, "reason": reason,
            "detail": detail or []}


#: DECOMP21: the label when the selected population is the whole book.
SCOPE_EQUALS_BOOK = "Selected scope = Total book"


def dual_scope(*, method: str, method_label: str,
               selected: Mapping[str, Any], book_opening: Decimal,
               selected_label: str, book_label: str,
               selected_equals_total: bool, stage_policy: str,
               selected_kpis: Mapping[str, Any] | None = None,
               book_kpis: Mapping[str, Any] | None = None,
               tolerance: Decimal = lg.CURRENCY) -> dict[str, Any]:
    """Selected scope AND total active book, from ONE execution (§10.3.1).

    `selected` carries `opening`, `closing`, `contributions`, `detail`,
    `measured` and `not_applicable` for the selected scope. The total book is
    the selected scope plus the rest of the book held at its booked ECL: its
    components are the selected components (the rest contributes zero), its
    opening is the whole book's booked ECL.
    """
    sel_open, sel_close = _d(selected["opening"]), _d(selected["closing"])
    na = {**_default_na(stage_policy), **dict(selected.get(
        "not_applicable") or {})}
    sel = scope_decomposition(
        scope="selected", label=selected_label, opening=sel_open,
        closing=sel_close, contributions=selected["contributions"],
        detail=selected.get("detail") or {}, not_applicable=na,
        measured=selected.get("measured") or (), kpis=selected_kpis,
        tolerance=tolerance)
    # "Selected scope = total book": one population, so ONE opening -- not
    # the same total summed twice by two engines with different rounding.
    book_open = sel_open if selected_equals_total else _d(book_opening)
    sel_delta = sel_close - sel_open
    rest_delta = Decimal(0)
    book_close = book_open + sel_delta + rest_delta
    total = scope_decomposition(
        scope="total", label=book_label, opening=book_open,
        closing=book_close, contributions=selected["contributions"],
        detail=selected.get("detail") or {}, not_applicable=na,
        measured=selected.get("measured") or (), kpis=book_kpis,
        tolerance=tolerance)
    total_delta = book_close - book_open
    cross_ok = abs(sel_delta + rest_delta - total_delta) <= tolerance
    if not cross_ok:  # pragma: no cover - arithmetic identity
        raise ValueError("selected + rest-of-book != total")
    return {
        "contract_version": CONTRACT_VERSION, "method": method,
        "method_label": method_label,
        "selected_equals_total": selected_equals_total,
        "scopes": {"selected": sel, "total": total},
        "cross_scope": {
            "selected_delta": str(sel_delta),
            "rest_of_book_delta": str(rest_delta),
            "total_delta": str(total_delta),
            "reconciles": cross_ok,
            "identity": "selected delta + rest-of-book delta = total delta",
            "selected_share_of_total_change_pct": (
                str((sel_delta / total_delta * 100)
                    .quantize(Decimal("0.01"))) if total_delta else None),
            "rest_of_book_reason": (
                SCOPE_EQUALS_BOOK + ": the selected population IS the whole "
                "active book, so there is no rest of book; its ECL delta is "
                "zero by definition and the selected-scope and total-book "
                "bridges are one bridge of the same population."
                if selected_equals_total else
                "The scenario is applied to the selected scope only; every "
                "exposure outside it keeps its booked ECL exactly, so the "
                "rest of the book contributes zero. No portfolio-wide stage, "
                "macro or overlay logic moves it."),
            **({"scope_equivalence": SCOPE_EQUALS_BOOK}
               if selected_equals_total else {}),
            "tolerance": str(tolerance),
        },
        "taxonomy": [{"id": c.id, "label": c.label, "kind": c.kind,
                      "definition": c.definition} for c in TAXONOMY],
    }


def _default_na(stage_policy: str) -> dict[str, str]:
    out = {c.id: SCENARIO_FLOW_REASON for c in TAXONOMY
           if c.kind == FLOW and not c.id.startswith("stage_")}
    out["stage_1_to_2"] = out["stage_2_to_3"] = _stage_na(stage_policy)
    out["calibration_gap"] = ("This method starts from the booked baseline, "
                              "so there is no calibration gap.")
    out["unattributed_method_effect"] = ("Every movement is attributed to a "
                                         "driver.")
    out["collateral"] = out.get("collateral", "No collateral rule in this "
                                              "scenario.")
    for cid in ("pd", "lgd", "ccf_ead", "rating_score", "macro",
                "sector_segment", "management_overlay"):
        out.setdefault(cid, "No rule of this kind in this scenario.")
    return out


def _stage23_share(rows: Sequence[Mapping[str, Any]]) -> str | None:
    ead = sum((_d(r.get("ead_sar_mn")) for r in rows), Decimal(0))
    if not ead:
        return None
    s23 = sum((_d(r.get("ead_sar_mn")) for r in rows
               if int(_d(r.get("stage") or 1)) >= 2), Decimal(0))
    return str((s23 / ead * 100).quantize(Decimal("0.0001")))


def from_computed(computed: Any, *, component_of: Mapping[str, str],
                  selected_label: str, book_label: str,
                  book_stage23_pct: str | None = None,
                  selected_equals_total: bool = False,
                  details: Mapping[str, Mapping[str, Any]] | None = None
                  ) -> dict[str, dict[str, Any]]:
    """Every method that ran -> its dual-scope decomposition (DECOMP24).

    `component_of` maps an economic-view group label (one per scenario
    component) to a taxonomy id. Delta is attributed driver by driver from
    the exact/sampled Shapley bridge; the ML emulator's whole move is one
    `unattributed_method_effect` bar (its SHAP explanation lives elsewhere);
    a User-defined impact is `management_overlay`.
    """
    from backend.cockpit_v4.scenario import run as rn
    from backend.cockpit_v4.scenario import spec as sp

    run = computed.outcome
    stage_policy = computed.spec.stage_policy
    rows = computed.rows
    sel_kpis = {"stage_2_3_ead_share_pct": _stage23_share(rows),
                "exposures": len(rows)}
    book_kpis = {"stage_2_3_ead_share_pct": book_stage23_pct,
                 "exposures": computed.book_rows}
    out: dict[str, dict[str, Any]] = {}
    for method in run.ran:
        o = run.outcomes[method]
        contributions: dict[str, Decimal] = {}
        detail: dict[str, list[dict[str, Any]]] = {}
        na: dict[str, str] = {}
        if method == sp.DELTA and computed.views.economic is not None:
            for c in computed.views.economic.contributions:
                cid = component_of.get(c.label) or _by_fields(c.fields)
                contributions[cid] = contributions.get(cid, Decimal(0)) + \
                    c.change
                detail.setdefault(cid, []).append(
                    {"label": c.label, "value": str(c.change),
                     "fields": list(c.fields),
                     **dict((details or {}).get(c.label, {}))})
        elif method == sp.ML:
            contributions["unattributed_method_effect"] = o.change or \
                Decimal(0)
            na["calibration_gap"] = (
                "The emulator is anchored on the booked baseline (§11.4): "
                "its own baseline gap is removed before the scenario effect "
                "and published in the model card, not hidden here.")
            for cid in ("pd", "lgd", "ccf_ead", "collateral",
                        "rating_score", "macro", "sector_segment"):
                na[cid] = ("The ML emulator predicts the whole move; it does "
                           "not split it by driver. Its SHAP explanation is "
                           "a separate view, not an accounting bridge.")
        elif method == sp.USER_DEFINED:
            contributions["management_overlay"] = o.change or Decimal(0)
            for cid in ("pd", "lgd", "ccf_ead", "collateral",
                        "rating_score", "macro", "sector_segment"):
                na[cid] = ("A User-defined impact is the reader's own "
                           "figure; it is not split by driver.")
        out[method] = dual_scope(
            method=method, method_label=rn.LABELS.get(method, method),
            selected={"opening": o.baseline, "closing": o.scenario,
                      "contributions": contributions, "detail": detail,
                      "measured": [], "not_applicable": na},
            book_opening=computed.book_baseline,
            selected_label=selected_label, book_label=book_label,
            selected_equals_total=selected_equals_total,
            stage_policy=stage_policy, selected_kpis=sel_kpis,
            book_kpis=book_kpis)
    return out


def _by_fields(fields: Sequence[str]) -> str:
    found = {FIELD_COMPONENT.get(f, "sector_segment") for f in fields}
    return found.pop() if len(found) == 1 else "sector_segment"


def check(decomposition: Mapping[str, Any]) -> None:
    """Re-verify both identities from the published strings (DECOMP16-18)."""
    for name, s in decomposition["scopes"].items():
        total = _d(s["opening"]) + sum(
            (_d(c["value"]) for c in s["components"]
             if c["kind"] != TOTAL and c["value"] is not None), Decimal(0))
        if abs(total - _d(s["closing"])) > lg.CURRENCY:
            raise ValueError(f"{name} does not reconcile")
    cross = decomposition["cross_scope"]
    if abs(_d(cross["selected_delta"]) + _d(cross["rest_of_book_delta"])
           - _d(cross["total_delta"])) > lg.CURRENCY:
        raise ValueError("cross-scope does not reconcile")


__all__ = ["BY_ID", "CONTRACT_VERSION", "Component", "FIELD_COMPONENT",
           "MEASURED", "NOT_APPLICABLE", "ORDER", "TAXONOMY", "ZERO",
           "check", "dual_scope", "from_computed", "scope_decomposition"]
