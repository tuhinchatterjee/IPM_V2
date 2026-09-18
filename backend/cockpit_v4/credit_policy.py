"""
The bank's credit policy: a synopsis always, the clauses on request.

Why not attach the policy
-------------------------
The pack is thirty clauses across two books, about 23KB of JSON. Attaching
it to every question would put the whole rule book in front of a request
about Stage 2 exposure -- the same mistake `product_knowledge` exists to
avoid, in a different costume. So the same two layers:

  * a compact SYNOPSIS in the analytical context -- which book's policy is
    in force, its sections, and the handful of thresholds a portfolio
    question actually collides with (the concentration limits, the DBR
    caps, the SICR triggers, the write-off points). Enough to notice that a
    number has crossed a line.

  * `inspect_credit_policy`, which returns the clauses a specific question
    needs, in full, with their thresholds and the levers they offer.

THE BOOKS DO NOT CROSS. A Retail thread never receives a Corporate clause
and a Corporate thread never receives a Retail one, because a policy
recommendation quoting the wrong book's rule is worse than no
recommendation: it is a governance answer that sounds right.

What this is for
----------------
A finding is not an action. "Credit Card - Gold held by non-salaried
customers is entering arrears at 20-29 days" is a fact about the book; what
a credit committee needs next is which rule allowed it and what changing
that rule would do. That step is only safe if the rule is QUOTED rather
than remembered, which is why `recommendation` below refuses a policy
action that cites no clause -- the same discipline as a numeric claim with
no evidence behind it.

CreditProbe retrieves. The analyst decides. Nothing here writes a
recommendation or ranks one clause above another.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PACK_PATH = Path(__file__).resolve().parent / "credit_policy.json"

#: The most clauses one retrieval may return. A question that matches more
#: than this is a question that has not been narrowed, and returning forty
#: clauses is attaching the pack by another route.
MAX_CLAUSES = 8

#: A clause id as the pack writes it: `RP-1.1`, `CP-4.2`.
CLAUSE_ID = re.compile(r"\b([RC]P)[-\s]?(\d+)\.(\d+)\b", re.IGNORECASE)

#: A section id: `RP-1`, `CP-4`.
SECTION_ID = re.compile(r"\b([RC]P)[-\s]?(\d+)\b(?!\.)", re.IGNORECASE)


class UnknownBook(ValueError):
    """A policy book that does not exist. Named, never coerced."""


@lru_cache(maxsize=1)
def pack() -> dict[str, Any]:
    return json.loads(PACK_PATH.read_text(encoding="utf-8"))


def version() -> str:
    return str(pack().get("pack_version", "unknown"))


def _book(book_id: str) -> dict[str, Any]:
    books = pack()["books"]
    if book_id not in books:
        raise UnknownBook(
            f"{book_id!r} has no credit policy in this pack. The books are "
            f"{', '.join(sorted(books))}.")
    return books[book_id]


def clauses(book_id: str) -> list[dict[str, Any]]:
    """Every clause of one book, flattened, each carrying its section."""
    out: list[dict[str, Any]] = []
    for section in _book(book_id)["sections"]:
        for clause in section["clauses"]:
            out.append({**clause, "section": section["section"],
                        "section_title": section["title"],
                        "book_id": book_id})
    return out


def clause(book_id: str, clause_id: str) -> dict[str, Any] | None:
    wanted = clause_id.strip().upper().replace(" ", "-")
    return next((c for c in clauses(book_id)
                 if c["clause"].upper() == wanted), None)


# ---- the always-present synopsis ---------------------------------------

#: The clauses a PORTFOLIO question runs into, per book. Deliberately short:
#: this is what makes the analyst notice that a number has crossed a line,
#: not what lets it write the policy change.
_HEADLINE: dict[str, tuple[str, ...]] = {
    "retail": ("RP-1.1", "RP-2.2", "RP-4.1", "RP-5.1"),
    "corporate": ("CP-1.1", "CP-1.2", "CP-2.1", "CP-3.1"),
}


def synopsis(book_id: str) -> dict[str, Any]:
    """The compact policy facts carried on an analytical turn.

    Substantive enough to recognise a breach, small enough to carry: the
    sections by name, and the four clauses a portfolio number is most
    likely to collide with, with their thresholds.
    """
    book = _book(book_id)
    by_id = {c["clause"]: c for c in clauses(book_id)}
    return {
        "policy": book["title"],
        "pack_version": version(),
        "book": book_id,
        "approved_by": book["approved_by"],
        "next_review": book["next_review"],
        "not_client_data": True,
        "sections": [f"{s['section']} {s['title']}"
                     for s in book["sections"]],
        "thresholds_a_portfolio_number_meets": [
            {"clause": cid, "title": by_id[cid]["title"],
             "rule": by_id[cid]["rule"],
             **({"thresholds": by_id[cid]["thresholds"]}
                if by_id[cid].get("thresholds") else {})}
            for cid in _HEADLINE.get(book_id, ()) if cid in by_id],
        "more_detail": (
            "Call inspect_credit_policy with a clause id, a section id or a "
            "topic for the clauses in full, with their thresholds and the "
            "levers each one offers."),
        "citation_rule": (
            "A policy action names the clause it changes, quotes the rule "
            "in force, and states the proposed change. A recommendation "
            "citing no clause is not publishable."),
    }


# ---- retrieval ----------------------------------------------------------

#: Words that point at a section. Deterministic and inspectable, the same
#: shape `product_knowledge` uses, and extended when the pack gains a
#: section rather than guessed at by a model.
_KEYWORDS: dict[str, tuple[str, ...]] = {
    "RP-1": ("dbr", "debt burden", "affordability", "income", "salary "
             "transfer", "salary", "employment"),
    "RP-2": ("limit", "cut-off", "cutoff", "score", "tenor", "ltv", "loan to "
             "value", "override", "card limit", "sub-product"),
    "RP-3": ("new product", "pilot", "launch", "bnpl", "buy now", "channel",
             "partner", "digital", "vintage", "origination"),
    "RP-4": ("collection", "collections", "arrears", "restructure",
             "forbearance", "deferral", "ramadan", "write-off", "write off",
             "bucket", "dpd", "days past due", "delinquen"),
    "RP-5": ("stage", "sicr", "staging", "provision", "ifrs", "default",
             "cure"),
    "CP-1": ("concentration", "single obligor", "group limit", "connected",
             "sector limit", "exposure limit"),
    "CP-2": ("covenant", "dscr", "debt service", "leverage", "interest "
             "cover", "breach", "waiver"),
    "CP-3": ("watchlist", "watch list", "rating", "notch", "downgrade",
             "early warning", "stage", "sicr", "default"),
    "CP-4": ("collateral", "security", "haircut", "ltv", "loan to value",
             "revaluation", "valuation"),
    "CP-5": ("new product", "pilot", "supply chain", "scf", "receivables "
             "finance", "programme"),
}


def sections_for(book_id: str, question: str) -> list[str]:
    """Which sections of THIS book's policy the question names."""
    text = (question or "").lower()
    prefix = "RP" if book_id == "retail" else "CP"
    return [section for section, words in _KEYWORDS.items()
            if section.startswith(prefix)
            and any(word in text for word in words)]


def named_clauses(question: str) -> list[str]:
    """Clause ids written out in the question, normalised."""
    return [f"{m.group(1).upper()}-{m.group(2)}.{m.group(3)}"
            for m in CLAUSE_ID.finditer(question or "")]


def named_sections(question: str) -> list[str]:
    return [f"{m.group(1).upper()}-{m.group(2)}"
            for m in SECTION_ID.finditer(question or "")]


def retrieve(book_id: str, *, question: str = "",
             clause_ids: tuple[str, ...] = (),
             topic: str = "") -> dict[str, Any]:
    """The clauses this question needs, in full, and nothing else.

    Three ways in, in order of precision: an explicit clause id, a section
    id, and finally a keyword match over the question. Whichever is used,
    the result is bounded at `MAX_CLAUSES` -- an unbounded retrieval is the
    pack by another name.
    """
    book = _book(book_id)
    everything = clauses(book_id)
    wanted: list[dict[str, Any]] = []
    how = ""

    asked = [c.upper().replace(" ", "-") for c in clause_ids]
    asked += named_clauses(question) + named_clauses(topic)
    if asked:
        seen = {c["clause"] for c in wanted}
        for cid in asked:
            found = clause(book_id, cid)
            if found is not None and found["clause"] not in seen:
                wanted.append(found)
                seen.add(found["clause"])
        how = "clause id"

    if not wanted:
        sections = (named_sections(question) + named_sections(topic)
                    or sections_for(book_id, f"{question} {topic}"))
        prefix = "RP" if book_id == "retail" else "CP"
        sections = [s for s in sections if s.startswith(prefix)]
        if sections:
            wanted = [c for c in everything if c["section"] in sections]
            how = "section"

    if not wanted:
        return {
            "book": book_id, "policy": book["title"],
            "pack_version": version(), "clauses": [], "matched_by": "",
            "note": ("No clause of this book's policy matches. Name a "
                     "clause id, a section id, or a policy topic -- "
                     "concentration, covenants, collections, staging, "
                     "collateral, cut-offs, a new product."),
            "sections": [f"{s['section']} {s['title']}"
                         for s in book["sections"]],
        }

    clipped = len(wanted) > MAX_CLAUSES
    return {
        "book": book_id, "policy": book["title"],
        "pack_version": version(),
        "approved_by": book["approved_by"],
        "next_review": book["next_review"],
        "not_client_data": True,
        "matched_by": how,
        "clauses": wanted[:MAX_CLAUSES],
        "clipped": clipped,
        "citation_rule": (
            "Quote the clause id and the rule as written when proposing a "
            "change to it. The `levers` on each clause are the changes that "
            "clause can carry; they are not a recommendation."),
    }


# ---- a recommendation has to cite --------------------------------------

def citations(text: str, book_id: str) -> list[str]:
    """Clause ids in a piece of prose that this book actually contains.

    A clause id the pack does not hold is not a citation. Neither is the
    OTHER book's clause: `CP-1.2` quoted in a Retail answer is a rule that
    does not apply to the exposure being discussed, which is a worse error
    than quoting nothing.
    """
    held = {c["clause"] for c in clauses(book_id)}
    seen: list[str] = []
    for cid in named_clauses(text):
        if cid in held and cid not in seen:
            seen.append(cid)
    return seen


def foreign_citations(text: str, book_id: str) -> list[str]:
    """Clause ids from the OTHER book. Always a mistake, never a warning."""
    other = "corporate" if book_id == "retail" else "retail"
    held = {c["clause"] for c in clauses(other)}
    return [cid for cid in named_clauses(text) if cid in held]


__all__ = ["CLAUSE_ID", "MAX_CLAUSES", "PACK_PATH", "UnknownBook",
           "citations", "clause", "clauses", "foreign_citations",
           "named_clauses", "named_sections", "pack", "retrieve",
           "sections_for", "synopsis", "version"]
