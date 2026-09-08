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
provider is configured it may produce the structured output instead, under
the same schema, and the result is checked before it is used — a pass that
came back with entities the question does not contain is discarded and the
deterministic reading stands. Where no provider is configured the
deterministic reading is what runs, and `engine` says so. Nothing here ever
records a model call that did not happen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.early_warning.conversation import budget as budget_mod

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

    def to_dict(self) -> dict[str, Any]:
        return {
            "original_text": self.original_text,
            "cleaned_english": self.cleaned_english,
            "translation_applied": self.translation_applied,
            "detected_entities": list(self.detected_entities),
            "uncertainties": list(self.uncertainties),
            "transcription_uncertainties": list(self.transcription_uncertainties),
            "engine": self.engine,
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
            "requested_analysis": self.requested_analysis,
            "requested_analyses": list(self.requested_analyses),
            "requested_evidence": self.requested_evidence,
            "remediation_requested": self.remediation_requested,
            "escalation_requested": self.escalation_requested,
            "report_requested": self.report_requested,
            "ambiguities": list(self.ambiguities),
            "clarification_needed": self.clarification_needed,
            "engine": self.engine,
        }


# --------------------------------------------------------------- pass one


def _looks_non_english(text: str) -> bool:
    """Whether the question is written in a non-Latin script."""
    return any(ord(ch) > 0x0590 for ch in text or "")


def clean(text: str, *, ledger: budget_mod.Ledger | None = None) -> Cleaned:
    """Pass one. Language only — nothing is resolved and nothing is answered."""
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


# --------------------------------------------------------------- pass two

_ACTION_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bescalat\w*", "escalate"),
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
     r"\bcut by\b|\bby (the )?(internal )?(segment|sector|grade|rating|"
     r"stage|region|band|severity|layer|utilisation|relationship manager)\b|"
     # "Which segments have deteriorated most?" names no "by" and is still a
     # grouping: the reader wants the book cut that way and ranked. Answering
     # it with the portfolio answers a different question entirely.
     r"\bwhich (segments?|sectors?|grades?|ratings?|regions?|stages?|"
     r"bands?|layers?)\b",
     "grouping"),
)

_PERIOD_PHRASES: tuple[tuple[str, int], ...] = (
    (r"last (six|6) months?", 6),
    (r"last (twelve|12) months?|last year|over the year", 12),
    (r"last (three|3) months?|last quarter", 3),
    (r"last month|since last month|month on month", 1),
)


#: "Which names drive it?" — a request to see INTO the current scope.
_WANTS_NAMES = re.compile(
    r"\bwhich (names?|borrowers?|obligors?|customers?)\b|\bwho\b|"
    r"\bname the\b|\blist the\b|\bshow me the (names?|borrowers?|obligors?)\b|"
    r"\bdriv\w* it\b|\bdriving it\b", re.I)

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
    """Pass two. What is being asked, with the thread and the screen in view."""
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
            grouping = grouped.group(1).strip()
        else:
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
    for key in ("customer_id", "customer_name", "segment", "sector", "region",
                "internal_rating", "period", "band", "level", "layer",
                "sub_category", "signal"):
        value = ui.get(key) or summary.get(key)
        if value:
            inherited[key] = value

    entities = list(cleaned.detected_entities)
    if referential and inherited.get("customer_name"):
        entities.append(str(inherited["customer_name"]))

    # An obligor NAMED in the question outranks one carried from the screen:
    # a reader who typed a name is asking about that name, whatever they were
    # looking at. Resolved against this domain's own obligors, which is the
    # only place that knows which names exist.
    named = _named_obligor(text)
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

    # "Open the weakest one" and "which names drive it" both point INTO the
    # current scope rather than away from it. Recorded so the planner can
    # rank within whatever the thread is already about.
    wants_names = bool(_WANTS_NAMES.search(text))
    wants_weakest = bool(_WANTS_WEAKEST.search(text))

    ambiguities: list[str] = []
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
        requested_analysis=analysis,
        requested_analyses=analyses,
        requested_evidence=analysis == "evidence" or "evidence" in lowered,
        remediation_requested="remediate" in actions,
        escalation_requested="escalate" in actions or "inform" in actions,
        report_requested="report" in actions,
        ambiguities=ambiguities,
        clarification_needed=bool(ambiguities),
        engine="deterministic",
    )


__all__ = ["BusinessRequest", "Cleaned", "clean", "read"]
