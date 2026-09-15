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
    writers = {INVESTIGATION: write_investigation, TRAITS: write_traits,
               VALIDATION: write_validation}
    writer = writers.get(family)
    if writer is None:
        raise ReportUnavailable(f"{family!r} is not a report this service "
                                f"writes.")
    payload = writer(bundle)
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    label = "".join(one if one.isalnum() else "_"
                    for one in (bundle.scope.get("label") or "Retail"))[:40]
    return payload, f"{family}_{label}_{stamp}.docx"


# ================================== family 3: the validation report

#: Test id prefix -> the category it belongs to and how it is titled.
#:
#: The engine returns 48 flat results. §15 wants them grouped into the report's
#: sections, and §14.1 is explicit that a Champion vs Challenger result must
#: never appear under Data & Representativeness, so the mapping is written
#: down here rather than inferred from whatever order the results arrive in.
VALIDATION_SECTIONS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("conceptual", "Conceptual soundness and design",
     ("CONC-",)),
    ("data", "Data quality and representativeness",
     ("DATA-", "REP-")),
    ("univariate", "Univariate and bivariate evidence",
     ("VAR-", "BIN-")),
    ("drift", "Population and score drift",
     ("STAB-PSI", "STAB-CSI", "STAB-BAND", "PSI", "CSI", "DRIFT-")),
    ("discrimination", "Discrimination, rank order and gains",
     ("DISC-", "AUC", "KS-", "GINI")),
    ("calibration", "Calibration and comparable default rates",
     ("CAL-",)),
    ("stability", "Stability, robustness and implementation verification",
     ("STAB-", "ROB-", "IMPL-", "IMP-")),
    ("segmentation", "Product, classification and sub-product performance",
     ("SEG-",)),
    ("usage", "Usage, overrides and challenger comparison",
     ("USE-", "OVR-", "CHAL-", "CC-")),
)

#: Every state the engine can return, and what it means for a reader. §14.2:
#: a Not Run or an insufficient-evidence result must never be reported as a
#: pass, and the report must show them all rather than only the successes.
STATE_MEANING: dict[str, str] = {
    "PASS": "Measured, and inside its configured limit.",
    "WARNING": "Measured, and close enough to its limit to watch.",
    "FAIL": "Measured, and outside its configured limit.",
    "NO_LIMIT": "Measured. No limit is configured, so this is evidence "
                "rather than a verdict.",
    "UNAVAILABLE": "Could not be measured: the data this needs is not "
                   "present.",
    "NOT_MATURED": "Not measured: the outcome window has not closed.",
    "INSUFFICIENT_SAMPLE": "Not measured: too few observations to say "
                           "anything.",
    "NOT_APPLICABLE": "Does not apply to this model.",
    "CALCULATION_ERROR": "The calculation failed. This is an error, not a "
                         "result.",
    "NOT_AUTHORISED": "Not run: this caller may not read what it needs.",
}


def _section_of(test_id: str) -> str:
    name = str(test_id or "").upper()
    for key, _, prefixes in VALIDATION_SECTIONS:
        if any(name.startswith(one) or one in name for one in prefixes):
            return key
    return "other"


def _model_of(run: dict[str, Any]) -> dict[str, Any]:
    """The model, from either shape the validation layer produces.

    A LIVE run nests it under `model`; a STORED run flattens it into
    `model_id`, `model_name`, `model_version`, `model_kind`. Reading only the
    nested shape gave a downloaded report the title "Scorecard — validation
    report" with an empty scope — the document was right about everything
    except which model it was about.
    """
    nested = dict(run.get("model") or {})
    if nested.get("name") or nested.get("model_id"):
        return nested
    return {
        "model_id": run.get("model_id", ""),
        "name": run.get("model_name", ""),
        "version": run.get("model_version", ""),
        "scorecard_type": run.get("model_kind", ""),
        "domain": run.get("domain", ""),
    }


def validation_bundle(run: dict[str, Any], *, prepared_by: str = "",
                      comments: list[dict[str, Any]] | None = None,
                      actions: list[dict[str, Any]] | None = None,
                      conclusion: str = "") -> Bundle:
    model = _model_of(run)
    results = list(run.get("results") or [])
    period = next((one.get("period") for one in results if one.get("period")),
                  "")
    return Bundle(
        family=VALIDATION,
        title=f"{model.get('name', 'Scorecard')} — validation report",
        subtitle=f"Version {model.get('version', '')} · observation window "
                 f"{period}",
        result={**run, "conclusion": conclusion},
        scope={"label": model.get("name", ""),
               "month": period,
               "customers": None, "facilities": None},
        findings=list(run.get("findings") or []),
        comments=list(comments or []),
        actions=list(actions or []),
        limitations=sorted({one for result in results
                            for one in (result.get("limitations") or [])}),
        versions={
            "model_id": model.get("model_id"),
            "model_version": model.get("version"),
            "scorecard_type": model.get("scorecard_type"),
            "domain": model.get("domain"),
            "run_key": run.get("run_key"),
            "calculation_version": run.get("calculation_version"),
        },
        prepared_by=prepared_by,
        as_of=period)


def write_validation(bundle: Bundle) -> bytes:
    """§15's fifteen sections, including every test that did NOT run."""
    run = bundle.result
    results = list(run.get("results") or [])
    if not results:
        raise ReportUnavailable(
            "This validation run produced no test results, so there is "
            "nothing to report on.")

    report = Report(bundle)
    report.cover()
    report.document_control()
    report.contents()

    model = _model_of(run)
    tally = dict(run.get("tally") or {})

    report.section("Executive opinion")
    summary = dict(run.get("findings_summary") or {})
    severities = dict(summary.get("by_severity") or {})
    report.para(
        f"{len(results)} tests were executed against "
        f"{model.get('name', 'this model')} version "
        f"{model.get('version', '')}. "
        f"{tally.get('FAIL', 0)} failed, {tally.get('WARNING', 0)} are on "
        f"watch, {tally.get('PASS', 0)} passed, and "
        f"{sum(v for k, v in tally.items() if k not in ('PASS', 'FAIL', 'WARNING'))} "
        f"produced no verdict — either because no limit is configured for "
        f"them or because they do not apply. Every one of them is listed in "
        f"this report.")
    report.table(
        ["State", "Tests", "What it means"],
        [[state, count, STATE_MEANING.get(state, "")]
         for state, count in tally.items()],
        caption="Every result state the run produced. A test without a "
                "verdict is not a pass.",
        widths=[1.4, 0.7, 4.2])
    if bundle.findings:
        report.subsection("Material findings")
        report.table(
            ["Finding", "Severity", "Category", "What", "Why it matters"],
            [[one.get("title"), one.get("severity"), one.get("category"),
              one.get("what"), one.get("why_it_matters")]
             for one in bundle.findings],
            caption=f"{summary.get('total', len(bundle.findings))} findings: "
                    + ", ".join(f"{k} {v}" for k, v in severities.items() if v),
            widths=[1.4, 0.8, 1.0, 1.8, 1.4])

    report.section("Model purpose, version and provenance")
    report.key_values([
        ("Model", model.get("name")),
        ("Model ID", model.get("model_id")),
        ("Version", model.get("version")),
        ("Type", model.get("scorecard_type")),
        ("Governed domain", model.get("domain")),
        ("Run key", run.get("run_key")),
        ("Calculation version", run.get("calculation_version")),
        ("Score direction", next((one.get("score_direction")
                                  for one in results
                                  if one.get("score_direction")), "—")),
    ])

    report.section("Validation sample, outcome definition and maturity")
    sample = next((one for one in results if one.get("observations")), {})
    report.key_values([
        ("Dataset", sample.get("dataset")),
        ("Observation window", sample.get("period")),
        ("Reference period", sample.get("reference_period") or "—"),
        ("Observations", f"{int(sample.get('observations') or 0):,}"),
        ("Matured observations",
         f"{int(sample.get('matured_observations') or 0):,}"),
        ("Events", f"{int(sample.get('events') or 0):,}"),
    ])
    report.para(
        "A twelve-month outcome can only be observed for an observation made "
        "at least twelve months before the latest month in the book. Tests "
        "whose window has not closed are reported as not matured rather than "
        "being measured on a partial outcome, which would understate the "
        "default rate for reasons that have nothing to do with the model.")

    # --- §15 sections 5 to 12, one per category, every test listed --------
    grouped: dict[str, list[dict[str, Any]]] = {}
    for one in results:
        grouped.setdefault(_section_of(one.get("test_id")), []).append(one)

    for key, title, _ in VALIDATION_SECTIONS:
        rows = grouped.get(key) or []
        report.section(title)
        if not rows:
            report.para("No test in this run belongs to this category. It is "
                        "reported as empty rather than omitted, so a reader "
                        "can see that it was not silently skipped.")
            continue
        report.table(
            ["Test", "State", "Measured", "Limit", "Limit source", "Detail"],
            [[one.get("test_id"), one.get("state_label") or one.get("state"),
              _measured(one), _limit(one), one.get("limit_source") or "—",
              one.get("detail") or STATE_MEANING.get(one.get("state"), "")]
             for one in rows],
            caption=f"{len(rows)} test(s). States: "
                    + ", ".join(sorted({str(one.get('state')) for one in rows})),
            widths=[1.1, 0.8, 0.9, 0.7, 0.9, 2.6])
        for one in rows:
            table = one.get("table")
            if isinstance(table, list) and table and isinstance(table[0], dict):
                report.unnumbered(f"{one.get('test_id')} — evidence", level=3)
                columns = list(table[0])[:8]
                report.table(
                    [str(c).replace("_", " ").capitalize() for c in columns],
                    [[row.get(c) for c in columns] for row in table[:30]],
                    caption=f"Evidence behind {one.get('test_id')}.")

    # A test that falls outside every named category is a mapping gap, not a
    # category. It is reported as one so the gap is visible rather than
    # quietly becoming a section of its own.
    if grouped.get("other"):
        report.section("Tests not mapped to a category")
        report.para(
            "These tests ran and are reported, but this report has no section "
            "mapped to them. That is a gap in the mapping rather than a "
            "finding about the model.")
        report.table(
            ["Test", "State", "Detail"],
            [[one.get("test_id"), one.get("state"), one.get("detail")]
             for one in grouped["other"]],
            caption="Tests this report does not map to a named category.",
            widths=[1.2, 1.0, 4.0])

    report.section("Linked findings across categories")
    if bundle.findings:
        report.para(
            "A finding is one record referenced from every category it "
            "touches, so the same metric, threshold and sample date appear "
            "identically wherever it is cited.")
        report.table(
            ["Finding", "Category", "Severity", "Remediation"],
            [[one.get("finding_id"), one.get("category"),
              one.get("severity"), one.get("remediation")]
             for one in bundle.findings],
            caption="Findings and their proposed remediation.",
            widths=[1.0, 1.1, 0.9, 3.4])
    else:
        report.para("This run produced no findings.")

    report.comments_section()
    report.actions_section()

    report.section("Conclusion, limitations and method")
    if run.get("conclusion"):
        report.para(str(run["conclusion"]))
    else:
        report.para(
            "No overall conclusion has been recorded by an analyst. This "
            "report states what was measured; the opinion on whether the "
            "model remains fit for its use is a human judgement and is not "
            "generated here.")
    report.subsection("Limitations")
    for one in bundle.limitations:
        report.bullet(str(one))
    report.bullet(PROVENANCE)
    report.subsection("Thresholds")
    report.para(
        "Every limit in this report is a demo policy with an owner, not a "
        "regulatory constant. The limit source column names which policy set "
        "a test was judged against; a test showing NO LIMIT was measured and "
        "not judged.")
    report.subsection("Trace")
    report.table(
        ["Test", "Dataset", "Period", "Observations", "Events",
         "Calculation version"],
        [[one.get("test_id"), one.get("dataset"), one.get("period"),
          f"{int(one.get('observations') or 0):,}",
          f"{int(one.get('events') or 0):,}",
          one.get("calculation_version")] for one in results],
        caption="Every test, and the exact data it read.",
        widths=[1.1, 1.4, 1.2, 0.9, 0.7, 1.0])
    return report.render()


def _measured(one: dict[str, Any]) -> str:
    if not one.get("measured"):
        return "not measured"
    value = one.get("value")
    try:
        return f"{float(value):,.4f}"
    except (TypeError, ValueError):
        return "—" if value is None else str(value)


def _limit(one: dict[str, Any]) -> str:
    value = one.get("limit")
    if value is None:
        return "none"
    try:
        return f"{float(value):,.4f}"
    except (TypeError, ValueError):
        return str(value)
