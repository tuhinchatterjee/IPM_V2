"""The cohort an Early Warning screen hands to What-If, and what it means.

Exporting a card to What-If cannot mean "navigate to What-If and hope the
filters match". The customers a reader was looking at — those exact customers,
at that exact month, under that exact set of filters — have to arrive.

So an export writes a SELECTION SET: an immutable record of who was selected,
where from, and on what basis. It holds the customer and facility identifiers
themselves, not a query that might resolve differently later, because the
whole point is that the scenario is run on the cohort the reader saw.

Two rules it is built around:

**The canonical What-If book is never touched.** A selection is membership,
joined to the What-If domain by facility and month. Marking rows in the book
would make one reader's export visible to every other reader and would make
the book's own figures depend on who had been browsing.

**The record says where it came from.** Source module, route, month, model and
rulebook version, product, classification, sub-product, every filter, and the
counts and exposure at the moment of export. A scenario run six weeks later can
still be traced back to the card it started on, and if the panel has been
rebuilt since, the difference is visible rather than silent.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from backend.retail import ews as ews_rules
from backend.retail import ews_model as M
from backend.retail import ews_score as S
from backend.retail import scorecards, taxonomy as tax

SOURCE_MODULE = "early_warning_score"

#: Where else a selection can come from. A cohort chosen on the standalone
#: What-If page, or by a guided card, is the same KIND of object as one
#: exported from Early Warning — an immutable set of facility-month keys with
#: the filters that produced it — and it goes through the same engine, the
#: same result shape and the same workbook. Only the provenance differs.
#:
#: Before this the standalone page ran a second implementation over a filter
#: dictionary, with no membership record, no materiality against its parents
#: and no workbook. Two implementations of one idea is how they drift.
SOURCE_STANDALONE = "what_if_standalone"
SOURCE_GUIDED = "what_if_guided_card"
SOURCE_MODULES = (SOURCE_MODULE, SOURCE_STANDALONE, SOURCE_GUIDED)

#: Where selections live. A directory of JSON documents rather than a table:
#: durable, inspectable, and it adds no migration to a schema this work has no
#: other reason to touch.
def _root() -> Path:
    base = Path(os.environ.get("RETAIL_VAR_DIR") or "var/retail")
    path = base / "whatif_selections"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class Selection:
    """One exported cohort, exactly as it was selected."""

    selection_id: str
    source_module: str
    source_route: str
    source_month: str
    source_model_version: str
    source_rulebook_version: str
    source_panel_version: str
    source_level: str
    source_product: str = ""
    source_classification: str = ""
    source_sub_product: str = ""
    source_customer_id: str = ""
    source_label: str = ""
    source_filters: dict[str, Any] = field(default_factory=dict)
    selected_customer_ids: list[str] = field(default_factory=list)
    selected_facility_ids: list[str] = field(default_factory=list)
    selected_customer_count: int = 0
    selected_account_count: int = 0
    selected_exposure_sar: float = 0.0
    ews_score: float = 0.0
    ews_severity: str = ""
    ews_score_range: list[float] = field(default_factory=list)
    severity_filter: str = ""
    current_bad_filter: str = ""
    forward_risk_filter: str = ""
    reason_filter: str = ""
    layer_filter: str = ""
    high_or_critical: int = 0
    current_bad: int = 0
    forward_risk: int = 0
    materiality: dict[str, Any] = field(default_factory=dict)
    created_by: str = ""
    created_at: str = ""
    source_thread_id: str = ""
    taxonomy_version: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _new_id() -> str:
    return "EWSEL-" + uuid.uuid4().hex[:12].upper()


def _counts(rows: Any) -> dict[str, Any]:
    from backend.retail import ews_views as V

    return V._counts(rows) if len(rows) else {}


def _materiality(rows: Any, month: str, product: str,
                 classification: str) -> dict[str, Any]:
    """What share of each parent the selection is, §32."""
    from backend.retail import ews_views as V

    whole = S.read(month)
    parents: dict[str, Any] = {"retail": whole}
    if product:
        parents["product"] = V._where(whole, product=product)
        if classification:
            parents["classification"] = V._where(
                whole, product=product, classification=classification)
    return V._materiality(rows, parents)


def build_rows(month: str, *, product: str = "", classification: str = "",
               sub_product: str = "", customer_id: str = "",
               cohort: str = "", severity: str = "", reason: str = "",
               layer: str = "", score_min: float | None = None,
               score_max: float | None = None,
               dpd_bucket: str = "", stage: str = "",
               behavioural_band: str = "") -> Any:
    """The exact rows a card or a filtered list was showing.

    The same filters the customer list applies, applied the same way, so the
    export cannot select a different population from the one on screen.
    """
    import pandas as pd

    from backend.retail import ews_views as V

    frame = V._where(S.read(month), product=product,
                     classification=classification, sub_product=sub_product)
    if customer_id:
        frame = frame[frame["customer_id"].astype(str) == str(customer_id)]
    if cohort and cohort not in ("all", "everyone"):
        if cohort == "current_bad":
            frame = frame[frame["current_bad_flag"].fillna(False)]
        elif cohort == "forward_risk":
            frame = frame[frame["forward_risk_flag"].fillna(False)]
        elif cohort in ("critical", "high"):
            frame = frame[frame["ews_severity"].astype(str) == cohort.upper()]
        elif cohort == "warned":
            frame = frame[frame["ews_alert_flag"].fillna(False)]
    if severity:
        wanted = [one.strip().upper() for one in str(severity).split(",") if one]
        frame = frame[frame["ews_severity"].astype(str).isin(wanted)]
    if reason:
        codes = {f"top_reason_code_{n}" for n in (1, 2, 3)}
        keep = None
        for column in codes:
            if column in frame.columns:
                hit = frame[column].astype(str) == str(reason)
                keep = hit if keep is None else (keep | hit)
        if keep is not None:
            frame = frame[keep]
    if layer:
        column = f"layer_{layer}_score"
        holder = M.layer(layer)
        if holder is not None and holder.score_column in frame.columns:
            frame = frame[frame[holder.score_column] > 0]
    if score_min is not None:
        frame = frame[pd.to_numeric(frame["ews_score"], errors="coerce")
                      >= float(score_min)]
    if score_max is not None:
        frame = frame[pd.to_numeric(frame["ews_score"], errors="coerce")
                      <= float(score_max)]
    if dpd_bucket:
        frame = frame[frame["dpd_bucket"].astype(str) == str(dpd_bucket)]
    if stage not in ("", None):
        frame = frame[pd.to_numeric(frame["ifrs9_stage"], errors="coerce")
                      == float(stage)]
    if behavioural_band:
        # The Behavioural Score Movement card selects by BAND, which the panel
        # carries as a letter. Without this the card could describe a cohort
        # it could not then select.
        wanted = [one.strip().upper()
                  for one in str(behavioural_band).split(",") if one.strip()]
        for column in ("behavioural_score_band", "beh_score_band_value"):
            if column in frame.columns:
                frame = frame[frame[column].astype(str).str.upper().isin(wanted)]
                break
    return frame


def create(*, month: str = "", level: str = "product", product: str = "",
           classification: str = "", sub_product: str = "",
           customer_id: str = "", cohort: str = "", severity: str = "",
           reason: str = "", layer: str = "", score_min: float | None = None,
           score_max: float | None = None, dpd_bucket: str = "",
           stage: str = "", route: str = "", created_by: str = "",
           label: str = "", thread_id: str = "",
           source_module: str = "", behavioural_band: str = "") -> Selection:
    """Write the selection set for what a reader has on screen."""
    at = month or (S.panel_months() or [""])[-1]
    rows = build_rows(
        at, product=product, classification=classification,
        sub_product=sub_product, customer_id=customer_id, cohort=cohort,
        severity=severity, reason=reason, layer=layer, score_min=score_min,
        score_max=score_max, dpd_bucket=dpd_bucket, stage=stage,
        behavioural_band=behavioural_band)
    if not len(rows):
        raise ValueError(
            "That selection matches no facility at this month, so there is "
            "nothing to stress. This is an empty selection, not a zero one.")

    head = _counts(rows)
    filters = {k: v for k, v in {
        "product": product, "classification": classification,
        "sub_product": sub_product, "customer_id": customer_id,
        "cohort": cohort, "severity": severity, "reason": reason,
        "layer": layer, "score_min": score_min, "score_max": score_max,
        "dpd_bucket": dpd_bucket, "stage": stage,
        "behavioural_band": behavioural_band,
    }.items() if v not in ("", None)}

    selection = Selection(
        selection_id=_new_id(),
        source_module=source_module or SOURCE_MODULE,
        source_route=route or "/early-warning",
        source_month=at,
        source_model_version=M.EWS_MODEL_VERSION,
        source_rulebook_version=str(rows["rulebook_version"].iloc[0])
                                if "rulebook_version" in rows else "",
        source_panel_version=S.EWS_PANEL_VERSION,
        source_level=level,
        source_product=str(product).upper(),
        source_classification=str(classification).upper(),
        source_sub_product=str(sub_product).upper(),
        source_customer_id=str(customer_id),
        source_label=label or _label(product, classification, sub_product,
                                     customer_id, rows),
        source_filters=filters,
        selected_customer_ids=sorted(rows["customer_id"].astype(str).unique()),
        selected_facility_ids=sorted(rows["facility_id"].astype(str).unique()),
        selected_customer_count=int(rows["customer_id"].nunique()),
        selected_account_count=int(rows["facility_id"].nunique()),
        selected_exposure_sar=round(
            float(rows["gross_carrying_amount_sar"].sum()), 2),
        ews_score=float(head.get("ews_score") or 0.0),
        ews_severity=str(head.get("severity_band") or ""),
        ews_score_range=[round(float(rows["ews_score"].min()), 3),
                         round(float(rows["ews_score"].max()), 3)],
        severity_filter=severity,
        current_bad_filter="yes" if cohort == "current_bad" else "",
        forward_risk_filter="yes" if cohort == "forward_risk" else "",
        reason_filter=reason,
        layer_filter=layer,
        high_or_critical=int(head.get("high_or_critical") or 0),
        current_bad=int(head.get("current_bad") or 0),
        forward_risk=int(head.get("forward_risk") or 0),
        materiality=_materiality(rows, at, str(product).upper(),
                                 str(classification).upper()),
        created_by=created_by,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        source_thread_id=thread_id,
        taxonomy_version=M.SUB_PRODUCT_TAXONOMY_VERSION,
    )
    save(selection)
    return selection


def _label(product: str, classification: str, sub_product: str,
           customer_id: str, rows: Any) -> str:
    if customer_id:
        name = (str(rows["customer_name"].iloc[0])
                if "customer_name" in rows else customer_id)
        return f"{name} ({customer_id})"
    parts = []
    if product:
        parts.append(str(rows["product_label"].iloc[0])
                     if "product_label" in rows else product)
    if classification:
        parts.append(M.CLASSIFICATION_LABELS.get(
            str(classification).upper(), classification))
    if sub_product:
        parts.append(M.SUB_PRODUCT_LABELS.get(
            str(sub_product).upper(), sub_product))
    return " — ".join(parts) if parts else "Total Retail"


def save(selection: Selection) -> Path:
    path = _root() / f"{selection.selection_id}.json"
    path.write_text(json.dumps(selection.to_dict(), indent=1, default=str))
    return path


def get(selection_id: str) -> Selection | None:
    path = _root() / f"{str(selection_id).upper()}.json"
    if not path.exists():
        return None
    return Selection(**json.loads(path.read_text()))


def listing(limit: int = 25) -> list[dict[str, Any]]:
    """The most recent selections, newest first, without their membership."""
    out = []
    for path in sorted(_root().glob("EWSEL-*.json"),
                       key=lambda p: p.stat().st_mtime, reverse=True)[:limit]:
        held = json.loads(path.read_text())
        held.pop("selected_customer_ids", None)
        held.pop("selected_facility_ids", None)
        out.append(held)
    return out


# ------------------------------------------------------------- the baseline

# Cuts that have a direction read them in it. Days past due runs from
# performing to written off; a score band from the best grade to the worst;
# Early Warning severity from quietest to loudest. A reader scanning these
# tables is looking for where the book turns, and a table sorted by size
# hides the turn. Cuts with no natural direction — sub-product, salaried or
# not — stay ranked by exposure, because there the largest is the point.
_ORDER: dict[str, tuple[str, ...]] = {
    "dpd_bucket": tax.DPD_BUCKETS,
    "behavioural_score_band": tuple(reversed(scorecards.SCORE_BAND_LABELS)),
    "application_score_band": tuple(reversed(scorecards.SCORE_BAND_LABELS)),
    "ifrs9_stage": ("1", "2", "3"),
    "ews_severity": ews_rules.SEVERITY_ORDER,
}

# What a group of records with nothing in the column should be called. Left
# alone, pandas hands back the float nan and it reaches the screen as "nan".
_UNKNOWN = "Not available"


def _cut(frame: Any, column: str, label: str,
         labels: dict[str, str] | None = None) -> dict[str, Any]:
    """One distribution cut of the baseline, §12."""
    import pandas as pd

    if column not in frame.columns:
        return {"key": column, "label": label, "available": False,
                "because": "the What-If domain does not carry this column"}
    keys = frame[column].astype("string").fillna(_UNKNOWN).replace(
        {"nan": _UNKNOWN, "None": _UNKNOWN, "<NA>": _UNKNOWN, "": _UNKNOWN})
    rows = []
    for value, block in frame.groupby(keys, dropna=False):
        exposure = float(block["gross_carrying_amount_sar"].sum())
        rows.append({
            "value": str(value),
            "label": (labels or {}).get(str(value), str(value)),
            "customers": int(block["customer_id"].nunique()),
            "accounts": int(block["facility_id"].nunique()),
            "exposure_sar": round(exposure, 2),
            "pd_pit_12m": round(float(
                (block["pd_pit_12m_base"] * block["gross_carrying_amount_sar"]).sum()
                / exposure), 6) if exposure else None,
            "lgd": round(float(
                (block["lgd_base"] * block["gross_carrying_amount_sar"]).sum()
                / exposure), 6) if exposure else None,
            "ead_sar": round(float(block["ead_base_sar"].sum()), 2),
            "ecl_weighted_sar": round(float(block["ecl_weighted_sar"].sum()), 2),
        })
    order = _ORDER.get(column)
    if order:
        rank = {str(one): i for i, one in enumerate(order)}
        # Anything the taxonomy does not name sorts after what it does, so an
        # unexpected value is visible rather than silently placed mid-table.
        rows.sort(key=lambda one: (rank.get(one["value"], len(rank)),
                                   one["value"]))
    else:
        rows.sort(key=lambda one: -one["exposure_sar"])
    return {"key": column, "label": label, "available": True,
            "ordered_by": "the taxonomy" if order else "exposure",
            "rows": rows}


def whatif_rows(selection: Selection) -> Any:
    """The What-If records for exactly this cohort.

    Joined by facility and month. The canonical dataset is read, never
    written: membership lives in the selection, not in the book.
    """
    # The canonical book, which is what the What-If engine itself runs on and
    # what the What-If domain is a view of. Reading the same month the same
    # way is what makes the selection map exactly: same facilities, same
    # exposure, same IFRS 9 position, no join to go wrong.
    frame = S._read_book(selection.source_month)
    return frame[frame["facility_id"].astype(str).isin(
        set(selection.selected_facility_ids))]


def baseline(selection: Selection) -> dict[str, Any]:
    """The full IFRS 9 baseline of the selected cohort before any scenario."""
    import pandas as pd

    rows = whatif_rows(selection)
    if not len(rows):
        return {"available": False,
                "because": ("none of the selected facilities are in the "
                            "What-If domain at this month")}

    exposure = float(rows["gross_carrying_amount_sar"].sum())
    scored = S.read(selection.source_month)
    scored = scored[scored["facility_id"].astype(str).isin(
        set(selection.selected_facility_ids))]

    def weighted(column: str) -> float | None:
        if column not in rows.columns or not exposure:
            return None
        return round(float(
            (pd.to_numeric(rows[column], errors="coerce").fillna(0.0)
             * rows["gross_carrying_amount_sar"]).sum() / exposure), 6)

    def total(column: str) -> float:
        return round(float(pd.to_numeric(rows.get(column), errors="coerce")
                           .fillna(0.0).sum()), 2) if column in rows else 0.0

    # The EWS cuts come from the scoring domain, joined on facility.
    joined = rows.merge(
        scored[["facility_id", "ews_severity", "current_bad_flag",
                "forward_risk_flag", "sub_product", "classification"]]
        .assign(facility_id=scored["facility_id"].astype(str)),
        left_on=rows["facility_id"].astype(str), right_on="facility_id",
        how="left", suffixes=("", "_ews"))
    joined["cohort_split"] = joined["current_bad_flag"].fillna(False).map(
        {True: "Already bad", False: "Still paying"})

    return {
        "available": True,
        "selection_id": selection.selection_id,
        "month": selection.source_month,
        "population": {
            "customers": int(rows["customer_id"].nunique()),
            "accounts": int(rows["facility_id"].nunique()),
            "exposure_sar": round(exposure, 2),
            "pct_of_product_exposure": (selection.materiality.get("product") or {})
                                       .get("exposure_pct"),
            "pct_of_retail_exposure": (selection.materiality.get("retail") or {})
                                      .get("exposure_pct"),
            "pct_of_product_accounts": (selection.materiality.get("product") or {})
                                       .get("accounts_pct"),
            "pct_of_retail_accounts": (selection.materiality.get("retail") or {})
                                      .get("accounts_pct"),
        },
        "ifrs9": {
            "pd_ttc_12m": weighted("pd_ttc_12m"),
            "pd_pit_12m": weighted("pd_pit_12m_base"),
            "pd_pit_lifetime": weighted("pd_pit_lifetime_base"),
            "lgd": weighted("lgd_base"),
            "ccf": weighted("ccf_base"),
            "ead_sar": total("ead_base_sar"),
            "collateral_value_sar": total("collateral_value_current_sar"),
            "ecl_base_sar": total("ecl_base_sar"),
            "ecl_upturn_sar": total("ecl_upturn_sar"),
            "ecl_downturn_sar": total("ecl_downturn_sar"),
            "ecl_weighted_sar": total("ecl_weighted_sar"),
            "ecl_coverage_pct": round(total("ecl_weighted_sar") / exposure * 100, 4)
                                if exposure else None,
            "sicr_flagged": int(rows["sicr_flag"].fillna(False).sum())
                            if "sicr_flag" in rows else None,
            "scenario_weights": {
                "base": weighted("scenario_weight_base"),
                "upturn": weighted("scenario_weight_upturn"),
                "downturn": weighted("scenario_weight_downturn"),
            },
        },
        "cuts": [
            _cut(rows, "dpd_bucket", "Days past due"),
            _cut(rows, "behavioural_score_band", "Behavioural score band"),
            _cut(rows, "application_score_band", "Application score band"),
            _cut(rows, "ifrs9_stage", "IFRS 9 stage"),
            _cut(joined, "sub_product", "Sub-product",
                 dict(M.SUB_PRODUCT_LABELS)),
            _cut(joined, "classification", "Classification",
                 dict(M.CLASSIFICATION_LABELS)),
            _cut(joined, "cohort_split", "Already bad or still paying"),
            _cut(joined, "ews_severity", "Early Warning severity"),
        ],
        "disclaimer": M.DISCLAIMER,
    }


def prompts(selection: Selection) -> list[str]:
    """Scenarios worth running on THIS cohort, §13."""
    out = [
        "Increase PIT 12-month PD by 20%.",
        "Increase LGD by 5 percentage points.",
        "Move 15% of Stage 1 exposure to Stage 2.",
    ]
    if selection.source_product == "CREDIT_CARD":
        # 30-59, which is the bucket the taxonomy has. Offered as "30-60" the
        # parser found no such bucket and refused a prompt the screen had just
        # invited the reader to press.
        out.insert(0, "Move 20% of 30-59 DPD exposure to 90+.")
        out.append("Increase CCF by 10 percentage points on undrawn card lines.")
        out.append("Move card utilisation up by 10 percentage points.")
    if selection.source_product in ("HOME_LOAN", "AUTO_LOAN"):
        out.append("Reduce collateral value by 10% where secured.")
    if selection.forward_risk:
        out.append("Stress only the forward-risk customers in this selection.")
    if selection.current_bad:
        out.append("Stress only the customers who are already bad.")
    if not selection.source_classification:
        out.append("Compare Salaried against Non-Salaried inside this selection.")
    out.append("Reduce verified income by 10%.")
    return out[:10]


__all__ = ["SOURCE_MODULE", "Selection", "baseline", "build_rows", "create",
           "get", "listing", "prompts", "save", "whatif_rows"]
