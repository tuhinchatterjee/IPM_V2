"""
Composing a product answer somebody wants to read.

The knowledge registries hold everything CreditProbe knows about itself. This
module decides how much of it one question actually needs, in what shape, and
whether the result is fit to show.

Why it exists
-------------
The first version of the product layer answered "What is CreditProbe AI?" with
five thousand characters: seven sections, all eighteen capabilities, the value
flow, the continuum and the installation counts, every time, joined into one
run of prose with upper-cased headings. Every fact in it was true and checked.
It was still the wrong answer, because nobody reads it.

Three separate mechanisms produced that, and all three are fixed here:

1.  **No selection.** The composer returned everything the registry held. It
    now returns what the QUESTION needs, and offers the rest.
2.  **No structure.** Sections were flattened into plain lines. They are now
    emitted as Markdown - headings, bold, bullets, short paragraphs, blank
    lines - and the answer surface renders that structure.
3.  **No limit.** Nothing capped the size. Every answer now declares a length
    band, and a gate checks the composed answer against it.

Progressive disclosure
----------------------
A section may be marked `detail`. Detail is written once, in the registry, and
shown only when the question asks for depth — "explain the Early Warning
methodology IN DETAIL" - or when the reader takes up the offer in the
follow-ups. That is the whole of the mechanism: the knowledge is retrieved,
the composer selects, and what is held back is offered rather than dropped.

The gate
--------
`inspect` is the eleven-point check from the remediation, run on the composed
Markdown rather than on the intention behind it. It is deliberately possible
for it to fail: an answer that fails carries its failures in the payload, and
a test asserts that every acceptance question passes. A gate that cannot fail
would be decoration.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------- length bands
#
# Section 6. The band is a property of the QUESTION, not of how much the
# registry happens to hold.

SHORT = "short"
MEDIUM = "medium"
DETAILED = "detailed"

#: (floor, ceiling) in words. The floor is advisory - an answer shorter than
#: its band is not a defect, an answer longer than it is. The ceiling is
#: enforced.
BANDS: dict[str, tuple[int, int]] = {
    SHORT: (150, 300),
    MEDIUM: (300, 600),
    # An expanded catalogue is legitimately long: "explain the Early Warning
    # methodology in detail" is a request for the forty-three signals, and
    # answering it in six hundred words would be answering a different
    # question. The ceiling still binds - it is roughly four times the
    # methodology's own default, which is the point of the default.
    DETAILED: (600, 2200),
}

#: The opening paragraph is what a reader decides on. Section 14: "Is the
#: opening concise?"
MAX_OPENING_WORDS = 45

#: Section 5: short paragraphs. Anything longer reads as a wall on a laptop.
MAX_PARAGRAPH_WORDS = 70

#: A heading is a signpost, not a sentence.
MAX_HEADING_WORDS = 9

#: One block of unbroken text. Whitespace is the point of the whole exercise.
MAX_BLOCK_CHARS = 700

FLOW_ARROW = " \u2192 "


# ------------------------------------------------------------------ the shape


@dataclass
class Section:
    """One part of an answer: a heading, and what sits under it."""

    key: str
    #: Empty renders no heading at all, which is how an answer opens with prose
    #: before its first section.
    title: str = ""
    #: Markdown heading level. 2 for a section, 3 for something under it.
    depth: int = 2
    #: Paragraphs. Each is emitted with a blank line around it.
    body: list[str] = field(default_factory=list)
    #: Bullets, emitted after the body.
    bullets: list[str] = field(default_factory=list)
    #: An optional table: {"columns": [...], "rows": [[...], ...]}.
    table: dict[str, Any] | None = None
    #: An ordered flow, rendered as a text process flow rather than a chart.
    flow: list[str] = field(default_factory=list)
    #: Held back unless the question asks for depth. This is progressive
    #: disclosure, and it is a property of the CONTENT rather than of the
    #: renderer: the composer never invents a section to drop.
    detail: bool = False
    #: Droppable if the composed answer overruns its band. Ordered content the
    #: answer is better with and survives without.
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "title": self.title,
                               "depth": self.depth, "body": list(self.body)}
        if self.bullets:
            out["bullets"] = list(self.bullets)
        if self.table:
            out["table"] = self.table
        if self.flow:
            out["flow"] = list(self.flow)
        if self.detail:
            out["detail"] = True
        return out


@dataclass
class Answer:
    """A composed product answer, and the band it was composed for."""

    topic: str
    #: The opening paragraph. First person where the user is addressing
    #: CreditProbe itself.
    headline: str
    sections: list[Section] = field(default_factory=list)
    #: What it was built from, so a reader can check it. Never rendered into
    #: the answer body - it is provenance, not prose.
    sources: list[str] = field(default_factory=list)
    #: Section 11: one to three, contextual, never canned.
    follow_ups: list[str] = field(default_factory=list)
    band: str = MEDIUM
    #: Whether the question asked for the held-back detail. Kept separate from
    #: the band on purpose: the band is how LONG an answer may be, this is
    #: WHICH content it may contain. A long answer is not automatically a
    #: detailed one, and conflating them is how a catalogue question started
    #: returning the threshold table nobody asked for.
    deep: bool = False

    # -- composition ---------------------------------------------------------

    def shown(self) -> list[Section]:
        """The sections this question actually asked for."""
        if self.deep:
            return list(self.sections)
        return [s for s in self.sections if not s.detail]

    def held_back(self) -> list[Section]:
        return [] if self.deep else [s for s in self.sections if s.detail]

    def markdown(self) -> str:
        return _markdown(self.headline, self.shown())

    def text(self) -> str:
        """The answer as the product shows it.

        Markdown, not flattened prose. Every channel that renders a CreditProbe
        answer renders this string, so the structure has to be IN it rather
        than beside it - the previous version kept the sections in a parallel
        payload and handed the renderer a wall of text.
        """
        return self.markdown()

    def to_dict(self) -> dict[str, Any]:
        body = self.markdown()
        review = inspect(self, body)
        return {"topic": self.topic, "headline": self.headline,
                "sections": [s.to_dict() for s in self.shown()],
                "held_back": [s.key for s in self.held_back()],
                "sources": list(self.sources),
                "follow_ups": list(self.follow_ups),
                "band": self.band,
                "deep": self.deep,
                "word_count": word_count(body),
                "composition": review.to_dict(),
                "visualization": dict(NO_CHART),
                "answer": body,
                "markdown": body}


#: Every product answer declares this. Section 12: text flows are encouraged,
#: quantitative charts are not - a bar chart of feature counts is decoration
#: pretending to be analysis.
NO_CHART = {"kind": "none",
            "reason": "A product or methodology explanation has no "
                      "quantitative shape. This is text and structure."}


# ------------------------------------------------------------------ emission


def _table(table: dict[str, Any]) -> list[str]:
    columns = [str(c) for c in (table.get("columns") or [])]
    if not columns:
        return []
    out = ["| " + " | ".join(columns) + " |",
           "| " + " | ".join("---" for _ in columns) + " |"]
    for row in (table.get("rows") or []):
        cells = [str(c).replace("|", "\\|").replace("\n", " ") for c in row]
        cells += [""] * (len(columns) - len(cells))
        out.append("| " + " | ".join(cells[:len(columns)]) + " |")
    return out


def _markdown(headline: str, sections: list[Section]) -> str:
    """Sections to Markdown, with a blank line between every block."""
    blocks: list[str] = []
    if headline:
        blocks.append(headline.strip())
    for section in sections:
        if section.title:
            level = "#" * max(2, min(4, section.depth))
            blocks.append(f"{level} {section.title.strip()}")
        for paragraph in section.body:
            said = str(paragraph or "").strip()
            if said:
                blocks.append(said)
        if section.bullets:
            blocks.append("\n".join(f"- {str(b).strip()}"
                                    for b in section.bullets if str(b).strip()))
        if section.flow:
            # A blockquote of arrow-joined steps. Standard Markdown, so it
            # degrades to something readable anywhere, and the answer surface
            # renders it as a process flow.
            blocks.append("> " + FLOW_ARROW.join(
                str(step).strip() for step in section.flow if str(step).strip()))
        if section.table:
            rows = _table(section.table)
            if rows:
                blocks.append("\n".join(rows))
    return "\n\n".join(b for b in blocks if b.strip())


_MARKUP = re.compile(r"[#*`>|]|^\s*-\s", re.MULTILINE)


def word_count(markdown: str) -> int:
    """Words a reader reads, with the markup taken out."""
    plain = _MARKUP.sub(" ", markdown or "")
    plain = plain.replace(FLOW_ARROW.strip(), " ")
    return len([w for w in plain.split() if any(c.isalnum() for c in w)])


def blocks_of(markdown: str) -> list[str]:
    return [b for b in (markdown or "").split("\n\n") if b.strip()]


def paragraphs_of(markdown: str) -> list[str]:
    """Prose blocks only: not headings, bullets, flows or tables."""
    out = []
    for block in blocks_of(markdown):
        stripped = block.strip()
        if stripped.startswith(("#", "-", ">", "|")):
            continue
        out.append(stripped)
    return out


def headings_of(markdown: str) -> list[tuple[int, str]]:
    out = []
    for line in (markdown or "").splitlines():
        found = re.match(r"^(#{2,4})\s+(.*\S)\s*$", line)
        if found:
            out.append((len(found.group(1)), found.group(2)))
    return out


# ---------------------------------------------------------------- the gate
#
# Section 14. Eleven checks, run on the composed answer. Each one is a question
# a reviewer would ask, expressed as something that can fail.

#: Words that sell rather than explain. A credit officer reading "world-class"
#: stops believing the rest of the sentence.
_FLUFF = re.compile(
    r"\bworld[- ]class\b|\bcutting[- ]edge\b|\brevolutionar\w*\b"
    r"|\bbest[- ]in[- ]class\b|\bseamless\w*\b|\bunparalleled\b"
    r"|\bstate[- ]of[- ]the[- ]art\b|\bgame[- ]chang\w*\b|\bnext[- ]generation\b"
    r"|\bempower\w*\b|\bsupercharg\w*\b|\bturbo[- ]?charg\w*\b"
    r"|\bindustry[- ]leading\b|\bone[- ]stop\b|\bholistic\b|\bsynerg\w*\b",
    re.IGNORECASE)

#: Section 13. The left-hand side of every microcopy rule, so a regression back
#: to the developer phrasing fails rather than ships.
_AWKWARD = re.compile(
    r"\bbusiness rationale\b|\binterpretation output\b"
    r"|\brecommended downstream analytical objective\b"
    r"|\bthe following capabilities are available\b"
    r"|\bthe user\b|\bend[- ]user\b",
    re.IGNORECASE)

#: Implementation vocabulary. Nothing here is wrong; it is simply not what a
#: Chief Risk Officer asked to hear.
_INTERNAL = re.compile(
    r"\bdataclass\b|\bpayload\b|\bregistry\b|\bJSON\b|\bSQL\b|\bDuckDB\b"
    r"|\bPostgres\w*\b|\bAPI\b|\bendpoint\b|\bschema\b|\bregex\b"
    r"|\bbackend\b|\bfrontend\b|\bmiddleware\b|\bserialis\w*\b|\bserializ\w*\b"
    r"|\bprompt\b|\btoken\w*\b|\bmodel call\b|\bfunction call\b|\btool call\b"
    r"|\bnull\b|\bboolean\b|\bendpoint\b|\bcache\b|\bdataframe\b",
    re.IGNORECASE)


@dataclass(frozen=True)
class Check:
    name: str
    question: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "question": self.question,
                "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class Review:
    checks: tuple[Check, ...] = ()

    @property
    def ok(self) -> bool:
        return all(c.passed for c in self.checks)

    @property
    def failures(self) -> tuple[Check, ...]:
        return tuple(c for c in self.checks if not c.passed)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok,
                "checks": [c.to_dict() for c in self.checks],
                "failed": [c.name for c in self.failures]}


def inspect(answer: Answer, markdown: str = "") -> Review:
    """The eleven-point composition gate."""
    body = markdown or answer.markdown()
    words = word_count(body)
    paragraphs = paragraphs_of(body)
    headings = headings_of(body)
    blocks = blocks_of(body)
    _floor, ceiling = BANDS.get(answer.band, BANDS[MEDIUM])
    checks: list[Check] = []

    # 1. Did it answer the actual question first?
    opening = paragraphs[0] if paragraphs else ""
    checks.append(Check(
        "answers_first", "Did it answer the actual question first?",
        bool(answer.headline.strip()) and bool(opening)
        and not body.lstrip().startswith("#"),
        "" if opening else "the answer opens with a heading, not an answer"))

    # 2. Did it retrieve only relevant capabilities?
    off_band = [] if answer.deep else [s.key for s in answer.shown()
                                       if s.detail]
    checks.append(Check(
        "relevant_only", "Did it retrieve only relevant capabilities?",
        not off_band,
        f"detail held for a deeper question was included: {off_band}"
        if off_band else ""))

    # 3. Is anything included that the user did not need yet?
    over = words > ceiling
    unoffered = bool(answer.held_back()) and not answer.follow_ups
    checks.append(Check(
        "nothing_premature",
        "Is anything included that was not needed yet?",
        not over and not unoffered,
        (f"{words} words against a {answer.band} ceiling of {ceiling}"
         if over else
         "content was held back but never offered" if unoffered else "")))

    # 4. Is the answer structured?
    structured = len(headings) >= 1 or words <= 120
    checks.append(Check(
        "structured", "Is the answer structured?", structured,
        "" if structured else f"{words} words with no headings"))

    # 5. Is the opening concise?
    opening_words = len(opening.split())
    checks.append(Check(
        "concise_opening", "Is the opening concise?",
        opening_words <= MAX_OPENING_WORDS,
        "" if opening_words <= MAX_OPENING_WORDS
        else f"the opening runs to {opening_words} words"))

    # 6. Are paragraphs short?
    long_ones = [p[:60] for p in paragraphs
                 if len(p.split()) > MAX_PARAGRAPH_WORDS]
    checks.append(Check(
        "short_paragraphs", "Are paragraphs short?", not long_ones,
        f"{len(long_ones)} paragraph(s) over {MAX_PARAGRAPH_WORDS} words: "
        f"{long_ones[:2]}" if long_ones else ""))

    # 7. Are headings useful?
    bad_headings = [h for _, h in headings
                    if len(h.split()) > MAX_HEADING_WORDS or h.isupper()]
    duplicated = len({h for _, h in headings}) != len(headings)
    checks.append(Check(
        "useful_headings", "Are headings useful?",
        not bad_headings and not duplicated,
        (f"unhelpful: {bad_headings}" if bad_headings else "")
        or ("a heading is repeated" if duplicated else "")))

    # 8. Is there enough whitespace?
    # A bullet list is many blocks visually even though it is one block of
    # Markdown, so what matters is the longest LINE, not the longest block.
    dense = [b[:60] for b in blocks
             if not b.startswith("|")
             and max((len(line) for line in b.splitlines()), default=0)
             > MAX_BLOCK_CHARS]
    enough = not dense and (len(blocks) >= 3 or words <= 120)
    checks.append(Check(
        "whitespace", "Is there enough whitespace?", enough,
        f"unbroken block(s) over {MAX_BLOCK_CHARS} characters: {dense[:2]}"
        if dense else ("" if enough else "the answer is one or two blocks")))

    # 9. Is the tone professional but conversational?
    fluff = sorted({m.group(0).lower() for m in _FLUFF.finditer(body)})
    awkward = sorted({m.group(0).lower() for m in _AWKWARD.finditer(body)})
    checks.append(Check(
        "tone", "Is the tone professional but conversational?",
        not fluff and not awkward,
        (f"marketing language: {fluff}" if fluff else "")
        + (f" awkward phrasing: {awkward}" if awkward else "")))

    # 10. Are follow-ups contextual?
    ups = [f.strip() for f in answer.follow_ups if f.strip()]
    good_ups = len(ups) <= 3 and len(set(ups)) == len(ups)
    checks.append(Check(
        "nudges", "Are follow-ups contextual?", good_ups,
        "" if good_ups else f"{len(ups)} follow-up(s), or a repeat"))

    # 11. Is any technical or internal terminology leaking?
    leaked = sorted({m.group(0).lower() for m in _INTERNAL.finditer(body)})
    checks.append(Check(
        "no_internals", "Is any internal terminology leaking?", not leaked,
        f"internal vocabulary: {leaked}" if leaked else ""))

    return Review(checks=tuple(checks))


def compose(answer: Answer) -> Answer:
    """Emit, check, and recompose an answer that overran its band.

    Section 14: "If the answer is effectively an unbroken knowledge dump,
    reject/recompose it." Recomposing means dropping what was marked droppable,
    from the end, until the answer fits - never truncating mid-sentence, and
    never dropping something the answer needs to be true.

    An answer that still fails afterwards is returned WITH its failures. The
    gate reports; it does not paper over.
    """
    review = inspect(answer)
    if review.ok:
        return answer

    _floor, ceiling = BANDS.get(answer.band, BANDS[MEDIUM])
    while word_count(answer.markdown()) > ceiling:
        droppable = [i for i, s in enumerate(answer.shown()) if s.optional]
        if not droppable:
            break
        drop = answer.shown()[droppable[-1]]
        answer.sections = [s for s in answer.sections if s is not drop]
    return answer


__all__ = [
    "Answer", "BANDS", "Check", "DETAILED", "FLOW_ARROW", "MEDIUM",
    "MAX_BLOCK_CHARS", "MAX_HEADING_WORDS", "MAX_OPENING_WORDS",
    "MAX_PARAGRAPH_WORDS", "NO_CHART", "Review", "SHORT", "Section",
    "blocks_of", "compose", "headings_of", "inspect", "paragraphs_of",
    "word_count",
]
