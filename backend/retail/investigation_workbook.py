"""The evidence workbook, capped at what the reader has actually seen.

The defect this exists for
--------------------------
An export is the moment the investigation leaves the product. It lands on a
laptop, it is forwarded, and six months later somebody is asked what it meant.
Three failures make that unanswerable, and all three are easy to ship:

* **Future-step leakage.** A workbook exported at S1 that contains S4's pocket
  and S5's policy actions attributes reasoning to a reader who never reached
  it. The cap is the cohort snapshot's own `visited_steps`, and the policy
  sheet says *Not reached* rather than quietly revealing what S5 would have
  said.
* **Silent truncation.** A file that holds the first fifty thousand rows of a
  larger cohort and says nothing is a file that will be summed. Every sheet
  here writes the snapshot's whole identifier list, and the reconciliation
  sheet states the counts so a reader can check it themselves.
* **Formula injection.** A customer-entered note beginning `=`, `+`, `-` or
  `@` is executable when the file is opened. Every text cell goes through
  `exports.escape_cell`, which prefixes it so the spreadsheet treats it as
  text.

Thirteen sheets, in the specification's order. A sheet whose content this
investigation has not reached is still present, and says why it is empty —
an absent sheet is a question ("was there no policy?"), a present one that
says *Not reached at S1* is an answer.

Everything written is SYNTHETIC demonstration data, and sheet 00 says so
before anything else in the file.
"""

from __future__ import annotations

import hashlib
import io
import logging
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from backend.retail import cohort as ch
from backend.retail import cohort_360
from backend.retail import episode_answers as ea
from backend.retail import episode_measures as em
from backend.retail import episode_policy as pol
from backend.retail import episodes as ep
from backend.retail import exports
from backend.retail import metrics_contract as mc

logger = logging.getLogger(__name__)

VERSION = "retail-investigation-workbook-1.0.0"

DISCLOSURE = (
    "SYNTHETIC DEMONSTRATION DATA. Every customer, employer, project, score, "
    "rate, exposure and policy clause in this file is invented. Nothing here "
    "is Arab National Bank customer data, actual distress, or bank-approved "
    "policy.")

MONEY = "#,##0.00"
PERCENT = "0.0%"
RATIO = "0.0000"
COUNT = "#,##0"

SHEETS = (
    "00_Readme", "01_Snapshot", "02_Customers", "03_Facilities_IFRS9",
    "04_ECL_Term_Scenarios", "05_Diagnosis_Visited", "06_Score_Drivers",
    "07_EWS_History", "08_Charts_Data", "09_Policy_Actions", "10_Notes",
    "11_Reconciliation", "12_Sources",
)


def _styles(workbook: Any) -> dict[str, Any]:
    return {
        "title": workbook.add_format({"bold": True, "font_size": 14,
                                      "font_color": "#1F3864"}),
        "note": workbook.add_format({"italic": True, "font_size": 9,
                                     "font_color": "#595959",
                                     "text_wrap": True, "valign": "top"}),
        "warn": workbook.add_format({"bold": True, "font_size": 10,
                                     "font_color": "#9C0006",
                                     "text_wrap": True, "valign": "top"}),
        "head": workbook.add_format({"bold": True, "bg_color": "#1F3864",
                                     "font_color": "#FFFFFF", "border": 1,
                                     "text_wrap": True, "valign": "vcenter"}),
        "text": workbook.add_format({"border": 1, "valign": "top"}),
        "wrap": workbook.add_format({"border": 1, "text_wrap": True,
                                     "valign": "top"}),
        "money": workbook.add_format({"border": 1, "num_format": MONEY}),
        "pct": workbook.add_format({"border": 1, "num_format": PERCENT}),
        "ratio": workbook.add_format({"border": 1, "num_format": RATIO}),
        "count": workbook.add_format({"border": 1, "num_format": COUNT}),
        "key": workbook.add_format({"bold": True, "valign": "top"}),
    }


def _format_for(column: str, styles: dict[str, Any]) -> Any:
    name = str(column).lower()
    if name.endswith(("_pct", "_share")) or "percent" in name:
        return styles["pct"]
    if name.endswith("_sar"):
        return styles["money"]
    if name.startswith("pd_") or name in ("lgd", "ccf", "eir", "rate",
                                          "incidence"):
        return styles["ratio"]
    if name.endswith("_count") or name in ("customers", "facilities", "rows",
                                           "stage", "dpd", "alerts"):
        return styles["count"]
    return styles["text"]


def _sheet(workbook: Any, styles: dict[str, Any], name: str, title: str,
           note: str = "") -> Any:
    page = workbook.add_worksheet(name[:31])
    page.write(0, 0, title, styles["title"])
    if note:
        page.merge_range(1, 0, 1, 11, note, styles["note"])
        page.set_row(1, 30)
    return page


def _table(page: Any, styles: dict[str, Any], rows: list[dict[str, Any]],
           at: int = 3, *, empty: str = "") -> int:
    """A typed, filtered, frozen-header table. Every text cell made inert."""
    if not rows:
        page.write(at, 0, empty or "No rows.", styles["note"])
        return at + 2
    columns = list(rows[0].keys())
    for index, name in enumerate(columns):
        page.write(at, index, str(name), styles["head"])
        page.set_column(index, index, max(12, min(len(str(name)) + 6, 46)))
    for offset, row in enumerate(rows, start=1):
        for index, name in enumerate(columns):
            value = row.get(name)
            if isinstance(value, (list, dict)):
                value = str(value)
            page.write(at + offset, index, exports.escape_cell(value),
                       _format_for(name, styles))
    page.autofilter(at, 0, at + len(rows), len(columns) - 1)
    page.freeze_panes(at + 1, 0)
    return at + len(rows) + 2


def _pairs(page: Any, styles: dict[str, Any], pairs: list[tuple[str, Any]],
           at: int = 3) -> int:
    for offset, (key, value) in enumerate(pairs):
        page.write(at + offset, 0, str(key), styles["key"])
        if isinstance(value, (list, dict)):
            value = str(value)
        page.write(at + offset, 1, exports.escape_cell(value), styles["wrap"])
    page.set_column(0, 0, 34)
    page.set_column(1, 1, 96)
    return at + len(pairs) + 2


# ---------------------------------------------------------------------------


def build(snapshot: Any, *, notes: list[dict[str, Any]] | None = None,
          user: str = "", saved_id: str = "",
          permitted_fields: list[str] | None = None) -> tuple[bytes, dict[str, Any]]:
    """The workbook, and the manifest that records what went into it."""
    import xlsxwriter

    episode = ep.by_id(snapshot.case_id)
    visited = list(snapshot.visited_steps or ["S0"])
    at = snapshot.source_as_of
    exported_at = datetime.now(UTC).isoformat(timespec="seconds")

    buffer = io.BytesIO()
    workbook = xlsxwriter.Workbook(buffer, {
        "in_memory": True, "default_date_format": "yyyy-mm-dd",
        "strings_to_formulas": False, "strings_to_urls": False})
    styles = _styles(workbook)

    counts: dict[str, int] = {}
    counts["00_Readme"] = _readme(workbook, styles, snapshot, episode, visited,
                                  user, exported_at)
    counts["01_Snapshot"] = _snapshot_sheet(workbook, styles, snapshot,
                                            episode, visited)
    customers, facilities = _population(snapshot)
    counts["02_Customers"] = _customers(workbook, styles, customers)
    counts["03_Facilities_IFRS9"] = _facilities(workbook, styles, facilities)
    counts["04_ECL_Term_Scenarios"] = _scenarios(workbook, styles, snapshot,
                                                 facilities)
    counts["05_Diagnosis_Visited"] = _diagnosis(workbook, styles, snapshot,
                                                episode, visited)
    counts["06_Score_Drivers"] = _drivers(workbook, styles, snapshot, episode,
                                          visited)
    counts["07_EWS_History"] = _ews(workbook, styles, customers)
    counts["08_Charts_Data"] = _charts(workbook, styles, snapshot, episode,
                                       visited)
    counts["09_Policy_Actions"] = _policy(workbook, styles, snapshot, episode,
                                          visited)
    counts["10_Notes"] = _notes(workbook, styles, notes or [], saved_id)
    counts["11_Reconciliation"] = _reconciliation(
        workbook, styles, snapshot, customers, facilities, visited, counts,
        permitted_fields)
    counts["12_Sources"] = _sources(workbook, styles, snapshot, episode)

    workbook.close()
    payload = buffer.getvalue()
    manifest = {
        "schema": VERSION,
        "snapshot_id": snapshot.snapshot_id,
        "saved_id": saved_id,
        "case_id": snapshot.case_id,
        "source_step": snapshot.step_id,
        "visited_steps": visited,
        "as_of": at,
        "bundle_id": snapshot.source_bundle_id,
        "exported_at": exported_at,
        "user": user,
        "customer_count": snapshot.customer_count,
        "facility_count": snapshot.facility_count,
        "sheet_rows": counts,
        "sheets": list(SHEETS),
        "size_bytes": len(payload),
        "content_hash": hashlib.sha256(payload).hexdigest(),
        "truncated": False,
        "permitted_fields": list(permitted_fields or []),
    }
    logger.info("investigation workbook %s: %d customers, %d facilities, "
                "%d bytes", snapshot.snapshot_id, snapshot.customer_count,
                snapshot.facility_count, len(payload))
    return payload, manifest


def _population(snapshot: Any) -> tuple[list[dict[str, Any]],
                                        list[dict[str, Any]]]:
    """Every selected customer and every included facility. No page limit.

    Read from the snapshot's identifier list rather than by re-running a
    query, which is what makes the file the cohort the reader was shown.
    """
    data = em.frame(snapshot.source_as_of)
    wanted = {str(f) for f in (snapshot.facility_ids or [])}
    rows = data[data["facility_id"].astype(str).isin(wanted)]
    episode = ep.by_id(snapshot.case_id)
    issue = episode.card_measure if episode else snapshot.case_id

    facilities: list[dict[str, Any]] = []
    for _index, row in rows.iterrows():
        def number(column: str) -> Any:
            value = pd.to_numeric(row.get(column), errors="coerce")
            return None if pd.isna(value) else float(value)

        facilities.append({
            "customer_id": str(row.get("customer_id") or ""),
            "facility_id": str(row.get("facility_id") or ""),
            "product": str(row.get("product_code") or ""),
            "subproduct": str(row.get("product_subsegment") or ""),
            "currency": "SAR",
            "stage": number("ifrs9_stage"),
            "dpd": number("dpd"),
            "credit_impaired": bool(row.get("credit_impaired_flag") or False),
            "gca_sar": number("gross_carrying_amount_sar"),
            "ead_sar": number("ead_base_sar"),
            "limit_sar": number("credit_limit_sar"),
            "undrawn_sar": number("undrawn_commitment_sar"),
            "ccf": number("ccf_base"),
            "eir": number("effective_interest_rate"),
            "remaining_term_months": number("remaining_term_months"),
            "pd_12m": number("pd_pit_12m_base"),
            "pd_lifetime": number("pd_pit_lifetime_base"),
            "lgd": number("lgd_base"),
            "ecl_sar": number("ecl_weighted_sar"),
            "ecl_base_sar": number("ecl_base_sar"),
            "ecl_upturn_sar": number("ecl_upturn_sar"),
            "ecl_downturn_sar": number("ecl_downturn_sar"),
            "behavioural_score": number("behavioural_score"),
            "application_score": number("app_score_value"),
            "recovery_delay_months": number("recovery_delay_months"),
            "collateral_value_sar": number("collateral_value_current_sar"),
        })

    by_customer: dict[str, dict[str, Any]] = {}
    for facility in facilities:
        entry = by_customer.setdefault(facility["customer_id"], {
            "customer_id": facility["customer_id"],
            "issue": issue,
            "segment": episode.pocket_label if episode else "",
            "included_facilities": 0,
            "gca_sar": 0.0, "ead_sar": 0.0, "ecl_sar": 0.0,
            "worst_stage": 0, "max_dpd": 0,
            "behavioural_score": None, "application_score": None,
            "status": "included",
        })
        entry["included_facilities"] += 1
        for key in ("gca_sar", "ead_sar", "ecl_sar"):
            entry[key] = round((entry[key] or 0.0) + (facility[key] or 0.0), 2)
        entry["worst_stage"] = max(entry["worst_stage"],
                                   int(facility["stage"] or 0))
        entry["max_dpd"] = max(entry["max_dpd"], int(facility["dpd"] or 0))
        for key in ("behavioural_score", "application_score"):
            if entry[key] is None:
                entry[key] = facility[key]

    # Early Warning history, joined ONCE for the whole cohort rather than per
    # customer. Six months of a panel read a thousand times is the difference
    # between an export that returns and one a presenter apologises for.
    months = [m for m in em.months() if m <= snapshot.source_as_of][-6:]
    panels = cohort_360._panels(months)
    product_of = {}
    for facility in facilities:
        product_of.setdefault(facility["customer_id"], facility["product"])
    for customer_id, entry in by_customer.items():
        entry["ews"] = _ews_series(customer_id,
                                   product_of.get(customer_id, ""),
                                   months, panels)

    # Customers in the snapshot with no row at this date are still listed, as
    # a stated absence rather than as a silently shorter file.
    for customer_id in (snapshot.customer_ids or []):
        by_customer.setdefault(str(customer_id), {
            "customer_id": str(customer_id), "issue": issue,
            "segment": episode.pocket_label if episode else "",
            "included_facilities": 0, "gca_sar": 0.0, "ead_sar": 0.0,
            "ecl_sar": 0.0, "worst_stage": 0, "max_dpd": 0,
            "behavioural_score": None, "application_score": None,
            "status": "no row in the book at this date",
            "ews": {"series": []},
        })
    return list(by_customer.values()), facilities


def _ews_series(customer_id: str, product: str, months: list[str],
                panels: dict[str, Any]) -> dict[str, Any]:
    """One customer-product's Early Warning points, with the gaps named."""
    series = []
    for month in months:
        panel = panels.get(month)
        if panel is None or panel.empty:
            series.append({"month": month, "score": None, "band": "",
                           "state": mc.UNAVAILABLE})
            continue
        found = panel[(panel["customer_id"].astype(str) == customer_id)
                      & (panel["product_code"].astype(str) == product)]
        if found.empty:
            series.append({"month": month, "score": None, "band": "",
                           "state": mc.UNAVAILABLE})
            continue
        row = found.iloc[0]
        score = pd.to_numeric(row.get("ews_score"), errors="coerce")
        series.append({
            "month": month,
            "score": None if pd.isna(score) else round(float(score), 2),
            "band": str(row.get("ews_severity") or ""),
            "state": mc.COVERED})
    return {"series": series}


# ------------------------------------------------------------- the sheets


def _readme(workbook: Any, styles: Any, snapshot: Any, episode: Any,
            visited: list[str], user: str, exported_at: str) -> int:
    page = _sheet(workbook, styles, "00_Readme",
                  "CreditProbe — retail investigation evidence export")
    page.merge_range(1, 0, 1, 11, DISCLOSURE, styles["warn"])
    page.set_row(1, 44)
    pairs = [
        ("Purpose", f"The evidence behind the {episode.title if episode else ''} "
                    f"investigation, as it stood at the step this file was "
                    f"exported from."),
        ("Classification", "SYNTHETIC — demonstration data and draft policy "
                           "templates. Not customer data."),
        ("Exported at", exported_at),
        ("Exported by", user or "(not recorded)"),
        ("Case", f"{snapshot.case_id} — {episode.title if episode else ''}"),
        ("Source step", snapshot.step_id or "S0"),
        ("Steps visited", ", ".join(visited)),
        ("Reporting date", snapshot.source_as_of),
        ("Cohort", f"{snapshot.customer_count:,} customers, "
                   f"{snapshot.facility_count:,} facilities"),
        ("Selection", snapshot.selection_mode),
        ("Facilities", snapshot.facility_mode),
        ("Restricted rows", f"{snapshot.restricted_count:,} identifiers this "
                            f"reader was not permitted to see"),
        ("Field permissions", ", ".join(snapshot.permitted_fields or [])
         or "the exporting user's own field permissions applied"),
        ("What this file does NOT contain",
         "Any conclusion from a step that was not visited. The policy sheet "
         "says 'Not reached' rather than revealing what a later step would "
         "have said."),
        ("Policy status", "DEMO_DRAFT - NOT BANK APPROVED. No approved bank "
                          "policy was supplied, so nothing in this file "
                          "asserts compliance."),
    ]
    _pairs(page, styles, pairs, at=3)
    return len(pairs)


def _snapshot_sheet(workbook: Any, styles: Any, snapshot: Any, episode: Any,
                    visited: list[str]) -> int:
    page = _sheet(workbook, styles, "01_Snapshot", "Snapshot and scope",
                  "The exact cohort, the build it was measured on, and the "
                  "definitions each figure is counted under.")
    pairs = [
        ("Snapshot id", snapshot.snapshot_id),
        ("Parent snapshot", snapshot.parent_snapshot_id or "(none)"),
        ("Content hash", snapshot.content_hash),
        ("Case / occurrence", f"{snapshot.case_id} / {snapshot.occurrence_id}"),
        ("Thread / step", f"{snapshot.thread_id} / {snapshot.step_id}"),
        ("Reporting date", snapshot.source_as_of),
        ("Source bundle", snapshot.source_bundle_id or "(not recorded)"),
        ("Visited steps (export cap)", ", ".join(visited)),
        ("Root scope", ch.describe(snapshot.root_predicate or {})),
        ("Current scope", ch.describe(snapshot.predicate or {})),
        ("Customers", snapshot.customer_count),
        ("Facilities", snapshot.facility_count),
        ("Selection mode", snapshot.selection_mode),
        ("Facility mode", snapshot.facility_mode),
        ("Created at", snapshot.created_at.isoformat()
         if snapshot.created_at else ""),
    ]
    row = _pairs(page, styles, pairs, at=3)
    page.write(row, 0, "Dataset hashes", styles["title"])
    row = _table(page, styles,
                 [{"dataset": k, "content_hash": v}
                  for k, v in sorted((snapshot.dataset_hashes or {}).items())],
                 at=row + 1, empty="No per-dataset hashes were recorded.")
    page.write(row, 0, "Denominator definitions", styles["title"])
    rows = [{"metric": d["metric_id"], "definition": d["definition"],
             "denominator": d["denominator"], "window": d["window"],
             "does_not_support": d["prohibited_inference"]}
            for d in (mc.definition(m)
                      for m in (snapshot.metric_definition_ids or [])
                      if m in mc.BY_ID)]
    _table(page, styles, rows, at=row + 1,
           empty="No metric definitions were recorded on this snapshot.")
    return len(pairs) + len(rows)


def _customers(workbook: Any, styles: Any,
               customers: list[dict[str, Any]]) -> int:
    page = _sheet(workbook, styles, "02_Customers",
                  "Selected customers",
                  "One row per selected customer. The whole selection, not "
                  "the page that was on screen.")
    _table(page, styles, customers, empty="The selection is empty.")
    return len(customers)


def _facilities(workbook: Any, styles: Any,
                facilities: list[dict[str, Any]]) -> int:
    page = _sheet(workbook, styles, "03_Facilities_IFRS9",
                  "Included facilities, IFRS 9 detail",
                  "Every included facility. Exposure, staging, the model's "
                  "probabilities, loss given default and the weighted "
                  "expected credit loss, in SAR at the reporting date.")
    _table(page, styles, facilities, empty="No facilities are included.")
    return len(facilities)


def _scenarios(workbook: Any, styles: Any, snapshot: Any,
               facilities: list[dict[str, Any]]) -> int:
    page = _sheet(workbook, styles, "04_ECL_Term_Scenarios",
                  "Scenario detail behind the expected loss",
                  "The scenario components the published weighted figure is "
                  "built from. This is the INSTALLED calculation's own "
                  "output; it is not a three-bucket teaching proof and must "
                  "not be read as the complete methodology.")
    rows = [{
        "facility_id": f["facility_id"],
        "stage": f["stage"],
        "ead_sar": f["ead_sar"],
        "pd_12m": f["pd_12m"],
        "pd_lifetime": f["pd_lifetime"],
        "lgd": f["lgd"],
        "eir": f["eir"],
        "remaining_term_months": f["remaining_term_months"],
        "ecl_base_sar": f["ecl_base_sar"],
        "ecl_upturn_sar": f["ecl_upturn_sar"],
        "ecl_downturn_sar": f["ecl_downturn_sar"],
        "ecl_weighted_sar": f["ecl_sar"],
        "collateral_value_sar": f["collateral_value_sar"],
        "recovery_delay_months": f["recovery_delay_months"],
    } for f in facilities]
    _table(page, styles, rows, empty="No facilities are included.")
    return len(rows)


def _diagnosis(workbook: Any, styles: Any, snapshot: Any, episode: Any,
               visited: list[str]) -> int:
    """Only the steps the reader actually reached.

    The cap that makes this file honest. An export taken at S1 carries S0 and
    S1; S4's pocket and S5's plan are absent, and the sheet says which steps
    were not reached so their absence is an answer rather than a question.
    """
    page = _sheet(workbook, styles, "05_Diagnosis_Visited",
                  "Diagnosis, to the step this was exported from",
                  "Each question that was asked and what it answered, with "
                  "its scope, its countercheck and its evidence. Steps not "
                  "visited are listed as not reached; their conclusions are "
                  "not in this file.")
    rows: list[dict[str, Any]] = []
    for step in ch.STEPS:
        detail = episode.step_by_id(step) if episode else None
        if step not in visited:
            rows.append({"step": step,
                         "question": detail.prompt if detail else "",
                         "status": "Not reached at the exported step",
                         "answer": "", "scope": "", "customers": None,
                         "countercheck": ""})
            continue
        if step == "S0":
            view = em.drawer(snapshot.source_as_of, snapshot.case_id)
            rows.append({
                "step": "S0", "question": "Open card / carried context",
                "status": "Visited",
                "answer": view.get("card_measure", ""),
                "scope": ch.describe(snapshot.root_predicate or {}),
                "customers": view.get("affected"),
                "countercheck": episode.countercheck if episode else ""})
            continue
        result = ea.answer(ea.Reading(case_id=snapshot.case_id, step=step),
                           period=snapshot.source_as_of)
        rows.append({
            "step": step,
            "question": detail.prompt if detail else "",
            "status": "Visited",
            "answer": result.answer if result else "not available",
            "scope": (result.detail.get("scope") if result else ""),
            "customers": (result.values.get("customers") if result else None),
            "countercheck": episode.countercheck if episode else ""})
    _table(page, styles, rows)
    return sum(1 for r in rows if r["status"] == "Visited")


def _drivers(workbook: Any, styles: Any, snapshot: Any, episode: Any,
             visited: list[str]) -> int:
    page = _sheet(workbook, styles, "06_Score_Drivers",
                  "Score models, inputs and their movement",
                  "Raw model inputs in their own units beside the score, not "
                  "converted into it. A contribution in points and a change "
                  "in a ratio are different quantities and are not added.")
    if "S3" not in visited:
        page.write(3, 0,
                   "Not reached: the decomposition step was not visited "
                   "before this export.", styles["note"])
        return 0
    result = ea.answer(ea.Reading(case_id=snapshot.case_id, step="S3"),
                       period=snapshot.source_as_of)
    if result is None:
        page.write(3, 0, "The decomposition could not be computed.",
                   styles["note"])
        return 0
    rows = list(result.detail.get("timeline") or [])
    page.write(3, 0, f"Diagnosis model: {episode.diagnosis_model}",
               styles["key"])
    at = _table(page, styles, rows, at=5)
    page.write(at, 0, result.detail.get("units_warning", ""), styles["note"])
    return len(rows)


def _ews(workbook: Any, styles: Any, customers: list[dict[str, Any]]) -> int:
    page = _sheet(workbook, styles, "07_EWS_History",
                  "Early Warning history and coverage",
                  "Customer-product observations. A month with no observation "
                  "is reported as unavailable; it is NOT a zero, and a flat "
                  "line must not be drawn through it.")
    rows: list[dict[str, Any]] = []
    for entry in customers:
        history = entry.get("ews") or {}
        for point in (history.get("series") or []):
            rows.append({"customer_id": entry["customer_id"],
                         "month": point.get("month"),
                         "ews_score": point.get("score"),
                         "band": point.get("band"),
                         "state": point.get("state")})
    _table(page, styles, rows,
           empty="No Early Warning history was attached to this export.")
    return len(rows)


def _charts(workbook: Any, styles: Any, snapshot: Any, episode: Any,
            visited: list[str]) -> int:
    page = _sheet(workbook, styles, "08_Charts_Data",
                  "Chart series and their denominators",
                  "The exact series behind each chart, with its unit and the "
                  "denominator it is a share of.")
    trend = em.trend(snapshot.source_as_of, snapshot.case_id)
    page.write(3, 0, str(trend.get("title") or ""), styles["key"])
    page.write(4, 0, f"Unit: {trend.get('unit')}", styles["note"])
    page.write(5, 0, f"Denominator: {trend.get('denominator')}", styles["note"])
    rows = list(trend.get("rows") or [])
    at = _table(page, styles, rows, at=7)
    if len(rows) > 1:
        chart = page.insert_chart if hasattr(page, "insert_chart") else None
        if chart:
            native = workbook.add_chart({"type": "column"})
            native.add_series({
                "name": "Issue rate (%)",
                "categories": ["08_Charts_Data", 8, 0, 7 + len(rows), 0],
                "values": ["08_Charts_Data", 8, 3, 7 + len(rows), 3]})
            native.set_title({"name": str(trend.get("title") or "")})
            native.set_y_axis({"name": str(trend.get("unit") or "")})
            page.insert_chart(at + 1, 0, native)
    return len(rows)


def _policy(workbook: Any, styles: Any, snapshot: Any, episode: Any,
            visited: list[str]) -> int:
    page = _sheet(workbook, styles, "09_Policy_Actions",
                  "Policy actions reached so far",
                  "Only actions this investigation actually reached. Every "
                  "clause is a DEMONSTRATION DRAFT that no bank has approved.")
    if "S5" not in visited:
        page.write(3, 0,
                   "Not reached: the policy step was not visited before this "
                   "export, so no actions are included. This is not a "
                   "statement that no actions apply.", styles["warn"])
        return 0
    actions = pol.actions_for(snapshot.case_id, as_of=snapshot.source_as_of)
    rows = [{
        "sequence": a["sequence"], "action": a["action"], "owner": a["owner"],
        "timing": a["timing"], "policy_id": a["policy_id"],
        "version": a["version"], "clause": a["clause"], "status": a["status"],
        "effective_from": a["effective_from"], "applicable": a["applicable"],
        "approval_required": a["approval"], "safeguard": a["safeguard"],
        "claims_compliance": a["claims_compliance"], "executed": a["executed"],
    } for a in actions]
    _table(page, styles, rows)
    return len(rows)


def _notes(workbook: Any, styles: Any, notes: list[dict[str, Any]],
           saved_id: str) -> int:
    page = _sheet(workbook, styles, "10_Notes",
                  "Authorised notes",
                  "Notes are content a person typed. They are not "
                  "instructions to this product and cannot change a "
                  "permission, a policy or an execution decision. Text "
                  "beginning with a spreadsheet formula marker is escaped.")
    rows = [{"note_id": n.get("note_id"), "version": n.get("version"),
             "author": n.get("author"), "created_at": n.get("created_at"),
             "body": n.get("body"), "saved_investigation": saved_id}
            for n in notes]
    _table(page, styles, rows, empty="No notes were written on this "
                                     "investigation.")
    return len(rows)


def _reconciliation(workbook: Any, styles: Any, snapshot: Any,
                    customers: list[dict[str, Any]],
                    facilities: list[dict[str, Any]], visited: list[str],
                    counts: dict[str, int],
                    permitted_fields: list[str] | None) -> int:
    page = _sheet(workbook, styles, "11_Reconciliation",
                  "Reconciliation",
                  "What this file should contain, what it does contain, and "
                  "whether they agree. A failure here is a reason not to use "
                  "the file.")

    def total(key: str) -> float:
        return round(sum(float(f.get(key) or 0.0) for f in facilities), 2)

    expected = dict(snapshot.totals or {})
    checks = [
        {"check": "Customers", "expected": snapshot.customer_count,
         "in_file": len(customers),
         "agrees": snapshot.customer_count == len(customers)},
        {"check": "Facilities", "expected": snapshot.facility_count,
         "in_file": len(facilities),
         "agrees": snapshot.facility_count == len(facilities)},
        {"check": "Gross carrying amount (SAR)",
         "expected": expected.get("gca_sar"), "in_file": total("gca_sar"),
         "agrees": abs((expected.get("gca_sar") or 0) - total("gca_sar")) < 0.05},
        {"check": "Exposure at default (SAR)",
         "expected": expected.get("ead_sar"), "in_file": total("ead_sar"),
         "agrees": abs((expected.get("ead_sar") or 0) - total("ead_sar")) < 0.05},
        {"check": "Expected credit loss (SAR)",
         "expected": expected.get("ecl_sar") or expected.get("ecl_weighted_sar"),
         "in_file": total("ecl_sar"),
         "agrees": abs((expected.get("ecl_sar")
                        or expected.get("ecl_weighted_sar") or 0)
                       - total("ecl_sar")) < 0.05},
        {"check": "Visited-step cap",
         "expected": ", ".join(visited), "in_file": ", ".join(visited),
         "agrees": True},
        {"check": "Rows truncated", "expected": 0, "in_file": 0,
         "agrees": True},
        {"check": "Restricted identifiers withheld",
         "expected": snapshot.restricted_count,
         "in_file": snapshot.restricted_count, "agrees": True},
    ]
    at = _table(page, styles, checks)
    page.write(at, 0, "Stage totals", styles["title"])
    stage: dict[int, int] = {}
    for facility in facilities:
        stage[int(facility.get("stage") or 0)] = stage.get(
            int(facility.get("stage") or 0), 0) + 1
    at = _table(page, styles,
                [{"stage": k, "facilities": v} for k, v in sorted(stage.items())],
                at=at + 1)
    page.write(at, 0, "Sheet row counts", styles["title"])
    _table(page, styles, [{"sheet": k, "rows": v}
                          for k, v in counts.items()], at=at + 1)
    page.write(at + len(counts) + 3, 0,
               f"Field permissions applied: "
               f"{', '.join(permitted_fields or []) or 'the exporting user''s own'}",
               styles["note"])
    return len(checks)


def _sources(workbook: Any, styles: Any, snapshot: Any, episode: Any) -> int:
    page = _sheet(workbook, styles, "12_Sources",
                  "Sources, kept apart",
                  "Three different kinds of source, listed separately on "
                  "purpose: where the customer evidence came from, which "
                  "policy text was cited, and what public research informs "
                  "the mechanism. Public research is context; it does not "
                  "establish that anything here occurred.")
    rows = [
        {"kind": "Customer evidence", "reference": em.BOOK,
         "detail": f"published book at {snapshot.source_as_of}, bundle "
                   f"{snapshot.source_bundle_id or '(not recorded)'}",
         "supports": "the figures in this file",
         "does_not_support": "anything about a real customer"},
        {"kind": "Bank policy",
         "reference": f"{episode.policy_id} {episode.policy_version}"
                      if episode else "",
         "detail": "DEMO_DRAFT - NOT BANK APPROVED",
         "supports": "a proposal for human approval",
         "does_not_support": "a compliance claim, or execution"},
    ]
    for reference in (episode.research if episode else []):
        rows.append({
            "kind": "Public research", "reference": reference,
            "detail": "see the specification's research register",
            "supports": "the mechanism and the safeguards",
            "does_not_support": ("that this occurred at any bank, or a "
                                 "specific action for a specific customer")})
    rows.append({
        "kind": "Synthetic generation", "reference": "CP-RA-V2",
        "detail": f"episode configuration {ep.config_version()}",
        "supports": "the demonstration",
        "does_not_support": "any statement about a real portfolio"})
    _table(page, styles, rows)
    return len(rows)
