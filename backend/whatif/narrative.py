"""
The reading a result needs, written by a model from evidence it cannot exceed.

Why a model at all
------------------
The engine settles what the numbers are. It cannot settle what they MEAN — that
a 38% rise is severe on this book, that the whole of it sits in one sector, that
the mechanism is a change of measurement basis rather than a change in anybody's
riskiness. A composed template can state those facts; it cannot shape them to
the question that was actually asked, and it reads like a form.

So the calculation is deterministic and the explanation is written. That
division is the whole design: the model never computes, and the engine never
narrates.

NO INVENTED NUMBERS
-------------------
The model is handed an EVIDENCE PACKET and nothing else — no tools, no
retrieval, no memory of the book. Every figure it may write is in that packet,
the system prompt says so in those words, and `check` re-reads the finished
prose looking for numbers that are not. A paragraph carrying a figure the
packet does not contain is refused, not published, because a plausible wrong
number in a professional paragraph is the single most expensive failure this
product can have.

Where no model is available
---------------------------
The same evidence is composed deterministically. It is shorter and flatter, and
it is true. A product that goes silent because a provider is down is worse than
one that reads like a form for an afternoon.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

NARRATIVE_VERSION = "1.0.0"

#: How many borrowers, sectors and drivers reach the packet. Enough to explain
#: a movement; not so much that the packet becomes the book.
TOP_N = 12

_SYSTEM = (
    "You are a senior IFRS 9 credit-risk analyst writing the interpretation of "
    "a What-If scenario result inside CreditProbe.\n\n"
    "Your reader is a credit-risk professional or a member of a credit "
    "committee. Write the way one would write to another: direct, specific, "
    "unhedged where the evidence is clear and explicitly uncertain where it is "
    "not. No marketing language. No exclamation marks. No bullet-point "
    "padding. No restating the question back.\n\n"
    "THE EVIDENCE PACKET BELOW IS THE ONLY THING YOU KNOW.\n\n"
    "Every number you write — every amount, percentage, count, ratio, rating, "
    "period, share and version — must appear in that packet. You may round a "
    "figure the packet gives you and you may state a difference between two "
    "figures it gives you. You may NOT estimate, infer, extrapolate or recall "
    "any other number. If you want to say something the packet does not "
    "support, say it qualitatively or do not say it.\n\n"
    "Do not describe a driver the packet does not list. Do not name a borrower "
    "or sector the packet does not name. Do not state a likelihood or a "
    "probability of the scenario occurring — the packet's plausibility "
    "assessment is a comparison against observed history and is not a forecast, "
    "and you must use its own words for the verdict.\n\n"
    "Cover, in this order and in flowing prose rather than headings: what was "
    "asked; what changed in the risk parameters; what happened to staging and "
    "why that matters for the measurement basis; the ECL movement and what "
    "drove it; where the impact concentrates; and what a senior risk "
    "professional should take from it."
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array", "minItems": 2, "maxItems": 6,
            "items": {"type": "string"},
            "description": "Two to five paragraphs of professional prose. "
                           "Every figure must come from the evidence packet.",
        },
        "headline": {
            "type": "string",
            "description": "One sentence a reader could quote.",
        },
        "next_questions": {
            "type": "array", "maxItems": 5,
            "items": {"type": "string"},
            "description": "Questions this particular result makes worth "
                           "asking, phrased as the reader would type them. "
                           "Specific to what happened here — not generic.",
        },
        "used_evidence": {
            "type": "array", "maxItems": 8,
            "items": {"type": "string"},
            "description": "Which parts of the packet the interpretation "
                           "rests on, by their key.",
        },
    },
    "required": ["paragraphs", "headline"],
}


def _round(value: Any, places: int = 4) -> Any:
    try:
        return round(float(value), places)
    except (TypeError, ValueError):
        return value


def _rows(frame: Any, columns: tuple[str, ...], limit: int) -> list[dict[str, Any]]:
    import pandas as pd

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    keep = [c for c in columns if c in frame.columns]
    return frame[keep].head(limit).round(4).to_dict(orient="records")


def packet(result: Any) -> dict[str, Any]:
    """Everything the interpretation may state, and nothing else.

    Assembled from the result the engine produced. Deliberately flat and
    deliberately named: a model given a nested object with ambiguous keys will
    describe the shape of the object.
    """
    import pandas as pd

    summary = dict(getattr(result, "summary", {}) or {})
    context = result.context() if hasattr(result, "context") else {}
    attribution = dict(getattr(result, "attribution", {}) or {})
    frame = getattr(result, "borrowers", None)
    movement = dict(getattr(result, "stage_movement", {}) or {})
    rating_movement = dict(getattr(result, "rating_movement", {}) or {})

    contributors: list[dict[str, Any]] = []
    if isinstance(frame, pd.DataFrame) and "ecl_increase" in frame.columns:
        moved = frame.reindex(
            pd.to_numeric(frame["ecl_increase"], errors="coerce")
            .abs().sort_values(ascending=False).index)
        contributors = _rows(
            moved, ("borrower_id", "display_name", "sector", "opening_rating",
                    "stressed_rating", "stage_baseline", "stage_stressed",
                    "ead", "ecl_baseline", "ecl_stressed", "ecl_increase"),
            TOP_N)

    return {
        "SCENARIO": {
            "period": context.get("period"),
            "population": context.get("population"),
            "population_count": context.get("population_count"),
            "steps": [s.get("interpreted") or s.get("instruction")
                      for s in (context.get("steps") or [])],
            "staging_criteria": context.get("whatif_staging"),
            "staging_version": context.get("whatif_staging_version"),
            "reported_staging": context.get("reported_staging"),
            "methodology": context.get("ecl_methodology"),
            "methodology_version": context.get("ecl_methodology_version"),
            "currency": context.get("currency"),
        },
        "RESULT": {
            "baseline_ecl": _round(summary.get("baseline_ecl"), 2),
            "whatif_ecl": _round(summary.get("stressed_ecl"), 2),
            "absolute_change": _round(summary.get("incremental_ecl"), 2),
            "percentage_change": _round(summary.get("incremental_ecl_pct"), 3),
            "borrowers": int(getattr(result, "population", 0) or 0),
        },
        "PARAMETER_MOVEMENT": {
            k: _round(v, 6) for k, v in
            ((result.factors.to_dict() if getattr(result, "factors", None)
              else {}) or {}).items()
            if isinstance(v, int | float)},
        "DRIVERS": [
            {"driver": d.get("label"), "effect": _round(d.get("effect"), 2),
             "share_pct": _round(d.get("share_pct"), 2),
             "borrowers_moved": d.get("borrowers_moved")}
            for d in (attribution.get("drivers") or [])],
        "MEASUREMENT_BASIS": attribution.get("measurement_basis") or {},
        "MODEL_ADJUSTMENT": attribution.get("model_adjustment"),
        "ATTRIBUTION_RECONCILES": (attribution.get("reconciliation") or {}
                                   ).get("reconciles"),
        "STAGE_MOVEMENT": {
            "moved": movement.get("moved"),
            "deteriorated": movement.get("deteriorated"),
            "cured": movement.get("cured"),
            "stages": movement.get("stages") or [],
        },
        "RATING_MOVEMENT": {
            "moved": rating_movement.get("moved"),
            "note": rating_movement.get("note"),
        },
        "TOP_BORROWERS": contributors,
        "BY_SECTOR": _rows(getattr(result, "by_sector", None),
                           ("label", "borrowers", "exposure", "ecl_baseline",
                            "ecl_stressed", "ecl_increase"), TOP_N),
        "BY_RATING": _rows(getattr(result, "by_rating", None),
                           ("label", "borrowers", "exposure", "ecl_baseline",
                            "ecl_stressed", "ecl_increase"), 20),
        "BY_STAGE": _rows(getattr(result, "by_stage", None),
                          ("label", "borrowers", "exposure", "ecl_baseline",
                           "ecl_stressed", "ecl_increase"), 5),
        "PLAUSIBILITY": {
            k: v for k, v in (getattr(result, "plausibility", {}) or {}).items()
            if k in ("available", "verdict", "because", "driven_by", "window",
                     "statement", "limitation")},
        "ML": {k: v for k, v in (getattr(result, "ml", {}) or {}).items()
               if k in ("model_version", "mean_factor", "fell_back_to_delta",
                        "in_distribution", "out_of_distribution")},
        "WARNINGS": list(getattr(result, "warnings", []) or []),
        "DATA_LIMITATIONS": list(getattr(result, "notes", []) or []),
    }


#: Numbers a paragraph may carry without being in the packet: the small
#: integers of ordinary prose ("one notch", "the two methodologies", "Stage 2",
#: "IFRS 9"), and years, which are periods the packet already names.
_HARMLESS = re.compile(
    r"^(?:[0-9]|1[0-2]|100|19|20[0-9]{2}|1\.0|0\.0)$")
_NUMBER = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def _stated(packet_body: dict[str, Any]) -> set[str]:
    """Every number the packet contains, in every form it could be written."""
    seen: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for value in node.values():
                walk(value)
        elif isinstance(node, list | tuple):
            for value in node:
                walk(value)
        elif isinstance(node, bool):
            return
        elif isinstance(node, int | float):
            value = float(node)
            for places in (0, 1, 2, 3):
                seen.add(f"{round(value, places):.{places}f}".rstrip("0").rstrip("."))
                seen.add(f"{abs(round(value, places)):.{places}f}".rstrip("0").rstrip("."))
            seen.add(str(int(value)) if float(value).is_integer() else str(value))
            seen.add(str(abs(int(value))) if float(value).is_integer() else str(abs(value)))
        elif isinstance(node, str):
            for found in _NUMBER.finditer(node):
                seen.add(found.group(0).replace(",", ""))
    walk(packet_body)
    return {s for s in seen if s}


def check(paragraphs: list[str], packet_body: dict[str, Any]) -> list[str]:
    """Numbers in the prose that are not in the evidence.

    A plausible wrong figure inside a professional paragraph is the most
    expensive failure this product can have: it is quoted, and nothing about
    the sentence says it was invented. So the finished prose is re-read against
    the packet and anything unaccounted for is reported.
    """
    known = _stated(packet_body)
    unknown: list[str] = []
    for paragraph in paragraphs:
        for found in _NUMBER.finditer(paragraph):
            raw = found.group(0).replace(",", "")
            if raw in known or _HARMLESS.match(raw):
                continue
            # A rounded form of a known figure is the same figure.
            try:
                value = float(raw)
            except ValueError:
                continue
            if any(abs(value - float(k)) <= max(abs(value), 1.0) * 0.005
                   for k in known if _is_number(k)):
                continue
            unknown.append(raw)
    return sorted(set(unknown))


def _is_number(text: str) -> bool:
    try:
        float(text)
    except (TypeError, ValueError):
        return False
    return True


def compose(result: Any) -> dict[str, Any]:
    """The reading, without a model. The same claims, flatter."""
    from backend.whatif import run as rn

    body = rn.interpret(result)
    return {
        "paragraphs": [" ".join(body["findings"][:2]),
                       *([" ".join(body["findings"][2:])]
                         if len(body["findings"]) > 2 else [])],
        "headline": body["headline"],
        "next_questions": body["next_questions"],
        "materiality": body["materiality"],
        "written_by": "composed from the result",
    }


def interpret(result: Any) -> dict[str, Any]:
    """What this result means, written from evidence it cannot exceed.

    Returns the prose, the packet it was written from, and — where a model
    wrote it — the verification that every number in the prose was in the
    packet. A paragraph carrying an unaccounted figure is DROPPED and the
    composed reading is used instead: a slightly flatter answer is a much
    smaller problem than a confident wrong one.
    """
    from backend.whatif import run as rn

    evidence = packet(result)
    deterministic = rn.interpret(result)
    body: dict[str, Any] = {
        "version": NARRATIVE_VERSION,
        "materiality": deterministic["materiality"],
        "direction": deterministic["direction"],
        # The composed findings travel with the written reading, always. They
        # are the claims the engine itself makes, and a reader comparing the
        # prose against them is exactly the check this design invites.
        "findings": list(deterministic["findings"]),
        "evidence": evidence,
        "statement": (
            "The engine calculated every figure above. This reading was "
            "written from those figures and from nothing else: the model that "
            "wrote it was given the evidence packet, no tools and no access to "
            "the book, and the finished prose was checked back against the "
            "packet for any number it did not contain."),
    }

    try:
        from backend.llm import get_provider
        from backend.llm import roles as rl

        chosen = rl.role(rl.INTERPRETATION)
        outcome = get_provider().structured(
            system=_SYSTEM,
            prompt=("Write the interpretation of this What-If result.\n\n"
                    "EVIDENCE PACKET:\n"
                    + json.dumps(evidence, indent=2, default=str)),
            schema=_SCHEMA,
            tool_name="interpret_the_result",
            tool_description="Interpret a What-If scenario result using only "
                             "the evidence packet supplied.",
            max_tokens=2400, purpose="interpretation",
            role=rl.INTERPRETATION, model=chosen.model, effort=chosen.effort)
        paragraphs = [str(p).strip() for p in outcome.data.get("paragraphs", [])
                      if str(p).strip()]
        headline = str(outcome.data.get("headline") or "").strip()
        invented = check([*paragraphs, headline], evidence)
        if paragraphs and not invented:
            body.update({
                "paragraphs": paragraphs,
                "headline": headline or deterministic["headline"],
                "next_questions": [str(q) for q in
                                   (outcome.data.get("next_questions") or [])][:5]
                or deterministic["next_questions"],
                "used_evidence": [str(k) for k in
                                  (outcome.data.get("used_evidence") or [])],
                "written_by": outcome.model,
                "verified": True,
            })
            return body
        if invented:
            logger.warning(
                "The interpretation stated figures the evidence packet does "
                "not contain (%s); using the composed reading instead.",
                ", ".join(invented[:8]))
            body["rejected_because"] = (
                "The written interpretation stated figures the evidence did "
                "not contain: " + ", ".join(invented[:8]) + ". It was "
                "discarded rather than shown.")
    except Exception as e:  # noqa: BLE001 - a reading must never cost the result
        logger.info("Composing the interpretation without a model: %s", e)

    composed = compose(result)
    body.update({
        "paragraphs": composed["paragraphs"],
        "headline": composed["headline"],
        "next_questions": composed["next_questions"],
        "written_by": composed["written_by"],
        "verified": True,
    })
    return body


# ------------------------------------------- interpreting a quick analysis

_ANALYSIS_SYSTEM = (
    "You are a senior IFRS 9 credit-risk analyst reading a table CreditProbe "
    "has just computed from the reported Corporate IFRS 9 book, inside a "
    "What-If thread, BEFORE any scenario has been applied.\n\n"
    "Your reader is deciding what to stress. So the useful interpretation is "
    "not a description of the table — they can see the table. It is what the "
    "shape of it means and what it implies for a scenario: where the risk "
    "actually sits, where the concentration is, where the numbers behave "
    "differently from what a credit professional would expect, and which "
    "population is worth shocking.\n\n"
    "THE EVIDENCE PACKET BELOW IS THE ONLY THING YOU KNOW.\n\n"
    "Every number you write must appear in that packet. You may round a figure "
    "it gives you and you may state a difference between two figures it gives "
    "you. You may NOT estimate, infer, extrapolate or recall any other number. "
    "Say anything the packet does not support qualitatively or not at all.\n\n"
    "Nothing has been shocked. Do not describe an impact, a stressed figure or "
    "an ECL movement — there is none. Three to five sentences, in flowing "
    "prose, no headings, no bullets, no restating the question."
)

_ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "paragraphs": {
            "type": "array", "minItems": 1, "maxItems": 3,
            "items": {"type": "string"},
            "description": "One to three short paragraphs. Every figure must "
                           "come from the evidence packet.",
        },
        "headline": {"type": "string",
                     "description": "One sentence a reader could quote."},
        "next_questions": {
            "type": "array", "maxItems": 5, "items": {"type": "string"},
            "description": "What this table makes worth asking next, phrased "
                           "as the reader would type it. Specific to what is "
                           "in the table.",
        },
    },
    "required": ["paragraphs", "headline"],
}


def analysis_packet(body: dict[str, Any]) -> dict[str, Any]:
    """The evidence a reading of a quick analysis may use, and nothing else.

    Deliberately the table itself rather than the book behind it. An
    interpretation that could reach past the table would be able to state a
    figure the reader cannot check against what is on their screen, which is
    the whole failure mode this design exists to prevent.
    """
    if body.get("kind") == "borrowers":
        rows = body.get("rows", [])[:25]
        return {
            "kind": "borrowers",
            "period": body.get("period"),
            "currency": body.get("currency"),
            "population": body.get("population"),
            "ordered_by": body.get("ordered_by"),
            "borrowers_in_population": body.get("borrowers"),
            "rows_shown": body.get("shown"),
            "rows_in_this_packet": len(rows),
            "concentration_pct": body.get("concentration_pct"),
            "rows": rows,
        }
    populated = [r for r in body.get("rows", [])
                 if (r.get("cells", {}).get("borrowers", {}).get("value") or 0) > 0]
    return {
        "kind": "breakdown",
        "period": body.get("period"),
        "currency": body.get("currency"),
        "dimension": body.get("dimension_label"),
        "population": body.get("population"),
        "columns": body.get("columns"),
        "borrowers_in_population": body.get("borrowers"),
        # The counts the composed reading states. A number a reading uses and
        # the packet does not carry is indistinguishable from an invented one
        # to `check()`, which is the correct behaviour — so the packet carries
        # it rather than the check being loosened.
        "rows_in_the_table": len(body.get("rows", [])),
        "populated_rows": len(populated),
        "rows": populated,
        "total": body.get("total"),
        "answer": body.get("answer"),
        "distribution": body.get("distribution"),
        "measurement": body.get("measurement"),
    }


def interpret_analysis(body: dict[str, Any]) -> dict[str, Any]:
    """What a quick-analysis table means, written from the table alone.

    Same discipline as the scenario interpretation: the model is given the
    packet, no tools and no access to the book, and the finished prose is
    re-read against the packet for any number it did not contain. A paragraph
    carrying an unaccounted figure is DROPPED rather than shown.

    When no model is available the reading is composed deterministically. It is
    flatter, and it is still true, which is the right trade.
    """
    evidence = analysis_packet(body)
    composed = compose_analysis(body)
    out: dict[str, Any] = {
        "version": NARRATIVE_VERSION,
        "evidence": evidence,
        "statement": (
            "CreditProbe calculated every figure in the table above from the "
            "reported book. This reading was written from those figures and "
            "from nothing else, and was checked back against them for any "
            "number they do not contain. Nothing has been shocked."),
        **composed,
    }
    try:
        from backend.llm import get_provider
        from backend.llm import roles as rl

        chosen = rl.role(rl.INTERPRETATION)
        outcome = get_provider().structured(
            system=_ANALYSIS_SYSTEM,
            prompt=("Interpret this table for a reader deciding what to "
                    "stress.\n\nEVIDENCE PACKET:\n"
                    + json.dumps(evidence, indent=2, default=str)),
            schema=_ANALYSIS_SCHEMA,
            tool_name="interpret_the_analysis",
            tool_description="Interpret a computed Corporate IFRS 9 breakdown "
                             "using only the evidence packet supplied.",
            max_tokens=1200, purpose="quick_analysis_interpretation",
            role=rl.INTERPRETATION, model=chosen.model, effort=chosen.effort)
        paragraphs = [str(p).strip() for p in outcome.data.get("paragraphs", [])
                      if str(p).strip()]
        headline = str(outcome.data.get("headline") or "").strip()
        invented = check([*paragraphs, headline], evidence)
        if paragraphs and not invented:
            out.update({
                "paragraphs": paragraphs,
                "headline": headline or composed["headline"],
                "findings": composed["findings"],
                "next_questions": [str(q) for q in
                                   (outcome.data.get("next_questions") or [])][:5]
                or composed["next_questions"],
                "written_by": outcome.model,
                "verified": True,
            })
            return out
        if invented:
            logger.warning(
                "The analysis reading stated figures the table does not "
                "contain (%s); using the composed reading instead.",
                ", ".join(invented[:8]))
            out["rejected_because"] = (
                "The written reading stated figures the table did not "
                "contain: " + ", ".join(invented[:8]) + ". It was discarded "
                "rather than shown.")
    except Exception as e:  # noqa: BLE001 - a reading must never cost the table
        logger.info("Composing the analysis reading without a model: %s", e)
    return out


def compose_analysis(body: dict[str, Any]) -> dict[str, Any]:
    """The reading, without a model. The same claims, flatter.

    Every sentence here is a fact read straight off the table, which is why it
    can be shown when the model is unavailable or when its prose failed the
    number check.
    """
    if body.get("kind") == "borrowers":
        rows = body.get("rows", [])
        order = body.get("ordered_by", {})
        first = rows[0] if rows else {}
        sentence = (
            f"{len(rows)} borrower(s) shown, ordered by "
            f"{str(order.get('label', 'ECL')).lower()}. They account for "
            f"{body.get('concentration_pct', 0):.1f}% of the population's "
            f"total." if rows else "No borrower matches that.")
        return {
            "headline": (f"{first.get('name') or first.get('borrower_id')} is "
                         f"the largest by {str(order.get('label', 'ECL')).lower()}."
                         if rows else "Nothing matches that."),
            "paragraphs": [sentence],
            "findings": [sentence],
            "next_questions": ["Show these by sector.",
                               "Which of these are Stage 2?"],
            "written_by": "composed from the table",
            "verified": True,
        }

    rows = [r for r in body.get("rows", [])
            if (r.get("cells", {}).get("borrowers", {}).get("value") or 0) > 0]
    dimension = str(body.get("dimension_label", "")).lower()
    said: list[str] = []
    if rows:
        said.append(
            f"{body.get('borrowers', 0):,} borrower(s) across "
            f"{len(rows)} populated {dimension} value(s) at "
            f"{body.get('period', '')}.")
        largest = max(rows, key=lambda r: r["cells"].get("exposure", {}).get("value") or 0)
        share = largest["cells"].get("exposure", {}).get("share_pct")
        if share is not None:
            said.append(f"{largest['label']} carries the largest exposure at "
                        f"{share:.1f}% of the total.")
        for key in ("applicable_pd", "pit_pd_12m", "lifetime_pd", "lgd"):
            if key not in {c["key"] for c in body.get("columns", [])}:
                continue
            weakest = max(rows, key=lambda r: r["cells"].get(key, {}).get("weighted") or -1)
            value = weakest["cells"].get(key, {}).get("weighted")
            label = next(c["label"] for c in body["columns"] if c["key"] == key)
            if value is not None:
                said.append(f"{weakest['label']} carries the highest "
                            f"exposure-weighted {label} at {value:.2f}%.")
            break
    else:
        said.append("No borrower in the book matches that.")
    if body.get("answer"):
        said.append(str(body["answer"]["sentence"]))
    return {
        "headline": said[0],
        "paragraphs": [" ".join(said)],
        # The claims the calculation itself makes, carried beside the written
        # reading exactly as they are on a scenario result: a reader comparing
        # the prose against them is the check this design invites.
        "findings": said,
        "next_questions": [
            "Split this by Stage.",
            "Show the same table for the previous quarter.",
            "What would be a sensible shock for the weakest of these?",
        ],
        "written_by": "composed from the table",
        "verified": True,
    }


def describe() -> dict[str, Any]:
    """How the interpretation is produced, for the configuration screen."""
    return {
        "version": NARRATIVE_VERSION,
        "evidence_keys": [
            "SCENARIO", "RESULT", "PARAMETER_MOVEMENT", "DRIVERS",
            "MEASUREMENT_BASIS", "MODEL_ADJUSTMENT", "STAGE_MOVEMENT",
            "RATING_MOVEMENT", "TOP_BORROWERS", "BY_SECTOR", "BY_RATING",
            "BY_STAGE", "PLAUSIBILITY", "ML", "WARNINGS", "DATA_LIMITATIONS"],
        "statement": (
            "The engine calculates; the model explains. The model is given an "
            "evidence packet and nothing else — no tools, no retrieval, no "
            "access to the book — and the finished prose is re-read against "
            "the packet. A paragraph carrying a figure the packet does not "
            "contain is discarded rather than shown, because a plausible wrong "
            "number inside a professional paragraph is the most expensive "
            "failure this product can have."),
    }


__all__ = ["NARRATIVE_VERSION", "TOP_N", "check", "compose", "describe",
           "interpret", "packet"]
