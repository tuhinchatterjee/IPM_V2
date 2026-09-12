"""
Reading the question before answering it. Two passes, deliberately separate.

Pass one is about language
--------------------------
Spelling, transcription noise, a question typed in another language. Its one
job is to produce the same sentence in clean English, and its one prohibition
is to resolve anything: an ambiguous question must come out of this pass
still ambiguous, because deciding what "it" refers to is a judgement about
the conversation and this pass cannot see the conversation. A pass that
silently disambiguates is a pass that guesses in a place nobody is looking.

Pass two is about the request
-----------------------------
What is actually being asked: which subquestions, over what scope, for which
period, compared against what, and what remains genuinely unclear. It reads
the thread and the screen as well as the sentence, because "which names drive
it?" is a complete question when you can see what "it" is and an unanswerable
one when you cannot.

The seam
--------
Each pass has a deterministic implementation and a provider seam. Where a
provider is configured, Sonnet produces the structured output under the same
schema and the deterministic reading becomes the floor it is merged onto: the
model may improve the phrasing, split the subquestions better and notice a
part the patterns missed, and it may not resolve an entity, change a period to
one that was never published, or drop a part the patterns did find. Where no
provider is configured the deterministic reading is what runs, and `engine`
says so. Nothing here ever records a model call that did not happen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import layers as layers_mod
from backend.early_warning.conversation import budget as budget_mod
from backend.early_warning.conversation import seam as seam_mod

#: Transcription noise a voice interface leaves behind.
_FILLERS = re.compile(
    r"\b(um+|uh+|er+|ah+|hmm+|you know|i mean|like,|sort of|kind of)\b",
    re.I)

#: Common mis-hearings and mis-spellings of the terms this domain uses. Only
#: terms whose correction is unambiguous — nothing here decides a meaning.
_CORRECTIONS: tuple[tuple[str, str], ...] = (
    (r"\be\.?\s?w\.?\s?s\.?\b", "EWS"),
    (r"\bearly warning system\b", "early warning"),
    (r"\bear[ly]* warning\b", "early warning"),
    (r"\bexposer\b|\bexposue\b|\bexpsoure\b", "exposure"),
    (r"\bobligor?s?\b", lambda m: m.group(0)),
    (r"\bcovenent\b|\bcovanant\b", "covenant"),
    (r"\bcollatral\b|\bcolateral\b", "collateral"),
    # Spelling only. The SUFFIX is preserved, because "has deteriorated" and
    # "is deteriorating" are different tenses and a speller that changes one
    # into the other has edited the meaning, not the spelling.
    (r"\bdeteri(?:a|o)t(e|ed|ing|ion)\b", lambda m: f"deteriorat{m.group(1)}"),
    (r"\bdeteriorate(d|s)?ing\b", "deteriorating"),
    (r"\bescalat?e?ion\b", "escalation"),
    (r"\bclassifer\b|\bclasifier\b", "classifier"),
    (r"\bacelerator\b|\baccelarator\b", "accelerator"),
    (r"\bsegement\b|\bsegmnet\b", "segment"),
    (r"\bportfollio\b|\bportfolo\b", "portfolio"),
    (r"\bborower\b|\bborrwer\b", "borrower"),
    # Dropped vowels. A credit officer typing quickly writes "lst 6 mnths",
    # and the whole point of the language pass is that they should not have
    # to type carefully. Spelling only — no word here changes a tense, a
    # number or a period, and none of them is a word in its own right.
    (r"\bwich\b|\bwhcih\b|\bwhich\b", "which"),
    (r"\blst\b", "last"),
    (r"\bmnths?\b|\bmths\b|\bmonhts\b", "months"),
    (r"\bmst\b", "most"),
    (r"\bnmes\b|\bnames?s\b", "names"),
    (r"\bcontrcting\b|\bcontracting\b|\bcontractng\b", "Contracting"),
    (r"\bhgh\b", "high"),
    (r"\briks\b|\brsik\b", "risk"),
    (r"\bsectr\b|\bsecotr\b", "sector"),
    (r"\bincrese[dn]?\b", "increased"),
)

#: Words that mean the reader is pointing at something already on screen.
_REFERENTIAL = re.compile(
    r"\b(it|its|it's|this|that|these|those|them|they|the same|the weakest|"
    r"the worst|the one|there|here)\b", re.I)


@dataclass
class Cleaned:
    """Pass one: the same question, in clean English. Nothing resolved."""

    original_text: str
    cleaned_english: str
    translation_applied: bool = False
    detected_entities: list[str] = field(default_factory=list)
    uncertainties: list[str] = field(default_factory=list)
    transcription_uncertainties: list[str] = field(default_factory=list)
    engine: str = "deterministic"
    #: What actually served this pass — provider, model, role, latency. Empty
    #: when the deterministic implementation ran.
    model_call: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "cleaned_english": self.cleaned_english,
            "translation_applied": self.translation_applied,
            "detected_entities": list(self.detected_entities),
            "uncertainties": list(self.uncertainties),
            "transcription_uncertainties": list(self.transcription_uncertainties),
            "engine": self.engine,
            "model_call": dict(self.model_call),
        }


@dataclass
class BusinessRequest:
    """Pass two: what is actually being asked."""

    normalized_business_request: str = ""
    subquestions: list[str] = field(default_factory=list)
    requested_actions: list[str] = field(default_factory=list)
    requested_scope: str = ""
    requested_entities: list[str] = field(default_factory=list)
    requested_period: str = ""
    comparison_period: str = ""
    inherited_context: dict[str, Any] = field(default_factory=dict)
    requested_grouping: str = ""
    #: Obligors a name fragment matched, when it matched more than one. The
    #: reader is asked which; nothing is guessed and nothing is run.
    ambiguous_obligors: list[dict[str, Any]] = field(default_factory=list)
    #: The detection layer the question names, as a governed code. A layer is
    #: not a grouping and not a filter value; it decides which of the model's
    #: six layer/dimension outputs the answer is about.
    requested_layer: str = ""
    requested_analysis: str = ""
    #: EVERY analysis the request asks for, not just the leading one.
    requested_analyses: list[str] = field(default_factory=list)
    requested_evidence: bool = False
    remediation_requested: bool = False
    escalation_requested: bool = False
    report_requested: bool = False
    ambiguities: list[str] = field(default_factory=list)
    clarification_needed: bool = False
    engine: str = "deterministic"
    model_call: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "normalized_business_request": self.normalized_business_request,
            "subquestions": list(self.subquestions),
            "requested_actions": list(self.requested_actions),
            "requested_scope": self.requested_scope,
            "requested_entities": list(self.requested_entities),
            "requested_period": self.requested_period,
            "comparison_period": self.comparison_period,
            "inherited_context": dict(self.inherited_context),
            "requested_grouping": self.requested_grouping,
            "requested_layer": self.requested_layer,
            "requested_analysis": self.requested_analysis,
            "requested_analyses": list(self.requested_analyses),
            "requested_evidence": self.requested_evidence,
            "remediation_requested": self.remediation_requested,
            "escalation_requested": self.escalation_requested,
            "report_requested": self.report_requested,
            "ambiguities": list(self.ambiguities),
            "clarification_needed": self.clarification_needed,
            "engine": self.engine,
            "model_call": dict(self.model_call),
        }


# --------------------------------------------------------------- pass one


def _looks_non_english(text: str) -> bool:
    """Whether the question is written in a non-Latin script."""
    return any(ord(ch) > 0x0590 for ch in text or "")


def clean(text: str, *, ledger: budget_mod.Ledger | None = None) -> Cleaned:
    """Pass one. Language only — nothing is resolved and nothing is answered.

    The deterministic reading is computed first and always. Where Sonnet is
    configured it is asked for the same structure and merged onto that floor
    under the checks in `_merge_cleaned`, so a model that is unavailable,
    slow, or wrong costs phrasing rather than the turn.
    """
    floor = _clean_deterministic(text)
    outcome = seam_mod.call(
        seam_mod.PASS_1, system=_PASS_1_SYSTEM,
        prompt=_pass_1_prompt(text or ""), schema=_PASS_1_SCHEMA,
        ledger=ledger)
    if not outcome.used_model:
        floor.model_call = outcome.to_dict()
        return floor
    return _merge_cleaned(floor, outcome)


def _clean_deterministic(text: str) -> Cleaned:
    """The floor: patterns only, and the same answer every time."""
    original = text or ""
    working = _FILLERS.sub(" ", original)
    noticed: list[str] = []
    for pattern, replacement in _CORRECTIONS:
        if re.search(pattern, working, re.I):
            fixed = re.sub(pattern, replacement, working, flags=re.I)
            if fixed != working:
                noticed.append(pattern)
                working = fixed
    # Removing a filler leaves the punctuation that surrounded it. "Um, why
    # has..." becoming ", why has..." is a worse sentence than the one that
    # arrived, so the seams are closed rather than just the fillers removed.
    working = re.sub(r"\s+", " ", working).strip()
    working = re.sub(r"^[\s,;:.]+", "", working)
    working = re.sub(r"\s+([,;:.?!])", r"\1", working)
    working = re.sub(r"([,;:])\s*([,;:.?!])", r"\2", working)
    if working:
        working = working[0].upper() + working[1:]

    translated = _looks_non_english(original)

    # Capitalised runs are the entities a question names. Kept as detected,
    # never resolved: which obligor "Rawabi" means is a question for the
    # domain that holds the obligors, not for a language pass.
    entities = re.findall(r"\b[A-Z][A-Za-z&'-]+(?:\s+[A-Z0-9][A-Za-z0-9&'-]*)*", original)
    entities = [e.strip() for e in entities
                if len(e) > 2 and e.lower() not in ("the", "what", "why", "how",
                                                     "which", "show", "ews")]

    uncertain: list[str] = []
    if _REFERENTIAL.search(original):
        # Recorded, NOT resolved. Pass two has the thread and can resolve it;
        # this pass cannot see the thread and must not guess.
        uncertain.append(
            "The question refers to something already on screen or earlier in "
            "the thread. Left unresolved here on purpose.")

    return Cleaned(
        original_text=original,
        cleaned_english=working or original,
        translation_applied=translated,
        detected_entities=entities[:8],
        uncertainties=uncertain,
        transcription_uncertainties=[f"corrected: {p}" for p in noticed[:5]],
        engine="deterministic",
    )


# ------------------------------------------------- pass one, under Sonnet

_PASS_1_SYSTEM = """You are the language pass of CreditProbe's Early Warning \
assistant. A credit officer has typed or dictated a question about early \
warning signals on a corporate loan book.

Your ONLY job is to return the same question in clean English.

WHAT YOU DO
- Fix spelling, typing slips and speech-to-text noise.
- Translate into English if the question is in another language.
- Remove fillers ("um", "you know") and repair the punctuation they leave.

WHAT YOU MUST NOT DO
- Do not resolve anything. "It", "that one", "the weakest" must come out of \
this pass exactly as vague as they went in. Deciding what "it" refers to is a \
judgement about the conversation, and you cannot see the conversation.
- Do not answer, expand, summarise or add context.
- Do not introduce any number, name, date or period that is not already in the \
question.
- Do not change tense. "Has deteriorated" and "is deteriorating" are different \
questions.

Keep it the same length and the same question. British English."""

_PASS_1_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "cleaned_english": {
            "type": "string",
            "description": "The same question, spelled correctly, in English.",
        },
        "translation_applied": {
            "type": "boolean",
            "description": "True only if the question arrived in another language.",
        },
        "detected_entities": {
            "type": "array", "items": {"type": "string"},
            "description": ("Names the question mentions, copied verbatim. "
                            "Never resolved to an identifier."),
        },
        "uncertainties": {
            "type": "array", "items": {"type": "string"},
            "description": ("Anything left deliberately unresolved, such as a "
                            "pronoun pointing at earlier context."),
        },
        "transcription_uncertainties": {
            "type": "array", "items": {"type": "string"},
            "description": "Words corrected where the correction was a guess.",
        },
    },
    "required": ["cleaned_english", "translation_applied"],
}


def _pass_1_prompt(text: str) -> str:
    import json

    return ("Return this question in clean English.\n\n"
            + json.dumps({"question": text}, indent=2))


_DIGITS = re.compile(r"\d+(?:[.,]\d+)?")


def _invents_a_figure(original: str, rewritten: str) -> bool:
    """Whether the rewrite carries a number the original does not.

    A speller that adds a figure has stopped spelling. Cheap to check and the
    one way a language pass can silently change what is being asked.
    """
    return bool(set(_DIGITS.findall(rewritten or ""))
                - set(_DIGITS.findall(original or "")))


_WORD = re.compile(r"[a-z]{3,}")


def _is_the_same_question(original: str, rewritten: str) -> bool:
    """Whether the rewrite is still the question that arrived.

    A speller returns the same sentence spelled correctly. A pass that
    returned a different sentence entirely — a summary, a generic
    placeholder, an answer — would send every stage after it to work on
    something the reader never asked, and nothing downstream could tell.

    Only checked for a question that arrived in Latin script: a translation
    legitimately shares no words with its original, and the check would
    reject exactly the case pass one exists for.
    """
    if _looks_non_english(original):
        return True
    before = set(_WORD.findall((original or "").lower()))
    if not before:
        return True
    after = set(_WORD.findall((rewritten or "").lower()))
    return len(before & after) * 2 >= len(before)


def _merge_cleaned(floor: Cleaned, outcome: seam_mod.Outcome) -> Cleaned:
    """The model's phrasing on top of the deterministic reading.

    The floor keeps everything that is a judgement rather than a phrasing:
    the referential uncertainty is computed from the ORIGINAL text, so a model
    that quietly resolved "it" cannot also erase the record that "it" was
    there. An entity the original does not contain is dropped rather than
    trusted — pass one detects names, it does not invent them.
    """
    data = outcome.data
    rewritten = str(data.get("cleaned_english") or "").strip()
    text = floor.cleaned_english
    if (rewritten
            and not _invents_a_figure(floor.original_text, rewritten)
            and _is_the_same_question(floor.original_text, rewritten)):
        text = rewritten

    lowered = (floor.original_text or "").lower()
    entities = list(floor.detected_entities)
    for named in data.get("detected_entities") or []:
        name = str(named).strip()
        if name and name.lower() in lowered and name not in entities:
            entities.append(name)

    uncertain = list(floor.uncertainties)
    for note in data.get("uncertainties") or []:
        note = str(note).strip()
        if note and note not in uncertain:
            uncertain.append(note)

    transcription = list(floor.transcription_uncertainties)
    for note in data.get("transcription_uncertainties") or []:
        note = str(note).strip()
        if note and note not in transcription:
            transcription.append(note)

    return Cleaned(
        original_text=floor.original_text,
        cleaned_english=text,
        translation_applied=bool(data.get("translation_applied"))
        or floor.translation_applied,
        detected_entities=entities[:8],
        uncertainties=uncertain[:6],
        transcription_uncertainties=transcription[:6],
        engine=seam_mod.MODEL,
        model_call=outcome.to_dict(),
    )


# --------------------------------------------------------------- pass two

_ACTION_WORDS: tuple[tuple[str, str], ...] = (
    # The VERB, not the noun. "How much exposure sits above the escalation
    # threshold" is a question about the book; reading the bare stem as an
    # instruction planned a workflow action with no obligor attached to it,
    # which produced nothing and answered a portfolio question with an empty
    # result.
    (r"\bescalate\b|\bescalated\b|\bescalating\b|\bescalation note\b|"
     r"\bre-?escalate\b|\bneeds? escalation\b|\brequires? escalation\b|"
     r"\bfor escalation\b|\braise (?:it|this|them) to\b", "escalate"),
    (r"\binform\b|\bnotify\b|\bfyi\b", "inform"),
    (r"\bsave\b.*\binvestigation\b|\bsave this\b", "save_investigation"),
    (r"\breport\b|\bdocx\b|\bdownload\b|\bpublish\b", "report"),
    (r"what should i do|what action|recommend\w*|remediat\w*", "remediate"),
)

_SCOPES: tuple[tuple[str, str], ...] = (
    (r"\bportfolio\b|\bthe book\b|\boverall\b|\bacross the book\b", "portfolio"),
    (r"\bsegment\b", "segment"),
    (r"\bsector\b|\bindustry\b", "sector"),
    (r"\bgrade\b|\brating\b", "rating"),
    (r"\bborrower\b|\bobligor\b|\bcustomer\b|\bname\b", "borrower"),
)

#: What kind of analysis a phrase asks for. EVERY match counts, not the
#: first: "why has it deteriorated over six months, and is it systemic?"
#: asks for a diagnosis AND a movement AND a concentration, and a reader who
#: forces that through one label has answered a third of it and reported the
#: whole. The planner composes steps from the set.
_ANALYSIS: tuple[tuple[str, str], ...] = (
    (r"\bwhy\b|\bwhat (caused|drove)\b|\bdriver\w*\b|\bdriving\b|"
     r"\bin common\b|\bdiagnos\w*|\bdriver tree\b|\bshare\b.*\bdriver",
     "diagnosis"),
    (r"\bmov\w*|\bchang\w*|\bdeteriorat\w*|\bimprov\w*|\btrend\b|"
     r"\bover the last\b|\bsince\b|\brose\b|\bfell\b|\bfallen\b|"
     r"\brisen\b|\bworsen\w*", "movement"),
    (r"\bcompar\w*|\bversus\b|\bvs\b|\bagainst\b", "comparison"),
    (r"\bconcentrat\w*|\bsystemic\b|\bbroad.based\b|\bacross the\b.*"
     r"\b(segment|book|portfolio)\b|\bhandful\b", "concentration"),
    (r"\bhow does the (model|score|matrix|framework)\b|\bexplain\b|"
     r"\bmethodolog\w*|\bhow do the\b|\bwhat is the matrix\b",
     "methodology"),
    (r"\bevidence\b|\bbehind\b|\bshow me the\b|\blineage\b|\bsource\b",
     "evidence"),
    (r"\bgroup\w*\b[^.?]*\bby\b|\bbroken? down by\b|\bsplit by\b|"
     r"\bcut by\b|\bdistribution by\b|\bmix by\b|"
     # "by RISK band" and "by SEVERITY band" name the field in two words, and
     # the single-word alternation below never reached the second one.
     r"\bby (the )?(risk|severity|ews|rating|credit) (band|grade|rating)\b|"
     r"\bby (the )?(internal )?(segment|sector|grade|rating|"
     r"stage|region|band|severity|layer|utilisation|relationship manager)\b|"
     # "Which segments have deteriorated most?" names no "by" and is still a
     # grouping: the reader wants the book cut that way and ranked. Answering
     # it with the portfolio answers a different question entirely.
     r"\bwhich (segments?|sectors?|grades?|ratings?|regions?|stages?|"
     r"bands?|layers?)\b",
     "grouping"),
)

#: How far back a phrase looks. Every spelling a reader uses for the same
#: window, because a window the reader named and the answer did not use is a
#: correct answer to a different question — "why has Contracting deteriorated
#: over six months" was measured over twenty, since only "LAST six months"
#: was recognised and "over six months" fell through to the whole history.
_PERIOD_PHRASES: tuple[tuple[str, int], ...] = (
    (r"(?:last|past|previous|over|within|in) (?:the )?(?:six|6)[ -]months?|"
     r"(?:six|6)[ -]month|half.year|(?:since|from) (?:six|6) months? ago", 6),
    (r"(?:last|past|previous|over|within|in) (?:the )?(?:twelve|12)[ -]months?|"
     r"(?:twelve|12)[ -]month|last year|over the year|"
     r"year[ -]on[ -]year|\byoy\b|(?:since|from) a year ago", 12),
    (r"(?:last|past|previous|over|within|in) (?:the )?(?:three|3)[ -]months?|"
     r"(?:three|3)[ -]month|last quarter|quarter[ -]on[ -]quarter|"
     r"\bqoq\b|since the quarter", 3),
    (r"last month|since last month|month on month|\bmom\b|"
     r"(?:in|over|during) (?:the )?(?:latest|current|last|this) month|"
     r"\bthis month\b|\bsince the last (?:published )?month\b", 1),
)


#: A question about crossing a severity band, rather than about how far a
#: score travelled.
#:
#: The two look alike in English and are different readings: "has it
#: deteriorated?" is a movement, "did it change band?" is a transition. The
#: movement cue below matches "changed" and "moved" too, so this is checked
#: FIRST and leads the analysis list — otherwise "how many obligors changed
#: risk band in the latest month?" is answered with a twenty-month
#: decomposition of the portfolio score, which is what it was.
_BANDS_SAID = (r"very[ -]?high|high|medium|very[ -]?low|low|"
               r"watch ?list|watchlist")

_TRANSITION = re.compile(
    r"\bband (?:change|changes|transition|transitions|movement|movements|"
    r"migration|migrations|shift|shifts)\b|"
    r"\b(?:chang\w+|mov\w+|shift\w+|migrat\w+|transition\w*|cross\w+|"
    r"jump\w*|slip\w*)\s+(?:their |its |the )?"
    r"(?:risk |severity |ews |early warning )?bands?\b|"
    r"\bbands?\s+(?:has |have |had )?(?:chang\w+|mov\w+|shift\w+|"
    r"migrat\w+)\b|"
    r"\b(?:up|down)graded?\b|"
    r"\bmoved? (?:up|down) a band\b|"
    r"\b(?:in)?to (?:the )?watch ?list\b|"
    rf"\b(?:from|out of) (?:{_BANDS_SAID})\b[^.?]{{0,20}}\bto (?:{_BANDS_SAID})\b|"
    rf"\bout of (?:the )?(?:{_BANDS_SAID})\b|"
    r"\b(?:in)?to (?:the )?(?:high or very high|very high or high|"
    r"high and very high|high or above|high\+)\b|"
    r"\bband[- ]transition\w*\b|\bband[- ]migration\w*\b|"
    r"\bmigrations?\b|\btransition matrix\b|"
    rf"\b(?:moved?|migrat\w+|fell|rose|dropped|climbed|slipp\w+|"
    rf"deteriorat\w+|improv\w+|worsen\w+|recover\w+) (?:in)?to "
    rf"(?:{_BANDS_SAID})\b",
    re.I)

_FROM_TO = re.compile(
    rf"\bfrom (?P<a>{_BANDS_SAID})\b[^.?]{{0,20}}?\bto (?P<b>{_BANDS_SAID})\b",
    re.I)

_INTO = re.compile(rf"\b(?:in)?to (?:the )?(?P<b>{_BANDS_SAID})\b", re.I)
_OUT_OF = re.compile(rf"\bout of (?:the )?(?P<a>{_BANDS_SAID})\b", re.I)

_IMPROVED = re.compile(
    r"\bimprov\w+|\bupgrad\w+|\bbetter\b|\brecover\w+|\bstrengthen\w+",
    re.I)
_WORSENED = re.compile(
    r"\bdeteriorat\w+|\bdowngrad\w+|\bworse\w*|\bweaken\w+|"
    r"\bslipp\w+|\bfell into\b", re.I)


def _canonical_band(said: str) -> str:
    """A band as the reader says it, under the name the data stores it."""
    text = re.sub(r"[\s-]+", "_", str(said or "").strip().lower())
    if text in ("watchlist", "watch_list"):
        return ""
    return text.upper() if text.upper() in (
        "VERY_HIGH", "HIGH", "MEDIUM", "LOW", "VERY_LOW") else ""


#: "into High or Very High" and "out of High or Very High" name the
#: watchlist threshold, which is a PAIR of bands rather than one. It is the
#: crossing credit officers actually ask about, and reading it as "Very High"
#: alone — which is what matching one band out of the phrase does — answers
#: about a fifth of the names.
_INTO_HIGH_PLUS = re.compile(
    r"\b(?:in)?to (?:the )?(?:high or very high|very high or high|"
    r"high and very high|high or above|high\+|watch ?list)\b", re.I)
_OUT_OF_HIGH_PLUS = re.compile(
    r"\b(?:out of|below|off) (?:the )?(?:high or very high|"
    r"very high or high|high and very high|high or above|high\+|"
    r"watch ?list)\b", re.I)

#: The pair, under one name the fact builder understands.
HIGH_PLUS = "HIGH_PLUS"


def _band_move(text: str) -> dict[str, str]:
    """Which cell of the transition matrix the question asked to see.

    Empty where it asked for all of them, which is the common case: "how
    many obligors changed band?" wants the counts, not one cell.
    """
    out: dict[str, str] = {}
    if _INTO_HIGH_PLUS.search(text):
        out["to_band"] = HIGH_PLUS
        out.setdefault("direction", "deteriorated")
        return out
    if _OUT_OF_HIGH_PLUS.search(text):
        out["from_band"] = HIGH_PLUS
        out.setdefault("direction", "improved")
        return out
    pair = _FROM_TO.search(text)
    if pair:
        out["from_band"] = _canonical_band(pair.group("a"))
        out["to_band"] = _canonical_band(pair.group("b"))
    else:
        leaving = _OUT_OF.search(text)
        if leaving:
            out["from_band"] = _canonical_band(leaving.group("a"))
        arriving = _INTO.search(text)
        if arriving:
            out["to_band"] = _canonical_band(arriving.group("b"))
    # A question that asks for BOTH directions has no direction. "How many
    # were upgraded and how many downgraded?" matches the worsening cue and
    # would come back as half the answer.
    worse, better = bool(_WORSENED.search(text)), bool(_IMPROVED.search(text))
    if worse and not better:
        out["direction"] = "deteriorated"
    elif better and not worse:
        out["direction"] = "improved"
    return {k: v for k, v in out.items() if v}


#: Whether the question asks about corroboration, and which way.
#:
#: "L3 warnings but weak internal corroboration" is two conditions, and a
#: reader who is given the first without the second has been handed a longer
#: list than the one they asked for and no way to see which half is theirs.
#: The concepts are the credit book's own — a signal nothing else echoes is
#: uncorroborated; a signal several layers agree on is corroborated.
_UNCORROBORATED = re.compile(
    r"\b(?:un|not |without |no |weak(?:ly)? |poor(?:ly)? |little |lacking |"
    r"absent |thin )\s*"
    r"(?:internal(?:ly)?\s+)?corroborat\w*|"
    r"\bcorroborat\w*\s+(?:is\s+)?(?:weak|absent|missing|lacking|poor)\b|"
    r"\bsingle[- ]source\b|\bone source only\b|"
    r"\bnothing (?:else|internal)\b|\bunsupported by\b", re.I)

_CORROBORATED = re.compile(
    r"\b(?:well[- ])?corroborat\w*\b|\bcross[- ]confirmed\b|"
    r"\bconfirmed (?:by|across) (?:another|other|several|multiple)\b|"
    r"\bmore than one layer\b|\bmultiple layers\b", re.I)


def _corroboration(text: str) -> str:
    """"weak", "strong" or nothing. Weak wins: "not corroborated" contains
    the word "corroborated", and reading it as the positive would answer the
    exact opposite of the question."""
    if _UNCORROBORATED.search(text):
        return "weak"
    if _CORROBORATED.search(text):
        return "strong"
    return ""


#: "Which names drive it?" — a request to see INTO the current scope.
#:
#: Every ordinary way of asking for a list, not three of them. "Show the 10
#: obligors whose score has risen the most" is a request for ten names and
#: was read as a movement question, so it came back as one number for the
#: whole population and no names at all.
_WANTS_NAMES = re.compile(
    # "Which CONTRACTING names" is the same request as "which names", and
    # the qualifier between the two words is usually the population the
    # reader means.
    r"\bwhich(?:\s+[A-Za-z&'-]+){0,2}\s+"
    r"(names?|borrowers?|obligors?|customers?|entit\w+|accounts?|"
    r"exposures?)\b|\bwho\b|"
    r"\b(?:show|list|give|name|display|return|fetch|pull)\b"
    r"(?:\s+me)?(?:\s+the)?(?:\s+top)?(?:\s+\d{1,3})?\s+"
    r"(names?|borrowers?|obligors?|customers?|entit\w+|accounts?|exposures?)\b|"
    r"\bthe (?:top|first|worst|weakest)\s+\d{1,3}\b|"
    # "Which two of those worsened fastest?" asks for two names out of a
    # population the thread already established. It is the commonest
    # follow-up there is, and it was read as a movement question.
    r"\bwhich (?:two|three|four|five|\d{1,3}|few)\b|"
    r"\b(?:of|among|from) (?:those|them|these|that list|the list)\b|"
    r"\bdriv\w* it\b|\bdriving it\b", re.I)

#: A question that names the population it is about. Not a filter word — a
#: population word: "obligors", "the book", "the portfolio".
_STATES_A_POPULATION = re.compile(
    r"\b(?:all |every |the )?(?:obligors?|borrowers?|customers?|names?|"
    r"book|portfolio|population)\b", re.I)

#: The inherited keys that NARROW a population rather than identify a
#: subject. A carried sector is usually still what the reader means; a
#: carried severity band usually is not, because bands are how a reader
#: slices rather than what they are looking at.
_NARROWING: frozenset[str] = frozenset({"band", "level"})

#: "Open the weakest one" — a request to resolve one obligor from that scope.
_WANTS_WEAKEST = re.compile(
    r"\b(open|show|take|drill into)\b[^.?]*\b(the )?(weakest|worst|"
    r"first|top|riskiest|highest)\b|\bthe (weakest|worst|riskiest) one\b",
    re.I)


def _named_group(text: str) -> dict[str, str] | None:
    """The segment, sector or region the question names, if it names one."""
    try:
        from backend.early_warning import ask as ask_mod

        found = ask_mod.resolve_group(text)
        if not found:
            return None
        field, value = found
        return {"field": field, "value": str(value)}
    except Exception:  # noqa: BLE001 - a resolver failure must not lose the turn
        return None


def _weakest_in(scope: dict[str, Any]) -> dict[str, str] | None:
    """The highest-scoring obligor in whatever the thread is looking at.

    Scoped, not global: "open the weakest one" after a Contracting question
    means the weakest in Contracting, and returning the weakest in the book
    would silently change the subject.
    """
    try:
        from backend.early_warning import v2_service as svc

        frame = svc.borrower_month()
        for field in ("segment", "sector", "region", "internal_rating"):
            value = scope.get(field)
            if value:
                frame = frame[frame[field].astype(str).str.lower()
                              == str(value).lower()]
        if frame.empty:
            return None
        row = frame.sort_values("ews_score", ascending=False).iloc[0]
        return {"customer_id": str(row["customer_id"]),
                "customer_name": str(row["customer_name"])}
    except Exception:  # noqa: BLE001
        return None


def _ambiguous_obligors(text: str, limit: int = 12) -> list[dict[str, Any]]:
    """Obligors a name fragment matches, when it matches more than one.

    Only a fragment of at least two characters that reaches a real name.
    A single letter matches half the book and is not a name anybody typed.
    """
    try:
        from backend.early_warning import ask as ask_mod

        found = ask_mod.candidates(text)
    except Exception:  # noqa: BLE001 - an unreadable domain names nobody
        return []
    if len(found) < 2:
        return []
    matched = str(found[0].get("matched") or "")
    # Two characters is the shortest fragment that can be a name in this
    # book — "Al" prefixes a great many of them. One is not a name anybody
    # typed, it is a letter.
    if len(matched.replace(" ", "")) < 2:
        return []
    return [{"customer_id": c["customer_id"],
             "customer_name": c["customer_name"],
             "ews_score": c.get("ews_score"), "ews_band": c.get("ews_band"),
             "exposure": c.get("exposure"), "matched": matched,
             "total": len(found)}
            for c in found[:limit]]


def _named_obligor(text: str) -> dict[str, str] | None:
    """The obligor the question names, if it names exactly one.

    Delegated to the domain's own resolver rather than reimplemented: it
    already knows how a reader refers to an obligor — by full name, by a
    distinctive part of one, or by position ("the weakest borrower") — and
    two resolvers that disagree would be worse than one that is imperfect.

    Several matches resolve to nothing here on purpose. The ambiguity is a
    question for the answer layer to put back to the reader, not something
    to settle silently inside a normalisation pass.
    """
    try:
        from backend.early_warning import ask as ask_mod
        from backend.early_warning import v2_service as svc

        found = ask_mod.resolve_borrower(text)
        if not found:
            return None
        frame = svc.borrower_month()
        row = frame[frame["customer_id"] == found]
        if row.empty:
            return None
        return {"customer_id": str(found),
                "customer_name": str(row.iloc[0]["customer_name"])}
    except Exception:  # noqa: BLE001 - a resolver failure must not lose the turn
        return None


def _subquestions(text: str) -> list[str]:
    """Every question the utterance contains, not just the first.

    A request that asks two things and is answered on one has not been
    answered; it has been half-answered and reported as complete. The
    sufficiency review needs each part separately to be able to say so.
    """
    parts = re.split(r"(?<=[?.])\s+|\s+\band\b\s+(?=(?:is|are|which|what|why|"
                     r"how|does|do|did|show|explain)\b)|;\s*", text or "")
    found = [p.strip(" ,;") for p in parts if p and len(p.strip()) > 8]
    return found if len(found) > 1 else ([text.strip()] if text.strip() else [])


def read(cleaned: Cleaned, *, ui_state: dict[str, Any] | None = None,
          rolling_summary: dict[str, Any] | None = None,
          recent: list[dict[str, Any]] | None = None,
          ledger: budget_mod.Ledger | None = None) -> BusinessRequest:
    """Pass two. What is being asked, with the thread and the screen in view.

    The deterministic reading runs first and is what the model is merged onto.
    Which obligor, which sector and which period stay the domain's answers —
    they are resolved against the published data, and a model that named one
    the data does not hold would be inventing the subject of the answer.
    """
    floor = _read_deterministic(cleaned, ui_state=ui_state,
                               rolling_summary=rolling_summary, recent=recent)
    outcome = seam_mod.call(
        seam_mod.PASS_2, system=_PASS_2_SYSTEM,
        prompt=_pass_2_prompt(cleaned, floor, ui_state, rolling_summary,
                              recent),
        schema=_PASS_2_SCHEMA, ledger=ledger)
    if not outcome.used_model:
        floor.model_call = outcome.to_dict()
        return floor
    return _merge_request(floor, outcome)


def _read_deterministic(
        cleaned: Cleaned, *, ui_state: dict[str, Any] | None = None,
        rolling_summary: dict[str, Any] | None = None,
        recent: list[dict[str, Any]] | None = None) -> BusinessRequest:
    """The floor: patterns, the screen and the thread."""
    text = cleaned.cleaned_english
    lowered = text.lower()
    ui = dict(ui_state or {})
    summary = dict(rolling_summary or {})

    actions = [name for pattern, name in _ACTION_WORDS
               if re.search(pattern, lowered)]
    scope = next((name for pattern, name in _SCOPES
                  if re.search(pattern, lowered)), "")
    analyses = [name for pattern, name in _ANALYSIS
                if re.search(pattern, lowered)]
    # The leading one is what the answer is chiefly about; the rest are the
    # parts a one-label reading would have dropped.
    analysis = analyses[0] if analyses else ""
    grouping = ""
    if "grouping" in analyses:
        grouped = re.search(
            r"\bby (?:the )?((?:internal |ifrs ?9 )?\w+(?: \w+)?)", lowered)
        if grouped:
            # The phrase can run past the field: "by sector for obligors at
            # High" captured "sector for", which resolves to nothing, so the
            # grouping was dropped and the question was answered at population
            # level instead — the reader asked for a cut of the book and got
            # the book.
            #
            # Two words are needed for "internal rating" and "dominant layer",
            # so the length cannot simply be one. The governed registry
            # arbitrates instead of the regex guessing: the longest prefix
            # that IS a grouping wins, and a phrase that is not one at any
            # length falls through to the message below rather than being
            # passed on as if it were a field.
            grouping = _longest_grouping(grouped.group(1).strip())
        if not grouping:
            # The "which segments..." form names the grouping as its subject
            # rather than after a "by".
            plural = re.search(
                r"\bwhich (segments?|sectors?|grades?|ratings?|regions?|"
                r"stages?|bands?|layers?)\b", lowered)
            if plural:
                grouping = plural.group(1).rstrip("s")

    comparison = ""
    for pattern, months in _PERIOD_PHRASES:
        if re.search(pattern, lowered):
            comparison = f"-{months}m"
            break

    # What the screen and the thread supply that the sentence does not. This
    # is where "it" becomes an obligor: the reference was RECORDED in pass
    # one and is RESOLVED here, because here is where the context exists.
    inherited: dict[str, Any] = {}
    referential = bool(_REFERENTIAL.search(text))
    # A question that names its own population is not asking about the last
    # one. The SCREEN's filters persist — the reader is looking at them — but
    # a severity band carried from three turns ago is a stale filter, and it
    # is exactly the kind that produces a confident answer to a narrower
    # question than the one typed: "how many obligors changed risk band in
    # the latest month?" came back as "all 52 held their band", because 52
    # was the high-risk population an earlier turn had been about.
    states_its_own = bool(_STATES_A_POPULATION.search(text)) and not referential
    for key in ("customer_id", "customer_name", "segment", "sector", "region",
                "internal_rating", "period", "band", "level", "layer",
                "sub_category", "signal"):
        from_screen = ui.get(key)
        from_thread = summary.get(key)
        if from_screen:
            inherited[key] = from_screen
        elif from_thread and not (states_its_own and key in _NARROWING):
            inherited[key] = from_thread

    entities = list(cleaned.detected_entities)
    if referential and inherited.get("customer_name"):
        entities.append(str(inherited["customer_name"]))

    # An obligor NAMED in the question outranks one carried from the screen:
    # a reader who typed a name is asking about that name, whatever they were
    # looking at. Resolved against this domain's own obligors, which is the
    # only place that knows which names exist.
    # A name FRAGMENT that matches several obligors is a question back, not
    # a guess — and not a reason to answer about the whole book either.
    # "Show me Al Rabia" returned the portfolio summary: the fragment
    # resolved to nobody, nothing recorded that it had failed, and the
    # planner fell through to the population as though no name had been
    # typed at all.
    ambiguous_names: list[dict[str, Any]] = []
    named = _named_obligor(text)
    if not named and not inherited.get("customer_id"):
        ambiguous_names = _ambiguous_obligors(text)
    if named:
        inherited["customer_id"] = named["customer_id"]
        inherited["customer_name"] = named["customer_name"]
        if named["customer_name"] not in entities:
            entities.append(named["customer_name"])

    # A GROUP named in the question does the same thing at population level:
    # "how is the Contracting sector doing?" is about Contracting, and
    # answering it with the whole book answers a different question. Resolved
    # against the domain's own values, so a sector that does not exist stays
    # unresolved rather than being invented.
    group = _named_group(text)
    if group and not named:
        inherited[group["field"]] = group["value"]
        if group["value"] not in entities:
            entities.append(group["value"])

    # A SEVERITY BAND named in the question is a filter on the population,
    # exactly as it is when the reader sets it on the screen.
    #
    # Without this, "show exposure by sector for obligors at High or Very
    # High" was answered for every obligor in every sector. The answer was
    # arithmetically right and about a different question, which is the worst
    # kind of wrong: nothing on screen says the filter was dropped.
    band = _named_band(text)
    if band and not inherited.get("band"):
        inherited["band"] = band

    # The DETECTION LAYER the question names, resolved through the governed
    # layer registry rather than by looking for one spelling of one word.
    #
    # Without this, "which obligors carry external-intelligence warning
    # signals?" was read as an ordinary ranking and answered with the
    # portfolio's largest high-risk names: a correct answer to a question
    # about severity, put to a question about where the risk was detected.
    # A layer NAMED in the question outranks one carried from the screen, for
    # the same reason a named obligor does.
    layer = layers_mod.resolve(text) or str(inherited.get("layer") or "")
    if layer:
        inherited["layer"] = layer

    corroboration = _corroboration(text)
    if corroboration:
        inherited["corroboration"] = corroboration

    # A band transition leads the reading when the sentence asks for one.
    # The movement cue matches the same verbs, so without this the more
    # general reading wins and answers a question one step out from the one
    # that was typed.
    if _TRANSITION.search(text):
        if "transition" in analyses:
            analyses.remove("transition")
        analyses.insert(0, "transition")
        analysis = "transition"
        move = _band_move(text)
        if move:
            inherited["band_move"] = move
            # The bands in "from High to Very High" are the ENDPOINTS of the
            # transition, not a filter on the population. Left in place they
            # narrow both months to one band, and the from-band side of the
            # question disappears.
            inherited.pop("band", None)
            inherited.pop("ews_band", None)

    # "Open the weakest one" and "which names drive it" both point INTO the
    # current scope rather than away from it. Recorded so the planner can
    # rank within whatever the thread is already about.
    wants_names = bool(_WANTS_NAMES.search(text))
    wants_weakest = bool(_WANTS_WEAKEST.search(text))

    ambiguities: list[str] = []
    if ambiguous_names:
        shown = ", ".join(str(c["customer_name"]) for c in ambiguous_names[:6])
        total = ambiguous_names[0].get("total", len(ambiguous_names))
        more = int(total) - 6
        ambiguities.append(
            f"{total} obligors match "
            f"{ambiguous_names[0]['matched']!r}: {shown}"
            + (f", and {more} more — name one, or add a word to narrow it."
               if more > 0 else "."))
    if referential and not inherited:
        ambiguities.append(
            "The question points at something — 'it', 'that', 'the weakest "
            "one' — and neither the screen nor the thread says what.")

    # Opening the weakest name in the current scope resolves it to an
    # obligor, which is what makes the next turn's "why did ITS score move?"
    # answerable at all.
    if wants_weakest and not inherited.get("customer_id"):
        weakest = _weakest_in(inherited)
        if weakest:
            inherited.update(weakest)
            entities.append(weakest["customer_name"])

    if wants_names and "ranking" not in analyses:
        analyses.insert(0, "ranking")

    return BusinessRequest(
        normalized_business_request=text,
        subquestions=_subquestions(text),
        requested_actions=actions,
        requested_scope=scope or ("borrower" if inherited.get("customer_id")
                                   else "portfolio"),
        requested_entities=entities[:8],
        requested_period=str(ui.get("period") or summary.get("period") or ""),
        comparison_period=comparison,
        inherited_context=inherited,
        requested_grouping=grouping,
        requested_layer=layer,
        requested_analysis=analysis,
        requested_analyses=analyses,
        requested_evidence=analysis == "evidence" or "evidence" in lowered,
        remediation_requested="remediate" in actions,
        escalation_requested="escalate" in actions or "inform" in actions,
        report_requested="report" in actions,
        ambiguities=ambiguities,
        ambiguous_obligors=ambiguous_names,
        clarification_needed=bool(ambiguities),
        engine="deterministic",
    )


# ------------------------------------------------- pass two, under Sonnet

_PASS_2_SYSTEM = """You are the request-reading pass of CreditProbe's Early \
Warning assistant. A credit officer has asked a question about early warning \
signals on a corporate loan book. A deterministic reader has already produced \
a first reading; you are given it, the thread summary and the screen state.

Your job is to say what is being asked — every part of it.

WHAT MATTERS MOST
A request that asks two things and is answered on one has not been answered; \
it has been half-answered and reported as complete. "Why has Contracting \
deteriorated and is it broad across the segment?" asks for a diagnosis AND a \
concentration. List every part.

RULES
- Never drop a part the first reading found. You may add parts it missed.
- Never resolve an entity. Which obligor "the weakest one" means is decided \
against the published data, not by you. Leave `requested_entities` to the \
first reading.
- Only use a period that appears in the published periods you are given.
- Only use a grouping field from the list you are given.
- Say plainly what is genuinely unclear. A pronoun with nothing behind it is \
an ambiguity, not something to guess at.
- Do not answer the question."""

#: What pass two may say a request asks for. Closed, because a label the
#: planner has no step for is a part the sufficiency review would then report
#: as permanently uncovered.
_ANALYSIS_LABELS: tuple[str, ...] = (
    "diagnosis", "movement", "transition", "comparison", "concentration",
    "methodology", "evidence", "grouping", "ranking")
_SCOPE_LABELS: tuple[str, ...] = (
    "portfolio", "segment", "sector", "rating", "borrower", "group")
_ACTION_LABELS: tuple[str, ...] = (
    "escalate", "inform", "save_investigation", "report", "remediate")

_PASS_2_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "normalized_business_request": {
            "type": "string",
            "description": ("The request in one plain sentence, with any "
                            "pronoun replaced by what the thread says it "
                            "refers to."),
        },
        "subquestions": {
            "type": "array", "items": {"type": "string"},
            "description": "Every distinct question the request contains.",
        },
        "requested_analyses": {
            "type": "array",
            "items": {"type": "string", "enum": list(_ANALYSIS_LABELS)},
            "description": "Every kind of analysis the request asks for.",
        },
        "requested_scope": {
            "type": "string", "enum": list(_SCOPE_LABELS) + [""],
            "description": "The population the answer is about.",
        },
        "requested_actions": {
            "type": "array",
            "items": {"type": "string", "enum": list(_ACTION_LABELS)},
        },
        "requested_grouping": {
            "type": "string",
            "description": ("The field the answer should be cut by, or empty. "
                            "Only a field from the grouping list."),
        },
        "requested_layer": {
            "type": "string", "enum": list(layers_mod.CODES) + [""],
            "description": ("The detection layer the question is about, if "
                            "it names one — L1 internal behavioural, L2 "
                            "credit and financial fundamentals, L3 external "
                            "intelligence, L4 network. Empty when the "
                            "question is about the score overall."),
        },
        "requested_period": {
            "type": "string",
            "description": "A published period, or empty.",
        },
        "comparison_period": {
            "type": "string",
            "description": ("A published period or a relative offset such as "
                            "-6m, or empty."),
        },
        "requested_evidence": {"type": "boolean"},
        "ambiguities": {
            "type": "array", "items": {"type": "string"},
            "description": "What is genuinely unclear, in the reader's terms.",
        },
        "clarification_needed": {"type": "boolean"},
    },
    "required": ["normalized_business_request", "requested_analyses"],
}

_OFFSET = re.compile(r"^-\d{1,2}m$")


def _published_periods() -> list[str]:
    try:
        from backend.early_warning import v2_service as svc

        return [str(p) for p in svc.periods()]
    except Exception:  # noqa: BLE001 - an unreadable domain offers none
        return []


#: The severity bands, as a reader writes them. "High or above" and "high+"
#: are the same filter said two other ways.
_HIGH_PLUS = re.compile(
    r"\b(?:high or very high|very high or high|high and very high|"
    r"high or above|high\+|at high or above)\b", re.I)


def _named_band(text: str) -> str:
    """The COMPOUND severity filter a question names, or "".

    Only the compound. A single band — "at Very High", "the Medium names" —
    is already resolved by `_named_group`, which checks it against the
    domain's own band values and records it under its canonical column; doing
    it twice here would be a second resolver for one thing, and the two would
    eventually disagree.

    "High or Very High" is the case that resolver cannot express, because it
    is two values and no single column value means both. It is returned as
    `high_plus`, which is the name the executor already knows it by.
    """
    return "high_plus" if _HIGH_PLUS.search(text or "") else ""


def _longest_grouping(phrase: str) -> str:
    """The longest leading part of `phrase` that names a real grouping."""
    from backend.early_warning import executable as ex

    words = [w for w in phrase.split() if w]
    for size in range(len(words), 0, -1):
        candidate = " ".join(words[:size])
        if ex.supports(ex.normalise(candidate, role=ex.GROUP_BY),
                       role=ex.GROUP_BY):
            return candidate
    return ""


def _grouping_fields() -> list[str]:
    try:
        from backend.early_warning import grain as grain_mod

        return sorted(grain_mod.GROUPINGS)
    except Exception:  # noqa: BLE001
        return []


def _pass_2_prompt(cleaned: Cleaned, floor: BusinessRequest,
                   ui_state: dict[str, Any] | None,
                   rolling_summary: dict[str, Any] | None,
                   recent: list[dict[str, Any]] | None) -> str:
    """The stage's own inputs, and nothing else.

    No data. Pass two decides what is being asked; the values come back later
    through validated execution, where they can be checked against what was
    actually run.
    """
    import json

    periods = _published_periods()
    context = {
        "question": cleaned.cleaned_english,
        "language_pass_uncertainties": list(cleaned.uncertainties),
        "screen_state": dict(ui_state or {}),
        "thread_summary": dict(rolling_summary or {}),
        "recent_turns": [
            {"question": str(t.get("question", ""))[:200],
             "answer": str(t.get("answer", ""))[:280]}
            for t in (recent or [])[-3:]],
        "first_reading": floor.to_dict(),
        "published_periods": periods[-24:],
        "grouping_fields": _grouping_fields(),
        "analysis_labels": list(_ANALYSIS_LABELS),
        "detection_layers": [{"code": entry.code, "name": entry.name}
                             for entry in layers_mod.LAYERS],
    }
    return ("Read this Early Warning request.\n\n"
            + json.dumps(context, indent=2, default=str))


def _merge_request(floor: BusinessRequest,
                   outcome: seam_mod.Outcome) -> BusinessRequest:
    """The model's reading on top of the deterministic one.

    Union on the parts, because the failure this pass exists to prevent is a
    dropped part; a validated allow-list on everything that names a field, a
    period or an obligor, because those are facts about the domain rather than
    readings of the sentence.
    """
    data = outcome.data
    periods = set(_published_periods())
    groupings = set(_grouping_fields())

    analyses = list(floor.requested_analyses)
    for label in data.get("requested_analyses") or []:
        label = str(label)
        if label in _ANALYSIS_LABELS and label not in analyses:
            analyses.append(label)
    analyses = analyses[:4]

    actions = list(floor.requested_actions)
    for label in data.get("requested_actions") or []:
        label = str(label)
        if label in _ACTION_LABELS and label not in actions:
            actions.append(label)

    subquestions = [str(q).strip() for q in (data.get("subquestions") or [])
                    if str(q).strip()]
    if len(subquestions) < len(floor.subquestions):
        subquestions = list(floor.subquestions)

    request_text = str(data.get("normalized_business_request") or "").strip()
    if not request_text or _invents_a_figure(floor.normalized_business_request,
                                             request_text):
        request_text = floor.normalized_business_request

    grouping = str(data.get("requested_grouping") or "").strip()
    if grouping not in groupings:
        grouping = floor.requested_grouping

    period = str(data.get("requested_period") or "").strip()
    if period not in periods:
        period = floor.requested_period

    comparison = str(data.get("comparison_period") or "").strip()
    if comparison not in periods and not _OFFSET.match(comparison):
        comparison = floor.comparison_period

    scope = str(data.get("requested_scope") or "").strip()
    if scope not in _SCOPE_LABELS:
        scope = floor.requested_scope

    # A layer the model names is checked against the registry, like every
    # other name of a thing in the domain. It may add one the patterns missed;
    # it cannot unset one they found, because the patterns read the sentence
    # and the model reads its own summary of it.
    layer = str(data.get("requested_layer") or "").strip().upper()
    if not layers_mod.is_code(layer):
        layer = floor.requested_layer

    ambiguities = list(floor.ambiguities)
    for note in data.get("ambiguities") or []:
        note = str(note).strip()
        if note and note not in ambiguities:
            ambiguities.append(note)

    return BusinessRequest(
        normalized_business_request=request_text,
        subquestions=subquestions or list(floor.subquestions),
        requested_actions=actions,
        requested_scope=scope,
        # Entity resolution is the domain's answer, never the model's.
        requested_entities=list(floor.requested_entities),
        requested_period=period,
        comparison_period=comparison,
        inherited_context={**dict(floor.inherited_context),
                            **({"layer": layer} if layer else {})},
        ambiguous_obligors=list(floor.ambiguous_obligors),
        requested_grouping=grouping,
        requested_layer=layer,
        requested_analysis=(analyses[0] if analyses
                            else floor.requested_analysis),
        requested_analyses=analyses,
        requested_evidence=bool(data.get("requested_evidence"))
        or floor.requested_evidence,
        remediation_requested="remediate" in actions,
        escalation_requested="escalate" in actions or "inform" in actions,
        report_requested="report" in actions,
        ambiguities=ambiguities[:6],
        # Tightening only: the model may notice an ambiguity the patterns
        # missed, and may not wave away one they found.
        clarification_needed=bool(data.get("clarification_needed"))
        or floor.clarification_needed,
        engine=seam_mod.MODEL,
        model_call=outcome.to_dict(),
    )


__all__ = ["BusinessRequest", "Cleaned", "clean", "read"]
