"""
Whether the governed data can answer this question at all.

The failure this prevents
-------------------------
    "Which borrowers had their CEO resign in the last three months?"

CreditProbe holds no governance or personnel data. The honest answer is one
sentence: it does not have that. What used to happen instead was a clarification
— *"which figure should CreditProbe measure?"* — which is a reasonable question
about a request that names a figure, and a slightly absurd one about a request
that names a corporate event. Worse, the user's most likely next move is to pick
a figure from the menu, at which point CreditProbe answers a question about
exposure that nobody asked.

So an out-of-scope request is a distinct outcome with its own sentence, not a
clarification with the wrong menu.

How it decides
--------------
Structurally, not by keyword list. A request is out of scope when it asks for a
computation, names a **subject the governed universe has no word for**, and
names no governed concept, dataset, field, dimension value or borrower that
would give the planner something to compute. The subject is read from the
request's own nouns, so a new domain published into the Data Builder makes the
same question answerable without touching this module.

The bar is deliberately high. Saying "CreditProbe does not have that" about
something it does have is a worse failure than a clarification, so anything that
touches the governed vocabulary at all falls through to the ordinary path.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

#: Words that carry no subject. Everything here is grammar, quantity, or the
#: vocabulary of asking — never the thing being asked about.
_STRUCTURAL = frozenset("""
a an the this that these those there here it its their his her they them
what which who whom whose when where why how many much any all some each every
both few more most other another same such no not only just also than then
show me give tell list find get display return report produce provide compute
calculate work out figure look see want need would could should can may might
do does did done have has had having be been being is are was were am
of in on at to for from by with without within into onto over under above below
between during before after since until across per about around as and or but if
i you we us our your please thanks thank
top bottom largest smallest biggest highest lowest first last latest previous
next current recent new old best worst
customers customer borrowers borrower clients client counterparties counterparty
names name entities entity accounts account facilities facility obligors obligor
data dataset datasets field fields information records record
period periods quarter quarters year years month months day days quarterly annual
one two three four five six seven eight nine ten
percent percentage share ratio total sum average mean count number amount value
increase decrease increased decreased rose fell rising falling worsening
improving deteriorating deteriorate deteriorated worsen worsened improve
improved decline declined declining rise fall grow grew shrink shrank
change changed movement growth trend trends compare comparison versus vs
""".split())

#: How many unrecognised content words it takes to conclude the request is
#: about something else entirely.
#:
#: One is not enough. A single unknown word is far more likely to be a synonym
#: nobody has taught CreditProbe than a whole domain the bank has not published
#: — "what deteriorated?" is a credit question with an unfamiliar verb, not a
#: question about a thing called deterioration. Refusing it would be the worse
#: error, so a single unknown falls through to the ordinary clarification.
MIN_UNKNOWN_TERMS = 2

#: Punctuation and numbers carry no subject either.
_TOKEN = re.compile(r"[a-z][a-z'&/-]*")


def _structural(token: str) -> str | bool:
    """Whether this word carries no subject, singular or plural.

    Stemmed for the same reason the universe is: "give me the numbers" is not a
    question about a governed thing called "numbers", and answering it with
    "CreditProbe has no data about numbers" would be both true and useless.
    """
    return (token in _STRUCTURAL
            or token.rstrip("s") in _STRUCTURAL
            or f"{token}s" in _STRUCTURAL)


@dataclass(frozen=True)
class Coverage:
    """Whether the governed universe has anything to say about this request."""

    covered: bool
    #: The words that found no governed meaning. Shown to the user, because
    #: "CreditProbe has no governed data about CEO resignations" is only useful
    #: if it names what it looked for.
    unknown_terms: tuple[str, ...] = ()
    #: What it did recognise. Present even when covered is False, so a partly
    #: recognised request can say what it did understand.
    known_terms: tuple[str, ...] = ()
    subject: str = ""

    @property
    def out_of_scope(self) -> bool:
        return not self.covered

    def sentence(self) -> str:
        """The refusal, naming what was asked, what is held, and a way on.

        §8: no dead ends. A refusal that names the gap and stops is still a
        dead end - the reader is told what cannot be done and left with
        nothing to do about it, which is the moment somebody closes the tab.

        So the sentence has three parts, and the third is not decoration:
        what was looked for, why it is not there, and what the catalogue DOES
        hold that is nearest. Said in prose rather than offered as a menu -
        §6 removed the menu for a reason, and a list of buttons here would
        invite the reader to accept a confident answer to a question they did
        not ask.
        """
        subject = self.subject or " and ".join(self.unknown_terms[:3])
        said = (
            f"CreditProbe has no governed data about {subject}. It answers only "
            "from the datasets a steward has published and marked "
            "authoritative, so it cannot look this up, estimate it, or infer it "
            "from what it does hold.")
        return said + " " + self.next_move()

    def next_move(self) -> str:
        """What the reader can do instead, from what is actually published.

        Drawn from the catalogue rather than written down here, so a bank that
        publishes a domain between two questions is offered it immediately -
        the same reason `_universe()` is rebuilt per call.
        """
        recognised = [t for t in self.known_terms if len(t) > 3][:4]
        if recognised:
            return ("It did recognise " + _and_list(recognised) +
                    ", so a question framed around those can be answered. "
                    "Name the figure you want and the period you want it for.")
        measures = _published_measures()
        if measures:
            return ("The catalogue carries measures such as "
                    + _and_list(measures[:4]) +
                    ". Name the one you want and the period you want it for, "
                    "and CreditProbe will compose the analysis.")
        return ("Nothing is published that would answer this. A data steward "
                "can publish the dataset it would need in the Data Builder.")

    def to_dict(self) -> dict[str, Any]:
        return {"covered": self.covered, "subject": self.subject,
                "unknown_terms": list(self.unknown_terms),
                "known_terms": list(self.known_terms),
                "next_move": self.next_move()}


def _and_list(items: Any) -> str:
    kept = [str(i) for i in items if str(i).strip()]
    if not kept:
        return ""
    if len(kept) == 1:
        return kept[0]
    return ", ".join(kept[:-1]) + " and " + kept[-1]


def _published_measures() -> list[str]:
    """Governed measures a reader could ask about, from the live catalogue."""
    try:
        from backend.orchestration import ontology

        found = [str(c) for c in getattr(ontology, "MEASURE_NAMES", ())]
        if found:
            return sorted(found)
    except Exception:  # noqa: BLE001 - the refusal must not itself fail
        pass
    try:
        from backend.orchestration import concepts as cx

        # The same source the reading clarification names its examples from
        # (`executor._reading_clarification`). Two refusals drawing their
        # examples from two places is how a product ends up offering a
        # measure on one screen that another screen says it does not have.
        return [c.label for c in cx.CONCEPTS
                if not c.is_categorical and not c.is_ordinal][:12]
    except Exception:  # noqa: BLE001
        return []


@dataclass
class _Universe:
    """Every word the governed data gives meaning to."""

    words: set[str] = field(default_factory=set)

    def knows(self, token: str) -> bool:
        if token in self.words:
            return True
        # A plural of a governed word is governed. Cheap stemming beats a
        # dependency, and the failure mode of missing one is a clarification.
        return token.rstrip("s") in self.words or f"{token}s" in self.words


def _universe() -> _Universe:
    """The governed vocabulary, assembled from what is actually published.

    Rebuilt per call rather than cached: the Data Builder can publish a domain
    between two questions, and a cached universe would keep refusing a question
    the bank has just made answerable.
    """
    words: set[str] = set()

    def add(text: Any) -> None:
        for token in _TOKEN.findall(str(text or "").lower()):
            if len(token) > 1:
                words.add(token)

    try:
        from backend.orchestration import concepts as cx

        for concept in cx.CONCEPTS:
            add(concept.id.replace("_", " "))
            add(concept.label)
            # The pattern is a regex of everything people call this concept.
            add(re.sub(r"[\\^$.|?*+()\[\]{}]|\\b", " ", concept.pattern))
            for candidate in concept.candidates:
                add(candidate.field.replace("_", " "))
                add(candidate.dataset.replace("_", " "))
                add(" ".join(candidate.qualifiers))
    except Exception as e:  # noqa: BLE001
        logger.debug("Concepts unavailable to the coverage check: %s", e)

    try:
        from backend.data_access import get_data_source

        source = get_data_source()
        for name in source.datasets():
            add(name.replace("_", " "))
            try:
                meta = source.describe(name)
            except Exception:  # noqa: BLE001
                continue
            add(getattr(meta, "business_name", ""))
            add(getattr(meta, "domain", ""))
            for column in getattr(meta, "columns", ()) or ():
                add(str(getattr(column, "name", column)).replace("_", " "))
                add(getattr(column, "business_name", ""))
    except Exception as e:  # noqa: BLE001
        logger.debug("Catalogue unavailable to the coverage check: %s", e)

    try:
        # An approved Analysis Studio method is part of the governed universe
        # too. "What methods do you have for concentration?" names nothing in
        # the data dictionary, but concentration is a method the bank has
        # certified, and refusing it would be CreditProbe denying it holds its
        # own method library.
        from backend.orchestration.context import all_methods

        for method in all_methods():
            add(method.id.replace("_", " "))
            add(method.name)
            add(method.category)
            add(" ".join(method.aliases or ()))
    except Exception as e:  # noqa: BLE001
        logger.debug("Method library unavailable to the coverage check: %s", e)

    try:
        from backend.orchestration.vocabulary import get_vocabulary

        vocab = get_vocabulary()
        for dimension, values in (vocab.to_dict().get("dimensions") or {}).items():
            add(dimension.replace("_", " "))
            for value in values:
                add(value)
    except Exception as e:  # noqa: BLE001
        logger.debug("Vocabulary unavailable to the coverage check: %s", e)

    return _Universe(words=words)


def _subject_of(unknown: list[str], question: str) -> str:
    """The unknown words as a phrase, in the order the question said them.

    Reconstructed from the question rather than joined with commas, so the
    refusal reads "CEO resignations" and not "ceo, resign".
    """
    if not unknown:
        return ""
    lowered = question.lower()
    first, last = unknown[0], unknown[-1]
    start = lowered.find(first)
    end = lowered.find(last) + len(last)
    if 0 <= start < end <= len(question):
        phrase = question[start:end].strip(" ,.?!")
        if len(phrase.split()) <= 6:
            return phrase
    return " ".join(unknown[:3])


def check(question: str, reading: Any = None) -> Coverage:
    """Whether the governed universe can say anything about this request.

    `reading` is the structured reading when one exists. A request that already
    resolved a governed concept is covered by construction — there is something
    to compute — and this returns early rather than second-guessing it.
    """
    text = str(question or "")
    if not text.strip():
        return Coverage(covered=True)

    if reading is not None:
        if getattr(reading, "concepts", ()) or getattr(reading, "metrics", ()):
            return Coverage(covered=True)
        if getattr(reading, "datasets", ()) or getattr(reading, "entities", ()):
            return Coverage(covered=True)

    # A governed composite is governed vocabulary. "Which companies are
    # running into liquidity trouble?" carries no word the catalogue holds —
    # `liquidity`, `trouble` and `companies` are none of them column names —
    # so the token scan below concluded the bank had not published anything on
    # the subject and refused. It has: the composite resolves to eight
    # published fields on the facility position, which is exactly the "there
    # is something to compute" test the reading check above applies.
    try:
        from backend.data_access import get_catalog
        from backend.orchestration import composites as cmp

        if cmp.find(text, get_catalog()) is not None:
            return Coverage(covered=True)
    except Exception:  # noqa: BLE001 - a catalogue that will not load is not
        # a reason to refuse; the same reasoning as the empty-universe guard
        # immediately below.
        pass

    universe = _universe()
    if not universe.words:
        # No catalogue to check against. Refusing on the basis of a universe
        # that failed to load would turn a transient data problem into "we do
        # not have your data", which is a much more damaging sentence.
        return Coverage(covered=True)

    known: list[str] = []
    unknown: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if len(token) < 2 or _structural(token):
            continue
        (known if universe.knows(token) else unknown).append(token)

    if known or len(unknown) < MIN_UNKNOWN_TERMS:
        return Coverage(covered=True, known_terms=tuple(known),
                        unknown_terms=tuple(unknown))

    return Coverage(covered=False, unknown_terms=tuple(unknown),
                    subject=_subject_of(unknown, text))


def _measure_words() -> set[str]:
    """The governed vocabulary of MEASURES, and nothing else.

    Narrower than `_universe` on purpose. That one includes every column name
    and business name in the catalogue, which is right for "could this question
    be about our data at all" and far too permissive for "did this question
    name something we can compute". "Tenure" is a word in some column's
    description, so a question about a chief executive's tenure looked covered;
    no concept in the ontology measures it, so nothing could be computed, and
    the reader got a menu of unrelated figures instead of an answer.
    """
    words: set[str] = set()
    try:
        from backend.orchestration import concepts as cx

        for concept in cx.CONCEPTS:
            for text in (concept.id.replace("_", " "), concept.label,
                         re.sub(r"[\\^$.|?*+()\[\]{}]|\\b", " ", concept.pattern)):
                for token in _TOKEN.findall(str(text or "").lower()):
                    if len(token) > 1 and not _structural(token):
                        words.add(token)
    except Exception as e:  # noqa: BLE001
        logger.debug("Concepts unavailable to the measure check: %s", e)
    return words


def names_a_measure(question: str) -> bool:
    """Whether this sentence names something CreditProbe can compute.

    Used to tell two failures apart that look identical from inside the
    planner. "Rank those by ECL" with no population names a measure and needs a
    clarification; "what is the CEO's tenure?" names none, and offering it a
    menu of exposure, expected credit loss and rating invites the reader to
    accept an answer to a question they did not ask.

    Errs toward TRUE. An empty vocabulary — a catalogue that failed to load —
    must not turn every question into "we do not hold that", which is a far
    more damaging sentence than an unnecessary clarification.
    """
    words = _measure_words()
    if not words:
        return True
    return any(token in words
               for token in _TOKEN.findall(str(question or "").lower())
               if len(token) > 1 and not _structural(token))


__all__ = ["Coverage", "check", "names_a_measure"]
