"""
Presenting a scenario: the executive summary first, the names underneath.

A stressed ECL with no borrowers behind it is a number nobody can act on, and a
list of borrowers with no total is a list nobody can take to a committee. Both,
in that order, is what a scenario answer is.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from backend.ifrs9 import policy
from backend.product.compose import DETAILED, MEDIUM, Answer, Section, compose
from backend.whatif import engine as wf
from backend.whatif import language as lg
from backend.whatif import masterscale as ms
from backend.whatif import sensitivity as sv

#: Section 1G's borrower table, in the order a credit officer reads it.
BORROWER_COLUMNS: tuple[str, ...] = tuple(
    label for _, label in wf.PRESENT_COLUMNS)


def _money(value: float) -> str:
    return f"{value:,.1f}"


def summary_sections(result: wf.Result) -> list[Section]:
    """The executive summary every scenario answer opens with."""
    s = result.summary
    lines = [
        f"**Population:** {s['borrowers']:,} borrowers — {s['population']}, {s['period']}",
        f"**Exposure at default:** {_money(s['baseline_ead'])} → "
        f"{_money(s['stressed_ead'])} {wf.CURRENCY}",
        f"**Expected credit loss:** {_money(s['baseline_ecl'])} → "
        f"{_money(s['stressed_ecl'])} {wf.CURRENCY}",
        f"**Incremental ECL:** {_money(s['incremental_ecl'])} {wf.CURRENCY} "
        f"({s['incremental_ecl_pct']:+.1f}%)",
        f"**ECL coverage:** {s['baseline_coverage_pct']:.2f}% → "
        f"{s['stressed_coverage_pct']:.2f}%",
        f"**Stage 1 → Stage 2 migrations:** {s['stage_2_migrations']:,}",
        f"**Borrowers with a higher ECL:** {s['borrowers_with_higher_ecl']:,}",
    ]
    if s.get("downgraded"):
        lines.insert(1, f"**Borrowers downgraded:** {s['downgraded']:,}")
    if s.get("covenant_breaches"):
        lines.append(f"**Borrowers already in covenant breach:** "
                     f"{s['covenant_breaches']:,}")
    return [Section(key="summary", title="Scenario impact", body=[], bullets=lines)]


def borrower_table(result: wf.Result, limit: int = 25) -> dict[str, Any]:
    frame = result.borrowers.head(limit)
    labels = {name: label for name, label in wf.PRESENT_COLUMNS}
    columns = [labels[c] for c in frame.columns if c in labels]
    rows = frame[[c for c in frame.columns if c in labels]].values.tolist()
    return {"columns": columns, "rows": rows}


def compose_answer(result: wf.Result, reading: lg.Reading) -> Answer:
    """The scenario, written for a reader rather than dumped."""
    s = result.summary
    scenario = result.scenario
    objective = reading.objective

    headline = (
        f"Under **{scenario.name}**, expected credit loss on "
        f"{s['borrowers']:,} borrowers moves from {_money(s['baseline_ecl'])} to "
        f"{_money(s['stressed_ecl'])} {wf.CURRENCY} — "
        f"{_money(s['incremental_ecl'])} more, {s['incremental_ecl_pct']:+.1f}%.")

    sections = summary_sections(result)

    if objective == lg.MIGRATIONS or s["stage_2_migrations"]:
        moved = result.borrowers[
            result.borrowers["stage_stressed"] > result.borrowers["stage_baseline"]] \
            if "stage_stressed" in result.borrowers.columns else pd.DataFrame()
        sections.append(Section(
            key="migrations", title="Stage migration",
            body=[f"{s['stage_2_migrations']:,} borrowers move from Stage 1 to "
                  f"Stage 2 under this scenario, and {s['stage_3_migrations']:,} "
                  "reach Stage 3. A Stage 2 borrower is measured on lifetime "
                  "expected loss rather than twelve-month, which is why the "
                  "provision moves further than the PD does.",
                  f"The governed triggers were re-read against the stressed PD: "
                  f"PD at least {policy.SICR_PD_RATIO:g}x its level at "
                  f"origination and at least {policy.SICR_PD_ABSOLUTE:.2f} "
                  f"percentage points higher, PD at or above "
                  f"{policy.SICR_ABSOLUTE_PD:.0f}%, or "
                  f"{policy.SICR_DPD_DAYS}+ days past due."],
            table=({"columns": ["Borrower", "Sector", "Opening rating",
                                "Stressed rating", "Opening PD (%)",
                                "Stressed PD (%)", "ECL increase (SAR)"],
                    "rows": [[r["display_name"], r["sector"],
                              r["opening_rating"], r["stressed_rating"],
                              round(float(r["pd_12m"]), 2),
                              round(float(r["pd_stressed"]), 2),
                              round(float(r["ecl_increase"]), 1)]
                             for _, r in moved.head(20).iterrows()]}
                   if not moved.empty else None)))

    if objective in (lg.BORROWERS, lg.TOP) or s["borrowers"] <= 40:
        sections.append(Section(
            key="borrowers",
            title="Borrower by borrower" if objective == lg.BORROWERS
            else "Largest ECL increases",
            body=["Every figure below is that borrower's own — the portfolio "
                  "total is the sum of this table, not an allocation onto it."],
            table=borrower_table(result)))

    if not result.by_sector.empty and objective in (lg.SECTOR, lg.SUMMARY):
        top = result.by_sector.head(8)
        sections.append(Section(
            key="sectors", title="Where the impact lands",
            body=[], table={
                "columns": ["Sector", "Borrowers", "Baseline ECL",
                            "Stressed ECL", "ECL increase", "Increase (%)"],
                "rows": [[r["sector"], int(r["borrowers"]),
                          round(r["baseline_ecl"], 1), round(r["stressed_ecl"], 1),
                          round(r["ecl_increase"], 1),
                          round(r["ecl_increase_pct"], 1)]
                         for _, r in top.iterrows()]}))

    sections.append(Section(
        key="how", title="How this was calculated", detail=True,
        body=[], bullets=[f"**{step['step']}.** {step['detail']}"
                          for step in result.steps]))

    if result.sensitivity_rows:
        sections.append(Section(
            key="sensitivity", title="Sensitivity assumptions", detail=True,
            body=[f"Macro effects come from sensitivity matrix "
                  f"{sv.MATRIX_VERSION}, owned by {sv.MATRIX_OWNER} and "
                  f"effective {sv.MATRIX_EFFECTIVE}. These are configured "
                  "management assumptions, not econometric estimates."],
            table={"columns": ["Variable", "Shock", "Sector",
                               "Sector sensitivity", "PD effect (%)",
                               "LGD effect (pp)", "Borrowers"],
                   "rows": [[r["variable"], r["shock"], r["scope"],
                             r["sector_sensitivity"], r["pd_effect_pct"],
                             r["lgd_effect_pp"], r["borrowers"]]
                            for r in result.sensitivity_rows[:20]]}))

    if reading.notes or result.warnings:
        sections.append(Section(
            key="assumptions", title="What this assumed",
            body=[], bullets=[*reading.notes, *result.warnings]))

    if reading.unread:
        sections.append(Section(
            key="unread", title="What could not be read",
            body=["Nothing was guessed. These parts of the question were not "
                  "applied:"],
            bullets=list(reading.unread)))

    return compose(Answer(
        topic="whatif",
        band=DETAILED if objective in (lg.BORROWERS, lg.MIGRATIONS) else MEDIUM,
        deep=True,
        headline=headline,
        sections=sections,
        sources=["corporate borrower snapshot", "IFRS 9 measurement",
                 f"rating masterscale {ms.MASTERSCALE_VERSION}",
                 f"macro sensitivity matrix {sv.MATRIX_VERSION}",
                 f"IFRS 9 policy {policy.POLICY_VERSION}"],
        follow_ups=[
            "Give me the result customer by customer.",
            "Which borrowers become most vulnerable?",
            "What does What-If Analysis do?"][:3]))


__all__ = ["BORROWER_COLUMNS", "borrower_table", "compose_answer",
           "summary_sections"]
