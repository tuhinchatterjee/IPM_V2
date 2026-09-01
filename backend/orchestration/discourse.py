"""
What a single message says about itself. P0.2.

The failure this exists to fix
------------------------------
    "Which customers experienced a rating downgrade, an increase in ECL of
     more than 20%, worsening DPD and declining covenant headroom over the
     latest year? Rank them by EAD."

CreditProbe answered: *"could not work out what 'them' refers to — no previous
result in this investigation returned a set of names to carry forward."*

There was no previous result and there did not need to be one. "them" is the
cohort the FIRST sentence defines. The product looked only backwards, at the
conversation, and never at the message in front of it — so a question that is
completely unambiguous to any reader was refused.

`referents.py` looks BACKWARDS, at what earlier turns settled. This module looks
INWARDS, at one message, and the two are deliberately separate: a message can be
self-contained (this module resolves it and no conversation is needed), can
depend on the conversation (referents.py), or can be genuinely ambiguous (a
clarification). P0.2 fixes the order in which those are tried:

    1. an explicit antecedent in the same clause
    2. an explicit cohort introduced earlier in the same message
    3. the conversation's working memory
    4. clarification

Only when 1-3 all fail is a question ambiguous.

Grammar, not phrases
--------------------
Every pattern here is grammatical: a pronoun, a head noun, a relative clause, a
comparative preposition. Nothing keys on a credit phrase, a measure name or a
specific sentence. "Rank them by EAD" resolves for the same reason "Rank them by
headcount" would — an anaphor with a plural antecedent in the preceding clause —
and the module has no idea what EAD is. That is the difference between reading a
sentence and recognising one, and P0.2 requires the first.

What it produces
----------------
A `Discourse`: the clauses in order, the cohorts the message DEFINES, the
mentions that point at them, and the resolution for each mention. The plan
stores it, so the Trace can show which words bound to which clause and a
reviewer can disagree with a specific link rather than with the whole reading.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# The grains a cohort can be about
# ---------------------------------------------------------------------------

#: Head nouns that denote a population, mapped to the governed grain they
#: correspond to. A cohort is always a set of THINGS, and which thing decides
#: how the cohort is later built and joined.
#: Deliberately excludes the words that name an ATTRIBUTE rather than a
#: population — rating, stage, exposure, limit. In credit language those are
#: measures ("an increase in exposure", "customers whose ratings were
#: unchanged"), and admitting them here would invent a cohort out of a measure
#: and let a pronoun bind to it.
HEAD_NOUNS: dict[str, str] = {
    "customer": "customer", "customers": "customer",
    "borrower": "customer", "borrowers": "customer",
    "client": "customer", "clients": "customer",
    "obligor": "customer", "obligors": "customer",
    "counterparty": "customer", "counterparties": "customer",
    "name": "customer", "names": "customer",
    "groups": "customer",
    "facility": "facility", "facilities": "facility",
    "account": "facility", "accounts": "facility",
    "loan": "facility", "loans": "facility",
    "sector": "sector", "sectors": "sector",
    "industry": "sector", "industries": "sector",
    "segment": "segment", "segments": "segment",
    "region": "region", "regions": "region",
    "product": "product", "products": "product",
    "portfolio": "portfolio", "portfolios": "portfolio",

    # Metadata objects. A question about the catalogue is still a question with
    # a population in it — "What columns are in the ratings data, and which of
    # them are financial ratios?" — and "them" there points at the columns.
    # Leaving these out made a metadata follow-up look like a dangling
    # reference to a previous result that was never needed.
    "column": "field", "columns": "field",
    "field": "field", "fields": "field",
    "measure": "measure", "measures": "measure",
    "metric": "measure", "metrics": "measure",
    "dataset": "dataset", "datasets": "dataset",
    "table": "dataset", "tables": "dataset",
    "domain": "domain", "domains": "domain",
    "method": "method", "methods": "method",
    "analysis": "analysis", "analyses": "analysis",
    "relationship": "relationship", "relationships": "relationship",
}

#: Plural anaphors. Deliberately only the plural and collective ones: a cohort
#: is a set, and "it" almost always points at a measure rather than at a
#: population, which is a different resolution problem.
_PRONOUNS: tuple[str, ...] = (
    "them", "these", "those", "they", "their", "theirs",
)

#: Determiner phrases that point back without a pronoun: "the same customers",
#: "that cohort", "this population". The head noun is captured so the mention
#: can be matched to a cohort of the right grain.
_DETERMINED = re.compile(
    r"\b(?:the same|that|this|these|those|such)\s+"
    r"(?P<head>[a-z]+(?:\s+[a-z]+)?)\b", re.I)

#: A pronoun as a whole word.
_PRONOUN_RE = re.compile(
    r"\b(" + "|".join(_PRONOUNS) + r")\b", re.I)

# ---------------------------------------------------------------------------
# Segmentation
# ---------------------------------------------------------------------------

#: Sentence end.
#:
#: A decimal point inside a number is the one common false boundary in this
#: domain — "a DSCR below 1.2" must not become two sentences. That is already
#: prevented by requiring WHITESPACE OR END after the terminator: the "." in
#: "1.2" is followed by a digit, so it never matches.
#:
#: There used to be a `(?<![0-9])` lookbehind here as well, and it was doing
#: real damage. It blocked a terminator after any digit, so a sentence ending
#: in a period, a year or an amount did not end:
#:
#:     "Which borrowers breached a covenant at Q2 2026? Explain what changed
#:      for each of them."
#:
#: stayed one clause. "them" then sat in the SAME clause as the cohort it
#: refers to, could not bind to it — a mention cannot resolve against its own
#: defining clause — and the product asked which borrowers were meant, of a
#: message that had just said. Every question ending "...in 2025." or "...at
#: Q2 2026?" was affected, which is most of them.
_SENTENCE = re.compile(r"[.?!]+(?:\s+|$)")

#: Clause boundaries INSIDE a sentence that start a new request. Each one is a
#: coordinator followed by something that begins a new predicate:
#:
#:   "... over the latest year and rank them by EAD"      → imperative verb
#:   "... deteriorated and which customers are affected"  → wh-word
#:   "... , then compare them with ..."                   → sequencer
#:
#: A bare "and" is NOT a boundary — "leverage and DSCR and DPD" is one clause
#: with three measures, and splitting it would turn one objective into three.
_CLAUSE = re.compile(
    r"[,;]?\s+(?:and\s+|then\s+|,\s*then\s+|and\s+then\s+|"
    r"finally\s+|also\s+|as\s+well\s+as\s+)?"
    r"(?=(?:"
    # a wh-question starting a new clause
    r"which|what|who|whose|whom|when|where|why|how"
    # an imperative that starts a new instruction
    r"|rank|sort|order|list|show|compare|contrast|determine|identify|find"
    r"|calculate|compute|decompose|attribute|split|group"
    # "break down" is separable: "break the change down by sector" is the
    # way an officer actually says it, and a contiguous "break\s+down"
    # pattern misses it. Missing it does not drop the clause - it MERGES it
    # into the previous one, which is worse: coverage then reports one
    # objective answered out of one, while half the request went unanswered.
    r"|break(?:\s+(?:the|this|that|it|them|these|those|\w+)){0,3}\s+down"
    r"|tell|give|display|highlight|explain|summarise|summarize|assess"
    r"|quantify|reconcile|rate|score|flag|check|evaluate|analyse|analyze"
    r"|investigate|review|report|say|state|provide|name|return"
    r")\b)",
    re.I)

#: The imperative verbs a request is built out of. Used to tell a SERIAL
#: instruction from a fronted adverbial, which is the one distinction a comma
#: cannot make on its own:
#:
#:   "For every sector, calculate the Stage 2 share"       one request
#:   "Calculate total EAD, rank the borrowers by ECL"      two
#:
#: Both are "<something>, <verb>". The difference is whether a predicate has
#: already happened: the first comma follows a prepositional phrase, the second
#: follows a complete instruction. So a comma is a boundary exactly when the
#: text before it already contains an imperative.
_IMPERATIVE = re.compile(
    r"\b(?:rank|sort|order|list|show|compare|contrast|determine|identify"
    r"|find|calculate|compute|decompose|attribute|split|group"
    r"|break(?:\s+(?:the|this|that|it|them|these|those|\w+)){0,3}\s+down"
    r"|tell|give|display|highlight|explain|summarise|summarize|assess"
    r"|quantify|reconcile|score|flag|check|evaluate|analyse|analyze"
    r"|investigate|review|report|say|state|provide|name|return)\b",
    re.I)

#: A boundary is real only when a COORDINATOR is actually there. A bare comma
#: is not one: "For every sector, calculate Stage 2 EAD share" is a fronted
#: adverbial followed by its verb — one request — and splitting on the comma
#: turned "For every sector" into an objective of its own that nothing could
#: ever answer.
_NEEDS_COORDINATOR = re.compile(
    r"(?:\band\b|\bthen\b|\balso\b|\bfinally\b|\bas\s+well\s+as\b)\s*[,;]?\s*$",
    re.I)


@dataclass(frozen=True)
class Clause:
    """One request inside a message."""

    index: int
    text: str
    #: Where it started in the original message, so the Trace can point at it.
    start: int

    @property
    def lowered(self) -> str:
        return self.text.lower()


def segment(question: str) -> list[Clause]:
    """Split a message into the clauses that each ask for something.

    Sentences first, then coordinated clauses inside a sentence. The result is
    ordered and covers the whole message: a mention in clause 2 can look at
    clause 1, which is the entire point.
    """
    text = str(question or "").strip()
    if not text:
        return []

    found: list[Clause] = []
    for piece, offset in _sentences(text):
        for part, inner in _inner_clauses(piece):
            cleaned = part.strip(" ,;")
            if len(cleaned.split()) >= 2:
                found.append(Clause(len(found), cleaned, offset + inner))
    if not found:
        found = [Clause(0, text.strip(" ,;.?!"), 0)]
    return found


def _sentences(text: str) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    at = 0
    for match in _SENTENCE.finditer(text):
        piece = text[at:match.start()]
        if piece.strip():
            out.append((piece, at))
        at = match.end()
    tail = text[at:]
    if tail.strip():
        out.append((tail, at))
    return out or [(text, 0)]


def _inner_clauses(sentence: str) -> list[tuple[str, int]]:
    """Split one sentence where a coordinator introduces a new request."""
    cuts: list[int] = []
    for match in _CLAUSE.finditer(sentence):
        before = sentence[:match.start() + len(match.group(0))]
        # The boundary is real only if a coordinator or punctuation sits
        # immediately before the new predicate, or the new predicate is a
        # wh-word (which can start a clause on its own after a comma).
        head = sentence[match.end():match.end() + 12].lower()
        wh = head.split(" ")[0].rstrip("?,.") in {
            "which", "what", "who", "whose", "whom", "when", "where",
            "why", "how"}
        separator = match.group(0)
        preceding = sentence[:match.start()]
        real = (
            _NEEDS_COORDINATOR.search(before)
            or (wh and separator.strip())
            # A semicolon separates independent clauses by definition. §11's
            # own example depends on it: "Decompose ECL change into exposure,
            # Stage, PD, LGD and mix; show sector and customer contributors"
            # is two objectives, and read as one it can never be reported as
            # partially answered.
            or ";" in separator
            # A serial instruction. See _IMPERATIVE.
            or ("," in separator and _IMPERATIVE.search(preceding))
        )
        if real and match.start() > 0:
            cuts.append(match.start())
    if not cuts:
        return [(sentence, 0)]

    out: list[tuple[str, int]] = []
    at = 0
    for cut in cuts:
        piece = sentence[at:cut]
        if piece.strip():
            out.append((piece, at))
        at = cut
    if sentence[at:].strip():
        out.append((sentence[at:], at))
    return out


# ---------------------------------------------------------------------------
# Cohorts a message defines
# ---------------------------------------------------------------------------

#: What RESTRICTS a population to a subset: a relative clause ("customers whose
#: rating fell"), a participle or finite verb ("customers experiencing",
#: "customers experienced"), or a preposition ("customers with a downgrade").
#:
#: A head noun with no restrictor is still a population — "the worst sectors",
#: "every sector", "customers" — and still an antecedent a later pronoun can
#: bind to. The restrictor decides whether the cohort is a SUBSET that has to be
#: built, not whether it can be referred to. Conflating those two was why
#: "Show the worst sectors and the customers driving them" resolved nothing.
_RESTRICTOR = re.compile(
    r"^\s*(?:"
    r"who|whose|whom|which|that|where"
    r"|with|without|having|showing|experiencing|reporting|exhibiting"
    r"|in|on|at|under|over|above|below|between"
    # A finite or participial verb directly after the head noun: "customers
    # experienced a downgrade", "sectors driving the increase". Matched by
    # shape (-ed / -ing) rather than by a list of credit verbs.
    r"|[a-z]+(?:ed|ing)\b"
    r")\b", re.I)

#: Determiners and adjectives that qualify a population without restricting it
#: to a computed subset. Captured for the label so a cohort reads back as the
#: words the user actually wrote.
_QUALIFIER = re.compile(
    r"((?:\b(?:the|every|each|all|any|those|these|top|bottom|first|last|worst|"
    r"best|largest|biggest|smallest|highest|lowest|main|key|material|affected|"
    r"remaining|other|same|\d+)\s+){0,4})$", re.I)

#: A determiner that means "all of them". Recorded, not excluded: "every sector"
#: is a population and "rank those with the largest increase" refers to it.
_UNIVERSAL = re.compile(r"\b(?:every|each|all|any)\s+$", re.I)


@dataclass
class Cohort:
    """A population one clause defines, for later clauses to refer to."""

    cohort_id: str
    #: "customer", "sector", ... the governed grain this cohort is a set of.
    grain: str
    #: The head noun as written, for the Trace and for prose.
    head: str
    #: The restricting text — what makes this a subset rather than everything.
    #: Empty for an unrestricted population.
    predicate: str
    #: Which clause introduced it.
    clause_index: int
    #: Where in the message, so the Trace can highlight the words.
    start: int
    #: One past the last character of the phrase. A pronoun INSIDE this span
    #: cannot refer to it — "the customers driving them" — and without the end
    #: position that constraint cannot be applied.
    end: int = 0
    #: Determiners and adjectives written before the head noun.
    qualifier: str = ""
    #: True when the clause defines the cohort by CONTRAST with another
    #: ("... customers whose ratings were unchanged"), which is what makes a
    #: comparison two cohorts rather than one.
    contrastive: bool = False
    #: True when a restrictor narrows it to a subset that has to be computed.
    restricted: bool = False
    #: True for "every sector" / "all customers".
    universal: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "cohort_id": self.cohort_id,
            "grain": self.grain,
            "head": self.head,
            "predicate": self.predicate,
            "clause_index": self.clause_index,
            "start": self.start,
            "end": self.end,
            "qualifier": self.qualifier,
            "contrastive": self.contrastive,
            "restricted": self.restricted,
            "universal": self.universal,
            "label": self.label,
        }

    @property
    def label(self) -> str:
        """How the cohort is named in prose and in a clarification."""
        said = " ".join(p for p in (self.qualifier.strip(), self.head,
                                    self.predicate) if p).strip()
        return said[:180]


def cohorts(clauses: list[Clause]) -> list[Cohort]:
    """Every population the message itself defines, in order."""
    found: list[Cohort] = []
    for clause in clauses:
        found.extend(_cohorts_in(clause, len(found)))
    return found


def _cohorts_in(clause: Clause, seen: int) -> list[Cohort]:
    out: list[Cohort] = []
    for match in re.finditer(r"\b([a-z]+)\b", clause.text, re.I):
        word = match.group(1).lower()
        grain = HEAD_NOUNS.get(word)
        if grain is None:
            continue
        before = clause.text[:match.start()]
        rest = clause.text[match.end():]

        restrictor = _RESTRICTOR.match(rest)
        predicate = ""
        if restrictor:
            predicate = rest.strip().rstrip(" ,.?!")
            if len(predicate.split()) < 2:
                predicate = ""

        qualifier = ""
        qualified = _QUALIFIER.search(before)
        if qualified:
            qualifier = qualified.group(1)

        # Where the phrase ends: after its restrictor if it has one, otherwise
        # after the head noun itself.
        end = clause.start + match.end()
        if predicate:
            end = clause.start + match.end() + len(rest.rstrip(" ,.?!"))

        out.append(Cohort(
            cohort_id=f"cohort_{seen + len(out) + 1}",
            grain=grain,
            head=word,
            predicate=predicate,
            clause_index=clause.index,
            start=clause.start + match.start() - len(qualifier),
            end=end,
            qualifier=qualifier,
            contrastive=_is_contrastive(before, predicate),
            restricted=bool(predicate),
            universal=bool(_UNIVERSAL.search(before)),
        ))
    return out


#: A comparison introduces its second cohort behind one of these. "Compare them
#: WITH customers whose ratings were unchanged" — the preposition is what says
#: a second population is being defined rather than the first being narrowed.
_CONTRAST_BEFORE = re.compile(
    r"\b(?:with|against|versus|vs\.?|to|and|between|compared\s+(?:with|to))\s*$",
    re.I)


def _is_contrastive(before: str, predicate: str) -> bool:
    if _CONTRAST_BEFORE.search(before):
        return True
    return bool(re.search(r"\b(?:unchanged|stable|did\s+not|were\s+not|"
                          r"no\s+change|not\s+downgraded|non-)\b",
                          predicate, re.I))


# ---------------------------------------------------------------------------
# Mentions that point at them
# ---------------------------------------------------------------------------


@dataclass
class Mention:
    """A word that refers to a population rather than naming one."""

    text: str
    clause_index: int
    start: int
    #: The head noun where the mention names one ("the same customers"), so a
    #: mention can be matched to a cohort of the right grain.
    head: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"text": self.text, "clause_index": self.clause_index,
                "start": self.start, "head": self.head}


def mentions(clauses: list[Clause]) -> list[Mention]:
    """Every anaphor in the message, in order."""
    found: list[Mention] = []
    for clause in clauses:
        for match in _PRONOUN_RE.finditer(clause.text):
            found.append(Mention(match.group(1).lower(), clause.index,
                                 clause.start + match.start()))
        for match in _DETERMINED.finditer(clause.text):
            head = match.group("head").split()[-1].lower()
            if head in HEAD_NOUNS:
                found.append(Mention(match.group(0).strip().lower(),
                                     clause.index,
                                     clause.start + match.start(),
                                     head=head))
    found.sort(key=lambda m: m.start)
    return found


# ---------------------------------------------------------------------------
# The reading
# ---------------------------------------------------------------------------


@dataclass
class Resolution:
    """One mention, and what it was found to mean."""

    mention: Mention
    cohort: Cohort | None
    #: "same_clause" | "earlier_clause" | "conversation" | "unresolved"
    source: str
    because: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "mention": self.mention.to_dict(),
            "cohort_id": self.cohort.cohort_id if self.cohort else "",
            "cohort": self.cohort.to_dict() if self.cohort else None,
            "source": self.source,
            "because": self.because,
        }


@dataclass
class Discourse:
    """What one message says about itself."""

    question: str
    clauses: list[Clause] = field(default_factory=list)
    cohorts: list[Cohort] = field(default_factory=list)
    mentions: list[Mention] = field(default_factory=list)
    resolutions: list[Resolution] = field(default_factory=list)

    @property
    def self_contained(self) -> bool:
        """Every mention found an antecedent inside this message.

        The question P0.2 turns on: when this is true, no previous result is
        needed and asking for one is the defect.
        """
        return bool(self.mentions) and all(
            r.cohort is not None for r in self.resolutions)

    @property
    def unresolved(self) -> list[Resolution]:
        return [r for r in self.resolutions if r.cohort is None]

    def cohort(self, cohort_id: str) -> Cohort | None:
        return next((c for c in self.cohorts if c.cohort_id == cohort_id), None)

    @property
    def comparison(self) -> tuple[Cohort, Cohort] | None:
        """The two cohorts a comparative message defines, if it defines two.

        §B's requirement, read off the sentence rather than assumed: one cohort
        introduced plainly and a second introduced behind a contrastive
        preposition, of the same grain so that comparing them means something.
        """
        if len(self.cohorts) < 2:
            return None
        contrastive = [c for c in self.cohorts if c.contrastive]
        plain = [c for c in self.cohorts if not c.contrastive]
        if not contrastive or not plain:
            return None
        first, second = plain[0], contrastive[-1]
        if first.grain != second.grain:
            return None
        return first, second

    def to_dict(self) -> dict[str, Any]:
        found = self.comparison
        return {
            "clauses": [{"index": c.index, "text": c.text} for c in self.clauses],
            "cohorts": [c.to_dict() for c in self.cohorts],
            "mentions": [m.to_dict() for m in self.mentions],
            "resolutions": [r.to_dict() for r in self.resolutions],
            "self_contained": self.self_contained,
            "comparison": ([found[0].cohort_id, found[1].cohort_id]
                           if found else []),
        }


def read(question: str, *, has_conversation_population: bool = False
         ) -> Discourse:
    """Read one message's internal structure.

    `has_conversation_population` is step 3 of P0.2's order: when this message
    resolves nothing locally but the conversation does hold a population, the
    mention is attributed to the conversation rather than left unresolved, and
    `referents.py` does the actual carrying.
    """
    clauses = segment(question)
    found = cohorts(clauses)
    said = mentions(clauses)

    resolutions: list[Resolution] = []
    for mention in said:
        cohort, source, because = _antecedent(
            mention, found, has_conversation_population)
        resolutions.append(Resolution(mention, cohort, source, because))

    return Discourse(question=question, clauses=clauses, cohorts=found,
                     mentions=said, resolutions=resolutions)


def _antecedent(mention: Mention, found: list[Cohort],
                has_conversation: bool) -> tuple[Cohort | None, str, str]:
    """P0.2's resolution order, applied to one mention."""
    # Two constraints, both structural.
    #
    # A cohort defined AFTER the mention cannot be its antecedent — "compare
    # them with customers whose ratings were unchanged" refers backwards, and
    # binding it to the cohort on its right would invert the comparison.
    #
    # A cohort CONTAINING the mention cannot be its antecedent either: in "the
    # customers driving them", "them" is inside the phrase that describes the
    # customers, so it must point at something else. Without this the pronoun
    # binds to the noun it modifies and the sentence resolves to itself.
    before = [c for c in found
              if c.start < mention.start and mention.start >= c.end]

    if mention.head:
        grain = HEAD_NOUNS.get(mention.head, "")
        matching = [c for c in before if c.grain == grain]
        if matching:
            best = matching[-1]
            return best, _source(best, mention), (
                f"{mention.text!r} names {best.head}, and this message already "
                f"defined {best.label!r}")

    if before:
        best = before[-1]
        return best, _source(best, mention), (
            f"{mention.text!r} refers to {best.label!r}, defined earlier in "
            f"the same message")

    if has_conversation:
        return None, "conversation", (
            f"{mention.text!r} was not defined in this message; the "
            f"conversation's population is used")

    return None, "unresolved", (
        f"{mention.text!r} refers to a population this message never defines "
        f"and no previous result supplies")


def _source(cohort: Cohort, mention: Mention) -> str:
    return ("same_clause" if cohort.clause_index == mention.clause_index
            else "earlier_clause")


# ---------------------------------------------------------------------------
# What the rest of the runtime asks
# ---------------------------------------------------------------------------


def resolves_locally(question: str) -> bool:
    """Whether this message answers its own references.

    The one call `referents.unresolved` needs: when this is true, refusing the
    question for want of a previous result is the defect P0.2 names.

    Two ways a message can answer itself, and the second was missing
    -----------------------------------------------------------------
    1. Every anaphor binds to a cohort an earlier clause defined. That is
       `self_contained`, and it is what "Rank THEM by EAD" needs.

    2. The message DEFINES its population and never refers back to it at all:

           "Identify the 10 borrowers with the highest probability of credit
            deterioration over the next 12 months."

       "the 10 borrowers" is not an anaphor. It is the head of the noun
       phrase that defines the cohort, and the restrictive modifier that
       defines it is in the same clause. There is nothing to carry forward
       because nothing points backwards.

       `self_contained` returns False here — it requires `bool(self.mentions)`
       and there are no mentions — so a question that could not be more
       self-contained was refused with "no previous result in this
       investigation returned a set of names to carry forward". A message with
       no backward reference is the easiest case in the language, and it was
       the one case that failed.

    3. It refers to nothing at all:

           "What is ECL for Contracting at Q2 2026?"

       No anaphor, no cohort, nothing pointing anywhere. The most
       self-contained sentence there is.

    So the condition is simply: nothing in this message points at something
    the message did not supply. `not found.unresolved` says exactly that, and
    it covers all three without enumerating them.

    A bare "Rank them by EAD" with nothing before it still has an unresolved
    mention, so it is still — correctly — a question for the conversation.
    """
    found = read(question)
    return not found.unresolved


def population_clause(question: str) -> str:
    """The clause that DEFINES the population, where the message defines one.

    Used by the planner: the cohort's own clause carries the conditions to
    build it, and the referring clause carries what to do with it.
    """
    found = read(question)
    if not found.cohorts:
        return ""
    return found.clauses[found.cohorts[0].clause_index].text


__all__ = [
    "Clause",
    "Cohort",
    "Discourse",
    "HEAD_NOUNS",
    "Mention",
    "Resolution",
    "cohorts",
    "mentions",
    "population_clause",
    "read",
    "resolves_locally",
    "segment",
]
