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
_PP = re.compile(_NUMBER + r"\s*(?:pp\b|percentage\s+points?\b|ppt\b)",
                 re.IGNORECASE)
_PCT = re.compile(_NUMBER + r"\s*(?:%|per\s?cent\w*\b)", re.IGNORECASE)


@dataclass
class Reading:
    """What the sentence said, and what could not be read from it."""

    scenario: sc.Scenario | None = None
    is_scenario_question: bool = False
    continues_previous: bool = False
    objective: str = "summary"
    unread: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
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

    ids = [m.group(0).upper()
           for m in re.finditer(r"\b(?:CORP|SA)-\d+\b", text, re.IGNORECASE)]
    watchlist = bool(re.search(r"\bwatchlist\b", text, re.IGNORECASE))

    return sc.Population(sectors=tuple(sectors), rating_bands=tuple(bands),
                         stages=tuple(stages), borrower_ids=tuple(ids),
                         watchlist_only=watchlist), notes


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

    # ---- macro variables, each with its own unit
    if re.search(r"\b(?:interest\s+)?rates?\b|\bpolicy\s+rate\b", text,
                 re.IGNORECASE):
        bps = _BPS.search(text)
        pp = _PP.search(text)
        if bps:
            size = float(bps.group(1)) * _direction(text, bps.start())
            shocks.append(sc.Shock(sc.MACRO, size, sc.BASIS_POINTS, target="rates"))
        elif pp:
            size = float(pp.group(1)) * 100.0 * _direction(text, pp.start())
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
        size = -float(pct.group(1)) if pct else -20.0
        if not pct:
            notes.append("No size was given for the oil move, so the "
                         "configured 20% downside was applied.")
        shocks.append(sc.Shock(sc.MACRO, size, sc.RELATIVE, target="oil"))
    if re.search(r"\bgdp\b|\brecession\b|\bdemand\s+shock\b", text, re.IGNORECASE):
        pp = _PP.search(text)
        size = -float(pp.group(1)) if pp else -1.0
        shocks.append(sc.Shock(sc.MACRO, size, sc.ABSOLUTE_PP, target="gdp"))
    if re.search(r"\binflation\b", text, re.IGNORECASE):
        pp = _PP.search(text)
        shocks.append(sc.Shock(sc.MACRO, float(pp.group(1)) if pp else 1.0,
                               sc.ABSOLUTE_PP, target="inflation"))

    # ---- PD
    if re.search(r"\bpd\b|\bprobability\s+of\s+default\b", text, re.IGNORECASE):
        anchor = re.search(r"\bpd\b|\bprobability\s+of\s+default\b", text,
                           re.IGNORECASE)
        pct = _PCT.search(text)
        pp = _PP.search(text)
        bps = _BPS.search(text)
        if pct:
            shocks.append(sc.Shock(sc.PD, float(pct.group(1))
                                   * _direction(text, pct.start()), sc.RELATIVE))
        elif pp:
            shocks.append(sc.Shock(sc.PD, float(pp.group(1))
                                   * _direction(text, pp.start()), sc.ABSOLUTE_PP))
        elif bps:
            shocks.append(sc.Shock(sc.PD, float(bps.group(1))
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
            shocks.append(sc.Shock(sc.LGD, float(pp.group(1))
                                   * _direction(text, pp.start()), sc.ABSOLUTE_PP))
        elif pct:
            shocks.append(sc.Shock(sc.LGD, float(pct.group(1))
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
            shocks.append(sc.Shock(sc.EAD, float(pct.group(1))
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
            size = float(pct.group(1)) * _direction(text, pct.start())
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
            size = float(pct.group(1)) * _direction(text, found.start())
            shocks.append(sc.Shock(sc.FINANCIAL, size, sc.RELATIVE, target=measure))
        else:
            unread.append(f"an {measure.replace('_', ' ')} movement with no "
                          "size given")

    if "sector" in lowered and re.search(r"\bdeteriorat\w*\b|\bstress\w*\b",
                                         lowered) and not shocks:
        shocks.append(sc.Shock(sc.MACRO, 2.0, sc.STEPS, target="sector_stress"))

    return shocks, notes, unread


def read(question: str) -> Reading:
    """The scenario a question describes, or a reading that says it is not one."""
    said = str(question or "").strip()
    if not said:
        return Reading()

    is_scenario = bool(_ASKS_A_SCENARIO.search(said))
    continues = bool(_CONTINUES.search(said))
    reading = Reading(is_scenario_question=is_scenario or continues,
                      continues_previous=continues and not is_scenario)

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
