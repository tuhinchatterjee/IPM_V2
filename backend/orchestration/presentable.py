"""
The last thing between an answer and a client. P0.8.

    "Do not display a polished but incomplete answer."

That sentence is the whole module. Every defect Phase 0 reproduced had the same
shape: the answer LOOKED finished. It had a headline, a table, a chart and a
confident paragraph, and it was wrong or partial in a way the reader had no way
to see. Polish is what makes an incomplete answer dangerous rather than merely
unhelpful — an obviously broken answer gets checked, and a beautiful one gets
forwarded to a credit committee.

So the answer is checked against the fourteen conditions of P0.8 before it is
shown, and the check happens HERE, once, rather than being distributed across
the places that produce each part. A validation spread over eight modules is a
validation nobody can read, and the question "is this safe to show a client?"
has to have one answer in one place.

The fourteen
------------
    every objective addressed        no duplicated phrases or entities
    a direct answer is present       no unsupported claims
    the period is right              no contradictory figures
    the population is right          the visualisation is semantically valid
    the scope is right               the validations are real
    no raw decimals                  the Trace agrees with what executed
                                     missing evidence is stated
                                     no unexplained failure

What happens when one fails
---------------------------
Not "show it with a warning". P0.8 gives three outcomes and none of them is
that:

    REPAIR    the answer is recoverable — drop the ungrounded prose, reformat
              the number, replace the chart — and what remains is honest
    CLARIFY   the answer cannot be completed without something from the user
    WITHHOLD  a controlled failure: the figures are not shown, and the reason
              is named

The verdict is the most severe remedy any MANDATORY failing check asks for. An
advisory check records what it found and never withholds an answer — it exists
so that a slow degradation shows up in the evaluation layer before it shows up
in front of a client.

This module composes, it does not reimplement
---------------------------------------------
Objectives coverage, invariants, grounding, the visualisation contract and the
failure taxonomy are all built already and all tested. Re-deriving any of them
here would produce a second opinion that can disagree with the first, which is
exactly the "contradictory states" P0.9 warns about. Every check below reads an
existing verdict.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

PASS = "PASS"
FAIL = "FAIL"
NOT_APPLICABLE = "NOT_APPLICABLE"

#: What to do about a failure, most severe last. The verdict for an answer is
#: the most severe remedy among its failing mandatory checks.
SHOW = "SHOW"
REPAIR = "REPAIR"
CLARIFY = "CLARIFY"
WITHHOLD = "WITHHOLD"

SEVERITY: dict[str, int] = {SHOW: 0, REPAIR: 1, CLARIFY: 2, WITHHOLD: 3}

# The fourteen, in the order P0.8 lists them.
OBJECTIVES = "objectives_addressed"
DIRECT_ANSWER = "direct_answer_present"
PERIOD = "period_correct"
POPULATION = "population_correct"
SCOPE = "scope_correct"
DECIMALS = "no_raw_decimals"
DUPLICATION = "no_duplication"
UNSUPPORTED = "no_unsupported_claims"
CONTRADICTION = "no_contradictory_figures"
VISUALISATION = "visualisation_semantics"
VALIDATIONS_REAL = "validations_are_real"
TRACE_AGREES = "trace_agrees_with_execution"
MISSING_STATED = "missing_evidence_stated"
NO_UNEXPLAINED = "no_unexplained_failure"

CHECKS: tuple[str, ...] = (
    OBJECTIVES, DIRECT_ANSWER, PERIOD, POPULATION, SCOPE, DECIMALS,
    DUPLICATION, UNSUPPORTED, CONTRADICTION, VISUALISATION,
    VALIDATIONS_REAL, TRACE_AGREES, MISSING_STATED, NO_UNEXPLAINED,
)

TITLES: dict[str, str] = {
    OBJECTIVES: "Every objective addressed",
    DIRECT_ANSWER: "A direct answer is present",
    PERIOD: "The period is the one asked for",
    POPULATION: "The population is the one asked for",
    SCOPE: "The scope is the one asked for",
    DECIMALS: "No raw decimals on screen",
    DUPLICATION: "No duplicated phrases or entities",
    UNSUPPORTED: "No unsupported claims",
    CONTRADICTION: "No contradictory figures",
    VISUALISATION: "The visualisation is semantically valid",
    VALIDATIONS_REAL: "The validations are real",
    TRACE_AGREES: "The Trace agrees with what executed",
    MISSING_STATED: "Missing evidence is stated",
    NO_UNEXPLAINED: "No unexplained failure",
}

#: Advisory checks record and do not withhold. Everything else is mandatory.
#: Kept short on purpose: a gate whose checks are mostly advisory is a report,
#: not a gate.
ADVISORY: frozenset[str] = frozenset({DUPLICATION})

#: What a failure of each check asks for. A missing objective is not a repair —
#: there is no way to fix it by rewriting, only by asking or by not claiming to
#: have answered.
REMEDY: dict[str, str] = {
    OBJECTIVES: WITHHOLD,
    DIRECT_ANSWER: WITHHOLD,
    PERIOD: WITHHOLD,
    POPULATION: WITHHOLD,
    SCOPE: WITHHOLD,
    DECIMALS: REPAIR,
    DUPLICATION: REPAIR,
    UNSUPPORTED: REPAIR,
    CONTRADICTION: WITHHOLD,
    VISUALISATION: REPAIR,
    VALIDATIONS_REAL: WITHHOLD,
    TRACE_AGREES: WITHHOLD,
    MISSING_STATED: REPAIR,
    NO_UNEXPLAINED: WITHHOLD,
}


@dataclass
class Check:
    """One of the fourteen, and what it found."""

    key: str
    title: str
    status: str = NOT_APPLICABLE
    mandatory: bool = True
    #: What it found, in a sentence an engineer can act on.
    detail: str = ""
    #: A remedy this check chose for what it actually found, where that is
    #: milder than the default for its key. A check that can distinguish two
    #: failures of different severity should say so: "no invariant applied to
    #: this result" and "the invariant step never ran" are both failures of the
    #: same check, and hiding correct figures for the first would punish the
    #: answer for a gap in the invariant library. It can only LOWER the remedy;
    #: a check cannot escalate past what its key declares.
    asks: str = ""

    @property
    def failed(self) -> bool:
        return self.status == FAIL

    @property
    def remedy(self) -> str:
        if not self.failed:
            return SHOW
        declared = REMEDY.get(self.key, WITHHOLD)
        if self.asks and SEVERITY.get(self.asks, 99) < SEVERITY[declared]:
            return self.asks
        return declared

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "title": self.title, "status": self.status,
                "mandatory": self.mandatory, "detail": self.detail,
                "remedy": self.remedy}


@dataclass
class Gate:
    """Whether this answer can be put in front of a client, and why not."""

    checks: list[Check] = field(default_factory=list)
    #: Set when the gate itself could not run. Distinct from a failing check:
    #: a gate that crashed has not established anything, and treating that as a
    #: pass is how a gate becomes decoration.
    error: str = ""

    def check(self, key: str) -> Check | None:
        return next((c for c in self.checks if c.key == key), None)

    @property
    def failures(self) -> list[Check]:
        return [c for c in self.checks if c.failed]

    @property
    def blocking(self) -> list[Check]:
        return [c for c in self.failures if c.mandatory]

    @property
    def verdict(self) -> str:
        """SHOW, REPAIR, CLARIFY or WITHHOLD — the most severe remedy asked
        for by a failing mandatory check."""
        if self.error:
            return WITHHOLD
        return max((c.remedy for c in self.blocking),
                   key=lambda r: SEVERITY[r], default=SHOW)

    @property
    def presentable(self) -> bool:
        return self.verdict == SHOW

    @property
    def why(self) -> str:
        """One sentence naming what is wrong, for the reader rather than the
        log. Empty when the answer passes."""
        if self.error:
            return ("CreditProbe could not confirm this answer is complete, so "
                    "it is not showing it as one.")
        blocking = self.blocking
        if not blocking:
            return ""
        named = "; ".join(c.detail or c.title.lower() for c in blocking[:3])
        more = len(blocking) - 3
        return named + (f"; and {more} more" if more > 0 else "")

    def sentence(self) -> str:
        """What was checked, for the Trace. Says how many ran, not just how
        many passed — a gate that skipped ten checks and passed four is not a
        gate that passed."""
        ran = [c for c in self.checks if c.status != NOT_APPLICABLE]
        passed = [c for c in ran if c.status == PASS]
        if not ran:
            return "No presentability check applied to this answer."
        return (f"{len(passed)} of {len(ran)} presentability checks passed"
                f" ({len(self.checks) - len(ran)} did not apply).")

    def to_dict(self) -> dict[str, Any]:
        return {"verdict": self.verdict, "presentable": self.presentable,
                "why": self.why, "sentence": self.sentence(),
                "error": self.error,
                "checks": [c.to_dict() for c in self.checks]}


# ---------------------------------------------------------------------------
# Running the gate
# ---------------------------------------------------------------------------


def assess(answered: Any, *, coverage: Any = None, reading: Any = None,
           visual_verdict: Any = None) -> Gate:
    """Whether this answer can be shown.

    `answered` is the orchestrator's Answered. `coverage` is the P0.3 objective
    coverage, `reading` the P0.8 eight sections and `visual_verdict` the P0.11
    visualisation verdict, each passed in when the caller already has it rather
    than recomputed here — a gate that recomputes can disagree with what was
    actually shown.

    Never raises. A gate that throws must not become a 500 on an answer that
    was otherwise fine; it records that it could not run, which WITHHOLDS, and
    the reason reaches the log.
    """
    gate = Gate()
    try:
        gate.checks = _run(answered, coverage, reading, visual_verdict)
    except Exception as e:  # noqa: BLE001 - the gate must not be the failure
        logger.exception("The presentability gate could not run: %s", e)
        gate.error = type(e).__name__
    return gate


def _run(answered: Any, coverage: Any, reading: Any,
         visual: Any) -> list[Check]:
    out: list[Check] = []

    def record(key: str, status: str, detail: str = "", asks: str = "") -> None:
        out.append(Check(key=key, title=TITLES[key], status=status,
                         mandatory=key not in ADVISORY, detail=detail,
                         asks=asks))

    written = getattr(answered, "written", None)
    invariants = getattr(answered, "invariants", None)
    runtime = getattr(answered, "runtime", None)
    build = getattr(answered, "build", None)
    prose = _prose(answered, reading)

    # 1 — every objective addressed. P0.3 already decided this; the gate's job
    # is to refuse to display an answer that P0.3 called unsettled.
    if coverage is None:
        record(OBJECTIVES, NOT_APPLICABLE)
    elif getattr(coverage, "presentable", True):
        record(OBJECTIVES, PASS)
    else:
        unmet = [o.description for o in getattr(coverage, "unsettled", [])][:3]
        record(OBJECTIVES, FAIL,
               "the request asks for " + _and_list(unmet) +
               ", which this answer does not settle")

    # 2 — a direct answer is present. An answer that opens with method, or
    # opens with nothing, has made the reader hunt for the number.
    record(DIRECT_ANSWER, *_direct_answer(answered, reading))

    # 3, 4, 5 — period, population and scope. Each is FAILED only by a
    # positive contradiction, never by absence: an answer with no explicit
    # period is not thereby an answer with the WRONG period.
    record(PERIOD, *_period(answered, prose))
    record(POPULATION, *_population(answered, prose))
    record(SCOPE, *_scope(answered))

    # 6 — no raw decimals. P0.12 governs display formatting; this catches a
    # raw float that reached PROSE, where no formatter runs.
    record(DECIMALS, *_decimals(prose))

    # 7 — no duplicated phrases or entities. Advisory: repetition is ugly and
    # is not a reason to withhold a correct figure from a credit officer.
    record(DUPLICATION, *_duplication(prose, reading))

    # 8 — no unsupported claims. The grounding check already discarded prose
    # carrying a figure the result does not hold; this refuses to call the
    # answer presentable while that prose is still attached.
    record(UNSUPPORTED, *_unsupported(written))

    # 9 — no contradictory figures.
    record(CONTRADICTION, *_contradiction(invariants))

    # 10 — the visualisation says something true about the result.
    record(VISUALISATION, *_visualisation(visual))

    # 11 — the validations are real. "SKIPPED is not PASS", from P0.9, applied
    # to the answer rather than to the agentic Trace: an answer that ran no
    # check must not be described as validated.
    record(VALIDATIONS_REAL, *_validations(invariants, runtime))

    # 12 — the Trace agrees with what executed.
    record(TRACE_AGREES, *_trace_agrees(answered, runtime, build))

    # 13 — missing evidence is stated.
    record(MISSING_STATED, *_missing_stated(answered, runtime, prose))

    # 14 — no unexplained failure. P0.10 categorises; this refuses to show an
    # answer whose failure was never given a category.
    record(NO_UNEXPLAINED, *_no_unexplained(answered))

    return out


# ---------------------------------------------------------------------------
# The individual checks
# ---------------------------------------------------------------------------


def _direct_answer(answered: Any, reading: Any) -> tuple[str, str]:
    if getattr(answered, "clarification", "") or getattr(answered, "failure", ""):
        # A clarification IS the direct answer to a question that cannot be
        # answered as asked.
        return NOT_APPLICABLE, ""
    written = getattr(answered, "written", None)
    headline = str(getattr(written, "headline", "") or "").strip()
    bottom = ""
    if reading is not None:
        from backend.orchestration import sections as sc

        found = reading.section(sc.BOTTOM_LINE)
        bottom = str(getattr(found, "text", "") or "").strip()
    if headline or bottom:
        return PASS, ""
    if getattr(answered, "runtime", None) is None:
        return NOT_APPLICABLE, ""
    return FAIL, "the answer leads with method rather than with the figure"


#: A period as it is written in this product: Q3 2026, 2026-Q3, FY2026.
_PERIOD = re.compile(r"\b(?:Q[1-4]\s*[-/]?\s*(?:20\d{2})|(?:20\d{2})\s*[-/]?\s*Q[1-4]"
                     r"|FY\s?20\d{2})\b", re.I)


def _period(answered: Any, prose: str) -> tuple[str, str]:
    """The prose must not name a period the analysis did not run over."""
    build = getattr(answered, "build", None)
    ran = {_normal_period(p) for p in _periods_of(build)}
    if not ran or not prose:
        return NOT_APPLICABLE, ""
    said = {_normal_period(m.group(0)) for m in _PERIOD.finditer(prose)}
    wrong = sorted(said - ran)
    if not wrong:
        return PASS, ""
    return FAIL, (f"the answer names {wrong[0]}, which is not a period this "
                  f"analysis ran over")


def _periods_of(build: Any) -> list[str]:
    found: list[str] = []
    for name in ("period", "periods", "opening_period", "closing_period",
                 "comparison", "window"):
        value = getattr(build, name, None)
        if isinstance(value, str) and value:
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found.extend(str(v) for v in value if v)
    plan = getattr(build, "plan", None)
    for name in ("period", "periods", "opening", "closing"):
        value = getattr(plan, name, None)
        if isinstance(value, str) and value:
            found.append(value)
        elif isinstance(value, (list, tuple)):
            found.extend(str(v) for v in value if v)
    return found


def _normal_period(text: str) -> str:
    """Q3 2026, 2026-Q3 and Q3-2026 are the same period written three ways."""
    lowered = str(text).lower().replace("-", " ").replace("/", " ")
    quarter = re.search(r"q([1-4])", lowered)
    year = re.search(r"(20\d{2})", lowered)
    if quarter and year:
        return f"q{quarter.group(1)} {year.group(1)}"
    return " ".join(lowered.split())


def _population(answered: Any, prose: str) -> tuple[str, str]:
    """The prose must not describe a population the filters exclude.

    Only a positive contradiction fails: naming a sector that was filtered OUT.
    An answer that does not restate its filters is terse, not wrong.
    """
    build = getattr(answered, "build", None)
    filters = _filters_of(build)
    if not filters or not prose:
        return NOT_APPLICABLE, ""
    lowered = prose.lower()
    for column, kept in filters.items():
        if len(kept) != 1:
            continue
        only = str(next(iter(kept)))
        siblings = _siblings(column, only)
        named = [s for s in siblings if re.search(rf"(?<!\w){re.escape(s.lower())}(?!\w)",
                                                  lowered)]
        if named:
            return FAIL, (f"the analysis covers only {only} and the answer "
                          f"discusses {named[0]}")
    return PASS, ""


def _filters_of(build: Any) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for holder in (build, getattr(build, "plan", None)):
        filters = getattr(holder, "filters", None) or []
        for item in filters:
            column = str(getattr(item, "column", "") or
                         (item.get("column") if isinstance(item, dict) else ""))
            values = getattr(item, "values", None)
            if values is None and isinstance(item, dict):
                values = item.get("values") or ([item.get("value")]
                                                if item.get("value") else [])
            if column and values:
                out.setdefault(column, set()).update(str(v) for v in values)
    return out


def _siblings(column: str, only: str) -> list[str]:
    """Other governed values of the same dimension, so the check names a real
    contradiction rather than any word that happens to appear."""
    known = _KNOWN_VALUES.get(column.lower().rsplit(".", 1)[-1], ())
    return [v for v in known if v.lower() != str(only).lower()]


#: The governed dimension values a contradiction can be stated against. Small
#: and explicit: a check that reaches into the data lake to answer "is this a
#: sector?" is a check that fails when the lake is unavailable, and a gate must
#: not depend on the thing it is guarding.
_KNOWN_VALUES: dict[str, tuple[str, ...]] = {
    "sector": ("Contracting", "Real Estate", "Retail Trade", "Manufacturing",
               "Energy", "Transport", "Healthcare", "Hospitality",
               "Agriculture", "Telecom", "Utilities", "Education"),
    "stage": ("Stage 1", "Stage 2", "Stage 3"),
    "segment": ("Corporate", "Retail", "SME", "Financial Institutions"),
}


def _scope(answered: Any) -> tuple[str, str]:
    """The scope the answer claims must be the scope that was computed."""
    scope = getattr(answered, "scope", None)
    if scope is None:
        return NOT_APPLICABLE, ""
    unresolved = list(getattr(scope, "unresolved", []) or [])
    if unresolved:
        return FAIL, (f"the scope of this answer is unresolved: "
                      f"{_and_list([str(u) for u in unresolved[:2]])}")
    return PASS, ""


#: Three or more decimal places on a number in prose. The display formatter
#: caps at two (P0.12); this catches a float that reached a sentence, where no
#: formatter runs. Guarded against version strings and timestamps.
_RAW_DECIMAL = re.compile(r"(?<![\w.:])(-?\d[\d,]*\.\d{3,})(?![\d.:])")


def _decimals(prose: str) -> tuple[str, str]:
    if not prose:
        return NOT_APPLICABLE, ""
    found = _RAW_DECIMAL.findall(prose)
    if not found:
        return PASS, ""
    return FAIL, f"the answer shows {found[0]} at full float precision"


#: A phrase long enough that repeating it is a bug rather than English.
_PHRASE_WORDS = 6


def _duplication(prose: str, reading: Any) -> tuple[str, str]:
    if not prose:
        return NOT_APPLICABLE, ""
    if reading is not None and getattr(reading, "deduplicated", None):
        names = list(reading.deduplicated)
        return FAIL, f"{names[0]} was named in every section"

    words = re.findall(r"[a-z0-9']+", prose.lower())
    seen: set[tuple[str, ...]] = set()
    for i in range(len(words) - _PHRASE_WORDS + 1):
        window = tuple(words[i:i + _PHRASE_WORDS])
        if window in seen:
            return FAIL, f'the phrase "{" ".join(window)}" appears twice'
        seen.add(window)
    return PASS, ""


def _unsupported(written: Any) -> tuple[str, str]:
    if written is None:
        return NOT_APPLICABLE, ""
    ungrounded = list(getattr(written, "ungrounded", []) or [])
    if not ungrounded:
        return PASS, ""
    return FAIL, (f"the interpretation states {ungrounded[0]}, which the "
                  f"result does not contain")


def _contradiction(invariants: Any) -> tuple[str, str]:
    if invariants is None:
        return NOT_APPLICABLE, ""
    failures = list(getattr(invariants, "failures", []) or [])
    if not failures:
        return PASS, ""
    first = failures[0]
    said = str(getattr(first, "detail", "") or getattr(first, "message", "")
               or first)
    return FAIL, f"a computed figure contradicts what was asked: {said}"


def _visualisation(visual: Any) -> tuple[str, str]:
    if visual is None:
        return NOT_APPLICABLE, ""
    if getattr(visual, "ok", True):
        return PASS, ""
    return FAIL, f"the chart would misrepresent the result — {visual.why}"


def _validations(invariants: Any, runtime: Any) -> tuple[str, ...]:
    """A result must have been checked, and "checked" means checks RAN.

    Two different failures, and they deserve different answers. When the
    invariant step never ran the pipeline did not complete, and the figures
    should not be shown. When it ran and had no applicable rule, the figures
    are fine and only the CLAIM is wrong: an answer presented as validated when
    nothing was verified is the dishonesty P0.9 names, but hiding a correct
    result because the invariant library has no rule for its shape punishes the
    answer for someone else's gap.

    So the second asks for a repair — say "computed" rather than "validated" —
    which is the same shape as P0.9's assurance ceiling: lower the claim, do
    not destroy the answer.
    """
    if runtime is None:
        return NOT_APPLICABLE, ""
    if invariants is None:
        return FAIL, "the invariant step never ran against this result", WITHHOLD
    checks = list(getattr(invariants, "checks", []) or [])
    if not checks:
        return (FAIL,
                "no invariant applied to this result, so it may be described as "
                "computed but not as validated",
                REPAIR)
    return PASS, ""


def _trace_agrees(answered: Any, runtime: Any, build: Any) -> tuple[str, str]:
    """What the Trace says happened must be what happened.

    The narrow, checkable version: an answer that carries a result must carry
    the plan that produced it, and one that carries no result must not carry a
    plan claiming to have run. A Trace describing an execution that did not
    happen is worse than no Trace.
    """
    if runtime is None and build is None:
        return NOT_APPLICABLE, ""
    if runtime is not None and build is None:
        return FAIL, "a result is shown with no plan recorded behind it"
    if runtime is None and getattr(build, "executed", False):
        return FAIL, "the Trace records an execution that produced no result"
    rows = getattr(runtime, "rows", None)
    if runtime is not None and rows is None:
        return FAIL, "the Trace records a result that carries no rows"
    return PASS, ""


def _missing_stated(answered: Any, runtime: Any, prose: str) -> tuple[str, str]:
    """When evidence is missing, the answer has to say so.

    The failure mode is an answer computed over a partial book that reads
    exactly like one computed over a whole one.
    """
    from backend.orchestration import assembly

    # `notable` is the product's own judgement about which warnings a reader
    # has to weigh, and it is deliberate: an as-of join carrying nulls rather
    # than dropping rows is governed behaviour that appears under every joined
    # answer, and repeating it every time trains people to skip the warnings
    # that matter. A second opinion here would demand a caveat the product has
    # already decided not to write, and the gate would be arguing with the
    # answer instead of checking it.
    warnings = assembly.notable(list(getattr(runtime, "warnings", []) or []))
    material = [w for w in warnings if _material(str(w))]
    if not material:
        return PASS if runtime is not None else NOT_APPLICABLE, ""
    written = getattr(answered, "written", None)
    caveats = " ".join(str(c) for c in (getattr(written, "caveats", []) or []))
    stated = f"{prose}\n{caveats}".lower()
    unstated = [w for w in material
                if not _mentions_limitation(stated, str(w))]
    if not unstated:
        return PASS, ""
    return FAIL, (f"the result is limited ({unstated[0]}) and the answer does "
                  f"not say so")


#: Warnings that change what can be concluded, as opposed to housekeeping.
_MATERIAL = re.compile(
    r"missing|incomplete|partial|stale|as[- ]of|not available|excluded|"
    r"truncat|capped|no data|unmatched|unjoined|dropped", re.I)


def _material(warning: str) -> bool:
    return bool(_MATERIAL.search(warning))


def _mentions_limitation(stated: str, warning: str) -> bool:
    """Whether the answer already tells the reader about this limitation.

    Word overlap rather than exact text: the answer restates a warning in its
    own words, and requiring the warning verbatim would fail every honest
    answer.
    """
    words = {w for w in re.findall(r"[a-z]{5,}", warning.lower())}
    if not words:
        return True
    hit = sum(1 for w in words if w in stated)
    return hit >= max(1, len(words) // 3)


def _no_unexplained(answered: Any) -> tuple[str, str]:
    """A failure has to have a category. P0.10 provides ten; an answer that
    failed without one is the anonymous 500 wearing a different coat."""
    failure = str(getattr(answered, "failure", "") or "")
    if not failure:
        return PASS if getattr(answered, "answered", False) else NOT_APPLICABLE, ""
    kind = str(getattr(answered, "failure_kind", "") or "")
    if not kind:
        return FAIL, "the answer failed and the failure was never categorised"
    return PASS, ""


# ---------------------------------------------------------------------------
# Shared reading
# ---------------------------------------------------------------------------


def _prose(answered: Any, reading: Any) -> str:
    """Every sentence this answer would show, as one string.

    Both the live interpretation and the eight sections, because a defect in
    either reaches the reader and the checks above are about what reaches the
    reader.
    """
    parts: list[str] = []
    written = getattr(answered, "written", None)
    if written is not None:
        parts.append(str(getattr(written, "headline", "") or ""))
        parts.append(str(getattr(written, "interpretation", "") or ""))
        parts.extend(str(n) for n in (getattr(written, "notable", []) or []))
    if reading is not None:
        try:
            parts.append(reading.prose())
        except Exception:  # noqa: BLE001
            pass
    result = getattr(answered, "result", None)
    if result is not None:
        parts.append(str(getattr(result, "narrative", "") or ""))
    return "\n".join(p for p in parts if p).strip()


def _and_list(values: list[str]) -> str:
    items = [str(v).strip() for v in values if str(v).strip()]
    if not items:
        return "something it does not name"
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + f" and {items[-1]}"


__all__ = [
    "ADVISORY",
    "CHECKS",
    "CLARIFY",
    "FAIL",
    "NOT_APPLICABLE",
    "PASS",
    "REMEDY",
    "REPAIR",
    "SHOW",
    "TITLES",
    "WITHHOLD",
    "Check",
    "Gate",
    "assess",
]
