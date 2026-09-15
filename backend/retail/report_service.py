"""One report service, and the bundle every report is built from.

§13 of the demo completion contract. Three report families — investigation,
trait deterioration, scorecard validation — with one document builder behind
them, because three builders would drift into three house styles and only one
of them would keep its page numbers.

What a bundle is
----------------
A report is generated from a versioned RECORD of an analysis, never from a
fresh run. Two reasons, and the second is the one that matters:

  * a run takes time, and a reader pressing Download has already waited once;
  * a fresh run against a book that has moved since would produce a document
    that disagrees with the screen it was downloaded from, and neither could
    then be trusted.

So `Bundle` carries the analysis result, the population it ran on, the
evidence tables, the commentary, the source versions and the findings. The
writers read it and write; they do not compute.

The download path
-----------------
§13 opens by asking for the end-to-end path to be repaired, "including
authentication, report-job status, content type, filename, file streaming,
stale URLs, browser download and actual DOCX contents. Never download an HTML
error/login page with a .docx extension." That last failure is why `render`
raises rather than returning a best-effort document: a caller that cannot
build a report must send an error with an error's content type, not a file.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

REPORT_SERVICE_VERSION = "retail-report-service-1.0.0"

INVESTIGATION = "investigation"
TRAITS = "trait_attribution"
VALIDATION = "scorecard_validation"

FAMILIES: dict[str, str] = {
    INVESTIGATION: "Investigation report",
    TRAITS: "Customer-trait deterioration report",
    VALIDATION: "Scorecard validation report",
}

#: Said once, on the document-control page, rather than on every page. §13:
#: "A report should contain a concise provenance/limitations statement and not
#: repeat disclaimers on every page."
PROVENANCE = (
    "Synthetic Saudi retail demonstration data and a synthetic demonstration "
    "model. This document is not ANB customer data, not an ANB-approved "
    "model, not an ANB policy, not a SAMA requirement, and has not been "
    "independently validated. It is a demonstration of a workflow. No credit "
    "decision should rest on it.")


class ReportUnavailable(RuntimeError):
    """This report cannot be built, and the caller must say so as an error.

    Never as a document. A .docx containing an apology is worse than a 503:
    the file opens, so the reader believes they have the report.
    """


@dataclass
class Bundle:
    """Everything one report is written from, pinned to when it was run."""

    family: str
    title: str
    subtitle: str = ""
    #: The analysis result, exactly as the screen received it.
    result: dict[str, Any] = field(default_factory=dict)
    #: Population and scope, so the document can state what it covers.
    scope: dict[str, Any] = field(default_factory=dict)
    #: Ordered (heading, rows, columns) evidence the writer lays out.
    evidence: list[dict[str, Any]] = field(default_factory=list)
    #: Analyst commentary and reviewer responses, in order.
    comments: list[dict[str, Any]] = field(default_factory=list)
    #: Shared finding records this report cites.
    findings: list[dict[str, Any]] = field(default_factory=list)
    #: Source, model, rulebook and data versions.
    versions: dict[str, Any] = field(default_factory=dict)
    #: Remediation actions with owners and dates.
    actions: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    prepared_by: str = ""
    prepared_at: str = ""
    #: Set when this report describes a snapshot that is no longer current.
    historical: bool = False
    as_of: str = ""

    def __post_init__(self) -> None:
        if not self.prepared_at:
            self.prepared_at = datetime.now(UTC).isoformat(timespec="seconds")

    def to_dict(self) -> dict[str, Any]:
        return {**self.__dict__, "service_version": REPORT_SERVICE_VERSION}


# ======================================================== the document

class Report:
    """A Word document with the furniture §13 asks for, already in place."""

    def __init__(self, bundle: Bundle) -> None:
        from docx import Document

        self.bundle = bundle
        self.document = Document()
        self.number = 0
        self.child = 0
        self._contents: list[tuple[int, str]] = []
        self._captions = {"Table": 0, "Figure": 0}
        self._setup()

    # -- furniture -------------------------------------------------------

    def _setup(self) -> None:
        from docx.enum.section import WD_SECTION
        from docx.shared import Cm, Pt, RGBColor

        normal = self.document.styles["Normal"]
        normal.font.name = "Calibri"
        normal.font.size = Pt(10)
        for name, size, colour in (("Heading 1", 16, "1F3864"),
                                   ("Heading 2", 13, "1F3864"),
                                   ("Heading 3", 11, "1B6B6B")):
            style = self.document.styles[name]
            style.font.name = "Calibri"
            style.font.size = Pt(size)
            style.font.color.rgb = RGBColor.from_string(colour)
            style.font.bold = True
        for section in self.document.sections:
            section.left_margin = Cm(2.0)
            section.right_margin = Cm(2.0)
            section.top_margin = Cm(2.0)
            section.bottom_margin = Cm(2.0)
        self._page_numbers()

    def _page_numbers(self) -> None:
        """A footer that says "Page N of M" — computed by Word, not by us."""
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.oxml.ns import qn
        from docx.shared import Pt

        footer = self.document.sections[0].footer
        para = footer.paragraphs[0]
        para.alignment = WD_ALIGN_PARAGRAPH.CENTER
        para.text = ""
        run = para.add_run("Page ")
        run.font.size = Pt(8)
        self._field(para, "PAGE")
        run = para.add_run(" of ")
        run.font.size = Pt(8)
        self._field(para, "NUMPAGES")

    @staticmethod
    def _field(paragraph: Any, instruction: str) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        run = paragraph.add_run()
        begin = OxmlElement("w:fldChar")
        begin.set(qn("w:fldCharType"), "begin")
        text = OxmlElement("w:instrText")
        text.set(qn("xml:space"), "preserve")
        text.text = f" {instruction} "
        end = OxmlElement("w:fldChar")
        end.set(qn("w:fldCharType"), "end")
        run._r.append(begin)
        run._r.append(text)
        run._r.append(end)

    def cover(self) -> None:
        from docx.enum.text import WD_ALIGN_PARAGRAPH
        from docx.shared import Pt, RGBColor

        bundle = self.bundle
        for _ in range(4):
            self.document.add_paragraph()
        title = self.document.add_paragraph()
        title.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = title.add_run(bundle.title)
        run.font.size = Pt(26)
        run.font.bold = True
        run.font.color.rgb = RGBColor.from_string("1F3864")
        if bundle.subtitle:
            sub = self.document.add_paragraph()
            sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = sub.add_run(bundle.subtitle)
            run.font.size = Pt(13)
            run.font.color.rgb = RGBColor.from_string("5B636B")
        kind = self.document.add_paragraph()
        kind.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = kind.add_run(FAMILIES.get(bundle.family, bundle.family))
        run.font.size = Pt(11)
        run.font.italic = True
        if bundle.historical:
            flag = self.document.add_paragraph()
            flag.alignment = WD_ALIGN_PARAGRAPH.CENTER
            run = flag.add_run(
                f"HISTORICAL — as at {bundle.as_of or 'an earlier snapshot'}. "
                f"The current book has moved since. Create a current revision "
                f"rather than quoting these figures as today's.")
            run.font.size = Pt(10)
            run.font.bold = True
            run.font.color.rgb = RGBColor.from_string("7F5F00")
        self.document.add_page_break()

    def document_control(self) -> None:
        bundle = self.bundle
        self.unnumbered("Document control", level=1)
        rows = [
            ("Report", FAMILIES.get(bundle.family, bundle.family)),
            ("Title", bundle.title),
            ("Scope", bundle.scope.get("label") or "—"),
            ("Reporting month", bundle.scope.get("month") or "—"),
            ("Population", _population(bundle.scope)),
            ("Prepared by", bundle.prepared_by or "CreditProbe"),
            ("Prepared at (UTC)", bundle.prepared_at),
            ("Status", "Historical snapshot" if bundle.historical
                       else "Current"),
            ("Service version", REPORT_SERVICE_VERSION),
        ]
        rows += [(str(k).replace("_", " ").capitalize(), str(v))
                 for k, v in (bundle.versions or {}).items() if v]
        self.table(["Field", "Value"], [[a, b] for a, b in rows],
                   caption="", widths=[2.0, 4.4])
        self.unnumbered("Provenance and limitations", level=2)
        self.para(PROVENANCE)
        for one in bundle.limitations:
            self.bullet(str(one))
        self.document.add_page_break()

    def contents(self) -> None:
        """A table of contents Word fills in, and a plain list that is right
        even if the reader never presses F9."""
        self.unnumbered("Contents", level=1)
        para = self.document.add_paragraph()
        self._field(para, 'TOC \\o "1-2" \\h \\z \\u')
        self._toc_at = len(self.document.paragraphs)
        self.document.add_page_break()

    # -- content ---------------------------------------------------------

    def section(self, title: str) -> None:
        self.number += 1
        self.child = 0
        self.document.add_heading(f"{self.number}. {title}", level=1)
        self._contents.append((1, f"{self.number}. {title}"))

    def subsection(self, title: str) -> None:
        self.child += 1
        self.document.add_heading(
            f"{self.number}.{self.child} {title}", level=2)
        self._contents.append((2, f"{self.number}.{self.child} {title}"))

    def unnumbered(self, title: str, level: int = 2) -> None:
        self.document.add_heading(title, level=level)

    def para(self, text: str) -> None:
        if str(text).strip():
            self.document.add_paragraph(str(text))

    def bullet(self, text: str) -> None:
        if str(text).strip():
            self.document.add_paragraph(str(text), style="List Bullet")

    def key_values(self, rows: list[tuple[str, Any]]) -> None:
        self.table(["", ""], [[a, "—" if b is None else str(b)]
                              for a, b in rows], caption="",
                   widths=[2.4, 4.0], header=False)

    def table(self, columns: list[str], rows: list[list[Any]], *,
              caption: str = "", widths: list[float] | None = None,
              header: bool = True) -> None:
        from docx.shared import Inches, Pt

        if not rows:
            self.para("No rows were produced for this table.")
            return
        table = self.document.add_table(rows=1, cols=len(columns))
        table.style = "Light Grid Accent 1"
        head = table.rows[0]
        for index, name in enumerate(columns):
            cell = head.cells[index]
            cell.text = str(name)
            for run in cell.paragraphs[0].runs:
                run.font.bold = True
                run.font.size = Pt(8)
        # §13: repeated table headers, so a table that spans a page break is
        # still readable on the second page.
        self._repeat_header(head)
        for row in rows:
            cells = table.add_row().cells
            for index, value in enumerate(row[:len(columns)]):
                cells[index].text = "" if value is None else str(value)
                for run in cells[index].paragraphs[0].runs:
                    run.font.size = Pt(8)
        if widths:
            for index, width in enumerate(widths[:len(columns)]):
                for row in table.rows:
                    row.cells[index].width = Inches(width)
        if caption:
            self.caption("Table", caption)
        self.document.add_paragraph()

    @staticmethod
    def _repeat_header(row: Any) -> None:
        from docx.oxml import OxmlElement
        from docx.oxml.ns import qn

        properties = row._tr.get_or_add_trPr()
        repeat = OxmlElement("w:tblHeader")
        repeat.set(qn("w:val"), "true")
        properties.append(repeat)

    def caption(self, kind: str, text: str) -> None:
        from docx.shared import Pt

        self._captions[kind] = self._captions.get(kind, 0) + 1
        para = self.document.add_paragraph(
            f"{kind} {self._captions[kind]}. {text}")
        for run in para.runs:
            run.font.size = Pt(8)
            run.font.italic = True

    def image(self, png: bytes, caption: str = "") -> None:
        from docx.shared import Inches

        if not png:
            return
        # 6.0 inches inside 2 cm margins on A4: a chart that is wider is
        # clipped at the right edge, which §13 lists as a defect.
        self.document.add_picture(io.BytesIO(png), width=Inches(6.0))
        if caption:
            self.caption("Figure", caption)

    def comments_section(self) -> None:
        if not self.bundle.comments:
            return
        self.section("Analyst and reviewer comments")
        self.para("Comments are attached to a specific test, run and data "
                  "version. They are reproduced here exactly as they were "
                  "written; nothing in this section is generated.")
        self.table(
            ["Section", "Author", "When", "Assessment", "Comment",
             "Status"],
            [[one.get("section", ""), one.get("author", ""),
              one.get("at", ""), one.get("assessment", ""),
              one.get("text", ""), one.get("status", "")]
             for one in self.bundle.comments],
            caption="Comments recorded against this analysis.",
            widths=[1.0, 0.9, 1.0, 0.9, 2.2, 0.7])

    def actions_section(self) -> None:
        if not self.bundle.actions:
            return
        self.section("Remediation actions")
        self.table(
            ["Action", "Owner", "Proposed due date", "Status"],
            [[one.get("action", ""), one.get("owner", ""),
              one.get("due", ""), one.get("status", "Proposed")]
             for one in self.bundle.actions],
            caption="Actions proposed by this analysis.",
            widths=[3.2, 1.2, 1.2, 0.8])

    def render(self) -> bytes:
        buffer = io.BytesIO()
        self.document.save(buffer)
        return buffer.getvalue()


def _population(scope: dict[str, Any]) -> str:
    customers = scope.get("customers")
    facilities = scope.get("facilities")
    if customers is None and facilities is None:
        return "—"
    return (f"{int(customers or 0):,} customers across "
            f"{int(facilities or 0):,} facilities")


def _money(value: Any) -> str:
    try:
        return f"{float(value):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _pct(value: Any, places: int = 2) -> str:
    try:
        return f"{float(value):.{places}f}%"
    except (TypeError, ValueError):
        return "—"


def _rate(value: Any, places: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{places}f}%"
    except (TypeError, ValueError):
        return "—"


# ============================================ family 1: the investigation

def investigation_bundle(analysis: dict[str, Any], *,
                         prepared_by: str = "",
                         comments: list[dict[str, Any]] | None = None,
                         actions: list[dict[str, Any]] | None = None
                         ) -> Bundle:
    """A bundle from `analysis_delinquency.run`, with nothing recomputed."""
    scope = dict(analysis.get("scope") or {})
    return Bundle(
        family=INVESTIGATION,
        title=f"{scope.get('label', 'Retail')} — delinquency and ECL "
              f"decomposition",
        subtitle=f"{scope.get('prior', '')} to {scope.get('month', '')}",
        result=analysis,
        scope=scope,
        findings=list(analysis.get("findings") or []),
        comments=list(comments or []),
        actions=list(actions or []),
        limitations=list(analysis.get("limitations") or []),
        versions={
            "analysis_id": analysis.get("analysis_id"),
            "analysis_version": analysis.get("analysis_version"),
            "method_version": (analysis.get("transitions") or {})
                              .get("method_version"),
        },
        prepared_by=prepared_by,
        as_of=scope.get("month", ""))


def write_investigation(bundle: Bundle) -> bytes:
    """§13's investigation report: the issue, the decomposition, the offsets."""
    analysis = bundle.result
    if not analysis.get("available"):
        raise ReportUnavailable(
            analysis.get("because")
            or "The analysis this report describes is not available.")

    report = Report(bundle)
    report.cover()
    report.document_control()
    report.contents()

    report.section("The attention issue")
    report.para(analysis.get("interpretation", ""))
    rate = analysis.get("rate") or {}
    bridge = analysis.get("rate_bridge") or {}
    report.key_values([
        ("Metric", "30+ DPD rate, exposure-weighted (ret.dpd30.exposure)"),
        ("This month", _pct(rate.get("exposure_weighted_pct"))),
        ("Prior month", _pct(rate.get("exposure_weighted_prior_pct"))),
        ("Change", f"{bridge.get('change_pp', 0):+} percentage points"),
        ("Relative change", _pct(bridge.get("change_relative_pct"))),
        ("By account count",
         f"{_pct(rate.get('account_weighted_prior_pct'))} to "
         f"{_pct(rate.get('account_weighted_pct'))}"),
    ])
    report.para(
        "The two weightings answer different questions and are stated "
        "separately rather than being reconciled to one number. A book of "
        "many small late accounts moves the count rate and not the exposure "
        "rate.")

    report.section("Findings")
    for one in analysis.get("findings") or []:
        report.unnumbered(str(one.get("label", "")), level=3)
        report.para(str(one.get("text", "")))

    report.section("Trend")
    series = analysis.get("trend") or []
    report.table(
        ["Month", "By exposure", "By account", "Facilities", "Customers",
         "Exposure (SAR)"],
        [[one.get("month"), _pct(one.get("exposure_weighted_pct")),
          _pct(one.get("account_weighted_pct")),
          f"{int(one.get('facilities') or 0):,}",
          f"{int(one.get('customers') or 0):,}",
          _money(one.get("exposure_sar"))] for one in series],
        caption=f"30+ DPD over {analysis.get('trend_window', '')}.",
        widths=[0.9, 1.0, 1.0, 1.0, 1.0, 1.4])

    report.section("Where facilities moved")
    moves = analysis.get("transitions") or {}
    report.para(str(moves.get("definition", "")))
    report.key_values([
        ("Matched facilities", f"{moves.get('matched_facilities', 0):,}"),
        ("Moved to a worse bucket",
         f"{(moves.get('worsened') or {}).get('facilities', 0):,}"),
        ("Moved to a better bucket",
         f"{(moves.get('cured') or {}).get('facilities', 0):,}"),
        ("Held their bucket",
         f"{(moves.get('held') or {}).get('facilities', 0):,}"),
        ("Entered the book",
         f"{(moves.get('entrants') or {}).get('facilities', 0):,}"),
        ("Left the book",
         f"{(moves.get('exits') or {}).get('facilities', 0):,}"),
    ])
    cells = [one for one in (moves.get("matrix") or []) if one.get("facilities")]
    report.subsection("Transition matrix")
    report.table(
        ["From", "To", "Facilities", "Opening exposure (SAR)",
         "Closing exposure (SAR)", "Share of the row", "Direction"],
        [[one.get("from"), one.get("to"), f"{one.get('facilities', 0):,}",
          _money(one.get("opening_exposure_sar")),
          _money(one.get("closing_exposure_sar")),
          _pct(one.get("row_share_pct")), one.get("direction")]
         for one in cells],
        caption="Observed movement on facilities present in both months. "
                "Entrants and exits are reported above and are not in this "
                "matrix.",
        widths=[0.8, 0.8, 0.9, 1.3, 1.3, 0.9, 0.8])

    report.section("How that moved the rate")
    report.para(f"Identity: {bridge.get('identity', '')}")
    report.table(
        ["Part", "Contribution (pp)", "What it is"],
        [[one.get("part"), f"{one.get('contribution_pp', 0):+}",
          one.get("detail")] for one in bridge.get("parts") or []],
        caption="The change in the rate, split between its numerator and its "
                "denominator.",
        widths=[1.4, 1.1, 3.4])
    report.subsection("The flows behind the numerator")
    report.table(
        ["Flow", "Facilities", "Amount (SAR)", "What it is"],
        [[one.get("flow"), f"{one.get('facilities', 0):,}",
          _money(one.get("amount")), one.get("detail")]
         for one in bridge.get("numerator_flows") or []],
        caption=f"These flows explain the numerator's movement of SAR "
                f"{_money(bridge.get('numerator_change'))} with a residual of "
                f"SAR {_money(bridge.get('flow_residual'))}.",
        widths=[1.6, 0.9, 1.3, 2.4])
    report.para(str(bridge.get("caution", "")))

    report.section("Where the change sits")
    for cut in analysis.get("mix_bridges") or []:
        report.subsection(f"By {str(cut.get('label', '')).lower()}")
        report.para(f"Mix {cut.get('mix_pp')} pp plus within-rate "
                    f"{cut.get('within_pp')} pp equals "
                    f"{cut.get('total_pp')} pp, against an observed "
                    f"{cut.get('observed_change_pp')} pp. Formula: "
                    f"{cut.get('formula')}")
        report.table(
            ["Segment", "Rate before", "Rate after", "Weight before",
             "Weight after", "Mix (pp)", "Within (pp)", "Total (pp)"],
            [[one.get("segment"), _pct(one.get("rate_before_pct")),
              _pct(one.get("rate_after_pct")),
              _pct(one.get("weight_before_pct")),
              _pct(one.get("weight_after_pct")),
              f"{one.get('mix_pp'):+}", f"{one.get('within_pp'):+}",
              f"{one.get('total_pp'):+}"]
             for one in (cut.get("segments") or [])[:12]],
            caption=str(cut.get("note", "")),
            widths=[1.3, 0.8, 0.8, 0.8, 0.8, 0.7, 0.7, 0.7])

    report.section("The loss allowance, separately")
    ecl = analysis.get("ecl_bridge") or {}
    report.para(str(ecl.get("methodology_note", "")))
    contributions = ecl.get("contributions") or []
    report.table(
        ["Driver", "Amount (SAR)", "Kind", "Facilities"],
        [[one.get("driver"), _money(one.get("amount_sar")),
          one.get("kind", ""), f"{one.get('facility_count', 0):,}"
          if one.get("facility_count") is not None else "—"]
         for one in contributions],
        caption=f"Opening SAR {_money(ecl.get('opening_ecl_sar'))} plus these "
                f"contributions equals closing SAR "
                f"{_money(ecl.get('closing_ecl_sar'))}; unexplained residual "
                f"SAR {ecl.get('unexplained_residual_sar')}.",
        widths=[2.2, 1.3, 1.0, 1.0])

    report.section("What improved")
    offsets = analysis.get("offsets") or {}
    report.key_values([
        ("Facilities that improved bucket",
         f"{offsets.get('cured_facilities', 0):,}"),
        ("Exposure that improved",
         _money(offsets.get("cured_exposure_sar"))),
        ("Facilities that left 30+",
         f"{(offsets.get('out_of_thirty_plus') or {}).get('facilities', 0):,}"),
    ])
    report.para(str(offsets.get("note", "")))

    report.section("Customers carrying most of the movement")
    report.table(
        ["Customer", "Name", "Facilities crossing", "Exposure crossing (SAR)",
         "From", "To"],
        [[one.get("customer_id"), one.get("customer_name"),
          one.get("facilities_crossing"),
          _money(one.get("exposure_crossing_sar")),
          ", ".join(one.get("from_buckets") or []),
          ", ".join(one.get("to_buckets") or [])]
         for one in analysis.get("top_customers") or []],
        caption="Ranked by the exposure that crossed into 30+ this month.",
        widths=[1.1, 1.6, 0.9, 1.4, 0.8, 0.8])

    report.comments_section()
    report.actions_section()

    report.section("Method, limitations and trace")
    for one in analysis.get("limitations") or []:
        report.bullet(str(one))
    report.subsection("Metric definitions used")
    report.table(
        ["Metric", "Numerator", "Denominator", "Horizon"],
        [[one.get("name"), one.get("numerator"), one.get("denominator"),
          one.get("horizon")]
         for one in analysis.get("metrics_used") or []],
        caption="Every figure in this report uses these definitions.",
        widths=[1.3, 2.0, 1.7, 1.0])
    return report.render()


# ======================================= family 2: trait deterioration

def traits_bundle(analysis: dict[str, Any], *, prepared_by: str = "",
                  comments: list[dict[str, Any]] | None = None,
                  actions: list[dict[str, Any]] | None = None) -> Bundle:
    scope = dict(analysis.get("scope") or {})
    periods = analysis.get("periods") or {}
    return Bundle(
        family=TRAITS,
        title=f"{scope.get('label', 'Retail')} — customer traits and ECL "
              f"attribution",
        subtitle=f"{(periods.get('prior') or {}).get('label', '')} against "
                 f"{(periods.get('current') or {}).get('label', '')}",
        result=analysis,
        scope=scope,
        findings=list(analysis.get("findings") or []),
        comments=list(comments or []),
        actions=list(actions or []),
        limitations=list(analysis.get("limitations") or []),
        versions={
            "analysis_id": analysis.get("analysis_id"),
            "analysis_version": analysis.get("analysis_version"),
            "period_policy": (periods.get("policy_version")
                              if isinstance(periods, dict) else ""),
        },
        prepared_by=prepared_by,
        as_of=(analysis.get("measured_at") or {}).get("current", ""))


def write_traits(bundle: Bundle) -> bytes:
    """§13's trait report: the whole inventory, then the mechanism."""
    analysis = bundle.result
    if not analysis.get("available"):
        raise ReportUnavailable(
            analysis.get("because")
            or "The analysis this report describes is not available.")

    report = Report(bundle)
    report.cover()
    report.document_control()
    report.contents()

    report.section("Question, periods and population")
    report.para(analysis.get("interpretation", ""))
    periods = analysis.get("periods") or {}
    measured = analysis.get("measured_at") or {}
    scope = analysis.get("scope") or {}
    report.key_values([
        ("Current window", (periods.get("current") or {}).get("label")),
        ("Comparison window", (periods.get("prior") or {}).get("label")),
        ("Measured at", f"{measured.get('reference')} against "
                        f"{measured.get('current')}"),
        ("Alternative mode", analysis.get("alternative_mode")),
        ("Facilities", f"{scope.get('facilities', 0):,}"),
        ("Customers", f"{scope.get('customers', 0):,}"),
        ("Matched facilities", f"{scope.get('matched_facilities', 0):,}"),
        ("Entered the book", f"{scope.get('entrants', 0):,}"),
        ("Left the book", f"{scope.get('exits', 0):,}"),
    ])
    report.para(str(scope.get("note", "")))

    report.section("Executive answer")
    for one in analysis.get("findings") or []:
        report.unnumbered(str(one.get("label", "")), level=3)
        report.para(str(one.get("text", "")))

    report.section("Every model input, reviewed")
    counts = analysis.get("inventory_counts") or {}
    report.key_values([(str(k).capitalize(), f"{v:,}")
                       for k, v in counts.items()])
    report.para(
        "The complete inventory follows. A shortlist of the largest movers "
        "hides the variables that did NOT move, which is half of what a "
        "reader needs in order to believe the ones that did.")
    inventory = analysis.get("inventory") or []
    report.table(
        ["Input", "Model", "Direction", "CSI", "Band", "Missing now",
         "Mean points change", "Assessment"],
        [[one.get("business_name"), one.get("model_id"),
          one.get("direction"),
          "—" if one.get("csi") is None else f"{one['csi']:.4f}",
          one.get("csi_band"), _pct(one.get("missing_current_pct")),
          "—" if one.get("mean_points_change") is None
          else f"{one['mean_points_change']:+.2f}",
          one.get("assessment")]
         for one in inventory],
        caption=f"All {len(inventory)} inputs of the active scorecards in "
                f"scope.",
        widths=[1.6, 1.3, 0.8, 0.6, 0.6, 0.7, 0.8, 1.0])

    report.section("The largest movements")
    report.subsection("Deteriorated")
    report.table(
        ["Input", "CSI", "Points change", "Facilities affected",
         "Exposure affected (SAR)", "Why"],
        [[one.get("display_name"), f"{one.get('csi', 0):.4f}",
          f"{one.get('mean_points_change', 0):+.2f}",
          f"{one.get('affected_facilities', 0):,}",
          _money(one.get("affected_exposure_sar")), one.get("why")]
         for one in analysis.get("top_deteriorated") or []],
        caption="Ranked by the fall in the points this input contributes.",
        widths=[1.7, 0.6, 0.8, 0.9, 1.2, 2.2])
    report.subsection("Improved")
    report.table(
        ["Input", "CSI", "Points change", "Why"],
        [[one.get("display_name"), f"{one.get('csi', 0):.4f}",
          f"{one.get('mean_points_change', 0):+.2f}", one.get("why")]
         for one in analysis.get("top_improved") or []],
        caption="Improvements are reported beside the deterioration rather "
                "than netted into it.",
        widths=[1.8, 0.7, 0.9, 3.0])

    report.subsection("Grouped drivers")
    report.para(
        "Inputs that read one underlying change are grouped. Income, debt "
        "burden and disposable income all derive from the same source field, "
        "and adding three one-variable shocks would count one change three "
        "times.")
    report.table(
        ["Group", "Deteriorated", "Improved", "Points change",
         "Facilities affected"],
        [[one.get("group"), ", ".join(one.get("deteriorated") or []) or "—",
          ", ".join(one.get("improved") or []) or "—",
          f"{one.get('points_change', 0):+.2f}",
          f"{one.get('affected_facilities', 0):,}"]
         for one in analysis.get("driver_groups") or []],
        caption="Grouped by the source each input derives from.",
        widths=[1.4, 1.6, 1.4, 0.8, 0.9])

    report.section("Score and band migration")
    migration = analysis.get("score_migration") or {}
    if migration.get("available"):
        report.para(str(migration.get("band_order_note", "")))
        report.key_values([
            ("Scored in both periods",
             f"{migration.get('scored_facilities', 0):,}"),
            ("Moved to a worse band",
             f"{(migration.get('downgraded') or {}).get('facilities', 0):,}"),
            ("Moved to a better band",
             f"{(migration.get('upgraded') or {}).get('facilities', 0):,}"),
            ("Unchanged",
             f"{(migration.get('unchanged') or {}).get('facilities', 0):,}"),
        ])
        cells = [one for one in migration.get("matrix") or []
                 if one.get("facilities")]
        report.table(
            ["From", "To", "Facilities", "Customers", "Exposure (SAR)",
             "Share of row", "Direction"],
            [[one.get("from"), one.get("to"), f"{one.get('facilities', 0):,}",
              f"{one.get('customers', 0):,}",
              _money(one.get("exposure_sar")),
              _pct(one.get("count_share_pct")), one.get("direction")]
             for one in cells],
            caption="Unchanged and improving populations are included.",
            widths=[0.7, 0.7, 0.9, 0.9, 1.3, 0.9, 0.9])
    else:
        report.para(str(migration.get("because")
                        or "No score migration was computed."))

    report.section("PD and stage propagation")
    pd_block = analysis.get("pd") or {}
    report.key_values([
        ("Metric", pd_block.get("metric_id")),
        ("Mean PD before", _rate(pd_block.get("mean_before"), 4)),
        ("Mean PD after", _rate(pd_block.get("mean_after"), 4)),
        ("Change", _rate(pd_block.get("change"), 4)),
        ("Basis", pd_block.get("basis")),
    ])
    stages = analysis.get("stage_movement") or {}
    if stages.get("available"):
        report.table(
            ["From stage", "To stage", "Facilities", "Exposure (SAR)",
             "Direction"],
            [[one.get("from"), one.get("to"), f"{one.get('facilities', 0):,}",
              _money(one.get("exposure_sar")), one.get("direction")]
             for one in stages.get("matrix") or [] if one.get("facilities")],
            caption=str(stages.get("note", "")),
            widths=[1.0, 1.0, 1.0, 1.5, 1.0])
    else:
        report.para(str(stages.get("because") or "No stage movement."))

    report.section("The loss allowance")
    ecl = analysis.get("ecl_bridge") or {}
    report.para(str(ecl.get("methodology_note", "")))
    report.table(
        ["Driver", "Amount (SAR)", "Kind"],
        [[one.get("driver"), _money(one.get("amount_sar")), one.get("kind")]
         for one in ecl.get("contributions") or []],
        caption=f"Opening SAR {_money(ecl.get('opening_ecl_sar'))} to closing "
                f"SAR {_money(ecl.get('closing_ecl_sar'))} on the matched "
                f"population.",
        widths=[2.6, 1.6, 1.2])

    report.comments_section()
    report.actions_section()

    report.section("What this is, and what it is not")
    for one in analysis.get("limitations") or []:
        report.bullet(str(one))
    return report.render()


# ============================================================ the service

def render(family: str, bundle: Bundle) -> tuple[bytes, str]:
    """Build one report. Raises rather than returning an apology as a file."""
    writers = {INVESTIGATION: write_investigation, TRAITS: write_traits}
    writer = writers.get(family)
    if writer is None:
        raise ReportUnavailable(f"{family!r} is not a report this service "
                                f"writes.")
    payload = writer(bundle)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    label = "".join(one if one.isalnum() else "_"
                    for one in (bundle.scope.get("label") or "Retail"))[:40]
    return payload, f"{family}_{label}_{stamp}.docx"
