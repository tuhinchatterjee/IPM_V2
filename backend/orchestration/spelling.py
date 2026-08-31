"""
Correcting a mistyped question against the governed vocabulary, before reading.

The failure this prevents
-------------------------
    "Show me the five largest Real Estste customers by EAD."

One adjacent-key slip, and a question CreditProbe answers perfectly well became
a clarification. The reader matches concepts, dimension values and dataset names
by pattern, so a single wrong letter in a content word does not degrade the
reading — it removes it. The user then gets a menu of governed concepts in
response to a question that named one.

Why deterministic
-----------------
A model would fix these, and a model is not always configured, is slower, and
introduces a second thing that can be wrong. The bank's own vocabulary is on
disk: every concept, dataset, field, dimension value and method name. A word
that is one keystroke from exactly one of them, and from nothing else, is a
typo. That is a lookup, not a judgement.

The bar
-------
Deliberately conservative, because a wrong correction is far worse than none —
it answers a different question confidently.

* the word has to be long enough to be worth correcting (short words are too
  close to each other for distance 1 to mean anything: `ecl` and `eal`);
* it has to be unknown to the governed vocabulary, so nothing that already
  means something is ever rewritten;
* it has to be one edit from EXACTLY ONE governed word — two candidates means
  CreditProbe cannot tell which was meant, and it asks instead;
* the first letter has to match, which is the letter people mistype least and
  the cheapest way to stop `sector`/`vector`-class swaps.

Every correction it makes is recorded and shown to the user, so an answer to a
question they did not quite type says so.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Below this length, one edit is too much of the word for the match to mean
#: anything.
MIN_LENGTH = 5

#: How many corrections one question may receive. A sentence needing four is
#: not a mistyped question, it is a question about something else, and quietly
#: rewriting it into a governed one is the failure this module must not cause.
MAX_CORRECTIONS = 2

#: Openings that carry no meaning and can leave the reader parsing "Please what
#: fields are in…". Stripped before reading, never from what is displayed.
_PLEASANTRY = re.compile(
    r"^\s*(?:hi|hello|hey)?[\s,]*"
    r"(?:(?:can|could|would)\s+you\s+(?:please\s+)?|please\s+|"
    r"i(?:'d| would)\s+like\s+to\s+know\s+|i\s+need\s+to\s+know\s+|"
    r"quick\s+one\s*[—–-]\s*)+",
    re.I)

#: Trailing softeners, for the same reason.
_TRAILING = re.compile(
    r"[\s,—–-]*(?:please|if\s+you\s+can|thanks?(?:\s+you)?)\s*[.?!]*\s*$", re.I)

_WORD = re.compile(r"[A-Za-z][A-Za-z'-]*")


@dataclass(frozen=True)
class Correction:
    """A question as CreditProbe read it, and what it changed to read it."""

    text: str
    original: str
    changes: tuple[tuple[str, str], ...] = ()
    trimmed: bool = False

    @property
    def changed(self) -> bool:
        return bool(self.changes) or self.trimmed

    def sentence(self) -> str:
        """What to tell the user, or nothing when nothing was rewritten."""
        if not self.changes:
            return ""
        pairs = ", ".join(f"{was!r} as {now!r}" for was, now in self.changes)
        return f"CreditProbe read {pairs}."

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "original": self.original,
                "changes": [list(c) for c in self.changes],
                "trimmed": self.trimmed}


@dataclass
class _Lexicon:
    """The governed words a typo can be corrected to."""

    words: set[str] = field(default_factory=set)
    #: Indexed by first letter and length, so a correction is a lookup over a
    #: handful of candidates rather than a scan of the whole vocabulary.
    buckets: dict[tuple[str, int], list[str]] = field(default_factory=dict)

    def index(self) -> None:
        for word in self.words:
            if len(word) < MIN_LENGTH - 1:
                continue
            for length in (len(word) - 1, len(word), len(word) + 1):
                self.buckets.setdefault((word[0], length), []).append(word)

    def candidates(self, token: str) -> list[str]:
        return self.buckets.get((token[0], len(token)), [])


#: Regex metacharacters, stripped so a pattern can be read for its words.
_META = re.compile(r"\\b|\\s|\\d|\\w|[\\\\^$.|?*+()\[\]{}]")


def _reader_words() -> set[str]:
    """Every word the downstream readers match on, so none is ever rewritten.

    This is the correction's most dangerous failure mode, and it happened on
    the first run: `least` is one substitution from `last`, `last` is in the
    structural vocabulary and `least` was not, so "covenant headroom of at
    least 25%" was read as "at last 25%". The threshold vanished and the answer
    came back as a ranking of the ten highest — a different population under
    the heading of the one that was asked for.

    A word the threshold reader, the period reader or the referent reader
    depends on is therefore part of the vocabulary by definition. Harvested
    from the patterns themselves rather than listed here, so a pattern gained
    later is protected without anyone remembering to protect it.
    """
    from backend.orchestration import periods as pd
    from backend.orchestration import referents as rf
    from backend.orchestration import semantics as sm

    sources: list[Any] = []
    for module, names in (
            (sm, ("_THRESHOLD_OPS", "DIRECTIONS")),
            (pd, ("_RELATIVE_SPANS",)),
            (rf, ("_POPULATION", "_MODIFY", "_CONTINUE", "_ENRICH",
                  "_PRESENTATION", "_INCOMPLETE", "_WIDEN", "_SAME_PERIOD")),
    ):
        for name in names:
            value = getattr(module, name, None)
            if value:
                sources.extend(value)

    out: set[str] = set()
    for item in sources:
        raw = item if isinstance(item, str) else (
            item[0] if isinstance(item, (tuple, list)) and item
            and isinstance(item[0], str) else "")
        if not raw:
            continue
        for token in re.findall(r"[a-z]{3,}", _META.sub(" ", raw).lower()):
            out.add(token)
    return out


def _lexicon() -> _Lexicon:
    """The governed vocabulary, from the same place the coverage check reads it.

    Shared deliberately: a word CreditProbe would recognise in a question is
    exactly the set a typo should be corrected to, and two lists that drift
    apart would produce a correction to a word the reader does not know.
    """
    from backend.orchestration import coverage as cov

    # The governed vocabulary AND the ordinary words a question is built from.
    # "What firlds are in the ratings data?" is a typo for `fields`, which is
    # not a concept or a column — it is the word the whole question turns on,
    # and a lexicon of governed nouns alone cannot repair it.
    words = set(cov._universe().words) | set(cov._STRUCTURAL)
    # Plurals too. The structural list is written in the singular where a
    # singular reads naturally, and "which of them are financial ratoos?" is a
    # typo for the plural.
    words |= {f"{w}s" for w in cov._STRUCTURAL if not w.endswith("s")}
    words |= _reader_words()
    lexicon = _Lexicon(words={w for w in words
                              if len(w) >= MIN_LENGTH - 1 and w.isalpha()})
    lexicon.index()
    return lexicon


def _within_one(token: str, word: str) -> bool:
    """Whether one insertion, deletion or substitution turns one into the other."""
    if token == word:
        return True
    long, short = (token, word) if len(token) >= len(word) else (word, token)
    if len(long) - len(short) > 1:
        return False

    if len(long) == len(short):
        differences = sum(1 for a, b in zip(long, short, strict=True) if a != b)
        return differences == 1

    # One is the other with a letter inserted. Walk both, allowing one skip.
    i = j = 0
    skipped = False
    while i < len(long) and j < len(short):
        if long[i] == short[j]:
            i, j = i + 1, j + 1
            continue
        if skipped:
            return False
        skipped, i = True, i + 1
    return True


#: Ordinary English that the governed vocabulary happens not to contain, and
#: that sits one keystroke from a word it does.
#:
#: The bar above says a correction requires a word "unknown to the governed
#: vocabulary, so nothing that already means something is ever rewritten".
#: That is the right rule and the module could only half apply it: it knows
#: the bank's vocabulary and not English, so a correctly spelled English word
#: absent from the catalogue looked exactly like a typo.
#:
#: "Who is beginning to run short of cash?" became "run SORT of cash" —
#: `sort` is a governed word, `short` is not, and they are one letter apart.
#: The question then described nothing the catalogue held and was refused as
#: out of scope. A corrector that damages a correctly typed question is worse
#: than no corrector, because the user cannot see why the sentence they typed
#: was not understood.
#:
#: Curated rather than a dictionary: a dictionary would be a dependency and a
#: download, and the words that actually collide with a credit vocabulary are
#: few and nameable. Add to it when a real question is damaged.
_ORDINARY: frozenset[str] = frozenset("""
short shorter shortage cash trouble troubled names weak weaker weakening
worse worst worry worried risky heavy heavily light tight tighter loose
begin beginning start starting stop stopping keep keeping getting going
under over above below behind ahead across around within without
running runs ruined ready steady rising rose falling fallen
strong stronger strongest weakest bigger smaller larger looks look
vulnerable exposed stretched strained squeeze squeezed crunch
""".split())


def _correct(token: str, lexicon: _Lexicon) -> str:
    """The single governed word this is one keystroke from, or "" for none."""
    lowered = token.lower()
    if len(lowered) < MIN_LENGTH or lowered in lexicon.words:
        return ""
    if lowered in _ORDINARY:
        return ""
    matches = {w for w in lexicon.candidates(lowered) if _within_one(lowered, w)}
    return matches.pop() if len(matches) == 1 else ""


def normalise(question: str, *, lexicon: _Lexicon | None = None) -> Correction:
    """The question as CreditProbe should read it. Never raises.

    A failure here has to leave the question alone rather than lose it: the
    worst outcome of no correction is the clarification the user would have got
    anyway, and the worst outcome of an exception is no answer at all.
    """
    original = str(question or "")
    try:
        return _normalise(original, lexicon)
    except Exception as e:  # noqa: BLE001
        logger.warning("A question could not be spell-checked: %s", e)
        return Correction(text=original, original=original)


def _normalise(original: str, lexicon: _Lexicon | None) -> Correction:
    text = _TRAILING.sub("", _PLEASANTRY.sub("", original)).strip()
    if not text:
        text = original.strip()
    trimmed = text != original.strip()

    from backend.orchestration import coverage as cov

    words = [w for w in _WORD.findall(text)
             if len(w) >= MIN_LENGTH and not cov._structural(w.lower())]
    if not words:
        return Correction(text=text, original=original, trimmed=trimmed)

    book = lexicon if lexicon is not None else _lexicon()
    if not book.words:
        return Correction(text=text, original=original, trimmed=trimmed)

    changes: list[tuple[str, str]] = []
    for word in words:
        fixed = _correct(word, book)
        if not fixed or fixed == word.lower():
            continue
        changes.append((word, fixed))
        if len(changes) > MAX_CORRECTIONS:
            # More slips than a mistyped sentence has. Read it as written and
            # let the ordinary path ask.
            return Correction(text=text, original=original, trimmed=trimmed)

    # Put the correction back in the case the user typed it in. `Real Estste`
    # becoming `Real estate` reads as a different thing to an entity matcher
    # that treats a capital as the start of a name.
    for was, now in changes:
        cased = now.capitalize() if was[:1].isupper() else now
        text = re.sub(rf"\b{re.escape(was)}\b", cased, text, count=1)

    return Correction(text=text, original=original,
                      changes=tuple(changes), trimmed=trimmed)


__all__ = ["MAX_CORRECTIONS", "MIN_LENGTH", "Correction", "normalise"]
