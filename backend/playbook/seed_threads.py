"""
The three demonstration workspaces. Playbook §13.

IFRS 9 Committee Report, Application Scorecard Model Development Report, and
Behavioural Scorecard Validation Report — each a complete, resumable history
with real input files, real generated documents and two genuinely different
versions.

Two rules this module keeps, and why
------------------------------------
**No provider call.** `backend/demo/seed.py` states it for the rest of the
product: pre-answering the questions a presenter is about to ask live is exactly
what a demonstration must not do. So every document here is rendered by
`backend/playbook/render`, deterministically, and every assistant turn is stored
with `origin="seed_fixture"`.

**No model attribution.** §13 forbids presenting synthetic fixture text as
something a model wrote. The origin column carries that, the interface shows it,
and the model column stays empty — a seeded turn has no model because no model
produced it.

The input files are generated rather than committed. A test that reads a binary
nobody can regenerate is a test whose failure nobody can diagnose, and the same
is true of a demonstration.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from backend.playbook import document as D
from backend.playbook.fixtures import ecl_oracle as ecl
from backend.playbook.fixtures import scorecard as sc

PRIOR = ecl.PRIOR_PERIOD
CURRENT = ecl.CURRENT_PERIOD


# --------------------------------------------------------------------------
# Input documents, built here so they can always be rebuilt
# --------------------------------------------------------------------------


def prior_committee_report() -> bytes:
    """The previous quarter's committee report, as a real Word file."""
    from docx import Document

    head = ecl.headline()
    doc = Document()
    doc.core_properties.title = f"IFRS 9 Committee Report — {PRIOR}"
    doc.core_properties.author = "Credit Risk"
    doc.sections[0].header.paragraphs[0].text = (
        f"IFRS 9 Committee Report — {PRIOR}  ·  Demo · synthetic")

    doc.add_heading(f"IFRS 9 Committee Report — {PRIOR}", level=0)
    doc.add_heading("1. Executive summary", level=1)
    doc.add_paragraph(
        f"Probability-weighted ECL for {PRIOR} was SAR "
        f"{head['weighted_ecl_prior'].rounded} million against exposure of SAR "
        f"1,000.00 million, a coverage ratio of "
        f"{head['coverage_prior'].rounded} per cent. Scenario weights were "
        "unchanged at 60/15/25.")
    doc.add_heading("2. Scenario results", level=1)
    table = doc.add_table(rows=5, cols=2)
    for r, (a, b) in enumerate([("Scenario", "ECL, SAR million"),
                                ("Base", "18.00"), ("Upturn", "14.00"),
                                ("Downturn", "32.00"),
                                ("Weighted", str(head["weighted_ecl_prior"].rounded))]):
        table.rows[r].cells[0].text = a
        table.rows[r].cells[1].text = b
    doc.add_heading("3. Staging", level=1)
    doc.add_paragraph(
        "Stage 2 exposure was SAR 72.00 million. Stage 3 was SAR 12.00 million.")
    doc.add_heading("4. Model monitoring", level=1)
    doc.add_paragraph(
        "Model monitoring was performed. Results are held by Model Risk.")
    doc.add_heading("5. Limitations", level=1)
    doc.add_paragraph(
        "This report does not cover post-model adjustments.")

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def current_results_workbook() -> bytes:
    """The current quarter's results, with a hidden working sheet.

    The hidden sheet is deliberate. A demonstration in which every source reads
    perfectly never shows the product doing the honest thing about a gap, and
    the gap is the interesting part.
    """
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "ECL"
    for row in [["Scenario", "ECL, SAR million", "Weight"],
                ["Base", 19.20, 0.60], ["Upturn", 15.00, 0.15],
                ["Downturn", 36.00, 0.25]]:
        ws.append(row)

    exposure = wb.create_sheet("Exposure")
    exposure.append(["Period", "Exposure, SAR million"])
    exposure.append([PRIOR, 1000.00])
    exposure.append([CURRENT, 1050.00])

    staging = wb.create_sheet("Staging")
    staging.append(["Stage", PRIOR, CURRENT])
    staging.append(["Stage 1", 916.00, 896.00])
    staging.append(["Stage 2", 72.00, 113.00])
    staging.append(["Stage 3", 12.00, 12.00])

    working = wb.create_sheet("Working")
    working.append(["intermediate", 1])
    working.sheet_state = "hidden"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def ecl_methodology() -> bytes:
    """The methodology a coverage check is run against."""
    from docx import Document

    doc = Document()
    doc.core_properties.title = "IFRS 9 ECL Methodology v4.2"
    doc.add_heading("IFRS 9 ECL Methodology v4.2", level=0)
    for topic, body in [
        ("Scenario design and weighting",
         "Three scenarios are maintained. Weights are reviewed annually and "
         "reported in every committee paper."),
        ("Staging criteria and SICR",
         "Significant increase in credit risk is assessed against origination. "
         "Stage movements are reported by direction and by cause."),
        ("Post-model adjustments",
         "Every post-model adjustment is documented with its rationale, its "
         "quantum and its expected removal date, and reported to committee."),
        ("Model monitoring and validation",
         "Monitoring results are reported quarterly with the underlying "
         "evidence, not by reference."),
    ]:
        doc.add_heading(topic, level=1)
        doc.add_paragraph(body)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def application_design_document() -> bytes:
    """The application scorecard's design reference."""
    from docx import Document

    doc = Document()
    doc.core_properties.title = "Application Scorecard — Model Design"
    doc.add_heading("Application Scorecard — Model Design", level=0)
    doc.add_heading("1. Purpose and scope", level=1)
    doc.add_paragraph(
        "The application scorecard ranks new retail applicants by the "
        "probability of default within twelve months of booking.")
    doc.add_heading("2. Development sample", level=1)
    doc.add_paragraph(
        f"The development sample holds {sc.GOODS + sc.BADS:,} accounts with a "
        f"bad rate of {sc.development().bad_rate * 100:.2f} per cent.")
    doc.add_heading("3. Characteristic selection", level=1)
    doc.add_paragraph(
        "Characteristics are selected on information value, monotonicity of "
        "the weight-of-evidence transformation, and business rationale.")
    doc.add_heading("4. Required evidence", level=1)
    doc.add_paragraph(
        "A development report must present discrimination, calibration by "
        "score band, characteristic evidence and an implementation test.")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def validation_standard() -> bytes:
    """The standard a behavioural validation report is written against."""
    from docx import Document

    doc = Document()
    doc.core_properties.title = "Model Validation Standard"
    doc.add_heading("Model Validation Standard", level=0)
    for topic, body in [
        ("Discrimination", "Report AUC, Gini and KS against approved limits."),
        ("Calibration", "Report observed against expected by score band."),
        ("Population stability", "Report PSI against the development sample."),
        ("Characteristic stability", "Report CSI for every characteristic."),
        ("Segment performance",
         "Report discrimination by segment, and say where a segment is too "
         "small to assess rather than reporting an unstable estimate."),
        ("Override analysis",
         "Report override rates and their outcomes."),
    ]:
        doc.add_heading(topic, level=1)
        doc.add_paragraph(body)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@dataclass
class SourceSpec:
    filename: str
    content: bytes
    role: str


@dataclass
class Turn:
    role: str
    text: str
    #: Set on the assistant turn that produced a version.
    version: int | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class ThreadSpec:
    key: str
    title: str
    document_family: str
    summary: str
    sources: list[SourceSpec]
    #: Titles of demonstration exports to attach, matched exactly.
    export_titles: list[str]
    turns: list[Turn]
    v1: D.Document
    v2: D.Document
    v2_summary: str
    change_items: list[dict]
    #: Which of the proposed changes the demonstration user approved.
    approved: list[str]
    deck_from_v2: bool = True


# --------------------------------------------------------------------------
# The documents each thread produced, as two genuinely different versions
# --------------------------------------------------------------------------


def _ifrs9_v1() -> D.Document:
    head = ecl.headline()
    doc = D.parse(f"""# IFRS 9 Committee Report — {CURRENT}

## 1. Executive summary

Probability-weighted ECL rose to SAR {head['weighted_ecl_current'].rounded} \
million from SAR {head['weighted_ecl_prior'].rounded} million, an increase of \
SAR {head['weighted_ecl_movement'].rounded} million or \
{head['weighted_ecl_percent_change'].rounded} per cent. Coverage rose \
{head['coverage_movement_bps'].rounded} basis points to \
{head['coverage_current'].rounded} per cent on exposure of SAR 1,050.00 million.

Scenario weights were unchanged at 60/15/25, so the movement is a change in \
scenario outcomes rather than in how they are weighted.

## 2. Scenario results

| Scenario | Weight | {PRIOR} | {CURRENT} |
| --- | --- | --- | --- |
| Base | 60% | 18.00 | 19.20 |
| Upturn | 15% | 14.00 | 15.00 |
| Downturn | 25% | 32.00 | 36.00 |
| Weighted | 100% | {head['weighted_ecl_prior'].rounded} | \
{head['weighted_ecl_current'].rounded} |

## 3. Staging

Stage 2 exposure rose from SAR 72.00 million to SAR 113.00 million. Stage 3 was \
unchanged at SAR 12.00 million.

## 4. Drivers

PD migration accounts for SAR 1.11 million of the increase, LGD revision for \
SAR 0.42 million and exposure growth for SAR 0.34 million.

## 5. Limitations

This report does not cover post-model adjustments.
""")
    doc.subtitle = "Prepared for the Credit Risk Committee"
    doc.meta = {"reporting_period": CURRENT, "currency": "SAR million",
                "basis": "Demo · synthetic data"}
    return doc


def _ifrs9_v2() -> D.Document:
    """Version 2 after three of five proposed changes were approved.

    The differences are real and are exactly the three that were approved: the
    executive summary is sharpened, a concentration section is added, and the
    limitation about post-model adjustments is expanded. Model monitoring and
    the staging commentary — changes 4 and 5 — are deliberately NOT applied.
    """
    head = ecl.headline()
    doc = D.parse(f"""# IFRS 9 Committee Report — {CURRENT}

## 1. Executive summary

Weighted ECL rose {head['weighted_ecl_percent_change'].rounded} per cent to SAR \
{head['weighted_ecl_current'].rounded} million. Coverage rose \
{head['coverage_movement_bps'].rounded} basis points to \
{head['coverage_current'].rounded} per cent. The movement is concentrated in \
one sector rather than broad-based, and PD migration accounts for most of it.

Scenario weights were unchanged at 60/15/25.

## 2. Scenario results

| Scenario | Weight | {PRIOR} | {CURRENT} |
| --- | --- | --- | --- |
| Base | 60% | 18.00 | 19.20 |
| Upturn | 15% | 14.00 | 15.00 |
| Downturn | 25% | 32.00 | 36.00 |
| Weighted | 100% | {head['weighted_ecl_prior'].rounded} | \
{head['weighted_ecl_current'].rounded} |

## 3. Staging

Stage 2 exposure rose from SAR 72.00 million to SAR 113.00 million. Stage 3 was \
unchanged at SAR 12.00 million.

## 4. Drivers

PD migration accounts for SAR 1.11 million of the increase, LGD revision for \
SAR 0.42 million and exposure growth for SAR 0.34 million.

## 5. Concentration

Contracting rose to 24.8 per cent of exposure from 23.1 per cent. The sector \
whose concentration rose is also the sector driving the ECL movement and the \
one at the top of the watchlist, which is the combination worth the \
committee's attention.

## 6. Limitations

This report does not cover post-model adjustments. The ECL methodology requires \
every post-model adjustment to be documented with its rationale, its quantum \
and its expected removal date, and none of that is presented here. The gap is \
material and is not closed by this version.
""")
    doc.subtitle = "Prepared for the Credit Risk Committee"
    doc.meta = {"reporting_period": CURRENT, "currency": "SAR million",
                "basis": "Demo · synthetic data"}
    return doc


def _application_v1() -> D.Document:
    stats = sc.headline()
    doc = D.parse(f"""# Application Scorecard — Model Development Report

## 1. Scope and purpose

The application scorecard ranks new retail applicants by the probability of \
default within twelve months of booking.

## 2. Development sample

The development sample holds {sc.GOODS + sc.BADS:,} accounts at a bad rate of \
{stats['development_bad_rate']} per cent.

## 3. Discrimination

| Statistic | Development | Limit |
| --- | --- | --- |
| AUC | {stats['development_auc']} | 0.725 |
| Gini | {stats['development_gini']} | 0.450 |
| KS | {stats['development_ks']} | 0.300 |

## 4. Characteristics

Eleven characteristics entered the final model, each with a monotone \
weight-of-evidence transformation and a documented rationale. Information \
values range from 0.09 to 0.41.

## 5. Limitations

An implementation test has not been performed and is not presented here.
""")
    doc.subtitle = "Model Development"
    doc.meta = {"model_kind": "application", "basis": "Demo · synthetic data"}
    return doc


def _application_v2() -> D.Document:
    stats = sc.headline()
    doc = D.parse(f"""# Application Scorecard — Model Development Report

## 1. Scope and purpose

The application scorecard ranks new retail applicants by the probability of \
default within twelve months of booking.

## 2. Development sample

The development sample holds {sc.GOODS + sc.BADS:,} accounts at a bad rate of \
{stats['development_bad_rate']} per cent.

## 3. Discrimination

| Statistic | Development | Limit |
| --- | --- | --- |
| AUC | {stats['development_auc']} | 0.725 |
| Gini | {stats['development_gini']} | 0.450 |
| KS | {stats['development_ks']} | 0.300 |

## 4. Calibration by score band

| Band | Accounts | Bads | Bad rate % |
| --- | --- | --- | --- |
""" + "\n".join(
        "| " + " | ".join(row) + " |" for row in sc.band_performance(sc.development())
    ) + """

Observed bad rates fall monotonically across all six bands.

## 5. Characteristics

Eleven characteristics entered the final model, each with a monotone \
weight-of-evidence transformation and a documented rationale. Information \
values range from 0.09 to 0.41.

## 6. Limitations

An implementation test has not been performed and is not presented here. The \
design document requires one before the model is approved for use, so this \
report cannot support an approval decision on its own.
""")
    doc.subtitle = "Model Development"
    doc.meta = {"model_kind": "application", "basis": "Demo · synthetic data"}
    return doc


def _behavioural_v1() -> D.Document:
    stats = sc.headline()
    doc = D.parse(f"""# Behavioural Scorecard — Validation Report

## 1. Scope

This report validates the behavioural scorecard for {CURRENT} against the \
Model Validation Standard.

## 2. Data and population

The validation sample holds {sc.GOODS + sc.BADS:,} accounts at a bad rate of \
{stats['recent_bad_rate']} per cent.

## 3. Discrimination

| Statistic | Development | {CURRENT} | Limit |
| --- | --- | --- | --- |
| AUC | {stats['development_auc']} | {stats['recent_auc']} | 0.725 |
| Gini | {stats['development_gini']} | {stats['recent_gini']} | 0.450 |
| KS | {stats['development_ks']} | {stats['recent_ks']} | 0.300 |

Discrimination remains above the approved floor.

## 4. Population stability

PSI against the development sample is {stats['psi']}, below the 0.10 \
investigation threshold.

## 5. Findings

Three findings are open. Two concern documentation. The third concerns the \
Contracting-employed segment, which is too small to assess reliably.

## 6. Limitations

Override analysis is required by the Model Validation Standard and no override \
evidence was supplied, so it is not presented here.
""")
    doc.subtitle = f"Validation for {CURRENT}"
    doc.meta = {"model_kind": "behavioural", "reporting_period": CURRENT,
                "basis": "Demo · synthetic data"}
    return doc


def _behavioural_v2() -> D.Document:
    stats = sc.headline()
    doc = D.parse(f"""# Behavioural Scorecard — Validation Report

## 1. Scope

This report validates the behavioural scorecard for {CURRENT} against the \
Model Validation Standard.

## 2. Data and population

The validation sample holds {sc.GOODS + sc.BADS:,} accounts at a bad rate of \
{stats['recent_bad_rate']} per cent.

## 3. Discrimination

| Statistic | Development | {CURRENT} | Limit |
| --- | --- | --- | --- |
| AUC | {stats['development_auc']} | {stats['recent_auc']} | 0.725 |
| Gini | {stats['development_gini']} | {stats['recent_gini']} | 0.450 |
| KS | {stats['development_ks']} | {stats['recent_ks']} | 0.300 |

Discrimination remains above the approved floor. The fall from development is \
gradual rather than a step change.

## 4. Calibration by score band

| Band | Accounts | Bads | Bad rate % |
| --- | --- | --- | --- |
""" + "\n".join(
        "| " + " | ".join(row) + " |" for row in sc.band_performance(sc.recent())
    ) + f"""

Observed bad rates fall monotonically across all six bands, so there is no \
evidence of a rank-order failure in the range the book occupies.

## 5. Population stability

PSI against the development sample is {stats['psi']}, below the 0.10 \
investigation threshold. The largest single band contribution comes from the \
640–699 band.

## 6. Findings

Three findings are open. Two concern documentation. The third concerns the \
Contracting-employed segment, where the population is too small for a stable \
Gini estimate — the finding is that the segment cannot be assessed, not that \
the scorecard fails on it.

## 7. Limitations

Override analysis is required by the Model Validation Standard and no override \
evidence was supplied, so it is not presented here. That is a gap in the \
evidence rather than a finding about the model, and it should be closed before \
the next cycle.
""")
    doc.subtitle = f"Validation for {CURRENT}"
    doc.meta = {"model_kind": "behavioural", "reporting_period": CURRENT,
                "basis": "Demo · synthetic data"}
    return doc


# --------------------------------------------------------------------------
# The three histories
# --------------------------------------------------------------------------


def _ifrs9_thread() -> ThreadSpec:
    head = ecl.headline()
    return ThreadSpec(
        key="ifrs9_committee_report",
        title=f"IFRS 9 Committee Report — {CURRENT}",
        document_family="ifrs9_committee_report",
        summary=(
            "Version 2 issued. Three of five proposed changes applied; model "
            "monitoring and staging commentary were not."),
        sources=[
            SourceSpec(f"ifrs9-committee-report-{PRIOR.replace(' ', '-').lower()}.docx",
                       prior_committee_report(), "previous_report"),
            SourceSpec(f"ecl-results-{CURRENT.replace(' ', '-').lower()}.xlsx",
                       current_results_workbook(), "results"),
            SourceSpec("ifrs9-ecl-methodology-v4.2.docx",
                       ecl_methodology(), "methodology"),
        ],
        export_titles=[
            f"Quarter-on-quarter ECL movement, {CURRENT}",
            f"Stage migration, {CURRENT}",
            f"Coverage ratio movement, {CURRENT}",
            f"Sector concentration, {CURRENT}",
            "Methodology coverage review — IFRS 9",
        ],
        turns=[
            Turn("user",
                 f"I've attached last quarter's committee report, the {CURRENT} "
                 "results workbook and the ECL methodology. Before you change "
                 "anything: what's out of date, what's missing, and what does "
                 "the methodology ask for that the report doesn't do?"),
            Turn("assistant",
                 f"""I read all three. One gap in what I could read first: the results workbook has a hidden sheet named "Working" which I did not read, so nothing below rests on it.

**What is out of date**

The {PRIOR} report states weighted ECL of SAR {head['weighted_ecl_prior'].rounded} million and coverage of {head['coverage_prior'].rounded} per cent. The {CURRENT} workbook gives SAR {head['weighted_ecl_current'].rounded} million and {head['coverage_current'].rounded} per cent — a movement of SAR {head['weighted_ecl_movement'].rounded} million, or {head['weighted_ecl_percent_change'].rounded} per cent. Staging has moved too: Stage 2 from SAR 72.00 million to SAR 113.00 million.

**What the methodology asks for and the report does not do**

Post-model adjustments. The methodology requires each one documented with rationale, quantum and expected removal date, reported to committee. The {PRIOR} report has one sentence saying they are not covered. That is a material gap rather than a stylistic one.

Model monitoring is partially covered: the report says monitoring was performed and refers the evidence to Model Risk. The methodology asks for the evidence in the paper.

**What I have not checked**

Whether the post-model adjustments exist at all. Nothing attached tells me that."""),
            Turn("user",
                 "Good. Give me a numbered change proposal — target section, "
                 "evidence, and what you'd write. Don't edit anything yet."),
            Turn("assistant",
                 """Five changes, in the order I would make them.

1. **Section 1, executive summary** — update every figure to the current period and lead with the movement rather than the level. Evidence: the results workbook, ECL and Exposure sheets.
2. **Section 2, scenario results** — replace the table with current-period figures alongside prior, keeping the comparison column. Evidence: workbook, ECL sheet.
3. **New section, concentration** — the sector whose concentration rose is the sector driving the movement and the one at the top of the watchlist. No current section says so. Evidence: the sector concentration and stage migration analyses.
4. **Section 4, model monitoring** — present the monitoring evidence in the paper rather than referring it out, as the methodology requires. Evidence: methodology v4.2, section 4.
5. **Section 5, limitations** — expand the post-model adjustment sentence into the documented treatment the methodology asks for. Evidence: methodology v4.2, section 3.

Item 4 depends on monitoring evidence that is not attached. I can restructure the section, but I cannot populate it from what I have."""),
            Turn("user",
                 "Apply 1, 2, 3 and 5. Not 4 — we don't have the monitoring "
                 "evidence yet and I'd rather the gap stayed visible. Give me "
                 "a new version and tell me exactly what changed."),
            Turn("assistant",
                 f"""Version 2 is ready. Word and PDF are attached.

**Applied**

1. Executive summary now leads with the movement: up {head['weighted_ecl_percent_change'].rounded} per cent to SAR {head['weighted_ecl_current'].rounded} million, coverage up {head['coverage_movement_bps'].rounded} basis points.
2. Scenario table carries both periods, comparison column kept.
3. New Section 5, Concentration.
5. Limitations now states what the methodology requires for post-model adjustments and that none of it is presented — so the gap reads as a gap.

**Not applied**

4. Model monitoring is unchanged, as you asked. The section still refers the evidence out.

**Unchanged**

Sections 3 and 4 of the original are carried through untouched. Every figure in version 2 traces to the workbook or to an attached analysis.""",
                 version=2,
                 notes=["Version 2 renders from the same document as version 1, "
                        "so the Word file and the PDF state the same figures."]),
            Turn("user",
                 "Sharpen the executive summary. More concise, more direct, "
                 "formal committee register. Don't change any figure or any "
                 "other section."),
            Turn("assistant",
                 """Done, and confined to Section 1. Every figure is unchanged, both other sections are byte-for-byte as they were, and the coverage and ECL conclusions read the same. The summary is now three sentences rather than five and leads with the movement."""),
            Turn("user", "What's still open?"),
            Turn("assistant",
                 """Two things.

**Post-model adjustments.** The report now says clearly that the methodology requires documented adjustments and that none are presented. That closes the honesty gap, not the evidence gap.

**Model monitoring.** Section 4 still refers evidence to Model Risk. You held change 4 deliberately; it will need the monitoring pack before it can be applied.

One thing I did not read at all: the hidden "Working" sheet in the results workbook. If anything in it matters, nothing in this report reflects it."""),
            Turn("user", "Turn the current version into a committee deck."),
            Turn("assistant",
                 """The deck is attached, built from version 2. Native editable text and tables — nothing is a picture of a table.

Seven slides: the movement, scenario results, staging, drivers, concentration, limitations, and sources. The post-model adjustment gap is on the limitations slide rather than in the notes, because a committee that only reads the slides should still see it.

Every figure matches the report it came from."""),
        ],
        v1=_ifrs9_v1(),
        v2=_ifrs9_v2(),
        v2_summary=("Applied changes 1, 2, 3 and 5. Change 4, model monitoring, "
                    "was held at the user's request."),
        change_items=[
            {"stable_id": "chg-exec-summary", "display_number": 1,
             "target_section": "1. Executive summary",
             "rationale": "Every figure is from the prior period.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["xlsx://ECL!A1", "xlsx://Exposure!A1"]}},
            {"stable_id": "chg-scenario-table", "display_number": 2,
             "target_section": "2. Scenario results",
             "rationale": "The table shows only the prior period.",
             "proposed": {"kind": "table"},
             "evidence": {"locators": ["xlsx://ECL!A1"]}},
            {"stable_id": "chg-concentration", "display_number": 3,
             "target_section": "New — Concentration",
             "rationale": "No section connects concentration to the movement.",
             "proposed": {"kind": "insert"},
             "evidence": {"locators": ["export://sector_concentration"]}},
            {"stable_id": "chg-monitoring", "display_number": 4,
             "target_section": "4. Model monitoring",
             "rationale": "The methodology asks for evidence in the paper.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["docx://para/12"]},
             "depends_on": ["monitoring-pack"]},
            {"stable_id": "chg-limitations", "display_number": 5,
             "target_section": "5. Limitations",
             "rationale": "Post-model adjustments are named but not treated.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["docx://para/8"]}},
        ],
        approved=["chg-exec-summary", "chg-scenario-table", "chg-concentration",
                  "chg-limitations"],
    )


def _application_thread() -> ThreadSpec:
    stats = sc.headline()
    return ThreadSpec(
        key="application_development_report",
        title="Application Scorecard Model Development Report",
        document_family="application_development_report",
        summary=("Version 2 issued with calibration added. The implementation "
                 "test is still absent and the report says so."),
        sources=[
            SourceSpec("application-scorecard-design.docx",
                       application_design_document(), "methodology"),
            SourceSpec("application-development-sample.xlsx",
                       current_results_workbook(), "results"),
            SourceSpec("model-validation-standard.docx",
                       validation_standard(), "methodology"),
        ],
        export_titles=[
            "Application scorecard — variable and score band evidence",
            f"Discrimination, behavioural scorecard, {CURRENT}",
            f"Calibration by score band, {CURRENT}",
            f"Characteristic stability, {CURRENT}",
        ],
        turns=[
            Turn("user",
                 "I need a model development report for the application "
                 "scorecard. I've attached the design document and the "
                 "development evidence. There's no template — write it properly."),
            Turn("assistant",
                 f"""Drafted. Word and PDF attached.

I inferred the structure from the design document's section 4, which names the evidence a development report must present: discrimination, calibration by score band, characteristic evidence and an implementation test.

**What the evidence supports**

Discrimination: AUC {stats['development_auc']}, Gini {stats['development_gini']}, KS {stats['development_ks']} — all above their limits. Eleven characteristics, all monotone, information values 0.09 to 0.41.

**What it does not**

There is no implementation test in anything attached. I have not written that section and I have not implied it passed. Section 5 says it has not been performed."""),
            Turn("user",
                 "Right — no implementation test yet. What about calibration? "
                 "The design doc asks for it."),
            Turn("assistant",
                 """It does, and I did not include it in the first draft because I had not confirmed the band definitions. The attached development evidence does carry observed performance by score band, so I can present it.

Six bands, and the observed bad rate falls monotonically across all of them. That is the ordering calibration requires, and it is worth stating explicitly rather than leaving the reader to check the table."""),
            Turn("user", "Add it as its own section."),
            Turn("assistant",
                 """Version 2 is ready, with calibration as Section 4 and the later sections renumbered.

**Changed**
- New Section 4, calibration by score band, with the observed bad rate for each of the six bands.
- Section 6, limitations, now says the implementation test is required by the design document before approval, so the report cannot support an approval decision on its own.

**Unchanged**
- Scope, development sample, discrimination and characteristics are exactly as they were.""",
                 version=2),
            Turn("user",
                 "Does the validation standard ask for anything this report "
                 "doesn't have?"),
            Turn("assistant",
                 """Yes, two things — and one of them is not this report's job.

**Override analysis.** The standard requires override rates and outcomes. A development report would not normally carry it, but the standard does not exempt one. Nothing attached has override data.

**Segment performance.** The standard asks for discrimination by segment, and says explicitly to report where a segment is too small to assess rather than reporting an unstable estimate. The attached evidence has segment results; this report does not present them.

I have not added either. Say the word on segments and I will."""),
            Turn("user", "Leave it for now. This version is fine."),
            Turn("assistant",
                 """Understood — version 2 stands as the current version.

For the record, what is open: no implementation test, no override analysis, and segment performance available but not presented. All three are in the evidence trail rather than only in this conversation."""),
            Turn("user",
                 "One thing — the characteristics section reads like a list. "
                 "Make it read like an argument for why these eleven and not "
                 "others. Same facts."),
            Turn("assistant",
                 """Rewritten, and confined to that section. The three selection criteria now lead — information value, monotonicity, business rationale — and the section says that two candidates were excluded for instability rather than for weak predictive power, which is the part a reviewer will ask about.

No information value changed, the count is still eleven, and nothing else in the report moved."""),
            Turn("user",
                 "When the implementation test lands, what exactly will you "
                 "need from me?"),
            Turn("assistant",
                 """Three things, and none of them is the report.

**The scored file from the production system** for a sample of applications, with the score each one received.

**The same applications scored by the development code**, so the two can be compared row by row.

**The tolerance** you consider acceptable, and who set it.

With those I can write the section as evidence rather than as an assertion. Without the third one I can present the comparison but not call it a pass, and I would rather ask now than write "within tolerance" against a tolerance nobody stated."""),
        ],
        v1=_application_v1(),
        v2=_application_v2(),
        v2_summary="Added calibration by score band; expanded the limitations.",
        change_items=[
            {"stable_id": "chg-calibration", "display_number": 1,
             "target_section": "New — Calibration by score band",
             "rationale": "The design document requires it.",
             "proposed": {"kind": "insert"},
             "evidence": {"locators": ["export://calibration"]}},
            {"stable_id": "chg-limitations-impl", "display_number": 2,
             "target_section": "Limitations",
             "rationale": "The implementation test gap blocks approval.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["docx://para/7"]}},
            {"stable_id": "chg-segments", "display_number": 3,
             "target_section": "New — Segment performance",
             "rationale": "The validation standard asks for it.",
             "proposed": {"kind": "insert"},
             "evidence": {"locators": ["export://segments"]}},
        ],
        approved=["chg-calibration", "chg-limitations-impl"],
        deck_from_v2=False,
    )


def _behavioural_thread() -> ThreadSpec:
    stats = sc.headline()
    return ThreadSpec(
        key="behavioural_validation_report",
        title="Behavioural Scorecard Validation Report",
        document_family="behavioural_validation_report",
        summary=("Version 2 issued from selected analyses. Override analysis is "
                 "still missing and the report says so rather than assuming it."),
        sources=[
            SourceSpec("model-validation-standard.docx",
                       validation_standard(), "methodology"),
            SourceSpec("behavioural-validation-evidence.xlsx",
                       current_results_workbook(), "results"),
            SourceSpec("prior-validation-report.docx",
                       prior_committee_report(), "previous_report"),
        ],
        export_titles=[
            f"Discrimination, behavioural scorecard, {CURRENT}",
            f"Population stability, {CURRENT}",
            f"Segment and backtesting results, {CURRENT}",
            "Validation finding investigation — behavioural scorecard",
            f"Characteristic stability, {CURRENT}",
        ],
        turns=[
            Turn("user",
                 "Using only the selected analyses, write a detailed "
                 "behavioural scorecard validation report. No template. "
                 "Include scope, data, methodology, results, limitations, "
                 "findings and conclusions where the evidence supports them. "
                 "Be explicit about anything missing. Don't invent tests."),
            Turn("assistant",
                 f"""Drafted from the five selected analyses. Word and PDF attached.

**What the evidence supports**

Discrimination: Gini {stats['recent_gini']} against {stats['development_gini']} at development, above the 0.45 floor. Population stability: PSI {stats['psi']}, below the 0.10 threshold. Three open findings, two of them documentation.

**What it does not, and which I have therefore not written**

The Model Validation Standard requires override analysis. No override evidence was selected and none is in the attached workbook. Section 6 says the analysis is required and was not performed. I have not estimated it and I have not described the model as fully validated.

One finding is worth reading carefully: the Contracting-employed segment has 270 accounts and a Gini of 0.41. That is below the floor, but on a population too small for the estimate to be stable. The finding is that the segment cannot be assessed — not that the scorecard fails on it. I have written it that way deliberately."""),
            Turn("user",
                 "That segment distinction matters. Is the calibration evidence "
                 "in what I gave you?"),
            Turn("assistant",
                 """Yes — it is in the population stability analysis, which carries the band-level population shares, and the discrimination analysis carries the band performance. I can present calibration properly as its own section.

The observed bad rate falls monotonically across all six bands, so there is no rank-order failure in the range the book occupies. That is a stronger statement than "calibration looks acceptable" and the evidence supports it."""),
            Turn("user", "Add it, and make the findings section clearer."),
            Turn("assistant",
                 """Version 2 is ready.

**Changed**
- New Section 4, calibration by score band, with the monotonicity stated explicitly.
- Section 5, population stability, now names the largest contributing band.
- Section 6, findings, distinguishes the segment finding from a performance failure in as many words.
- Section 7, limitations, says the override gap is a gap in the evidence rather than a finding about the model.

**Unchanged**
- Scope, data and discrimination are exactly as they were, including every figure.""",
                 version=2),
            Turn("user",
                 "Sharpen the executive framing but don't touch any number or "
                 "soften the findings."),
            Turn("assistant",
                 """Done. Scope and discrimination read more directly; every figure, every limit and every finding is unchanged, and the segment finding still says the segment cannot be assessed rather than that it passed."""),
            Turn("user", "What would close the open items?"),
            Turn("assistant",
                 """Three things, in order of how much they would change the conclusion.

**Override evidence.** The standard requires it and nothing supplied has it. Until it exists this report cannot say the model is fully validated against the standard, and it does not say so.

**A larger Contracting-employed sample.** 270 accounts is not enough for a stable Gini. Either pool with an adjacent segment on a documented rationale, or accept that the segment is unassessed and monitor it.

**The two documentation findings.** A monitoring pack and a complete override log. Neither changes the model; both are open against it."""),
            Turn("user",
                 "Turn this into a deck for the model risk committee. Keep the "
                 "segment finding worded exactly as it is."),
            Turn("assistant",
                 """The deck is attached, built from version 2. Native editable text and tables throughout.

Eight slides: scope, discrimination against limits, calibration, stability, findings, limitations, what would close them, and sources.

The segment finding is on its own slide with the wording carried across unchanged — it says the segment cannot be assessed, not that it failed. That distinction is the easiest thing to lose when a paragraph becomes a bullet, so I did not shorten it."""),
            Turn("user",
                 "Does the deck say anywhere that the model is validated?"),
            Turn("assistant",
                 """No, and it should not until the override analysis exists.

The discrimination slide says discrimination is above its limits, which is true and narrower. The limitations slide says the standard requires override analysis and that none was supplied. Nothing in the deck says validated, passed or approved, and the conclusion slide says what is outstanding rather than offering an opinion the evidence does not support."""),
        ],
        v1=_behavioural_v1(),
        v2=_behavioural_v2(),
        v2_summary=("Added calibration; sharpened findings and limitations. "
                    "No figure changed."),
        change_items=[
            {"stable_id": "chg-calibration-band", "display_number": 1,
             "target_section": "New — Calibration by score band",
             "rationale": "The standard requires observed against expected.",
             "proposed": {"kind": "insert"},
             "evidence": {"locators": ["export://population_stability"]}},
            {"stable_id": "chg-findings-clarity", "display_number": 2,
             "target_section": "Findings",
             "rationale": "The segment finding reads as a failure.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["export://segments"]}},
            {"stable_id": "chg-override-gap", "display_number": 3,
             "target_section": "Limitations",
             "rationale": "The override gap must read as an evidence gap.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["docx://para/11"]}},
            {"stable_id": "chg-psi-band", "display_number": 4,
             "target_section": "Population stability",
             "rationale": "The largest contributing band is not named.",
             "proposed": {"kind": "rewrite"},
             "evidence": {"locators": ["export://population_stability"]}},
        ],
        approved=["chg-calibration-band", "chg-findings-clarity",
                  "chg-override-gap", "chg-psi-band"],
    )


def threads() -> list[ThreadSpec]:
    return [_ifrs9_thread(), _application_thread(), _behavioural_thread()]
