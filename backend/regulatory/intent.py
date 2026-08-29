"""Is this a question about what a REGULATION SAYS?

The client-demo release-candidate brief, §3, lists among the failures that
produce NO-GO:

    "unsupported question answered with unrelated analysis"

The demonstration question set found exactly that. Asked

    "What does the circular say about provisioning for Stage 2?"

CreditProbe ran a SIMPLE_ANALYSIS over `ifrs9_staging` and presented the
result. There is no circular in the corpus and no active Regulatory Knowledge
Release, and it answered anyway.

The reason is instructive. The coverage check asks whether the question names
things CreditProbe holds governed data ABOUT, and this one does: provisioning
and Stage 2 are governed concepts. So coverage passed, and nothing else asked
the different question — is this a request for a FIGURE, or for the CONTENT OF
A DOCUMENT? Those need different sources and only one of them exists here.

`backend/regulatory/assurance.py` already makes `release_active` a CRITICAL
gate: without an active release, nothing regulatory may be quoted. The gate
was right and nothing routed to it.

Deterministic on purpose
------------------------
No model decides this. A question about what a regulator requires is precisely
the question where a plausible-sounding answer does most damage, so the test
is a keyword rule anyone can read and argue with rather than a judgement call
made somewhere invisible.

Deliberately narrow
-------------------
It fires on a question asking what a SOURCE says or requires, not on any
question that mentions a regulatory concept. "What is total ECL by stage?" is
an IFRS 9 question and an ordinary analytical one; "what does IFRS 9 require
for Stage 2?" is a documentary one. The first must keep working exactly as it
does — a detector that swallowed it would break most of the product to fix one
question.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

INTENT_VERSION = "1.0.0"

#: Named regulatory SOURCES. A question is documentary when it asks what one
#: of these says, requires, permits or defines.
_SOURCES = (
    "circular", "circulars",
    "sama", "basel", "bcbs",
    "regulation", "regulations", "regulator", "regulatory",
    "ifrs 9", "ifrs9", "ifrs",
    "guideline", "guidelines", "guidance",
    "standard", "standards",
    "rulebook", "framework",
    "directive", "directives",
    "supervisory", "prudential",
)

#: Verbs that turn a mention of a source into a question about its CONTENT.
_ASKS = (
    "say", "says", "said", "state", "states", "stated",
    "require", "requires", "required", "requirement", "requirements",
    "permit", "permits", "allow", "allows", "prohibit", "prohibits",
    "define", "defines", "definition",
    "mandate", "mandates", "prescribe", "prescribes",
    "stipulate", "stipulates", "specify", "specifies",
    "comply", "compliance", "compliant",
    "rule", "rules", "clause", "article", "paragraph", "provision",
)

_SOURCE_RE = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(s) for s in _SOURCES) + r")(?![\w])",
    re.IGNORECASE)
_ASK_RE = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(a) for a in _ASKS) + r")(?![\w])",
    re.IGNORECASE)

#: Phrasings that are documentary on their own, with no separate verb needed.
_OUTRIGHT = (
    "under the circular", "per the circular", "according to the circular",
    "under sama", "according to sama", "per sama",
    "under basel", "according to basel",
    "what the regulator", "what the regulation",
    "regulatory requirement", "regulatory treatment",
    "cite the", "citation for",
)


@dataclass
class Reading:
    """Whether this is a documentary regulatory question, and why."""

    documentary: bool = False
    source: str = ""
    asked: str = ""
    phrase: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"documentary": self.documentary, "source": self.source,
                "asked": self.asked, "phrase": self.phrase,
                "version": INTENT_VERSION}


def read(question: str) -> Reading:
    """Read the question. Documentary only when a source AND an ask are both
    present, or when the phrasing is outright."""
    text = (question or "").strip()
    if not text:
        return Reading()

    low = text.lower()
    for phrase in _OUTRIGHT:
        if phrase in low:
            return Reading(documentary=True, phrase=phrase,
                           source=phrase, asked=phrase)

    source = _SOURCE_RE.search(text)
    ask = _ASK_RE.search(text)
    if source and ask:
        return Reading(documentary=True, source=source.group(1).lower(),
                       asked=ask.group(1).lower())
    return Reading()


def refusal(reading: Reading) -> str:
    """What to tell a user when there is nothing approved to answer from.

    Says three things, because a refusal that says only the first invites the
    user to rephrase and try again: what was asked for, why it cannot be
    answered, and what would make it answerable.
    """
    what = reading.source or "a regulatory source"
    return (
        f"This is a question about what {what} says, not about the "
        "portfolio, and CreditProbe answers it only from an approved "
        "Regulatory Knowledge Release. None is active on this deployment, so "
        "there is no reviewed source to quote and nothing to cite. It will "
        "not answer from the analytical data instead: a figure from the book "
        "is not what a regulation requires. Load the circulars, have a "
        "regulatory SME approve them, and activate a release.")


def may_answer(session: Any = None, *, tenant: str = "") -> bool:
    """Whether an approved Regulatory Knowledge Release is active.

    Fail-closed. Anything that goes wrong reading the release table means NO:
    a regulatory answer given because a query raised is the worst possible
    reason to have given one.
    """
    if session is None:
        return False
    try:
        from backend.services import regulatory as service

        return service.active_release(session, tenant=tenant) is not None
    except Exception:  # noqa: BLE001 - see the docstring
        return False
