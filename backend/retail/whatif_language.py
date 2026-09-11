"""
What a person types into the What-If box, read as a retail scenario.

The engine in `backend.retail.whatif` is exact and will refuse anything it does
not implement. This module is the half in front of it: it turns a sentence into
that engine's own contract — a population, a set of shocks, a staging mode and,
where the sentence asks for it, the three macroeconomic weights.

Three rules decide everything here.

**A unit is never guessed.** "Increase PD by 2" is two different scenarios: two
percent of the current PD, and two percentage points added to it. On a PD of
0.02 those are 0.0204 and 0.04 — one is a rounding error and the other doubles
the book's expected loss. The sentence is ambiguous, so the answer is a
question, with both readings offered exactly as they will be run.

**An instruction is never dropped.** A sentence naming something the engine does
not implement is refused with the list of what it does, never silently reduced
to the part that was understood. A scenario that quietly ignored half of what it
was told is worse than one that did not run.

**Nothing is normalised behind the reader's back.** Weights that sum to 110% are
sent to the engine, which refuses them and says so. Rescaling them to 100% would
answer a question nobody asked and look like agreement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from backend.retail import whatif as wif

#: How a person names a retail product, mapped to the governed product code.
PRODUCTS: dict[str, str] = {
    "personal finance": "PERSONAL_LOAN",
    "personal loan": "PERSONAL_LOAN",
    "personal loans": "PERSONAL_LOAN",
    "personal": "PERSONAL_LOAN",
    "auto finance": "AUTO_LOAN",
    "auto loan": "AUTO_LOAN",
    "auto": "AUTO_LOAN",
    "car finance": "AUTO_LOAN",
    "vehicle finance": "AUTO_LOAN",
    "home finance": "HOME_LOAN",
    "home loan": "HOME_LOAN",
    "mortgage": "HOME_LOAN",
    "mortgages": "HOME_LOAN",
    "credit card": "CREDIT_CARD",
    "credit cards": "CREDIT_CARD",
    "cards": "CREDIT_CARD",
}

#: Populations a scenario is commonly narrowed to, beyond the product.
POPULATIONS: tuple[tuple[str, str, Any], ...] = (
    (r"\bsalary[- ]transfer(?:red)?\b", "salary_transfer_flag", True),
    (r"\bnon[- ]salary[- ]transfer(?:red)?\b", "salary_transfer_flag", False),
    (r"\bstage\s*1\b", "ifrs9_stage", 1),
    (r"\bstage\s*2\b", "ifrs9_stage", 2),
    (r"\bstage\s*3\b", "ifrs9_stage", 3),
    (r"\bcredit[- ]impaired\b", "credit_impaired_flag", True),
    (r"\bsecured\b", "secured_flag", True),
    (r"\bunsecured\b", "secured_flag", False),
    (r"\bforb(?:orne|earance)\b", "forbearance_flag", True),
)

_NUMBER = r"(-?\d+(?:\.\d+)?)"

#: A percentage-POINT move. Checked before the plain percentage, because
#: "percentage points" contains "percent".
_POINTS = r"(?:percentage\s*points?|pps?\b|p\.p\.|ppt)"
_PERCENT = r"(?:per\s*cent|percent|%)"

_SPELLED: dict[str, float] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
    "twenty": 20, "twenty five": 25, "thirty": 30, "fifty": 50,
    "half": 50, "a hundred": 100, "one hundred": 100,
}


@dataclass
class Ask:
    """One typed sentence, read."""

    filters: dict[str, Any] = field(default_factory=dict)
    shocks: dict[str, Any] = field(default_factory=dict)
    staging_mode: str = wif.FROZEN_STAGE
    scenario_weights: dict[str, float] | None = None
    month: str = ""
    name: str = ""
    #: Set when the sentence cannot be run as written.
    question: str = ""
    #: The readings offered, each one a complete scenario the user can pick.
    options: list[dict[str, Any]] = field(default_factory=list)
    #: What the sentence said that the engine does not implement.
    unsupported: list[str] = field(default_factory=list)
    #: What was read, in the words the answer will use.
    read_as: list[str] = field(default_factory=list)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.question)

    @property
    def is_neutral(self) -> bool:
        return not self.shocks and self.scenario_weights is None

    def to_dict(self) -> dict[str, Any]:
        return {
            "filters": dict(self.filters), "shocks": dict(self.shocks),
            "staging_mode": self.staging_mode,
            "scenario_weights": dict(self.scenario_weights)
            if self.scenario_weights else None,
            "month": self.month, "name": self.name,
            "question": self.question, "options": list(self.options),
            "unsupported": list(self.unsupported),
            "read_as": list(self.read_as),
        }


def _spelled(text: str) -> str:
    """"five percentage points" -> "5 percentage points"."""
    out = text
    for word, value in sorted(_SPELLED.items(), key=lambda kv: -len(kv[0])):
        out = re.sub(rf"\b{word}\b", str(int(value)), out)
    return out


def _month(text: str, months: list[str]) -> str:
    """The reporting month the sentence names, resolved against the book."""
    from backend.orchestration.periods import read_period_intent

    intent = read_period_intent(text, list(months))
    named = list(intent.named_periods)
    return named[-1] if named else ""


def read(question: str, months: list[str] | None = None,
         carried: dict[str, Any] | None = None) -> Ask:
    """Read one sentence into a scenario, or into the question to ask back."""
    said = _spelled(" ".join(str(question or "").lower().split()))
    ask = Ask()
    carried = carried or {}

    ask.month = _month(said, months or [])
    if not ask.month and carried.get("month"):
        ask.month = str(carried["month"])

    # ---- population ---------------------------------------------------
    for phrase, code in sorted(PRODUCTS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", said):
            ask.filters["product_code"] = code
            ask.read_as.append(f"{phrase} only")
            break
    for pattern, column, value in POPULATIONS:
        if re.search(pattern, said):
            ask.filters[column] = value
            ask.read_as.append(f"{column.replace('_', ' ')} = {value}")

    # A narrowing turn keeps the population of the scenario it narrows, unless
    # this sentence states its own.
    for column, value in (carried.get("filters") or {}).items():
        ask.filters.setdefault(column, value)

    # ---- staging ------------------------------------------------------
    if re.search(r"\bre-?evaluat\w*\s+(?:the\s+)?stag\w+|\ballow\w*\s+migration|"
                 r"\blet\s+(?:them|facilities)\s+migrate|\brestage\b", said):
        ask.staging_mode = wif.REEVALUATE_STAGE
        ask.read_as.append("staging re-evaluated")
    elif re.search(r"\bfroz\w+|\bfreeze\s+(?:the\s+)?stag\w+|\bfixed stages?\b", said):
        ask.staging_mode = wif.FROZEN_STAGE
        ask.read_as.append("stages held at their published values")

    # ---- scenario weights --------------------------------------------
    weights = _weights(said)
    if weights:
        ask.scenario_weights = weights
        ask.read_as.append(
            "weights base/upturn/downturn = "
            + "/".join(f"{weights[s]:.2f}" for s in ("base", "upturn", "downturn")))

    # ---- shocks -------------------------------------------------------
    _shocks(said, ask)
    if ask.needs_clarification:
        return ask

    unsupported = _unsupported(said, ask)
    if unsupported:
        ask.unsupported = unsupported
    return ask


def _weights(said: str) -> dict[str, float] | None:
    """Three macroeconomic weights, exactly as written.

    Never renormalised: weights that do not sum to one are sent on to the
    engine, which refuses them and says by how much. Quietly rescaling them
    would run a scenario the reader did not ask for and report it as theirs.
    """
    found: dict[str, float] = {}
    for name, words in (("base", r"base(?:line)?"),
                        ("upturn", r"up[- ]?turn|upside|optimistic"),
                        ("downturn", r"down[- ]?turn|downside|adverse|pessimistic")):
        match = re.search(rf"\b(?:{words})\D{{0,12}}?{_NUMBER}\s*(?:{_PERCENT})?", said)
        if match:
            found[name] = float(match.group(1))
    if len(found) < 3:
        return None
    # Written as percentages ("base 50%") or as weights ("base 0.5").
    if any(value > 1.0 for value in found.values()):
        found = {name: value / 100.0 for name, value in found.items()}
    return found


def _shocks(said: str, ask: Ask) -> None:
    """Every shock the sentence names, or the question its units leave open."""
    # --- PD, the one that carries the ambiguity ------------------------
    for match in re.finditer(
            rf"\b(?:pd|probability of default)\b[^.;]{{0,40}}?"
            rf"\b(?:by|of|to)?\s*(?:up\s+)?{_NUMBER}\s*"
            rf"({_POINTS}|{_PERCENT})?", said):
        amount, unit = float(match.group(1)), (match.group(2) or "")
        direction = -1.0 if re.search(r"\b(?:reduc\w+|decreas\w+|lower|cut|down|fall\w*)\b",
                                      said[:match.start()][-60:]) else 1.0
        if re.search(_POINTS, unit):
            ask.shocks["pd_absolute_pp"] = direction * amount
            ask.read_as.append(f"PD {'+' if direction > 0 else '−'}{amount:g} "
                               "percentage points")
        elif re.search(_PERCENT, unit):
            ask.shocks["pd_relative"] = direction * amount / 100.0
            ask.read_as.append(f"PD {'+' if direction > 0 else '−'}{amount:g}% relative")
        else:
            # No unit. Two different scenarios, so ask — with both readings
            # offered as the scenarios they are, not as words.
            ask.question = (
                f"Do you mean {amount:g} percent of the current PD, or "
                f"{amount:g} percentage points added to it? On a PD of 2% the "
                f"first gives {2 * (1 + amount / 100):.4g}% and the second "
                f"{2 + amount:g}% — they are different scenarios, so "
                "CreditProbe will not guess.")
            ask.options = [
                {"id": "relative",
                 "label": f"{amount:g}% relative (multiply the PD by "
                          f"{1 + amount / 100:.4g})",
                 "shocks": {"pd_relative": direction * amount / 100.0}},
                {"id": "absolute",
                 "label": f"{amount:g} percentage points (add {amount:g}pp to "
                          "the PD)",
                 "shocks": {"pd_absolute_pp": direction * amount}},
            ]
            return
        break

    _simple(said, ask, r"\b(?:lgd|loss given default)\b", "lgd_relative",
            percent_scale=0.01, label="LGD")
    _simple(said, ask, r"\bcollateral\b", "collateral_value_pct",
            percent_scale=0.01, label="collateral values")
    _simple(said, ask, r"\b(?:income|salar(?:y|ies))\b", "income_pct",
            percent_scale=0.01, label="verified income")

    match = re.search(rf"\b(?:utilisation|utilization)\b[^.;]{{0,30}}?{_NUMBER}"
                      rf"\s*(?:{_POINTS}|{_PERCENT})?", said)
    if match:
        amount = float(match.group(1))
        if re.search(r"\b(?:reduc\w+|decreas\w+|lower|cut|down)\b", said):
            amount = -amount
        ask.shocks["utilisation_pp"] = amount
        ask.read_as.append(f"card utilisation {amount:+g} percentage points")

    match = (re.search(rf"\brecover\w*\s+delay\w*[^.;]{{0,20}}?{_NUMBER}", said)
             or re.search(rf"\bdelay\w*\s+(?:the\s+)?recover\w*[^.;]{{0,20}}?"
                          rf"{_NUMBER}", said)
             or re.search(rf"{_NUMBER}\s*months?[^.;]{{0,24}}?recover\w*\s+"
                          rf"delay", said))
    if match:
        ask.shocks["recovery_delay_months"] = float(match.group(1))
        ask.read_as.append(f"recovery delayed {match.group(1)} months")

    match = re.search(rf"\bccf\b[^.;]{{0,20}}?{_NUMBER}\s*(?:{_PERCENT})?", said)
    if match:
        value = float(match.group(1))
        ask.shocks["ccf_absolute"] = value / 100.0 if value > 1 else value
        ask.read_as.append(f"credit conversion factor set to "
                           f"{ask.shocks['ccf_absolute']:.2f}")

    match = re.search(rf"\bbehavioural\s+score\b[^.;]{{0,30}}?{_NUMBER}", said)
    if match:
        amount = float(match.group(1))
        if re.search(r"\b(?:reduc\w+|decreas\w+|lower|cut|drop|down|worse\w*)\b", said):
            amount = -amount
        ask.shocks["behavioural_score_points"] = amount
        ask.read_as.append(f"behavioural score {amount:+g} points")


def _simple(said: str, ask: Ask, subject: str, shock: str, *,
            percent_scale: float, label: str) -> None:
    """A relative shock whose only supported unit is a percentage."""
    match = re.search(rf"({subject})[^.;]{{0,30}}?{_NUMBER}\s*"
                      rf"({_POINTS}|{_PERCENT})?", said)
    if not match:
        return
    amount, unit = float(match.group(2)), (match.group(3) or "")
    if re.search(r"\b(?:reduc\w+|decreas\w+|lower|cut|down|fall\w*|halve)\b",
                 said[:match.start(2)][-60:]):
        amount = -amount
    if unit and re.search(_POINTS, unit) and shock.endswith("_relative"):
        ask.unsupported.append(
            f"{label} can be moved by a relative percentage, not by percentage "
            f"points: the engine multiplies it, and a percentage-point move on "
            f"a rate that varies by facility is not a defined operation here.")
        return
    ask.shocks[shock] = amount * percent_scale
    ask.read_as.append(f"{label} {amount:+g}% relative")


#: Things people ask for that this engine does not implement. Named so the
#: refusal can say what was asked for rather than "unsupported".
_NOT_IMPLEMENTED: tuple[tuple[str, str], ...] = (
    (r"\bnotch\w*\b", "a rating-notch downgrade — this is a retail book with "
                      "scorecards and no rating master scale"),
    (r"\bmaster scale\b", "the rating master scale"),
    (r"\bsector\b", "a corporate sector stress"),
    (r"\bunemployment|oil price|policy rate|gdp\b",
     "a macroeconomic variable shock — the retail engine reweights the three "
     "published macroeconomic scenarios instead"),
    (r"\bcovenant\b", "covenant testing"),
    (r"\bebitda|leverage|dscr\b", "a corporate financial ratio"),
)


def _unsupported(said: str, ask: Ask) -> list[str]:
    out: list[str] = []
    for pattern, description in _NOT_IMPLEMENTED:
        if re.search(pattern, said):
            out.append(description)
    if not ask.shocks and ask.scenario_weights is None and out:
        return out
    return out


#: A question ABOUT the run that is already on the table, rather than a new one.
_EXPLAINS = re.compile(
    r"\bwhat changed\b|\bwhy (?:did|is|has|does)\b|\bexplain\b|"
    r"\bwhich assumptions\b|\bwhat drove\b|\bwhat matters\b|"
    r"\bwalk me through\b|\bwhat does (?:that|this) mean\b")


def wants_explanation(question: str) -> bool:
    """Whether the sentence asks about the LAST run rather than for a new one.

    The failure this prevents
    -------------------------
        "What changed, why, and which assumptions matter?"

    named no shock, so it was read as a scenario with no shocks — a neutral run
    over the whole book — and answered with a baseline the reader had not asked
    for, under a question about the scenario they were looking at.
    """
    said = " ".join(str(question or "").lower().split())
    if not said:
        return False
    if not _EXPLAINS.search(said):
        return False
    # A sentence that also names a change is a new scenario that happens to ask
    # for an explanation with it.
    probe = read(said, [])
    return not probe.shocks and probe.scenario_weights is None


def describe(ask: Ask) -> str:
    """What CreditProbe understood, in one line, for the answer to open with."""
    if not ask.read_as:
        return "An unchanged scenario over the whole retail book."
    return "Read as: " + "; ".join(ask.read_as) + "."


def supported_sentence() -> str:
    """The list a refusal offers, built from the engine's own contract."""
    return ", ".join(sorted(wif.SUPPORTED_METHODOLOGIES))
