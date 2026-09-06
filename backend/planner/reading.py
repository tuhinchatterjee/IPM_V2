"""Turning what somebody said into things the plan actually contains.

This is the half of the language layer that has no opinions about grammar. It
answers four questions, and it answers them the same way whether the sentence
was read by the rule reader or proposed by a model:

    "1 October"            → which date is that?
    "Sameer"               → which person is that?
    "data reconciliation"  → which task is that?
    "two days"             → what number is that?

Keeping it separate matters for one reason above all. A model may propose a
command, but it may never propose an ID. It says the words the person said,
and the resolution from those words to a user id or an item code happens
HERE, against the plan the person can see and the directory they can see. A
model that returned `owner_id: 41` would be a model deciding who is on a
project, and no amount of prompt would make that safe.

Resolution is deliberately three-tier, because "no match" and "several
matches" are different problems with different answers:

    RESOLVED    exactly one thing fits, and it is used;
    AMBIGUOUS   several fit, and the person is asked which — with buttons,
                because typing the same sentence again more carefully is not
                a conversation;
    UNKNOWN     nothing fits, and the Copilot says so rather than inventing.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

READING_VERSION = "1.0.0"

RESOLVED = "RESOLVED"
AMBIGUOUS = "AMBIGUOUS"
UNKNOWN = "UNKNOWN"


# ------------------------------------------------------------------ numbers


_WORD_NUMBERS: dict[str, int] = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11,
    "twelve": 12, "fourteen": 14, "fifteen": 15, "twenty": 20, "thirty": 30,
    "a": 1, "an": 1, "the": 1, "first": 1, "second": 2, "third": 3,
    "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8,
    "ninth": 9, "tenth": 10,
}


def number(text: Any) -> int | None:
    """`3`, `three` and `third` are all three. Anything else is nothing."""
    word = str(text or "").strip().lower().rstrip(".")
    if not word:
        return None
    if word.isdigit():
        return int(word)
    stripped = re.sub(r"(st|nd|rd|th)$", "", word)
    if stripped.isdigit():
        return int(stripped)
    return _WORD_NUMBERS.get(word)


# -------------------------------------------------------------------- dates


_MONTHS: dict[str, int] = {}
for _index, _name in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"], start=1):
    _MONTHS[_name] = _index
    _MONTHS[_name[:3]] = _index
_MONTHS["sept"] = 9

_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
             "friday": 4, "saturday": 5, "sunday": 6}

#: `1 October`, `1st Oct 2026`, `October 1`, `2026-10-01`, `01/10/2026`.
_DAY_MONTH = re.compile(
    r"\b(?P<day>\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?"
    r"(?P<month>[a-z]{3,9})\.?(?:\s+(?P<year>\d{4}))?\b", re.IGNORECASE)
_MONTH_DAY = re.compile(
    r"\b(?P<month>[a-z]{3,9})\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?"
    r"(?:,?\s+(?P<year>\d{4}))?\b", re.IGNORECASE)
_ISO = re.compile(r"\b(?P<year>\d{4})-(?P<month>\d{1,2})-(?P<day>\d{1,2})\b")
#: Day first. This product is used in the UK and the Gulf, where 01/10 is the
#: first of October and reading it as the tenth of January would move a
#: deadline by nine months without anybody noticing.
_SLASHED = re.compile(
    r"\b(?P<day>\d{1,2})[/.](?P<month>\d{1,2})[/.](?P<year>\d{2,4})\b")
_RELATIVE = re.compile(
    r"\b(?:in\s+(?P<count>\w+)\s+(?P<unit>day|days|week|weeks|month|months)"
    r"|(?P<next>next|this)\s+(?P<weekday>monday|tuesday|wednesday|thursday"
    r"|friday|saturday|sunday)"
    r"|(?P<word>today|tomorrow))\b", re.IGNORECASE)


@dataclass
class Found:
    """Something recognised in a sentence, and where it was."""

    value: Any
    start: int
    end: int
    text: str = ""


def _safe(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _year_for(month: int, day: int, today: date, window: tuple[
        date | None, date | None] = (None, None)) -> int:
    """Which year a date without one means.

    Inside the project's own window when there is one, because a plan running
    to June 2027 that says "1 March" means the March in the plan. Otherwise
    the next occurrence, since a plan is about what has not happened yet.
    """
    start, end = window
    if start and end:
        for year in range(start.year, end.year + 1):
            found = _safe(year, month, day)
            if found and start <= found <= end:
                return year
    guess = _safe(today.year, month, day)
    if guess and guess >= today:
        return today.year
    return today.year + 1


def find_date(text: str, *, today: date,
              window: tuple[date | None, date | None] = (None, None),
              ) -> Found | None:
    """The first date in this text, however it was written."""
    body = str(text or "")

    match = _ISO.search(body)
    if match:
        found = _safe(int(match["year"]), int(match["month"]),
                      int(match["day"]))
        if found:
            return Found(found, match.start(), match.end(), match.group(0))

    match = _SLASHED.search(body)
    if match:
        year = int(match["year"])
        year = year + 2000 if year < 100 else year
        found = _safe(year, int(match["month"]), int(match["day"]))
        if found:
            return Found(found, match.start(), match.end(), match.group(0))

    for pattern in (_DAY_MONTH, _MONTH_DAY):
        for match in pattern.finditer(body):
            month = _MONTHS.get(match["month"].lower().rstrip("."))
            if month is None:
                continue
            day = int(match["day"])
            year = int(match["year"]) if match["year"] else _year_for(
                month, day, today, window)
            found = _safe(year, month, day)
            if found:
                return Found(found, match.start(), match.end(),
                             match.group(0))

    match = _RELATIVE.search(body)
    if match:
        found = _relative(match, today)
        if found:
            return Found(found, match.start(), match.end(), match.group(0))
    return None


def _relative(match: re.Match[str], today: date) -> date | None:
    if match["word"]:
        return today if match["word"].lower() == "today" else today + timedelta(days=1)
    if match["weekday"]:
        wanted = _WEEKDAYS[match["weekday"].lower()]
        ahead = (wanted - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    count = number(match["count"])
    if count is None:
        return None
    unit = (match["unit"] or "").lower()
    if unit.startswith("day"):
        return today + timedelta(days=count)
    if unit.startswith("week"):
        return today + timedelta(weeks=count)
    return today + timedelta(days=30 * count)


# ------------------------------------------------------------------ matching


def normalise(text: Any) -> str:
    """Lowercase, unaccented, punctuation-free, single-spaced.

    So "Data Foundation", "data foundation" and "the Data-Foundation" are one
    thing. Comparison is on this form throughout; what gets shown back is
    always the original.
    """
    body = unicodedata.normalize("NFKD", str(text or ""))
    body = "".join(ch for ch in body if not unicodedata.combining(ch))
    body = re.sub(r"[^A-Za-z0-9]+", " ", body).strip().lower()
    return re.sub(r"\s+", " ", body)


#: Words that carry no identity. Stripped before comparing, so "the data
#: extraction task" finds "Data Extraction".
_NOISE = {"the", "a", "an", "of", "for", "and", "to", "task", "tasks",
          "milestone", "milestones", "project", "step", "stage", "item",
          "this", "that", "it", "please", "phase"}


def _tokens(text: Any) -> list[str]:
    return [word for word in normalise(text).split() if word not in _NOISE]


@dataclass
class Match:
    """One candidate, and how sure we are it is the one meant."""

    key: str
    label: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass
class Resolution:
    """The answer to "which one did they mean?"."""

    state: str
    match: Match | None = None
    candidates: list[Match] = field(default_factory=list)
    asked: str = ""

    @property
    def ok(self) -> bool:
        return self.state == RESOLVED

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "key": self.match.key if self.match else "",
            "label": self.match.label if self.match else "",
            "candidates": [{"key": c.key, "label": c.label}
                           for c in self.candidates],
        }


def _score(said: str, candidate: str) -> float:
    """How well one phrase names another.

    Exact beats prefix beats containment beats overlapping words, and a
    single overlapping word is never enough on its own — "data" must not
    silently resolve to whichever of Data Extraction and Data Reconciliation
    happens to come first.
    """
    left, right = normalise(said), normalise(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    said_words, candidate_words = _tokens(said), _tokens(candidate)
    if said_words and said_words == candidate_words:
        return 0.98
    if right.startswith(left) or left.startswith(right):
        return 0.9
    if left in right or right in left:
        return 0.85
    if not said_words or not candidate_words:
        return 0.0
    shared = set(said_words) & set(candidate_words)
    if len(shared) < 2 and len(said_words) > 1:
        return 0.0
    if not shared:
        return 0.0
    return 0.5 + 0.3 * len(shared) / max(len(said_words), len(candidate_words))


#: Below this, a candidate is not a candidate. Above it but close to a rival,
#: the person is asked.
_FLOOR = 0.55
#: Two candidates this close together are a question, not a decision.
_TIE = 0.08


def choose(said: str, candidates: list[Match], *, what: str) -> Resolution:
    ranked = sorted((c for c in candidates if c.score >= _FLOOR),
                    key=lambda c: -c.score)
    if not ranked:
        return Resolution(UNKNOWN, asked=what)
    if len(ranked) == 1 or ranked[0].score - ranked[1].score > _TIE:
        return Resolution(RESOLVED, match=ranked[0], candidates=ranked[:4])
    return Resolution(AMBIGUOUS, candidates=ranked[:4], asked=what)


# ------------------------------------------------------------------ context


@dataclass
class Directory:
    """The colleagues who can be named, as the person would name them.

    Matched on the full name, on either part of it, and on the username, so
    "Sameer", "Sameer Haddad" and "s.haddad" all find one person — and two
    Sameers produce a question rather than a coin toss.
    """

    people: list[dict[str, Any]] = field(default_factory=list)

    def find(self, said: str) -> Resolution:
        wanted = normalise(said)
        if not wanted:
            return Resolution(UNKNOWN, asked="person")
        found: list[Match] = []
        for person in self.people:
            name = str(person.get("name") or "")
            username = str(person.get("username") or "")
            best = max(_score(said, name), _score(said, username))
            for part in name.split():
                if normalise(part) == wanted:
                    best = max(best, 0.95)
            if best >= _FLOOR:
                found.append(Match(str(person["user_id"]), name or username,
                                   best, {"user_id": int(person["user_id"])}))
        return choose(said, found, what="person")

    def name_of(self, user_id: Any) -> str:
        for person in self.people:
            if int(person.get("user_id", 0)) == int(user_id or 0):
                return str(person.get("name") or person.get("username") or "")
        return ""

    @property
    def looks_like_names(self) -> set[str]:
        """Every single word that could begin somebody's name.

        Used to stop the rule reader treating "Sameer owns X" as a sentence
        about a milestone called Sameer.
        """
        words: set[str] = set()
        for person in self.people:
            for part in str(person.get("name") or "").split():
                words.add(normalise(part))
            words.add(normalise(person.get("username")))
        return {word for word in words if word}


@dataclass
class Lexicon:
    """Everything in the plan that can be named, by code or by name."""

    rows: list[dict[str, Any]] = field(default_factory=list)

    def find(self, said: str, *, kind: str = "") -> Resolution:
        wanted = normalise(said)
        if not wanted:
            return Resolution(UNKNOWN, asked="item")
        found: list[Match] = []
        for row in self.rows:
            if kind and row.get("kind") != kind:
                continue
            code = str(row.get("code") or "")
            name = str(row.get("name") or "")
            # A code said exactly is never ambiguous: it is an identifier.
            if normalise(code) == wanted:
                return Resolution(RESOLVED,
                                  match=Match(code, name or code, 1.0, row))
            best = _score(said, name)
            if best >= _FLOOR:
                found.append(Match(code, f"{code} — {name}", best, row))
        return choose(said, found, what="item")

    def all(self, kind: str = "") -> list[dict[str, Any]]:
        return [row for row in self.rows
                if not kind or row.get("kind") == kind]

    def matching(self, said: str, *, kind: str = "") -> list[dict[str, Any]]:
        """Everything this phrase names, when it names more than one thing.

        For "escalate Validation tasks to Ananya", where the person means all
        of them rather than one of them, and picking the best single match
        would silently do a fraction of what they asked.

        Compared on words rather than on the raw string, so "Validation
        tasks" finds "Validation Report" and "Validation Sign-off" — the
        noise words that make it a plural English phrase are not part of any
        of their names.
        """
        wanted = set(_tokens(said))
        if not wanted:
            return []
        out = []
        for row in self.rows:
            if kind and row.get("kind") != kind:
                continue
            if normalise(row.get("code")) == normalise(said):
                return [row]
            if wanted and wanted <= set(_tokens(row.get("name"))):
                out.append(row)
        return out


__all__ = [
    "AMBIGUOUS", "Directory", "Found", "Lexicon", "Match", "READING_VERSION",
    "RESOLVED", "Resolution", "UNKNOWN", "choose", "find_date", "normalise",
    "number",
]
