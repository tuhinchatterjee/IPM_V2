"""
The interpreter — structured engine results in, English out.

The single rule this module is built around:

    Every figure that appears in a sentence was taken, unchanged, from an engine
    result. The interpreter selects, orders and formats. It never derives.

There is no arithmetic anywhere below. Where a sentence contains a change, that
change is a value the engine already computed and returned (`movement`,
`net_change`, `ecl_increase`). Where a sentence ranks something, the ranking is
a selection from rows the engine already ordered. If the engine did not produce
a number, the interpreter cannot say it — which is precisely why a language
model is not needed here and is not used here in DEMO_MODE.

When a model key IS configured, the model is given only this structured result —
never the underlying rows, and never the data — and is asked to write the same
kind of summary. The figures it may quote are exactly the ones assembled here.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

Number = int | float


@dataclass
class Metric:
    """One headline figure, exactly as the engine reported it."""

    label: str
    value: Any
    unit: str = ""
    change: float | None = None
    change_unit: str = ""
    # "up-is-bad" for risk measures, "up-is-good", or "neutral" for size measures.
    direction: str = "up-is-bad"
    hint: str = ""
    step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label, "value": self.value, "unit": self.unit,
            "change": self.change, "change_unit": self.change_unit,
            "direction": self.direction, "hint": self.hint, "step": self.step,
        }


@dataclass
class Finding:
    """One statement of fact, with the figures behind it attached."""

    text: str
    tone: str = "neutral"  # negative | warning | positive | neutral
    evidence: list[dict[str, Any]] = field(default_factory=list)
    step: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "tone": self.tone, "evidence": self.evidence,
                "step": self.step}


@dataclass
class Narrative:
    summary: str = ""
    findings: list[Finding] = field(default_factory=list)
    metrics: list[Metric] = field(default_factory=list)
    drivers: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "metrics": [m.to_dict() for m in self.metrics],
            "drivers": self.drivers,
            "caveats": self.caveats,
        }


# ---------------------------------------------------------------- formatting


def _n(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def money(value: Any, unit: str = "USD mn") -> str:
    v = _n(value)
    if v is None:
        return "—"
    return f"{v:,.0f} {unit}" if abs(v) >= 100 else f"{v:,.1f} {unit}"


def pct(value: Any, places: int = 2) -> str:
    v = _n(value)
    return "—" if v is None else f"{v:.{places}f}%"


def pp(value: Any, places: int = 2) -> str:
    """A change expressed in percentage points, signed."""
    v = _n(value)
    return "—" if v is None else f"{v:+.{places}f}pp"


def signed_money(value: Any, unit: str = "USD mn") -> str:
    v = _n(value)
    if v is None:
        return "—"
    return f"{v:+,.0f} {unit}" if abs(v) >= 100 else f"{v:+,.1f} {unit}"


def direction_word(value: Any, up: str = "risen", down: str = "fallen",
                   flat: str = "been broadly unchanged") -> str:
    v = _n(value)
    if v is None:
        return flat
    if v > 0:
        return up
    if v < 0:
        return down
    return flat


def tone_for(value: Any, *, up_is_bad: bool = True) -> str:
    v = _n(value)
    if v is None or v == 0:
        return "neutral"
    worse = v > 0 if up_is_bad else v < 0
    return "negative" if worse else "positive"


# ------------------------------------------------------- per-analysis readers
# Each reader receives one executed step and contributes metrics and findings.
# It reads `values` and `rows` and writes sentences. Nothing else.


def _portfolio_summary(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    move = values.get("movement") or {}
    period = values.get("period", "the current period")
    compare = values.get("compare_period", "the prior period")

    metrics = [
        Metric("Total EAD", values.get("total_ead"), "USD mn", _n(move.get("total_ead")),
               "USD mn", "neutral", f"vs {compare}", index),
        Metric("Total ECL", values.get("total_ecl"), "USD mn", _n(move.get("total_ecl")),
               "USD mn", "up-is-bad", f"vs {compare}", index),
        Metric("ECL coverage", values.get("ecl_coverage_pct"), "%",
               _n(move.get("ecl_coverage_pct")), "pp", "up-is-bad", f"vs {compare}", index),
        Metric("Stage 2 share", values.get("stage2_pct"), "%", _n(move.get("stage2_pct")),
               "pp", "up-is-bad", f"vs {compare}", index),
        Metric("NPL ratio", values.get("npl_ratio_pct"), "%", _n(move.get("npl_ratio_pct")),
               "pp", "up-is-bad", f"vs {compare}", index),
    ]

    findings: list[Finding] = []
    ecl_move = _n(move.get("total_ecl"))
    if ecl_move is not None:
        findings.append(Finding(
            f"Expected credit loss stands at {money(values.get('total_ecl'))} in {period}, "
            f"{signed_money(ecl_move)} against {compare}, taking coverage to "
            f"{pct(values.get('ecl_coverage_pct'))} ({pp(move.get('ecl_coverage_pct'))}).",
            tone_for(ecl_move),
            [{"label": "Total ECL", "value": values.get("total_ecl"), "unit": "USD mn"},
             {"label": "ECL coverage", "value": values.get("ecl_coverage_pct"), "unit": "%"}],
            index,
        ))
    s2 = _n(move.get("stage2_ead"))
    if s2 is not None:
        findings.append(Finding(
            f"Stage 2 exposure is {money(values.get('stage2_ead'))}, "
            f"{pct(values.get('stage2_pct'))} of the book and {signed_money(s2)} on "
            f"{compare}.",
            tone_for(s2),
            [{"label": "Stage 2 EAD", "value": values.get("stage2_ead"), "unit": "USD mn"},
             {"label": "Stage 2 share", "value": values.get("stage2_pct"), "unit": "%"}],
            index,
        ))
    breaches = _n(values.get("appetite_breach_count"))
    if breaches:
        findings.append(Finding(
            f"{int(breaches)} exposures breach the declared risk appetite, and "
            f"{money(values.get('watchlist_ead'))} sits on the watchlist.",
            "warning",
            [{"label": "Watchlist EAD", "value": values.get("watchlist_ead"), "unit": "USD mn"}],
            index,
        ))
    return metrics, findings


def _stage_distribution(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    by_stage = {int(r.get("ifrs9_stage", 0)): r for r in rows if r.get("ifrs9_stage") is not None}
    metrics: list[Metric] = []
    for stage in (1, 2, 3):
        row = by_stage.get(stage)
        if row:
            metrics.append(Metric(f"Stage {stage} EAD", row.get("ead"), "USD mn",
                                  None, "", "neutral",
                                  f"{pct(row.get('ead_pct'), 1)} of the book", index))
    findings: list[Finding] = []
    s2, s3 = by_stage.get(2), by_stage.get(3)
    if s2 and (_n(s2.get("ead")) or 0) > 0:
        findings.append(Finding(
            f"Stage 2 holds {money(s2.get('ead'))} — {pct(s2.get('ead_pct'), 1)} of exposure — "
            f"carried at {pct(s2.get('coverage_pct'))} coverage across "
            f"{s2.get('borrower_count', '—')} borrowers.",
            "warning",
            [{"label": "Stage 2 coverage", "value": s2.get("coverage_pct"), "unit": "%"}],
            index,
        ))
    if s3 and (_n(s3.get("ead")) or 0) > 0:
        findings.append(Finding(
            f"Stage 3 holds {money(s3.get('ead'))} at {pct(s3.get('coverage_pct'))} coverage.",
            "negative",
            [{"label": "Stage 3 coverage", "value": s3.get("coverage_pct"), "unit": "%"}],
            index,
        ))
    return metrics, findings


def _sector_concentration(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    dimension = str(values.get("dimension", "sector"))
    metrics = [
        Metric("Largest 5 share", values.get("top_5_pct"), "%", None, "", "up-is-bad",
               f"of total exposure by {dimension.replace('_', ' ')}", index),
        Metric("Herfindahl index", values.get("hhi"), "", None, "", "up-is-bad",
               "concentration score", index),
    ]
    findings: list[Finding] = []
    if rows:
        top = rows[0]
        findings.append(Finding(
            f"{top.get(dimension, 'The largest group')} is the largest concentration at "
            f"{money(top.get('ead'))}, {pct(top.get('ead_pct'), 1)} of the book, carried at "
            f"{pct(top.get('coverage_pct'))} coverage.",
            "warning" if (_n(top.get("ead_pct")) or 0) >= 15 else "neutral",
            [{"label": "Exposure", "value": top.get("ead"), "unit": "USD mn"},
             {"label": "Share", "value": top.get("ead_pct"), "unit": "%"}],
            index,
        ))
        findings.append(Finding(
            f"The five largest groups account for {pct(values.get('top_5_pct'), 1)} of exposure "
            f"across {values.get('group_count', '—')} {dimension.replace('_', ' ')}s.",
            "neutral", [], index,
        ))
    return metrics, findings


def _portfolio_trend(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    change = values.get("change") or {}
    first, last = values.get("first_period"), values.get("last_period")
    metrics = [
        Metric("Coverage change", change.get("ecl_coverage_pct"), "pp", None, "", "up-is-bad",
               f"{first} to {last}", index),
        Metric("Stage 2 share change", change.get("stage2_pct"), "pp", None, "", "up-is-bad",
               f"{first} to {last}", index),
    ]
    findings: list[Finding] = []
    if rows:
        cov = _n(change.get("ecl_coverage_pct"))
        findings.append(Finding(
            f"Across {len(rows)} reporting periods from {first} to {last}, ECL coverage has "
            f"{direction_word(cov)} by {pp(cov)} and the Stage 2 share by "
            f"{pp(change.get('stage2_pct'))}.",
            tone_for(cov),
            [{"label": "Periods", "value": len(rows), "unit": ""}],
            index,
        ))
    return metrics, findings


def _migration(values: dict, rows: list[dict], index: int, *,
               subject: str) -> tuple[list[Metric], list[Finding]]:
    move = values.get("movement") or {}
    basis = "exposure" if values.get("basis") == "ead" else "borrower count"
    unit = "USD mn" if values.get("basis") == "ead" else ""
    frm, to = values.get("from_period"), values.get("to_period")
    metrics = [
        Metric("Deteriorated", move.get("deteriorated"), unit, None, "", "up-is-bad",
               f"{pct(move.get('deteriorated_pct'), 1)} of {basis}", index),
        Metric("Stable", move.get("stable"), unit, None, "", "neutral",
               pct(move.get("stable_pct"), 1), index),
        Metric("Improved", move.get("improved"), unit, None, "", "up-is-good",
               pct(move.get("improved_pct"), 1), index),
    ]
    findings = [Finding(
        f"Between {frm} and {to}, {money(move.get('deteriorated'), unit) if unit else move.get('deteriorated')} "
        f"of {basis} — {pct(move.get('deteriorated_pct'), 1)} — {subject}, against "
        f"{pct(move.get('improved_pct'), 1)} that improved.",
        tone_for(_n(move.get("deteriorated_pct"))),
        [{"label": "Deteriorated", "value": move.get("deteriorated"), "unit": unit},
         {"label": "Improved", "value": move.get("improved"), "unit": unit}],
        index,
    )]
    cover = values.get("coverage") or {}
    if _n(cover.get("exits")) or _n(cover.get("entries")):
        findings.append(Finding(
            f"{cover.get('matched', '—')} facilities were present in both periods; "
            f"{cover.get('exits', 0)} left the book and {cover.get('entries', 0)} were new, "
            "and are excluded from the migration.",
            "neutral", [], index,
        ))
    cure = _n(move.get("cure_rate_pct"))
    if cure is not None:
        findings.append(Finding(
            f"{pct(cure, 1)} of opening arrears cured back to a better bucket.",
            "positive" if cure > 0 else "neutral", [], index,
        ))
    return metrics, findings


def _rating_transition(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    move = values.get("movement") or {}
    metrics = [
        Metric("Downgraded", move.get("downgraded_pct"), "%", None, "", "up-is-bad",
               "of opening exposure", index),
        Metric("Unchanged", move.get("stable_pct"), "%", None, "", "neutral", "", index),
        Metric("Upgraded", move.get("upgraded_pct"), "%", None, "", "up-is-good", "", index),
    ]
    basis = "opening exposure" if values.get("basis") == "ead" else "borrowers"
    findings = [Finding(
        f"Over {values.get('interval', 'the interval')}, "
        f"{pct(move.get('downgraded_pct'), 1)} of {basis} was downgraded and "
        f"{pct(move.get('upgraded_pct'), 1)} upgraded; {pct(move.get('stable_pct'), 1)} held "
        "its grade.",
        tone_for(_n(move.get("downgraded_pct"))),
        [{"label": "Downgraded", "value": move.get("downgraded_pct"), "unit": "%"}],
        index,
    )]
    return metrics, findings


def _ecl_movement(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    net = _n(values.get("net_change"))
    metrics = [
        Metric("Opening ECL", values.get("opening_ecl"), "USD mn", None, "", "neutral",
               str(values.get("from_period", "")), index),
        Metric("Closing ECL", values.get("closing_ecl"), "USD mn", net, "USD mn", "up-is-bad",
               str(values.get("to_period", "")), index),
    ]
    findings = [Finding(
        f"Expected credit loss moved from {money(values.get('opening_ecl'))} to "
        f"{money(values.get('closing_ecl'))} between {values.get('from_period')} and "
        f"{values.get('to_period')}, a net {signed_money(net)}.",
        tone_for(net),
        [{"label": "Net change", "value": values.get("net_change"), "unit": "USD mn"}],
        index,
    )]
    breakdown = [b for b in (values.get("breakdown") or []) if isinstance(b, dict)]
    if breakdown:
        group = values.get("group_by", "sector")
        worst = breakdown[0]
        findings.append(Finding(
            f"{worst.get(group, 'The largest contributor')} contributed the most, "
            f"{signed_money(worst.get('ecl_change'))} of the movement.",
            tone_for(_n(worst.get("ecl_change"))),
            [{"label": str(worst.get(group, "")), "value": worst.get("ecl_change"),
              "unit": "USD mn"}],
            index,
        ))
    return metrics, findings


def _top_deteriorating(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    metrics = [
        Metric("Borrowers deteriorated", values.get("deteriorated_count"), "", None, "",
               "up-is-bad", f"of {values.get('borrowers_compared', '—')} compared", index),
        Metric("ECL increase from these", values.get("total_ecl_increase"), "USD mn", None, "",
               "up-is-bad", "aggregate across deteriorating borrowers", index),
    ]
    findings = [Finding(
        f"{values.get('deteriorated_count', '—')} of "
        f"{values.get('borrowers_compared', '—')} borrowers deteriorated between "
        f"{values.get('from_period')} and {values.get('to_period')}, adding "
        f"{money(values.get('total_ecl_increase'))} of expected credit loss.",
        "negative",
        [{"label": "Deteriorated", "value": values.get("deteriorated_count"), "unit": ""}],
        index,
    )]
    if rows:
        top = rows[0]
        findings.append(Finding(
            f"{top.get('borrower_name', 'The most affected borrower')} "
            f"({top.get('sector', '—')}) is the most affected: "
            f"{money(top.get('ead'))} of exposure, ECL "
            f"{signed_money(top.get('ecl_change'))}. {top.get('reasons', '')}".strip(),
            "negative",
            [{"label": "Exposure", "value": top.get("ead"), "unit": "USD mn"},
             {"label": "ECL change", "value": top.get("ecl_change"), "unit": "USD mn"}],
            index,
        ))
    return metrics, findings


def _stress(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    scope = values.get("sector") or "the whole portfolio"
    metrics = [
        Metric("Base ECL", values.get("base_ecl"), "USD mn", None, "", "neutral",
               "as reported", index),
        Metric("Stressed ECL", values.get("stressed_ecl"), "USD mn",
               _n(values.get("ecl_increase")), "USD mn", "up-is-bad",
               str(values.get("scenario_label", "")), index),
        Metric("Coverage under stress", values.get("stressed_coverage_pct"), "%", None, "",
               "up-is-bad", f"from {pct(values.get('base_coverage_pct'))}", index),
    ]
    findings = [Finding(
        f"Under the {str(values.get('scenario_label', 'scenario')).lower()} applied to {scope}, "
        f"expected credit loss rises from {money(values.get('base_ecl'))} to "
        f"{money(values.get('stressed_ecl'))} — {signed_money(values.get('ecl_increase'))}, "
        f"{pct(values.get('ecl_increase_pct'), 1)} above the reported position — and coverage "
        f"moves to {pct(values.get('stressed_coverage_pct'))}.",
        "negative",
        [{"label": "Incremental ECL", "value": values.get("ecl_increase"), "unit": "USD mn"}],
        index,
    )]
    shocks = values.get("shocks") or {}
    if shocks:
        findings.append(Finding(
            f"Shocks applied: PD ×{shocks.get('pd_multiplier', '—')}, LGD "
            f"{pp(shocks.get('lgd_uplift_pp'), 1)}, EAD "
            f"{pp(shocks.get('ead_uplift_pct'), 1)}, Stage 2 migration "
            f"{pct(shocks.get('stage2_migration_pct'), 1)}.",
            "neutral", [], index,
        ))
    by_sector = [s for s in (values.get("by_sector") or []) if isinstance(s, dict)]
    if by_sector:
        worst = by_sector[0]
        findings.append(Finding(
            f"{worst.get('sector', 'The largest contributor')} absorbs the most of the "
            f"increase, {signed_money(worst.get('ecl_increase'))} on "
            f"{money(worst.get('ead'))} of exposure.",
            "warning", [], index,
        ))
    return metrics, findings


def _watchlist(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    metrics = [
        Metric("Facilities above threshold", values.get("matched"), "", None, "", "up-is-bad",
               f"utilisation over {pct(values.get('threshold_pct'), 0)}", index),
        Metric("Exposure involved", values.get("total_ead"), "USD mn", None, "", "neutral",
               "", index),
    ]
    findings = [Finding(
        f"{values.get('matched', '—')} facilities are drawn above "
        f"{pct(values.get('threshold_pct'), 0)} of their committed limit, involving "
        f"{money(values.get('total_ead'))} of exposure.",
        "warning" if _n(values.get("matched")) else "neutral", [], index,
    )]
    return metrics, findings


READERS = {
    "portfolio_summary": _portfolio_summary,
    "stage_distribution": _stage_distribution,
    "sector_concentration": _sector_concentration,
    "portfolio_trend": _portfolio_trend,
    "stage_migration": lambda v, r, i: _migration(v, r, i, subject="migrated to a worse stage"),
    "dpd_migration": lambda v, r, i: _migration(v, r, i, subject="moved to a worse arrears bucket"),
    "rating_transition_matrix": _rating_transition,
    "ecl_movement": _ecl_movement,
    "top_deteriorating_borrowers": _top_deteriorating,
    "stress_scenario_basic": _stress,
    "high_utilisation_watchlist": _watchlist,
}


# --------------------------------------------------------------- assembly


def _drivers(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The named contributors behind the movement, taken from engine output.

    Not recomputed and not re-ranked — the engine already returned these ordered
    by contribution. This selects the top few and labels them.
    """
    for index, step in enumerate(steps):
        values = (step.get("result") or {}).get("values") or {}
        rows = (step.get("result") or {}).get("rows") or []

        if step.get("analysis_id") == "ecl_movement":
            group = values.get("group_by", "sector")
            out = []
            for entry in (values.get("breakdown") or [])[:5]:
                if not isinstance(entry, dict):
                    continue
                out.append({"name": str(entry.get(group, "—")),
                            "value": entry.get("ecl_change"), "unit": "USD mn",
                            "measure": "ECL movement", "step": index})
            if out:
                return out

        if step.get("analysis_id") == "top_deteriorating_borrowers" and rows:
            return [
                {"name": str(r.get("borrower_name", "—")), "value": r.get("ecl_change"),
                 "unit": "USD mn", "measure": "ECL movement",
                 "detail": str(r.get("reasons", "")), "step": index}
                for r in rows[:5]
            ]

        if step.get("analysis_id") == "sector_concentration" and rows:
            dimension = values.get("dimension", "sector")
            return [
                {"name": str(r.get(dimension, "—")), "value": r.get("ead"), "unit": "USD mn",
                 "measure": "Exposure", "step": index}
                for r in rows[:5]
            ]
    return []


def _summary_sentence(question: str, intent: str, findings: list[Finding]) -> str:
    """The executive summary: the two most material findings, in order.

    Deliberately short. An executive summary that restates every finding is not
    a summary, and the findings are directly below it.
    """
    if not findings:
        return (
            "The analyses ran, but returned no figures to summarise. This usually means "
            "the filters selected no exposure for the requested period."
        )
        # A blank summary would read as a failure of nerve rather than of data.
    # The lead sentence comes from the first step. The planner put that analysis
    # first because it is the one that answers the question, and second-guessing
    # it here would let a louder but less relevant figure open the summary.
    first_step = min(f.step for f in findings)
    # Within a step, the readers above emit their headline finding first, so the
    # order is already the right one and is not re-sorted here.
    lead = next(f for f in findings if f.step == first_step)

    # The second sentence must add something: a figure the first did not quote,
    # and a different opening. Candidates are taken in the order the readers
    # emitted them, which is deliberate — a step's driver finding follows its
    # headline finding, and that pairing is usually the summary you want.
    quoted = {f"{e.get('value')}" for e in lead.evidence}
    support = None
    for finding in findings:
        if finding is lead:
            continue
        figures = {f"{e.get('value')}" for e in finding.evidence}
        if figures and figures <= quoted:
            continue
        if _opening(finding.text) == _opening(lead.text):
            continue
        # Two sentences starting on the same subject ("Stage 2 holds…",
        # "Stage 3 holds…") is a list, not a summary.
        if _subject(finding.text) == _subject(lead.text):
            continue
        support = finding
        break

    return " ".join(f.text for f in ([lead, support] if support else [lead]))


def _opening(text: str) -> str:
    return " ".join(str(text).lower().split()[:3])


def _subject(text: str) -> str:
    return str(text).lower().split()[0] if text.split() else ""


def build_narrative(question: str, intent: str, steps: list[dict[str, Any]]) -> Narrative:
    """Assemble the narrative for an executed investigation.

    `steps` are executed steps: {"analysis_id", "result": {"values","rows","warnings"}}.
    """
    metrics: list[Metric] = []
    findings: list[Finding] = []
    caveats: list[str] = []

    for index, step in enumerate(steps):
        if step.get("status") != "succeeded":
            caveats.append(
                f"{step.get('title') or step.get('analysis_id')} could not be completed: "
                f"{step.get('error') or 'unknown reason'}."
            )
            continue
        result = step.get("result") or {}
        values = result.get("values") or {}
        rows = result.get("rows") or []
        reader = READERS.get(str(step.get("analysis_id")))
        if reader is None:
            continue
        try:
            step_metrics, step_findings = reader(values, rows, index)
        except Exception as e:  # pragma: no cover - a narrative must never break a result
            logger.warning("Interpreter failed on %s: %s", step.get("analysis_id"), e)
            continue
        metrics.extend(step_metrics)
        findings.extend(step_findings)
        for warning in result.get("warnings") or []:
            caveats.append(str(warning))

    # Keep the first occurrence of each headline label: several analyses report
    # total exposure, and a briefing that says it three times reads as noise.
    seen: set[str] = set()
    unique_metrics = []
    for metric in metrics:
        if metric.label in seen:
            continue
        seen.add(metric.label)
        unique_metrics.append(metric)

    return Narrative(
        summary=_summary_sentence(question, intent, findings),
        findings=findings,
        metrics=unique_metrics[:6],
        drivers=_drivers(steps),
        caveats=list(dict.fromkeys(caveats))[:6],
    )


__all__ = ["Finding", "Metric", "Narrative", "build_narrative"]
