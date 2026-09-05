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


def _category_sections(number: str, results: list[states.Result]
                       ) -> list[report_mod.Section]:
    """One numbered subsection per validation category."""
    out: list[report_mod.Section] = []
    by_category: dict[str, list[states.Result]] = {}
    for result in results:
        test = test_registry.BY_ID.get(result.test_id)
        if test is None:
            continue
        by_category.setdefault(test.category, []).append(result)

    index = 0
    for category in test_registry.CATEGORIES:
        found = by_category.get(category)
        if not found:
            continue
        index += 1
        definition = test_registry.BY_CATEGORY_KEY[category]
        measured = [r for r in found if r.measured]
        adverse = [r for r in found if r.adverse]
        narrative = (
            f"{definition.purpose} {len(measured)} of {len(found)} tests in "
            f"this category produced a number"
            + (f", of which {len(adverse)} fell outside a governed limit."
               if adverse else ", and none fell outside a governed limit.")
            + (f" The remaining {len(found) - len(measured)} could not be "
               "measured; the reason is on each row."
               if len(measured) < len(found) else ""))
        out.append(report_mod.Section(
            number=f"{number}.{index}", title=definition.title,
            narrative=narrative,
            tables=[_table(
                f"{definition.title} — every test, including the refusals",
                RESULT_COLUMNS, _result_rows(found),
                note=("A test that could not run is shown with its reason "
                      "and no value. It is never shown as zero."))]))
    return out


def _finding_rows(assessed: list[finding_engine.Finding]) -> list[list[str]]:
    return [[
        made.finding_id, made.severity, made.title, made.what,
        made.remediation, made.verify_by,
        ", ".join(made.evidence), ", ".join(made.cbuae) or "—",
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


def build(model: model_registry.Model, results: list[states.Result], *,
          generated_by: str = "CreditProbe Scorecard Validation",
          generated_at: str = "") -> report_mod.Report:
    """Assemble the report. Computes nothing; reads what was computed.

    `generated_at` is an argument rather than a call to `now()` so that a
    test can build the same report twice and compare the content hash. The
    hash excludes the document-control section for exactly this reason, and
    a generator that stamped its own clock would defeat that from the other
    direction.
    """
    assessed = finding_engine.assess(results, model)
    opinion, because = _opinion(assessed, results, model)
    stamp = generated_at or dt.datetime.now(dt.UTC).isoformat(
        timespec="seconds")

    applicable = [r for r in results if r.state != states.NOT_APPLICABLE]
    measured = [r for r in applicable if r.measured]
    window, current = _windows(model)

    sections: list[report_mod.Section] = [
        report_mod.Section(
            "1", "Document control",
            narrative=("This report was assembled from validation results "
                       "computed before it was requested. Every figure in it "
                       "appears in the evidence register at the back with "
                       "the method that produced it."),
            tables=[_table(
                "Document control", ["Item", "Value"],
                [["Model", f"{model.name} ({model.model_id})"],
                 ["Approved version", model.version],
                 ["Reference number", model.reference_number],
                 ["Portfolio", model.portfolio],
                 ["Materiality", model.materiality],
                 ["Tier", model.tier],
                 ["Model owner", model.owner],
                 ["Validation owner", model.validation_owner],
                 ["Matured window (outcome tests)", window or "none"],
                 ["Latest data period (stability tests)",
                  current or "none"],
                 ["Generated at", stamp],
                 ["Generated by", generated_by],
                 ["Calculation version", VALIDATION_REPORT_VERSION]])]),

        report_mod.Section(
            "2", "Validation opinion",
            narrative=f"{opinion}. {because}",
            tables=[_table(
                "Opinion, and what each one means", ["Opinion", "Meaning"],
                [[o, OPINION_MEANING[o]] for o in OPINIONS],
                note=("The opinion is derived from the findings by a rule in "
                      "`validation/report.py::_opinion`, not written. It does "
                      "not approve anything: approval is a committee's act."))]),

        report_mod.Section(
            "3", "Scope, purpose and approved use",
            narrative=(f"{model.intended_use} The model is approved at "
                       f"version {model.version} for {model.portfolio} in "
                       f"{model.jurisdiction}. Its default definition is: "
                       f"{model.default_definition}"),
            tables=[_table(
                "What this validation covered", ["Item", "Value"],
                [["Tests defined", str(len(test_registry.TESTS))],
                 ["Tests applicable to this model",
                  str(len(model.applicable_tests()))],
                 ["Tests run", str(len(results))],
                 ["Tests that produced a number", str(len(measured))],
                 ["Observation window", model.observation_window],
                 ["Matured window (outcome tests)", window or "none"],
                 ["Latest data period (stability tests)", current or "none"],
                 ["Performance window (months)",
                  str(model.performance_window_months)],
                 ["Development population", model.development_population
                  or "NOT RECORDED"]])]),
    ]

    limitations = list(model.known_limitations)
    sections.append(report_mod.Section(
        "4", "Limitations of this validation",
        narrative=(
            "Stated first rather than last. A limitation a reader finds at "
            "the back of a document has already been read past."
            if limitations else
            "No limitations are recorded on the model registry entry for "
            "this scorecard, which is itself worth a validator's attention: "
            "every model has some."),
        tables=[_table(
            "Recorded limitations", ["Limitation"],
            [[one] for one in limitations] or [["NOT RECORDED"]])]))

    sections.append(report_mod.Section(
        "5", "Findings",
        narrative=(
            f"{len(assessed)} finding(s). The list is ordered by severity, "
            "and where a cross-test pattern matched it replaces the "
            "single-test findings it was built from — one problem is one "
            "row, not three."
            if assessed else
            "No finding. Every measured test is inside its governed limit "
            "and no cross-test pattern matched."),
        tables=[_table(
            "Findings, most severe first", FINDING_COLUMNS,
            _finding_rows(assessed))] if assessed else []))

    burning = finding_engine.burning(assessed)
    sections.append(report_mod.Section(
        "5.1", "What to do first",
        narrative=(
            "The few a model owner should act on before the others. Short on "
            "purpose: a list of thirty urgent things is a list of nothing "
            "urgent."
            if burning else
            "Nothing on this run requires action ahead of anything else."),
        tables=[_table(
            "Priority", ["Ref", "Severity", "Finding", "Remediation"],
            [[f.finding_id, f.severity, f.title, f.remediation]
             for f in burning])] if burning else []))

    sections.append(report_mod.Section(
        "6", "Results by category",
        narrative=("Every test, in every category, including the ones that "
                   "refused. A validation report that omits what it could "
                   "not measure is a report whose scope the reader has to "
                   "guess at.")))
    sections.extend(_category_sections("6", results))

    coverage = regulatory_map.coverage(results)
    sections.append(report_mod.Section(
        "7", "Where the evidence sits",
        narrative=coverage["disclaimer"],
        tables=[_table(
            "Supervisory references and the tests that evidence them",
            ["Reference", "Title", "Status", "Measured", "Mapped",
             "Not measured"],
            [[row["reference"], row["title"], row["status"],
              str(row["tests_measured"]), str(row["mapped_tests"]),
              ", ".join(g["test_id"] for g in row["not_measured"]) or "—"]
             for row in coverage["requirements"]],
            note=("Status describes this engine's own output on this run. It "
                  "is not a compliance assessment, and this product has no "
                  "standing to make one."))]))

    section_of = {}
    for section in sections:
        for table in section.tables:
            for row in table.rows:
                if row and row[0] in test_registry.BY_ID:
                    section_of[row[0]] = section.number

    return report_mod.Report(
        report_id=(f"SCV-{model.model_id}-{window or 'no-matured-period'}"
                   f"-{VALIDATION_REPORT_VERSION}"),
        model_id=model.model_id,
        model_version=model.version,
        model_name=model.name,
        scorecard_type=model.scorecard_type,
        model_kind="CHAMPION",
        period=window,
        title=f"{model.name} — independent validation",
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
