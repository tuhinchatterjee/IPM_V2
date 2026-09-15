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

def _sub_products() -> dict[str, str]:
    """Every governed sub-product, by every phrase a person would type for it.

    Read from the Early Warning model's taxonomy rather than restated, because
    the two have to agree: a cohort exported from an Early Warning card names
    its sub-product by code, and a sentence typed into the composer names the
    same thing in words. A list written out here would be a second taxonomy,
    and the first thing it would do is fall behind the first one.
    """
    from backend.retail import ews_model as M

    out: dict[str, str] = {}
    for code, label in M.SUB_PRODUCT_LABELS.items():
        out[label.lower()] = code
        out[code.lower()] = code
        # "platinum card" reads as naturally as "platinum credit card", and
        # "platinum" alone is unambiguous across the twelve.
        short = label.lower()
        for drop in (" card", " personal finance", " finance", " lease",
                     " home finance", " residential finance"):
            if short.endswith(drop) and len(short) > len(drop) + 2:
                out.setdefault(short[: -len(drop)].strip(), code)
    for was, now in M.SUB_PRODUCT_RENAMES.items():
        out.setdefault(was.lower(), now)
        previous = M.SUB_PRODUCT_PREVIOUS_LABELS.get(now)
        if previous:
            out.setdefault(previous.lower(), now)
    return {k: v for k, v in out.items() if k}


#: How a person says "salaried" and "non-salaried". Order matters: the negative
#: is checked first, because "non-salaried" contains "salaried".
CLASSIFICATIONS: tuple[tuple[str, str], ...] = (
    (r"\bnon[-\s]?salar(?:ied|y)\b", "NON_SALARIED"),
    (r"\bself[-\s]?employed\b", "NON_SALARIED"),
    (r"\bretired\b", "NON_SALARIED"),
    (r"\bsalaried\b", "SALARIED"),
    (r"\bsalary[-\s]earner", "SALARIED"),
    (r"\bgovernment\s+employ", "SALARIED"),
)

#: Delinquency buckets, by how they are written rather than how they are keyed.
#: "90+" and "90 plus" both mean everything from ninety days, which is two
#: buckets, so they resolve to a LIST and the filter takes any of them.
DPD_PHRASES: tuple[tuple[str, list[str]], ...] = (
    (r"\b(?:current|up[-\s]to[-\s]date|performing)\s+(?:accounts?|"
     r"facilities|exposure|customers?)\b", ["CURRENT"]),
    (r"\b0\s*dpd\b|\bzero\s+days?\s+past\s+due\b", ["CURRENT"]),
    (r"\b1\s*[-–—to]+\s*29\b", ["1-29"]),
    (r"\b30\s*[-–—to]+\s*59\b", ["30-59"]),
    (r"\b60\s*[-–—to]+\s*89\b", ["60-89"]),
    (r"\b90\s*[-–—to]+\s*179\b", ["90-179"]),
    (r"\b180\s*\+|\b180\s+plus\b", ["180+"]),
    (r"\b90\s*\+|\b90\s+plus\b|\b90\s+days?\s+or\s+more\b",
     ["90-179", "180+"]),
    (r"\b30\s*\+|\b30\s+plus\b|\b30\s+days?\s+or\s+more\b",
     ["30-59", "60-89", "90-179", "180+"]),
)

#: The Early Warning severity bands, and the two cohort splits beside them.
SEVERITIES: tuple[tuple[str, list[str]], ...] = (
    (r"\bcritical\s+and\s+high\b|\bhigh\s+and\s+critical\b",
     ["HIGH", "CRITICAL"]),
    (r"\bcritical\b", ["CRITICAL"]),
    (r"\bhigh[-\s]risk\b|\bhigh\s+severity\b|\bhigh\s+ews\b",
     ["HIGH"]),
    (r"\bmedium\s+ews\b|\bmedium\s+severity\b", ["MEDIUM"]),
    (r"\blow\s+ews\b|\blow\s+severity\b", ["LOW"]),
)

#: Score bands, for "band D and below" style asks as well as a single band.
_BAND = r"(?:\bband\s+)?([A-E]\+?)\b"


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
    #: An application-score cutoff to replay, by product code. This is NOT a
    #: shock: `cutoff_replay` is a retrospective count over booked originations,
    #: not a revaluation of the book, so it never joins `shocks`.
    cutoff: dict[str, float] | None = None

    @property
    def needs_clarification(self) -> bool:
        return bool(self.question)

    @property
    def is_neutral(self) -> bool:
        return (not self.shocks and self.scenario_weights is None
                and self.cutoff is None)

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
            "cutoff": dict(self.cutoff) if self.cutoff else None,
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


#: "20% of", "a fifth of", "half the", "all of".
_SHARE_WORDS: dict[str, float] = {
    "all": 1.0, "every": 1.0, "the whole": 1.0,
    "half": 0.5, "a half": 0.5, "a third": 1 / 3, "a quarter": 0.25,
    "a fifth": 0.2, "a tenth": 0.1,
}


def _share(said: str, at: int) -> tuple[float | None, str]:
    """The share named just before position `at`, and how it was written."""
    head = said[:at]
    found = re.search(rf"{_NUMBER}\s*{_PERCENT}\s*(?:of\s+)?$", head)
    if found:
        return float(found.group(1)) / 100.0, f"{found.group(1)}%"
    for word, value in sorted(_SHARE_WORDS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(word)}\s+(?:of\s+|the\s+)?$", head):
            return value, word
    return None, ""


def _basis(said: str) -> str:
    """Whether a share is a share of money or a share of facilities."""
    if re.search(r"\bexposure\b|\bbalance[s]?\b|\bgca\b|\bamount\b", said):
        return "exposure"
    if re.search(r"\baccounts?\b|\bfacilit(?:y|ies)\b|\bcustomers?\b|"
                 r"\bborrowers?\b", said):
        return "accounts"
    return "exposure"


def _one_bucket(text: str) -> str:
    """A single delinquency bucket named in `text`, or ""."""
    for pattern, buckets in DPD_PHRASES:
        if len(buckets) == 1 and re.search(pattern, text):
            return buckets[0]
    # "90+" as a destination means the first bucket at ninety days: a facility
    # lands somewhere, and "90-179 or 180+" is not a place.
    if re.search(r"\b90\s*\+|\b90\s+plus\b", text):
        return "90-179"
    if re.search(r"\b30\s*\+|\b30\s+plus\b", text):
        return "30-59"
    return ""


def _migrations(said: str, ask: Ask) -> None:
    """Read "move X% of A to B" for delinquency, score band and stage."""
    # "Cure" and "upgrade" move a share the same way "move" does; a migration
    # that only understood deterioration could not express a recovery.
    move = re.search(
        r"\b(?:move|migrate|shift|push|roll|cure|upgrade|downgrade)\b", said)
    if not move:
        return
    split = re.search(r"\b(?:back\s+to|to|into)\b", said[move.end():])
    if not split:
        return
    cut = move.end() + split.start()
    source_text, target_text = said[move.end():cut], said[cut:]
    share, written = _share(said, move.end() + (
        re.search(r"\S", said[move.end():]).start()
        if re.search(r"\S", said[move.end():]) else 0))
    # The share is written after "move", so read it out of the source clause.
    if share is None:
        found = re.search(rf"{_NUMBER}\s*{_PERCENT}", source_text)
        if found:
            share, written = float(found.group(1)) / 100.0, f"{found.group(1)}%"
        else:
            for word, value in sorted(_SHARE_WORDS.items(),
                                      key=lambda kv: -len(kv[0])):
                if re.search(rf"\b{re.escape(word)}\b", source_text):
                    share, written = value, word
                    break
    if share is None:
        # `_spelled` has already turned "half" into "50" and "a hundred" into
        # "100" by the time this reads the sentence, so a share written in
        # words arrives here as a bare number with no percent sign. Read it as
        # a percentage only where the clause says it is a share OF something —
        # "50 the stage 1 exposure", from "half the" — and only in range. A
        # bare number anywhere else stays ambiguous and is refused, which is
        # what "a unit is never guessed" means.
        bare = re.search(rf"{_NUMBER}\s+(?:of|the)\b", source_text)
        if bare and 0 < float(bare.group(1)) <= 100:
            share = float(bare.group(1)) / 100.0
            written = f"{bare.group(1)}%"
    if share is None:
        return

    basis = _basis(source_text)

    # Stage first: "stage 1" is unambiguous and would otherwise be read as a
    # population filter and silently dropped from the migration.
    from_stage = re.search(r"\bstage\s*([123])\b", source_text)
    to_stage = re.search(r"\bstage\s*([123])\b", target_text)
    if from_stage and to_stage:
        ask.shocks["stage_migration"] = {
            "from": int(from_stage.group(1)), "to": int(to_stage.group(1)),
            "share": share, "basis": basis}
        ask.filters.pop("ifrs9_stage", None)
        ask.read_as.append(
            f"{written} of Stage {from_stage.group(1)} by {basis} moved to "
            f"Stage {to_stage.group(1)}")
        return

    source, target = _one_bucket(source_text), _one_bucket(target_text)
    if source and target and source != target:
        ask.shocks["dpd_migration"] = {
            "from": source, "to": target, "share": share, "basis": basis}
        ask.filters.pop("dpd_bucket", None)
        ask.read_as.append(
            f"{written} of {source} days past due by {basis} moved to {target}")
        return

    from_band = re.search(r"\b(?:band\s+)?([a-e]\+?)\s*(?:band)?\b",
                          source_text)
    to_band = re.search(r"\b(?:band\s+)?([a-e]\+?)\s*(?:band)?\b",
                        target_text)
    if from_band and to_band:
        column = ("application_score_band"
                  if "application" in said else "behavioural_score_band")
        ask.shocks["score_band_migration"] = {
            "from": from_band.group(1).upper(), "to": to_band.group(1).upper(),
            "share": share, "basis": basis, "column": column}
        ask.filters.pop(column, None)
        ask.read_as.append(
            f"{written} of {column.replace('_', ' ')} "
            f"{from_band.group(1).upper()} moved to {to_band.group(1).upper()}")


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
    named_population = False
    for phrase, code in sorted(PRODUCTS.items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", said):
            ask.filters["product_code"] = code
            ask.read_as.append(f"{phrase} only")
            named_population = True
            break
    # Sub-product, before the generic populations: "stress platinum card" names
    # a sub-product and, through it, its product.
    for phrase, code in sorted(_sub_products().items(), key=lambda kv: -len(kv[0])):
        if re.search(rf"\b{re.escape(phrase)}\b", said):
            from backend.retail import ews_model as M

            ask.filters["sub_product"] = code
            ask.read_as.append(
                f"{M.SUB_PRODUCT_LABELS.get(code, code)} only")
            owner = next((one.product for one in M.SUB_PRODUCTS
                          if one.code == code), "")
            if owner:
                ask.filters.setdefault("product_code", owner)
            named_population = True
            break

    # Salaried / non-salaried, the classification every product is cut by.
    for pattern, code in CLASSIFICATIONS:
        if re.search(pattern, said):
            ask.filters["classification"] = code
            ask.read_as.append(
                "salaried only" if code == "SALARIED" else "non-salaried only")
            named_population = True
            break

    # Delinquency. Longest phrase first so "90-179" is not read as "90+".
    for pattern, buckets in DPD_PHRASES:
        if re.search(pattern, said):
            ask.filters["dpd_bucket"] = list(buckets)
            ask.read_as.append("days past due in " + ", ".join(buckets))
            named_population = True
            break

    # Early Warning severity, and the two cohort splits beside it.
    for pattern, bands in SEVERITIES:
        if re.search(pattern, said):
            ask.filters["ews_severity"] = list(bands)
            ask.read_as.append(
                "Early Warning severity " + " or ".join(bands))
            named_population = True
            break
    if re.search(r"\bforward[-\s]risk\b|\bstill\s+paying\b|"
                 r"\bstill\s+performing\b", said):
        ask.filters["forward_risk_flag"] = True
        ask.read_as.append("forward-risk customers, still paying")
        named_population = True
    if re.search(r"\balready\s+bad\b|\bcurrently\s+bad\b|"
                 r"\balready\s+delinquent\b", said):
        ask.filters["current_bad_flag"] = True
        ask.read_as.append("customers already bad")
        named_population = True

    # A score band, with or without "and below".
    # Lower case, because the sentence was lower-cased before it got here: a
    # band written [A-E] never matched the "d" a reader typed.
    band = re.search(
        r"\b(behavioural|behavioral|application)\s+score\s+band\s+"
        r"([a-e]\+?)(\s+(?:and|or)\s+below)?\b", said)
    if band:
        from backend.retail.scorecards import SCORE_BAND_LABELS

        column = ("application_score_band" if band.group(1) == "application"
                  else "behavioural_score_band")
        labels = list(SCORE_BAND_LABELS)          # A+ best .. E worst
        named = band.group(2).upper()
        if named in labels:
            at = labels.index(named)
            wanted = labels[:at + 1] if band.group(3) else [named]
            ask.filters[column] = wanted
            ask.read_as.append(
                f"{column.replace('_', ' ')} " + " or ".join(wanted))
            named_population = True

    for pattern, column, value in POPULATIONS:
        if re.search(pattern, said):
            ask.filters[column] = value
            ask.read_as.append(f"{column.replace('_', ' ')} = {value}")
            named_population = True

    # A narrowing turn keeps the population of the scenario it narrows, unless
    # this sentence states its own — or unless it WIDENS.
    #
    #     "Run a neutral no-change scenario over the whole retail book."
    #
    # asked after a credit-card scenario ran over credit cards alone: 4,624
    # facilities and SAR 2,373,271, under a heading reading "An unchanged
    # scenario over the whole retail book". The sentence names its scope in so
    # many words, and the scope it names is everything.
    if _WHOLE_BOOK.search(said) and "product_code" not in ask.filters:
        ask.filters.clear()
        ask.read_as.append("the whole retail book")
    else:
        for column, value in (carried.get("filters") or {}).items():
            ask.filters.setdefault(column, value)

    # ---- migrations: move a share of one band into another ------------
    #
    # "Move 20% of 30-59 DPD exposure to 90+" is one instruction with four
    # parts — how much, of what, measured how, to where — and all four have to
    # be read or the sentence is refused. A migration read as a shock on the
    # whole population would move the entire bucket.
    _migrations(said, ask)

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
    elif _NAMES_WEIGHTS.search(said):
        # The methodology is named and the numbers are not.
        #
        #     "Shift macro scenario weights toward downturn and show the
        #      effect on weighted ECL."
        #
        # is one of the questions this engine exists to answer, and it came
        # back as a NEUTRAL run: no weights parsed, no shock parsed, so the
        # published book was recomputed unchanged and reported as the
        # scenario. A reweighting with no weights is not a reweighting, and
        # three numbers are not something to guess at — so they are offered.
        _ask_for_weights(said, ask)
        return ask

    # ---- application-score cutoff replay -------------------------------
    #
    # Read BEFORE the shocks, because a cutoff replay is a different analysis
    # over a different population — the booked originations, counted — and not
    # a shock this engine can fold into an ECL rebuild. Reading it first is
    # what stops "replay a cutoff of 620" from falling through every shock
    # pattern, matching none, and being run as a neutral scenario.
    _cutoff(said, ask)

    # ---- shocks -------------------------------------------------------
    _shocks(said, ask)
    if ask.needs_clarification:
        return ask

    # A narrowing turn keeps the SHOCKS of the scenario it narrows, as it
    # already keeps its population. Only when the sentence refers back: a bare
    # new sentence starts a new scenario.
    if _BACKREF.search(said) and not ask.cutoff:
        carry_shocks(ask, dict(carried.get("shocks") or {}))
        if carried.get("scenario_weights") and ask.scenario_weights is None:
            ask.scenario_weights = dict(carried["scenario_weights"])
            ask.read_as.append("carrying forward the scenario weights")
    elif (named_population and _NARROWS_ONLY.match(said) and ask.is_neutral
          and not ask.cutoff and carried.get("shocks")):
        # A sentence that names ONLY a population is narrowing the scenario on
        # screen. "Only salary-transfer customers.", asked straight after
        # "increase personal-finance PD by 20% relative", was refused with
        # "CreditProbe could not read a change in that" — the back-reference
        # test wanted "only FOR" or "narrow to", and the most ordinary way in
        # English to say it names the population and nothing else. There is
        # only one scenario it can be narrowing, it states no shock of its
        # own, and refusing it sends the reader back to retype the shock they
        # just ran.
        carry_shocks(ask, dict(carried.get("shocks") or {}))
        if carried.get("scenario_weights") and ask.scenario_weights is None:
            ask.scenario_weights = dict(carried["scenario_weights"])
            ask.read_as.append("carrying forward the scenario weights")

    unsupported = _unsupported(said, ask)
    if unsupported:
        ask.unsupported = unsupported
        return ask

    # A sentence that named no operation, and did not ask for none.
    #
    #     "Make risk worse."
    #
    # was answered "ECL 15,952,109 → 15,952,109" — a scenario that changed
    # nothing, presented as a run. A reader takes that for "this shock has no
    # impact", which is the opposite of what happened: nothing in the sentence
    # was understood. A neutral run is a legitimate and important scenario —
    # it is the parity check — but only where somebody ASKED for one.
    if ask.is_neutral and not _EXPLICITLY_NEUTRAL.search(said) and said:
        _ask_for_a_shock(ask)
    return ask


#: How a person names the application-score cutoff. "Cut-off", "score floor",
#: "minimum application score" and "approval threshold" are the same control.
_CUTOFF_SUBJECT = (r"(?:application[- ]score\s+)?cut[- ]?off|score\s+floor|"
                   r"minimum\s+application\s+score|approval\s+threshold")


def _cutoff(said: str, ask: Ask) -> None:
    """An application-score cutoff to replay, and the products to replay it on.

    The defect this closes
    ----------------------
        "Replay an application cutoff of 620 on personal finance."

    named a methodology the screen advertises, matched no shock pattern, and
    was therefore run as a scenario with no shocks — the published book,
    returned under the reader's question as though it were the answer. An
    advertised capability that silently answers with the baseline is worse
    than one that is not offered.
    """
    match = re.search(
        rf"\b(?:{_CUTOFF_SUBJECT})\b[^.;]{{0,30}}?{_NUMBER}", said)
    if not match:
        match = re.search(
            rf"{_NUMBER}\s*(?:points?\s*)?\b(?:{_CUTOFF_SUBJECT})\b", said)
    if not match:
        return
    score = float(match.group(1))

    # A cutoff is a point on the application score scale. A number that cannot
    # be one is a misread sentence, not a scenario: say so rather than replay
    # a threshold of 20.
    if not 300.0 <= score <= 900.0:
        ask.unsupported.append(
            f"an application-score cutoff of {score:g} — the application score "
            "runs from 300 to 900, so this is not a point on it")
        return

    products = ([str(ask.filters["product_code"])]
                if ask.filters.get("product_code") else list(_ALL_PRODUCTS))
    ask.cutoff = {code: score for code in products}
    ask.read_as.append(
        f"replay an application-score cutoff of {score:g} on "
        + ("the whole book" if len(products) > 1 else products[0]))


#: Every governed retail product a cutoff can be replayed on, in one place so
#: the whole-book reading names the same set the engine validates against.
_ALL_PRODUCTS: tuple[str, ...] = tuple(sorted(set(PRODUCTS.values())))


#: Shocks that are the same CONTROL expressed two ways. A new sentence naming
#: one of a family replaces the carried other — "instead, two percentage points"
#: must not leave the earlier relative increase sitting underneath it.
SHOCK_FAMILIES: dict[str, str] = {
    "pd_relative": "pd",
    "pd_absolute_pp": "pd",
}


def family(shock: str) -> str:
    return SHOCK_FAMILIES.get(shock, shock)


#: A sentence that continues the scenario on the table rather than starting a
#: new one. "Apply the same shock only to salary-transfer customers" narrows
#: THAT scenario; "show me credit cards" does not.
#: A sentence that OPENS by restricting, and then names only a population.
#: "Only salary-transfer customers." is the scenario on the table, narrowed.
#: Anchored at the start deliberately: "show me credit cards" also names a
#: population and is a request to LOOK at credit cards, not to re-apply the
#: last shock to them.
_NARROWS_ONLY = re.compile(
    r"^(?:and\s+|now\s+|then\s+|but\s+)*"
    r"(?:only|just|restrict(?:ed)?\s+to|limit(?:ed)?\s+to|"
    r"narrow(?:ed)?\s+to)\b", re.IGNORECASE)


_BACKREF = re.compile(
    r"\bthe same\b|\bsame shock\b|\bthat shock\b|\bthis shock\b|"
    r"\bagain\b|\bas above\b|\bonly (?:to|for|on)\b|\brestrict\w*\b|"
    r"\bnarrow\w*\b|\bjust (?:to|for)\b|\blimit (?:it|this|that)\b|"
    r"\bnow (?:only|just)\b|\bkeep (?:the|that|this)\b")


def carry_shocks(ask: Ask, carried_shocks: dict[str, Any]) -> None:
    """Keep the shocks of the scenario being narrowed, without compounding them.

    The defect this closes
    ----------------------
        "Increase PD by 20% relative for personal finance."
        "Apply the same shock only to salary-transfer customers."

    The second sentence narrowed the population correctly and DROPPED the 20%,
    so the screen answered a request to re-apply a shock with the untouched
    published book — a neutral run, labelled as the reader's scenario. The
    engine promises an instruction is never dropped; this is where the
    conversational half was breaking it.

    A shock the new sentence states wins: a sentence naming any PD shock
    replaces a carried PD shock of either unit, so "instead, two percentage
    points" does not silently sit on top of the earlier relative increase.
    """
    claimed = {family(name) for name in ask.shocks}
    kept: list[str] = []
    for name, value in (carried_shocks or {}).items():
        if name not in wif.SUPPORTED_METHODOLOGIES:
            continue
        if family(name) in claimed:
            continue
        ask.shocks[name] = value
        claimed.add(family(name))
        kept.append(name)
    if kept:
        ask.read_as.append(
            "carrying forward " + ", ".join(sorted(kept)) + " from the scenario "
            "on the table")


#: A sentence that states its scope as everything. Widening, not narrowing,
#: and the one thing a carried population must not survive.
_WHOLE_BOOK = re.compile(
    r"\b(?:the\s+)?(?:whole|entire|full|complete)\s+"
    r"(?:retail\s+)?(?:book|portfolio|population)\b|"
    r"\bacross\s+(?:the\s+)?(?:whole\s+)?(?:retail\s+)?book\b|"
    r"\ball\s+products\b|\bevery\s+product\b|\bportfolio[- ]wide\b|"
    r"\bbook\s+as\s+a\s+whole\b", re.IGNORECASE)


#: A sentence that asks for the reweighting methodology by name.
_NAMES_WEIGHTS = re.compile(
    r"\b(?:scenario|macro(?:economic)?)\s+weight|"
    r"\bweight\w*\s+(?:toward|towards|to)\s+(?:the\s+)?"
    r"(?:down[- ]?turn|downside|adverse|up[- ]?turn|upside|base)|"
    r"\b(?:shift|move|reweight|re-weight)\w*\s+(?:the\s+)?"
    r"(?:macro|scenario)\b", re.IGNORECASE)

#: A sentence that ASKED for no change. The parity check is a real scenario
#: and must keep working; what must not happen is an unreadable sentence being
#: treated as a request for one.
_EXPLICITLY_NEUTRAL = re.compile(
    r"\bneutral\b|\bno[- ]change\b|\bunchanged\b|\bparity\b|"
    r"\bbaseline only\b|\bwithout any (?:shock|change)\b|"
    r"\bleave everything (?:as it is|unchanged)\b|"
    r"\bdo(?:es)? not change anything\b", re.IGNORECASE)

def _published_weights() -> dict[str, float]:
    """The weights the book was computed with, read rather than restated.

    Offering alternatives against a hard-coded set would eventually offer a
    "movement from the published weights" that is not one.
    """
    try:
        from backend.retail.config import load_config

        return {name: float(value)
                for name, value in load_config().scenarios.weights.items()}
    except Exception:  # noqa: BLE001 - the offer still works without it
        return {}

_WEIGHT_CHOICES: tuple[tuple[str, str, dict[str, float]], ...] = (
    ("mild", "Mild downturn tilt — base 0.40, upturn 0.15, downturn 0.45",
     {"base": 0.40, "upturn": 0.15, "downturn": 0.45}),
    ("severe", "Severe downturn tilt — base 0.30, upturn 0.10, downturn 0.60",
     {"base": 0.30, "upturn": 0.10, "downturn": 0.60}),
    ("downturn_only", "Downturn only — base 0.00, upturn 0.00, downturn 1.00",
     {"base": 0.00, "upturn": 0.00, "downturn": 1.00}),
)


def _ask_for_weights(said: str, ask: "Ask") -> None:
    """Offer three reweightings rather than inventing one."""
    current = _published_weights()
    published = ("/".join(f"{current.get(s, 0.0):.2f}"
                          for s in ("base", "upturn", "downturn"))
                 if current else "")
    ask.question = (
        "Reweighting the macroeconomic scenarios needs three numbers, and "
        "CreditProbe will not choose them."
        + (f" The published weights are base/upturn/downturn = {published}."
           if published else "")
        + " Pick a reweighting, or type the three weights you want.")
    ask.options = [
        {"id": key, "label": label, "shocks": {},
         "scenario_weights": dict(weights)}
        for key, label, weights in _WEIGHT_CHOICES
    ]


def _ask_for_a_shock(ask: "Ask") -> None:
    """Offer the engine's own scenarios rather than running an empty one."""
    ask.question = (
        "CreditProbe could not read a change in that. A What-If needs "
        "something to move and by how much — running it as written would "
        "recompute the published book unchanged and report it as your "
        "scenario. Pick one of these, or say what to move and by how much.")
    ask.options = [
        {"id": "pd20", "label": "Increase PD by 20% relative",
         "shocks": {"pd_relative": 0.20}},
        {"id": "pd2pp", "label": "Add 2 percentage points to PD",
         "shocks": {"pd_absolute_pp": 2.0}},
        {"id": "lgd10", "label": "Increase LGD by 10% relative",
         "shocks": {"lgd_relative": 0.10}},
        {"id": "util10",
         "label": "Move card utilisation up 10 percentage points",
         "shocks": {"utilisation_pp": 10.0}},
        {"id": "income10", "label": "Cut verified income by 10%",
         "shocks": {"income_pct": -0.10}},
    ]


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


def _rate_shock(said: str, ask: Ask, subject: str, label: str,
                relative_key: str, absolute_key: str,
                example_pct: float) -> bool:
    """A shock on a per-facility RATE, where the unit changes the scenario.

    "+20%" multiplies and "+20 percentage points" adds, and on a rate that
    differs by facility those are two different scenarios — not two ways of
    saying one. Both are implementable and both are implemented; what is not
    allowed is guessing which was meant.

    This was PD-only. LGD went through `_simple`, which understands percent
    and nothing else, so "Increase LGD by 5 percentage points" — a chip the
    product offered on three screens — was refused. The capability was
    missing; the chip was right.

    Returns True when it consumed the sentence with a clarification.
    """
    # Two word orders, because people use both and §23 forbids refusing one
    # for being phrased the other way. Subject first — "increase LGD by 5
    # percentage points" — and amount first — "add 5 percentage points to
    # LGD". The second was unreadable, so "Add 2 percentage points to PD",
    # which the product offers as a chip, could not be typed.
    patterns = (
        rf"{subject}[^.;]{{0,40}}?\b(?:by|of|to)?\s*(?:up\s+)?{_NUMBER}\s*"
        rf"({_POINTS}|{_PERCENT})?",
        rf"{_NUMBER}\s*({_POINTS}|{_PERCENT})\s*(?:on|to|of|onto|for)\s+"
        rf"(?:the\s+)?{subject}",
    )
    # A match WITH a unit beats one without, whichever pattern produced it.
    # Taking the first pattern's first match read "add 5 percentage points to
    # LGD for Stage 2 Home Finance" as an unspecified move of 2 — the "2" in
    # "Stage 2" — and asked the reader which unit they meant, about a sentence
    # that had said so twice.
    candidates = [one for pattern in patterns
                  for one in re.finditer(pattern, said)]
    found = next((one for one in candidates if one.group(2)),
                 candidates[0] if candidates else None)
    for match in ([found] if found is not None else []):
        amount, unit = float(match.group(1)), (match.group(2) or "")
        direction = -1.0 if re.search(
            r"\b(?:reduc\w+|decreas\w+|lower|cut|down|fall\w*)\b",
            said[:match.start()][-60:]) else 1.0
        sign = "+" if direction > 0 else "−"
        if re.search(_POINTS, unit):
            ask.shocks[absolute_key] = direction * amount
            ask.read_as.append(
                f"{label} {sign}{amount:g} percentage points")
        elif re.search(_PERCENT, unit):
            ask.shocks[relative_key] = direction * amount / 100.0
            ask.read_as.append(f"{label} {sign}{amount:g}% relative")
        else:
            moved = example_pct * (1 + amount / 100)
            ask.question = (
                f"Do you mean {amount:g} percent of the current {label}, or "
                f"{amount:g} percentage points added to it? On a {label} of "
                f"{example_pct:g}% the first gives {moved:.4g}% and the "
                f"second {example_pct + amount:g}% — they are different "
                f"scenarios, so CreditProbe will not guess.")
            ask.options = [
                {"id": "relative",
                 "label": f"{amount:g}% relative (multiply the {label} by "
                          f"{1 + amount / 100:.4g})",
                 "shocks": {relative_key: direction * amount / 100.0}},
                {"id": "absolute",
                 "label": f"{amount:g} percentage points (add {amount:g}pp to "
                          f"the {label})",
                 "shocks": {absolute_key: direction * amount}},
            ]
            return True
        return False
    return False


def _shocks(said: str, ask: Ask) -> None:
    """Every shock the sentence names, or the question its units leave open."""
    # --- PD and LGD: the two whose unit decides which scenario was asked for
    if _rate_shock(said, ask, r"\b(?:pd|probability of default)\b", "PD",
                   "pd_relative", "pd_absolute_pp", example_pct=2.0):
        return
    if _rate_shock(said, ask, r"\b(?:lgd|loss given default)\b", "LGD",
                   "lgd_relative", "lgd_absolute_pp", example_pct=35.0):
        return
    _simple(said, ask, r"\bcollateral\b", "collateral_value_pct",
            percent_scale=0.01, label="collateral values")
    # A HAIRCUT is a collateral reduction, and it is the word a credit officer
    # actually uses: "apply a 15% haircut on secured auto finance" parsed no
    # shock at all, resolved the population correctly, and was then refused
    # for naming no change. Always a reduction — there is no such thing as a
    # negative haircut — so the sign is not read from the sentence.
    if "collateral_value_pct" not in ask.shocks:
        cut = re.search(rf"\bhair[- ]?cut\b[^.;]{{0,30}}?{_NUMBER}\s*"
                        rf"(?:{_PERCENT})?"
                        rf"|{_NUMBER}\s*(?:{_PERCENT})?[^.;]{{0,20}}?"
                        rf"\bhair[- ]?cut\b", said)
        if cut:
            amount = float(next(g for g in cut.groups() if g))
            ask.shocks["collateral_value_pct"] = -abs(amount) * 0.01
            ask.read_as.append(
                f"a {abs(amount):g}% haircut on collateral values")
    _simple(said, ask, r"\b(?:income|salar(?:y|ies))\b", "income_pct",
            percent_scale=0.01, label="verified income")
    # Expenses are read separately from income and land on the same
    # affordability path. "Increase the household expense burden by 10%" is a
    # cost-of-living scenario, not a pay cut, and the two can be asked for
    # together.
    _simple(said, ask,
            r"\b(?:household\s+)?(?:expense|expenses|cost\s+of\s+living|"
            r"living\s+cost)s?\b(?:\s+burden)?", "expense_pct",
            percent_scale=0.01, label="household expenses")

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

    match = re.search(
        rf"\b(?:ccf|credit conversion factor)\b[^.;]{{0,24}}?{_NUMBER}\s*"
        rf"({_POINTS}|{_PERCENT})?", said) or re.search(
        rf"{_NUMBER}\s*({_POINTS}|{_PERCENT})\s*(?:on|to|of|onto|for)\s+"
        rf"(?:the\s+)?\b(?:ccf|credit conversion factor)\b", said)
    if match:
        value = float(match.group(1))
        unit = match.group(2) or ""
        window = said[:match.start()][-40:] + said[match.end():match.end() + 20]
        # "Increase CCF by 10 percentage points" is an ADDITION to the
        # published 0.45. Read as a set — which is what `ccf_absolute` does —
        # it moved the factor to 0.10, a reduction, while reporting the
        # increase the reader asked for.
        adds = bool(re.search(_POINTS, unit)) or bool(re.search(
            r"\b(?:increase|raise|add|lift|reduce|lower|cut|decrease)\b", window))
        direction = -1.0 if re.search(
            r"\b(?:reduc\w+|decreas\w+|lower|cut)\b", window) else 1.0
        if adds:
            points = value if value > 1 else value * 100.0
            ask.shocks["ccf_absolute_pp"] = direction * points
            ask.read_as.append(
                f"credit conversion factor {'+' if direction > 0 else '−'}"
                f"{points:g} percentage points")
        else:
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


#: How each shock reads back to the person who asked for it, so a scenario
#: assembled from a CLICK describes itself in the same words as one that was
#: typed.
def _say_shock(name: str, value: Any) -> str:
    number = float(value)
    if name == "pd_relative":
        return f"PD {number * 100:+g}% relative"
    if name == "pd_absolute_pp":
        return f"PD {number:+g} percentage points"
    if name == "lgd_relative":
        return f"LGD {number * 100:+g}% relative"
    if name == "collateral_value_pct":
        return f"collateral values {number * 100:+g}% relative"
    if name == "income_pct":
        return f"verified income {number * 100:+g}% relative"
    if name == "utilisation_pp":
        return f"card utilisation {number:+g} percentage points"
    if name == "recovery_delay_months":
        return f"recovery delayed {number:g} months"
    if name == "ccf_absolute":
        return f"credit conversion factor set to {number:.2f}"
    if name == "behavioural_score_points":
        return f"behavioural score {number:+g} points"
    return f"{name} {number:g}"


def describe_scenario(ask: Ask) -> list[str]:
    """What a resolved scenario says about itself, rebuilt from its own fields.

    The defect this closes
    ----------------------
    Answering "do you mean 2 percent or 2 percentage points?" by CLICKING a
    button produced a run whose `read_as` was empty, because the button's label
    was parsed as a fresh sentence and named nothing. The screen falls back to
    "An unchanged scenario over the whole retail book" when nothing was read —
    so a two-percentage-point shock on personal finance was captioned as the
    untouched book. The figures were right and the sentence above them was not,
    which is the harder error to catch.
    """
    lines: list[str] = []
    product = ask.filters.get("product_code")
    if product:
        lines.append(f"{product} only")
    for column, value in ask.filters.items():
        if column == "product_code":
            continue
        lines.append(f"{column.replace('_', ' ')} = {value}")
    for name, value in ask.shocks.items():
        lines.append(_say_shock(name, value))
    if ask.scenario_weights:
        lines.append("weights base/upturn/downturn = " + "/".join(
            f"{ask.scenario_weights.get(s, 0.0):.2f}"
            for s in ("base", "upturn", "downturn")))
    if ask.staging_mode == wif.REEVALUATE_STAGE:
        lines.append("staging re-evaluated")
    if ask.cutoff:
        level = next(iter(ask.cutoff.values()))
        lines.append(f"replay an application-score cutoff of {level:g} on "
                     + ("the whole book" if len(ask.cutoff) > 1
                        else next(iter(ask.cutoff))))
    return lines


def describe(ask: Ask) -> str:
    """What CreditProbe understood, in one line, for the answer to open with.

    The fallback is built from the scenario's OWN fields rather than written
    out. A turn that read nothing new still inherits the population of the
    turn before it, and the sentence "An unchanged scenario over the whole
    retail book" was printed above a run scoped to credit cards. A caption
    that contradicts the population under it is worse than no caption.
    """
    if ask.read_as:
        return "Read as: " + "; ".join(ask.read_as) + "."
    scope = describe_scenario(ask)
    if scope:
        return "An unchanged scenario over " + "; ".join(scope) + "."
    return "An unchanged scenario over the whole retail book."


def supported_sentence() -> str:
    """The list a refusal offers, built from the engine's own contract."""
    return ", ".join(sorted(wif.SUPPORTED_METHODOLOGIES))
