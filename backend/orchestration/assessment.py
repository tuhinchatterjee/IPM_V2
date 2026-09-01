"""
What an analyst says when asked whether the result on the screen makes sense.

The answer this replaces
------------------------
"Yes, the trend is consistent." Which is true, contains no evidence, and is
indistinguishable from a guess. A credit officer reading it learns nothing they
could take to a committee, and — worse — cannot tell whether CreditProbe looked
at the figures or at the question.

The five parts
--------------
Every assessment has the same shape, because a reader who has seen one knows
where to look in the next:

**CONCLUSION** — the finding, in one sentence, with its own qualification
inside it. "Strong monotonic association between weaker grade and higher ECL
coverage; the DSCR relationship is weaker and has two exceptions" is a
conclusion. "The trend is consistent" is a mood.

**EVIDENCE** — direction, magnitude, the coefficient, the sample size, the
strongest pattern and the exceptions. Every figure computed by an approved
kernel over the rows that were already on the screen.

**CREDIT INTERPRETATION** — why the association is economically plausible, in
governed terms. Bounded hard: it may reason from what the measures *are* — a
definition — and from established credit-risk logic. It may not claim the data
shows a cause, because an aggregate cannot.

**LIMITATION** — what would break the reading. Group count, aggregation hiding
dispersion, same-period association rather than prediction, confounding.

**NEXT BEST ANALYSIS** — the calculation that would actually settle it.

What this module may not do
----------------------------
Invent a figure. Every number in the prose comes from an `Outcome` returned by
`kernels`, formatted by `figures`, and appears in `Assessment.evidence_values`
so the grounding check can verify it. Nothing here calls a model: this is the
skeleton the interpretation writer is given, and where there is no provider it
IS the answer.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import association, figures, kernels, reuse

logger = logging.getLogger(__name__)

#: Where a coefficient stops being a curiosity and starts being a finding.
#: The same thresholds `association` uses, imported rather than restated so the
#: word "strong" cannot mean two things in one product.
STRONG = association.STRONG
MODERATE = association.MODERATE

#: How many pairs are described. Three measures make three pairs and that is
#: already a paragraph; six measures make fifteen and nobody reads it.
MAX_PAIRS = 3

#: The fixed sentence about causation. `association.CAVEAT` verbatim — this is
#: the one piece of wording in the product that must never be regenerated.
CAVEAT = association.CAVEAT


@dataclass
class Assessment:
    """The five parts, plus everything needed to check them."""

    conclusion: str = ""
    evidence: list[str] = field(default_factory=list)
    credit_interpretation: str = ""
    limitations: list[str] = field(default_factory=list)
    next_analysis: list[str] = field(default_factory=list)
    caveat: str = CAVEAT

    #: The association this was built from, serialised for the Trace.
    association: dict[str, Any] = field(default_factory=dict)
    #: Every kernel that ran, in order, with its inputs and its result.
    kernels: list[dict[str, Any]] = field(default_factory=list)
    #: Figures the prose is allowed to quote, keyed for the grounding check.
    evidence_values: dict[str, Any] = field(default_factory=dict)
    #: Set when no assessment could honestly be made.
    unavailable: str = ""
    offer: str = ""

    @property
    def usable(self) -> bool:
        return bool(self.conclusion and not self.unavailable)

    def prose(self) -> str:
        """The whole assessment as one readable block."""
        parts = [self.conclusion]
        if self.evidence:
            parts.append(" ".join(self.evidence))
        if self.credit_interpretation:
            parts.append(self.credit_interpretation)
        return "\n\n".join(p for p in parts if p)

    def to_dict(self) -> dict[str, Any]:
        return {
            "conclusion": self.conclusion,
            "evidence": list(self.evidence),
            "credit_interpretation": self.credit_interpretation,
            "limitations": list(self.limitations),
            "next_analysis": list(self.next_analysis),
            "caveat": self.caveat,
            "association": dict(self.association),
            "kernels": [dict(k) for k in self.kernels],
            "values": dict(self.evidence_values),
            "unavailable": self.unavailable,
            "offer": self.offer,
        }


# ---------------------------------------------------------------------------
# Building it
# ---------------------------------------------------------------------------


def assess(cached: reuse.Cached, question: str = "") -> Assessment:
    """The assessment of a result that is already on the table.

    Takes the cached result and nothing else. It cannot reach governed data
    because it is not given any way to — which is what makes "no governed data
    was rescanned for this follow-up" a property of the code rather than a
    promise on the screen.
    """
    enough = reuse.sufficient(cached, question)
    if not enough.ok:
        return Assessment(unavailable=enough.missing, offer=enough.offer)

    found = association.analyse(cached.columns, cached.rows)
    if not found.usable:
        return Assessment(
            unavailable=(found.unavailable
                         or "no pattern could be described from this result"),
            offer=reuse.sufficient(None).offer,
            association=found.to_dict())

    ran: list[dict[str, Any]] = []
    values: dict[str, Any] = {}
    series = _series(cached, found)

    pairs = [p for p in found.pairs if p.spearman is not None][:MAX_PAIRS]
    for pair in pairs:
        left, right = series.get(pair.a, []), series.get(pair.b, [])
        labels = series.get("__labels__", [])
        for outcome in (
            kernels.run("spearman", left, right, labels),
            kernels.run("pearson", left, right, labels),
            kernels.run("rank_consistency", left, right, labels),
            kernels.run("significance", pair.spearman, pair.groups),
        ):
            ran.append({**outcome.to_dict(),
                        "inputs": [pair.a_label, pair.b_label]})
            values[f"{outcome.kernel}:{pair.a}:{pair.b}"] = outcome.value

    for trend in found.trends:
        outcome = kernels.run("monotonicity", series.get(trend.measure, []),
                              series.get("__labels__", []))
        ran.append({**outcome.to_dict(), "inputs": [trend.label]})
        values[f"monotonicity:{trend.measure}"] = outcome.value

    assessment = Assessment(
        conclusion=_conclusion(found, pairs),
        evidence=_evidence(found, pairs, ran),
        credit_interpretation=_credit(found, pairs),
        limitations=_limitations(cached, found),
        next_analysis=_next(cached, found, pairs),
        association=found.to_dict(),
        kernels=ran,
        evidence_values=values,
    )
    return assessment


def _series(cached: reuse.Cached,
            found: association.Analysis) -> dict[str, list[Any]]:
    """The columns as parallel lists, in the order the result presented them.

    Rebuilt here rather than returned by `association` so that a kernel sees
    exactly what the association saw — rows dropped for a missing value are
    dropped for every measure at once, and the labels stay aligned with them.
    """
    measures = {p.a for p in found.pairs} | {p.b for p in found.pairs}
    measures |= {t.measure for t in found.trends}
    out: dict[str, list[Any]] = {m: [] for m in measures}
    labels: list[Any] = []
    for row in cached.rows:
        if any(not isinstance(row.get(m), (int, float))
               or isinstance(row.get(m), bool) for m in measures):
            continue
        labels.append(row.get(found.subject))
        for m in measures:
            out[m].append(row[m])
    out["__labels__"] = labels
    return out


def _rho(value: float | None) -> str:
    return figures.text(value, figures.Spec(decimals=2)) if value is not None else ""


def _said(label: str) -> str:
    """A measure name mid-sentence. "ECL coverage", never "ecl coverage"."""
    text = str(label or "").strip()
    if not text:
        return text
    first = text.split()[0]
    if first.isupper() or any(c.isdigit() for c in first):
        return text
    return text[:1].lower() + text[1:]


def _conclusion(found: association.Analysis,
                pairs: list[association.Pair]) -> str:
    """The finding, with its qualification inside the same sentence.

    Built from the strongest pair and the weakest, because the honest headline
    for a three-measure result is almost never one relationship — it is one
    that holds and one that does not, and reporting only the first is how a
    confident sentence ends up describing a third of the table.
    """
    if not pairs:
        trend = next((t for t in found.trends if t.monotonic), None)
        if trend is None:
            return (f"Across {found.groups} "
                    f"{_said(found.subject_label)} groups the measures do not "
                    "move in a single direction, so the result does not "
                    "support a trend either way.")
        return (f"{trend.label} moves {trend.direction} consistently across "
                f"all {found.groups} {_said(found.subject_label)} groups.")

    ordered = sorted(pairs, key=lambda p: abs(p.spearman or 0.0), reverse=True)
    lead = ordered[0]
    shape = ("monotonic " if _is_monotonic(found, lead) else "")
    moves = ("higher" if lead.direction == "same" else "lower")
    sentence = (
        f"The result shows a {lead.strength} {shape}association across "
        f"{found.groups} {_said(found.subject_label)} groups: groups with "
        f"higher {_said(lead.a_label)} carry {moves} {_said(lead.b_label)} "
        f"(Spearman {_rho(lead.spearman)})")

    weakest = ordered[-1]
    if weakest is not lead and abs(weakest.spearman or 0.0) < STRONG:
        sentence += (
            f". The relationship with {_said(weakest.b_label)} is "
            f"{weakest.strength}er (Spearman {_rho(weakest.spearman)})")
        if weakest.exceptions:
            count = len(weakest.exceptions)
            sentence += (f" and contains {count} "
                         f"{'exception' if count == 1 else 'exceptions'} — "
                         + ", ".join(weakest.exceptions))
    elif lead.exceptions:
        count = len(lead.exceptions)
        sentence += (f", with {count} "
                     f"{'exception' if count == 1 else 'exceptions'}: "
                     + ", ".join(lead.exceptions))
    return sentence + "."


def _is_monotonic(found: association.Analysis,
                  pair: association.Pair) -> bool:
    by_measure = {t.measure: t for t in found.trends}
    left, right = by_measure.get(pair.a), by_measure.get(pair.b)
    return bool(left and right and left.monotonic and right.monotonic)


def _evidence(found: association.Analysis, pairs: list[association.Pair],
              ran: list[dict[str, Any]]) -> list[str]:
    """Direction, magnitude, coefficient, sample size, exceptions.

    Sample size is never omitted. A rank correlation of 0.9 over six rating
    grades and one over six hundred borrowers are different findings, and the
    only thing on the page that distinguishes them is the n.
    """
    out: list[str] = []
    #: Pairs that cleared the significance threshold, reported together at the
    #: end. One line naming three findings beats the same line three times.
    notable: list[str] = []
    critical = ""
    sample = 0

    for trend in found.trends:
        moves = "rises" if trend.direction == "rising" else "falls"
        if trend.monotonic:
            out.append(
                f"{trend.label} {moves} at every step across the "
                f"{found.groups} groups"
                + (f", from {figures.text(trend.first, figures.Spec(decimals=2))} "
                   f"to {figures.text(trend.last, figures.Spec(decimals=2))}."
                   if trend.first is not None and trend.last is not None
                   else "."))
        elif trend.breaks:
            out.append(
                f"{trend.label} does not move in a single direction: the "
                "sequence breaks at " + ", ".join(trend.breaks) + ".")

    for pair in pairs:
        consistency = _outcome_for(ran, "rank_consistency", pair)
        significant = _outcome_for(ran, "significance", pair)
        sentence = (
            f"{pair.a_label} and {pair.b_label} rank "
            f"{'together' if pair.direction == 'same' else 'inversely'} with a "
            f"Spearman coefficient of {_rho(pair.spearman)} over "
            f"{pair.groups} groups")
        if consistency is not None and consistency.get("value") is not None:
            # Stated in the direction the pair actually runs. "5% order them
            # the same way" is arithmetically identical to "95% order them
            # inversely" and reads as the opposite finding.
            agreeing = float(consistency["value"])
            same = pair.direction == "same"
            share = figures.percent((agreeing if same else 1.0 - agreeing)
                                    * 100.0, decimals=0)
            sentence += (f"; {share} of group-to-group comparisons order the "
                         "two measures "
                         + ("the same way" if same else "inversely"))
        out.append(sentence + ".")

        if pair.pearson is not None and not pair.linear:
            out.append(
                f"The level relationship is weaker than the rank one "
                f"(Pearson {_rho(pair.pearson)}), so the pattern is ordinal "
                "rather than proportional.")
        if significant is not None:
            detail = significant.get("detail") or {}
            threshold = _rho(detail.get("critical_value"))
            if detail.get("significant"):
                notable.append(
                    f"{pair.a_label} against {pair.b_label} "
                    f"({_rho(pair.spearman)})")
            else:
                out.append(
                    f"At {pair.groups} groups the {_said(pair.a_label)} / "
                    f"{_said(pair.b_label)} coefficient does not reach the "
                    f"p < 0.05 threshold of {threshold}, so it is suggestive "
                    "rather than established.")
            critical = threshold
            sample = pair.groups
        if pair.exceptions:
            out.append(
                ", ".join(pair.exceptions)
                + (" does" if len(pair.exceptions) == 1 else " do")
                + " not sit where the association places "
                + ("it" if len(pair.exceptions) == 1 else "them") + ".")

    if notable:
        out.append(
            f"At {sample} groups the p < 0.05 threshold for Spearman's rho is "
            f"{critical}; " + ", ".join(notable)
            + (" clears it." if len(notable) == 1 else " clear it."))
    return out


def _outcome_for(ran: list[dict[str, Any]], kernel: str,
                 pair: association.Pair) -> dict[str, Any] | None:
    for entry in ran:
        if entry.get("kernel") != kernel:
            continue
        inputs = entry.get("inputs") or []
        if pair.a_label in inputs and pair.b_label in inputs:
            return entry
    return None


# ---------------------------------------------------------------------------
# The credit reading
# ---------------------------------------------------------------------------


#: What each governed measure means, and which direction is worse.
#:
#: Definitions, not opinions. This is what lets the assessment say *why* an
#: association is economically plausible without asserting a cause: "weaker
#: obligors are provisioned more heavily" is what ECL coverage IS, and the
#: result is consistent with it or it is not.
_MEANING: dict[str, tuple[str, str]] = {
    "ecl": ("expected credit loss, which rises as the probability of default "
            "and the loss given default rise", "up"),
    "coverage": ("the provision held against exposure, which rises as the "
                 "assessed risk of the exposure rises", "up"),
    "stage": ("the IFRS 9 stage, which moves up when credit risk has "
              "increased significantly since origination", "up"),
    "pd": ("the probability of default over the measurement horizon", "up"),
    "lgd": ("the share of exposure expected to be lost given a default", "up"),
    "leverage": ("indebtedness relative to earnings, which reduces the "
                 "capacity to absorb a downturn", "up"),
    "dscr": ("the cash available to service debt as a multiple of the "
             "obligation, so a lower figure is the weaker position", "down"),
    "debt service": ("the cash available to service debt as a multiple of the "
                     "obligation, so a lower figure is the weaker position",
                     "down"),
    "headroom": ("the margin before a covenant is breached, so a lower figure "
                 "is the weaker position", "down"),
    "dpd": ("days past due, the most direct observed evidence of distress",
            "up"),
    "grade": ("the internal rating, where a weaker grade is the bank's own "
              "assessment that the obligor is more likely to default", "up"),
    "rating": ("the internal rating, where a weaker grade is the bank's own "
               "assessment that the obligor is more likely to default", "up"),
    "utilisation": ("the drawn share of a committed limit, which tends to "
                    "rise as an obligor's liquidity tightens", "up"),
    "ead": ("exposure at default, the amount at risk rather than a measure of "
            "quality", ""),
}


def _meaning_of(label: str) -> tuple[str, str]:
    lowered = str(label or "").lower()
    for key, value in _MEANING.items():
        if key in lowered:
            return value
    return ("", "")


def _credit(found: association.Analysis,
            pairs: list[association.Pair]) -> str:
    """Why the association is economically plausible, in governed terms.

    Reasons from what the measures ARE. Where both sides of a pair have a
    governed meaning and the observed direction matches what those meanings
    imply, that is said — and where it does NOT match, that is said too, which
    is the more useful half: an association running the wrong way against its
    own definitions is a data question, not a credit finding.
    """
    if not pairs:
        return ""
    pair = max(pairs, key=lambda p: abs(p.spearman or 0.0))
    left_meaning, left_worse = _meaning_of(pair.a_label)
    right_meaning, right_worse = _meaning_of(pair.b_label)
    if not left_meaning or not right_meaning:
        return ("These are governed measures of the same obligors over the "
                "same window, so they are comparable; the result describes "
                "how they move together and not why.")

    if not left_worse or not right_worse:
        return (f"{pair.a_label} is {left_meaning}. {pair.b_label} is "
                f"{right_meaning}. The two are measured over the same "
                "obligors and the same window, so the ordering is comparable.")

    # Do the definitions predict the direction that was observed?
    expected_same = (left_worse == right_worse)
    observed_same = (pair.direction == "same")
    lead = (f"{pair.a_label} is {left_meaning}. {pair.b_label} is "
            f"{right_meaning}.")
    if expected_same == observed_same:
        return (f"{lead} Deterioration in one is therefore expected to appear "
                "alongside deterioration in the other, and that is the "
                "ordering the result shows — the association is consistent "
                "with how the two measures are defined.")
    return (f"{lead} On those definitions, deterioration in one would be "
            "expected alongside deterioration in the other, and the result "
            "runs the other way. That is worth checking before it is read as "
            "a credit finding: a reversed ordering more often reflects "
            "portfolio mix or a data definition than an economic effect.")


# ---------------------------------------------------------------------------
# What would break it, and what would settle it
# ---------------------------------------------------------------------------


def _limitations(cached: reuse.Cached,
                 found: association.Analysis) -> list[str]:
    out: list[str] = []

    if found.groups <= 8:
        out.append(
            f"{found.groups} groups is a small number of observations. One "
            "group moving would change the coefficient materially.")

    if cached.dimension or found.subject:
        subject = _said(found.subject_label or cached.dimension_label)
        out.append(
            f"These are {subject} averages. A group whose members are widely "
            "dispersed and a group whose members are tightly clustered "
            "produce the same figure, so the aggregate can hide the "
            "distribution that matters.")

    if len(cached.periods) <= 1:
        out.append(
            "Both measures are read at the same date, so this is an "
            "association within one period and not evidence that either "
            "predicts the other.")

    if len(found.trends) > 2:
        out.append(
            "Several measures move together here, and any of them may be "
            "standing in for a common driver rather than acting on the "
            "others. Separating them needs a controlled comparison.")

    if cached.filters:
        applied = ", ".join(str(f.get("value") or "") for f in cached.filters
                            if f.get("value"))
        if applied:
            out.append(
                f"The result is already restricted to {applied}, so the "
                "pattern describes that population rather than the book.")
    return out


def _next(cached: reuse.Cached, found: association.Analysis,
          pairs: list[association.Pair]) -> list[str]:
    """The calculations that would actually settle it.

    Specific and runnable. "Investigate further" is not a next analysis; "show
    the distribution of ECL coverage within grade 5" is.
    """
    out: list[str] = []
    subject = found.subject_label or cached.dimension_label or "group"
    measure = pairs[0].b_label if pairs else (
        found.trends[0].label if found.trends else "the measure")

    exceptions = [name for pair in pairs for name in pair.exceptions]
    if exceptions:
        out.append(f"Show the customers inside {exceptions[0]} and their "
                   f"{_said(measure)}, to see whether the exception is a "
                   "handful of names or the whole group.")
    out.append(f"Show the distribution of {_said(measure)} within each "
               f"{_said(subject)}, rather than its average.")
    if len(cached.periods) <= 1:
        out.append(f"Compare the same {_said(subject)} breakdown against the "
                   "previous period, to see whether the ordering is stable or "
                   "is a feature of this quarter.")
    else:
        out.append("Run the same comparison one period earlier, to see "
                   "whether the ordering held before the latest movement.")
    if cached.filters:
        out.append("Run the same comparison across sectors, to see whether "
                   "the ordering survives controlling for sector mix.")
    else:
        out.append(f"Break the same {_said(subject)} comparison down by "
                   "sector, to see whether the ordering is a sector-mix "
                   "effect.")
    return out[:4]


__all__ = ["CAVEAT", "MAX_PAIRS", "MODERATE", "STRONG", "Assessment", "assess"]
