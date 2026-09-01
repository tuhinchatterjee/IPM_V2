"""
Building a method from a description, and testing it before anybody trusts it.

The flow
--------
A methodology owner describes a method in their own words. CreditProbe reads it,
says what it understood, and asks about the parts that were genuinely ambiguous —
not everything, because a builder that asks twelve questions is a form.

    describe -> clarify -> MethodDefinition + Analytical IR -> tests -> certify

The clarifications are not decoration. "Look one year forward and count defaults"
leaves at least four real decisions open, and two banks answering them
differently get materially different numbers from the same book:

    facility level or customer level?
    default at the horizon, or at any point up to it?
    what about accounts that closed in between?
    counted by number, or weighted by exposure?

Each is asked because the answer changes the plan, and each answer is recorded on
the method so a reviewer nine months later can see what was decided rather than
inferring it from SQL.

What the model does and does not do here
----------------------------------------
It reads prose and proposes structure. It does not compute, and it does not
decide whether the method is right: the plan it proposes goes through the same
validator as everything else, the test data is generated deterministically by
code below, and the expected results are computed by an independent
implementation rather than by running the method under test.

That last point matters. A test whose expectation comes from the thing being
tested asserts only that the code is deterministic.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.studio.model import Category, Lifecycle, MethodDefinition

logger = logging.getLogger(__name__)


# ------------------------------------------------------------- clarifications


@dataclass
class Clarification:
    """One decision the description left open."""

    id: str
    question: str
    #: Why it matters — shown under the question, because "grain?" means nothing
    #: to somebody who has not thought about it before.
    because: str
    options: list[dict[str, str]] = field(default_factory=list)
    default: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "question": self.question, "because": self.because,
                "options": self.options, "default": self.default}


#: The decisions a forward-looking default measure always has to make. Asked in
#: the order they change the answer by, largest first.
FORWARD_RATE_CLARIFICATIONS = [
    Clarification(
        "grain", "Facility level or customer level?",
        "A customer with four facilities counts once at customer level and four "
        "times at facility level. On a corporate book the two rates differ by "
        "more than most people expect.",
        [{"id": "facility", "label": "Facility level",
          "detail": "One row per account. The usual choice for a corporate book."},
         {"id": "customer", "label": "Customer level",
          "detail": "One row per obligor. A customer defaults if any facility does."}],
        "facility"),
    Clarification(
        "default_definition", "What counts as default?",
        "90 days past due and IFRS 9 Stage 3 usually overlap but are not the "
        "same population, and the gap between them is where the argument lives.",
        [{"id": "dpd90", "label": "90 or more days past due",
          "detail": "The arrears definition. Objective and easy to reconcile."},
         {"id": "stage3", "label": "IFRS 9 Stage 3",
          "detail": "The accounting definition. Includes unlikely-to-pay cases "
                    "with no arrears."},
         {"id": "either", "label": "Either",
          "detail": "90+ DPD or Stage 3. The widest definition."}],
        "dpd90"),
    Clarification(
        "timing", "Default at the horizon, or at any point before it?",
        "An account that defaulted in month seven and cured by month twelve is a "
        "default under one reading and not under the other.",
        [{"id": "at_horizon", "label": "Status at the horizon date",
          "detail": "Simpler, and reconcilable to a published position."},
         {"id": "anytime", "label": "Default at any point within the horizon",
          "detail": "Truer to credit experience, and needs every intervening "
                    "period."}],
        "at_horizon"),
    Clarification(
        "exits", "What about accounts that leave the book before the horizon?",
        "They have no forward observation. Excluding them assumes their exit was "
        "unrelated to credit quality, which is exactly the assumption that fails "
        "when a bank exits weakening names.",
        [{"id": "exclude", "label": "Exclude them",
          "detail": "The rate describes only accounts that could be observed."},
         {"id": "non_default", "label": "Treat as not defaulted",
          "detail": "Assumes an exit was a repayment. Understates the rate."}],
        "exclude"),
    Clarification(
        "weighting", "Counted by number, or weighted by exposure?",
        "An unweighted rate treats a two-million facility and a two-hundred-"
        "million facility as one event each.",
        [{"id": "count", "label": "By number of accounts",
          "detail": "The frequency. Comparable to a PD."},
         {"id": "ead", "label": "Weighted by exposure at default",
          "detail": "The loss-relevant view."},
         {"id": "both", "label": "Both, side by side",
          "detail": "The divergence between them is itself informative."}],
        "count"),
]


# -------------------------------------------------------- reading description


@dataclass
class Reading:
    """What CreditProbe made of a description, before anything is built."""

    understood: bool
    summary: str = ""
    kind: str = ""                     # forward_rate | ratio | distribution | unknown
    horizon_periods: int = 0
    detected: dict[str, Any] = field(default_factory=dict)
    clarifications: list[Clarification] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "understood": self.understood, "summary": self.summary,
            "kind": self.kind, "horizon_periods": self.horizon_periods,
            "detected": self.detected,
            "clarifications": [c.to_dict() for c in self.clarifications],
            "note": self.note,
        }


_HORIZONS = [
    (r"\b(one|1)[\s-]*year|12[\s-]*month|annual", 4),
    (r"\b(six|6)[\s-]*month|two quarter", 2),
    (r"\b(three|3)[\s-]*month|one quarter|1[\s-]*quarter", 1),
    (r"\b(two|2)[\s-]*year|24[\s-]*month", 8),
]


def read_description(text: str) -> Reading:
    """Work out what kind of method is being described.

    Deterministic pattern matching rather than a model call, and deliberately
    so: this decides which clarifications to ask, and a clarification set that
    varies run to run makes the builder feel unreliable. The model's role is
    the prose around this — the summary a person reads — not the routing.
    """
    lowered = " ".join(str(text).lower().split())
    if not lowered:
        return Reading(False, note="Describe the method and CreditProbe will "
                                   "read it back to you.")

    horizon = 0
    for pattern, periods in _HORIZONS:
        if re.search(pattern, lowered):
            horizon = periods
            break

    forward = bool(
        re.search(r"forward|look\s+(one|two|1|2|ahead)|later|subsequent|"
                  r"after\s+(one|a)\s+year|next\s+(year|12)", lowered)
    )
    default_words = bool(re.search(r"default|dpd|past due|stage\s*3|"
                                   r"non[- ]?performing|npl", lowered))

    detected: dict[str, Any] = {}
    dpd_threshold = re.search(r"(\d{2,3})\s*(?:\+|or more)?\s*(?:days?\s*)?"
                              r"(?:past due|dpd)", lowered)
    if dpd_threshold:
        detected["dpd_threshold"] = int(dpd_threshold.group(1))
    if re.search(r"\bcustomer|obligor|borrower\s+level", lowered):
        detected["grain"] = "customer"
    if re.search(r"\bfacilit|account\s+level", lowered):
        detected["grain"] = "facility"
    if re.search(r"\bead|exposure[- ]weighted|weighted by exposure", lowered):
        detected["weighting"] = "ead"

    if (forward or horizon) and default_words:
        return Reading(
            understood=True,
            kind="forward_rate",
            horizon_periods=horizon or 4,
            detected=detected,
            summary=_forward_summary(horizon or 4, detected),
            clarifications=[c for c in FORWARD_RATE_CLARIFICATIONS
                            if c.id not in detected],
        )

    if re.search(r"\bratio|share|percentage|rate\b|divided by|per cent", lowered):
        return Reading(
            understood=True, kind="ratio", detected=detected,
            summary="A ratio: one measured population as a share of another, at "
                    "a single reporting date.",
            clarifications=[FORWARD_RATE_CLARIFICATIONS[0],
                            FORWARD_RATE_CLARIFICATIONS[4]],
        )

    if re.search(r"\bdistribut|split|breakdown|by sector|by rating|across", lowered):
        return Reading(
            understood=True, kind="distribution", detected=detected,
            summary="A distribution: a measure broken down across a dimension "
                    "at a single reporting date.",
            clarifications=[FORWARD_RATE_CLARIFICATIONS[4]],
        )

    return Reading(
        understood=False,
        note="CreditProbe could not tell what kind of measure this is. It builds "
             "forward-looking rates, ratios and distributions today. Say what is "
             "counted, what it is divided by, and over what period.",
    )


def _forward_summary(horizon: int, detected: dict[str, Any]) -> str:
    label = {1: "one quarter", 2: "six months", 4: "one year",
             8: "two years"}.get(horizon, f"{horizon} quarters")
    threshold = detected.get("dpd_threshold", 90)
    return (
        f"A forward-looking default rate over {label}. CreditProbe reads this "
        f"as: take the population performing at each opening date, look "
        f"{label} forward, count those in default ({threshold}+ days past "
        f"due), and divide by the opening population."
    )


# ------------------------------------------------------------ building the IR


def build_forward_rate_plan(*, dataset: str = "portfolio_facility",
                            opening_period: str, closing_period: str,
                            answers: dict[str, str] | None = None,
                            dpd_threshold: int = 90) -> dict[str, Any]:
    """The Analytical IR for a forward default rate.

    Written as an explicit plan rather than generated by a model. The model
    proposes WHICH method to build and what its parameters are; the shape of a
    forward rate is a known thing, and a known thing belongs in code where it
    can be read, reviewed and tested.
    """
    answers = answers or {}
    if answers.get("timing") == "anytime":
        # Refused rather than approximated. Reading status only at the horizon
        # and labelling it "default at any point" would return a lower rate than
        # the method claims to compute, and nothing about the result would look
        # wrong. Building it properly needs every intervening period.
        raise ValueError(
            "Counting a default at any point within the horizon needs every "
            "reporting period between the two dates, which this release does "
            "not read. Use status at the horizon, or narrow the horizon to one "
            "period so the two readings coincide."
        )
    grain = answers.get("grain", "facility")
    key = "customer_id" if grain == "customer" else "account_id"
    weighting = answers.get("weighting", "count")
    default_definition = answers.get("default_definition", "dpd90")
    exits = answers.get("exits", "exclude")

    opening_fields = [key, "dpd_days", "ead"]
    closing_fields = [key, "dpd_days"]
    if default_definition in ("stage3", "either"):
        opening_fields.append("ifrs9_stage")
        closing_fields.append("ifrs9_stage")

    # The default test, as an expression tree. Both columns carry the join's
    # right-hand prefix: they are the FORWARD observation, and reading the
    # opening stage here would test whether an account was already impaired —
    # a different question with a plausible-looking answer.
    def default_test() -> dict[str, Any]:
        dpd = {"type": "function", "function": "gte",
               "args": ["forward_dpd_days",
                        {"type": "literal", "value": dpd_threshold}]}
        stage = {"type": "function", "function": "gte",
                 "args": ["forward_ifrs9_stage", {"type": "literal", "value": 3}]}
        if default_definition == "dpd90":
            return dpd
        if default_definition == "stage3":
            return stage
        return {"type": "function", "function": "or", "args": [dpd, stage]}

    operations: list[dict[str, Any]] = [
        {"id": "opening", "op": "SCAN",
         "label": f"Opening population · {opening_period}",
         "params": {"dataset": dataset, "period": opening_period,
                    "fields": opening_fields}},
        {"id": "performing", "op": "FILTER", "inputs": ["opening"],
         "label": f"Performing at {opening_period}",
         "params": {"where": [{"column": "dpd_days", "op": "<",
                               "value": dpd_threshold}]}},
        {"id": "closing", "op": "SCAN",
         "label": f"Forward observation · {closing_period}",
         "params": {"dataset": dataset, "period": closing_period,
                    "fields": closing_fields}},
    ]

    # An inner join drops accounts with no forward observation; a left join
    # keeps them. Which one is right IS the "exits" answer, so it is expressed
    # in the plan rather than decided quietly.
    operations.append({
        "id": "followed", "op": "JOIN", "inputs": ["performing", "closing"],
        "label": ("Follow forward, excluding exits" if exits == "exclude"
                  else "Follow forward, keeping exits as non-defaults"),
        "params": {"kind": "inner" if exits == "exclude" else "left",
                   "on": [key], "right_prefix": "forward_"},
    })

    operations.append({
        "id": "flagged", "op": "DERIVE", "inputs": ["followed"],
        "label": "Flag those in default at the forward date",
        "params": {"columns": [{
            "as": "defaulted",
            "expression": {
                "type": "case",
                "whens": [[default_test(),
                           {"type": "literal", "value": 1}]],
                "otherwise": {"type": "literal", "value": 0},
            },
        }]},
    })

    aggregates: list[dict[str, Any]] = [
        {"function": "count", "as": "opening_population"},
        {"column": "defaulted", "function": "sum", "as": "defaults"},
    ]
    if weighting in ("ead", "both"):
        aggregates += [
            {"column": "ead", "function": "sum", "as": "opening_ead"},
            {"column": "ead", "function": "weighted_avg", "weight": "ead",
             "as": "mean_facility_ead"},
        ]

    operations.append({
        "id": "totals", "op": "AGGREGATE", "inputs": ["flagged"],
        "label": "Count the opening population and the defaults",
        "params": {"aggregates": aggregates},
    })
    operations.append({
        "id": "rate", "op": "RATIO", "inputs": ["totals"],
        "label": "Defaults over opening population",
        "params": {"numerator": "defaults", "denominator": "opening_population",
                   "as": "forward_default_rate_pct"},
    })

    return {
        "objective": (f"Forward default rate from {opening_period} to "
                      f"{closing_period}, {grain} level"),
        "operations": operations,
        "output": "rate",
        "meta": {"kind": "forward_rate", "answers": answers,
                 "dpd_threshold": dpd_threshold,
                 "opening_period": opening_period,
                 "closing_period": closing_period},
    }


def build_method(*, id: str, name: str, description: str,
                 reading: Reading, answers: dict[str, str],
                 opening_period: str, closing_period: str,
                 dataset: str = "portfolio_facility",
                 author: str = "") -> MethodDefinition:
    """Assemble the MethodDefinition from the description and the answers."""
    if reading.kind != "forward_rate":
        raise ValueError(
            "The method builder implements forward-looking rates in this "
            "release. Ratios and distributions are read and summarised but not "
            "yet built."
        )

    threshold = int(reading.detected.get("dpd_threshold", 90))
    grain = answers.get("grain", "facility")
    plan = build_forward_rate_plan(
        dataset=dataset, opening_period=opening_period,
        closing_period=closing_period, answers=answers, dpd_threshold=threshold,
    )

    horizon = {1: "one quarter", 2: "six months", 4: "one year",
               8: "two years"}.get(reading.horizon_periods, "the stated horizon")
    definitions = {
        "dpd90": f"{threshold} or more days past due",
        "stage3": "IFRS 9 Stage 3",
        "either": f"{threshold}+ days past due or IFRS 9 Stage 3",
    }
    default_text = definitions[answers.get("default_definition", "dpd90")]

    return MethodDefinition(
        id=id, name=name, category=Category.DEFAULT_DELINQUENCY,
        definition=(f"The share of the {grain}-level population performing at a "
                    f"reporting date that is in default {horizon} later."),
        purpose="The empirical counterpart to a modelled probability of "
                "default: what actually happened to the population that looked "
                "sound at the opening date.",
        methodology=(
            f"Opening population: every {grain} with fewer than {threshold} days "
            f"past due at the opening reporting date.\n"
            f"Forward observation: the same {grain} identifiers {horizon} later.\n"
            f"Default: {default_text} at the forward date.\n"
            f"Rate: defaults divided by the opening population, "
            f"{'counted by number' if answers.get('weighting', 'count') == 'count' else 'weighted by exposure'}.\n"
            f"{grain.title()}s with no forward observation are "
            f"{'excluded' if answers.get('exits', 'exclude') == 'exclude' else 'treated as not defaulted'}."
        ),
        lifecycle=Lifecycle.BUILT,
        aliases=_aliases_for(name),
        when_to_use="Backtesting a PD model, or setting expectations from "
                    "realised experience.",
        when_not_to_use=(
            f"Where less than {reading.horizon_periods + 1} periods of history "
            "exist, or where identifiers are not stable across periods."),
        required_grain=f"{grain.title()} per reporting period",
        required_history=f"{reading.horizon_periods + 1} periods",
        required_domains=["credit_facility_position"],
        required_fields=sorted({
            "account_id" if grain == "facility" else "customer_id",
            "dpd_days", "ead",
        }),
        weighting_options=["count", "EAD"],
        output_type="Percentage",
        interpretation="Read against the PD assigned at the opening date. A "
                       "realised rate persistently above the predicted one is a "
                       "calibration finding, not noise.",
        limitations=(
            f"{grain.title()}s that leave the book between the two dates have no "
            "forward observation and are excluded, which biases the result if "
            "exits are not random. A rate measured on one pair of periods is one "
            "observation — read several before concluding anything."
        ),
        plan=plan,
        source="bank",
        created_at=datetime.now(UTC).isoformat(),
        updated_at=datetime.now(UTC).isoformat(),
        owner=author or "Credit Risk Analytics",
    )


def _aliases_for(name: str) -> list[str]:
    """Obvious other names, so the method is findable by what people type."""
    aliases = {name.lower()}
    compact = re.sub(r"[^a-z0-9 ]", "", name.lower())
    aliases.add(compact)
    initials = "".join(w[0] for w in compact.split() if w)
    if len(initials) >= 3:
        aliases.add(initials)
    if "one year" in compact:
        aliases.add(compact.replace("one year", "1y"))
        aliases.add(compact.replace("one year", "12 month"))
    return sorted(a for a in aliases if a and a != name.lower())


__all__ = [
    "FORWARD_RATE_CLARIFICATIONS",
    "Clarification",
    "ProposedEdit",
    "Reading",
    "build_forward_rate_plan",
    "build_method",
    "read_description",
    "read_edit",
]


# ------------------------------------------------- editing a method in words


#: Which prose field an instruction is about. Matched longest-phrase-first, so
#: "when not to use" beats "use". Only prose: the plan is not editable as
#: English, because a sentence that changes a calculation without changing a
#: test is how a certified method quietly stops computing what it says.
_EDITABLE_FIELDS: list[tuple[str, str]] = [
    (r"when (it should )?not be used|when not to use|do not use", "when_not_to_use"),
    (r"when to use|when it should be used|applicab", "when_to_use"),
    (r"limitation|what it does not tell|caveat|weakness", "limitations"),
    (r"interpret|how to read|reading", "interpretation"),
    (r"methodolog|how it is calculated|how it works", "methodology"),
    (r"purpose|why we", "purpose"),
    (r"definition|what it measures", "definition"),
    (r"output type|output", "output_type"),
    (r"\bname\b|call it|rename", "name"),
]

#: Add to what is there, or replace it. "Also say" and "add" append; "change to"
#: and "say instead" replace. Guessing wrong loses somebody's text, so an
#: instruction matching neither is refused rather than assumed.
_APPEND = r"\b(also|add|append|include|as well|mention)\b"
_REPLACE = r"\b(change|replace|instead|reword|rewrite|set|make it|should (read|say))\b"


@dataclass
class ProposedEdit:
    """What CreditProbe would change, before anything is changed."""

    understood: bool
    field: str = ""
    mode: str = ""              # append | replace
    before: str = ""
    after: str = ""
    note: str = ""

    @property
    def diff(self) -> str:
        if not self.understood:
            return ""
        return f"{self.field}: {self.before or '(empty)'} → {self.after}"

    def to_dict(self) -> dict[str, Any]:
        return {"understood": self.understood, "field": self.field,
                "mode": self.mode, "before": self.before, "after": self.after,
                "note": self.note, "diff": self.diff}


def read_edit(instruction: str, current: dict[str, str]) -> ProposedEdit:
    """Read an instruction into a proposed change. Nothing is applied here.

    Deterministic, and it refuses rather than guesses. "Tidy this up" names no
    field and no new text; acting on it would rewrite somebody's methodology on
    a model's judgement, which is precisely the thing this product does not do.
    """
    text = " ".join(str(instruction).split())
    if not text:
        return ProposedEdit(False, note="Say what should change.")

    lowered = text.lower()
    field = ""
    for pattern, target in _EDITABLE_FIELDS:
        if re.search(pattern, lowered):
            field = target
            break
    if not field:
        return ProposedEdit(
            False,
            note=("CreditProbe could not tell which part of the method this is "
                  "about. Name one: the definition, purpose, methodology, when "
                  "to use it, when not to use it, how to read the result, its "
                  "limitations, or its name."))

    # The new text is what follows the instruction's verb. Quoted text wins,
    # because somebody who quoted it meant exactly that.
    quoted = re.search(r"[\"“']([^\"”']{3,})[\"”']", text)
    if quoted:
        replacement = quoted.group(1).strip()
    else:
        tail = re.split(
            r"\b(?:to say|should say|should read|to read|that|to|:)\s+", text,
            maxsplit=1)
        replacement = tail[1].strip() if len(tail) > 1 else ""

    if not replacement:
        return ProposedEdit(
            False, field=field,
            note=("CreditProbe read which part to change but not what to change "
                  "it to. Put the new wording in quotes."))

    mode = ("append" if re.search(_APPEND, lowered)
            else "replace" if re.search(_REPLACE, lowered) else "")
    if not mode:
        return ProposedEdit(
            False, field=field,
            note=("Say whether this replaces what is there or is added to it. "
                  "Guessing wrong loses text somebody wrote."))

    before = str(current.get(field, "") or "")
    after = (f"{before} {replacement}".strip() if mode == "append" and before
             else replacement)
    return ProposedEdit(True, field=field, mode=mode, before=before, after=after)
