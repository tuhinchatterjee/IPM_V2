"""
Reading the whole question. Brief §7.1.

The base Cockpit read a question into ONE intent label and answered that. Asked
"Give me an ECL decomposition and explain the impact of PD", it produced a
clarification about horizons; asked for base, upturn, downturn and weighted
ECL, it produced the ten largest facilities by ECL. Both are the same defect:
a multipart request forced through a single lossy label.

So this module does not return an intent. It returns a REQUEST: the complete
utterance, every subquestion it contains, every output asked for, the filters,
the periods, and what remains genuinely ambiguous. The answer layer then
answers each requested output, and a subquestion that could not be answered is
reported as unanswered rather than dropped.

Curated phrase lists here are a GUIDE to which capability is wanted, not a
keyword bottleneck: an utterance matching none of them still resolves to the
composition or movement default according to whether it asks about a change,
and novel phrasings compose because the outputs are independent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.cockpit_v2 import calendar as cal
from backend.cockpit_v2 import policy
from backend.cockpit_v2 import schema as schema_mod
from backend.cockpit_v2.generate import GEOGRAPHIES, SECTORS, SEGMENTS

# ------------------------------------------------------------------ outputs

#: A reconciled opening-to-closing ECL bridge by FACTOR. Not by sector.
ECL_FACTOR_DECOMPOSITION = "ecl_factor_decomposition"
#: Within that bridge, the PD group explained at length.
PD_IMPACT = "pd_impact"
#: The current ECL broken down by a dimension. A composition, not a movement.
COMPOSITION = "composition"
#: Where an additive measure moved, by dimension member.
MOVEMENT_BY_DIMENSION = "movement_by_dimension"
#: Scenario ECLs side by side, and why the weighted result sits where it does.
SCENARIO_COMPARISON = "scenario_comparison"
#: Whether weighted PD x weighted LGD reproduces weighted ECL. It does not.
PARAMETER_PRODUCT_CHECK = "parameter_product_check"
#: A ratio movement split into numerator and denominator effects.
RATIO_MOVEMENT = "ratio_movement"
#: A measure over its published periods, with honest statistics.
METRIC_HISTORY = "metric_history"
#: Ratings, downgrades and the financial ratios behind them.
RATING_REVIEW = "rating_review"
#: Covenant breaches, headroom, waivers and thresholds.
COVENANT_REVIEW = "covenant_review"
#: Collateral coverage, allocation, valuation age and the LGD consequence.
COLLATERAL_REVIEW = "collateral_review"
#: Stage migrations and the rule that triggered each.
STAGE_REVIEW = "stage_review"
#: Concentration by sector, product, geography and connected group.
CONCENTRATION = "concentration"
#: Which macro predictors enter the declared model, and how.
MACRO_DEPENDENCY = "macro_dependency"
#: A definition. No investigation and no chart.
DEFINITION = "definition"
#: What is missing, stale or not available.
DATA_QUALITY = "data_quality"

ALL_OUTPUTS = (ECL_FACTOR_DECOMPOSITION, PD_IMPACT, COMPOSITION,
               MOVEMENT_BY_DIMENSION, SCENARIO_COMPARISON,
               PARAMETER_PRODUCT_CHECK, RATIO_MOVEMENT, METRIC_HISTORY,
               RATING_REVIEW, COVENANT_REVIEW, COLLATERAL_REVIEW,
               STAGE_REVIEW, CONCENTRATION, MACRO_DEPENDENCY, DEFINITION,
               DATA_QUALITY)


# ---------------------------------------------------------------- vocabulary

_MOVEMENT_WORDS = (
    "movement", "moved", "change", "changed", "rise", "rose", "risen",
    "increase", "increased", "fall", "fell", "fallen", "decrease", "decreased",
    "grew", "growth", "deteriorat", "improv", "drove", "driver", "bridge",
    "since", "versus", "vs", "compare", "comparison", "quarter on quarter",
    "worsened", "shrank", "shrink")

_DECOMPOSITION_WORDS = ("decomposition", "decompose", "break down",
                        "breakdown", "attribution", "attribute", "bridge",
                        "waterfall", "walk", "explain the impact",
                        "what drove", "what is driving")

_FACTOR_WORDS = ("pd", "lgd", "ead", "parameter", "factor", "driver",
                 "scenario weight", "staging", "discount")

_COMPOSITION_WORDS = ("composition", "compose", "make up", "made up",
                      "split by", "by stage", "by sector", "by product",
                      "by geography", "distribution", "profile", "mix",
                      "current ecl", "break the current")

_NOT_A_MOVEMENT = ("not asking for a movement", "not a movement",
                   "i am not asking for a movement", "current composition",
                   "as at", "not the movement")

#: The five families whose words are distinctive enough to name directly.
_TOPIC_WORDS: dict[str, tuple[str, ...]] = {
    RATING_REVIEW: ("rating", "downgrade", "upgrade", "notch", "grade",
                    "dscr", "ratio", "ebitda", "leverage", "coverage ratio",
                    "cash generation", "financial", "quick ratio",
                    "current ratio", "inventory", "stale rating"),
    COVENANT_REVIEW: ("covenant", "breach", "breached", "headroom", "waiver",
                      "waived", "threshold", "test date", "cure"),
    COLLATERAL_REVIEW: ("collateral", "security", "secured", "unsecured",
                        "haircut", "valuation", "lgd", "recovery",
                        "property", "charge", "lien"),
    STAGE_REVIEW: ("stage 1", "stage 2", "stage 3", "staging", "sicr",
                   "migration", "migrated", "moved from stage",
                   "credit-impaired", "credit impaired", "npl",
                   "non-performing", "default", "write-off", "written off"),
    CONCENTRATION: ("concentration", "concentrated", "connected group",
                    "group exposure", "largest borrowers", "top borrowers",
                    "portfolio composition", "exposure by"),
    MACRO_DEPENDENCY: ("macro", "macroeconomic", "gdp", "inflation",
                       "unemployment", "policy rate", "bond yield",
                       "exchange rate", "property price", "oil price",
                       "industrial production", "household income",
                       "predictor", "forecast vintage"),
    SCENARIO_COMPARISON: ("scenario", "base case", "upturn", "downturn",
                          "weighted ecl", "scenario weight", "probability "
                          "weight"),
    DATA_QUALITY: ("missing", "stale", "not available", "unavailable",
                   "data quality", "gaps", "no statement"),
}

_DEFINITION_PATTERNS = (
    re.compile(r"^\s*what\s+(is|are|does)\b", re.I),
    re.compile(r"^\s*define\b", re.I),
    re.compile(r"\bwhat does\s+\w+\s+mean\b", re.I),
    re.compile(r"^\s*explain\s+(what\s+)?\w+\s+(is|are|means)\b", re.I),
    re.compile(r"\bin plain english\b", re.I),
)

_NO_CHART = re.compile(
    r"\b(do not|don'?t|no)\s+(show\s+)?(a\s+)?(chart|graph|visual)", re.I)
_WANT_CHART = re.compile(r"\b(chart|graph|waterfall|plot|visuali[sz]e)\b", re.I)

#: Documented sector aliases and common misspellings. Material ambiguity is
#: preserved rather than guessed: "trade" alone maps to nothing.
_SECTOR_ALIASES: dict[str, str] = {
    "construction": "Construction", "constrution": "Construction",
    "construciton": "Construction", "contracting": "Construction",
    "building": "Construction", "infra": "Construction",
    "manufacturing": "Manufacturing", "manufactuing": "Manufacturing",
    "industrials": "Manufacturing", "factories": "Manufacturing",
    "retail trade": "Retail Trade", "retail": "Retail Trade",
    "transport and logistics": "Transport and Logistics",
    "transport": "Transport and Logistics", "logistics": "Transport and Logistics",
    "shipping": "Transport and Logistics", "freight": "Transport and Logistics",
    "hospitality": "Hospitality", "hotels": "Hospitality",
    "hotel": "Hospitality", "leisure": "Hospitality",
    "healthcare": "Healthcare", "health care": "Healthcare",
    "hospitals": "Healthcare", "pharma": "Healthcare",
    "information technology": "Information Technology",
    # No "it" alias: it matches the pronoun in "where it is" and silently
    # filtered a portfolio question down to one sector on the first run. A
    # two-letter alias is not worth a wrong population.
    "i.t.": "Information Technology", "software": "Information Technology",
    "technology": "Information Technology",
    "real estate": "Real Estate", "realestate": "Real Estate",
    "property": "Real Estate", "realty": "Real Estate",
}

#: Assertions the Cockpit must not simply adopt. Brief A11.54, A11.55.
_LOADED_ASSERTIONS = (
    (re.compile(r"\bstatistically (abnormal|significant|unusual)\b", re.I),
     "statistical_abnormality",
     "The question asserts statistical abnormality. With eight published "
     "quarters at most, this demo cannot establish that, and the history "
     "tool reports the observation count and the descriptive nature of the "
     "comparison instead of confirming the assertion."),
    (re.compile(r"\b(fraud|fraudulent|management fraud|embezzl)\w*\b", re.I),
     "fraud_cause",
     "The question proposes fraud as the cause. Nothing in the governed data "
     "evidences it, so it is not adopted; the evidenced drivers are reported "
     "instead."),
    (re.compile(r"\bcaused by\b|\bbecause of management\b", re.I),
     "asserted_cause",
     "The question asserts a cause. The Cockpit reports attribution under a "
     "stated method and does not confirm a real-world cause it has no "
     "evidence for."),
    (re.compile(r"\bignore\b.{0,40}\b(restriction|instruction|scope|rule)s?\b",
                re.I),
     "scope_override_attempt",
     "The question asks the Cockpit to set its read scope aside. The scope is "
     "enforced in the backend and a request cannot widen it."),
)


@dataclass
class Request:
    """Everything the Cockpit understood, with nothing discarded."""

    utterance: str
    subquestions: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    to_period: str = ""
    from_period: str = ""
    dimension: str = ""
    measure: str = ""
    term: str = ""
    entity: str = ""
    wants_chart: bool | None = None
    wants_recommendations: bool = False
    wants_expansion: bool = False
    top_n: int = 0
    loaded_assertions: list[dict[str, str]] = field(default_factory=list)
    ambiguities: list[dict[str, Any]] = field(default_factory=list)
    is_followup: bool = False

    def wants(self, output: str) -> bool:
        return output in self.outputs

    def to_dict(self) -> dict[str, Any]:
        return {
            "utterance": self.utterance, "subquestions": list(self.subquestions),
            "requested_outputs": list(self.outputs), "filters": dict(self.filters),
            "to_period": self.to_period, "from_period": self.from_period,
            "dimension": self.dimension, "measure": self.measure,
            "term": self.term, "entity": self.entity,
            "wants_chart": self.wants_chart,
            "wants_recommendations": self.wants_recommendations,
            "wants_expansion": self.wants_expansion, "top_n": self.top_n,
            "loaded_assertions": list(self.loaded_assertions),
            "ambiguities": list(self.ambiguities),
            "is_followup": self.is_followup,
        }


def _subquestions(text: str) -> list[str]:
    """Split the utterance into the things actually asked.

    Sentence boundaries first, then coordinating conjunctions that join two
    imperatives — "give me X and explain Y" is two requests, and answering only
    the first is the defect this exists to prevent.
    """
    parts = [p.strip() for p in re.split(r"(?<=[.?!])\s+|;\s*", text) if p.strip()]
    out: list[str] = []
    for part in parts:
        pieces = re.split(
            r"\s+and\s+(?=(?:explain|tell|show|give|quantify|compare|separate|"
            r"break|list|identify|which|what|why|how|who|where)\b)",
            part, flags=re.I)
        out.extend(p.strip() for p in pieces if p.strip())
    return out or ([text.strip()] if text.strip() else [])


def _contains(text: str, words: tuple[str, ...]) -> bool:
    return any(w in text for w in words)


def _contains_word(text: str, words: tuple[str, ...]) -> bool:
    """Substring matching with a left word boundary.

    `"composition" in "decomposition"` is true, and it cost the checkpoint
    question a spurious composition output on the very first run. Anything
    matched against a word the user typed needs the boundary.
    """
    return any(re.search(rf"(?<![a-z]){re.escape(w)}", text) for w in words)


def _sector(text: str) -> str:
    for sector in SECTORS:
        if sector.lower() in text:
            return sector
    for alias, sector in _SECTOR_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return sector
    return ""


def _periods(text: str) -> tuple[str, str]:
    """Quarters named in the utterance, closing last."""
    found: list[str] = []
    for match in re.finditer(
            r"\b(?:cockpit[_\s-]*)?(\d{4})[_\s-]*q([1-4])\b|"
            r"\bq([1-4])[\s-]*(\d{4})\b", text, re.I):
        if match.group(1):
            label = f"{match.group(1)}Q{match.group(2)}"
        else:
            label = f"{match.group(4)}Q{match.group(3)}"
        if label not in found:
            found.append(label)
    if not found:
        return "", ""
    if len(found) == 1:
        return found[0], ""
    ordered = sorted(found, key=lambda q: cal.parse(q).index)
    return ordered[-1], ordered[0]


def read(text: str, *, previous: "Request | None" = None) -> Request:
    """Read one utterance, carrying forward what a follow-up should keep."""
    utterance = (text or "").strip()
    lower = utterance.lower()
    request = Request(utterance=utterance,
                      subquestions=_subquestions(utterance),
                      is_followup=previous is not None)

    for pattern, name, note in _LOADED_ASSERTIONS:
        if pattern.search(utterance):
            request.loaded_assertions.append({"assertion": name, "note": note})

    to_period, from_period = _periods(lower)
    request.to_period, request.from_period = to_period, from_period

    sector = _sector(lower)
    if sector:
        request.filters["sector"] = sector
    for segment in SEGMENTS:
        if segment.lower() in lower:
            request.filters["segment"] = segment
    for geography in GEOGRAPHIES:
        if re.search(rf"\b{geography.lower()}\b", lower):
            request.filters["geography"] = geography
    stage = re.search(r"\bstage\s*([123])\b", lower)
    if stage:
        request.filters["stage"] = int(stage.group(1))
    if re.search(r"\bexclude\s+new\b|\bexcluding\s+new\b", lower):
        request.filters["exclude_new"] = True
    if re.search(r"\bonly\s+continuing\b|\bcontinuing\s+(accounts|facilities)\b",
                 lower):
        request.filters["continuing_only"] = True

    top = (re.search(r"\b(?:top|largest|first)\s+(\w+)\b", lower)
           or re.search(r"\b(?:which|name|list|give me)\s+(\w+)\s+"
                        r"(?:borrowers?|names?|facilities|facility|sectors?|"
                        r"groups?|accounts?)\b", lower))
    if top:
        words = {"three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                 "eight": 8, "nine": 9, "ten": 10, "twenty": 20}
        raw = top.group(1)
        request.top_n = int(raw) if raw.isdigit() else words.get(raw, 0)

    # ---- follow-up inheritance. Brief §7.1.
    if previous is not None:
        for key in ("sector", "segment", "geography", "stage"):
            if key not in request.filters and key in previous.filters:
                request.filters[key] = previous.filters[key]
        if not request.to_period:
            request.to_period = previous.to_period
        if not request.from_period:
            request.from_period = previous.from_period
        if re.search(r"\b(previous|prior|last)\s+quarter\b", lower):
            # A new period resets the periods but keeps the sector.
            request.to_period = previous.from_period or ""
            request.from_period = ""
        request.dimension = previous.dimension
        request.measure = previous.measure

    # ---- what is actually being asked for
    outputs: list[str] = []
    definition_like = (any(p.search(utterance) for p in _DEFINITION_PATTERNS)
                       and len(utterance) < 220)
    if definition_like:
        outputs.append(DEFINITION)
        request.term = _definition_term(utterance)

    asks_movement = _contains(lower, _MOVEMENT_WORDS)
    asks_decomposition = _contains(lower, _DECOMPOSITION_WORDS)
    denies_movement = _contains(lower, _NOT_A_MOVEMENT)

    mentions_ecl = bool(re.search(
        r"\becl\b|\bexpected credit loss\b|\bprovision\b|\bimpairment\b|"
        r"\ballowance\b", lower))
    mentions_factor = _contains(lower, _FACTOR_WORDS)

    if mentions_ecl and asks_decomposition and not denies_movement:
        outputs.append(ECL_FACTOR_DECOMPOSITION)
    elif mentions_ecl and asks_movement and not denies_movement:
        outputs.append(ECL_FACTOR_DECOMPOSITION)

    if re.search(r"\bimpact of pd\b|\bpd (impact|effect|contribution)\b|"
                 r"\bimpact of the pd\b|\bpd effect\b|\brole of pd\b", lower):
        outputs.append(PD_IMPACT)
        if ECL_FACTOR_DECOMPOSITION not in outputs:
            outputs.append(ECL_FACTOR_DECOMPOSITION)

    if (denies_movement or _contains_word(lower, _COMPOSITION_WORDS)) and mentions_ecl:
        if ECL_FACTOR_DECOMPOSITION in outputs and denies_movement:
            outputs.remove(ECL_FACTOR_DECOMPOSITION)
        outputs.append(COMPOSITION)

    if re.search(r"\breproduce\b.*\bweighted\b|\bmultiply\w*\b.*\bweighted\b|"
                 r"\bweighted pd\b.*\bweighted lgd\b", lower):
        outputs.append(PARAMETER_PRODUCT_CHECK)

    if re.search(r"\bnpl ratio\b|\bcoverage ratio\b.*\b(rose|fell|change)\b|"
                 r"\bdenominator\b|\bnumerator\b", lower):
        outputs.append(RATIO_MOVEMENT)

    if re.search(r"\bover (the last |the )?(four|eight|\d+) quarters?\b|"
                 r"\btrack\b|\btrend\b|\bover time\b|\bhistory\b", lower):
        outputs.append(METRIC_HISTORY)

    for output, words in _TOPIC_WORDS.items():
        if _contains(lower, words):
            if output == COLLATERAL_REVIEW and "lgd" in lower and mentions_ecl \
                    and ECL_FACTOR_DECOMPOSITION in outputs:
                # "explain the LGD effect" inside an ECL bridge is the bridge's
                # recovery factor, not a separate collateral review.
                continue
            outputs.append(output)

    if asks_movement and not mentions_ecl and not outputs:
        outputs.append(MOVEMENT_BY_DIMENSION)

    request.wants_recommendations = bool(re.search(
        r"\bwhat should i\b|\brecommend\b|\bwhat to do\b|\bnext step\b|"
        r"\bpriorit\w+\b|\breview first\b|\bescalat\w+\b|\baction\b", lower))
    request.wants_expansion = bool(re.search(
        r"\bexpand\b|\bin more detail\b|\bshow the method\b|\bgo deeper\b|"
        r"\bmore detail\b", lower))

    if _NO_CHART.search(utterance):
        request.wants_chart = False
    elif _WANT_CHART.search(utterance):
        request.wants_chart = True

    # ---- dimension and measure
    for dimension in schema_mod.DIMENSIONS:
        if re.search(rf"\bby {dimension['name'].replace('_', ' ')}\b", lower) \
                or re.search(rf"\bby {dimension['label'].lower()}\b", lower):
            request.dimension = dimension["name"]
            break
    if not request.dimension and "sector" in lower:
        request.dimension = "sector"
    if not request.dimension and re.search(r"\bstage\b", lower):
        request.dimension = "stage"
    request.measure = request.measure or (
        schema_mod.resolve_measure("ECL") if mentions_ecl else "")

    borrower = re.search(r"\b(CKB-\d{4})\b", utterance, re.I)
    if borrower:
        request.entity = borrower.group(1).upper()

    # ---- deduplicate, preserving the order they were asked in
    seen: set[str] = set()
    request.outputs = [o for o in outputs
                       if not (o in seen or seen.add(o))]

    if not request.outputs:
        # Nothing matched. Rather than guess, offer the two readings that are
        # actually different — the current composition and the movement — and
        # let the user choose. A question with a selected quarter and an
        # explicit change word never reaches here.
        request.ambiguities.append({
            "question": ("Would you like the current position, or what has "
                         "changed since the previous quarter?"),
            "choices": [
                {"label": "The current position",
                 "output": COMPOSITION},
                {"label": "What changed since last quarter",
                 "output": ECL_FACTOR_DECOMPOSITION},
            ],
            "free_text": True,
        })
    return request


_TERMS: dict[str, tuple[str, str]] = {
    "ccf": ("Credit conversion factor",
            "The proportion of an undrawn commitment assumed to be drawn by "
            "the time a borrower defaults. It is what turns a limit into an "
            "exposure at default: EAD is the drawn balance plus the CCF "
            "applied to the undrawn part. Exposure and EAD are therefore "
            "different numbers, and this demo keeps them in separate fields."),
    "ecl": ("Expected credit loss",
            "The probability-weighted estimate of credit losses. Here it is "
            "the sum, over future periods and scenarios, of the marginal "
            "probability of default times the exposure at default times the "
            "loss severity, discounted back to the reporting date, weighted by "
            "scenario probability, plus any separately identified overlay."),
    "pd": ("Probability of default",
            "The chance a borrower defaults within a stated horizon. The "
            "horizon is part of the measure: a twelve-month PD and a lifetime "
            "PD are different numbers and this demo never reports one without "
            "saying which it is."),
    "lgd": ("Loss given default",
            "The proportion of exposure expected to be lost if default "
            "occurs, after recoveries and the cost and timing of realising "
            "them. Here it is built from a secured and an unsecured component "
            "weighted by recognised collateral coverage."),
    "ead": ("Exposure at default",
            "The exposure expected at the moment of default: the drawn "
            "balance plus the credit conversion factor applied to the undrawn "
            "commitment."),
    "sicr": ("Significant increase in credit risk",
             "The test that moves an account from Stage 1 to Stage 2. In this "
             "demo it fires on three or more notches of downgrade since "
             "origination, a doubling of lifetime PD above an absolute floor, "
             "or thirty days past due as a backstop."),
    "lifetime ecl": ("Lifetime ECL",
                     "Expected credit loss measured over the whole remaining "
                     "life of the instrument. Twelve-month ECL restricts the "
                     "window in which a DEFAULT may occur to twelve months; it "
                     "does not restrict the recovery cash flows that follow a "
                     "default to twelve months."),
    "twelve-month ecl": ("Twelve-month ECL",
                         "Expected credit loss from defaults that occur within "
                         "the next twelve months. The losses from such a "
                         "default may still be realised years later."),
    "stage 2": ("Stage 2",
                "An account whose credit risk has increased significantly "
                "since origination, measured on a lifetime ECL basis."),
    "overlay": ("Management overlay",
                "An adjustment to the modelled result made by management. In "
                "this demo it is identified separately at every date and is "
                "never blended into a parameter."),
    "dscr": ("Debt service coverage ratio",
             "Cash available for debt service divided by scheduled principal "
             "plus cash interest, on a twelve-month basis. A portfolio DSCR "
             "can mean the ratio of the summed components or the weighted "
             "average of borrower ratios; they are different and this demo "
             "says which it is reporting."),
}


def _definition_term(text: str) -> str:
    lower = text.lower()
    for term in sorted(_TERMS, key=len, reverse=True):
        if re.search(rf"\b{re.escape(term)}\b", lower):
            return term
    match = re.search(r"what\s+(?:is|are)\s+(?:an?\s+|the\s+)?([\w\s-]{2,40})",
                      lower)
    return match.group(1).strip(" ?.") if match else ""


def definition(term: str) -> tuple[str, str]:
    """The governed definition of a term, or empty strings."""
    return _TERMS.get(str(term).strip().lower(), ("", ""))


def known_terms() -> list[str]:
    return sorted(_TERMS)


def macro_predictor(text: str) -> str:
    lower = (text or "").lower()
    for entry in policy.MACRO_PREDICTORS:
        if entry["predictor"].replace("_", " ") in lower or \
                entry["label"].lower() in lower:
            return entry["predictor"]
    return ""


__all__ = ["ALL_OUTPUTS", "COLLATERAL_REVIEW", "COMPOSITION", "CONCENTRATION",
           "COVENANT_REVIEW", "DATA_QUALITY", "DEFINITION",
           "ECL_FACTOR_DECOMPOSITION", "MACRO_DEPENDENCY", "METRIC_HISTORY",
           "MOVEMENT_BY_DIMENSION", "PARAMETER_PRODUCT_CHECK", "PD_IMPACT",
           "RATING_REVIEW", "RATIO_MOVEMENT", "Request", "SCENARIO_COMPARISON",
           "STAGE_REVIEW", "definition", "known_terms", "macro_predictor",
           "read"]
