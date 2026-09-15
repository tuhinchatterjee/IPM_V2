"""Which retail question this is, and on what.

The failure this exists for
---------------------------
The generic semantic planner reads a sentence against a vocabulary of fields
and picks the analysis whose shape fits best. That is the right mechanism for
"show retail exposure by product", and it is the wrong one for

    what is the reason of this rise?

because the sentence contains almost no information. Everything that matters —
which rise, of what, over which step — is in the investigation the question was
asked inside. Planning it as a fresh sentence produced a confident answer about
gross carrying amount across the whole portfolio over twelve months, inside an
investigation about the Credit Card 30+ DPD rate moving month on month.

So a small number of question FAMILIES are recognised here, scoped from the
thread rather than from the words, and handed to a purpose-built analysis.
Everything this does not recognise falls through to the planner untouched: the
router's job is to decline quickly, not to take over.

What it deliberately does not do
--------------------------------
Guess. A "why" with no recognisable subject and no case context is not routed;
the planner's clarification is a better answer than this module inventing a
scope. And a question that names its own scope wins over the thread's, because
a reader who types "and for personal finance?" means it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.retail import taxonomy as tax

ROUTER_VERSION = "retail-story-router-1.0.0"

DELINQUENCY = "delinquency_decomposition"
TRAITS = "trait_attribution"

#: "why did this go up" in the shapes a person actually types, including the
#: contract's own examples with their original punctuation and word order.
_WHY = re.compile(
    r"\b("
    r"what\s+(is|are)\s+the\s+reasons?"
    r"|what\s+(is|are)\s+the\s+reasons?\s+of\s+this"
    r"|why\s+(has|did|is)\s+(it|this|that)"
    r"|why\s+(has|did)\s+.{0,40}\b(risen|rise|gone\s+up|increased|worsened)"
    r"|reasons?\s+for\s+(this|the)\s+(rise|increase|deterioration)"
    r"|break\s+(it|this|the\s+deterioration)\s+down"
    r"|break\s+down\s+the\s+deterioration"
    r"|what\s+(is|)\s*driv(ing|es)\s+(this|the\s+(rise|increase))"
    r"|explain\s+(this|the)\s+(rise|increase|deterioration|movement)"
    r")", re.I)

#: Questions that are about the decomposition even without a "why".
_DECOMPOSE = re.compile(
    r"\b("
    r"worsening\s+accounts?,?\s+cures?"
    r"|(roll|migration)\s+(rates?|matrix)"
    r"|transition\s+matrix"
    r"|what\s+improved\s+and\s+offset"
    r"|which\s+sub-?products?\s+(are\s+)?driv"
    r"|which\s+customers\s+explain"
    r"|compare\s+account-?count\s+and\s+exposure-?weighted"
    r"|ecl\s+impact\s+separately\s+from"
    r"|cures?\s+and\s+(new\s+)?arrears"
    # No trailing \b. Several alternatives above end on a truncated stem —
    # "driv", "explain" — and there is no word boundary between "driv" and the
    # "ing" that follows it, so a \b here made them unmatchable. "Which
    # sub-products are driving the increase?" fell through to the planner.
    r")", re.I)

#: §7. The trait question, and the follow-ups that stay inside it.
_TRAITS = re.compile(
    r"\b("
    r"customer\s+traits?\s+.{0,40}\bdeteriorat"
    r"|traits?\s+(that\s+)?(have\s+)?deteriorat"
    r"|what\s+.{0,30}\bcharacteristics?\s+.{0,30}\b(chang|deteriorat|worsen)"
    r"|which\s+(scorecard\s+)?variables?\s+.{0,30}\b(deteriorat|chang|drift)"
    r"|impact\s+on\s+ecl\s+because\s+of\s+(them|these|those|traits?)"
    r"|show\s+all\s+behaviou?ral\s+scorecard\s+variables?"
    r"|separate\s+existing-?customer\s+deterioration\s+from"
    r"|income-?to-?score-?to-?pd-?to-?ecl"
    r")", re.I)

#: A metric named in the sentence itself wins over the thread's.
_METRICS = (
    (re.compile(r"\b(30\s*\+?\s*dpd|30\+\s*delinquen|arrears\s+rate)\b", re.I),
     "ret.dpd30.exposure"),
    (re.compile(r"\becl\b|\ballowance\b|expected\s+credit\s+loss", re.I),
     "ret.ecl.coverage"),
    (re.compile(r"\bstage\s*2\b|\bsicr\b", re.I), "ret.stage2.share"),
)


@dataclass
class Ask:
    """One recognised question, with everything the analysis needs."""

    analysis: str
    product: str = ""
    classification: str = ""
    sub_product: str = ""
    month: str = ""
    prior: str = ""
    metric_id: str = ""
    why: str = ""
    from_case: bool = False
    scope_source: str = ""
    router_version: str = ROUTER_VERSION
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"analysis": self.analysis, "product": self.product,
                "classification": self.classification,
                "sub_product": self.sub_product, "month": self.month,
                "prior": self.prior, "metric_id": self.metric_id,
                "why": self.why, "from_case": self.from_case,
                "scope_source": self.scope_source,
                "router_version": self.router_version,
                "notes": list(self.notes)}


def _product_in(text: str) -> str:
    got = tax.resolve_product(text or "")
    return str(got or "")


def _classification_in(text: str) -> str:
    low = (text or "").lower()
    if re.search(r"\bnon-?salaried\b", low):
        return "NON_SALARIED"
    if re.search(r"\bsalaried\b", low):
        return "SALARIED"
    return ""


def _sub_product_in(text: str) -> str:
    """A Saudi card tier or finance sub-product named in the sentence."""
    from backend.retail import ews_model as M

    low = (text or "").lower()
    best = ""
    for code, label in sorted(getattr(M, "SUB_PRODUCT_LABELS", {}).items(),
                              key=lambda kv: -len(str(kv[1]))):
        phrase = str(label).lower()
        if phrase and phrase in low:
            best = str(code)
            break
        bare = str(code).split("_", 1)[-1].replace("_", " ").lower()
        if bare and len(bare) > 4 and bare in low:
            best = str(code)
            break
    return best


def read(question: str, context: dict[str, Any] | None = None) -> Ask | None:
    """The recognised question and its scope, or None to use the planner."""
    said = (question or "").strip()
    if not said:
        return None
    held = dict(context or {})
    scope = dict(held.get("scope") or {})
    case = dict(held.get("risk_case") or {})

    which = ""
    if _TRAITS.search(said):
        which = TRAITS
    elif _WHY.search(said) or _DECOMPOSE.search(said):
        which = DELINQUENCY
    if not which:
        return None

    # The sentence's own scope first; the thread's only where the sentence is
    # silent. "and for personal finance?" has to mean personal finance even
    # inside a credit-card investigation.
    said_product = _product_in(said)
    case_product = ""
    if case.get("entity_kind") == "product" or case.get("level") == "SEGMENT":
        case_product = _product_in(str(case.get("entity") or ""))
    if not case_product:
        case_product = _product_in(str(scope.get("sector") or ""))

    # §7.1: a trait question opened in a fresh thread is a RETAIL question.
    # Inheriting the product from whatever investigation it was typed inside,
    # without showing that it had, is the silent-filter defect the contract
    # names — so the trait analysis takes only a scope the sentence states,
    # and offers the narrowing as a follow-up instead.
    inherits = which == DELINQUENCY
    product = said_product or (case_product if inherits else "")
    source = ("the question" if said_product
              else "the investigation's risk case"
              if (case_product and inherits) else "")

    if which == DELINQUENCY and not product and not case:
        # A bare "why?" with nothing to attach it to. The planner's
        # clarification beats a scope invented here.
        return None

    month = str(scope.get("period") or case.get("period") or "")
    prior = str(scope.get("compare_period") or "")

    metric = ""
    for pattern, name in _METRICS:
        if pattern.search(said):
            metric = name
            break
    if not metric and which == DELINQUENCY:
        title = str(case.get("title") or "")
        for pattern, name in _METRICS:
            if pattern.search(title):
                metric = name
                break

    out = Ask(analysis=which, product=product,
              classification=_classification_in(said),
              sub_product=_sub_product_in(said),
              month=month, prior=prior, metric_id=metric,
              why=said, from_case=bool(case), scope_source=source)
    if case and not said_product and product:
        out.notes.append(
            f"Scope taken from the investigation's case: {case.get('title')}")
    if which == DELINQUENCY and metric and metric != "ret.dpd30.exposure":
        out.notes.append(
            "The case is about a delinquency rate; the decomposition is "
            "reported on it, and the ECL movement is reported separately "
            "beside it rather than mixed into it.")
    return out


# ------------------------------------------------- running what was read

def answer(ask: Ask) -> dict[str, Any]:
    """Run the analysis this question asked for."""
    if ask.analysis == DELINQUENCY:
        from backend.retail import analysis_delinquency as A

        out = A.run(month=ask.month, prior=ask.prior, product=ask.product,
                    classification=ask.classification,
                    sub_product=ask.sub_product, question=ask.why)
    elif ask.analysis == TRAITS:
        from backend.retail import analysis_traits as T

        out = T.run(month=ask.month, product=ask.product,
                    classification=ask.classification,
                    sub_product=ask.sub_product, question=ask.why)
    else:
        return {"available": False,
                "because": f"{ask.analysis!r} has no analysis behind it"}
    out["routed"] = ask.to_dict()
    return out
