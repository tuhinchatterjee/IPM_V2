"""
Requires Attention: ranked, evidence-backed issue cards over the book in use.

Deterministic detectors over governed metrics (`metric_catalog.py`) and the
governed grid view -- no model call. Each detector names its rule id and
version, the metric ids it measured, both comparison periods, the exact
typed filters of the affected population, and a measured breakdown of the
movement. Drivers are CONTRIBUTIONS (association), never causes; the
interpretation sentence says so.

Cards are ranked by a materiality score (share of the book's ECL or EAD that
is affected × size of the movement × the pattern's weight) and only material
findings are shown. A detector that finds nothing material produces nothing:
an empty section is truthful, a padded one is not.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any

from backend.workspace import grid, metrics, nbq
from backend.workspace import metric_catalog as mc
from backend.workspace.access import Book

RULESET_VERSION = "gw-issues-1.0.0"

#: Detector definitions. `mode`:
#:   book_delta     -- the metric for the whole book, t vs t-1;
#:   segment_delta  -- the metric by `dimension`, t vs t-1, largest movers;
#:   segment_excess -- the metric's LEVEL by `dimension` against the book level.
PATTERNS: list[dict[str, Any]] = [
    # ---- Corporate -----------------------------------------------------------
    {"id": "CORP-BOOK-ECL", "domain": "corporate", "mode": "book_delta",
     "metric": "M001", "breakdown": "sector", "min_rel": 0.03, "weight": 1.0,
     "title": "Booked ECL {verb} {move} across the Corporate book"},
    {"id": "CORP-SECTOR-ECL", "domain": "corporate", "mode": "segment_delta",
     "metric": "M001", "dimension": "sector", "breakdown": "sub_sector",
     "min_rel": 0.08, "min_share": 0.02, "top": 2, "weight": 1.0,
     "title": "{value}: booked ECL {verb} {move}"},
    {"id": "CORP-STAGE2-MIGRATION", "domain": "corporate", "mode": "segment_level",
     "metric": "M009", "dimension": "sector", "breakdown": "sub_sector",
     "min_value": 50.0, "top": 1, "weight": 0.9,
     "title": "{value}: {level} of EAD migrated from Stage 1 to Stage 2"},
    {"id": "CORP-DOWNGRADES", "domain": "corporate", "mode": "segment_excess",
     "metric": "M023", "dimension": "sector", "breakdown": "rating_current",
     "min_excess": 0.03, "top": 1, "weight": 0.8,
     "title": "{value}: rating downgrades at {level} of borrowers (book {book})"},
    {"id": "CORP-COVENANT", "domain": "corporate", "mode": "segment_excess",
     "metric": "M036", "dimension": "sector", "breakdown": "product_type",
     "min_excess": 0.03, "top": 1, "weight": 0.7,
     "title": "{value}: covenant breaches on {level} of tested facilities (book {book})"},
    {"id": "CORP-PD-DRIFT", "domain": "corporate", "mode": "segment_delta",
     "metric": "M015", "dimension": "sector", "breakdown": "rating_current",
     "min_abs": 0.0010, "min_share": 0.02, "top": 1, "weight": 0.8,
     "title": "{value}: EAD-weighted PD {verb} {move}"},
    {"id": "CORP-WATCHLIST", "domain": "corporate", "mode": "segment_excess",
     "metric": "M051", "dimension": "sector", "breakdown": "rating_current",
     "min_excess": 0.03, "top": 1, "weight": 0.7,
     "title": "{value}: {level} of EAD is on the watchlist (book {book})"},
    {"id": "CORP-EWS", "domain": "corporate", "mode": "segment_level",
     "metric": "M063", "dimension": "sector", "breakdown": "rating_current",
     "min_value": 2000.0, "top": 1, "weight": 0.75,
     "title": "{value}: {level} of EAD in high/critical early-warning bands"},
    {"id": "CORP-PAST-DUE", "domain": "corporate", "mode": "segment_level",
     "metric": "M054", "dimension": "sector", "breakdown": "product_type",
     "min_value": 1000.0, "top": 1, "weight": 0.6,
     "title": "{value}: {level} of EAD is past due"},
    {"id": "CORP-CONCENTRATION", "domain": "corporate", "mode": "book_level",
     "metric": "M020", "breakdown": "sector", "min_value": 0.10, "weight": 0.5,
     "title": "Top-10 borrower concentration at {level} of EAD"},
    # ---- Retail --------------------------------------------------------------
    {"id": "RET-BOOK-ECL", "domain": "retail", "mode": "book_delta",
     "metric": "M001", "breakdown": "product", "min_rel": 0.05, "weight": 1.0,
     "title": "Booked ECL {verb} {move} across the Retail book"},
    {"id": "RET-PRODUCT-ECL", "domain": "retail", "mode": "segment_delta",
     "metric": "M001", "dimension": "product", "breakdown": "sub_product",
     "min_rel": 0.10, "min_share": 0.05, "top": 2, "weight": 0.95,
     "title": "{value}: booked ECL {verb} {move}"},
    {"id": "RET-FORWARD-RISK", "domain": "retail", "mode": "segment_level",
     "metric": "M034", "dimension": "product", "breakdown": "score_band",
     "min_value": 200, "top": 1, "weight": 0.85,
     "title": "{value}: {level} customers with PD up 20% or more this month"},
    {"id": "RET-EWS", "domain": "retail", "mode": "segment_excess",
     "metric": "M033", "dimension": "product", "breakdown": "score_band",
     "min_excess": 0.02, "top": 1, "weight": 0.8,
     "title": "{value}: {level} of warned customers are high/critical (book {book})"},
    {"id": "RET-PAYMENT-RATIO", "domain": "retail", "mode": "segment_delta",
     "metric": "M057", "dimension": "product", "breakdown": "employment_type",
     "min_abs": 0.02, "min_share": 0.05, "top": 1, "weight": 0.75,
     "direction_only": "down",
     "title": "{value}: average payment ratio {verb} {move}"},
    {"id": "RET-WEAK-BAND", "domain": "retail", "mode": "segment_excess",
     "metric": "M056", "dimension": "product", "breakdown": "score_band",
     "min_excess": 0.03, "top": 1, "weight": 0.6,
     "title": "{value}: {level} of EAD in weak score bands D/E (book {book})"},
    {"id": "RET-SCORE-DETERIORATION", "domain": "retail", "mode": "segment_level",
     "metric": "M058", "dimension": "product", "breakdown": "score_band",
     "min_value": 20, "top": 1, "weight": 0.6,
     "title": "{value}: {level} customers' behaviour score deteriorated"},
    {"id": "RET-PAST-DUE", "domain": "retail", "mode": "segment_level",
     "metric": "M054", "dimension": "product", "breakdown": "delinquency_bucket",
     "min_value": 1.0, "top": 1, "weight": 0.55,
     "title": "{value}: {level} of EAD is past due"},
    {"id": "RET-VINTAGE", "domain": "retail", "mode": "segment_excess",
     "metric": "M061", "dimension": "product", "breakdown": "sub_product",
     "min_excess": 0.002, "top": 1, "weight": 0.5,
     "title": "{value}: newest-vintage PD {level} (book {book})"},
]

NOUNS = {"corporate": ("facilities", "borrowers"),
         "retail": ("accounts", "customers")}


# ---- display (server-side, for card titles and sentences) -------------------

def fmt(value: Any, unit: str) -> str:
    if value is None:
        return "—"
    v = float(value)
    if unit == "SAR_mn":
        a = abs(v)
        if a >= 1000:
            text = f"SAR {a / 1000:.1f}bn"
        elif a >= 1:
            text = f"SAR {a:.0f}m" if a >= 100 else f"SAR {a:.1f}m" if a >= 10 else f"SAR {a:.2f}m"
        elif a >= 0.001:
            text = f"SAR {a * 1000:.0f}k"
        else:
            text = f"SAR {a * 1e6:.0f}"
        return ("−" if v < 0 else "") + text
    if unit == "fraction":
        return f"{v * 100:.2f}%"
    if unit == "count":
        return f"{int(round(v)):,}"
    return f"{v:.2f}"


def fmt_move(delta: float | None, rel: float | None, unit: str) -> str:
    if delta is None:
        return "—"
    sign = "+" if delta > 0 else "−" if delta < 0 else ""
    if unit == "fraction":
        return f"{sign}{abs(delta) * 10000:.0f} bps"
    body = fmt(abs(delta), unit)
    return f"{sign}{body}" + (f" ({sign}{abs(rel) * 100:.1f}%)" if rel is not None else "")


def _verb(delta: float | None) -> str:
    if delta is None or delta == 0:
        return "unchanged at"
    return "rose" if delta > 0 else "fell"


# ---- detection ------------------------------------------------------------------

def _share_of_book(affected: dict[str, Any], book_totals: dict[str, Any]) -> float:
    ecl = book_totals.get("ecl") or 0
    ead = book_totals.get("ead") or 0
    if ecl:
        return float(affected.get("ecl") or 0) / ecl
    return float(affected.get("ead") or 0) / ead if ead else 0.0


def _affected(book: Book, filters: list[dict[str, Any]]) -> dict[str, Any]:
    return grid.query(book, filters=filters, limit=1)["summary"]


def _breakdown(book: Book, pattern: dict[str, Any],
               filters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dim = pattern["breakdown"]
    metric_id = pattern["metric"]
    metric = mc.BY_ID[metric_id]
    try:
        if metric["evaluator"] or metric["kind"] != "book":
            groups = metrics.evaluate(book, "M002", filters=filters,
                                      group_by=dim)["groups"]
            label_metric = "M002"
        else:
            delta_id = "M002" if metric_id == "M001" else metric_id
            if delta_id == "M002":
                groups = metrics.evaluate(book, "M002", filters=filters,
                                          group_by=dim)["groups"]
            else:
                now = metrics.evaluate(book, metric_id, filters=filters,
                                       group_by=dim)["groups"]
                groups = [{"dimension": g["dimension"], "value": g["value"],
                           "current": g["value"]} for g in now]
            label_metric = delta_id
    except Exception:  # noqa: BLE001 - a breakdown is supporting evidence
        return []
    rows = [g for g in groups if g.get("value") is not None]
    rows.sort(key=lambda g: -abs(float(g["value"])))
    unit = mc.BY_ID[label_metric]["unit"]
    return [{"label": str(g["dimension"]), "value": float(g["value"]),
             "current": g.get("current"), "prior": g.get("prior"),
             "metric_id": label_metric, "unit": unit,
             "display": fmt_move(float(g["value"]), None, unit)
             if label_metric == "M002" else fmt(g["value"], unit)}
            for g in rows[:8]]


def _severity(score: float) -> str:
    if score >= 0.06:
        return "critical"
    if score >= 0.025:
        return "high"
    if score >= 0.008:
        return "moderate"
    return "low"


def _candidates(book: Book, pattern: dict[str, Any], book_totals: dict[str, Any]
                ) -> list[dict[str, Any]]:
    metric = mc.BY_ID[pattern["metric"]]
    unit = metric["unit"]
    mode = pattern["mode"]
    out: list[dict[str, Any]] = []
    if mode in ("book_delta", "book_level"):
        now = metrics.evaluate(book, pattern["metric"])
        if mode == "book_delta":
            delta = metrics.evaluate(book, "M002" if pattern["metric"] == "M001"
                                     else pattern["metric"])
            current = now.get("value")
            prior_eval = (metrics.evaluate(book, pattern["metric"],
                                           period=book.periods[-2])
                          if len(book.periods) > 1 else {})
            prior = prior_eval.get("value")
            if current is None or prior is None:
                return []
            d = float(current) - float(prior)
            rel = d / float(prior) if prior else None
            if rel is None or abs(rel) < pattern["min_rel"]:
                return []
            score = abs(rel) * pattern["weight"]
            out.append({"value": "whole book", "dimension": "portfolio",
                        "filters": [], "current": current, "prior": prior,
                        "delta": d, "rel": rel, "score": score,
                        "level_display": fmt(current, unit),
                        "move_display": fmt_move(d, rel, unit)})
        else:
            v = now.get("value")
            if v is None or v < pattern["min_value"]:
                return []
            out.append({"value": "whole book", "dimension": "portfolio",
                        "filters": [], "current": v, "prior": None, "delta": None,
                        "rel": None, "score": float(v) * pattern["weight"] * 0.2,
                        "level_display": fmt(v, unit), "move_display": ""})
        return out

    dim = pattern["dimension"]
    if mode == "segment_delta":
        groups = metrics.evaluate(book, pattern["metric"], group_by=dim)["groups"]
        prior_groups = {g["dimension"]: g for g in (metrics.evaluate(
            book, pattern["metric"], period=book.periods[-2],
            group_by=dim)["groups"] if len(book.periods) > 1 else [])}
        for g in groups:
            p = prior_groups.get(g["dimension"])
            if g["value"] is None or p is None or p["value"] is None:
                continue
            d = float(g["value"]) - float(p["value"])
            rel = d / float(p["value"]) if p["value"] else None
            if pattern.get("direction_only") == "down" and d >= 0:
                continue
            if "min_rel" in pattern and (rel is None or abs(rel) < pattern["min_rel"]):
                continue
            if "min_abs" in pattern and abs(d) < pattern["min_abs"]:
                continue
            filters = [{"column": dim, "op": "eq", "value": g["dimension"]}]
            affected = _affected(book, filters)
            share = _share_of_book(affected, book_totals)
            if share < pattern.get("min_share", 0):
                continue
            magnitude = abs(rel) if rel is not None else abs(d) * 10
            out.append({"value": g["dimension"], "dimension": dim,
                        "filters": filters, "current": g["value"],
                        "prior": p["value"], "delta": d, "rel": rel,
                        "affected": affected,
                        "score": magnitude * max(share, 0.01) * 10 * pattern["weight"],
                        "level_display": fmt(g["value"], unit),
                        "move_display": fmt_move(d, rel if unit != "fraction" else None, unit)})
    else:  # segment_level / segment_excess
        groups = metrics.evaluate(book, pattern["metric"], group_by=dim)["groups"] \
            if not metric["evaluator"] else _evaluator_groups(book, pattern, dim)
        book_value = metrics.evaluate(book, pattern["metric"]).get("value")
        for g in groups:
            v = g["value"]
            if v is None:
                continue
            if mode == "segment_excess":
                if book_value is None or v - book_value < pattern["min_excess"]:
                    continue
            elif v < pattern["min_value"]:
                continue
            filters = [{"column": dim, "op": "eq", "value": g["dimension"]}]
            affected = _affected(book, filters)
            share = _share_of_book(affected, book_totals)
            if mode == "segment_excess":
                magnitude = (v - book_value) / max(abs(book_value), 1e-9)
            elif unit == "SAR_mn":
                magnitude = v / max(book_totals.get("ead") or 1, 1e-9) * 20
            else:
                magnitude = v / max(affected.get("owners") or 1, 1)
            out.append({"value": g["dimension"], "dimension": dim,
                        "filters": filters, "current": v, "prior": None,
                        "delta": None, "rel": None, "affected": affected,
                        "book_value": book_value,
                        "score": min(magnitude, 5) * max(share, 0.01) * pattern["weight"],
                        "level_display": fmt(v, unit), "move_display": ""})
    out.sort(key=lambda c: -c["score"])
    return out[: pattern.get("top", 1)]


def _evaluator_groups(book: Book, pattern: dict[str, Any], dim: str
                      ) -> list[dict[str, Any]]:
    values = [r["value"] for r in grid.grouped(book, dimension=dim,
                                               measures=("ead_sar_mn",))]
    out = []
    for value in values:
        r = metrics.evaluate(book, pattern["metric"],
                             filters=[{"column": dim, "op": "eq", "value": value}])
        out.append({"dimension": value, "value": r.get("value")})
    return out


def _issue(book: Book, pattern: dict[str, Any], cand: dict[str, Any],
           book_totals: dict[str, Any], generated_at: float) -> dict[str, Any]:
    metric = mc.BY_ID[pattern["metric"]]
    unit = metric["unit"]
    entities, owners = NOUNS[book.domain_id]
    filters = cand["filters"]
    affected = cand.get("affected") or _affected(book, filters)
    series = metrics.series(book, pattern["metric"], periods=8,
                            filters=filters or None)
    ecl_series = metrics.series(book, "M001", periods=8, filters=filters or None)
    drivers = _breakdown(book, pattern, filters)
    title = pattern["title"].format(
        value=cand["value"], verb=_verb(cand.get("delta")),
        move=cand.get("move_display", ""), level=cand["level_display"],
        book=fmt(cand.get("book_value"), unit))
    share = _share_of_book(affected, book_totals)
    score = cand["score"]
    severity = _severity(score)
    key = f"{pattern['id']}|{book.domain_id}|{book.release_id}|{book.latest_period}|{cand['value']}"
    issue_id = "iss-" + hashlib.sha256(key.encode()).hexdigest()[:12]
    top = drivers[0] if drivers else None
    where = "across the book" if cand["value"] == "whole book" else f"in {cand['value']}"
    if cand.get("delta") is not None:
        fact = (f"{metric['name']} {where} moved from "
                f"{fmt(cand['prior'], unit)} in {book.periods[-2]} to "
                f"{fmt(cand['current'], unit)} in {book.latest_period} "
                f"({cand['move_display']}).")
    elif cand.get("book_value") is not None:
        fact = (f"{metric['name']} {where} is {cand['level_display']} against "
                f"{fmt(cand['book_value'], unit)} for the whole book in "
                f"{book.latest_period}.")
    else:
        fact = f"{metric['name']} {where} is {cand['level_display']} in {book.latest_period}."
    driver = (f" The largest measured contribution is {top['label']} "
              f"({top['display']})." if top else "")
    interpretation = (fact + driver + " This is an association in the "
                      "published data, not an established cause.")
    issue = {
        "issue_id": issue_id, "domain_id": book.domain_id,
        "release_id": book.release_id, "fingerprint": book.fingerprint,
        "generated_at": generated_at,
        "detection_rule": {"id": pattern["id"], "version": RULESET_VERSION,
                           "mode": pattern["mode"]},
        "title": title, "severity": severity, "score": round(score, 6),
        "metric_id": pattern["metric"], "metric_name": metric["name"],
        "metric_unit": unit,
        "segment": {"dimension": cand["dimension"], "value": cand["value"]},
        "entity_plural": entities, "owner_plural": owners,
        "materiality": {
            "current_value": cand["current"], "prior_value": cand.get("prior"),
            "movement_abs": cand.get("delta"), "movement_rel": cand.get("rel"),
            "movement_display": cand.get("move_display") or cand["level_display"],
            "level_display": cand["level_display"],
            "book_value": cand.get("book_value"),
            "threshold": {k: pattern[k] for k in ("min_rel", "min_abs",
                                                  "min_value", "min_excess",
                                                  "min_share") if k in pattern},
            "threshold_relation": "above",
            "affected_ead": affected.get("ead"), "affected_ecl": affected.get("ecl"),
            "affected_entities": affected.get("entities", 0),
            "affected_owners": affected.get("owners", 0),
            "share_of_book_ecl": share,
            "stage2_ead": sum(s["ead"] or 0 for s in affected.get("stage_mix", [])
                              if s.get("stage") == 2),
            "stage3_ead": sum(s["ead"] or 0 for s in affected.get("stage_mix", [])
                              if s.get("stage") == 3),
        },
        "evidence": {
            "metric_ids": sorted({pattern["metric"], "M001", "M002",
                                  *(d["metric_id"] for d in drivers)}),
            "metric_versions": {pattern["metric"]: metric["version"]},
            "period": book.latest_period,
            "prior_period": book.periods[-2] if len(book.periods) > 1 else "",
            "predicate": filters, "series": series["points"],
            "ecl_series": ecl_series["points"],
            "breakdown_dimension": pattern["breakdown"],
            "breakdown": drivers,
            "stage_mix": affected.get("stage_mix", []),
            "band_mix": affected.get("band_mix", []),
        },
        "drivers": drivers[:3],
        "interpretation": interpretation,
        "fact_vs_inference": {"fact": fact, "inference": driver.strip() or None,
                              "caveat": "association, not an established cause"},
        "cohort": {"filters": filters, "selection": "row",
                   "description": f"{entities} {where}",
                   "entities": affected.get("entities", 0),
                   "owners": affected.get("owners", 0),
                   "ead": affected.get("ead"), "ecl": affected.get("ecl")},
        "actions": ["investigate", "show_customers", "compare_periods",
                    "explain_driver", "view_data", "save_cohort", "run_whatif",
                    "share", "monitor"],
    }
    issue["next_best_questions"] = nbq.for_issue(issue)
    return issue


def detect(book: Book) -> dict[str, Any]:
    started = time.perf_counter()
    totals = grid.query(book, limit=1)["summary"]
    generated_at = time.time()
    cards: list[dict[str, Any]] = []
    ran: list[dict[str, Any]] = []
    for pattern in PATTERNS:
        if pattern["domain"] != book.domain_id:
            continue
        try:
            found = _candidates(book, pattern, totals)
            for cand in found:
                cards.append(_issue(book, pattern, cand, totals, generated_at))
            ran.append({"rule": pattern["id"], "found": len(found)})
        except Exception as exc:  # noqa: BLE001 - one detector never blanks the feed
            ran.append({"rule": pattern["id"], "found": 0,
                        "error": f"{type(exc).__name__}: {exc}"[:300]})
    cards.sort(key=lambda c: -c["score"])
    return {"domain_id": book.domain_id, "release_id": book.release_id,
            "fingerprint": book.fingerprint, "period": book.latest_period,
            "prior_period": book.periods[-2] if len(book.periods) > 1 else "",
            "ruleset": RULESET_VERSION, "generated_at": generated_at,
            "issues": cards, "detectors": ran,
            "book": {"ead": totals["ead"], "ecl": totals["ecl"],
                     "entities": totals["entities"], "owners": totals["owners"]},
            "server_ms": int((time.perf_counter() - started) * 1000),
            "model_calls": 0}


_FEED: dict[tuple, dict[str, Any]] = {}


def feed(book: Book, *, refresh: bool = False) -> dict[str, Any]:
    key = (book.tenant_id, book.domain_id, book.release_id, book.fingerprint)
    if refresh or key not in _FEED:
        _FEED[key] = detect(book)
    return _FEED[key]


def find(book: Book, issue_id: str) -> dict[str, Any] | None:
    for card in feed(book)["issues"]:
        if card["issue_id"] == issue_id:
            return card
    return None


def seed_for_thread(issue: dict[str, Any]) -> dict[str, Any]:
    """The issue in the attention-item shape the Cockpit already reads.

    `context.build` turns this into the analysis packet for every turn of the
    thread (relation, fields, segment, both periods), so the analyst starts
    from the evidence without the banker restating it -- through the existing
    seeded-thread path, not a new one.
    """
    domain = issue["domain_id"]
    relation = grid.SPEC[domain]["relation"]
    dim = issue["segment"]["dimension"]
    measure_fields = ["ead_sar_mn", "ecl_sar_mn", "stage", "pd_pit_12m",
                      "lgd_pct"]
    questions = [{"question": s["exact_request"], "relation": relation,
                  "required_fields": measure_fields}
                 for s in issue["next_best_questions"]["primary"]
                 if s["required_capability"] == "execute_analysis"]
    m = issue["materiality"]
    return {
        "item_id": issue["issue_id"], "origin": "guided_requires_attention",
        "domain_id": domain, "release_id": issue["release_id"],
        "release_fingerprint": issue["fingerprint"],
        "headline": issue["title"],
        "segment": "" if issue["segment"]["value"] == "whole book"
        else issue["segment"]["value"],
        "segment_dimension": "portfolio" if dim == "portfolio" else dim,
        "reporting_period": issue["evidence"]["period"],
        "comparison_period": issue["evidence"]["prior_period"],
        "reporting_month": issue["evidence"]["period"] if domain == "retail" else "",
        "comparison_month": issue["evidence"]["prior_period"] if domain == "retail" else "",
        "reporting_quarter": issue["evidence"]["period"] if domain == "corporate" else "",
        "comparison_quarter": issue["evidence"]["prior_period"] if domain == "corporate" else "",
        "comparison_basis": "previous published period",
        "metric": issue["metric_id"], "metric_label": issue["metric_name"],
        "issue": issue["interpretation"], "why_it_appeared": (
            f"Rule {issue['detection_rule']['id']} ({RULESET_VERSION}): "
            f"materiality score {issue['score']:.4f}."),
        "movement": m["movement_display"],
        "key_numbers": [
            {"label": "Current", "value": m["level_display"]},
            {"label": "Affected " + issue["entity_plural"],
             "value": f"{m['affected_entities']:,}"},
            {"label": "Affected EAD", "value": fmt(m["affected_ead"], "SAR_mn")},
            {"label": "Affected ECL", "value": fmt(m["affected_ecl"], "SAR_mn")}],
        "evidence": {"metric_ids": issue["evidence"]["metric_ids"],
                     "predicate": issue["evidence"]["predicate"],
                     "breakdown": issue["drivers"]},
        "drilldown": {"relation": relation, "measure_fields": measure_fields,
                      "suggested_questions": questions,
                      "entity_count": m["affected_entities"]},
        "evidence_url": f"/issues/{issue['issue_id']}",
    }


__all__ = ["PATTERNS", "RULESET_VERSION", "detect", "feed", "find", "fmt",
           "fmt_move", "seed_for_thread"]
