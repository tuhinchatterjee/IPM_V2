"""
What a CreditProbe export IS, before anything is written.

Two workbooks, and the difference between them is the whole design:

    RESULTS WORKBOOK       what the analysis found. Two or three sheets, opened
                           in a meeting, mailed to a committee.
    CALCULATION PACK       how it found it. Twenty sheets, opened by Internal
                           Audit, a methodology owner or a model-risk reviewer
                           who has to reconstruct the number.

One rule shapes both and is worth stating before the code: **an export never
recomputes.** It reads what was persisted when the analysis ran — the result,
the trace, the plan, the SQL, the reconciliation, the fingerprint — and writes
it down. An export that re-ran the analysis would be a second answer wearing
the first one's filename, and the moment the data moved on, the workbook and
the screen would disagree with nobody able to say which was right.

That is also why there is no model call anywhere below this line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

#: What the workbook writer understands about itself. Bumped when the sheet
#: structure changes, so a workbook found on a shared drive in two years can be
#: matched against the code that wrote it.
SCHEMA_VERSION = "1.0"
GENERATOR_VERSION = "creditprobe-exports/1.0"

RESULTS = "results"
CALCULATION_PACK = "calculation_pack"

XLSX_MIME = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

#: Excel's own limits. Exceeding either produces a file Excel refuses to open,
#: so they are enforced here rather than discovered by the reader.
EXCEL_MAX_ROWS = 1_048_576
EXCEL_MAX_COLUMNS = 16_384

#: How many data rows a single sheet may carry before the writer splits.
#: Well under Excel's limit: a sheet that opens is not the same as a sheet
#: anybody can work with, and 250k rows is already past that point.
ROWS_PER_SHEET = 250_000

#: The largest analytical population a workbook will carry inline. Above this
#: the pack says so and names the governed extract instead of silently
#: truncating — §24, and the failure it prevents is a reviewer concluding the
#: population was 100,000 rows because that is where the sheet stopped.
MAX_INLINE_POPULATION_ROWS = 100_000

#: How long a workbook may take to build before the request gives up. A reader
#: waiting on a spinner needs an answer, and "still working" after a minute is
#: not one.
GENERATION_TIMEOUT_SECONDS = 120


class ExportError(RuntimeError):
    """An export that could not be produced, with something to tell the user."""

    def __init__(self, code: str, message: str, *, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class NotExportable(ExportError):
    """This run has nothing to export — a clarification, a refusal, a failure."""

    def __init__(self, message: str) -> None:
        super().__init__("not_exportable", message, status=409)


class RunNotFound(ExportError):
    """No such analysis run, or no such Trace version of it.

    Separate from NotExportable because they are different answers: "this run
    produced a clarification rather than a result" is a fact about an analysis
    that exists, and a reader who is told 409 for both cannot tell whether they
    typed the wrong id or asked the wrong question.
    """

    def __init__(self, message: str) -> None:
        super().__init__("run_not_found", message, status=404)


class TooLarge(ExportError):
    """The workbook would exceed what Excel or this deployment can carry."""

    def __init__(self, message: str) -> None:
        super().__init__("export_too_large", message, status=413)


@dataclass
class Workbook:
    """A finished workbook, ready to be handed to a browser."""

    filename: str
    content: bytes
    kind: str
    #: What went into it, for the audit log and for the caller's headers.
    manifest: dict[str, Any] = field(default_factory=dict)

    @property
    def size(self) -> int:
        return len(self.content)


# --------------------------------------------------------------- filenames


#: Characters Windows refuses in a filename, plus the ones that make a shell
#: or a browser misread one. The product is used on Windows laptops, so a
#: filename that is legal on Linux and rejected by Explorer is a broken
#: download rather than a cosmetic problem.
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_COLLAPSE = re.compile(r"[\s_]+")


def slug(text: str, *, limit: int = 60) -> str:
    """A filename fragment that is safe on Windows, macOS and Linux.

    Lower case, underscore-separated, no reserved characters, no trailing dot
    or space (Explorer silently strips both, so a name ending in one is a name
    that changes when it lands).
    """
    cleaned = _UNSAFE.sub(" ", str(text or ""))
    cleaned = _COLLAPSE.sub("_", cleaned.strip())
    cleaned = re.sub(r"[^A-Za-z0-9_.-]", "", cleaned).strip("._-")
    return (cleaned[:limit] or "analysis").lower()


def filename_for(kind: str, *, analysis: str, period: str, run_id: int,
                 fingerprint: str = "") -> str:
    """The name the file lands under.

    Carries the analysis, the period and a short run id, so a folder of them
    sorts and reads sensibly and two exports of different runs never collide.
    """
    short = (fingerprint or "")[:6] or f"{run_id}"
    suffix = "results" if kind == RESULTS else "calculation_pack"
    named = slug(analysis, limit=48)
    stamp = slug(period, limit=16) if period else ""
    # An analysis is usually titled by its own scope — "…by sector at Q2 2026" —
    # so appending the period again produces "..._at_q2_2026_q2_2026_", which
    # reads as a mistake in a folder even though the file is correct.
    if stamp and named.endswith(f"_{stamp}"):
        named = named[: -len(stamp) - 1].removesuffix("_at")
    parts = ["CreditProbe", named, stamp, slug(short, limit=12), suffix]
    return "_".join(p for p in parts if p) + ".xlsx"


#: Excel forbids these in a sheet name, and caps the name at 31 characters.
_SHEET_UNSAFE = re.compile(r"[\[\]:*?/\\]")


def sheet_name(text: str, *, taken: set[str] | None = None) -> str:
    """A worksheet name Excel will accept, unique within the workbook.

    Excel silently refuses to open a file with a duplicate or over-long sheet
    name, so uniqueness is enforced here rather than hoped for. The numeric
    suffix is appended INSIDE the 31-character budget, not after it.
    """
    cleaned = _SHEET_UNSAFE.sub(" ", str(text or "Sheet")).strip() or "Sheet"
    cleaned = cleaned[:31]
    if taken is None:
        return cleaned
    if cleaned not in taken:
        taken.add(cleaned)
        return cleaned
    for n in range(2, 1000):
        suffix = f" {n}"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    raise ExportError("sheet_names_exhausted",
                      "Too many sheets share a name to number them apart.")
