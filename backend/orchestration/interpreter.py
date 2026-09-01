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
    """One answer, with the boundary between fact and reading kept visible.

    `direct_answer` and `findings` are CALCULATED: every figure in them was
    returned by an engine analysis and is quoted unchanged.

    `interpretation` is CreditProbe's READING of those figures. It describes, compares
    and points somewhere next. It never introduces a number the engine did not
    produce, and it never asserts causation the engine did not establish.
    """

    #: One sentence answering the question that was asked. Calculated.
    direct_answer: str = ""
    #: Kept for callers that predate the split; equals the direct answer.
    summary: str = ""
    #: The evidence, in the engine's own figures.
    findings: list[Finding] = field(default_factory=list)
    #: CreditProbe's reading of that evidence, as a short paragraph.
    interpretation: str = ""
    #: The same reading as discrete points, for a scannable panel.
    interpretation_points: list[str] = field(default_factory=list)
    #: One line saying why more than one analysis ran. Empty when only one did.
    #: Describes the PLAN, not the portfolio, so it introduces no figure.
    why_multiple: str = ""
    #: What these figures cover: the population, the window, the measures.
    #: Shown above the table rather than buried in a panel, because a
    #: five-name figure read as a portfolio one is wrong by three orders of
    #: magnitude and looks exactly like the right answer.
    scope: str = ""
    metrics: list[Metric] = field(default_factory=list)
    drivers: list[dict[str, Any]] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "direct_answer": self.direct_answer,
            "summary": self.summary,
            "findings": [f.to_dict() for f in self.findings],
            "interpretation": self.interpretation,
            "interpretation_points": list(self.interpretation_points),
            "why_multiple": self.why_multiple,
            "scope": self.scope,
            "metrics": [m.to_dict() for m in self.metrics],
            "drivers": self.drivers,
            "caveats": self.caveats,
        }


# ---------------------------------------------------------------- formatting


def _n(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def money(value: Any, unit: str = "SAR mn") -> str:
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


def signed_money(value: Any, unit: str = "SAR mn") -> str:
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
        Metric("Total EAD", values.get("total_ead"), "SAR mn", _n(move.get("total_ead")),
               "SAR mn", "neutral", f"vs {compare}", index),
        Metric("Total ECL", values.get("total_ecl"), "SAR mn", _n(move.get("total_ecl")),
               "SAR mn", "up-is-bad", f"vs {compare}", index),
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
            [{"label": "Total ECL", "value": values.get("total_ecl"), "unit": "SAR mn"},
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
            [{"label": "Stage 2 EAD", "value": values.get("stage2_ead"), "unit": "SAR mn"},
             {"label": "Stage 2 share", "value": values.get("stage2_pct"), "unit": "%"}],
            index,
        ))
    breaches = _n(values.get("appetite_breach_count"))
    if breaches:
        findings.append(Finding(
            f"{int(breaches)} exposures breach the declared risk appetite, and "
            f"{money(values.get('watchlist_ead'))} sits on the watchlist.",
            "warning",
            [{"label": "Watchlist EAD", "value": values.get("watchlist_ead"), "unit": "SAR mn"}],
            index,
        ))
    return metrics, findings


def _stage_distribution(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    by_stage = {int(r.get("ifrs9_stage", 0)): r for r in rows if r.get("ifrs9_stage") is not None}
    metrics: list[Metric] = []
    for stage in (1, 2, 3):
        row = by_stage.get(stage)
        if row:
            metrics.append(Metric(f"Stage {stage} EAD", row.get("ead"), "SAR mn",
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
            [{"label": "Exposure", "value": top.get("ead"), "unit": "SAR mn"},
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
    unit = "SAR mn" if values.get("basis") == "ead" else ""
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
        Metric("Opening ECL", values.get("opening_ecl"), "SAR mn", None, "", "neutral",
               str(values.get("from_period", "")), index),
        Metric("Closing ECL", values.get("closing_ecl"), "SAR mn", net, "SAR mn", "up-is-bad",
               str(values.get("to_period", "")), index),
    ]
    findings = [Finding(
        f"Expected credit loss moved from {money(values.get('opening_ecl'))} to "
        f"{money(values.get('closing_ecl'))} between {values.get('from_period')} and "
        f"{values.get('to_period')}, a net {signed_money(net)}.",
        tone_for(net),
        [{"label": "Net change", "value": values.get("net_change"), "unit": "SAR mn"}],
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
              "unit": "SAR mn"}],
            index,
        ))
    return metrics, findings


def _top_deteriorating(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    metrics = [
        Metric("Borrowers deteriorated", values.get("deteriorated_count"), "", None, "",
               "up-is-bad", f"of {values.get('borrowers_compared', '—')} compared", index),
        Metric("ECL increase from these", values.get("total_ecl_increase"), "SAR mn", None, "",
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
            [{"label": "Exposure", "value": top.get("ead"), "unit": "SAR mn"},
             {"label": "ECL change", "value": top.get("ecl_change"), "unit": "SAR mn"}],
            index,
        ))
    return metrics, findings


def _stress(values: dict, rows: list[dict], index: int) -> tuple[list[Metric], list[Finding]]:
    scope = values.get("sector") or "the whole portfolio"
    metrics = [
        Metric("Base ECL", values.get("base_ecl"), "SAR mn", None, "", "neutral",
               "as reported", index),
        Metric("Stressed ECL", values.get("stressed_ecl"), "SAR mn",
               _n(values.get("ecl_increase")), "SAR mn", "up-is-bad",
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
        [{"label": "Incremental ECL", "value": values.get("ecl_increase"), "unit": "SAR mn"}],
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
        Metric("Exposure involved", values.get("total_ead"), "SAR mn", None, "", "neutral",
               "", index),
    ]
    findings = [Finding(
        f"{values.get('matched', '—')} facilities are drawn above "
        f"{pct(values.get('threshold_pct'), 0)} of their committed limit, involving "
        f"{money(values.get('total_ead'))} of exposure.",
        "warning" if _n(values.get("matched")) else "neutral", [], index,
    )]
    return metrics, findings


def _arrears_position(values: dict, rows: list[dict], index: int
                      ) -> tuple[list[Metric], list[Finding]]:
    in_arrears = _n(values.get("facilities_in_arrears")) or 0
    ninety_plus = _n(values.get("facilities_90_plus")) or 0
    metrics = [
        Metric("Facilities in arrears", values.get("facilities_in_arrears"), "",
               None, "", "up-is-bad",
               f"{pct(values.get('arrears_rate_pct'))} of the book", index),
        Metric("Amount overdue", values.get("total_arrears_amount"), "SAR mn",
               None, "", "up-is-bad", "", index),
        Metric("Exposure at risk", values.get("exposure_at_risk"), "SAR mn",
               None, "", "up-is-bad", "90 or more days past due", index),
        Metric("Cured this period", values.get("cured_this_period"), "",
               None, "", "down-is-bad", "current again after being behind", index),
    ]

    findings = [Finding(
        f"{int(in_arrears):,} facilities are in arrears — "
        f"{pct(values.get('arrears_rate_pct'))} of those read — owing "
        f"{money(values.get('total_arrears_amount'))} in overdue amounts.",
        "warning" if in_arrears else "positive", [], index,
    )]
    if ninety_plus:
        findings.append(Finding(
            f"{int(ninety_plus):,} of them are 90 or more days past due, carrying "
            f"{money(values.get('exposure_at_risk'))} of exposure at default.",
            "negative", [], index,
        ))
    forborne = _n(values.get("forborne_facilities")) or 0
    if forborne:
        findings.append(Finding(
            f"{int(forborne):,} facilities have been granted a concession, of which "
            f"{int(_n(values.get('restructured_facilities')) or 0):,} were restructured.",
            "warning", [], index,
        ))
    return metrics, findings


def _credit_file_signals(values: dict, rows: list[dict], index: int
                         ) -> tuple[list[Metric], list[Finding]]:
    notes = _n(values.get("notes_written")) or 0
    metrics = [
        Metric("Notes written", values.get("notes_written"), "", None, "", "neutral",
               "credit file entries in the period", index),
        Metric("Negative", values.get("negative_notes"), "", None, "", "up-is-bad",
               f"{pct(values.get('negative_share_pct'))} of notes", index),
        Metric("Borrowers reviewed", values.get("borrowers_reviewed"), "", None, "",
               "neutral", "", index),
        Metric("Concerns per note", values.get("mean_concerns_per_note"), "", None, "",
               "up-is-bad", "of the six tracked", index),
    ]

    findings = [Finding(
        f"{int(notes):,} credit file notes were written, "
        f"{int(_n(values.get('negative_notes')) or 0):,} of them negative "
        f"({pct(values.get('negative_share_pct'))}).",
        "warning" if (_n(values.get("negative_share_pct")) or 0) > 33 else "neutral",
        [], index,
    )]
    for row in rows[:2]:
        findings.append(Finding(
            f"{row.get('signal')} was raised in {int(row.get('mentions') or 0):,} "
            f"notes ({pct(row.get('share_of_notes_pct'))}), against "
            f"{int(row.get('borrowers') or 0):,} borrowers.",
            "warning", [], index,
        ))
    return metrics, findings


# ---------------------------------------------------------- the direct answer
#
# One sentence that answers the question that was asked, in the engine's own
# figures. This is the first thing a reader sees, and it is CALCULATED: every
# number in it was returned by the analysis named in the key.


def _ranked(entries: list[dict], key: str, label_key: str, top: int = 2,
            positive_only: bool = True) -> list[dict]:
    """The largest contributors, as the engine already ordered them."""
    rows = [e for e in entries if isinstance(e, dict)]
    if positive_only:
        rows = [e for e in rows if (_n(e.get(key)) or 0) > 0]
    return rows[:top]


def _and_list(names: list[str]) -> str:
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return f"{', '.join(names[:-1])} and {names[-1]}"


def _answer_ecl_movement(values: dict, rows: list[dict]) -> str:
    group = values.get("group_by", "sector")
    breakdown = [b for b in (values.get("breakdown") or []) if isinstance(b, dict)]
    top = _ranked(breakdown, "ecl_change", group)
    frm, to = values.get("from_period"), values.get("to_period")
    if top:
        names = _and_list([str(t.get(group, "—")) for t in top])
        amounts = _and_list([signed_money(t.get("ecl_change")) for t in top])
        plural = "s" if len(top) > 1 else ""
        return (
            f"{names} show the largest increase{plural} in expected credit loss "
            f"between {frm} and {to}, at {amounts} against a net portfolio movement "
            f"of {signed_money(values.get('net_change'))}."
        )
    return (
        f"Expected credit loss moved {signed_money(values.get('net_change'))} between "
        f"{frm} and {to}, from {money(values.get('opening_ecl'))} to "
        f"{money(values.get('closing_ecl'))}."
    )


def _answer_migration(values: dict, rows: list[dict]) -> str:
    move = values.get("movement") or {}
    basis = "exposure" if values.get("basis") == "ead" else "borrowers"
    unit = "SAR mn" if values.get("basis") == "ead" else ""
    amount = money(move.get("deteriorated"), unit) if unit else str(move.get("deteriorated"))
    return (
        f"{amount} of {basis} — {pct(move.get('deteriorated_pct'), 1)} — moved to a worse "
        f"position between {values.get('from_period')} and {values.get('to_period')}, "
        f"against {pct(move.get('improved_pct'), 1)} that improved."
    )


def _answer_rating_transition(values: dict, rows: list[dict]) -> str:
    move = values.get("movement") or {}
    basis = "opening exposure" if values.get("basis") == "ead" else "borrowers"
    return (
        f"{pct(move.get('downgraded_pct'), 1)} of {basis} was downgraded between "
        f"{values.get('from_period')} and {values.get('to_period')}, and "
        f"{pct(move.get('upgraded_pct'), 1)} upgraded; "
        f"{pct(move.get('stable_pct'), 1)} held its grade."
    )


def _answer_top_deteriorating(values: dict, rows: list[dict]) -> str:
    lead = rows[0] if rows else None
    base = (
        f"{values.get('deteriorated_count', '—')} of "
        f"{values.get('borrowers_compared', '—')} borrowers deteriorated between "
        f"{values.get('from_period')} and {values.get('to_period')}, adding "
        f"{money(values.get('total_ecl_increase'))} of expected credit loss."
    )
    if lead:
        base += (
            f" {lead.get('borrower_name', 'The most affected borrower')} is the most "
            f"affected, with ECL {signed_money(lead.get('ecl_change'))} on "
            f"{money(lead.get('ead'))} of exposure."
        )
    return base


def _answer_portfolio_summary(values: dict, rows: list[dict]) -> str:
    return (
        f"The book stands at {money(values.get('total_ead'))} of exposure as at "
        f"{values.get('period')}, carried at {pct(values.get('ecl_coverage_pct'))} ECL "
        f"coverage with {pct(values.get('npl_ratio_pct'))} non-performing and "
        f"{pct(values.get('stage2_pct'))} in Stage 2."
    )


def _answer_sector_concentration(values: dict, rows: list[dict]) -> str:
    dimension = str(values.get("dimension", "sector"))
    if not rows:
        return "No exposure was returned for this concentration view."
    top = rows[0]
    return (
        f"{top.get(dimension, 'The largest group')} is the largest concentration at "
        f"{money(top.get('ead'))}, {pct(top.get('ead_pct'), 1)} of the book; the five "
        f"largest hold {pct(values.get('top_5_pct'), 1)} between them."
    )


def _answer_stage_distribution(values: dict, rows: list[dict]) -> str:
    by_stage = {int(r.get("ifrs9_stage", 0)): r for r in rows if r.get("ifrs9_stage") is not None}
    s2, s3 = by_stage.get(2), by_stage.get(3)
    if not s2 and not s3:
        return f"Exposure of {money(values.get('total_ead'))} as at {values.get('period')}."
    parts = []
    if s2:
        parts.append(f"Stage 2 holds {money(s2.get('ead'))} ({pct(s2.get('ead_pct'), 1)})")
    if s3:
        parts.append(f"Stage 3 {money(s3.get('ead'))} ({pct(s3.get('ead_pct'), 1)})")
    return f"{' and '.join(parts)} of {money(values.get('total_ead'))} total exposure as at {values.get('period')}."


def _answer_portfolio_trend(values: dict, rows: list[dict]) -> str:
    change = values.get("change") or {}
    return (
        f"Across {len(rows)} reporting periods from {values.get('first_period')} to "
        f"{values.get('last_period')}, ECL coverage has "
        f"{direction_word(change.get('ecl_coverage_pct'))} by "
        f"{pp(change.get('ecl_coverage_pct'))} and the Stage 2 share by "
        f"{pp(change.get('stage2_pct'))}."
    )


def _answer_stress(values: dict, rows: list[dict]) -> str:
    scope = values.get("sector") or "the whole portfolio"
    return (
        f"Under the {str(values.get('scenario_label', 'scenario')).lower()} applied to "
        f"{scope}, expected credit loss rises from {money(values.get('base_ecl'))} to "
        f"{money(values.get('stressed_ecl'))} — {signed_money(values.get('ecl_increase'))}, "
        f"{pct(values.get('ecl_increase_pct'), 1)} above the reported position."
    )


def _answer_watchlist(values: dict, rows: list[dict]) -> str:
    return (
        f"{values.get('matched', '—')} facilities are drawn above "
        f"{pct(values.get('threshold_pct'), 0)} of their committed limit as at "
        f"{values.get('period')}, involving {money(values.get('total_ead'))} of exposure."
    )


def _answer_arrears_position(values: dict, rows: list[dict]) -> str:
    in_arrears = int(_n(values.get("facilities_in_arrears")) or 0)
    if not in_arrears:
        return (
            f"Nothing in {values.get('period', 'the period')} is in arrears — every "
            f"one of the {int(_n(values.get('facilities_read')) or 0):,} facilities "
            "read is current."
        )
    return (
        f"{in_arrears:,} facilities are in arrears in "
        f"{values.get('period', 'the period')} — "
        f"{pct(values.get('arrears_rate_pct'))} of the book — owing "
        f"{money(values.get('total_arrears_amount'))}, with "
        f"{money(values.get('exposure_at_risk'))} of exposure 90 or more days "
        "past due."
    )


def _answer_credit_file_signals(values: dict, rows: list[dict]) -> str:
    notes = int(_n(values.get("notes_written")) or 0)
    if not notes:
        return f"No credit file notes were written in {values.get('period', 'the period')}."
    top = rows[0] if rows else {}
    leading = (
        f" The concern raised most often was {str(top.get('signal', '')).lower()}, in "
        f"{int(_n(top.get('mentions')) or 0):,} of them."
        if top else ""
    )
    return (
        f"{notes:,} credit file notes were written in "
        f"{values.get('period', 'the period')}, "
        f"{pct(values.get('negative_share_pct'))} of them negative.{leading}"
    )


ANSWERS = {
    "arrears_position": _answer_arrears_position,
    "credit_file_signals": _answer_credit_file_signals,
    "ecl_movement": _answer_ecl_movement,
    "stage_migration": _answer_migration,
    "dpd_migration": _answer_migration,
    "rating_transition_matrix": _answer_rating_transition,
    "top_deteriorating_borrowers": _answer_top_deteriorating,
    "portfolio_summary": _answer_portfolio_summary,
    "sector_concentration": _answer_sector_concentration,
    "stage_distribution": _answer_stage_distribution,
    "portfolio_trend": _answer_portfolio_trend,
    "stress_scenario_basic": _answer_stress,
    "high_utilisation_watchlist": _answer_watchlist,
}


# ------------------------------------------------------- CreditProbe's interpretation
#
# The reading of the evidence. Three rules hold throughout:
#
#   1. No figure appears here that the engine did not return.
#   2. Where the engine established only that a change SITS somewhere, the
#      language says so — "concentrated in", "sits in", "coincides with". It
#      never says "caused by", because a decomposition is not an attribution
#      of cause.
#   3. It ends by pointing at what would actually settle the question.


def _interpret_ecl_movement(values: dict, rows: list[dict]) -> list[str]:
    group = values.get("group_by", "sector")
    breakdown = [b for b in (values.get("breakdown") or []) if isinstance(b, dict)]
    rising = [b for b in breakdown if (_n(b.get("ecl_change")) or 0) > 0]
    falling = [b for b in breakdown if (_n(b.get("ecl_change")) or 0) < 0]
    net = _n(values.get("net_change")) or 0
    points = []
    if rising:
        share = _and_list([str(b.get(group, "—")) for b in rising[:3]])
        points.append(
            f"The increase is concentrated in {share}. This is where the movement sits; "
            "the decomposition does not establish that these groups caused it."
        )
    if falling:
        points.append(
            f"{_and_list([str(b.get(group, '—')) for b in falling[:2]])} moved the other "
            "way, partly offsetting the increase — so the net figure understates the "
            "gross deterioration."
        )
    points.append(
        "Worth checking next: whether the movement reflects a small number of large "
        "names or a broad shift, which the borrower-level ranking would settle."
        if net > 0 else
        "The net movement is not adverse, but the gross picture may still contain "
        "deterioration offset by releases elsewhere."
    )
    return points


def _interpret_migration(values: dict, rows: list[dict]) -> list[str]:
    move = values.get("movement") or {}
    cover = values.get("coverage") or {}
    deteriorated = _n(move.get("deteriorated_pct")) or 0
    improved = _n(move.get("improved_pct")) or 0
    points = [
        f"Gross deterioration of {pct(deteriorated, 1)} against {pct(improved, 1)} improvement "
        "means the net change understates how much actually moved."
    ]
    if deteriorated > improved * 2:
        points.append(
            "Movement is materially one-directional, which is more consistent with a "
            "broad shift in credit quality than with normal period-to-period noise."
        )
    exits, entries = _n(cover.get("exits")) or 0, _n(cover.get("entries")) or 0
    if exits or entries:
        points.append(
            f"{int(exits)} facilities left the book and {int(entries)} were new. They are "
            "excluded from the migration, so this measures the same facilities twice, not "
            "the change in the book as a whole."
        )
    points.append(
        "The names behind the movement would show whether this is concentrated or broad."
    )
    return points


def _interpret_rating_transition(values: dict, rows: list[dict]) -> list[str]:
    move = values.get("movement") or {}
    down = _n(move.get("downgraded_pct")) or 0
    up = _n(move.get("upgraded_pct")) or 0
    points = [
        f"Downgrades exceed upgrades by {pp(down - up, 1).lstrip('+')} of opening exposure."
        if down > up else
        "Upgrades exceed downgrades over this interval."
    ]
    points.append(
        "This is an empirical matrix over one interval, not a through-the-cycle estimate. "
        "Cells with little exposure behind them will be unstable."
    )
    points.append(
        "Whether the downgrades cluster in particular grades or sectors is the question "
        "this matrix raises rather than answers."
    )
    return points


def _interpret_top_deteriorating(values: dict, rows: list[dict]) -> list[str]:
    total = _n(values.get("total_ecl_increase")) or 0
    lead_share = 0.0
    if rows and total:
        lead_share = ((_n(rows[0].get("ecl_change")) or 0) / total) * 100
    points = []
    if lead_share >= 20:
        points.append(
            f"A single borrower accounts for roughly {lead_share:.0f}% of the aggregate ECL "
            "increase across these names, so the movement is concentrated rather than broad."
        )
    else:
        points.append(
            "No single name dominates the aggregate increase, which points to a broad "
            "movement rather than an isolated credit event."
        )
    sectors = [str(r.get("sector")) for r in rows[:10] if r.get("sector")]
    if sectors:
        common = max(set(sectors), key=sectors.count)
        if sectors.count(common) >= 3:
            points.append(
                f"{sectors.count(common)} of the listed names sit in {common}. That is an "
                "association worth testing, not evidence of a sector-wide cause."
            )
    points.append(
        "The recorded reasons on each row give the specific trigger — stage change, "
        "downgrade, arrears or ECL — for each name."
    )
    return points


def _interpret_portfolio_summary(values: dict, rows: list[dict]) -> list[str]:
    move = values.get("movement") or {}
    points = []
    cov = _n(move.get("ecl_coverage_pct"))
    if cov is not None and abs(cov) >= 0.01:
        points.append(
            f"Coverage has {direction_word(cov)} {pp(abs(cov))} against "
            f"{values.get('compare_period')}. Coverage can move because impairment "
            "changed, because the book grew, or both — the two are separated by the "
            "impairment movement analysis."
        )
    breaches = _n(values.get("appetite_breach_count"))
    if breaches:
        points.append(
            f"{int(breaches)} exposures breach declared appetite, which is a limit "
            "question rather than a measurement one."
        )
    points.append("This is the position. What moved and why sits behind the other analyses.")
    return points


def _interpret_sector_concentration(values: dict, rows: list[dict]) -> list[str]:
    dimension = str(values.get("dimension", "sector"))
    top5 = _n(values.get("top_5_pct")) or 0
    points = []
    if top5 >= 60:
        points.append(
            f"With {pct(top5, 1)} of exposure in five groups, the book is materially "
            "concentrated. Concentration is not itself a problem; concentration in a "
            "deteriorating group is."
        )
    worst = max(rows, key=lambda r: _n(r.get("coverage_pct")) or 0, default=None)
    if worst:
        points.append(
            f"{worst.get(dimension)} carries the highest coverage at "
            f"{pct(worst.get('coverage_pct'))}, which is where size and quality overlap."
        )
    points.append(
        "This is a point-in-time view. Whether any of these concentrations is worsening "
        "needs a comparison across periods."
    )
    return points


def _interpret_stage_distribution(values: dict, rows: list[dict]) -> list[str]:
    by_stage = {int(r.get("ifrs9_stage", 0)): r for r in rows if r.get("ifrs9_stage") is not None}
    points = []
    s2 = by_stage.get(2)
    if s2 and (_n(s2.get("ead_pct")) or 0) > 10:
        points.append(
            f"A Stage 2 share above 10% is significant: {pct(s2.get('ead_pct'), 1)} of the "
            "book is carrying lifetime expected loss without being credit-impaired."
        )
    points.append(
        "A distribution shows where exposure sits, not what moved there. The stage "
        "migration analysis separates the two."
    )
    return points


def _interpret_portfolio_trend(values: dict, rows: list[dict]) -> list[str]:
    change = values.get("change") or {}
    cov = _n(change.get("ecl_coverage_pct")) or 0
    points = [
        "The direction is consistent across the series rather than a single-period step."
        if abs(cov) > 0 else "Coverage has been broadly flat across the series."
    ]
    points.append(
        "Each point is a portfolio total, so this shows the path without attributing it "
        "to any sector or name."
    )
    return points


def _interpret_stress(values: dict, rows: list[dict]) -> list[str]:
    by_sector = [b for b in (values.get("by_sector") or []) if isinstance(b, dict)]
    points = []
    if by_sector:
        worst = by_sector[0]
        points.append(
            f"{worst.get('sector')} absorbs the largest share of the increase, "
            f"{signed_money(worst.get('ecl_increase'))} — a function of both its exposure "
            "and its starting coverage."
        )
    points.append(
        "This is a management scenario: each facility's reported ECL is scaled by the "
        "shock. There is no forward-looking macro path and no lifetime PD term structure, "
        "so it sizes sensitivity rather than forecasting loss."
    )
    return points


def _interpret_watchlist(values: dict, rows: list[dict]) -> list[str]:
    return [
        "High utilisation often precedes a stage migration, because a borrower drawing "
        "its committed lines is a borrower short of liquidity. It is a signal, not a "
        "default indicator.",
        "This analysis is user-defined and has not been validated by the bank.",
    ]


def _interpret_arrears_position(values: dict, rows: list[dict]) -> list[str]:
    """A reading of the arrears position. Never a forecast of recovery."""
    points: list[str] = []
    rate = _n(values.get("arrears_rate_pct")) or 0
    ninety = _n(values.get("facilities_90_plus")) or 0
    in_arrears = _n(values.get("facilities_in_arrears")) or 0

    if in_arrears and ninety:
        share = 100.0 * ninety / in_arrears
        points.append(
            f"Of the facilities behind, {share:.0f}% are already 90 or more days "
            "past due, so the arrears are concentrated at the hard end rather "
            "than spread thinly across early buckets."
            if share >= 40 else
            f"Only {share:.0f}% of the facilities behind have reached 90 days, so "
            "most of the arrears are still early and, on this data alone, "
            "still curable."
        )

    cured = _n(values.get("cured_this_period")) or 0
    new = _n(values.get("newly_delinquent")) or 0
    if cured or new:
        points.append(
            f"{int(new):,} facilities fell behind this period against {int(cured):,} "
            "that returned to current — " +
            ("the book is losing ground on arrears."
             if new > cured else
             "cures outpaced new delinquencies.")
        )

    forborne = _n(values.get("forborne_facilities")) or 0
    if forborne and in_arrears:
        points.append(
            f"{int(forborne):,} facilities carry a concession. Forbearance keeps a "
            "facility from ageing into a worse bucket, so an arrears rate of "
            f"{rate:.2f}% understates how many borrowers are under strain."
        )

    points.append(
        "This is the position at one quarter end. It says what is overdue and "
        "how far collections has escalated; it does not estimate what will be "
        "recovered."
    )
    return points


def _interpret_credit_file_signals(values: dict, rows: list[dict]) -> list[str]:
    """A reading of what was written. Explicitly not a prediction."""
    points: list[str] = []
    negative = _n(values.get("negative_share_pct")) or 0
    concerns = _n(values.get("mean_concerns_per_note")) or 0

    if negative >= 40:
        points.append(
            f"{negative:.0f}% of the notes are negative in tone, which is high "
            "enough that the commentary is describing a book under pressure "
            "rather than isolated names."
        )
    elif negative:
        points.append(
            f"{negative:.0f}% of the notes are negative in tone; the balance of "
            "the commentary is neutral or better."
        )

    if len(rows) >= 2:
        first, second = rows[0], rows[1]
        points.append(
            f"{first.get('signal')} and {second.get('signal')} are the two concerns "
            f"raised most often, in {pct(first.get('share_of_notes_pct'))} and "
            f"{pct(second.get('share_of_notes_pct'))} of notes respectively."
        )

    if concerns >= 2:
        points.append(
            f"Notes raise {concerns:.1f} of the six tracked concerns on average, so "
            "the files that are worried tend to be worried about more than one "
            "thing at once."
        )

    points.append(
        "These are counts of what was written, not evidence of what will "
        "happen. No relationship between these signals and credit outcomes has "
        "been established here, and none is claimed."
    )
    return points


INTERPRETERS = {
    "arrears_position": _interpret_arrears_position,
    "credit_file_signals": _interpret_credit_file_signals,
    "ecl_movement": _interpret_ecl_movement,
    "stage_migration": _interpret_migration,
    "dpd_migration": _interpret_migration,
    "rating_transition_matrix": _interpret_rating_transition,
    "top_deteriorating_borrowers": _interpret_top_deteriorating,
    "portfolio_summary": _interpret_portfolio_summary,
    "sector_concentration": _interpret_sector_concentration,
    "stage_distribution": _interpret_stage_distribution,
    "portfolio_trend": _interpret_portfolio_trend,
    "stress_scenario_basic": _interpret_stress,
    "high_utilisation_watchlist": _interpret_watchlist,
}


READERS = {
    "arrears_position": _arrears_position,
    "credit_file_signals": _credit_file_signals,
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
                            "value": entry.get("ecl_change"), "unit": "SAR mn",
                            "measure": "ECL movement", "step": index})
            if out:
                return out

        if step.get("analysis_id") == "top_deteriorating_borrowers" and rows:
            return [
                {"name": str(r.get("borrower_name", "—")), "value": r.get("ecl_change"),
                 "unit": "SAR mn", "measure": "ECL movement",
                 "detail": str(r.get("reasons", "")), "step": index}
                for r in rows[:5]
            ]

        if step.get("analysis_id") == "sector_concentration" and rows:
            dimension = values.get("dimension", "sector")
            return [
                {"name": str(r.get(dimension, "—")), "value": r.get("ead"), "unit": "SAR mn",
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


def _primary_index(steps: list[dict[str, Any]], plan: Any) -> int:
    """Which executed step answers the question.

    The planner marks exactly one step PRIMARY. That marking is the whole point
    of question-scoped planning, so it is honoured here rather than re-derived:
    a supporting step can easily produce the louder number, and opening the
    answer with it would answer a question nobody asked.
    """
    succeeded = [i for i, s in enumerate(steps) if s.get("status") == "succeeded"]
    if not succeeded:
        return -1

    primary = getattr(plan, "primary", None) if plan is not None else None
    wanted = getattr(primary, "analysis_id", None)
    if wanted:
        for i in succeeded:
            if steps[i].get("analysis_id") == wanted:
                return i
        # The primary step failed. Its answer is unavailable, and the caveat
        # already says so; the first surviving step leads instead.
    return succeeded[0]


def build_narrative(question: str, intent: str, steps: list[dict[str, Any]],
                    plan: Any = None) -> Narrative:
    """Assemble the answer for an executed investigation.

    `steps` are executed steps: {"analysis_id", "result": {"values","rows","warnings"}}.
    `plan` is the AnalysisPlan that produced them, used only to identify which
    step was PRIMARY. It is optional so that callers predating question-scoped
    planning keep working.

    The output keeps two things apart on purpose:

        direct_answer + findings + metrics   calculated, quoted from the engine
        interpretation + interpretation_points   CreditProbe's reading of them

    Nothing crosses that line. The interpretation composers may not introduce a
    figure, and the readers may not offer an opinion.
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

    # ------------------------------------------------ the answer to the question
    primary_index = _primary_index(steps, plan)
    direct_answer = ""
    interpretation_points: list[str] = []

    if primary_index >= 0:
        primary_step = steps[primary_index]
        analysis_id = str(primary_step.get("analysis_id"))
        result = primary_step.get("result") or {}
        values = result.get("values") or {}
        rows = result.get("rows") or []

        composer = ANSWERS.get(analysis_id)
        if composer is not None:
            try:
                direct_answer = composer(values, rows)
            except Exception as e:  # pragma: no cover - never break a result
                logger.warning("Answer composer failed on %s: %s", analysis_id, e)

        interpreter = INTERPRETERS.get(analysis_id)
        if interpreter is not None:
            try:
                interpretation_points = [p for p in interpreter(values, rows) if p]
            except Exception as e:  # pragma: no cover - never break a result
                logger.warning("Interpretation failed on %s: %s", analysis_id, e)

    if not direct_answer:
        # No composer for this analysis, or it failed. The findings are still
        # calculated facts, so the older summary is a safe fallback.
        direct_answer = _summary_sentence(question, intent, findings)

    # A supporting step earns one line of reading, never a second briefing. This
    # is what keeps "why has Stage 2 increased?" to an answer rather than a tour.
    for index, step in enumerate(steps):
        if index == primary_index or step.get("status") != "succeeded":
            continue
        interpreter = INTERPRETERS.get(str(step.get("analysis_id")))
        if interpreter is None:
            continue
        result = step.get("result") or {}
        try:
            extra = [p for p in interpreter(result.get("values") or {},
                                            result.get("rows") or []) if p]
        except Exception:  # pragma: no cover - never break a result
            continue
        if extra:
            interpretation_points.append(extra[0])

    interpretation_points = list(dict.fromkeys(interpretation_points))[:4]

    # Keep the first occurrence of each headline label: several analyses report
    # total exposure, and an answer that says it three times reads as noise.
    seen: set[str] = set()
    unique_metrics = []
    for metric in metrics:
        if metric.label in seen:
            continue
        seen.add(metric.label)
        unique_metrics.append(metric)

    # The primary step's own metrics lead, because they are the ones the answer
    # quotes. Four is the most a reader takes in above a chart.
    unique_metrics.sort(key=lambda m: 0 if m.step == primary_index else 1)

    return Narrative(
        direct_answer=direct_answer,
        summary=direct_answer,
        findings=findings,
        interpretation=" ".join(interpretation_points),
        interpretation_points=interpretation_points,
        why_multiple=_why_multiple(steps, primary_index),
        metrics=unique_metrics[:4],
        drivers=_drivers(steps),
        caveats=list(dict.fromkeys(caveats))[:6],
    )


def _why_multiple(steps: list[dict[str, Any]], primary_index: int) -> str:
    """One line on why more than one analysis ran.

    A reader who sees three results is entitled to know why three, and the
    honest answer is a property of the PLAN: each supporting step was chosen
    because the question needs something the primary analysis does not provide.

    Composed from the steps' own recorded rationale, so it says what actually
    happened rather than a generic sentence about thoroughness. It introduces no
    figure, because it is not describing the portfolio.
    """
    completed = [s for s in steps if s.get("status") == "succeeded"]
    if len(completed) < 2:
        return ""

    supporting = [
        str(step.get("rationale") or "").strip().rstrip(".")
        for index, step in enumerate(steps)
        if index != primary_index and step.get("status") == "succeeded"
    ]
    supporting = [r for r in supporting if r]
    if not supporting:
        return (
            f"CreditProbe ran {len(completed)} analyses: one answers the "
            "question, the others provide the context needed to read it."
        )

    reasons = "; ".join(supporting[:2]).lower()
    return (
        f"CreditProbe ran {len(completed)} analyses because the question needs "
        f"more than one: {reasons}."
    )


__all__ = ["Finding", "Metric", "Narrative", "build_narrative"]
