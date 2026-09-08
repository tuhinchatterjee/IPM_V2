"""
Whether an interpretation is any good, decided by arithmetic.

Why a rubric rather than a reviewer
-----------------------------------
"Unimpressive, generic, indirect or incomplete" is a fair description of prose
and a useless test result. Somebody has to be able to run this on every answer
and get the same verdict twice, which rules out asking a model whether the
writing is good — a grader that disagrees with itself cannot say whether a
change improved anything.

So every criterion here is decided from the text and the result together, with
no judgement and no second model. A live reviewer may be added later for style;
it may never be the thing that decides correctness, because a model marking
another model's homework is a closed loop with no ground in it.

The ten criteria
----------------
Four are safety: no figure the result does not carry, no name it does not
contain, no binary debris, no asserted cause. Those are pass-or-the-answer-is-
withheld.

Six are quality: does the first sentence answer the question, is it short
enough to read, does it name the largest contributor, does it name the rows
that do not fit, does it say what limits the conclusion, and does it leave
somewhere to go next. Those are scored and reported.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# Safety — a failure here means the answer should not have been shown as it is.
GROUNDED_FIGURES = "grounded_figures"
GROUNDED_ENTITIES = "grounded_entities"
NO_DEBRIS = "no_debris"
NON_CAUSAL = "non_causal"

# Quality — a failure here means the answer is worse than it could be.
DIRECTNESS = "directness"
CONCISION = "concision"
DRIVERS = "drivers"
EXCEPTIONS = "exceptions"
LIMITATION = "limitation"
NEXT_STEP = "next_step"

SAFETY = (GROUNDED_FIGURES, GROUNDED_ENTITIES, NO_DEBRIS, NON_CAUSAL)
QUALITY = (DIRECTNESS, CONCISION, DRIVERS, EXCEPTIONS, LIMITATION, NEXT_STEP)

# The Early Warning criteria are declared with the rest of the Early Warning
# rubric further down; they are named here because Assessment scores against
# both sets and cannot be defined before it knows what they are.
EWS_GROUNDED = "ews_grounded_figures"
EWS_NO_DEBRIS = "ews_no_debris"
EWS_NO_SCORE_CHANGE = "ews_no_score_change"
EWS_NOTCH_NOT_IMPROVEMENT = "ews_notch_not_improvement"

EWS_NAMES_THE_NODE = "ews_names_the_node"
EWS_SOURCE_SYSTEM = "ews_source_system"
EWS_LIVE_VERSUS_STRUCTURAL = "ews_live_versus_structural"
EWS_GOVERNED_ACTION = "ews_governed_action"
EWS_STATES_LIMITS = "ews_states_limits"
EWS_NEXT_DRILL = "ews_next_drill"
EWS_CHART_FITS = "ews_chart_fits"

EWS_SAFETY = (EWS_GROUNDED, EWS_NO_DEBRIS, EWS_NO_SCORE_CHANGE,
              EWS_NOTCH_NOT_IMPROVEMENT)
EWS_QUALITY = (EWS_NAMES_THE_NODE, EWS_SOURCE_SYSTEM,
               EWS_LIVE_VERSUS_STRUCTURAL, EWS_GOVERNED_ACTION,
               EWS_STATES_LIMITS, EWS_NEXT_DRILL, EWS_CHART_FITS)

#: A first sentence longer than this is a paragraph pretending to be an answer.
MAX_DIRECT_WORDS = 45

#: And a reading longer than this is a report. The figures are directly beneath
#: it; the reading is the thing you read INSTEAD of the table.
MAX_READING_WORDS = 120


@dataclass
class Score:
    """One criterion, and why it went the way it did."""

    criterion: str
    passed: bool
    detail: str = ""
    #: False where the criterion does not apply to this answer — a result with
    #: three rows has no exceptions to name.
    applicable: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {"criterion": self.criterion, "passed": self.passed,
                "detail": self.detail, "applicable": self.applicable}


@dataclass
class Assessment:
    """How one answer scored, and on what."""

    scores: list[Score] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return all(s.passed for s in self.scores
                   if s.criterion in SAFETY + EWS_SAFETY and s.applicable)

    @property
    def failures(self) -> list[Score]:
        return [s for s in self.scores if s.applicable and not s.passed]

    @property
    def quality(self) -> float:
        """The share of applicable quality criteria that were met."""
        relevant = [s for s in self.scores
                    if s.criterion in QUALITY + EWS_QUALITY and s.applicable]
        if not relevant:
            return 1.0
        return round(sum(1 for s in relevant if s.passed) / len(relevant), 3)

    def to_dict(self) -> dict[str, Any]:
        return {"safe": self.safe, "quality": self.quality,
                "scores": [s.to_dict() for s in self.scores],
                "failed": [s.criterion for s in self.failures]}


_WORD = re.compile(r"[A-Za-z0-9%.,'-]+")
_FIRST_SENTENCE = re.compile(r"^.*?[.!?](?:\s|$)", re.S)


def assess(narrative: Any, runtime: Any = None, build: Any = None, *,
           question: str = "", suggestions: list[str] | None = None,
           association: dict[str, Any] | None = None,
           values: dict[str, Any] | None = None) -> Assessment:
    """Score one answer against the ten criteria.

    `values` is the step's headline figures — totals, shares, coefficients, the
    figures the analyst pass derived. They are part of the result and a reading
    is entitled to quote them; omitting them here reported every derived
    percentage as ungrounded, which is the check calling correct prose a
    defect.
    """
    try:
        return _assess(narrative, runtime, build, question=question,
                       suggestions=suggestions or [],
                       association=association or {},
                       values=values or {})
    except Exception as e:  # noqa: BLE001 - a score must not lose an answer
        logger.warning("The rubric could not be applied: %s", e)
        return Assessment()


def _assess(narrative: Any, runtime: Any, build: Any, *, question: str,
            suggestions: list[str], association: dict[str, Any],
            values: dict[str, Any]) -> Assessment:
    from backend.orchestration import assembly, evidence, figures

    direct = str(getattr(narrative, "direct_answer", "") or "")
    reading = str(getattr(narrative, "interpretation", "") or "")
    findings = [str(getattr(f, "text", "")) for f in
                (getattr(narrative, "findings", None) or [])]
    caveats = [str(c) for c in (getattr(narrative, "caveats", None) or [])]
    everything = " ".join(x for x in [direct, reading, *findings] if x)

    out: list[Score] = []

    # ---- safety --------------------------------------------------------
    allowed = assembly.grounded_values(
        runtime, values, asked=question) if runtime is not None else set()
    loose = assembly.ungrounded(everything, allowed) if allowed else []
    out.append(Score(GROUNDED_FIGURES, not loose,
                     f"figures the result does not carry: {loose[:4]}" if loose
                     else "every figure appears in the result",
                     applicable=runtime is not None))

    package = (evidence.build(runtime, build) if runtime is not None
               else evidence.Package())
    grounding = evidence.check(everything, package, allow_causal=True)
    out.append(Score(GROUNDED_ENTITIES, not grounding.unknown_entities,
                     f"names not in the result: {grounding.unknown_entities[:3]}"
                     if grounding.unknown_entities else
                     "every name appears in the result",
                     applicable=bool(package.entities)))

    debris = [t for t in (direct, reading, *findings, *caveats)
              if figures.has_debris(t)]
    out.append(Score(NO_DEBRIS, not debris,
                     "binary floating-point debris in the prose" if debris
                     else "no figure written to sixteen decimal places"))

    # An association answer discusses relationships and carries the caveat that
    # says they are not causes; anything else may not assert one at all.
    causal = evidence.check(everything, package).causal_claims
    excused = bool(association.get("caveat"))
    out.append(Score(NON_CAUSAL, not causal or excused,
                     f"asserts a cause: {causal[:1]}" if causal and not excused
                     else "no cause is asserted"))

    # ---- quality -------------------------------------------------------
    first = (_FIRST_SENTENCE.match(direct) or [None])
    opening = (first.group(0) if hasattr(first, "group") else direct).strip()
    words = len(_WORD.findall(opening))
    answers = bool(re.search(r"\d", opening)) or bool(
        re.search(r"\bnone\b|\bno\b|\bnothing\b|\bcannot\b", opening, re.I))
    out.append(Score(DIRECTNESS, bool(opening) and answers and words <= MAX_DIRECT_WORDS,
                     f"first sentence is {words} words and "
                     f"{'carries' if answers else 'carries no'} an answer"))

    reading_words = len(_WORD.findall(reading))
    out.append(Score(CONCISION, reading_words <= MAX_READING_WORDS,
                     f"the reading is {reading_words} words",
                     applicable=bool(reading)))

    observations = list(getattr(build, "observations", None) or [])
    out.append(_names(observations, everything, "driver", DRIVERS,
                      ("leader", "top")))
    out.append(_names(observations, everything, "exception", EXCEPTIONS,
                      ("exceptions",)))

    limits = [o for o in observations
              if str(getattr(o, "kind", "")) == "limitation"]
    out.append(Score(LIMITATION,
                     any(o.text in everything or o.text in " ".join(caveats)
                         for o in limits),
                     "the limitation the result carries is stated",
                     applicable=bool(limits)))

    out.append(Score(NEXT_STEP, bool(suggestions),
                     f"{len(suggestions)} suggestions offered"))
    return Assessment(scores=out)


def _names(observations: list[Any], text: str, kind: str, criterion: str,
           keys: tuple[str, ...]) -> Score:
    """Whether the reading names what the analyst pass found."""
    found = [o for o in observations if str(getattr(o, "kind", "")) == kind]
    if not found:
        return Score(criterion, True, f"no {kind} to name", applicable=False)

    wanted: list[str] = []
    for observation in found:
        facts = getattr(observation, "facts", None) or {}
        for key in keys:
            value = facts.get(key)
            if isinstance(value, str) and value.strip():
                wanted.append(value.strip())
            elif isinstance(value, list):
                wanted.extend(str(v) for v in value if str(v).strip())
    if not wanted:
        return Score(criterion, True, f"the {kind} has no name",
                     applicable=False)

    named = [w for w in wanted if w.lower() in text.lower()]
    return Score(criterion, bool(named),
                 f"names {named[0]}" if named
                 else f"does not name {wanted[0]}, which the result singles out")




# =====================================================================
# Early Warning
# =====================================================================
#
# The ten criteria above grade an answer built from a query result. An Early
# Warning answer is built from a fact pack, and the things that make it good
# or bad are different ones.
#
# Four are safety. No figure the pack does not carry. No binary debris. Never
# a claim to have changed a score or closed a case, because the assistant
# explains and navigates and the override path and the escalation matrix are
# where those decisions are counted as controls. And never "improved" about a
# fall the notches produced while the underlying condition was flat or worse,
# which is the single most expensive thing this tool could say.
#
# Seven are quality, and each is a specific failure the brief names: a number
# quoted without the node it came from, evidence shown without the system it
# came from, a live problem and a structural one read as the same thing, a
# recommendation with no owner or no way to tell when it is done, a reading
# that never says what it cannot see, an answer with nowhere to go next, and
# a chart attached to a question that has no shape to show.

#: Scopes whose answer is about a shape, and so may carry a chart. The list
#: matches components/early-warning/chart-rules.ts deliberately: one rule
#: enforced on the server and drawn on the client, not two that drift.
CHARTABLE_SCOPES = frozenset({"portfolio", "level", "group", "movement",
                              "comparison", "diagnosis", "borrower"})

#: A claim to have done something only the override path or the escalation
#: matrix may do.
_CLAIMS_A_CHANGE = re.compile(
    r"\bi (have |'ve )?(changed|overrode|overridden|adjusted|reset|closed|"
    r"resolved|cleared|dismissed|waived)\b|"
    r"\b(the score|the band|the case|the alert) (has been|was) "
    r"(changed|overridden|adjusted|closed|resolved|cleared)\b", re.I)

#: The word that must not describe a notch-driven fall.
_IMPROVEMENT = re.compile(
    r"\b(improv\w*|recover\w*|better|healthier|strengthen\w*)\b", re.I)

#: "Anything else?" is not a next step. A drill names where to look.
_EMPTY_DRILL = re.compile(
    r"^(would you like|do you want|anything else|shall i|is there anything|"
    r"let me know|tell me more|more details?)\b", re.I)

#: A period label is not two figures. Stripping it before the figures are
#: read is the difference between checking a claim and checking a date.
_PERIOD_LABEL = re.compile(r"\b\d{4}-\d{2}(?:-\d{2})?\b")

#: Where a pack keeps the name of a thing, as opposed to a measure of it.
_NAME_KEYS = frozenset({
    "name", "label", "layer", "layer_label", "level_label", "weakest_group",
    "signal_key", "sub_category", "sub_category_name", "population",
    "customer_name", "weakest_obligor", "dominant_subcategory",
    "dominant_driver", "segment", "code", "reason_code",
})


def _ews_allowed(pack: Any) -> set[str]:
    """Every form a sentence could reasonably write a pack figure in.

    Prose rounds and prose rescales: the book is kept in millions and a
    sentence says "SAR 15.5bn", which is the same fact as 15,464.2. Both are
    accepted, at the roundings a sentence would use, because the check exists
    to catch invented figures rather than formatting.
    """
    out: set[str] = set()
    for number in (pack.numbers() if pack is not None else []):
        for candidate in (number, abs(number),
                          number / 1000.0, abs(number) / 1000.0):
            for places in (0, 1, 2, 3, 4):
                out.add(f"{round(candidate, places):.4f}"
                        .rstrip("0").rstrip("."))
    return out


def _ews_ungrounded(text: str, allowed: set[str]) -> list[str]:
    """Figures in the prose that the pack does not carry."""
    stripped = _PERIOD_LABEL.sub(" ", text or "")
    out: list[str] = []
    # A hyphen after a letter is a compound word, not a minus sign: "tier-3"
    # and "five-by-five" are words, and reading them as negative numbers had
    # the check reporting correct prose as a fabricated figure.
    for raw in re.findall(r"(?<![\w-])-?\d[\d,]*(?:\.\d+)?", stripped):
        try:
            value = float(raw.replace(",", ""))
        except ValueError:
            continue
        if value.is_integer() and (1900 <= value <= 2100 or 0 <= value <= 12):
            continue
        if f"{value:.4f}".rstrip("0").rstrip(".") in allowed:
            continue
        out.append(raw)
    return out


def assess_early_warning(answer: Any, *, question: str = "") -> Assessment:
    """Score one Early Warning answer against the eleven criteria."""
    try:
        return _assess_early_warning(answer, question=question)
    except Exception as e:  # noqa: BLE001 - a score must not lose an answer
        logger.warning("The Early Warning rubric could not be applied: %s", e)
        return Assessment()


def _assess_early_warning(answer: Any, *, question: str) -> Assessment:
    from backend.orchestration import figures

    composed = getattr(answer, "composed", answer)
    pack = getattr(answer, "pack", None)
    scope = str(getattr(answer, "scope", "") or "")
    refused = bool(getattr(answer, "refused", False))

    direct = str(getattr(composed, "direct", "") or "")
    reading = str(getattr(composed, "interpretation", "") or "")
    points = [str(p) for p in (getattr(composed, "points", None) or [])]
    drills = [str(d) for d in (getattr(composed, "follow_ups", None) or [])]
    caveats = [str(c) for c in (getattr(composed, "caveats", None) or [])]
    chart = getattr(composed, "chart", None) or {}
    prose = " ".join(x for x in [direct, reading, *points] if x)

    figs = (pack.figures if pack is not None else {}) or {}
    out: list[Score] = []

    # ---- safety --------------------------------------------------------
    allowed = _ews_allowed(pack)
    loose = _ews_ungrounded(prose, allowed) if allowed else []
    out.append(Score(EWS_GROUNDED, not loose,
                     f"figures the pack does not carry: {loose[:4]}" if loose
                     else "every figure appears in the fact pack",
                     applicable=pack is not None))

    debris = [t for t in (direct, reading, *points, *caveats)
              if figures.has_debris(t)]
    out.append(Score(EWS_NO_DEBRIS, not debris,
                     "binary floating-point debris in the prose" if debris
                     else "no figure written to sixteen decimal places"))

    claimed = _CLAIMS_A_CHANGE.search(prose)
    out.append(Score(EWS_NO_SCORE_CHANGE, not claimed,
                     f"claims to have acted: {claimed.group(0)!r}" if claimed
                     else "explains and navigates; changes nothing"))

    # A fall the notches produced is not an improvement, and this is the one
    # criterion where the pack decides rather than the prose: the movement
    # figures say whether the underlying condition moved at all.
    movement = figs.get("movement") if isinstance(figs.get("movement"), dict) \
        else (figs if scope == "movement" else {})
    notch_driven = bool((movement or {}).get("driven_by_notches")) and not \
        bool((movement or {}).get("condition_improved"))
    said_improved = bool(_IMPROVEMENT.search(prose))
    out.append(Score(EWS_NOTCH_NOT_IMPROVEMENT, not (notch_driven and said_improved),
                     "calls a notch-driven fall an improvement" if
                     (notch_driven and said_improved) else
                     "a score movement is not read as a condition movement",
                     applicable=notch_driven))

    # ---- quality -------------------------------------------------------
    # A number without its node is the table narration this tool exists to
    # not be. Any of the pack's own names will do: the layer, the
    # sub-category, the signal, the group, the obligor.
    # An explanation of the framework and a refusal are about the model and
    # about what the tool will not do; neither is about a node, and holding
    # them to one would make the criterion mean nothing where it does apply.
    about_a_node = scope not in ("methodology", "refusal")
    named = [n for n in _ews_node_names(pack, scope)
             if n and n.lower() in prose.lower()]
    out.append(Score(EWS_NAMES_THE_NODE, bool(named),
                     f"names {named[0]}" if named
                     else "quotes figures without naming the node behind them",
                     applicable=about_a_node and bool(_ews_node_names(pack, scope))))

    wants_source = scope == "evidence"
    source = str(figs.get("source_domain") or figs.get("source_system") or "")
    out.append(Score(EWS_SOURCE_SYSTEM,
                     bool(source) and source.lower() in prose.lower(),
                     f"names {source}" if source else "no source system on the pack",
                     applicable=wants_source and bool(source)))

    lvs = figs.get("live_versus_structural") or {}
    expected = str(lvs.get("reading") or "")
    said = bool(re.search(r"\blive\b|\bstructural\b|\bstanding\b|"
                          r"\bdeterioration\b|\bcondition\b", prose, re.I))
    out.append(Score(EWS_LIVE_VERSUS_STRUCTURAL, said,
                     f"distinguishes the {expected} reading" if said
                     else "does not say whether this is live or structural",
                     applicable=bool(expected)))

    # A recommendation without an owner, a timeframe and a closing test is an
    # opinion. "Monitor closely" is the specific failure the brief names.
    recommends = scope in ("action", "escalation")
    has_owner = bool(re.search(r"\bowns it\b|\bowner\b|"
                               + "|".join(_LADDER_TITLES()), prose, re.I))
    has_when = bool(re.search(r"\bimmediat\w*|\b\d+\s*(working\s*)?days?\b|"
                              r"\bsame.day\b", prose, re.I))
    has_close = bool(re.search(r"\bcloses on\b|\bevidence to close\b", prose, re.I))
    vague = bool(re.search(r"\bmonitor closely\b|\bkeep an eye\b|"
                           r"\bwatch (this|it) closely\b", prose, re.I))
    out.append(Score(EWS_GOVERNED_ACTION,
                     has_owner and has_when and has_close and not vague,
                     ("says 'monitor closely', which is not an action" if vague
                      else "carries owner, timeframe and closing evidence"
                      if (has_owner and has_when and has_close)
                      else f"owner={has_owner} timeframe={has_when} "
                           f"closing evidence={has_close}"),
                     applicable=recommends and not refused))

    out.append(Score(EWS_STATES_LIMITS, bool(caveats),
                     f"{len(caveats)} limits stated" if caveats
                     else "states nothing about what it cannot see",
                     applicable=pack is not None and bool(pack.caveats)))

    real = [d for d in drills if d.strip() and not _EMPTY_DRILL.match(d.strip())]
    out.append(Score(EWS_NEXT_DRILL, bool(real),
                     f"offers {real[0]!r}" if real
                     else "offers no specific next drill",
                     applicable=not refused))

    drawn = bool(chart) or scope in CHARTABLE_SCOPES
    fits = (scope in CHARTABLE_SCOPES) if drawn else True
    out.append(Score(EWS_CHART_FITS, fits,
                     (f"a chart on a {scope} answer shows nothing" if not fits
                      else f"{scope} is about shape, so a chart earns its place"
                      if drawn else f"no chart on a {scope} answer"),
                     applicable=bool(scope)))
    return Assessment(scores=out)


def _LADDER_TITLES() -> list[str]:
    """The role titles a governed action may name, escaped for a pattern."""
    from backend.early_warning import escalation as esc

    titles = [str(r.get("role") or "") for r in esc.LADDER]
    titles += [str(r.get("role") or "") for r in
               getattr(esc, "SPECIALIST_ROUTES", [])]
    return [re.escape(t) for t in titles if t]


def _ews_node_names(pack: Any, scope: str) -> list[str]:
    """The names this answer could have used instead of a bare number.

    Harvested at any depth, because a pack keeps its node names where the
    figures need them rather than at the top: the layer that led a movement
    is inside `movement.layers`, the group is a row key, and a check that
    only read the top level would report a reading that names three layers
    as naming nothing.
    """
    del scope
    if pack is None:
        return []
    names: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in _NAME_KEYS and isinstance(item, str) and item.strip():
                    names.append(item.strip())
                else:
                    walk(item)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item)

    walk(pack.figures or {})
    walk(pack.rows or [])
    if isinstance(pack.label, str) and pack.label.strip():
        names.append(pack.label.strip())
    return names
