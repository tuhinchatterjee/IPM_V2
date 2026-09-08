"""
Answering an Early Warning question.

Why this exists at all
----------------------
Nothing else could answer one. An Early Warning question reaching the
general planner was checked against the credit book's customer master,
failed to find the obligor there, and came back "CreditProbe could not find
that borrower in the published data" — accurate about the book it looked in,
and useless, because the borrower is in the Early Warning domain and that is
where the question was asked. The domain lock already guarantees an Early
Warning thread reads only Early Warning datasets; this is the reader that
knows what to do inside them.

Reading the question without a model
------------------------------------
No provider is configured in this deployment, and a question family this
bounded does not need one. There are a dozen things a reader asks of an
early warning screen — how the book looks, how it looks grouped by
something, how one group or one obligor looks, why a score moved, what sits
behind a node, what to do, whom to tell, how the model works — and each maps
to a fact scope. So intent is matched deterministically here, entities are
resolved against the Early Warning domain's own names, and the answer is
composed from the facts. When a provider IS configured the same facts become
its grounding, and the deterministic reading stands if the model declines or
strays.

What it will not do
-------------------
It will not change a score: the assistant explains and navigates, and
overrides go through the documented override path where they are counted as
a control. It will not close a case: the chat layer proposes and the
escalation matrix decides. Asked for either, it says so and offers the route
that does exist.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.early_warning import compose as cp
from backend.early_warning import facts as ff
from backend.early_warning import v2_service as svc

#: Words that mean the reader wants the whole book.
_PORTFOLIO = ("portfolio", "the book", "overall", "in total", "across the book")

#: What makes a question one this domain should answer at all. Without this
#: gate the portfolio fallback would answer every unrecognised question with
#: a portfolio summary, including questions about other domains entirely.
_ABOUT_EARLY_WARNING = re.compile(
    r"\b(early warning|ews\b|portfolio|the book|watchlist|severity|"
    r"high.risk|risk score|deteriorat\w*|obligor\w*|borrower\w*|"
    r"layer [1-4]|classifier|trigger\w*|score\w*|exposure|weakest)", re.I)

#: An intent to look at something, which makes naming a group a request to
#: open it. "How is Riyadh looking?" asks for the region; "What is the
#: weather in Riyadh?" names the same region and asks for something else
#: entirely, and answering it with that region's early warning position
#: would be answering a different question.
_LOOK_AT = re.compile(
    r"\b(how (is|are|does|did)|show|open|tell me about|what about|"
    r"look at|which|drill)\b", re.I)

#: Question shapes, in the order they are tested. Order matters: "what should
#: I do about X" is an action question before it is a question about X.
_REFUSE_SCORE_CHANGE = re.compile(
    r"\b(change|override|set|adjust|raise|lower|reduce|increase)\b[^.?]*\b"
    r"(the )?(score|band|rating|severity)\b", re.I)
_REFUSE_CLOSE = re.compile(
    r"\b(close|dismiss|clear|resolve)\b[^.?]*\b(case|alert|flag)\b", re.I)

# Stems are written with an explicit `\w*` tail rather than closed with `\b`:
# a trailing word boundary after "diagnos" can never match inside
# "diagnosis", which is exactly the word a reader types.
_ACTION = re.compile(
    r"\b(what should i do|what action|recommend\w*|remediat\w*|next step|"
    r"if i (can )?only|one thing|highest.value)", re.I)
_ESCALATION = re.compile(
    r"\b(escalat\w*|who should i (tell|inform)|refer up|draft the note|"
    r"escalation note|whom do i)", re.I)
_EVIDENCE = re.compile(
    r"\b(evidence|what sits behind|source\w*|verif\w*|how confident|"
    r"where did .* come from|is this synthetic)", re.I)
_MOVEMENT = re.compile(
    r"\b(why did .*(chang\w*|fall|fell|drop\w*|rise|rose|increas\w*|decreas\w*)|"
    r"what changed|did .* improve\w*|score (fall|fell|drop\w*|rose)|"
    r"movement|moved most)", re.I)
_DIAGNOSIS = re.compile(
    r"\b(in common|diagnos\w*|driver tree|what do the .* share|"
    r"common (driver|feature))", re.I)
_METHODOLOGY = re.compile(
    r"\b(methodolog\w*|how (does|is) the (score|model)|explain (the )?"
    r"(matrix|notch\w*|decay|l\d(\.\w+)?)|why is.*not (independently )?scored|"
    r"which signals|what does .* mean)", re.I)
_COMPARE = re.compile(r"\bcompare\b|\bversus\b|\bvs\.?\b|\bagainst\b", re.I)
_GROUP_BY = re.compile(
    r"\b(group|grouped|by) (the (portfolio|book) )?by ([a-z0-9 ]+)", re.I)

#: Plain-language names for the fields the book can be grouped by.
_LEVEL_WORDS: dict[str, tuple[str, ...]] = {
    "segment": ("segment", "sector group", "corporate segment"),
    "sector": ("sector", "industry"),
    "internal_rating": ("grade", "rating", "internal grade", "rating grade",
                        "grade band", "internal rating"),
    "ifrs9_stage": ("stage", "ifrs 9 stage", "ifrs9 stage", "staging"),
    "region": ("region", "branch", "geography"),
    "relationship_manager": ("relationship manager", "rm", "portfolio owner"),
    "ews_band": ("severity", "band", "severity band"),
    "dominant_layer": ("dominant layer", "layer", "where risk is detected"),
    "utilisation_band": ("utilisation", "utilisation band", "drawdown"),
}

_LAYER_WORDS = {
    "L1": ("layer 1", "l1", "behavioural", "behavioral"),
    "L2": ("layer 2", "l2", "fundamentals", "financial"),
    "L3": ("layer 3", "l3", "external"),
    "L4": ("layer 4", "l4", "network"),
}


@dataclass
class Answer:
    """One composed Early Warning answer, with the facts behind it."""

    pack: ff.FactPack | None
    composed: cp.Composed
    scope: str
    #: True when the answer refused rather than computed — asked to change a
    #: score, or to close a case.
    refused: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"scope": self.scope, "refused": self.refused,
                **self.composed.to_dict(),
                "facts": self.pack.to_dict() if self.pack else {}}


# ------------------------------------------------------------- resolution


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower()).strip()


def resolve_borrower(question: str, period: str | None = None) -> str | None:
    """Find the obligor a question names, in the Early Warning domain.

    Matched against the domain's own names rather than the credit book's,
    which is the specific reason a question about an Early Warning obligor
    used to come back as "not in the published data".
    """
    bm = svc.borrower_month(period)
    if bm.empty:
        return None
    asked = _norm(question)
    if not asked:
        return None
    # An identifier quoted outright wins over any name match.
    for cid in bm["customer_id"]:
        if str(cid).lower() in (question or "").lower():
            return str(cid)
    best: tuple[int, str] | None = None
    for _, row in bm.iterrows():
        name = _norm(str(row["customer_name"]))
        if not name:
            continue
        if name in asked:
            score = len(name)
            if best is None or score > best[0]:
                best = (score, str(row["customer_id"]))
    return best[1] if best else None


def resolve_level(question: str) -> str | None:
    """Which field the reader wants the book grouped by."""
    asked = _norm(question)
    found: tuple[int, str] | None = None
    for field_name, words in _LEVEL_WORDS.items():
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", asked):
                # Longest phrase wins, so "internal grade" beats "grade".
                if found is None or len(word) > found[0]:
                    found = (len(word), field_name)
    return found[1] if found else None


def resolve_group(question: str, period: str | None = None
                   ) -> tuple[str, str] | None:
    """Find a named group — a segment, a grade, a region — in the question."""
    bm = ff._with_derived(svc.borrower_month(period))
    asked = _norm(question)
    best: tuple[int, str, str] | None = None
    for field_name in ff.LEVEL_FIELDS:
        if field_name not in bm.columns:
            continue
        for value in bm[field_name].dropna().unique():
            token = _norm(str(value))
            if not token or len(token) < 3:
                continue
            if re.search(rf"\b{re.escape(token)}\b", asked):
                if best is None or len(token) > best[0]:
                    best = (len(token), field_name, str(value))
    return (best[1], best[2]) if best else None


def resolve_layer(question: str) -> str | None:
    asked = _norm(question)
    for code, words in _LAYER_WORDS.items():
        for word in words:
            if re.search(rf"\b{re.escape(word)}\b", asked):
                return code
    return None


def resolve_signal(question: str, customer_id: str,
                    period: str | None = None) -> str | None:
    obs = svc.signal_observations(customer_id, period)
    if obs.empty:
        return None
    asked = _norm(question)
    for key in obs["signal_key"]:
        if _norm(str(key).replace("_", " ")) in asked:
            return str(key)
    # Nothing named outright: the node the reader is most likely asking about
    # is the one carrying the obligor.
    return str(obs.sort_values("signal_score", ascending=False).iloc[0]["signal_key"])


# ---------------------------------------------------------------- routing


def answer(question: str, *, period: str | None = None,
           customer_id: str | None = None) -> Answer | None:
    """Read one Early Warning question and answer it from the domain.

    Returns None when the question is not one this domain should answer, so
    it falls through to the ordinary path rather than being met with a
    portfolio summary it did not ask for. That is also what keeps the domain
    lock meaningful: a question needing another domain's data reaches the
    lock and is refused, instead of being quietly absorbed here.

    `customer_id` is the obligor the conversation is already about, so a
    follow-up of "what should I do?" is answered about that obligor rather
    than about the book. A name in the question always wins over it.
    """
    text = question or ""

    # Two things the assistant does not do, said plainly and with the route
    # that does exist rather than a flat refusal.
    if _REFUSE_SCORE_CHANGE.search(text):
        return Answer(None, cp.Composed(
            direct=("CreditProbe does not change a score on request. The "
                    "assistant explains and navigates; an override goes "
                    "through the documented override path, where it is "
                    "recorded and counted as a control."),
            follow_ups=["Why is this obligor scored where it is?",
                        "Show me the evidence behind that node."]),
            scope="refusal", refused=True)
    if _REFUSE_CLOSE.search(text):
        return Answer(None, cp.Composed(
            direct=("Closing a case is not something the chat layer does. It "
                    "proposes; the escalation matrix decides, and a case "
                    "closes on its evidence test rather than on a request."),
            follow_ups=["What action should I take?",
                        "What evidence closes this case?"]),
            scope="refusal", refused=True)

    # Asked before any group is resolved: "what do the high-risk borrowers
    # have in common?" names a band, but it is a question about the
    # population's shared drivers rather than a request to open that band.
    if _DIAGNOSIS.search(text):
        band = "HIGH_PLUS" if re.search(r"\bhigh\b|\bworst\b|\brisk\b", text, re.I) else None
        pack = ff.diagnosis(period, band=band)
        return Answer(pack, cp.compose(pack), "diagnosis")

    # A question about the model itself is answered before any population is
    # resolved: "explain the matrix" names no obligor and needs none.
    if _METHODOLOGY.search(text) and not _MOVEMENT.search(text):
        pack = ff.methodology()
        return Answer(pack, cp.compose(pack), "methodology")

    named = resolve_borrower(text, period)
    customer_id = named or customer_id
    group_found = resolve_group(text, period) if named is None else None

    # An obligor named in the question, or carried from the conversation,
    # anchors everything that follows.
    if customer_id is not None:
        if _EVIDENCE.search(text):
            signal = resolve_signal(text, customer_id, period)
            pack = ff.signal_evidence(customer_id, signal, period) if signal else None
            if pack is not None:
                return Answer(pack, cp.compose(pack), "evidence")
        if _ESCALATION.search(text):
            pack = ff.borrower(customer_id)
            return Answer(pack, cp.escalation(pack), "escalation")
        if _ACTION.search(text):
            pack = ff.borrower(customer_id)
            return Answer(pack, cp.action(pack), "action")
        layer_code = resolve_layer(text)
        if layer_code and not _MOVEMENT.search(text):
            pack = ff.layer(customer_id, layer_code)
            return Answer(pack, cp.compose(pack), "layer")
        pack = ff.borrower(customer_id)
        return Answer(pack, cp.compose(pack), "borrower")

    if _COMPARE.search(text) and group_found:
        # Two groups named; compare them on the field the first matched.
        field_name, left = group_found
        others = [v for v in svc.borrower_month(period)[field_name].dropna().unique()
                  if _norm(str(v)) in _norm(text) and str(v) != left]
        if others:
            pack = ff.comparison(field_name, left, str(others[0]), period)
            return Answer(pack, cp.compose(pack), "comparison")

    if group_found and (_ABOUT_EARLY_WARNING.search(text) or _LOOK_AT.search(text)):
        field_name, value = group_found
        pack = ff.group(field_name, value, period)
        return Answer(pack, cp.compose(pack), "group")

    if _MOVEMENT.search(text):
        pack = ff.movement(period_to=period)
        return Answer(pack, cp.compose(pack), "movement")

    grouped = _GROUP_BY.search(text)
    level_field = resolve_level(text)
    if grouped or (level_field and not any(w in _norm(text) for w in _PORTFOLIO)):
        if level_field:
            pack = ff.level(level_field, period)
            return Answer(pack, cp.compose(pack), "level")

    # Falling back to a portfolio summary for anything unrecognised would
    # answer a different question from the one asked — "how much is in
    # arrears?" met with the portfolio's early warning score is a
    # non-sequitur that reads like an answer. So the reader has to have asked
    # about this domain, and anything else is declined here and left to the
    # ordinary path, where the domain lock decides whether it may be answered
    # at all.
    if _ABOUT_EARLY_WARNING.search(text):
        pack = ff.portfolio(period)
        return Answer(pack, cp.compose(pack), "portfolio")
    return None


def suggestions() -> list[dict[str, str]]:
    """The questions the Early Warning screen offers, all of them answerable."""
    return [
        {"question": "Why has portfolio early warning moved?",
         "note": "Contribution by layer"},
        {"question": "Show me the highest-risk borrowers.",
         "note": "Ranked by score, with the driver"},
        {"question": "Group the portfolio by internal grade.",
         "note": "Grade against early warning"},
        {"question": "What do the high-risk borrowers have in common?",
         "note": "Descriptive diagnosis"},
        {"question": "Which layer moved most?",
         "note": "Where risk is being detected"},
    ]


__all__ = ["Answer", "answer", "suggestions", "resolve_borrower",
           "resolve_level", "resolve_group", "resolve_layer", "resolve_signal"]
