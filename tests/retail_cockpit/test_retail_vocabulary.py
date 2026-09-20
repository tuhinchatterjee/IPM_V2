"""No corporate vocabulary on a retail Cockpit, and the record says what moved.

The defect this exists for
--------------------------
The ECL-highlights caption in the ported `attention-panel.tsx` read *"by
sector, by borrower and across the book"* -- on a retail book that has
neither sectors nor borrowers. The heading directly above it adapts, because
the server names its own section (`attention_v2.HIGHLIGHT_LABELS`); the
caption had no such field and named the corporate cut in its own JSX.

Fixing it meant editing a file that was ported verbatim, which is approved as
**F1** and recorded in `docs/retail_cockpit/PORTED_FILES.md`. These tests are
what stop that approval from decaying into "the frontend port is whatever it
is now":

- the retail wording must not contain the two words the browser check greps
  for, so the fix cannot be half-done;
- the corporate wording must be byte-identical to the original, so the frozen
  book's page is provably unchanged by this;
- the file's SHA-256 must equal the one the record publishes, so the record
  and the file cannot drift apart.

The third is not decoration. `scripts/retail_cockpit/verify_port.py` checks
all 291 hashes but nothing in the test suite called it, so the frontend half
of the port has been a documentary guarantee only. It is a checked one from
here.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PANEL = ROOT / "frontend/src/components/cockpit-v4/attention-panel.tsx"
RECORD = ROOT / "docs/retail_cockpit/PORTED_FILES.md"
COCKPIT_V4 = ROOT / "frontend/src/components/cockpit-v4"

#: Exactly what the frozen component said, character for character. The
#: corporate book must keep reading this.
CORPORATE = "by sector, by borrower and across the book"

#: What the browser check greps the whole page for, at
#: `tests/retail_cockpit/browser/candidate.browser.mjs`.
FORBIDDEN_ON_RETAIL = ("sector", "borrower")

_ENTRY = re.compile(r'^\s*(corporate|retail):\s*"([^"]*)",\s*$', re.M)


def _spread() -> dict[str, str]:
    """`HIGHLIGHT_SPREAD` as the component actually declares it."""
    source = PANEL.read_text(encoding="utf-8")
    start = source.find("const HIGHLIGHT_SPREAD")
    assert start != -1, "the component no longer declares HIGHLIGHT_SPREAD"
    end = source.find("};", start)
    assert end != -1
    found = dict(_ENTRY.findall(source[start:end]))
    assert set(found) == {"corporate", "retail"}, found
    return found


def test_the_retail_caption_names_no_sector_and_no_borrower() -> None:
    retail = _spread()["retail"].lower()
    named = [word for word in FORBIDDEN_ON_RETAIL if word in retail]
    assert not named, (
        f"the retail ECL caption still says {named}: {retail!r}. The retail "
        f"book is cut by product -- attention_v2._highlights uses "
        f"dimension='product' for it -- and the browser suite greps the "
        f"whole page for exactly these words.")


def test_the_retail_caption_names_what_the_cards_actually_are() -> None:
    # Not merely the absence of the wrong word: the server groups the retail
    # highlights by product and adds the whole-book figures, so the caption
    # has to say that or it is describing cards that are not there.
    retail = _spread()["retail"].lower()
    assert "product" in retail and "book" in retail, retail


def test_the_corporate_caption_is_unchanged() -> None:
    # F1 is a retail fix. If it altered a single character of what the
    # corporate book reads, it stopped being one.
    assert _spread()["corporate"] == CORPORATE


def test_the_caption_is_driven_by_the_book_rather_than_hard_coded() -> None:
    source = PANEL.read_text(encoding="utf-8")
    assert "HIGHLIGHT_SPREAD[feed.domain_id]" in source, (
        "the caption no longer reads the book off the feed, so it is naming "
        "one book's dimensions on every book again")
    # The old literal must be gone from the JSX. It survives only inside the
    # per-book map and the comment that explains it.
    assert "developments\"} — by" not in source


def test_the_record_and_the_file_agree() -> None:
    row = re.search(
        r"^\|\s*`frontend/src/components/cockpit-v4/attention-panel\.tsx`\s*"
        r"\|\s*`?([0-9a-f]{8,64})`?\s*\|\s*(.+?)\s*\|\s*$",
        RECORD.read_text(encoding="utf-8"), re.M)
    assert row, f"{RECORD.name} no longer records attention-panel.tsx"
    recorded, note = row.group(1), row.group(2)
    digest = hashlib.sha256(PANEL.read_bytes()).hexdigest()
    assert digest.startswith(recorded), (
        f"attention-panel.tsx is {digest[:16]} but the record says "
        f"{recorded}. Update docs/retail_cockpit/PORTED_FILES.md -- an "
        f"unrecorded edit to a ported file is exactly what that file exists "
        f"to catch.")
    assert "exception" in note.lower() and "F1" in note, (
        f"the record calls this file {note!r}. It is not verbatim any more "
        f"and must not be recorded as though it were.")


#: `.tsx` files whose JSX a retail reader can see. `.test.ts` files and the
#: per-book tables that select by domain at runtime are not page text.
_ALLOWED = {"domain-meta.ts", "follow-ups.ts", "domain-switch.tsx"}


@pytest.mark.parametrize("word", FORBIDDEN_ON_RETAIL)
def test_no_other_component_renders_corporate_vocabulary(word: str) -> None:
    """The caption was the only one. This is what keeps it that way.

    Comments, type names and `.test.ts` files are not page text, and neither
    are the three modules that already key their wording on the book. What is
    left is JSX a retail reader would actually read.
    """
    offenders: list[str] = []
    for path in sorted(COCKPIT_V4.glob("*.tsx")):
        if path.name in _ALLOWED or path.name.endswith(".test.tsx"):
            continue
        for number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith(("*", "//", "/*", "{/*")):
                continue
            if word in stripped.lower():
                offenders.append(f"{path.name}:{number}: {stripped}")
    # The per-book map in attention-panel.tsx is the corporate branch, which
    # a retail reader never sees. Everything else is a finding.
    offenders = [o for o in offenders
                 if not o.startswith("attention-panel.tsx")
                 or "corporate:" not in o]
    assert not offenders, "\n".join(offenders)
