"""Which reader produced a parse, and whether it is still the current one. §18.

Why a version at all
--------------------
The uploaded bytes never change. Improving a reader therefore does not
invalidate the upload — it invalidates the READING. A source read by an older
reader still holds everything it always held; what it is missing is whatever
the newer reader would now find. Number formats, for instance: before
`sheets` learned to read `number_format`, every spreadsheet cell came back at
full float precision and a report had to print seventeen significant digits to
survive grounding. Every workbook parsed before that change is readable; it is
just read worse.

So the fix is a re-read of the stored bytes — local, free, no provider call,
and no asking the user to find the file again. A parser version is what makes
"this was read worse" a fact the system can state rather than a suspicion.

How to change one
-----------------
Bump the format's entry here in the same commit that changes its reader, and
say in `CHANGES` what a re-read now finds. Two rules:

* **Bump when the OUTPUT can differ** — different chunks, different locators,
  different `data`, a different manifest. A refactor that cannot change what
  comes out is not a version change, and pretending otherwise asks every user
  to re-read every file for nothing.
* **Never re-use a number.** The version is recorded on parses that already
  exist and cannot be corrected retrospectively.

`SCHEMA_VERSION` is separate and spans every format: it moves when the SHAPE
of a chunk changes — a new field, a changed meaning — rather than when one
reader gets better. A parse is stale if either is behind.
"""

from __future__ import annotations

from backend.playbook.ingest import validate

#: The chunk contract itself: kinds, locator grammar, `data` keys.
#:
#: 1 — the original shape.
#: 2 — spreadsheet cells carry three readings (`rows` as displayed,
#:     `raw_rows` as stored, `cells` as addresses) rather than one.
SCHEMA_VERSION = "2"

#: Per-format reader versions. See CHANGES for what each one means.
PARSER_VERSIONS = {
    validate.DOCX: "1",
    validate.PDF: "1",
    validate.XLSX: "2",
    validate.CSV: "2",
    validate.PPTX: "1",
}

#: The fallback for a format with no reader of its own — plain text, read
#: whole. It has no history of its own; it is here so that every parse records
#: a version rather than an empty string.
DEFAULT_VERSION = "1"

#: What changed, per format and version, in words a user can act on. Shown
#: beside a stale source so "re-read" is a decision rather than a leap.
CHANGES = {
    (validate.XLSX, "2"): (
        "Spreadsheet cells are now read three ways — as displayed, as stored, "
        "and by address — so a figure can be quoted the way the workbook "
        "shows it instead of at full stored precision."),
    (validate.CSV, "2"): (
        "Rows now carry their cell addresses, so a figure taken from a CSV "
        "can be cited to the cell it came from."),
}


def current(kind: str) -> str:
    """The reader version in force for this format right now."""
    return PARSER_VERSIONS.get(kind, DEFAULT_VERSION)


def is_stale(kind: str, *, parser_version: str, schema_version: str) -> bool:
    """Whether a parse was made by something older than what is in force.

    Only BEHIND counts. A parse recorded by a newer version than this code
    knows about — a database restored from a later deployment — is left alone
    rather than re-read backwards into a worse reading.
    """
    return (_behind(parser_version, current(kind))
            or _behind(schema_version, SCHEMA_VERSION))


def _behind(recorded: str, now: str) -> bool:
    try:
        return int(recorded or 0) < int(now)
    except (TypeError, ValueError):
        # An unparseable version is one this code did not write. Treated as
        # stale, because the alternative is silently trusting a reading whose
        # provenance cannot be established.
        return (recorded or "") != now


def what_changed(kind: str, *, parser_version: str) -> list[str]:
    """Every improvement between the recorded version and the current one."""
    try:
        was, now = int(parser_version or 0), int(current(kind))
    except (TypeError, ValueError):
        return []
    return [CHANGES[(kind, str(v))] for v in range(was + 1, now + 1)
            if (kind, str(v)) in CHANGES]
