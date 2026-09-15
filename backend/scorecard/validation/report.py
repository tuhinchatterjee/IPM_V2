"""The validation report, assembled from results that already exist. §29.

This builds a `backend.scorecard.report.Report` — the same content model the
retail scorecard report uses, and therefore the same DOCX writer, the same
table style, the same content hash, the same evidence register. There is no
second document engine here and there must not be: two report builders that
both claim to produce "the validation report" will disagree about a heading
within a quarter, and the reader who notices will be a regulator.

What is assembled and what is not
---------------------------------
Every sentence in this report comes from a `Result` or a `Finding` that was
computed before the report was asked for. Nothing here recomputes anything,
and nothing here decides anything: the opinion is derived from the findings
by a rule short enough to read (`_opinion`), and the narrative sentences are
the `detail` fields the results already carry.

That is the constraint that makes a report reproducible from its own
evidence register. A narrative written *about* results can drift from them;
a narrative assembled *out of* them cannot.

The refusals are in the document
--------------------------------
A validation report that quietly omits the tests that could not run is a
report whose scope the reader has to guess. Every refusal appears, with its
reason, in the section it belongs to — and the coverage section counts them.
"""

from __future__ import annotations

import datetime as dt

from backend.scorecard import report as report_mod
from backend.scorecard.validation import findings as finding_engine
from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import regulatory as regulatory_map
from backend.scorecard.validation import states

VALIDATION_REPORT_VERSION = "scv-report-1.0.0"

READY = "READY FOR USER ACCEPTANCE TESTING"
NOT_READY = "NOT READY FOR USER ACCEPTANCE TESTING"

#: The opinion vocabulary. Three words, and none of them is "approved":
#: approval is a committee's act, and a document that pre-empts it is a
#: document that will be quoted as though the committee had met.
USE_AS_IS = "USE AS IS"
USE_WITH_CONDITIONS = "USE WITH CONDITIONS"
DO_NOT_USE_UNTIL_REMEDIATED = "DO NOT USE UNTIL REMEDIATED"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT EVIDENCE TO FORM AN OPINION"

OPINIONS: tuple[str, ...] = (USE_AS_IS, USE_WITH_CONDITIONS,
                             DO_NOT_USE_UNTIL_REMEDIATED,
                             INSUFFICIENT_EVIDENCE)

OPINION_MEANING: dict[str, str] = {
    USE_AS_IS: "Nothing measured on this run is outside its governed limit.",
    USE_WITH_CONDITIONS: "Findings exist that a model owner must act on, and "
                         "none of them undermines the evidence base itself.",
    DO_NOT_USE_UNTIL_REMEDIATED: "Something is wrong that makes the rest of "
                                 "the evidence unreliable — most often that "
                                 "the production score does not reproduce "
                                 "from its approved specification.",
    INSUFFICIENT_EVIDENCE: "Too little of the model could be measured for an "
                           "opinion to rest on anything.",
}

#: Below this share of applicable tests producing a number, there is not
#: enough measured to form an opinion at all. A report that concluded
#: USE AS IS on four tests out of forty-eight would be technically true and
#: completely misleading.
MINIMUM_MEASURED_SHARE = 0.5


def _opinion(assessed: list[finding_engine.Finding],
             results: list[states.Result],
             model: model_registry.Model) -> tuple[str, str]:
    """The opinion, and the sentence that justifies it.

    Four outcomes from two questions, in this order: is there enough
    evidence to have an opinion, and does anything in it undermine the rest.
    Deliberately short — an opinion rule a reader cannot hold in their head
    is one they will not check.
    """
    applicable = [r for r in results
                  if r.state != states.NOT_APPLICABLE]
    measured = [r for r in applicable if r.measured]
    share = len(measured) / len(applicable) if applicable else 0.0

    if share < MINIMUM_MEASURED_SHARE:
        return INSUFFICIENT_EVIDENCE, (
            f"Only {len(measured)} of {len(applicable)} applicable tests "
            f"produced a number, {share:.0%}. Below "
            f"{MINIMUM_MEASURED_SHARE:.0%} there is not enough measured for "
            "an opinion to rest on, and a conclusion drawn here would be a "
            "conclusion about the tests that happened to run.")

    critical = [f for f in assessed if f.severity == finding_engine.CRITICAL]
    undermining = [f for f in critical
                   if f.category == test_registry.IMPLEMENTATION]
    if undermining:
        return DO_NOT_USE_UNTIL_REMEDIATED, (
            f"{undermining[0].what} Until that reconciles, every other "
            "result in this report describes a model that is not the one in "
            "production.")

    actionable = [f for f in assessed
                  if f.severity in (finding_engine.CRITICAL,
                                    finding_engine.HIGH,
                                    finding_engine.MEDIUM)]
    if not actionable:
        return USE_AS_IS, (
            f"All {len(measured)} measured tests are inside their governed "
            "limits, and no cross-test pattern raised a finding.")

    worst = actionable[0]
    return USE_WITH_CONDITIONS, (
        f"{len(actionable)} finding(s) require action, the most severe being "
        f"{worst.severity}: {worst.title}. None of them undermines the "
        "evidence base itself, so the results below can be relied on while "
        "the remediation is carried out.")


def _windows(model: model_registry.Model) -> tuple[str, str]:
    """The matured window, and the latest period the book has.

    Two windows because the report uses two. Outcome tests run over the
    cohorts whose performance window has closed; stability tests run on the
    newest data, because population drift is visible before its consequences
    are. Both are stated on the cover, because a reader who assumes one
    window covers the whole report will misread half of it.

    Derived from the model's own data rather than from the period labels the
    results carry. Those labels are a mix of ranges and single months —
    "2023-01..2024-04" beside "2025-12" — and sorting them as strings and
    taking the ends produced a report id reading
    `2023-01..2024-04..2025-12`, which is not a window at all.
    """
    from backend.scorecard.validation import runner

    try:
        matured = runner.matured_periods(model)
        available = runner.available_periods(model)
    except Exception:  # noqa: BLE001 - an unbuilt lake is a real state
        return "", ""
    span = (f"{matured[0]}..{matured[-1]}" if len(matured) > 1
            else (matured[0] if matured else ""))
    return span, (available[-1] if available else "")


def _table(caption: str, columns: list[str], rows: list[list[str]],
           note: str = "") -> report_mod.Table:
    return report_mod.Table(caption=caption, columns=columns, rows=rows,
                            note=note)


def _result_rows(results: list[states.Result]) -> list[list[str]]:
    """One row per test, refusals included and labelled as refusals.

    The value column is em-dash for an unmeasured state rather than blank or
    zero. A blank reads as "not filled in yet" and a zero reads as a
    measurement; neither is what happened.
    """
    rows: list[list[str]] = []
    for result in states.rank(results):
        test = test_registry.BY_ID.get(result.test_id)
        rows.append([
            result.test_id,
            test.name if test else result.test_id,
            report_mod.stat(result.value) if result.measured else "—",
            report_mod.stat(result.limit) if result.limit is not None
            else "no approved limit",
            states.STATE_LABELS[result.state],
            result.detail,
        ])
    return rows


RESULT_COLUMNS = ["Test", "Name", "Result", "Limit", "State", "Basis"]


def _finding_rows(assessed: list[finding_engine.Finding]) -> list[list[str]]:
    return [[
        made.finding_id, made.severity, made.title, made.what,
        made.remediation, made.verify_by,
        ", ".join(made.evidence),
        ", ".join(regulatory_map.shown_as(r) for r in made.cbuae) or "—",
    ] for made in assessed]


FINDING_COLUMNS = ["Ref", "Severity", "Finding", "Basis", "Remediation",
                   "Verified by", "Evidence", "Reference"]


def _evidence_register(results: list[states.Result],
                       section_of: dict[str, str]) -> list[report_mod.Evidence]:
    """Every measured figure, with what it would take to find it again.

    Only the measured ones. An evidence register that lists refusals as
    entries with no value is a register a reader stops trusting, and the
    refusals are already in the body with their reasons.
    """
    register: list[report_mod.Evidence] = []
    for result in results:
        if not result.measured or result.value is None:
            continue
        test = test_registry.BY_ID.get(result.test_id)
        register.append(report_mod.Evidence(
            section=section_of.get(result.test_id, ""),
            label=test.name if test else result.test_id,
            metric=result.test_id,
            value=result.value,
            value_text=report_mod.stat(result.value),
            method=result.method,
            period=result.period,
            model_version=result.model_version,
            validation_state=result.state,
            data_version=result.calculation_version,
        ))
    return register


# ================= §15: the fifteen sections, and what fills each ==========


#: Which report section each test's evidence belongs in.
#:
#: §15 lists fifteen sections by subject, not by the engine's eleven
#: categories, and the two do not line up: Data & Representativeness supplies
#: three of them, Stability supplies two, and DATA-ODR belongs beside the
#: calibration evidence rather than beside the row counts.
#:
#: Written out per test rather than derived from the category, because a
#: derived mapping silently drops a newly registered test into whichever
#: section its category happens to own, and the test that catches that is the
#: one asserting every result lands somewhere.
SECTION_OF_TEST: dict[str, str] = {
    # 4. Validation sample, default definition, maturity and exclusions
    "DATA-ROWS": "4", "DATA-MATURITY": "4", "DATA-PROVENANCE": "4",
    "DATA-COVERAGE": "4", "DATA-DUPLICATES": "4", "DATA-EVENTS": "4",
    "CONC-DEFAULT": "4", "CONC-WINDOWS": "4",
    # 5. Data quality and development/current representativeness
    "DATA-MISSING": "5", "DATA-REPRESENTATIVE": "5", "DATA-MIXADJ": "5",
    "CONC-PURPOSE": "5", "CONC-DIRECTION": "5", "CONC-DOCUMENTATION": "5",
    # 6. Univariate and bivariate evidence for the inputs
    "VAR-IV": "6", "VAR-GINI": "6", "VAR-WOE": "6", "VAR-OCCUPANCY": "6",
    "VAR-SIGN": "6",
    # 7. CSI/PSI and population/score drift
    "STAB-PSI": "7", "STAB-CSI": "7", "STAB-BAND": "7",
    "DATA-INPUT-DRIFT": "7",
    # 8. Discrimination, KS/gains and rank-order inversions
    "DISC-AUC": "8", "DISC-GINI": "8", "DISC-KS": "8", "DISC-LIFT": "8",
    "DISC-RANK": "8", "DISC-RANK-PEER": "8", "DISC-TREND": "8",
    # 9. Calibration and comparable ODR/PD analysis
    "CAL-OE": "9", "CAL-BAND": "9", "CAL-BRIER": "9", "CAL-SLOPE": "9",
    "CAL-DRIFT": "9", "DATA-ODR": "9",
    # 10. Stability through time, robustness and implementation
    "STAB-ROLLING": "10", "ROB-BOOTSTRAP": "10",
    "ROB-SEGMENT-EXCLUSION": "10", "ROB-WINDOW": "10",
    "IMPL-REPLICATE": "10", "IMPL-VERSION": "10",
    # 11. Product, classification and sub-product performance
    "SEG-DISCRIMINATION": "11", "SEG-CALIBRATION": "11", "SEG-RANK": "11",
    # 12. Usage, overrides and the challenger comparison
    "USE-OVERRIDE-RATE": "12", "USE-OVERRIDE-OUTCOME": "12",
    "USE-MATRIX": "12", "USE-CUTOFF": "12",
    "CC-DISCRIMINATION": "12", "CC-CALIBRATION": "12",
    "CC-STABILITY": "12", "CC-SWAPSET": "12",
}

#: What each section is for, in the sentence that opens it.
SECTION_PURPOSE: dict[str, str] = {
    "4": "What was measured, over which rows, against which outcome, and "
         "what was excluded on the way. Every later number in this report is "
         "a number about this population and about no other.",
    "5": "Whether the data is fit to validate on, and whether the book being "
         "scored still resembles the book the model was fitted on. Those are "
         "two questions and a report that runs them together answers "
         "neither.",
    "6": "Each input on its own: how much it predicts, whether its bins are "
         "still ordered by risk, and whether it carries the sign the "
         "approved equation gives it.",
    "7": "How far the population and the score have moved from the "
         "development distribution. CSI means feature-level shift over the "
         "approved bins; PSI means the same statistic over the score's "
         "reference bands. Neither is used to mean anything else anywhere in "
         "this document.",
    "8": "Whether the score separates the accounts that defaulted from the "
         "accounts that did not, and whether it orders risk monotonically.",
    "9": "Whether the predicted probability is the right LEVEL, which is a "
         "different question from whether the score ranks. A model can rank "
         "perfectly and be calibrated to the wrong number; the fixes differ.",
    "10": "Whether the answers hold when the window, the segments or the "
          "sample are perturbed, and whether the score in production is the "
          "score the approved specification produces.",
    "11": "The same questions asked of each product, classification and "
          "cohort separately. A portfolio statistic inside its limit can "
          "conceal a segment well outside it.",
    "12": "How the score is used, how often it is overridden and how the "
          "overrides performed; and the challenger comparison where an "
          "actual registered challenger exists to compare against.",
}


#: How long a finding of each severity is proposed to run for.
REMEDIATION_DAYS: dict[str, int] = {
    "CRITICAL": 30, "HIGH": 60, "MEDIUM": 90, "LOW": 180,
    "OBSERVATION": 180,
}


def _due(severity: str, window: str) -> str:
    """A PROPOSED due date, derived from severity and the validation window.

    §15 asks for remediation actions with owners and proposed due dates. The
    word proposed is doing work: a date this document invents is a date
    nobody has committed to, and printing it without that word is how a
    generated suggestion becomes a missed deadline in a committee pack.

    Anchored on the END OF THE VALIDATION WINDOW, not on the clock that
    generated the document. Two reasons, and the second is the load-bearing
    one. A date measured from "now" moves every time the file is
    regenerated, so the same finding acquires a later deadline by being
    printed again. And §56's content hash exists to answer "has anything
    about this model's assessment changed, or is this the same report with a
    new cover?" — a generated-at date inside a hashed section makes every
    regeneration a different hash and the question unanswerable.
    """
    days = REMEDIATION_DAYS.get(severity, 180)
    month = (window or "").split("..")[-1].strip()
    try:
        year, number = (int(part) for part in month.split("-")[:2])
        # The month after the window closes: the window covers whole months,
        # so the first day a validator could act on it is the next one.
        start = (dt.date(year + 1, 1, 1) if number == 12
                 else dt.date(year, number + 1, 1))
    except (ValueError, TypeError):
        return f"within {days} days of acceptance"
    return f"{(start + dt.timedelta(days=days)).isoformat()} (proposed)"


def _figures_for(results: list[states.Result], *, keep: int = 3
                 ) -> list[report_mod.Figure]:
    """The drawable charts in one section, most severe first.

    Capped, because a section with fourteen tests would otherwise carry
    fourteen pictures and a reader would look at none of them. The cap is on
    PICTURES only: every test's numbers are in the section's table whether
    or not it got a figure.
    """
    from backend.scorecard.validation import report_charts

    out: list[report_mod.Figure] = []
    for result in states.rank(results):
        if len(out) >= keep:
            break
        if not result.measured or not result.chart:
            continue
        kind = str(result.chart.get("kind") or "")
        if kind not in report_charts.DRAW:
            continue
        test = test_registry.BY_ID.get(result.test_id)
        out.append(report_mod.Figure(
            caption=(f"Figure — {test.name if test else result.test_id} "
                     f"({result.test_id}), "
                     + (result.period or "the validation window")),
            kind=kind,
            payload=dict(result.chart),
            note=str(result.chart.get("caption") or "")))
    return out


def _evidence_section(number: str, title: str,
                      results: list[states.Result]) -> report_mod.Section:
    """One numbered section, with its tests, its refusals and its charts."""
    measured = [r for r in results if r.measured]
    adverse = [r for r in results if r.adverse]
    refused = [r for r in results if not r.measured]
    if not results:
        return report_mod.Section(
            number=number, title=title,
            unavailable=("No test in this report addresses this section for "
                         "this model. That is a statement about the test "
                         "registry and this model's capabilities, not a "
                         "finding about the model."))
    narrative = (
        f"{SECTION_PURPOSE.get(number, '')} "
        f"{len(measured)} of {len(results)} tests here produced a number"
        + (f", of which {len(adverse)} fell outside a governed limit."
           if adverse else ", and none fell outside a governed limit.")
        + (f" {len(refused)} could not be measured and each says why."
           if refused else ""))
    return report_mod.Section(
        number=number, title=title, narrative=narrative.strip(),
        figures=_figures_for(results),
        tables=[_table(
            f"{title} — every test, including the refusals",
            RESULT_COLUMNS, _result_rows(results),
            note=("A test that could not run is shown with its reason and no "
                  "value. It is never shown as zero, and it is never "
                  "omitted."))])


def _bin_dictionary(model: model_registry.Model) -> list[report_mod.Table]:
    """The approved bins and the coefficients that score them.

    §15's variable/bin dictionary. Read from the governed specification
    rather than restated here, so the document cannot describe bins the
    engine is not using.
    """
    try:
        spec = model.approved_spec()
    except Exception as problem:  # noqa: BLE001 - an absence is a finding
        return [_table(
            "Variable and bin dictionary", ["Item"],
            [[f"The approved binning specification could not be read: "
              f"{problem}. Without it this document cannot state which bins "
              f"the score is computed over."]])]

    rows: list[list[str]] = []
    for name in (model.binned_variables or tuple(spec.variables)):
        variable = spec.variables.get(name)
        if variable is None:
            rows.append([name, "—", "NOT IN THE APPROVED SPECIFICATION",
                         "—", "—", "—"])
            continue
        for one in variable.bins:
            low = "−∞" if one.lower is None else report_mod.stat(one.lower, 2)
            high = "∞" if one.upper is None else report_mod.stat(one.upper, 2)
            rows.append([
                name, variable.kind, one.label,
                f"{low} to {high}" if not one.special else "special",
                report_mod.stat(one.woe, 4),
                report_mod.percent(one.bad_rate),
            ])
    tables = [_table(
        "Variable and bin dictionary, as approved",
        ["Variable", "Kind", "Bin", "Range", "Weight of evidence",
         "Development bad rate"], rows,
        note=(f"Specification {spec.spec_version}, fitted on "
              f"{spec.development_population or 'an unrecorded population'} "
              f"({spec.development_rows:,} rows, {spec.development_bads:,} "
              "defaults). Read from the governed specification, not restated "
              "here."))]

    try:
        equation = model.approved_equation()
    except Exception:  # noqa: BLE001 - reported by IMPL-REPLICATE, not here
        return tables
    tables.append(_table(
        "Approved coefficients",
        ["Variable", "Coefficient", "Applied to"],
        [[term.variable, report_mod.stat(term.coefficient, 6),
          term.transformation] for term in equation.terms],
        note=(f"Intercept {report_mod.stat(equation.intercept, 6)}, "
              f"{equation.link} link. Score scaling: "
              f"{equation.score_mapping.base_score:.0f} points at "
              f"{equation.score_mapping.base_odds:.0f}:1 odds, "
              f"{equation.score_mapping.pdo:.0f} points to double the odds, "
              f"{equation.score_mapping.score_direction.lower().replace('_', ' ')}"
              ".")))
    return tables


def _method_table(results: list[states.Result]) -> report_mod.Table:
    """Every method actually used on this run, in registry order."""
    rows: list[list[str]] = []
    for test in test_registry.TESTS:
        ran = [r for r in results if r.test_id == test.test_id]
        if not ran:
            continue
        rows.append([test.test_id, test.name, test.method,
                     "; ".join(test.limitations) or "—"])
    return _table(
        "Method and stated limitation, per test",
        ["Test", "Name", "Method", "What it does not tell you"], rows,
        note=("Every test that ran, whether or not it produced a number. A "
              "method a reader cannot reproduce is an assertion."))


def _comment_rows(comments: list[dict]) -> list[list[str]]:
    return [[
        str(one.get("author") or "unattributed"),
        str(one.get("created_at") or "")[:19].replace("T", " "),
        str(one.get("kind") or ""),
        str(one.get("assessment") or "—"),
        str(one.get("severity") or "—"),
        (str(one.get("context", {}).get("test_id"))
         or str(one.get("context", {}).get("category"))
         or str(one.get("target") or "")),
        "resolved" if one.get("resolved") else "open",
        str(one.get("body") or ""),
    ] for one in comments]


COMMENT_COLUMNS = ["Author", "When", "Kind", "Assessment",
                   "Author's severity", "On", "Status", "Comment"]


def _sections(*, model: model_registry.Model,
              results: list[states.Result],
              assessed: list[finding_engine.Finding],
              opinion: str, because: str, stamp: str, generated_by: str,
              run_key: str, window: str, current: str,
              measured: list[states.Result],
              comments: list[dict]) -> list[report_mod.Section]:
    """§15's fifteen sections, filled from results that already exist.

    Nothing here computes anything. Every sentence is assembled out of a
    `Result` or a `Finding` that was produced before the report was asked
    for, which is the property that lets the document be reproduced from its
    own evidence register.
    """
    burning = finding_engine.burning(assessed)
    limitations = list(model.known_limitations)
    by_section: dict[str, list[states.Result]] = {}
    unplaced: list[states.Result] = []
    for result in results:
        where = SECTION_OF_TEST.get(result.test_id)
        if where is None:
            unplaced.append(result)
            continue
        by_section.setdefault(where, []).append(result)

    sections: list[report_mod.Section] = []

    # ---------------------------------------------------------------- 1
    sections.append(report_mod.Section(
        "1", "Document control and review status",
        narrative=("This report was assembled from validation results "
                   "computed before it was requested. Every figure in it "
                   "appears in the evidence register at the back with the "
                   "method that produced it, and every test that ran appears "
                   "in the body whether or not it produced a number."),
        tables=[
            _table(
                "Document control", ["Item", "Value"],
                [["Model", f"{model.name} ({model.model_id})"],
                 ["Approved version", model.version],
                 ["Reference number", model.reference_number],
                 ["Portfolio", model.portfolio],
                 ["Jurisdiction", model.jurisdiction],
                 ["Materiality", model.materiality],
                 ["Tier", model.tier],
                 ["Model owner", model.owner],
                 ["Validation owner", model.validation_owner],
                 ["Matured window (outcome tests)", window or "none"],
                 ["Latest data period (stability tests)", current or "none"],
                 ["Validation population", model.dataset],
                 ["Reference population", model.reference_dataset or "none"],
                 ["Validation run", run_key or
                  "not recorded — generated without a persisted run"],
                 ["Generated at", stamp],
                 ["Generated by", generated_by],
                 ["Calculation version", VALIDATION_REPORT_VERSION]]),
            _table(
                "Review status", ["Stage", "Status", "By"],
                [["Evidence computed", "Complete", generated_by],
                 ["Analyst assessment",
                  f"{sum(1 for c in comments if c.get('kind') == 'ANALYST')} "
                  "recorded",
                  ", ".join(sorted({str(c.get("author") or "")
                                    for c in comments
                                    if c.get("kind") == "ANALYST"})) or "—"],
                 ["Second-line response",
                  f"{sum(1 for c in comments if c.get('kind') == 'REVIEWER')} "
                  "recorded",
                  ", ".join(sorted({str(c.get("author") or "")
                                    for c in comments
                                    if c.get("kind") == "REVIEWER"})) or "—"],
                 ["Approver decision",
                  f"{sum(1 for c in comments if c.get('kind') == 'APPROVER')} "
                  "recorded",
                  ", ".join(sorted({str(c.get("author") or "")
                                    for c in comments
                                    if c.get("kind") == "APPROVER"})) or "—"],
                 ["Document", "DRAFT — for validator review, edit and "
                              "signature", "unsigned"]],
                note=("CreditProbe assembles evidence; it does not issue "
                      "validation opinions, and this document carries no "
                      "signature until a validator adds one."))]))

    # ---------------------------------------------------------------- 2
    sections.append(report_mod.Section(
        "2", "Executive opinion",
        narrative=(
            f"{opinion}. {because} "
            f"{len(measured)} of {len(results)} tests run produced a number; "
            f"{len(assessed)} finding(s) were raised."),
        tables=[_table(
            "Opinion, and what each one means", ["Opinion", "Meaning"],
            [[o, OPINION_MEANING[o]] for o in OPINIONS],
            note=("The opinion is derived from the findings by a rule in "
                  "`validation/report.py::_opinion`, not written. It does "
                  "not approve anything: approval is a committee's act."))]))

    sections.append(report_mod.Section(
        "2.1", "Material findings",
        narrative=(
            "The few a model owner should act on before the others. Short on "
            "purpose: a list of thirty urgent things is a list of nothing "
            "urgent."
            if burning else
            "Nothing on this run requires action ahead of anything else."),
        tables=[_table(
            "Material findings", ["Ref", "Severity", "Finding",
                                  "Remediation"],
            [[f.finding_id, f.severity, f.title, f.remediation]
             for f in burning])] if burning else []))

    sections.append(report_mod.Section(
        "2.2", "Scope limitations",
        narrative=(
            "Stated here rather than at the back. A limitation a reader "
            "finds on the last page has already been read past."
            if limitations else
            "No limitations are recorded on the model registry entry for "
            "this scorecard, which is itself worth a validator's attention: "
            "every model has some."),
        tables=[_table(
            "Recorded limitations", ["Limitation"],
            [[one] for one in limitations] or [["NOT RECORDED"]])]))

    # ---------------------------------------------------------------- 3
    provenance = next((r for r in results
                       if r.test_id == "DATA-PROVENANCE"), None)
    facts: list[list[str]] = [
        ["Intended use", model.intended_use],
        ["Approved version", model.version],
        ["Portfolio and jurisdiction",
         f"{model.portfolio}, {model.jurisdiction}"],
        ["Scorecard type", model.scorecard_type],
        ["Strategy the score feeds", model.intended_use],
        ["Cut-off in force", str(model.cut_off) if model.cut_off is not None
         else "no cut-off is recorded for this model"],
        ["Score range and direction",
         f"{model.score_range[0]:.0f}–{model.score_range[1]:.0f}, "
         f"{model.score_direction.lower().replace('_', ' ')}"],
        ["Scaling", f"{model.base_score:.0f} points at "
                    f"{model.base_odds:.0f}:1 odds, "
                    f"{model.points_to_double_odds:.0f} points to double"],
        ["Development population",
         model.development_population or "NOT RECORDED"],
    ]
    if provenance is not None and provenance.measured:
        for label, value in (
                ("Development window", provenance.reference_period),
                ("Development rows",
                 f"{provenance.observations:,}"),
                ("Development defaults", f"{provenance.events:,}"),
                ("Development event rate",
                 report_mod.percent(provenance.value))):
            facts.append([label, value or "—"])
    sections.append(report_mod.Section(
        "3", "Model purpose, version, strategy and development provenance",
        narrative=(f"{model.intended_use} The model is approved at version "
                   f"{model.version} for {model.portfolio} in "
                   f"{model.jurisdiction}."),
        tables=[_table("The model as registered", ["Item", "Value"], facts)]))

    # ------------------------------------------------------------- 4..12
    for number, title in (
            ("4", "Validation sample, outcome definition, maturity and "
                  "exclusions"),
            ("5", "Data quality and representativeness"),
            ("6", "Univariate and bivariate evidence for the model inputs"),
            ("7", "CSI, PSI and population drift"),
            ("8", "Discrimination, separation and rank ordering"),
            ("9", "Calibration and comparable event rates"),
            ("10", "Stability, robustness and implementation verification"),
            ("11", "Product, classification and cohort performance"),
            ("12", "Usage, overrides and challenger comparison")):
        sections.append(_evidence_section(number, title,
                                          by_section.get(number, [])))

    if unplaced:
        # A registered test with no section is a test whose evidence would
        # vanish from the document. It is reported HERE rather than dropped,
        # and a test asserts this section stays empty.
        sections.append(_evidence_section(
            "12.1", "Tests not yet assigned to a section", unplaced))

    # --------------------------------------------------------------- 13
    linked = [f for f in assessed if f.also_in]
    sections.append(report_mod.Section(
        "13", "Cross-category findings, analyst assessment and review",
        narrative=(
            f"{len(assessed)} finding(s), ordered by severity. Where a "
            "cross-test pattern matched it replaces the single-test findings "
            "it was built from — one problem is one row, not three."
            + (f" {len(linked)} of them is read under more than one category "
               "and carries the same id and the same values in each."
               if linked else "")
            if assessed else
            "No finding. Every measured test is inside its governed limit "
            "and no cross-test pattern matched."),
        tables=([_table("Findings, most severe first", FINDING_COLUMNS,
                        _finding_rows(assessed))] if assessed else [])
        + ([_table(
            "Findings read under more than one category",
            ["Ref", "Owning category", "Also read under", "Finding"],
            [[f.finding_id,
              test_registry.BY_CATEGORY_KEY[f.category].title
              if f.category in test_registry.BY_CATEGORY_KEY else f.category,
              ", ".join(
                  test_registry.BY_CATEGORY_KEY[c].title
                  for c in f.also_in if c in test_registry.BY_CATEGORY_KEY),
              f.title] for f in linked],
            note=("One finding seen from several categories, not several "
                  "findings that agree. The id and the values are the same "
                  "wherever it appears."))] if linked else [])))

    sections.append(report_mod.Section(
        "13.1", "Analyst and reviewer comments",
        narrative=(
            f"{len(comments)} comment(s) recorded against this run. A "
            "system-calculated finding, an analyst's assessment, a "
            "reviewer's response and an approver's decision are different "
            "kinds of statement and are never merged: the kind is on every "
            "row. Where an author gave a severity it is theirs, is labelled "
            "as theirs, and does not change any measured state above."
            if comments else
            "No comment has been recorded against this run. The findings "
            "above are the engine's; nobody has yet written an assessment, a "
            "response or a decision."),
        tables=[_table(
            "Comments recorded against this run", COMMENT_COLUMNS,
            _comment_rows(comments),
            note=("Every comment is attached to this model, this run and "
                  "this test. A comment made against an earlier run is not "
                  "reproduced here."))] if comments else []))

    # --------------------------------------------------------------- 14
    sections.append(report_mod.Section(
        "14", "Remediation actions, owners and proposed due dates",
        narrative=(
            "One row per finding. The owner is taken from the model "
            "registry and the date is PROPOSED — derived from severity, "
            "agreed by nobody. A date this document invents and prints "
            "without that word is how a generated suggestion becomes a "
            "missed deadline."
            if assessed else
            "Nothing to remediate on this run."),
        tables=[_table(
            "Remediation", ["Ref", "Severity", "Action", "Owner",
                            "Proposed due", "Verified by"],
            [[f.finding_id, f.severity, f.remediation,
              model.owner or "NOT RECORDED",
              _due(f.severity, window), f.verify_by]
             for f in assessed],
            note=("Owner is the recorded model owner. Where a finding is a "
                  "data-lineage defect the owner of the feed is the right "
                  "recipient, and this document cannot know who that is. "
                  "Dates are measured from the month after the validation "
                  "window closes, so the same finding keeps the same "
                  "proposed date however often this document is "
                  "regenerated."))]
        if assessed else []))

    # --------------------------------------------------------------- 15
    coverage = regulatory_map.coverage(results)
    sections.append(report_mod.Section(
        "15", "Conclusion, limitations and appendices",
        narrative=(
            f"{opinion}. {because} This conclusion rests on "
            f"{len(measured)} measured results out of {len(results)} tests "
            f"run; the {len(results) - len(measured)} that could not be "
            "measured are listed in the sections above with their reasons "
            "and are not counted as passes.")))

    sections.append(report_mod.Section(
        "15.1", "Limitations of this validation",
        narrative=("Repeated at the back so the document can be read from "
                   "either end."),
        tables=[_table(
            "Recorded limitations", ["Limitation"],
            [[one] for one in limitations] or [["NOT RECORDED"]])]))

    sections.append(report_mod.Section(
        "15.2", "Variable and bin dictionary",
        narrative=("The bins the score is actually computed over, and the "
                   "coefficients applied to them, read from the governed "
                   "specification."),
        tables=_bin_dictionary(model)))

    sections.append(report_mod.Section(
        "15.3", "Method and formulas",
        narrative=("What each test computes, and what it does not tell you. "
                   "A method a reader cannot reproduce is an assertion."),
        tables=[_method_table(results), _table(
            "Formulas used across this report", ["Statistic", "Formula"],
            [["Observed over expected",
              "sum(observed events) / sum(predicted probability), over "
              "comparable observations on one horizon"],
             ["Population stability index (PSI)",
              "sum over bands of (current share − reference share) × "
              "ln(current share / reference share), reference bands fixed "
              "at development"],
             ["Characteristic stability index (CSI)",
              "the same expression over one characteristic's APPROVED bins "
              "rather than over the score's bands"],
             ["Zero-bin smoothing", "an empty bin is floored at 1e-06 before "
                                    "the logarithm, and the floor is applied "
                                    "on both sides"],
             ["Gini", "2 × AUC − 1"],
             ["Kolmogorov–Smirnov",
              "the largest vertical distance between the cumulative "
              "distributions of the defaulted and non-defaulted populations"],
             ["Wilson interval",
              "the 95% score interval on a rate, used rather than the normal "
              "approximation because the normal one runs below zero at the "
              "rates a good scorecard produces in its safest bands"],
             ["Direct standardisation",
              "sum over strata of (development weight × current stratum "
              "rate); the difference from the crude rate is the composition "
              "effect"]])]))

    sections.append(report_mod.Section(
        "15.4", "Trace appendix",
        narrative=("What produced this document, at which versions. A number "
                   "is only reproducible beside the code version that "
                   "produced it."),
        tables=[
            _table("Versions", ["Component", "Version"],
                   [["Test registry", test_registry.REGISTRY_VERSION],
                    ["Result states", states.STATES_VERSION],
                    ["Findings engine", finding_engine.FINDINGS_VERSION],
                    ["Report structure", VALIDATION_REPORT_VERSION],
                    ["Validation run", run_key or "not recorded"],
                    ["Calculation versions used",
                     ", ".join(sorted({r.calculation_version
                                       for r in results
                                       if r.calculation_version})) or "—"]]),
            _table(
                "Supervisory references and the tests that evidence them",
                ["Reference", "Title", "Status", "Measured", "Mapped",
                 "Not measured"],
                [[row["reference"], row["title"], row["status"],
                  str(row["tests_measured"]), str(row["mapped_tests"]),
                  ", ".join(g["test_id"] for g in row["not_measured"]) or "—"]
                 for row in coverage["requirements"]],
                note=coverage["disclaimer"])]))

    return sections


def build(model: model_registry.Model, results: list[states.Result], *,
          generated_by: str = "CreditProbe Scorecard Validation",
          generated_at: str = "",
          windows: tuple[str, str] | None = None,
          run_key: str = "",
          comments: list[dict] | None = None) -> report_mod.Report:
    """Assemble the report. Computes nothing; reads what was computed.

    `generated_at` is an argument rather than a call to `now()` so that a
    test can build the same report twice and compare the content hash. The
    hash excludes the document-control section for exactly this reason, and
    a generator that stamped its own clock would defeat that from the other
    direction.

    `windows` exists for the same reason, one level deeper. `_windows` reads
    the lake to find the matured span, which is correct when the results were
    computed a moment ago and WRONG when they were computed last quarter: a
    report rebuilt from a stored run would print today's window over last
    quarter's numbers, and its report id — which carries the window — would
    change under it. A caller holding a persisted run passes the window that
    run recorded, and the document stops moving.

    `run_key` names the validation run in the DOCUMENT, not only in the
    database row. A committee reading the file has to be able to ask for the
    run behind it; a foreign key they cannot see is a link only an engineer
    can follow.
    """
    assessed = finding_engine.assess(results, model)
    opinion, because = _opinion(assessed, results, model)
    stamp = generated_at or dt.datetime.now(dt.UTC).isoformat(
        timespec="seconds")

    applicable = [r for r in results if r.state != states.NOT_APPLICABLE]
    measured = [r for r in applicable if r.measured]
    window, current = windows if windows is not None else _windows(model)

    sections = _sections(
        model=model, results=results, assessed=assessed, opinion=opinion,
        because=because, stamp=stamp, generated_by=generated_by,
        run_key=run_key, window=window, current=current,
        measured=measured, comments=list(comments or []))

    section_of = {}
    for section in sections:
        for table in section.tables:
            for row in table.rows:
                if row and row[0] in test_registry.BY_ID:
                    section_of[row[0]] = section.number

    made = report_mod.Report(
        report_id=(f"SCV-{model.model_id}-{window or 'no-matured-period'}"
                   f"-{VALIDATION_REPORT_VERSION}"),
        model_id=model.model_id,
        model_version=model.version,
        model_name=model.name,
        scorecard_type=model.scorecard_type,
        model_kind="CHAMPION",
        period=window,
        # The word "draft" is on the cover, not only on the button that
        # produced it. A document that does not announce itself as a draft is
        # the exact artefact that ends up in a committee pack with somebody's
        # name under it — and by then the screen it came from is long gone.
        title=f"{model.name} — independent validation (DRAFT)",
        structure_version=VALIDATION_REPORT_VERSION,
        generated_at=stamp,
        generated_by=generated_by,
        opinion=opinion,
        document_control=[
            ("Model", f"{model.name} ({model.model_id})"),
            ("Version", model.version),
            ("Matured window", window or "none"),
            ("Latest data period", current or "none"),
            ("Generated at", stamp),
            ("Generated by", generated_by),
        ],
        sections=sections,
        evidence=_evidence_register(results, section_of),
    )

    # The content hash, printed where a reader holding only the file can see
    # it. Safe to add AFTER construction and only to section 1, because
    # `Report.content_hash` deliberately excludes section 1 — so stamping it
    # into the document control table cannot change the value it states. Put
    # anywhere else it would hash itself and never settle.
    control = made.section("1")
    if control and control.tables:
        control.tables[0].rows.append(
            ["Content hash (sections 2 onward)", made.content_hash])
    made.document_control.append(("Content hash", made.content_hash))
    return made


def docx(report: report_mod.Report) -> bytes:
    """The report as .docx, through the writer the product already has."""
    from backend.scorecard import report_docx

    return report_docx.write(report)


__all__ = [
    "DO_NOT_USE_UNTIL_REMEDIATED", "INSUFFICIENT_EVIDENCE",
    "MINIMUM_MEASURED_SHARE", "NOT_READY", "OPINIONS", "OPINION_MEANING",
    "READY", "USE_AS_IS", "USE_WITH_CONDITIONS",
    "VALIDATION_REPORT_VERSION", "build", "docx",
]
