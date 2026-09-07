"""
Reading a scenario out of a sentence.

"What if EBITDA falls 15% and interest rates rise 200 basis points?" is two
shocks, a unit each, and a population. This module turns the sentence into the
typed `Scenario` the engine runs — and refuses to guess where the sentence does
not say.

Two rules it will not break
---------------------------
**A period is never a magnitude.** "What happens to ECL in Q1 2026 if PD rises
25%?" contains two numbers and only one of them is a shock. Time is masked out
before any magnitude is read, using the same temporal reader the analytical
planner uses, so the year can never become a percentage.

**A unit is never assumed.** "LGD increases by 10" is ambiguous between ten
percent and ten percentage points, and the two produce materially different
provisions. Percentage points are read only from an explicit "percentage
point"/"pp" and a bare percentage only from an explicit "%"/"percent"; a bare
number against LGD is read as percentage points because that is how a credit
officer says it, and the answer states which reading it took.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.orchestration import temporal
from backend.whatif import macro as mc
from backend.whatif import masterscale as ms
from backend.whatif import scenarios as sc

# ------------------------------------------------------------- the intent

#: The shapes a scenario question takes. Deliberately narrow: a question that
#: does not propose a hypothetical is not a scenario question, and answering it
#: as one would substitute an analysis nobody asked for.
_ASKS_A_SCENARIO = re.compile(
    r"\bwhat\s+if\b|\bwhat\s+happens?\s+if\b|\bwhat\s+would\s+happen\b"
    r"|\bwhat\s+happens?\s+to\b.{0,60}\bif\b"
    r"|\bif\s+.{0,60}\b(?:were|was|are|is)\s+(?:downgraded|upgraded|stressed)\b"
    r"|\bsuppose\b|\bassuming\b"
    r"|\bunder\s+(?:a|an|the)\s+.{0,40}\b(?:scenario|disruption|stress|"
    r"downside|shock|downturn|event|closure)\b"
    r"|\bif\s+.{0,50}\bnotch(?:es)?\b"
    r"|\bstress\s+(?:the\s+)?(?:book|portfolio|population)\b"
    r"|\bscenario\b.{0,20}\b(?:analysis|impact|result)\b"
    r"|\bwhat[- ]if\b|\bdowngrade\s+(?:all|every|the)\b",
    re.IGNORECASE)

#: A follow-up inside a scenario thread, which carries the previous scenario.
_CONTINUES = re.compile(
    r"\bwhich\s+(?:\w+\s+){0,3}?borrowers?\s+becomes?\b|\bwho\s+becomes?\b"
    r"|\bwhich\s+(?:\w+\s+){0,3}?borrowers?\s+breach\w*\b"
    r"|\bcustomer\s+by\s+customer\b|\bborrower\s+by\s+borrower\b"
    r"|\bwhich\s+.{0,30}\bbecome\s+most\s+vulnerable\b"
    r"|\bhow\s+much\s+(?:incremental|additional|extra)?\s*ecl\b"
    r"|\bgive\s+me\s+the\s+result\b|\bshow\s+me\s+the\s+borrowers?\b"
    r"|\bstressed\s+(?:ecl|pd|exposure)\b|\bunder\s+(?:that|this)\s+scenario\b",
    re.IGNORECASE)

# ------------------------------------------------------------- magnitudes

_NUMBER = r"(\d+(?:\.\d+)?)"
_WORD_NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
                 "a": 1, "an": 1, "half": 0.5}

_UP = re.compile(r"\b(?:rise|rises|rising|increase|increases|increasing|"
                 r"up|higher|grow|grows|worsen|worsens|deteriorat\w*|add)\b",
                 re.IGNORECASE)
_DOWN = re.compile(r"\b(?:fall|falls|falling|fell|drop|drops|decline|declines|"
                   r"decrease|decreases|down|lower|reduce|reduces|weaken|"
                   r"weakens|shrink|shrinks)\b", re.IGNORECASE)

_NOTCH = re.compile(
    r"\b(?:by\s+)?(\d+|one|two|three|four|five|a)\s*[- ]?notch(?:es)?\b",
    re.IGNORECASE)
_DOWNGRADE = re.compile(r"\bdowngrad\w*\b", re.IGNORECASE)
_UPGRADE = re.compile(r"\bupgrad\w*\b", re.IGNORECASE)

# A trailing \b after "%" never matches, because "%" is not a word character
# and neither is the "?" or the space that follows it. Four of the acceptance
# questions were lost to that one boundary, so the percent sign stands alone
# and only the spelled-out forms carry a boundary.
_BPS = re.compile(_NUMBER + r"\s*(?:bps|basis\s+points?|bp)\b", re.IGNORECASE)
#: A magnitude may be written out. "five percentage points" is how a credit
#: officer says it out loud, and refusing it because it is not "5" would be a
#: parser telling a person how to talk.
_WORD = "|".join(_WORD_NUMBERS)
_ANY_NUMBER = rf"(\d+(?:\.\d+)?|{_WORD}|half|a\s+quarter|three\s+quarters)"

_PP = re.compile(_ANY_NUMBER + r"\s*(?:pp\b|percentage\s+points?\b|ppt\b)",
                 re.IGNORECASE)
_PCT = re.compile(_NUMBER + r"\s*(?:%|per\s?cent\w*\b)", re.IGNORECASE)


#: The vocabulary the retired planner intent used to catch. A question using
#: any of these is a What-If question even when it carries no number — "stress
#: the real estate portfolio" states an intention, not a magnitude, and the
#: right response is to open a What-If and ask how hard, not to fall through to
#: a planner that no longer answers it.
_OPENS_WHATIF = re.compile(
    r"\bstress\w*\b|\bshock\w*\b|\bdownturn\b|\bscenario\b|\badverse\b"
    r"|\bsensitivit\w+|\bdownside\b|\bsevere case\b|\bwhat[- ]if\b",
    re.IGNORECASE)

#: A question about what the book ALREADY did. "Which sectors deteriorated the
#: most?" and "Which customers had a rating downgrade?" are reports: the words
#: that open a scenario — downgrade, increase, rising — appear in them as
#: history, not as instructions. Answering either with a shocked book answers a
#: question nobody asked, and silently takes the screening questions away from
#: the analysis that is certified to answer them.
#:
#: The frame is deliberately narrow: the sentence has to ASK (an interrogative
#: or a listing verb), it has to be in the past or the perfect, and it must
#: carry no hypothetical at all. A scenario survives all three — "what if
#: ratings had fallen" keeps its "what if", and "Downgrade everyone two
#: notches" never asks in the first place.
_ASKS = re.compile(
    r"^\s*(?:which|what|who|whose|whom|how\s+many|how\s+much|list|show|name|"
    r"rank|give|tell)\b", re.IGNORECASE)
_PAST_OR_PERFECT = re.compile(
    r"\b(?:saw|had|has|have|having|were|was|been|did|"
    r"deteriorated|worsened|improved|rose|fell|grew|shrank|moved|migrated|"
    r"increased|decreased|breached|defaulted|downgraded|upgraded)\b",
    re.IGNORECASE)
#: What makes a past-tense question hypothetical after all. Deliberately does
#: NOT include "stress", "shock" or "adverse" on their own: "borrowers with the
#: strongest evidence of liquidity stress" is a screening question, and a word
#: that names a CONDITION cannot also be the thing that proves a sentence is
#: about a condition that has not happened. "Under stress" can, because the
#: preposition is what makes it counterfactual.
_HYPOTHETICAL = re.compile(
    r"\bif\b|\bwere\s+to\b|\bwould\b|\bassum\w+|\bsuppose\w*\b"
    r"|\bscenario\b|\bwhat[- ]if\b|\bsimulat\w+|\bhypothetic\w+"
    r"|\bunder\s+(?:a|an|the|stress|shock|adverse|severe|downturn)\b",
    re.IGNORECASE)

#: Numbers that are part of a NAME, not the size of a movement. "12-month PD"
#: names a measure, "Stage 2" names a stage, and "four quarters ago" names a
#: date. Masked before any magnitude is read, the same way a period is.
_TERM_OF_ART = re.compile(
    r"\b\d+\s*[- ]?\s*(?:month|year|day)s?\b"
    r"|\bstage\s*\d\b"
    r"|\b(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten)\s+"
    r"(?:quarter|year|month)s?\s+(?:ago|earlier|back|before)\b",
    re.IGNORECASE)

#: Words that turn a movement verb into a movement NOUN. "rank sectors by the
#: largest increase" reports one; "increase PD by 20%" instructs one. Without
#: this the reader answers a ranking question with a shocked book.
#: A determiner or a superlative makes it a noun — "the largest increase". So
#: does a preposition: "ranked BY increase", "an increase IN ECL". A conjunction
#: does not, because "reduce collateral and increase PD" is still two
#: instructions.
_NOMINAL_BEFORE = re.compile(
    r"(?:\b(?:the|a|an|its|their|our|this|that|those|these|any|no|net|"
    r"largest|biggest|greatest|smallest|sharp|sharpest|recent|same|"
    r"total|average|overall|percentage|"
    r"by|in|of|for|with|on|from|per|about)\s+)$", re.IGNORECASE)


#: An auxiliary turns a movement verb into a REPORT of something that already
#: happened. "Shipping has deteriorated" states a fact about the book;
#: "deteriorate the Shipping book" instructs one. Without this, adding
#: "deteriorate" to the credit moves routed a segment-review question — "Shipping
#: has deteriorated. Show me everything." — into the scenario engine, which
#: answered it with one What-If instead of the named set of ten analyses that
#: review is.
_AUXILIARY_BEFORE = re.compile(
    r"\b(?:has|have|had|is|are|was|were|been|being|already|recently|"
    r"materially|significantly|further|which|that|who|since|after|when)\s+"
    r"(?:\w+\s+){0,2}$", re.IGNORECASE)


def _instructs(text: str, pattern: re.Pattern[str]) -> bool:
    """True when the verb is used as a verb, not as a noun or a report."""
    for found in pattern.finditer(text):
        before = text[:found.start()]
        if _NOMINAL_BEFORE.search(before) or _AUXILIARY_BEFORE.search(before):
            continue
        return True
    return False

#: A plain instruction. "Increase Stage 1 PD by 20%" is a What-If — it just
#: does not phrase itself as a question. Requiring "what if" would refuse the
#: most direct way a credit officer states a scenario.
#: Verbs that can only mean a credit move. "Downgrade the BBB names" is a
#: scenario with or without a notch count, so these open a What-If on their own
#: and the product asks how far.
#: "worsen" and "deteriorate" sit here rather than in `_OPENS_WHATIF`, and the
#: difference is the participle. "Worsen the macro outlook" is an instruction;
#: "show me the top ten DETERIORATING borrowers" is a screening question about
#: what the book already did, and putting the word in the unconditional list
#: turned that question into a scenario. `_instructs` is what tells them apart,
#: so the verbs belong where it is consulted.
_CREDIT_MOVE = re.compile(
    r"\b(?:downgrade[sd]?|upgrade[sd]?|cure[sd]?|migrate[sd]?"
    r"|worsen(?:s|ed)?|deteriorate[sd]?)\b",
    re.IGNORECASE)

#: Verbs that move SOMETHING, but not necessarily a risk parameter. "Add their
#: latest internal rating" adds a column to the answer on screen; "add 20% to
#: PD" adds to a risk parameter. Without a size these are enrichment, not a
#: scenario, and reading them as one takes a thread's follow-up away from the
#: conversation that owns it.
#: "weaken" and "strengthen" sit here rather than with the credit moves: a
#: screening question asks which borrowers ARE weakening, and only a scenario
#: says by how much.
_MOVES = re.compile(
    r"\b(?:increase|decrease|raise|reduce|lower|cut|add|apply|set|move|"
    r"shift|widen|narrow|weaken\w*|strengthen\w*)\b", re.IGNORECASE)

#: A bare direction. Only counts as an instruction when a size is present too,
#: because "PD is down" is an observation and "PD down 20%" is a scenario.
_DIRECTED = re.compile(
    r"\b(?:up|down|rise[sn]?|rose|rising|fall[sn]?|fell|falling|higher|lower|"
    r"widen\w*|narrow\w*|weaken\w*|strengthen\w*)\b", re.IGNORECASE)
_HAS_MAGNITUDE = re.compile(
    r"\d|\bnotch\w*\b|\bhalf\b|\bquarter\b|\b(?:one|two|three|four|five|"
    r"six|seven|eight|nine|ten)\b", re.IGNORECASE)

#: Severity words the old presets were selected by. "Use the severe scenario"
#: named a preset that no longer exists on this path, so the word is read as a
#: severity the person wants rather than left unmatched.
_SEVERITY = {
    "base": "base", "mild": "mild", "light": "mild", "moderate": "moderate",
    "severe": "severe", "extreme": "severe", "harsh": "severe",
}
_SEVERITY_WORD = re.compile(
    r"\b(base|mild|light|moderate|severe|extreme|harsh)\b", re.IGNORECASE)


@dataclass
class Reading:
    """What the sentence said, and what could not be read from it."""

    scenario: sc.Scenario | None = None
    is_scenario_question: bool = False
    continues_previous: bool = False
    objective: str = "summary"
    unread: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    #: The question belongs to What-If but does not yet describe a runnable
    #: scenario. The product should OPEN a What-If and ask, never fall through.
    opens_whatif: bool = False
    #: A severity the question named without giving a magnitude.
    severity: str = ""

    def to_dict(self) -> dict[str, Any]:  # noqa: D102
        return {
            "is_scenario_question": self.is_scenario_question,
            "continues_previous": self.continues_previous,
            "objective": self.objective,
            "scenario": self.scenario.to_dict() if self.scenario else None,
            "unread": list(self.unread),
            "notes": list(self.notes),
        }


#: What the question wants OUT of the scenario, as opposed to what it puts in.
SUMMARY = "summary"
BORROWERS = "borrowers"
MIGRATIONS = "migrations"
TOP = "top_contributors"
SECTOR = "by_sector"
COVENANTS = "covenants"

_OBJECTIVE: tuple[tuple[str, str], ...] = (
    (r"\bcustomer\s+by\s+customer\b|\bborrower\s+by\s+borrower\b"
     r"|\bname\s+by\s+name\b|\beach\s+borrower\b|\bevery\s+borrower\b"
     r"|\blist\s+(?:the\s+)?borrowers?\b|\bgive\s+me\s+the\s+result\b", BORROWERS),
    (r"\bbecomes?\s+stage\s*2\b|\bmove\s+to\s+stage\s*2\b|\bmigrat\w*\b"
     r"|\bstage\s*1\b.{0,40}\bstage\s*2\b|\bbecomes?\s+stage\b", MIGRATIONS),
    (r"\bbreach\w*\s+covenants?\b|\bcovenant\s+breach\w*\b", COVENANTS),
    (r"\blargest\b.{0,30}\bincrease\b|\bmost\s+vulnerable\b|\btop\s+\d+\b"
     r"\b|\bbiggest\s+contributors?\b|\bworst\s+affected\b", TOP),
    (r"\bby\s+sector\b|\bwhich\s+sectors?\b|\bsector\s+impact\b", SECTOR),
)
_OBJECTIVE_COMPILED = tuple((re.compile(p, re.IGNORECASE), o)
                            for p, o in _OBJECTIVE)

#: The one phrase that turns the optional rating-deterioration SICR assumption
#: on. Nothing else does, because an assumption applied because the question
#: sounded like it wanted one is an assumption nobody made.
_ASSUME_RATING_SICR = re.compile(
    r"\bassum\w*\b.{0,60}\b(?:downgrade|notch|rating)\w*.{0,40}\b"
    r"(?:sicr|significant\s+increase|stage\s*2)\b"
    r"|\b(?:apply|applying|with)\b.{0,30}\brating[- ]deterioration\b"
    r"|\btreat\w*\b.{0,40}\bdowngrade\b.{0,40}\b(?:sicr|stage\s*2)\b",
    re.IGNORECASE)


def _word_number(said: str) -> float:
    """A magnitude however it was written — "5", "five", or "half"."""
    text = str(said or "").strip().lower()
    if text in ("half", "a half"):
        return 50.0
    if text in ("a quarter",):
        return 25.0
    if text in ("three quarters",):
        return 75.0
    if text in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[text])
    try:
        return float(text)
    except ValueError:
        return 1.0


def _word_number_original(said: str) -> float:
    said = said.strip().lower()
    if said in _WORD_NUMBERS:
        return float(_WORD_NUMBERS[said])
    try:
        return float(said)
    except ValueError:  # pragma: no cover - the pattern only matches numbers
        return 0.0


def _direction(text: str, at: int, window: int = 60) -> int:
    """Whether the movement near `at` is up (+1) or down (-1).

    Where both a rise and a fall appear — "EBITDA falls 15% and rates rise 200
    bps" — the nearer one wins. The offset of `at` inside the window has to be
    computed rather than assumed: near the start of a sentence the window is
    clipped, and assuming the anchor sits in the middle of it read "EBITDA
    falls" as a rise, which silently dropped the shock.
    """
    start = max(0, at - window)
    around = text[start: at + window]
    anchor = at - start
    down = _DOWN.search(around)
    up = _UP.search(around)
    if down and not up:
        return -1
    if up and not down:
        return 1
    if down and up:
        return -1 if abs(down.start() - anchor) <= abs(up.start() - anchor) else 1
    return 1


#: Amounts a person writes: "SAR 100m", "100 million", "1.5bn", "50m".
_AMOUNT = re.compile(
    r"(?:sar\s*)?(\d+(?:\.\d+)?)\s*(m|mn|million|bn|billion|k|thousand)?\b",
    re.IGNORECASE)
_MULTIPLIER = {"m": 1.0, "mn": 1.0, "million": 1.0,
               "bn": 1000.0, "billion": 1000.0,
               "k": 0.001, "thousand": 0.001}

#: The fields a person filters on by name, and the column each one is.
_FILTER_FIELD: tuple[tuple[str, str, str], ...] = (
    (r"\bexposure(?:\s+at\s+default)?\b|\bead\b", "ead", "SAR mn"),
    (r"\bdrawn(?:\s+exposure)?\b|\boutstanding\b", "drawn_exposure", "SAR mn"),
    (r"\bundrawn\b|\bheadroom\b", "undrawn_commitment", "SAR mn"),
    (r"\breported\s+ecl\b|\bprovision\b|\becl\b", "final_ecl", "SAR mn"),
    (r"\blifetime\s+pd\b", "pd_lifetime", "%"),
    (r"\b(?:12|twelve)[- ]month\s+pd\b|\bpd\b", "pd_12m", "%"),
    (r"\blgd\b|\bloss\s+given\s+default\b", "lgd", "%"),
    (r"\bcoverage\b", "ecl_coverage", "%"),
    (r"\bcollateral\s+coverage\b", "collateral_coverage_pct", "%"),
    (r"\bleverage\b", "leverage", ""),
    (r"\bdscr\b", "dscr", ""),
)

#: How a comparison is written. Ordered so "at least" beats "least".
_COMPARISON: tuple[tuple[str, str], ...] = (
    (r"\bat\s+least\b|\bno\s+less\s+than\b|\bor\s+more\b|\b>=\b", "at least"),
    (r"\bat\s+most\b|\bno\s+more\s+than\b|\bor\s+less\b|\b<=\b", "at most"),
    (r"\babove\b|\bover\b|\bgreater\s+than\b|\bmore\s+than\b|\bexceed\w*\b|\b>\b", "above"),
    (r"\bbelow\b|\bunder\b|\bless\s+than\b|\bsmaller\s+than\b|\b<\b", "below"),
)

#: "top 20 borrowers by EAD", "largest 50 by exposure".
_TOP_N = re.compile(
    r"\b(?:top|largest|biggest|highest)\s+(\d{1,4})\b", re.IGNORECASE)

#: What people call a sector when it is not what the book calls it. The book's
#: own names win; this only rescues a question that would otherwise silently
#: match nothing and widen to the whole book.
_SECTOR_SYNONYM: dict[str, str] = {
    "construction": "Contracting",
    "builders": "Contracting",
    "building": "Contracting",
    "infrastructure": "Contracting",
    "property": "Real Estate",
    "realty": "Real Estate",
    "retail": "Wholesale & Retail Trade",
    "wholesale": "Wholesale & Retail Trade",
    "trade": "Wholesale & Retail Trade",
    "logistics": "Transport & Logistics",
    "transport": "Transport & Logistics",
    "transportation": "Transport & Logistics",
    "shipping": "Shipping",
    "marine": "Shipping",
    "petchem": "Petrochemicals",
    "chemicals": "Petrochemicals",
    "oil": "Oil & Gas",
    "gas": "Oil & Gas",
    "energy": "Oil & Gas",
    "power": "Utilities",
    "utility": "Utilities",
    "telecom": "Telecommunications",
    "telco": "Telecommunications",
    "banks": "Financial Services",
    "financials": "Financial Services",
    "hotels": "Hospitality & Tourism",
    "hospitality": "Hospitality & Tourism",
    "tourism": "Hospitality & Tourism",
    "mining": "Mining & Metals",
    "metals": "Mining & Metals",
    "agriculture": "Agriculture & Food",
    "food": "Agriculture & Food",
    "farming": "Agriculture & Food",
    "health": "Healthcare",
    "hospitals": "Healthcare",
    "schools": "Education",
    "government": "Government-Related Entities",
    "public sector": "Government-Related Entities",
    "gre": "Government-Related Entities",
    "manufacturers": "Manufacturing",
    "industrial": "Manufacturing",
}


def _amount(said: str, unit: str) -> float | None:
    """The number a filter names, in the book's own units.

    The book is denominated in SAR MILLIONS, so "SAR 100m" is 100 and
    "1.5 billion" is 1,500. A percentage is itself.
    """
    found = _AMOUNT.search(said)
    if not found:
        return None
    value = float(found.group(1))
    scale = (found.group(2) or "").lower()
    if unit == "SAR mn":
        return value * _MULTIPLIER.get(scale, 1.0)
    return value


def _thresholds(text: str) -> tuple[list[sc.Threshold], list[str]]:
    """Every numeric filter the sentence states, and anything it could not read.

    Read from CLAUSES rather than from the whole sentence, because "exposure
    above SAR 100m by two notches" contains two numbers and only one of them
    is the filter. A clause is the run of words around a comparison word, and
    the field and the amount both have to be inside it.
    """
    out: list[sc.Threshold] = []
    unread: list[str] = []
    for pattern, operator in _COMPARISON:
        for found in re.finditer(pattern, text, re.IGNORECASE):
            # 48 characters either side: enough for "exposure at default of
            # more than SAR 100 million", short enough not to reach the shock.
            before = text[max(0, found.start() - 48): found.start()]
            after = text[found.end(): found.end() + 48]
            field, unit = "", ""
            for field_pattern, name, field_unit in _FILTER_FIELD:
                if re.search(field_pattern, before, re.IGNORECASE):
                    field, unit = name, field_unit
                    break
            if not field:
                continue
            value = _amount(after, unit)
            if value is None:
                unread.append(
                    f"a filter on {sc.LABELS.get(field, field)} "
                    f"{operator} an amount that was not given")
                continue
            if not any(t.field == field for t in out):
                out.append(sc.Threshold(field=field, operator=operator,
                                        value=value, unit=unit))
    return out, unread


def _population(text: str) -> tuple[sc.Population, list[str]]:
    """Who the scenario applies to, from the governed vocabulary."""
    notes: list[str] = []
    lowered = text.lower()

    bands: list[str] = []
    for band in ("investment grade", "sub-investment grade", "speculative grade"):
        if band in lowered:
            bands.append(band)
    if not bands:
        for grade in sorted(ms.BANDS, key=len, reverse=True):
            if grade in ("investment grade", "sub-investment grade",
                         "speculative grade"):
                continue
            # Case-SENSITIVE on purpose: "under a logistics disruption" is
            # not an A-rated population, and reading the article as a grade
            # silently narrowed a whole-book scenario to one grade.
            if re.search(rf"\b{re.escape(grade)}\b", text):
                bands.append(grade)
                break

    sectors: list[str] = []
    from backend.orchestration import vocabulary as vc
    try:
        known = vc.get_vocabulary().dimensions.get("sector", [])
    except Exception:  # noqa: BLE001 - a scenario without a sector is still a
        # scenario, and failing to read the vocabulary must not lose the answer
        known = []
    for name in known:
        if re.search(rf"\b{re.escape(str(name))}\b", text, re.IGNORECASE):
            sectors.append(str(name))

    stages: list[int] = []
    for found in re.finditer(r"\bstage\s*([123])\b", text, re.IGNORECASE):
        stages.append(int(found.group(1)))
    # "which Stage 1 borrowers become Stage 2" names the population once and
    # the OUTCOME once. The population is the first, and the second is what the
    # question is asking for rather than what it is filtering on.
    if len(stages) > 1:
        stages = stages[:1]
        notes.append("The second Stage named is the outcome asked about, not a "
                     "filter on the population.")

    # A sector the book calls something else. Only consulted when the book's
    # own names matched nothing, so "Real Estate" always beats "property".
    if not sectors:
        for word, name in sorted(_SECTOR_SYNONYM.items(),
                                 key=lambda kv: len(kv[0]), reverse=True):
            if re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE):
                sectors.append(name)
                notes.append(f"Read '{word}' as the {name} sector.")
                break

    ids = [m.group(0).upper()
           for m in re.finditer(r"\b(?:CORP|SA)-\d+\b", text, re.IGNORECASE)]
    watchlist = bool(re.search(r"\bwatchlist\b", text, re.IGNORECASE))

    thresholds, unread = _thresholds(text)
    notes.extend(f"Could not read {u}." for u in unread)

    top_n, top_by = 0, "ead"
    found = _TOP_N.search(text)
    if found:
        top_n = int(found.group(1))
        after = text[found.end(): found.end() + 60]
        for field_pattern, name, _unit in _FILTER_FIELD:
            if re.search(field_pattern, after, re.IGNORECASE):
                top_by = name
                break

    return sc.Population(sectors=tuple(sectors), rating_bands=tuple(bands),
                         stages=tuple(stages), borrower_ids=tuple(ids),
                         watchlist_only=watchlist,
                         thresholds=tuple(thresholds),
                         top_n=top_n, top_by=top_by), notes


#: Words that name a DIFFERENT BOOK. This engine reads Corporate IFRS 9 and
#: nothing else, and the corporate sector names share words with the retail and
#: SME books: "downgrade the retail mortgage book by two notches" resolved
#: "retail" to the Wholesale & Retail Trade SECTOR and priced a corporate
#: scenario, which is a wrong answer wearing the shape of a right one.
#:
#: Matched before any sector is read, so a question about another book is
#: refused rather than mapped.
_ANOTHER_BOOK = re.compile(
    r"\bretail\s+(?:mortgage|loan|book|portfolio|customer|lending|banking)"
    r"|\bmortgage\b|\bcredit\s+card\b|\bcards?\s+book\b"
    r"|\bpersonal\s+loan|\bauto\s+loan|\bconsumer\s+(?:loan|book|lending)"
    r"|\bsme\s+(?:book|portfolio|scorecard|customer)|\bmicrofinance\b"
    r"|\bapplication\s+scorecard|\bbehavioural?\s+scorecard",
    re.IGNORECASE)

OTHER_BOOK_NOTE = (
    "That names a different book. What-If Analysis reads the Corporate IFRS 9 "
    "domain only, and the retail, SME and card books are measured on their own "
    "scales, their own staging rules and their own models. Answering from the "
    "corporate book because the words overlap would give you a confident "
    "number about the wrong portfolio.")


#: "Move half the Stage 1 borrowers to Stage 2", "Stage 2 to Stage 3",
#: "move 30% of Stage 2 back to Stage 1".
_STAGE_MOVE = re.compile(
    r"stage\s*(?P<from>[123])\b.{0,40}?\b(?:to|into|back\s+to)\s+stage\s*"
    r"(?P<to>[123])\b", re.IGNORECASE)

#: How much of a population moves. "half" is a share people actually say.
_SHARE = re.compile(
    r"\b(half|a\s+quarter|three\s+quarters|\d+(?:\.\d+)?)\s*(?:%|per\s?cent)?"
    r"\s*(?:of\s+)?", re.IGNORECASE)

#: The ten governed macro variables, by the words people use for them. Ordered
#: so a more specific name is tried before a more general one — "house prices"
#: before "prices", "credit spread" before "spread".
_MACRO_SPOKEN: tuple[tuple[str, str], ...] = (
    (r"\bunemployment\b|\bjobless\w*\b", "unemployment"),
    (r"\bhouse\s+price\w*\b|\bproperty\s+price\w*\b|\bhpi\b"
     r"|\bhousing\b|\breal\s+estate\s+price\w*\b", "house_price_index"),
    (r"\bcurrent\s+account\b|\bexternal\s+balance\b", "current_account"),
    (r"\bstock\s+market\b|\bequit\w+\b|\bshare\s+price\w*\b"
     r"|\btadawul\b", "equity_index"),
    (r"\bcredit\s+spread\w*\b|\bcorporate\s+spread\w*\b", "credit_spread"),
    (r"\bcurrency\b|\bfx\b|\bexchange\s+rate\b|\bdepreciat\w+\b"
     r"|\briyal\b", "fx_depreciation"),
    (r"\binflation\b|\bcpi\b", "inflation"),
    (r"\bgdp\b|\breal\s+gdp\b", "gdp_growth"),
    (r"\boil\b|\bcrude\b|\bbrent\b", "oil_price"),
    (r"\bpolicy\s+rate\w*\b", "policy_rate"),
)


def _shocks(text: str) -> tuple[list[sc.Shock], list[str], list[str]]:
    """Every shock the sentence states, with its unit read explicitly."""
    shocks: list[sc.Shock] = []
    notes: list[str] = []
    unread: list[str] = []
    lowered = text.lower()

    # ---- rating
    notch = _NOTCH.search(text)
    if notch:
        count = _word_number(notch.group(1))
        sign = -1 if _UPGRADE.search(text) and not _DOWNGRADE.search(text) else 1
        shocks.append(sc.Shock(sc.RATING, sign * count, sc.NOTCHES))
    elif _DOWNGRADE.search(text):
        shocks.append(sc.Shock(sc.RATING, 1, sc.NOTCHES))
        notes.append("No notch count was given, so a one-notch downgrade was "
                     "applied.")
    elif _UPGRADE.search(text):
        shocks.append(sc.Shock(sc.RATING, -1, sc.NOTCHES))

    # ---- a Stage migration somebody asked for outright
    stage_move = _STAGE_MOVE.search(text)
    if stage_move:
        start, end = int(stage_move.group("from")), int(stage_move.group("to"))
        share = _SHARE.search(text)
        size = _word_number(share.group(1)) if share else 100.0
        if share and share.group(0).strip().lower() in ("half", "a half"):
            size = 50.0
        shocks.append(sc.Shock(sc.STAGE, size, sc.RELATIVE,
                               target=f"{start}->{end}"))
        if not share:
            notes.append(
                f"No share was given, so every Stage {start} borrower in the "
                f"population was moved to Stage {end}.")

    # ---- credit conversion factor
    if re.search(r"\bccf\b|\bcredit\s+conversion\s+factor\b", text,
                 re.IGNORECASE):
        found = _PCT.search(text) or _PP.search(text)
        if found:
            size = _word_number(found.group(1)) * _direction(text, found.start())
            unit = sc.RELATIVE if found.re is _PCT else sc.ABSOLUTE_PP
            shocks.append(sc.Shock(sc.CCF, size, unit))
        else:
            unread.append("a CCF movement with no size given")

    # ---- the ten governed macro variables, by the names people use
    for spoken, key in _MACRO_SPOKEN:
        if key in {s.target for s in shocks}:
            continue
        if not re.search(spoken, text, re.IGNORECASE):
            continue
        variable = mc.BY_KEY[key]
        bps = _BPS.search(text)
        pp = _PP.search(text)
        percent = _PCT.search(text)
        if variable.unit == "basis points" and bps:
            size = _word_number(bps.group(1)) * _direction(text, bps.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.BASIS_POINTS, target=key))
        elif variable.unit == "percent" and percent:
            size = _word_number(percent.group(1)) * _direction(text, percent.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.RELATIVE, target=key))
        elif pp:
            size = _word_number(pp.group(1)) * _direction(text, pp.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.ABSOLUTE_PP, target=key))
        elif percent:
            size = _word_number(percent.group(1)) * _direction(text, percent.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.RELATIVE, target=key))
        else:
            unread.append(f"a {variable.name} movement with no size given")

    # ---- macro variables, each with its own unit
    if re.search(r"\b(?:interest\s+)?rates?\b|\bpolicy\s+rate\b", text,
                 re.IGNORECASE):
        bps = _BPS.search(text)
        pp = _PP.search(text)
        if bps:
            size = _word_number(bps.group(1)) * _direction(text, bps.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.BASIS_POINTS, target="rates"))
        elif pp:
            size = _word_number(pp.group(1)) * 100.0 * _direction(text, pp.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.BASIS_POINTS, target="rates"))
        else:
            unread.append("a rate movement with no size given")

    if re.search(r"\bdisruption\b|\bport\s+closure\b|\bfreight\b"
                 r"|\bsupply\s+chain\b|\broute\s+closure\b",
                 text, re.IGNORECASE):
        shocks.append(sc.Shock(sc.MACRO, 2.0, sc.STEPS,
                               target="shipping_disruption"))
    if re.search(r"\boil\b|\bcrude\b|\bcommodity\s+price", text, re.IGNORECASE):
        pct = _PCT.search(text)
        size = -_word_number(pct.group(1)) if pct else -20.0
        if not pct:
            notes.append("No size was given for the oil move, so the "
                         "configured 20% downside was applied.")
        shocks.append(sc.Shock(sc.MACRO, size, sc.RELATIVE, target="oil"))
    if re.search(r"\bgdp\b|\brecession\b|\bdemand\s+shock\b", text, re.IGNORECASE):
        pp = _PP.search(text)
        size = -_word_number(pp.group(1)) if pp else -1.0
        shocks.append(sc.Shock(sc.MACRO, size, sc.ABSOLUTE_PP, target="gdp"))
    if re.search(r"\binflation\b", text, re.IGNORECASE):
        pp = _PP.search(text)
        shocks.append(sc.Shock(sc.MACRO, _word_number(pp.group(1)) if pp else 1.0,
                               sc.ABSOLUTE_PP, target="inflation"))

    # ---- PD
    if re.search(r"\bpd\b|\bprobability\s+of\s+default\b", text, re.IGNORECASE):
        anchor = re.search(r"\bpd\b|\bprobability\s+of\s+default\b", text,
                           re.IGNORECASE)
        pct = _PCT.search(text)
        pp = _PP.search(text)
        bps = _BPS.search(text)
        if pct:
            shocks.append(sc.Shock(sc.PD, _word_number(pct.group(1))
                                   * _direction(text, pct.start()), sc.RELATIVE))
        elif pp:
            shocks.append(sc.Shock(sc.PD, _word_number(pp.group(1))
                                   * _direction(text, pp.start()), sc.ABSOLUTE_PP))
        elif bps:
            shocks.append(sc.Shock(sc.PD, _word_number(bps.group(1))
                                   * _direction(text, bps.start()), sc.BASIS_POINTS))
        elif anchor and not any(s.kind == sc.RATING for s in shocks):
            unread.append("a PD movement with no size given")

    # ---- LGD
    if re.search(r"\blgd\b|\bloss\s+given\s+default\b", text, re.IGNORECASE):
        pp = _PP.search(text)
        pct = _PCT.search(text)
        bare = re.search(r"\blgd\b\s+\w*\s*(?:by\s+)?" + _NUMBER, text,
                         re.IGNORECASE)
        if pp:
            shocks.append(sc.Shock(sc.LGD, _word_number(pp.group(1))
                                   * _direction(text, pp.start()), sc.ABSOLUTE_PP))
        elif pct:
            shocks.append(sc.Shock(sc.LGD, _word_number(pct.group(1))
                                   * _direction(text, pct.start()), sc.RELATIVE))
        elif bare:
            shocks.append(sc.Shock(sc.LGD, float(bare.group(1))
                                   * _direction(text, bare.start()), sc.ABSOLUTE_PP))
            notes.append("LGD was read in percentage points, which is how a "
                         "credit officer states it. Say '10%' for a relative "
                         "move.")
        else:
            unread.append("an LGD movement with no size given")

    # ---- exposure and utilisation
    if re.search(r"\butilisation\b|\butilization\b|\bead\b|\bdrawdown\b"
                 r"|\bexposure\s+at\s+default\b|\bundrawn\b", text, re.IGNORECASE):
        moves = bool(_UP.search(text) or _DOWN.search(text))
        pct = _PCT.search(text)
        if pct and moves:
            shocks.append(sc.Shock(sc.EAD, _word_number(pct.group(1))
                                   * _direction(text, pct.start()), sc.RELATIVE))
        elif moves:
            shocks.append(sc.Shock(sc.EAD, 15.0, sc.RELATIVE))
            notes.append("No size was given for the drawdown, so the "
                         "configured 15% utilisation stress was applied.")

    # ---- collateral
    if re.search(r"\bcollateral\b|\bsecurity\s+value\b|\bproperty\s+value",
                 text, re.IGNORECASE):
        pct = _PCT.search(text)
        if pct:
            size = _word_number(pct.group(1)) * _direction(text, pct.start())
            shocks.append(sc.Shock(sc.COLLATERAL, size, sc.RELATIVE))
        else:
            unread.append("a collateral movement with no size given")

    # ---- financial measures
    for measure, pattern in (("ebitda", r"\bebitda\b"),
                             ("revenue", r"\brevenue\b|\bturnover\b|\bsales\b"),
                             ("free_cash_flow", r"\bcash\s?flow\b")):
        found = re.search(pattern, text, re.IGNORECASE)
        if not found:
            continue
        after = text[found.end(): found.end() + 60]
        pct = _PCT.search(after) or _PCT.search(text)
        if pct:
            size = _word_number(pct.group(1)) * _direction(text, found.start())
            shocks.append(sc.Shock(sc.FINANCIAL, size, sc.RELATIVE, target=measure))
        else:
            unread.append(f"an {measure.replace('_', ' ')} movement with no "
                          "size given")

    if "sector" in lowered and re.search(r"\bdeteriorat\w*\b|\bstress\w*\b",
                                         lowered) and not shocks:
        shocks.append(sc.Shock(sc.MACRO, 2.0, sc.STEPS, target="sector_stress"))

    return _deduplicate(shocks), notes, unread


#: The older sensitivity matrix's keys, and the governed variable each one is
#: really about. A sentence like "oil price down 20%" matches both readers, and
#: applying it twice would double the shock.
_LEGACY_MACRO: dict[str, str] = {
    "rates": "policy_rate", "oil": "oil_price", "gdp": "gdp_growth",
    "inflation": "inflation", "property": "house_price_index",
    "fx": "fx_depreciation",
}


def _deduplicate(shocks: list[sc.Shock]) -> list[sc.Shock]:
    """One shock per concept, keeping the governed reading.

    Both the governed ten and the older matrix can recognise the same
    sentence. Left alone that produces two macro shocks for one instruction
    and the engine applies both, so the answer is the square of what was
    asked for.
    """
    governed = {s.target for s in shocks
                if s.kind == sc.MACRO and s.target not in _LEGACY_MACRO}
    out: list[sc.Shock] = []
    for shock in shocks:
        if (shock.kind == sc.MACRO
                and _LEGACY_MACRO.get(shock.target) in governed):
            continue
        out.append(shock)
    return out


def read(question: str) -> Reading:
    """The scenario a question describes, or a reading that says it is not one."""
    said = str(question or "").strip()
    if not said:
        return Reading()

    is_scenario = bool(_ASKS_A_SCENARIO.search(said))
    continues = bool(_CONTINUES.search(said))
    # A direction plus a size is an instruction too: "oil price down 20%" and
    # "policy rates up 200 bps" are how these are actually written, and neither
    # carries a verb.
    #
    # The size is looked for with TIME MASKED OUT. "Which customers were
    # downgraded and had ECL rise in Q1 2026?" is a question about what already
    # happened; reading the year as a magnitude turned it into a scenario and
    # answered a question nobody asked.
    sized = _TERM_OF_ART.sub(" ", temporal.without_time(said))
    directed = bool(_DIRECTED.search(said) and _HAS_MAGNITUDE.search(sized))
    opens = bool(_OPENS_WHATIF.search(said)
                 or _instructs(said, _CREDIT_MOVE)
                 or (_instructs(said, _MOVES) and _HAS_MAGNITUDE.search(sized))
                 or directed)
    # A report is never a scenario, however many scenario words it borrows.
    reports = bool(_ASKS.search(said)
                   and _PAST_OR_PERFECT.search(said)
                   and not _HYPOTHETICAL.search(said))
    if reports:
        return Reading(notes=["Read as a question about what the book already "
                              "did, not as a What-If."])
    if _ANOTHER_BOOK.search(said):
        return Reading(notes=[OTHER_BOOK_NOTE], unread=[said])
    reading = Reading(is_scenario_question=is_scenario or continues or opens,
                      continues_previous=continues and not is_scenario,
                      opens_whatif=opens)
    severity = _SEVERITY_WORD.search(said)
    if severity:
        reading.severity = _SEVERITY[severity.group(1).lower()]

    for pattern, objective in _OBJECTIVE_COMPILED:
        if pattern.search(said):
            reading.objective = objective
            break

    if not reading.is_scenario_question:
        return reading

    # A period is a period. Mask it before a single magnitude is read.
    magnitudes_from = temporal.without_time(said)
    shocks, notes, unread = _shocks(magnitudes_from)
    population, population_notes = _population(said)
    reading.notes = notes + population_notes
    reading.unread = unread

    if not shocks:
        if reading.continues_previous:
            return reading
        if reading.opens_whatif:
            # A What-If question with no magnitude. The product opens the
            # conversation and asks; it does not hand the question back.
            reading.notes.append(
                "This is a What-If question, but it does not yet say how big "
                "the movement is. Opening a What-If to ask."
                + (f" A '{reading.severity}' severity was named."
                   if reading.severity else ""))
            return reading
        reading.unread.append("no shock could be read from the question")
        return reading

    window = temporal.read(said)
    period = str(window.texts()[-1]) if window.any else ""

    assumptions = sc.Assumptions()
    asked_for_assumption = bool(_ASSUME_RATING_SICR.search(said))
    if asked_for_assumption:
        notches = max((abs(int(s.magnitude)) for s in shocks
                       if s.kind == sc.RATING), default=1)
        assumptions = sc.Assumptions(rating_deterioration_sicr=True,
                                     rating_sicr_notches=max(1, notches))
        reading.notes.append(
            f"The rating-deterioration SICR assumption was applied as asked: a "
            f"fall of {notches} notch(es) is treated as a significant increase "
            "in credit risk on its own, in addition to the governed PD and "
            "days-past-due triggers.")
    elif reading.objective == MIGRATIONS and any(s.kind == sc.RATING
                                                 for s in shocks):
        reading.notes.append(
            "Staging was re-evaluated against the governed SICR triggers, not "
            "against the downgrade itself — a notch is not a SICR trigger in "
            "this policy. Ask again with \"assume a downgrade is a "
            "significant increase in credit risk\" to see the population "
            "under that assumption.")

    reading.scenario = sc.Scenario(
        key="ad_hoc", name=_name(shocks, population), shocks=tuple(shocks),
        population=population, assumptions=assumptions, severity="custom",
        rationale=f"Composed from the question: {said}", period=period)
    return reading


def _name(shocks: list[sc.Shock], population: sc.Population) -> str:
    parts = [shock.describe() for shock in shocks]
    body = " with ".join(parts) if len(parts) > 1 else (parts[0] if parts else "")
    who = population.describe()
    return f"{body.capitalize()} — {who}" if body else who


__all__ = ["BORROWERS", "COVENANTS", "MIGRATIONS", "Reading", "SECTOR",
           "SUMMARY", "TOP", "read"]
