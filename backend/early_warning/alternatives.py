"""
What Early Warning CAN answer, when it is not the right place to ask.

Why "go to What-If" is not an answer
------------------------------------
A reader who asks about an oil shock inside Early Warning has an objective —
they want to know which of their names are exposed to a commodity downturn.
The scenario is how they thought to ask for it. Routing them to What-If is
correct and, on its own, useless: it answers the question they typed and
abandons the one they had.

So a redirect carries alternatives: three to five questions this domain can
actually answer that get as close to the same objective as observed data
allows. They are not decoration and they are not generated hopefully — each
is checked against the field dictionary, the published periods and the
caller's permissions before it is shown, because an offered question that
then fails is worse than no offer.

The rule the checking enforces
------------------------------
An alternative may only reference fields that exist. That is the same rule
the planner works under, applied here for the same reason: a question the
product proposes and cannot then answer costs more trust than the redirect
saved.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.early_warning import dictionary as dic
from backend.early_warning import functionality as fn

#: How many alternatives a redirect carries. Three is enough to show the
#: domain has something to say; more than five is a menu nobody reads.
MIN_ALTERNATIVES = 3
MAX_ALTERNATIVES = 5


@dataclass(frozen=True)
class Alternative:
    """One question this domain can answer, and the fields that make it so."""

    question: str
    #: Every field the question needs. Checked before it is offered.
    requires: tuple[str, ...]
    #: Why this gets at the reader's objective.
    because: str

    def to_dict(self) -> dict[str, Any]:
        return {"question": self.question, "requires": list(self.requires),
                "because": self.because}


#: Alternatives keyed to the objective behind the question, not to its words.
#: Each is written against the wide view's own field names so the check below
#: is a real check rather than a formality.
_BY_THEME: tuple[tuple[str, tuple[Alternative, ...]], ...] = (
    ("commodity", (
        Alternative(
            "Which obligors currently carry external-intelligence warning "
            "signals?",
            ("l3_ta", "customer_name", "ews_score"),
            "External intelligence is where a commodity event reaches the "
            "book as something observed rather than assumed."),
        Alternative(
            "Which sectors have the highest external-intelligence score?",
            ("sector", "l3_ta", "exposure"),
            "It finds the sectors already showing the stress a shock would "
            "deepen."),
        Alternative(
            "Which obligors' Early Warning score has risen most over twelve "
            "months?",
            ("ews_change_12m", "customer_name", "exposure"),
            "Deterioration already under way is the closest observed "
            "equivalent to a shock's effect."),
        Alternative(
            "Which obligors in the affected sectors are at High or Very High?",
            ("sector", "ews_band", "high_plus", "exposure"),
            "It names the exposure that is already vulnerable before any "
            "scenario is applied."),
    )),
    ("downgrade", (
        Alternative(
            "Which obligors' internal grade and Early Warning score diverge "
            "most?",
            ("internal_rating", "ews_score", "customer_name"),
            "A grade that has not caught up with the score is where the next "
            "downgrade is most likely to come from."),
        Alternative(
            "Which obligors have deteriorated most since last month?",
            ("ews_change_1m", "customer_name", "exposure"),
            "Observed movement, rather than an assumed one."),
        Alternative(
            "How does the book look grouped by internal grade?",
            ("internal_rating", "ews_score", "exposure", "high_plus"),
            "It shows the current position of each grade before any "
            "hypothetical migration."),
        Alternative(
            "Which obligors carry a direction-of-travel notch against them?",
            ("notch_direction_of_travel", "customer_name", "ews_score"),
            "The notch records obligors whose own score is already moving the "
            "wrong way."),
    )),
    ("model_quality", (
        Alternative(
            "How does the Early Warning model work?",
            ("ews_score",),
            "The methodology is documented and readable here, including what "
            "the model is and is not calibrated to do."),
        Alternative(
            "Where do the Early Warning score and the internal grade "
            "disagree?",
            ("internal_rating", "ews_score", "customer_name"),
            "Divergence between the two is the observable question closest to "
            "asking whether the model is behaving."),
        Alternative(
            "How complete is the evidence behind the current scores?",
            ("notch_evidence_quality", "notch_data_staleness", "ews_score"),
            "The evidence-quality and staleness notches are what this domain "
            "holds about the reliability of its own inputs."),
        Alternative(
            "How is the book distributed across the severity bands?",
            ("ews_band", "exposure", "customer_id"),
            "The distribution is the observable shape of the model's output."),
    )),
    ("portfolio", (
        Alternative(
            "Show exposure by sector for obligors at High or Very High.",
            ("sector", "exposure", "high_plus", "ews_band"),
            "It is the same cut, restricted to the population Early Warning "
            "actually scores and is about."),
        Alternative(
            "Which sectors have deteriorated most in Early Warning?",
            ("sector", "ews_change_12m", "exposure"),
            "It answers the sector question in warning terms rather than in "
            "balance terms."),
        Alternative(
            "Which segments carry the most high-risk exposure?",
            ("segment", "exposure", "high_plus"),
            "It names where the vulnerable exposure sits."),
        Alternative(
            "How is high-risk exposure concentrated across obligors?",
            ("exposure", "high_plus", "customer_name"),
            "Concentration decides whether a population action or a set of "
            "single-name escalations is the efficient response."),
    )),
)

#: Which theme a redirected question belongs to.
_THEMES: tuple[tuple[str, str], ...] = (
    ("commodity", r"oil|gas|commodit\w*|petro|energy|price\w* (fall|drop|rise)|"
                  r"gdp|macro|rate\w* (rise|fall)|inflation"),
    ("downgrade", r"downgrade|notch\w* down|migrat\w*|rating (shock|change)|"
                  r"\bgrade \d|pd shock|lgd shock"),
    ("model_quality", r"gini|auc|\bks\b|\bpsi\b|calibrat\w*|discriminat\w*|"
                      r"backtest\w*|validat\w*|stability|rank order"),
    ("portfolio", r"exposure|sector|segment|portfolio|distribution|stage|"
                  r"concentrat\w*|total"),
)

_BY_THEME_MAP = dict(_BY_THEME)


def _theme(text: str) -> str:
    for name, pattern in _THEMES:
        if re.search(pattern, text or "", re.I):
            return name
    return "portfolio"


def feasible(alternative: Alternative, *,
              known: frozenset[str] | None = None) -> bool:
    """Whether this domain can actually answer it.

    Every field the question needs has to exist in the dictionary. An offered
    question that then fails is worse than no offer, so this runs before the
    alternative is shown rather than after it is chosen.
    """
    fields = known if known is not None else dic.names()
    return all(name in fields for name in alternative.requires)


def for_request(request_text: str, winner: str = "") -> list[Alternative]:
    """Alternatives this domain can answer, closest to the same objective.

    Filtered against the live dictionary, so what comes back is a promise the
    domain can keep.
    """
    theme = _theme(request_text)
    candidates = list(_BY_THEME_MAP.get(theme, ()))
    # A model-quality redirect and a portfolio redirect share the observable
    # ground when neither theme matched much, so the portfolio set backs up
    # any theme that came up short.
    if len(candidates) < MAX_ALTERNATIVES:
        candidates += [a for a in _BY_THEME_MAP["portfolio"]
                       if a not in candidates]
    known = dic.names()
    checked = [a for a in candidates if feasible(a, known=known)]
    del winner
    return checked[:MAX_ALTERNATIVES]


def redirect_answer(request_text: str, selection: fn.Selection
                     ) -> dict[str, Any]:
    """The whole redirect: who owns it, why, and what this domain can do.

    No analysis is planned and none is run. That is the point of routing
    before planning rather than after it.
    """
    won = fn.BY_KEY.get(selection.selected)
    here = fn.BY_KEY[fn.EARLY_WARNING]
    options = for_request(request_text, selection.selected)

    direct = (f"That is a question for {won.name}, not for Early Warning."
              if won else "That is not a question Early Warning owns.")
    reading = (
        f"{won.purpose} "
        f"{here.purpose} "
        f"Answering it here would mean using the fields Early Warning happens "
        f"to hold to approximate something it does not measure, and "
        f"presenting the result as though it did."
        if won else here.purpose)

    return {
        "answered": False,
        "redirected": True,
        "scope": "redirect",
        "direct": direct,
        "interpretation": reading,
        "selected_functionality": selection.selected,
        "selected_name": selection.name,
        "rationale": selection.rationale,
        "alternatives": [a.to_dict() for a in options],
        "follow_ups": [a.question for a in options],
        "caveats": [
            "No Early Warning analysis was run for this question. Ownership "
            "is decided before any analysis is planned, so a question this "
            "domain does not own never reaches its data."],
    }


__all__ = ["MAX_ALTERNATIVES", "MIN_ALTERNATIVES", "Alternative", "feasible",
           "for_request", "redirect_answer"]
