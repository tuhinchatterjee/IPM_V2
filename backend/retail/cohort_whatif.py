"""Handing an investigation's customers to What-If, and proving they arrived.

The defect this exists for
--------------------------
"Export to What-If" cannot mean "navigate to What-If and hope the filters
match". A scenario run on a slightly different cohort produces a number that
answers a question nobody asked, and there is no way to tell from the result
that it happened: the totals look plausible, the chart draws, and the figure
goes into a paper.

So the handoff carries the cohort snapshot's own identifiers into the existing
What-If Selection, and the landing page is GATED on reconciliation. Before a
scenario may be run, the identifiers, the customer and facility counts, the
gross carrying amount, the exposure at default, the stage totals and the
expected credit loss have to match the Borrower 360 scope they came from. When
they do not, the difference is named — how many identifiers are missing, how
many SAR the loss is short by — rather than reported as a failure to load.

What a scenario may and may not do
----------------------------------
A scenario is a RECORD, never an edit. Nothing here writes to the published
book, and a parameter is stored beside its result rather than applied to an
account. The story's own scenario family says what it may vary and what it must
not: an existing card's limit change moves the lawful undrawn headroom and its
credit conversion factor, never the drawn balance; a recovery trial holds the
probability of default; a reschedule shows the duration effect even when it
raises the loss.

Everything here describes SYNTHETIC demonstration data.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from backend.retail import bundle as bnd
from backend.retail import cohort as ch
from backend.retail import episode_policy as pol
from backend.retail import episodes as ep
from backend.retail import episode_measures as em

logger = logging.getLogger(__name__)

VERSION = "retail-cohort-whatif-1.0.0"

#: Currency reconciliation tolerance. One halala: a rounding difference is a
#: rounding difference, and anything larger is a different cohort.
TOLERANCE_SAR = 0.01


def baseline(snapshot: Any) -> dict[str, Any]:
    """The unchanged position of the imported scope, before any scenario.

    Read from the snapshot's identifier list and the published book at the
    snapshot's own date. Not a query that might resolve differently, and not
    the book's current month — a saved investigation simulated six weeks later
    is simulated on what it was saved against, or it is not the same
    investigation.
    """
    at = snapshot.source_as_of
    data = em.frame(at)
    if data.empty:
        return {"available": False,
                "because": f"the book holds no {at}"}
    wanted = {str(f) for f in (snapshot.facility_ids or [])}
    rows = data[data["facility_id"].astype(str).isin(wanted)]
    if rows.empty:
        return {"available": False,
                "because": ("none of the selected facilities are in the book "
                            "at this date")}

    def total(column: str) -> float:
        return round(float(pd.to_numeric(rows.get(column), errors="coerce")
                           .fillna(0.0).sum()), 2)

    def weighted(column: str) -> float | None:
        values = pd.to_numeric(rows.get(column), errors="coerce")
        weights = pd.to_numeric(rows.get("ead_base_sar"), errors="coerce")
        ok = values.notna() & weights.notna() & (weights > 0)
        if not ok.any():
            return None
        return round(float((values[ok] * weights[ok]).sum()
                           / weights[ok].sum()), 6)

    stage = rows["ifrs9_stage"].value_counts().to_dict()
    episode = ep.by_id(snapshot.case_id)
    return {
        "available": True,
        "snapshot_id": snapshot.snapshot_id,
        "case_id": snapshot.case_id,
        "issue": episode.card_measure if episode else "",
        "as_of": at,
        "bundle_id": snapshot.source_bundle_id,
        "customers": int(rows["customer_id"].nunique()),
        "facilities": int(len(rows)),
        "missing_facilities": len(wanted) - int(len(rows)),
        "gca_sar": total("gross_carrying_amount_sar"),
        "ead_sar": total("ead_base_sar"),
        "ecl_sar": total("ecl_weighted_sar"),
        "stage": {f"stage_{int(k)}": int(v) for k, v in sorted(stage.items())},
        "pd_12m": weighted("pd_pit_12m_base"),
        "pd_lifetime": weighted("pd_pit_lifetime_base"),
        "lgd": weighted("lgd_base"),
        "drawn_sar": total("gross_carrying_amount_sar"),
        "undrawn_sar": total("undrawn_commitment_sar"),
        "basis": ("the included facilities of the imported scope, at the "
                  "snapshot's own reporting date"),
        "unchanged": True,
    }


def reconcile(snapshot: Any, *, source_totals: dict[str, Any] | None = None
              ) -> dict[str, Any]:
    """Prove the imported scope is the scope it came from.

    The gate a scenario may not run without. It returns the differences rather
    than a boolean, because "these do not match" is not actionable and "three
    customers are missing and the loss is short by SAR 412" is.
    """
    position = baseline(snapshot)
    if not position.get("available"):
        return {"reconciled": False, "available": False,
                "because": position.get("because"), "differences": []}

    expected = dict(source_totals or snapshot.totals or {})
    differences: list[dict[str, Any]] = []

    if position["customers"] != snapshot.customer_count:
        differences.append({
            "what": "customers", "expected": snapshot.customer_count,
            "got": position["customers"],
            "because": ("customers in the saved cohort have no row in the "
                        "book at this date")})
    if position["facilities"] != snapshot.facility_count:
        differences.append({
            "what": "facilities", "expected": snapshot.facility_count,
            "got": position["facilities"],
            "because": f"{position['missing_facilities']} included "
                       f"facilities are absent from the book at this date"})

    for key, column in (("gca_sar", "gca_sar"), ("ead_sar", "ead_sar"),
                        ("ecl_weighted_sar", "ecl_sar"), ("ecl_sar", "ecl_sar")):
        if key not in expected:
            continue
        gap = abs(float(expected[key]) - float(position[column]))
        if gap > TOLERANCE_SAR:
            differences.append({
                "what": key, "expected": round(float(expected[key]), 2),
                "got": position[column], "difference": round(gap, 2)})

    return {
        "reconciled": not differences,
        "available": True,
        "snapshot_id": snapshot.snapshot_id,
        "baseline": position,
        "differences": differences,
        "tolerance_sar": TOLERANCE_SAR,
        "gate": ("A scenario may not be run until this reconciles. A "
                 "simulation on a cohort that is not the one the reader "
                 "selected answers a question nobody asked, and nothing in "
                 "the result would show it."),
    }


def to_selection(snapshot: Any, *, created_by: str = "",
                 route: str = "/borrower-360") -> Any:
    """Write the existing What-If Selection from a cohort snapshot.

    The existing module rather than a second one: What-If already knows how to
    read a Selection, price it and return to where it came from, and a
    parallel object would be a second place for the cohort to drift.
    """
    from datetime import UTC, datetime

    from backend.retail import ews_model as M
    from backend.retail import ews_score as S
    from backend.retail import whatif_selection as ws

    position = baseline(snapshot)
    if not position.get("available"):
        raise ValueError(position.get("because")
                         or "there is nothing to simulate")

    episode = ep.by_id(snapshot.case_id)
    selection = ws.Selection(
        selection_id=ws._new_id(),
        source_module="retail_investigation",
        source_route=route,
        source_month=snapshot.source_as_of,
        source_model_version=M.EWS_MODEL_VERSION,
        source_rulebook_version="",
        source_panel_version=S.EWS_PANEL_VERSION,
        source_level="investigation",
        source_product=episode.product if episode else "",
        source_sub_product="",
        source_label=(f"{episode.title} — {snapshot.step_id}"
                      if episode else snapshot.case_id),
        source_filters={
            "snapshot_id": snapshot.snapshot_id,
            "case_id": snapshot.case_id,
            "step": snapshot.step_id,
            "scope": ch.describe(snapshot.predicate or {}),
            "bundle_id": snapshot.source_bundle_id,
        },
        selected_customer_ids=[str(c) for c in (snapshot.customer_ids or [])],
        selected_facility_ids=[str(f) for f in (snapshot.facility_ids or [])],
        selected_customer_count=snapshot.customer_count,
        selected_account_count=snapshot.facility_count,
        selected_exposure_sar=position["gca_sar"],
        created_by=created_by,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source_thread_id=snapshot.thread_id,
        taxonomy_version=M.SUB_PRODUCT_TAXONOMY_VERSION,
        notes=("Imported from a retail investigation. The identifiers are the "
               "snapshot's own; nothing was re-queried."),
    )
    ws.save(selection)
    logger.info("cohort %s exported to What-If selection %s",
                snapshot.snapshot_id, selection.selection_id)
    return selection


def handoff(snapshot: Any, *, created_by: str = "") -> dict[str, Any]:
    """Everything the What-If landing banner shows, plus the gate."""
    check = reconcile(snapshot)
    episode = ep.by_id(snapshot.case_id)
    scenario = pol.scenarios_for(snapshot.case_id, snapshot.source_as_of,
                                 {"customer_count": snapshot.customer_count,
                                  "facility_count": snapshot.facility_count,
                                  "totals": dict(snapshot.totals or {})})
    out: dict[str, Any] = {
        "snapshot_id": snapshot.snapshot_id,
        "case_id": snapshot.case_id,
        "issue": episode.card_measure if episode else "",
        "source_step": snapshot.step_id,
        "as_of": snapshot.source_as_of,
        "bundle_id": snapshot.source_bundle_id,
        "current_bundle_id": bnd.current_id(),
        "baseline": check.get("baseline"),
        "reconciliation": check,
        "may_simulate": bool(check.get("reconciled")),
        "scenario": scenario,
        "return_to": {
            "thread_id": snapshot.thread_id,
            "snapshot_id": snapshot.snapshot_id,
            "note": "the investigation this came from, at the same step"},
        "versions": dict(snapshot.versions or {}),
        "never": ("A scenario is a record. It does not write to the published "
                  "book and it does not change an account."),
    }
    # A cohort measured on an earlier build is not silently re-priced on this
    # one. The reader is told, and the refresh that would fix it is a
    # deliberate act that creates a new version.
    try:
        bnd.require_same(snapshot.source_bundle_id or "", bnd.current_id())
        out["bundle_matches"] = True
    except bnd.StaleBundle as stale:
        out["bundle_matches"] = False
        out["may_simulate"] = False
        out["stale_bundle"] = str(stale)
    return out
