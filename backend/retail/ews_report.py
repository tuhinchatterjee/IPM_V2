"""The Early Warning Score model development report, as a Word document.

Everything in the document is computed when the document is generated: the
univariate distributions, the bivariate event rates, the discrimination
statistics, the stability figures and every chart. Nothing is typed in, so the
report cannot disagree with the screen a reader has just come from — if the
panel is rebuilt, the next download says something different because the book
did, not because somebody edited a paragraph.

Two rules about what this document may claim, both enforced by the text and
by a test that reads the generated file:

  * The data are demonstration data. That is stated once, plainly, where a
    reader of a model document expects provenance — not sprinkled through
    every page as a disclaimer, which trains people to skip it.
  * No approval, validation or endorsement is claimed by anybody. The
    document says what was measured and what was not. A model development
    report that implies sign-off it does not have is worse than no report.
"""

from __future__ import annotations

import io
from datetime import date
from typing import Any

from backend.retail import ews_model as M
from backend.retail import ews_performance as P
from backend.retail import ews_registry as R
from backend.retail import ews_score as S

PROVENANCE = (
    "This report documents a model built on a synthetic Saudi retail "
    "demonstration portfolio. The portfolio, its customers and its outcomes "
    "are generated; they are not the records of any bank. The model, its "
    "thresholds and its performance are therefore demonstration artefacts. "
    "No regulator, bank or independent validation function has reviewed, "
    "approved or endorsed the model or this document."
)

#: The variables analysed one at a time in §16. Chosen as the classifier and
#: trigger inputs that carry the most weight in the model rather than as a
#: sample of what happens to be in the book.
UNIVARIATE: tuple[tuple[str, str], ...] = (
    ("dpd", "Days past due"),
    ("utilisation_ratio", "Utilisation"),
    ("behavioural_score", "Behavioural score"),
    ("debt_burden_ratio", "Debt burden ratio"),
    ("missed_payment_count_3m", "Missed payments, three months"),
    ("disposable_income_sar", "Disposable income"),
    ("bureau_score_current", "Bureau score, as last observed"),
    ("bureau_recency_months", "Months since the bureau observation"),
    ("payment_to_due_ratio_1m", "Payment to amount due"),
    ("ltv_current_ratio", "Loan to value"),
)


# ------------------------------------------------------------------- charts

def _png(draw) -> bytes:
    """One matplotlib figure, rendered to bytes at document resolution."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figure = plt.figure(figsize=(6.2, 3.1), dpi=170)
    axes = figure.add_subplot(111)
    draw(axes)
    axes.spines["top"].set_visible(False)
    axes.spines["right"].set_visible(False)
    axes.grid(True, alpha=0.25, linewidth=0.5)
    figure.tight_layout()
    buffer = io.BytesIO()
    figure.savefig(buffer, format="png")
    plt.close(figure)
    return buffer.getvalue()


def _roc_chart(measured: dict[str, Any]) -> bytes:
    def draw(axes):
        points = measured.get("roc") or []
        axes.plot([p["fpr"] for p in points], [p["tpr"] for p in points],
                  linewidth=1.8, color="#1f4e79")
        axes.plot([0, 1], [0, 1], linestyle="--", linewidth=0.9, color="#999")
        axes.set_xlabel("False positive rate")
        axes.set_ylabel("True positive rate")
        axes.set_title(f"ROC — AUC {measured.get('auc')}, "
                       f"Gini {measured.get('gini')}", fontsize=9)
    return _png(draw)


def _ks_chart(measured: dict[str, Any]) -> bytes:
    def draw(axes):
        gains = measured.get("gains") or []
        roc = measured.get("roc") or []
        share = [p["share"] for p in gains]
        axes.plot(share, [p["tpr"] for p in roc[:len(share)]],
                  label="Events captured", linewidth=1.6, color="#1f4e79")
        axes.plot(share, [p["fpr"] for p in roc[:len(share)]],
                  label="Non-events", linewidth=1.6, color="#c0504d")
        axes.set_xlabel("Share of the population, worst-scoring first")
        axes.set_ylabel("Cumulative share")
        axes.set_title(f"KS {measured.get('ks')} at "
                       f"{measured.get('ks_at_share')}", fontsize=9)
        axes.legend(fontsize=7, frameon=False)
    return _png(draw)


def _pr_chart(measured: dict[str, Any]) -> bytes:
    def draw(axes):
        points = measured.get("pr") or []
        axes.plot([p["recall"] for p in points],
                  [p["precision"] for p in points],
                  linewidth=1.8, color="#1f4e79")
        axes.axhline(measured.get("base_rate") or 0, linestyle="--",
                     linewidth=0.9, color="#999")
        axes.set_xlabel("Recall")
        axes.set_ylabel("Precision")
        axes.set_title(f"Precision-recall — PR-AUC {measured.get('pr_auc')}; "
                       f"base rate {measured.get('base_rate')}", fontsize=9)
    return _png(draw)


def _lift_chart(measured: dict[str, Any]) -> bytes:
    def draw(axes):
        rows = measured.get("lift") or []
        axes.bar([r["decile"] for r in rows], [r["lift"] or 0 for r in rows],
                 color="#1f4e79")
        axes.axhline(1.0, linestyle="--", linewidth=0.9, color="#999")
        axes.set_xlabel("Score decile, worst first")
        axes.set_ylabel("Lift against the base rate")
        axes.set_title("Lift by score decile", fontsize=9)
    return _png(draw)


def _bar_chart(labels: list[str], values: list[float], title: str,
               ylabel: str) -> bytes:
    def draw(axes):
        axes.bar(range(len(values)), values, color="#1f4e79")
        axes.set_xticks(range(len(labels)))
        axes.set_xticklabels(labels, rotation=30, ha="right", fontsize=7)
        axes.set_ylabel(ylabel)
        axes.set_title(title, fontsize=9)
    return _png(draw)


def _line_chart(x: list[str], series: dict[str, list[float]], title: str,
                ylabel: str) -> bytes:
    def draw(axes):
        for name, values in series.items():
            axes.plot(range(len(values)), values, linewidth=1.6, label=name)
        axes.set_xticks(range(0, len(x), max(1, len(x) // 8)))
        axes.set_xticklabels([x[i] for i in range(0, len(x), max(1, len(x) // 8))],
                             rotation=30, ha="right", fontsize=7)
        axes.set_ylabel(ylabel)
        axes.set_title(title, fontsize=9)
        if len(series) > 1:
            axes.legend(fontsize=7, frameon=False)
    return _png(draw)


def _histogram(values: Any, title: str, xlabel: str) -> bytes:
    def draw(axes):
        axes.hist(values, bins=30, color="#1f4e79")
        axes.set_xlabel(xlabel)
        axes.set_ylabel("Facilities")
        axes.set_title(title, fontsize=9)
    return _png(draw)


# -------------------------------------------------------------- the analysis

def _univariate(frame: Any) -> list[dict[str, Any]]:
    """Distribution, missingness and spread for each modelled variable."""
    import numpy as np
    import pandas as pd

    out = []
    for column, label in UNIVARIATE:
        if column not in frame.columns:
            out.append({"column": column, "label": label, "available": False,
                        "because": "the book does not carry this column"})
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        present = values.dropna()
        if not len(present):
            out.append({"column": column, "label": label, "available": False,
                        "because": "no values in the scoring month"})
            continue
        out.append({
            "column": column, "label": label, "available": True,
            "count": int(len(values)),
            "missing_pct": round(float(values.isna().mean()) * 100, 2),
            "mean": round(float(present.mean()), 4),
            "std": round(float(present.std()), 4),
            "min": round(float(present.min()), 4),
            "p25": round(float(present.quantile(0.25)), 4),
            "median": round(float(present.median()), 4),
            "p75": round(float(present.quantile(0.75)), 4),
            "p95": round(float(present.quantile(0.95)), 4),
            "max": round(float(present.max()), 4),
            "values": present.to_numpy(),
        })
    return out


def _bivariate(panel: Any, frame: Any) -> list[dict[str, Any]]:
    """Event rate by band of each variable — the univariate against the target.

    Joined by facility and month so each band's event rate is measured on the
    same observations the discrimination statistics use.
    """
    import numpy as np
    import pandas as pd

    if not len(panel):
        return []
    latest = panel["reporting_month"].max()
    here = panel[panel["reporting_month"] == latest]
    joined = here.merge(
        frame[[c for c, _ in UNIVARIATE if c in frame.columns]
              + ["facility_id"]].assign(
                  facility_id=frame["facility_id"].astype(str)),
        on="facility_id", how="left", suffixes=("", "_book"))

    out = []
    for column, label in UNIVARIATE:
        if column not in joined.columns:
            continue
        values = pd.to_numeric(joined[column], errors="coerce")
        if values.dropna().nunique() < 4:
            continue
        try:
            bands = pd.qcut(values, 5, duplicates="drop")
        except ValueError:
            continue
        rows = []
        for band, block in joined.groupby(bands, observed=True):
            if not len(block):
                continue
            rows.append({
                "band": str(band),
                "observations": int(len(block)),
                "events": int(block["event"].sum()),
                "event_rate": round(float(block["event"].mean()), 6),
            })
        if len(rows) >= 2:
            base = float(joined["event"].mean() or 0.0)
            out.append({"column": column, "label": label, "bands": rows,
                        "base_rate": round(base, 6),
                        "spread": round(max(r["event_rate"] for r in rows)
                                        - min(r["event_rate"] for r in rows), 6)})
    return out


# --------------------------------------------------------------- the document

def _styles(document) -> None:
    from docx.shared import Pt, RGBColor

    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(10)
    for name, size, colour in (("Heading 1", 16, "1F4E79"),
                               ("Heading 2", 13, "1F4E79"),
                               ("Heading 3", 11, "44546A")):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = RGBColor.from_string(colour)
        style.font.bold = True


def _table(document, columns: list[str], rows: list[list[Any]],
           widths: list[float] | None = None) -> None:
    from docx.shared import Inches, Pt

    table = document.add_table(rows=1, cols=len(columns))
    table.style = "Light Grid Accent 1"
    for index, name in enumerate(columns):
        cell = table.rows[0].cells[index]
        cell.text = str(name)
        for run in cell.paragraphs[0].runs:
            run.font.bold = True
            run.font.size = Pt(8)
    for row in rows:
        cells = table.add_row().cells
        for index, value in enumerate(row):
            cells[index].text = "" if value is None else str(value)
            for run in cells[index].paragraphs[0].runs:
                run.font.size = Pt(8)
    if widths:
        for index, width in enumerate(widths):
            for row in table.rows:
                row.cells[index].width = Inches(width)
    document.add_paragraph()


def _image(document, png: bytes, caption: str = "") -> None:
    from docx.shared import Inches, Pt

    document.add_picture(io.BytesIO(png), width=Inches(6.0))
    if caption:
        para = document.add_paragraph(caption)
        para.runs[0].font.size = Pt(8)
        para.runs[0].font.italic = True


def _pct(value: Any) -> str:
    return "—" if value is None else f"{float(value) * 100:.2f}%"


def _num(value: Any, places: int = 4) -> str:
    return "—" if value is None else f"{float(value):.{places}f}"


class _Sections:
    """Numbers the report's sections, and decides their heading level from
    the number rather than from whoever wrote the line.

    Written out by hand at each call site, the two drifted: sections 6, 8, 11,
    15, 16 and 20 carried a top-level number and a second-level heading, so
    Word's navigation pane and any generated contents page ran 5, 7, 9, 10,
    12 — a document that looks like it is missing six sections. Inserting a
    section also meant renumbering every one after it. Here a section is
    numbered and levelled in one place: a top-level section gets the next
    whole number and Heading 1, a numbered subsection gets its parent's number
    and Heading 2, and anything unnumbered stays out of the sequence.
    """

    def __init__(self) -> None:
        self.number = 0
        self.child = 0

    def section(self, document, title: str):
        self.number += 1
        self.child = 0
        return document.add_heading(f"{self.number}. {title}", level=1)

    def subsection(self, document, title: str):
        self.child += 1
        return document.add_heading(
            f"{self.number}.{self.child} {title}", level=2)

    @staticmethod
    def unnumbered(document, title: str, level: int = 2):
        """A heading that is part of its section rather than a section."""
        return document.add_heading(title, level=level)


def build(model_version: str = "") -> tuple[bytes, str]:
    """The report for one model version. Returns the bytes and a filename."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    which = model_version or R.ACTIVE
    version = R.get(which)
    if version is None:
        raise ValueError(f"{which} is not in the model registry")

    record = R.record(which)
    measured = record.get("performance") or {}
    months = S.panel_months()
    latest = months[-1] if months else ""
    book = S.read(latest) if latest else None
    panel = P.observations() if months else None

    document = Document()
    _styles(document)
    H = _Sections()

    # ---------------------------------------------------------- 1. Cover
    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run("Retail Early Warning Score\nModel Development Report")
    run.font.size = Pt(26)
    run.font.bold = True
    for line in (f"Model version {version.model_version}",
                 f"Rulebook {version.rulebook_version}",
                 f"Status: {version.status.title()}",
                 f"Portfolio: Saudi retail — credit card, personal finance, "
                 f"auto finance, home finance",
                 f"Scoring period: {months[0] if months else '—'} to {latest}",
                 f"Issued {date.today().isoformat()}"):
        para = document.add_paragraph(line)
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.runs[0].font.size = Pt(11)
    document.add_paragraph()
    note = document.add_paragraph(PROVENANCE)
    note.runs[0].font.size = Pt(9)
    note.runs[0].font.italic = True
    document.add_page_break()

    # ------------------------------------------- 2. Document control
    H.section(document, "Document control")
    _table(document, ["Field", "Value"], [
        ["Version ID", version.version_id],
        ["Model version", version.model_version],
        ["Rulebook version", version.rulebook_version],
        ["Sub-product taxonomy", version.taxonomy_version],
        ["Status", version.status],
        ["Effective from", version.effective_from],
        ["Effective to", version.effective_to or "current"],
        ["Development sample", version.development_sample],
        ["Validation sample", version.validation_sample],
        ["Configuration hash", record.get("config_hash")],
        ["Data manifest hash", record.get("data_manifest_hash")],
        ["Owner", version.created_by],
        ["Independent validation", "Not performed"],
        ["Regulatory approval", "Not sought and not held"],
    ], widths=[2.0, 4.0])

    H.unnumbered(document, "Version history")
    _table(document, ["Version", "Status", "Effective from", "Change"],
           [[one.model_version, one.status, one.effective_from,
             one.change_summary] for one in R.versions()],
           widths=[0.8, 0.9, 1.1, 3.4])

    # ------------------------------------------- 3. Executive summary
    H.section(document, "Executive summary")
    head = measured.get("headline") or {}
    document.add_paragraph(
        f"The Retail Early Warning Score ranks every open retail facility each "
        f"month on how likely it is to deteriorate over the following "
        f"{P.HORIZON_MONTHS} month-ends. It is a ranking and explanation "
        f"score: it orders customers by concern and names the reasons, and it "
        f"does not claim to be a calibrated probability of default.")
    document.add_paragraph(
        f"Measured over {measured.get('observations', 0):,} scored "
        f"facility-months in the published panel, on the population the model "
        f"exists for — facilities fully up to date when scored — the score "
        f"separates the facilities that go on to deteriorate with an AUC of "
        f"{_num(head.get('auc'))} (Gini {_num(head.get('gini'))}, KS "
        f"{_num(head.get('ks'))}). At the warning cutoff of "
        f"{M.SCALE.warning_cutoff:g} it flags "
        f"{_pct(head.get('alert_rate'))} of that population, catching "
        f"{_pct(head.get('recall'))} of the facilities that deteriorate at a "
        f"precision of {_pct(head.get('precision'))}.")
    lead = measured.get("lead_time") or {}
    if lead.get("available"):
        document.add_paragraph(
            f"Of the facilities that deteriorated, "
            f"{lead.get('warned_before_or_with', 0):,} of "
            f"{lead.get('facilities_that_deteriorated', 0):,} were already "
            f"above the cutoff when or before it happened, with a median "
            f"warning of {lead.get('median_months')} months; "
            f"{lead.get('at_least_1_month_early_pct')}% were flagged at least "
            f"one month early and {lead.get('at_least_2_months_early_pct')}% "
            f"at least two.")
    document.add_paragraph(
        f"What changed in this version: {version.change_summary} "
        f"{version.change_rationale}")

    # ------------------------------------------- 4. Business context
    H.section(document, "Business context and purpose")
    document.add_paragraph(
        "The score exists to find retail customers whose position is "
        "deteriorating before it reaches arrears, and to separate those who "
        "are already in trouble from those who are still paying and are "
        "likely to stop. Those two populations need different action, and a "
        "single delinquency report cannot tell them apart.")
    _table(document, ["Term", "Definition"], [
        ["Current bad", S.CURRENT_BAD_RULE],
        ["Forward risk", S.FORWARD_RISK_RULE],
        ["Default-entry rate", S.ODR_DEFINITION],
        ["Warning cutoff",
         f"An Early Warning Score of {M.SCALE.warning_cutoff:g} or above."],
    ], widths=[1.4, 4.6])

    # ------------------------------------------- 5. Target and horizon
    H.section(document, "Target definition and outcome horizon")
    document.add_paragraph(P.TARGET_DEFINITION)
    document.add_paragraph(
        f"The outcome window is {P.HORIZON_MONTHS} month-ends. The last "
        f"{P.HORIZON_MONTHS} months of the panel are therefore not scoreable "
        f"— there is no observed outcome for them — and they are excluded "
        f"rather than counted as non-events, which would understate every "
        f"event rate in this document. "
        f"{len(measured.get('scored_months') or [])} months remain, "
        f"{(measured.get('scored_months') or [''])[0]} to "
        f"{(measured.get('scored_months') or [''])[-1]}.")
    document.add_paragraph(P.CALIBRATION_STATEMENT)

    # ------------------------------------------- 6. Scope and data
    H.section(document, "Portfolio scope, data sources and lineage")
    _table(document, ["Layer", "Dataset", "What it carries"], [
        ["Canonical book", "retail_facility_month",
         "Every open retail facility at each month-end, with its IFRS 9 "
         "position, delinquency, scores and affordability."],
        ["Raw source domain", "retail_early_warning",
         "The governed Early Warning source: the book's raw fields needed to "
         "build the score and to hand a cohort to What-If. No derived score."],
        ["Scoring domain", S.DOMAIN,
         "Classifiers, triggers, action dimensions, sub-layer and layer "
         "scores, effective weights, the score, severity and reason codes."],
    ], widths=[1.2, 1.6, 3.2])
    if book is not None:
        document.add_paragraph(
            f"At {latest} the panel holds {len(book):,} facilities across "
            f"{book['customer_id'].nunique():,} customers and "
            f"{len(book.columns):,} fields, over {len(months)} monthly "
            f"snapshots from {months[0]} to {latest}.")

    H.section(document, "Data quality and exclusions")
    absent = [one for one in M.all_triggers()
              if getattr(one, "absent_because", "")]
    document.add_paragraph(
        f"{len(M.all_triggers()) - len(absent)} of {len(M.all_triggers())} "
        f"declared triggers are evaluated. The remainder are declared and "
        f"never evaluated because the published book cannot support them; "
        f"they are listed rather than approximated from another column.")
    if absent:
        _table(document, ["Trigger", "Why it is not evaluated"],
               [[one.name, one.absent_because] for one in absent],
               widths=[1.5, 4.5])

    # ------------------------------------------- 7. Architecture
    H.section(document, "Model architecture")
    document.add_paragraph(
        "Four layers, each built from sub-layers, each sub-layer from "
        "classifiers and triggers. A classifier is stable context that never "
        "fires; a trigger is a deterioration event measured against this "
        "month's book and the months behind it.")
    _table(document, ["Layer", "Base weight", "Kind", "Sub-layers",
                      "Classifiers", "Triggers"],
           [[layer.name, f"{layer.weight:.0%}", layer.kind,
             len(layer.sublayers),
             sum(len(s.classifiers) for s in layer.sublayers),
             sum(len(s.triggers) for s in layer.sublayers)]
            for layer in M.LAYERS],
           widths=[2.2, 0.8, 0.8, 0.7, 0.8, 0.7])

    H.section(document, "Classifier, trigger and action")
    document.add_paragraph(
        "Every dynamic trigger that fires is scored on six action dimensions, "
        "which together decide how much of its severity reaches the score. A "
        "one-month spike and a six-month slide are not the same event and are "
        "not weighted as though they were.")
    _table(document, ["Dimension", "Weight", "What it measures"],
           [[one.name, f"{M.ACTION_WEIGHTS.get(one.key, 0):.0%}", one.meaning]
            for one in M.ACTION_DIMENSIONS],
           widths=[1.0, 0.7, 4.3])

    # ------------------------------------------- 8. Bureau recency
    H.section(document, "Bureau recency weighting")
    document.add_paragraph(
        "A bureau pull is most informative the month it lands and loses "
        "decision value as it ages. The Bureau layer's weight therefore "
        "decays continuously with the age of the observation behind it:")
    formula = document.add_paragraph(
        "W(age) = W_floor + (W_max − W_floor) × exp(−ln2 × age ⁄ half_life)")
    formula.runs[0].font.bold = True
    document.add_paragraph(
        f"with W_max {M.BUREAU_RECENCY.w_max:.0%}, W_floor "
        f"{M.BUREAU_RECENCY.w_floor:.0%} and a half-life of "
        f"{M.BUREAU_RECENCY.half_life_months:g} months. "
        f"{M.BUREAU_RECENCY.basis}")
    _table(document, ["Months since pull", "Effective Bureau weight"],
           [[f"{row['age_months']:.0f}", f"{row['effective_weight_pct']:.2f}%"]
            for row in M.BUREAU_RECENCY.table()],
           widths=[1.8, 2.0])
    table = M.BUREAU_RECENCY.table(tuple(range(0, 37)))
    _image(document, _line_chart(
        [str(int(r["age_months"])) for r in table],
        {"Effective weight %": [r["effective_weight_pct"] for r in table]},
        "Bureau layer effective weight by age of observation",
        "Weight (%)"),
        "Figure 1. The decay, from the model configuration.")
    document.add_paragraph(
        "The weight this releases is not discarded. It is redistributed "
        "across the three dynamic layers in proportion to their base weights, "
        "so the four layers always total one hundred per cent. Both the base "
        "and the effective weight are stored on every row of the scoring "
        "domain.")
    if book is not None and "bureau_weight_effective" in book:
        _table(document, ["Statistic", "Effective Bureau weight at " + latest],
               [["Minimum", f"{float(book['bureau_weight_effective'].min()):.4f}"],
                ["Median", f"{float(book['bureau_weight_effective'].median()):.4f}"],
                ["Maximum", f"{float(book['bureau_weight_effective'].max()):.4f}"],
                ["Layer weights total, minimum",
                 f"{float(book['effective_weight_total'].min()):.6f}"],
                ["Layer weights total, maximum",
                 f"{float(book['effective_weight_total'].max()):.6f}"]],
               widths=[2.0, 3.0])

    # ------------------------------------------- 9. Product weighting
    H.section(document, "Product weighting")
    document.add_paragraph(
        "Each product is scored on its own base weights, because the same "
        "signal does not mean the same thing on a card as on a mortgage.")
    _table(document, ["Product"] + [layer.name for layer in M.LAYERS],
           [[code.replace("_", " ").title()]
            + [f"{M.weights_for(code)[layer.key]:.0%}" for layer in M.LAYERS]
            for code in M.ALL_PRODUCTS],
           widths=[1.4, 1.2, 1.2, 1.1, 1.1])

    H.section(document, "Classification and sub-product hierarchy")
    _table(document, ["Classification", "Derivation"],
           [[one.label, one.derivation] for one in M.CLASSIFICATIONS],
           widths=[1.4, 4.6])
    _table(document, ["Sub-product", "Product", "Derivation"],
           [[one.label, one.product.replace("_", " ").title(), one.derivation]
            for one in M.SUB_PRODUCTS],
           widths=[1.8, 1.3, 2.9])

    document.add_page_break()

    # ------------------------------------------- 10. Univariate
    H.section(document, "Univariate analysis")
    document.add_paragraph(
        f"Each modelled variable at {latest}: its distribution, its spread "
        f"and how much of it is missing. Missingness matters as much as the "
        f"distribution — a trigger built on a column that is empty for a "
        f"third of the book is a trigger that fires for two thirds of it.")
    stats = _univariate(book) if book is not None else []
    _table(document,
           ["Variable", "n", "Missing", "Mean", "SD", "Min", "P25",
            "Median", "P75", "P95", "Max"],
           [[one["label"], f"{one['count']:,}", f"{one['missing_pct']}%",
             one["mean"], one["std"], one["min"], one["p25"], one["median"],
             one["p75"], one["p95"], one["max"]]
            if one.get("available") else
            [one["label"], "—", "—", one.get("because", ""), "", "", "", "",
             "", "", ""]
            for one in stats],
           widths=[1.5] + [0.45] * 10)
    for one in stats[:4]:
        if one.get("available"):
            _image(document, _histogram(
                one["values"], f"{one['label']} at {latest}", one["label"]),
                f"Figure. Distribution of {one['label'].lower()}.")

    # ------------------------------------------- 11. Bivariate
    H.section(document, "Bivariate analysis")
    document.add_paragraph(
        "Each variable against the target: the event rate in each quintile of "
        "the variable, on the same observations the discrimination statistics "
        "below are measured on. A variable whose event rate does not move "
        "across its own range carries no information about the target, "
        "whatever its distribution looks like.")
    pairs = _bivariate(panel, book) if panel is not None and book is not None else []
    for one in pairs:
        H.unnumbered(document, one["label"], level=3)
        _table(document, ["Band", "Observations", "Events", "Event rate"],
               [[row["band"], f"{row['observations']:,}", f"{row['events']:,}",
                 _pct(row["event_rate"])] for row in one["bands"]],
               widths=[2.0, 1.2, 1.0, 1.2])
        _image(document, _bar_chart(
            [row["band"][:14] for row in one["bands"]],
            [row["event_rate"] * 100 for row in one["bands"]],
            f"Event rate by {one['label'].lower()}", "Event rate (%)"),
            f"Figure. Spread across the range: "
            f"{_pct(one['spread'])} between the lowest and highest band.")

    document.add_page_break()

    # ------------------------------------------- 12. Score construction
    H.section(document, "Score construction")
    document.add_paragraph(
        "A fired trigger contributes its severity, scaled by its action "
        "dimensions and capped, to its sub-layer. A sub-layer takes its worst "
        "contribution plus a tenth of the others. Layers combine their "
        "sub-layers, and the four layers combine on the product's effective "
        "weights, through a bounded roll-up:")
    para = document.add_paragraph(
        "combined = 100 × (1 − ∏(1 − wᵢ × sᵢ ⁄ 100))")
    para.runs[0].font.bold = True
    document.add_paragraph(
        "The roll-up is monotone and bounded: adding a signal can never lower "
        "a score and no combination can exceed the top of the scale. A "
        "weighted mean was tried first and diluted a single serious signal to "
        "a tenth of the scale; a rescaled weighted sum overshot and pinned "
        "part of the book at exactly one hundred.")
    _table(document, ["Setting", "Value"], [
        ["Scale", f"{M.SCALE.minimum:g} to {M.SCALE.maximum:g}, "
                  f"{M.SCALE.direction}"],
        ["Warning cutoff", f"{M.SCALE.warning_cutoff:g}"],
        ["Severity points",
         ", ".join(f"{k} {v:g}" for k, v in M.SEVERITY_POINTS.items())],
        ["Single-trigger cap", f"{M.TRIGGER_CONTRIBUTION_CAP:g}"],
        ["Action multiplier bounds",
         f"{M.ACTION_MULTIPLIER_FLOOR:g} to {M.ACTION_MULTIPLIER_CEILING:g}"],
    ], widths=[1.6, 4.4])

    H.section(document, "Severity thresholds")
    _table(document, ["Band", "Customer score from", "Population score from"],
           [[band, f"{low:g}",
             next((f"{plow:g}" for plow, pband in M.POPULATION_BANDS
                   if pband == band), "—")]
            for low, band in M.SEVERITY_BANDS],
           widths=[1.3, 1.6, 1.8])
    document.add_paragraph(
        "Customer bands and population bands differ deliberately. A "
        "portfolio in which one customer in six is warned is a portfolio in "
        "trouble; the customer table would put all six in the bottom band "
        "and the badge would say nothing.")

    H.section(document, "Hard triggers and overrides")
    _table(document, ["Override", "Condition", "Floor", "Why"],
           [[h.name, h.condition, f"{h.floor_score:g}", h.because]
            for h in M.HARD_TRIGGERS],
           widths=[1.3, 1.3, 0.5, 2.9])

    document.add_page_break()

    # ------------------------------------------- 13. Performance by cohort
    H.section(document, "Performance")
    document.add_paragraph(
        "Performance is reported by the state a facility was in when it was "
        "scored. A facility already ninety days down does not need an early "
        "warning, and a model measured including those is measuring its own "
        "inputs.")

    for cohort in (measured.get("cohorts") or []):
        H.subsection(document, str(cohort["name"]))
        document.add_paragraph(cohort["meaning"])
        if cohort.get("caveat"):
            warn = document.add_paragraph(cohort["caveat"])
            warn.runs[0].font.italic = True
        if not cohort.get("available"):
            document.add_paragraph(
                f"Not measured: {cohort.get('because', 'no observations')}.")
            continue
        if cohort.get("discrimination_reported") is False:
            capture = cohort.get("capture") or {}
            document.add_paragraph(cohort.get("why_no_discrimination", ""))
            _table(document, ["Measure", "Value"], [
                ["Observations", f"{cohort['observations']:,}"],
                ["Flagged at or above the cutoff",
                 f"{capture.get('flagged', 0):,}"],
                ["Operational capture rate", _pct(capture.get("capture_rate"))],
                ["Scored CRITICAL", f"{capture.get('at_critical', 0):,}"],
                ["Scored CRITICAL, share", _pct(capture.get("at_critical_rate"))],
            ], widths=[2.6, 1.6])
            document.add_page_break()
            continue
        threshold = cohort.get("threshold") or {}
        _table(document, ["Statistic", "Value"], [
            ["Observations", f"{cohort['observations']:,}"],
            ["Events", f"{cohort['events']:,}"],
            ["Event rate", _pct(cohort["event_rate"])],
            ["ROC AUC", _num(cohort.get("auc"))],
            ["Gini", _num(cohort.get("gini"))],
            ["KS", _num(cohort.get("ks"))],
            ["PR-AUC", _num(cohort.get("pr_auc"))],
            ["Alert rate at cutoff", _pct(threshold.get("alert_rate"))],
            ["Precision", _pct(threshold.get("precision"))],
            ["Recall", _pct(threshold.get("recall"))],
            ["F1", _num(threshold.get("f1"))],
            ["Balanced accuracy", _num(threshold.get("balanced_accuracy"))],
            ["False positive rate", _pct(threshold.get("false_positive_rate"))],
            ["False negative rate", _pct(threshold.get("false_negative_rate"))],
        ], widths=[2.2, 2.0])
        _table(document, ["", "Deteriorated", "Did not"],
               [["Flagged", f"{threshold.get('true_positive', 0):,}",
                 f"{threshold.get('false_positive', 0):,}"],
                ["Not flagged", f"{threshold.get('false_negative', 0):,}",
                 f"{threshold.get('true_negative', 0):,}"]],
               widths=[1.4, 1.4, 1.4])
        if cohort.get("roc"):
            _image(document, _roc_chart(cohort),
                   f"Figure. ROC, {cohort['name'].lower()}.")
            _image(document, _ks_chart(cohort),
                   f"Figure. KS, {cohort['name'].lower()}.")
            _image(document, _pr_chart(cohort),
                   f"Figure. Precision-recall, {cohort['name'].lower()}.")
            _image(document, _lift_chart(cohort),
                   f"Figure. Lift by decile, {cohort['name'].lower()}.")
        document.add_page_break()

    # ------------------------------------------- 14. Cuts
    H.section(document, "Performance by product")
    _table(document, ["Product", "Observations", "Events", "Event rate",
                      "AUC", "Gini", "KS"],
           [[one["label"], f"{one['observations']:,}", f"{one['events']:,}",
             _pct(one["event_rate"]), _num(one.get("auc")),
             _num(one.get("gini")), _num(one.get("ks"))]
            for one in (measured.get("by_product") or [])],
           widths=[1.4, 1.0, 0.8, 0.9, 0.7, 0.7, 0.7])
    products = [one for one in (measured.get("by_product") or [])
                if one.get("auc") is not None]
    if products:
        _image(document, _bar_chart(
            [one["label"] for one in products],
            [float(one["gini"]) for one in products],
            "Gini by product, broad pre-default cohort", "Gini"),
            "Figure. Discrimination by product.")

    H.section(document, "Performance by classification")
    _table(document, ["Classification", "Observations", "Events",
                      "Event rate", "AUC", "Gini", "KS"],
           [[one["label"], f"{one['observations']:,}", f"{one['events']:,}",
             _pct(one["event_rate"]), _num(one.get("auc")),
             _num(one.get("gini")), _num(one.get("ks"))]
            for one in (measured.get("by_classification") or [])],
           widths=[1.4, 1.0, 0.8, 0.9, 0.7, 0.7, 0.7])

    H.section(document, "Performance by sub-product")
    _table(document, ["Sub-product", "Observations", "Events", "Event rate",
                      "Gini"],
           [[one["label"], f"{one['observations']:,}", f"{one['events']:,}",
             _pct(one["event_rate"]), _num(one.get("gini"))]
            for one in (measured.get("by_sub_product") or [])],
           widths=[1.8, 1.1, 0.9, 1.0, 0.8])

    # ------------------------------------------- 15. Stability
    H.section(document, "Stability")
    stability = measured.get("stability") or {}
    if stability.get("available"):
        document.add_paragraph(
            f"Population stability against {stability['baseline_month']}: "
            f"PSI {stability['psi_latest']} at the latest scored month, read "
            f"as {stability['reading']}. {stability['bands']}")
        series = stability.get("series") or []
        _table(document, ["Month", "Observations", "Mean score",
                          "Alert rate", "PSI vs baseline"],
               [[row["month"], f"{row['observations']:,}", row["mean_score"],
                 _pct(row["alert_rate"]), row["psi_vs_first"]]
                for row in series],
               widths=[1.0, 1.1, 1.0, 1.0, 1.2])
        _image(document, _line_chart(
            [row["month"] for row in series],
            {"PSI": [row["psi_vs_first"] or 0 for row in series]},
            "Population stability index over time", "PSI"),
            "Figure. PSI against the first scored month.")
        _image(document, _line_chart(
            [row["month"] for row in series],
            {"Alert rate %": [(row["alert_rate"] or 0) * 100 for row in series]},
            "Alert rate over time", "Alert rate (%)"),
            "Figure. Share of the population above the warning cutoff.")

    # ------------------------------------------- 16. Lead time
    H.section(document, "Lead time")
    if lead.get("available"):
        document.add_paragraph(
            f"Measured per facility: the first month the score crossed the "
            f"cutoff against the first month the facility deteriorated. "
            f"Facilities never warned in time are counted as misses rather "
            f"than dropped.")
        _table(document, ["Measure", "Value"], [
            ["Facilities that deteriorated",
             f"{lead['facilities_that_deteriorated']:,}"],
            ["Warned before or in the same month",
             f"{lead['warned_before_or_with']:,}"],
            ["Never warned in time", f"{lead['never_warned_in_time']:,}"],
            ["Mean months of warning", lead.get("mean_months")],
            ["Median months of warning", lead.get("median_months")],
            ["At least one month early",
             f"{lead.get('at_least_1_month_early_pct')}%"],
            ["At least two months early",
             f"{lead.get('at_least_2_months_early_pct')}%"],
        ], widths=[2.6, 1.6])
        spread = lead.get("distribution") or []
        if spread:
            _image(document, _bar_chart(
                [str(row["months_early"]) for row in spread],
                [row["facilities"] for row in spread],
                "Months of warning before deterioration", "Facilities"),
                "Figure. Lead-time distribution.")

    # ------------------------------------------- 17. Score behaviour
    H.section(document, "Score behaviour against the target")
    rates = measured.get("severity_event_rates") or []
    _table(document, ["Severity band", "Observations", "Events", "Event rate"],
           [[row["band"], f"{row['observations']:,}", f"{row['events']:,}",
             _pct(row["event_rate"])] for row in rates],
           widths=[1.4, 1.3, 1.0, 1.2])
    if rates:
        _image(document, _bar_chart(
            [row["band"] for row in rates],
            [(row["event_rate"] or 0) * 100 for row in rates],
            "Event rate by severity band", "Event rate (%)"),
            "Figure. The bands separate the outcome, which is what they are for.")
    spread = measured.get("score_distribution") or []
    if spread:
        _image(document, _line_chart(
            [row["band"] for row in spread],
            {"Deteriorated": [row["events"] for row in spread],
             "Did not": [row["non_events"] for row in spread]},
            "Score distribution, events against non-events", "Facility-months"),
            "Figure. Where the two populations sit on the scale.")

    # ------------------------------------------- 18. Governance
    document.add_page_break()
    H.section(document, "Limitations")
    for line in (
        "The score is a ranking score. It is not a calibrated probability of "
        "default and no calibration statistic is reported for it.",
        "The portfolio is synthetic. Every rate in this document describes a "
        "generated book and none of it is evidence about any real portfolio.",
        "Thresholds are demonstration thresholds, chosen so the products "
        "separate on this book. They are bank-configurable and have not been "
        "optimised against observed outcomes.",
        f"The bureau position is a governed proxy on a modelled pull "
        f"schedule, not a live bureau feed. Between pulls the last observed "
        f"value is carried forward unchanged and the layer's weight decays.",
        f"{len([1 for one in M.all_triggers() if getattr(one, 'absent_because', '')])} "
        "declared triggers are never evaluated because the book cannot "
        "support them; they are listed in section 6.",
        "The outcome window is three months. Deterioration beyond that "
        "horizon is not measured here.",
        "No independent validation has been performed on this model and none "
        "is claimed.",
    ):
        document.add_paragraph(line, style="List Bullet")

    H.section(document, "Monitoring framework")
    _table(document, ["What is monitored", "How", "Where"], [
        ["Discrimination", "AUC, Gini, KS and PR-AUC by starting-state "
                           "cohort, each month the panel is rebuilt",
         "Model Log"],
        ["Stability", "PSI of the score distribution against the first "
                      "scored month, plus alert-rate and severity drift",
         "Model Log"],
        ["Lead time", "Median months of warning before deterioration",
         "Model Log"],
        ["Alert volume", "Share of each population above the cutoff",
         "Early Warning Score portfolio screen"],
        ["Trigger behaviour", "How many customers each trigger caught, and "
                              "triggers that never fire",
         "View Model"],
    ], widths=[1.5, 3.0, 1.5])

    H.section(document, "Governance and change rationale")
    document.add_paragraph(version.change_rationale)
    comparison = R.compare("2.0.0", version.model_version) \
        if version.model_version != "2.0.0" else None
    if comparison and comparison.get("available"):
        _table(document, ["What", "Previous version", "This version"],
               [[row["what"], row["left"], row["right"]]
                for row in comparison["configuration"]],
               widths=[1.3, 2.3, 2.4])
        impact = comparison.get("population_impact") or {}
        document.add_paragraph(
            f"At {impact.get('month')}, {impact.get('severity_changed'):,} of "
            f"{impact.get('observations'):,} scored facilities "
            f"({impact.get('severity_changed_pct')}%) change severity band "
            f"between the two versions, covering SAR "
            f"{impact.get('exposure_severity_changed_sar', 0):,.0f} "
            f"({impact.get('exposure_severity_changed_pct')}% of exposure). "
            f"{impact.get('score_moved_up'):,} scores rise and "
            f"{impact.get('score_moved_down'):,} fall, a mean change of "
            f"{impact.get('mean_score_change')} points.")

    # ------------------------------------------- 19. Dictionaries
    document.add_page_break()
    H.section(document, "Variable dictionary")
    _table(document, ["Layer", "Sub-layer", "Variable", "Column", "Kind",
                      "What it means"],
           [[layer.name, sub.name, one.name, one.column, "Classifier",
             one.meaning]
            for layer in M.LAYERS for sub in layer.sublayers
            for one in sub.classifiers]
           + [[layer.name, sub.name, one.name, one.column, "Trigger",
               one.meaning]
              for layer in M.LAYERS for sub in layer.sublayers
              for one in sub.triggers],
           widths=[1.1, 1.0, 1.1, 1.2, 0.6, 1.0])

    H.section(document, "Rule dictionary")
    _table(document, ["Reason code", "Trigger", "Severity", "Test",
                      "Recommended review"],
           [[one.reason_code, one.name, one.severity,
             f"{one.column} {one.test} {one.threshold:g} {one.unit}".strip(),
             one.recommended_review]
            for layer in M.LAYERS for sub in layer.sublayers
            for one in sub.triggers],
           widths=[0.9, 1.3, 0.7, 1.6, 1.5])

    H.section(document, "Glossary")
    _table(document, ["Term", "Meaning"],
           [[one.term, one.meaning] for one in M.GLOSSARY],
           widths=[1.2, 4.8])

    closing = document.add_paragraph(PROVENANCE)
    closing.runs[0].font.size = Pt(8)
    closing.runs[0].font.italic = True

    buffer = io.BytesIO()
    document.save(buffer)
    name = (f"Retail_Early_Warning_Score_Model_Development_Report_"
            f"v{version.model_version}_{latest or 'latest'}.docx")
    return buffer.getvalue(), name


__all__ = ["PROVENANCE", "UNIVARIATE", "build"]
