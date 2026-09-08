"""Early Warning V2 Word reports: borrower, portfolio and segment, all
generated from the live governed monthly domain — never a static sample
download (spec Sections AS/AT).

Reuses `backend/reporting/writers.py::write_docx()` directly rather than
`backend/reporting/content.py`'s report-assembly functions: those are
tightly bound to the quarterly credit-book's own schema (SMC/BRC board
packs, `_context(quarter)`). `write_docx()` itself is report-shape-agnostic
— it only needs the dict shape documented below — so this module builds
that same shape from Early Warning data instead, which is the reusable
seam without reworking `content.py`'s credit-book-specific section
functions. Each key section now carries a real chart spec (`ews_score_trend`,
`ews_band_mix`, `ews_layer_bars` in `backend/reporting/charts.py`) built
from the same live figures as the section's own table — `charts.render()`
still degrades to no image on any failure rather than breaking the report.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from backend.early_warning import v2_service as svc
from backend.reporting import writers

CLASSIFICATION = "CONFIDENTIAL — FOR INTERNAL CREDIT RISK USE ONLY"


def _finding(text: str, severity: str = "MEDIUM", area: str = "") -> dict:
    return {"text": text, "severity": severity, "area": area}


def _section(key: str, title: str, narrative: str, table: dict | None = None,
             findings: list[dict] | None = None, chart: dict | None = None) -> dict:
    return {"key": key, "title": title, "narrative": narrative, "table": table,
            "chart": chart, "findings": findings or []}


def _methodology_section() -> dict:
    narrative = (
        "The model scores every obligor on two questions that are never added together. "
        "What is happening now is the trigger and accelerator dimension: fresh, observable "
        "deterioration measured against the obligor's own baseline, scaled by how large, fast, "
        "persistent, repeated and corroborated it is, then decayed by signal class. Signals roll "
        "up through 14 sub-categories, then four layers (L1 internal behaviour, L2 credit events, "
        "L3 external intelligence, L4 network) at published weights. How vulnerable the obligor is "
        "is the classifier dimension: 23 structural classifiers in 8 sub-categories, reviewed "
        "periodically and never re-scored daily, rolled up the same way. The two dimensions are "
        "read together off a published 5x5 matrix to set an anchor score, then five discrete "
        "notches (network contagion, direction of travel, evidence quality, data staleness, "
        "management and governance) adjust it by up to 16 points either way, and a small set of "
        "caps and overrides apply last — never a single equation that adds or multiplies the two "
        "dimensions together."
    )
    return _section("methodology", "The Early Warning Model", narrative)


def borrower_report(customer_id: str, *, prepared_by: str = "") -> dict:
    detail = svc.borrower_detail(customer_id)
    latest = detail["latest"]
    history = detail["history"]

    findings: list[dict] = []
    band = latest.get("ews_band", "LOW")
    if band in ("HIGH", "VERY_HIGH"):
        findings.append(_finding(
            f"EWS score {latest['ews_score']:.1f} ({band}). Dominant driver: "
            f"{latest.get('dominant_driver') or 'none'}.",
            severity="HIGH" if band == "VERY_HIGH" else "MEDIUM"))
    if latest.get("overrides_applied"):
        findings.append(_finding(
            f"Overrides applied this period: {latest['overrides_applied']}.", severity="MEDIUM"))

    exec_summary = _section(
        "executive_summary", "Executive Summary",
        f"{latest.get('customer_name', customer_id)} carries SAR {latest.get('exposure', 0):.1f} "
        f"million of exposure against a SAR {latest.get('limit', 0):.1f} million limit, "
        f"{latest.get('dpd', 0):.0f} days past due, IFRS 9 Stage {latest.get('ifrs9_stage', '—')}. "
        f"The Early Warning score is {latest.get('ews_score', 0):.1f}, {band.replace('_', ' ').title()} "
        f"severity. The anchor is a classifier score of {latest.get('classifier_score', 0):.1f} "
        f"({latest.get('classifier_band')}) read against a live trigger-and-accelerator score of "
        f"{latest.get('ta_score', 0):.1f} ({latest.get('ta_band')}).",
        findings=findings,
    )

    position = _section(
        "position", "Obligor Position",
        f"Segment {latest.get('segment', '—')}, sector {latest.get('sector', '—')}, "
        f"region {latest.get('region', '—')}. Relationship manager: "
        f"{latest.get('relationship_manager', '—')}. Internal rating "
        f"{latest.get('internal_rating', '—')}, 12-month PD "
        f"{float(latest.get('pd_12m') or 0):.2f}%.",
        table={"columns": ["Field", "Value"], "rows": [
            ["Exposure (SAR mn)", f"{latest.get('exposure', 0):.1f}"],
            ["Limit (SAR mn)", f"{latest.get('limit', 0):.1f}"],
            ["Utilisation", f"{latest.get('utilisation_pct', 0):.1f}%"],
            ["Days past due", f"{latest.get('dpd', 0):.0f}"],
            ["IFRS 9 stage", str(latest.get('ifrs9_stage', '—'))],
            ["Internal rating", str(latest.get('internal_rating', '—'))],
        ]},
    )

    history_table = {
        "columns": ["Month", "EWS score", "EWS band", "T&A score", "Classifier score"],
        "rows": [[h["snapshot_month"], f"{h['ews_score']:.1f}", h["ews_band"],
                  f"{h['ta_score']:.1f}", f"{h['classifier_score']:.1f}"] for h in history],
    }
    trend_chart = {
        "kind": "ews_score_trend", "title": "EWS, T&A and Classifier score by month",
        "data": [(h["snapshot_month"], h["ews_score"], h["ta_score"], h["classifier_score"])
                 for h in history],
    }
    trend = _section(
        "trend", "Twelve-Month Movement",
        f"Score history over the {len(history)} months on record. "
        f"{'The score has moved into higher severity over this window.' if len(history) >= 2 and history[-1]['ews_score'] > history[0]['ews_score'] else 'The score has been broadly stable or improving over this window.'}",
        table=history_table, chart=trend_chart,
    )

    fired = detail.get("fired_signals", [])
    evidence_table = None
    if fired:
        evidence_table = {
            "columns": ["Signal", "Score", "Causal chain"],
            "rows": [[f["signal_key"], f"{f['signal_score']:.1f}", f["causal_chain_id"]]
                     for f in fired],
        }
    evidence = _section(
        "evidence", "Evidence and Data Lineage",
        f"{len(fired)} signal(s) fired this period. Every field in this report traces back to "
        "the governed source domain recorded in the Early Warning field-level lineage "
        "(GET /early-warning/v2/lineage) — ratings and PD from Corporate Ratings, IFRS 9 stage "
        "and ECL from the IFRS 9 domain, exposure and collateral from Core Portfolio / Facility.",
        table=evidence_table,
    )

    return {
        "type": "ews_borrower", "title": f"Early Warning — {latest.get('customer_name', customer_id)}",
        "short_title": "Early Warning", "audience": "Credit Risk", "purpose":
            "Prepared for internal credit risk use. Every figure is computed from the live "
            "Early Warning V2 monthly domain and reconciles to the corresponding screen in "
            "CreditProbe.",
        "quarter": latest.get("snapshot_month", ""), "quarter_label": latest.get("snapshot_month", ""),
        "generated_at": datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        "prepared_by": prepared_by or "CreditProbe AI — Early Warning System",
        "sections": [exec_summary, _methodology_section(), position, trend, evidence],
        "findings": findings, "actions": [], "remediation": [],
        "high_severity_count": sum(1 for f in findings if f["severity"] == "HIGH"),
        "classification": CLASSIFICATION,
    }


def portfolio_report(*, period: str | None = None, prepared_by: str = "") -> dict:
    summary = svc.portfolio_summary(period)
    trend = svc.portfolio_trend()
    segments = svc.segment_summary(period)
    top = svc.top_high_risk(period, limit=25)

    exec_summary = _section(
        "executive_summary", "Executive Summary",
        f"The portfolio Early Warning score stands at {summary['portfolio_ews']:.1f} on an "
        f"exposure-weighted basis for {summary['borrower_count']} borrowers. "
        f"{summary['high_plus_count']} obligors ({100 * summary['high_plus_count'] / max(summary['borrower_count'], 1):.1f}%) "
        f"sit at High severity or above, carrying SAR {summary['high_plus_exposure']:.1f} million "
        f"of a total SAR {summary['total_exposure']:.1f} million.",
    )

    dist_table = {
        "columns": ["Severity", "Borrowers", "Exposure (SAR mn)", "Share of exposure"],
        "rows": [[b["band"].replace("_", " ").title(), b["borrower_count"],
                  f"{b['exposure']:.1f}", f"{b['exposure_pct']:.1f}%"]
                 for b in summary["severity_distribution"]],
    }
    dist_chart = {
        "kind": "ews_band_mix", "title": "Borrowers by severity band",
        "data": [(b["band"].replace("_", " ").title(), b["borrower_count"])
                 for b in summary["severity_distribution"] if b["borrower_count"] > 0],
    }
    position = _section("position", "Portfolio Position",
                         "Severity distribution across the governed monthly domain.",
                         table=dist_table, chart=dist_chart)

    trend_table = {"columns": ["Month", "Portfolio EWS", "High+ count"],
                   "rows": [[t["period"], f"{t['portfolio_ews']:.1f}", t["high_plus_count"]] for t in trend]}
    trend_section = _section("trend", "Movement Over Time",
                              f"Portfolio EWS is the exposure-weighted mean of obligor scores across "
                              f"{len(trend)} monthly snapshots.", table=trend_table)

    seg_table = {"columns": ["Segment", "Borrowers", "Exposure (SAR mn)", "Portfolio EWS", "High+"],
                 "rows": [[s["segment"], s["borrower_count"], f"{s['exposure']:.1f}",
                           f"{s['portfolio_ews']:.1f}", s["high_plus_count"]] for s in segments]}
    seg_section = _section("segments", "Where the Risk Sits — By Segment",
                            "Segments ranked by exposure-weighted Early Warning score.",
                            table=seg_table)

    watch_table = {"columns": ["Customer", "Segment", "Exposure", "EWS", "Band", "Dominant driver"],
                   "rows": [[r["customer_name"], r["segment"], f"{r['exposure']:.1f}",
                             f"{r['ews_score']:.1f}", r["ews_band"], r.get("dominant_driver") or "—"]
                            for r in top]}
    watch_chart = {
        "kind": "ews_layer_bars", "title": "Top 10 highest-scoring obligors",
        "data": [(r["customer_name"], r["ews_score"]) for r in top[:10]],
    }
    watch_section = _section("watchlist", "Watchlist", "The highest-scoring obligors this period.",
                              table=watch_table, chart=watch_chart)

    return {
        "type": "ews_portfolio", "title": "Early Warning — Portfolio Report",
        "short_title": "Early Warning", "audience": "Credit Risk Committee",
        "purpose": "Prepared for internal credit risk use. Every figure is computed from the "
                   "live Early Warning V2 monthly domain.",
        "quarter": summary["period"], "quarter_label": summary["period"],
        "generated_at": datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        "prepared_by": prepared_by or "CreditProbe AI — Early Warning System",
        "sections": [exec_summary, _methodology_section(), position, trend_section, seg_section, watch_section],
        "findings": [], "actions": [], "remediation": [],
        "high_severity_count": summary["high_plus_count"],
        "classification": CLASSIFICATION,
    }


def segment_report(segment: str, *, period: str | None = None, prepared_by: str = "") -> dict:
    bm = svc.borrower_month(period)
    rows = bm[bm["segment"] == segment]
    if rows.empty:
        raise KeyError(segment)

    weighted = (rows["ews_score"] * rows["exposure"]).sum() / rows["exposure"].sum() \
        if rows["exposure"].sum() > 0 else rows["ews_score"].mean()
    high_plus = rows[rows["ews_band"].isin(("HIGH", "VERY_HIGH"))]

    exec_summary = _section(
        "executive_summary", "Executive Summary",
        f"{segment} carries an exposure-weighted Early Warning score of {weighted:.1f} across "
        f"{len(rows)} borrowers and SAR {rows['exposure'].sum():.1f} million of exposure. "
        f"{len(high_plus)} borrowers sit at High severity or above.",
    )

    borrower_table = {
        "columns": ["Customer", "Exposure", "DPD", "EWS", "Band", "Dominant driver"],
        "rows": [[r["customer_name"], f"{r['exposure']:.1f}", f"{r['dpd']:.0f}",
                  f"{r['ews_score']:.1f}", r["ews_band"], r.get("dominant_driver") or "—"]
                 for _, r in rows.sort_values("ews_score", ascending=False).iterrows()],
    }
    borrowers_chart = {
        "kind": "ews_layer_bars", "title": f"{segment} — top 10 by EWS score",
        "data": [(r["customer_name"], r["ews_score"])
                 for _, r in rows.sort_values("ews_score", ascending=False).head(10).iterrows()],
    }
    borrowers_section = _section("borrowers", "Borrowers", "Every borrower in this segment, "
                                  "ranked by Early Warning score.", table=borrower_table,
                                  chart=borrowers_chart)

    return {
        "type": "ews_segment", "title": f"Early Warning — {segment}",
        "short_title": "Early Warning", "audience": "Credit Risk",
        "purpose": "Prepared for internal credit risk use.",
        "quarter": rows["snapshot_month"].iloc[0], "quarter_label": rows["snapshot_month"].iloc[0],
        "generated_at": datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        "prepared_by": prepared_by or "CreditProbe AI — Early Warning System",
        "sections": [exec_summary, _methodology_section(), borrowers_section],
        "findings": [], "actions": [], "remediation": [],
        "high_severity_count": len(high_plus),
        "classification": CLASSIFICATION,
    }


def multi_borrower_report(customer_ids: list[str], *, prepared_by: str = "") -> dict:
    """Spec Section AT: selecting many customers must not collapse to a
    tiny summary table. Each borrower gets its own substantive section —
    the same executive-summary/position/evidence shape as the single-
    borrower report — plus one population-comparison section up front."""
    details = []
    for cid in customer_ids:
        try:
            details.append((cid, svc.borrower_detail(cid)))
        except KeyError:
            continue
    if not details:
        raise KeyError("none of the requested customer_ids have Early Warning data")

    rows = [d["latest"] for _, d in details]
    comparison_table = {
        "columns": ["Customer", "Exposure", "EWS", "Band", "Dominant driver"],
        "rows": [[r.get("customer_name", cid), f"{r.get('exposure', 0):.1f}",
                  f"{r.get('ews_score', 0):.1f}", r.get("ews_band"), r.get("dominant_driver") or "—"]
                 for cid, r in zip(customer_ids, rows, strict=False)],
    }
    total_exposure = sum(r.get("exposure", 0) or 0 for r in rows)
    high_plus = sum(1 for r in rows if r.get("ews_band") in ("HIGH", "VERY_HIGH"))
    comparison = _section(
        "comparison", "Population Comparison",
        f"{len(details)} borrowers selected, SAR {total_exposure:.1f} million of combined "
        f"exposure, {high_plus} at High severity or above.",
        table=comparison_table,
    )

    sections = [comparison, _methodology_section()]
    findings: list[dict] = []
    for idx, (cid, detail) in enumerate(details, start=1):
        latest = detail["latest"]
        band = latest.get("ews_band", "LOW")
        section_findings = []
        if band in ("HIGH", "VERY_HIGH"):
            f = _finding(f"EWS {latest['ews_score']:.1f} ({band}). Dominant driver: "
                         f"{latest.get('dominant_driver') or 'none'}.",
                         severity="HIGH" if band == "VERY_HIGH" else "MEDIUM")
            section_findings.append(f)
            findings.append(f)
        history_table = {
            "columns": ["Month", "EWS score", "EWS band"],
            "rows": [[h["snapshot_month"], f"{h['ews_score']:.1f}", h["ews_band"]]
                     for h in detail["history"]],
        }
        sections.append(_section(
            f"borrower_{idx}", f"{latest.get('customer_name', cid)}",
            f"Exposure SAR {latest.get('exposure', 0):.1f} million, "
            f"{latest.get('dpd', 0):.0f} days past due, IFRS 9 Stage {latest.get('ifrs9_stage', '—')}. "
            f"EWS {latest.get('ews_score', 0):.1f} ({band}): classifier {latest.get('classifier_band')} "
            f"({latest.get('classifier_score', 0):.1f}), T&A {latest.get('ta_band')} "
            f"({latest.get('ta_score', 0):.1f}).",
            table=history_table, findings=section_findings,
        ))

    return {
        "type": "ews_multi_borrower", "title": f"Early Warning — {len(details)} Borrowers",
        "short_title": "Early Warning", "audience": "Credit Risk",
        "purpose": "Prepared for internal credit risk use. Every figure is computed from the "
                   "live Early Warning V2 monthly domain.",
        "quarter": rows[0].get("snapshot_month", "") if rows else "",
        "quarter_label": rows[0].get("snapshot_month", "") if rows else "",
        "generated_at": datetime.now(UTC).strftime("%d %b %Y %H:%M UTC"),
        "prepared_by": prepared_by or "CreditProbe AI — Early Warning System",
        "sections": sections, "findings": findings, "actions": [], "remediation": [],
        "high_severity_count": sum(1 for f in findings if f["severity"] == "HIGH"),
        "classification": CLASSIFICATION,
    }


def generate_docx(scope: str, identifier: str | None = None, *, period: str | None = None,
                   customer_ids: list[str] | None = None) -> bytes:
    """scope in {"borrower", "portfolio", "segment", "multi_borrower"}."""
    if scope == "borrower":
        if not identifier:
            raise ValueError("borrower report needs a customer_id")
        report = borrower_report(identifier)
    elif scope == "segment":
        if not identifier:
            raise ValueError("segment report needs a segment name")
        report = segment_report(identifier, period=period)
    elif scope == "portfolio":
        report = portfolio_report(period=period)
    elif scope == "multi_borrower":
        if not customer_ids:
            raise ValueError("multi-borrower report needs customer_ids")
        report = multi_borrower_report(customer_ids)
    else:
        raise ValueError(f"unknown report scope {scope!r}")
    return writers.write_docx(report, context=None)
