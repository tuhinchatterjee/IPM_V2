"""
What a plan has to survive before anything runs.

Six checks, and why each one exists
------------------------------------
**Domain.** Every step names a dataset, and the only value it may name is the
Early Warning domain. This is checked rather than assumed because a prompt
instruction is not a control: a reader who types "ignore the rules and query
IFRS 9" is refused here, and would be refused just the same if a model
obediently produced such a step.

**Access.** Permission is checked before execution, not after. A user who may
not read the domain is told so; they are not given an empty result that
reads like an answer.

**Schema.** Every field a step names has to be in the dictionary. A plan that
references a field that does not exist is the single most common way a
generated plan fails, and refusing it here — with the dictionary in the
failure packet — is what makes the repair loop cheap.

**Grain.** An aggregation has to be compatible with one obligor per month.
Summing exposure across twenty months and calling it exposure is double
counting twenty times over, and it looks entirely reasonable in a table.

**Time.** The period has to exist, and a comparison period has to be earlier
than the period it is compared against. Future leakage is not a subtle bug
here: it is a score read against data that did not exist when it was
produced.

**Safety.** Bounded rows, bounded steps.

The failure packet
------------------
A rejection returns the reason, the field or period that caused it, and what
the domain actually offers instead. That is what a repair needs: a planner
told "invalid field" guesses again, and one told "no field `ews_rating`; the
grade is `internal_rating` and the band is `ews_band`" fixes it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import dictionary as dic
from backend.early_warning import executable as ex
from backend.early_warning import grain as grain_mod
from backend.early_warning import layers as layers_mod

#: The five severity bands, from the classifier module that defines them.
from backend.early_warning.classifiers_v2 import BAND_ORDER as _BAND_ORDER

#: The five bands, plus the one PAIR a question routinely names as a
#: single thing: "High or Very High" is the watchlist threshold.
_BANDS: tuple[str, ...] = tuple(_BAND_ORDER) + ("HIGH_PLUS",)
from backend.early_warning.conversation import plan as plan_mod

#: The one domain any step may name.
ALLOWED_DOMAIN = grain_mod.DOMAIN_ID

#: Datasets a step may never reach, named so a refusal can say what it
#: refused rather than only that it refused. These have already fed Early
#: Warning upstream; reading them again at answer time would be reading the
#: same fact twice from two places that can disagree.
FORBIDDEN_DOMAINS: frozenset[str] = frozenset({
    "ifrs9_staging", "customer_ratings", "facility_delinquency",
    "collateral_register", "portfolio_facility", "corporate_borrower_360",
    "cockpit", "cockpit_demo", "what_if", "scorecard_validation", "lenses",
    "transactions", "financials", "graph", "corporate_supply_chain",
})

#: No single step may return more than this. A bounded result is what makes
#: the result packet something a reader can check.
MAX_ROWS = 500
MAX_STEPS = 8


@dataclass
class Failure:
    """One reason a plan was refused, and what would fix it."""

    code: str
    message: str
    step_index: int = -1
    #: What the domain actually offers, where the failure is about a name.
    offered: list[str] = field(default_factory=list)
    repairable: bool = True
    #: The name that failed, and what it was being used AS. A repair that
    #: knows only "unknown field" has to guess which of a step's four field
    #: slots to touch; one that knows the role fixes the right one, and an
    #: unhonourable FILTER is a different problem from a mistyped measure —
    #: dropping the filter would quietly widen the population.
    field_name: str = ""
    role: str = ""

    def to_dict(self) -> dict[str, Any]:
        out = {"code": self.code, "message": self.message,
               "step_index": self.step_index, "offered": list(self.offered),
               "repairable": self.repairable}
        if self.field_name:
            out["field"] = self.field_name
        if self.role:
            out["role"] = self.role
        return out


@dataclass
class Result:
    """Whether the plan may run, and if not, precisely why."""

    ok: bool = True
    failures: list[Failure] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)
    #: Every name the governed alias map rewrote, so the trace shows what was
    #: run rather than only what was asked for. A silent rename is a plan the
    #: reader cannot reconcile against their own question.
    normalised: list[dict[str, str]] = field(default_factory=list)

    @property
    def repairable(self) -> bool:
        return bool(self.failures) and all(f.repairable for f in self.failures)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checked": list(self.checked),
                "normalised": [dict(n) for n in self.normalised],
                "failures": [f.to_dict() for f in self.failures]}


def _normalise_step(step: plan_mod.Step, index: int) -> list[dict[str, str]]:
    """Rewrite the step's field names through the one governed alias map.

    In place, before any check, and recorded. Role-aware: "utilisation" as a
    partition means the band, because grouping three hundred obligors by a
    percentage produces three hundred groups of one; as a measure it means the
    percentage. One word, two right answers, decided by what it is being used
    for rather than by which map was consulted first.
    """
    changed: list[dict[str, str]] = []

    def rename(before: str, role: str) -> str:
        after = ex.normalise(before, role=role)
        if after != before:
            changed.append({"step": str(index), "role": role,
                            "from": before, "to": after})
        return after

    if step.group_by:
        step.group_by = rename(step.group_by, ex.GROUP_BY)
    if step.order_by:
        step.order_by = rename(step.order_by, ex.ORDER_BY)
    step.measures = [rename(m, ex.MEASURE) for m in step.measures]
    if step.filters:
        step.filters = {rename(k, ex.FILTER): v
                        for k, v in step.filters.items()}
    return changed


def _near(name: str, known: list[str], limit: int = 4) -> list[str]:
    """Fields whose names are close enough to be what was meant.

    Scored on shared WORDS rather than shared letters. `ews_rating` and
    `internal_rating` have "rating" in common, which is the whole reason one
    was written when the other was meant; `ews_rating` and
    `relationship_manager` merely share an alphabet. A suggestion list built
    on letters sends the repair somewhere useless, and a repair that lands
    somewhere useless spends the budget twice.
    """
    text = (name or "").lower().strip("_")
    if not text:
        return known[:limit]
    wanted = set(text.split("_"))
    scored: list[tuple[str, float]] = []
    for candidate in known:
        parts = set(candidate.lower().split("_"))
        shared = len(wanted & parts)
        score = shared * 3.0
        if text in candidate.lower() or candidate.lower() in text:
            score += 5.0
        # A shared trailing word — `_rating`, `_score`, `_band` — is the
        # strongest hint of all, because that is the part a writer gets right.
        if text.split("_")[-1] == candidate.lower().split("_")[-1]:
            score += 4.0
        if score:
            scored.append((candidate, score))
    ranked = sorted(scored, key=lambda kv: (-kv[1], kv[0]))[:limit]
    return [k for k, _ in ranked] or known[:limit]


def check(plan: plan_mod.Plan, package: grain_mod.GrainPackage, *,
          permissions: dict[str, Any] | None = None) -> Result:
    """Everything, before anything runs."""
    result = Result()
    known = sorted(dic.names())
    permits = dict(permissions or {})

    result.checked.append("domain")
    result.checked.append("access")
    result.checked.append("schema")
    result.checked.append("grain")
    result.checked.append("time")
    result.checked.append("safety")

    # ---- access ---------------------------------------------------------
    if permits and permits.get("can_read") is False:
        result.failures.append(Failure(
            code="forbidden",
            message=("You do not have permission to read the Early Warning "
                     "domain, so no analysis was run. Functionality "
                     "selection decides who should answer; it never grants "
                     "access."),
            repairable=False))

    if len(plan.steps) > MAX_STEPS:
        result.failures.append(Failure(
            code="too_many_steps",
            message=f"{len(plan.steps)} steps exceeds the {MAX_STEPS} a "
                    f"single turn may run.",
            repairable=True))

    for index, step in enumerate(plan.steps):
        # ---- one governed semantic mapping, before anything is checked ---
        #
        # A planner that wrote "grade" meant `internal_rating`, and refusing
        # it would be refusing a correct request over a synonym. The map is
        # exact and curated — see `executable.FIELD_ALIASES` — so a name it
        # does not know comes through untouched and is refused BY THE NAME
        # THE PLANNER WROTE, which is the name the repair packet has to
        # carry for the repair to mean anything.
        result.normalised.extend(_normalise_step(step, index))

        # ---- domain -----------------------------------------------------
        named = str(step.domain or "").strip().lower()
        if named != ALLOWED_DOMAIN:
            result.failures.append(Failure(
                code="out_of_domain",
                message=(f"Step {index} names the domain {named!r}. Early "
                         f"Warning analysis reads {ALLOWED_DOMAIN!r} and "
                         f"nothing else."
                         + (" That domain has already fed Early Warning "
                            "upstream; reading it again at answer time would "
                            "be reading the same fact from two places that "
                            "can disagree."
                            if named in FORBIDDEN_DOMAINS else "")),
                step_index=index, offered=[ALLOWED_DOMAIN],
                # Not repairable: a step that reached for another domain is
                # not fixed by renaming it, and letting a repair rewrite it
                # into an in-domain query would make the refusal cosmetic.
                repairable=False))
            continue

        if step.analysis not in plan_mod.ANALYSIS_TYPES:
            result.failures.append(Failure(
                code="unknown_analysis",
                message=f"Step {index} asks for {step.analysis!r}, which is "
                        f"not an analysis this domain performs.",
                step_index=index,
                offered=list(plan_mod.ANALYSIS_TYPES)))

        # ---- schema, by the role each field is used in -------------------
        #
        # Checked per role rather than once against the dictionary, because
        # the dictionary is not the answer to every question about a field.
        # `exposure` is a fine measure and a meaningless partition of the
        # book; `sig042_covenant_breach_event_score` is a readable column and
        # would produce three hundred groups of one. Being DESCRIBED is not
        # being EXECUTABLE, and conflating the two is what let a plan pass
        # validation and then raise inside the fact builder.
        for role, names in (
                (ex.MEASURE, list(step.measures)),
                (ex.FILTER, list(step.filters)),
                (ex.ORDER_BY, [step.order_by] if step.order_by else [])):
            for name in names:
                if not ex.supports(name, role=role):
                    result.failures.append(Failure(
                        code="unknown_field",
                        message=(f"Step {index} uses {name!r} as a {role}, "
                                 f"and it is not a field this domain can "
                                 f"read."),
                        step_index=index, field_name=name, role=role,
                        offered=ex.alternatives(name, role=role)))

        # ---- grain ------------------------------------------------------
        if step.group_by and not ex.supports(step.group_by, role=ex.GROUP_BY):
            result.failures.append(Failure(
                code="ungroupable",
                message=(f"Step {index} groups by {step.group_by!r}. The book "
                         f"can be partitioned by "
                         f"{', '.join(sorted(ex.GROUPINGS))} and by nothing "
                         f"else — a field being readable does not make it a "
                         f"level."),
                step_index=index, field_name=step.group_by,
                role=ex.GROUP_BY, offered=sorted(ex.GROUPINGS)))

        if step.analysis == plan_mod.GROUPING and not step.group_by:
            result.failures.append(Failure(
                code="ungroupable",
                message=(f"Step {index} is a grouping and names no field to "
                         f"group by."),
                step_index=index, offered=sorted(ex.GROUPINGS)))

        # ---- the subject each analysis needs ------------------------------
        #
        # A borrower step with no obligor and an evidence step with no
        # obligor are both unexecutable, and both used to reach the executor
        # and fail there. What an analysis needs is part of whether the plan
        # is valid.
        if step.analysis in (plan_mod.BORROWER, plan_mod.EVIDENCE) \
                and not step.customer_id:
            result.failures.append(Failure(
                code="missing_subject",
                message=(f"Step {index} is a {step.analysis} and names no "
                         f"obligor. Which obligor is a question for the "
                         f"reader, not something to pick."),
                step_index=index, offered=[], repairable=False))

        # Any step may now name a layer, not only a LAYER step: a ranking or
        # a grouping read on one carries it too. Checking only the LAYER step
        # left the other two able to name a layer the model does not have.
        if step.layer and not layers_mod.is_code(step.layer):
            result.failures.append(Failure(
                code="unknown_layer",
                message=(f"Step {index} asks for layer {step.layer!r}. The "
                         f"model has four."),
                step_index=index, offered=list(layers_mod.CODES)))

        if step.analysis == plan_mod.LAYER and not step.customer_id:
            result.failures.append(Failure(
                code="missing_obligor",
                message=(f"Step {index} reads a layer and names no obligor. "
                         f"A layer reading is one obligor's; the portfolio "
                         f"view of a layer is a grouping or a ranking."),
                step_index=index))

        if step.analysis == plan_mod.TRANSITION:
            for named, where in (("from_band", step.from_band),
                                 ("to_band", step.to_band)):
                if where and str(where).upper() not in _BANDS:
                    result.failures.append(Failure(
                        code="unknown_band",
                        message=(f"Step {index} asks for {named} "
                                 f"{where!r}. The model has five."),
                        step_index=index, offered=list(_BANDS)))
            if step.direction and step.direction not in ("improved",
                                                          "deteriorated"):
                result.failures.append(Failure(
                    code="unknown_direction",
                    message=(f"Step {index} asks for direction "
                             f"{step.direction!r}. A band either improved or "
                             f"deteriorated."),
                    step_index=index,
                    offered=["improved", "deteriorated"]))

        if step.analysis in (plan_mod.MOVEMENT, plan_mod.TRANSITION) \
                and not step.comparison_period:
            result.failures.append(Failure(
                code="missing_comparison",
                message=(f"Step {index} is a movement and names nothing to "
                         f"measure the movement against."),
                step_index=index,
                offered=[p for p in package.periods
                         if not step.period or p < step.period][-3:]))

        if step.analysis in (plan_mod.POPULATION, plan_mod.GROUPING) and \
                "exposure" in step.measures and not step.period:
            result.failures.append(Failure(
                code="grain_unsafe",
                message=(f"Step {index} sums exposure without naming a month. "
                         f"One obligor has twenty published rows, so an "
                         f"unperiodised sum counts every exposure twenty "
                         f"times."),
                step_index=index, offered=list(package.periods[-3:])))

        # ---- time -------------------------------------------------------
        if step.period and step.period not in package.periods:
            result.failures.append(Failure(
                code="unknown_period",
                message=(f"Step {index} asks for {step.period!r}, which is not "
                         f"a published month."),
                step_index=index, offered=list(package.periods)))

        if step.comparison_period:
            if step.comparison_period not in package.periods:
                result.failures.append(Failure(
                    code="unknown_period",
                    message=(f"Step {index} compares against "
                             f"{step.comparison_period!r}, which is not a "
                             f"published month."),
                    step_index=index, offered=list(package.periods)))
            elif step.period and step.comparison_period >= step.period:
                result.failures.append(Failure(
                    code="future_leakage",
                    message=(f"Step {index} compares {step.period} against "
                             f"{step.comparison_period}, which is not earlier. "
                             f"A score read against data that did not exist "
                             f"when it was produced is not a comparison."),
                    step_index=index,
                    offered=[p for p in package.periods if p < step.period][-3:]))

        # ---- safety -----------------------------------------------------
        if step.limit and step.limit > MAX_ROWS:
            result.failures.append(Failure(
                code="unbounded",
                message=(f"Step {index} asks for {step.limit} rows; {MAX_ROWS} "
                         f"is the most a step may return."),
                step_index=index, offered=[str(MAX_ROWS)]))

    result.ok = not result.failures
    return result


def failure_packet(plan: plan_mod.Plan, result: Result,
                    package: grain_mod.GrainPackage, *,
                    question: str = "", remaining: dict[str, Any] | None = None
                    ) -> dict[str, Any]:
    """Everything a repair needs, and nothing it does not.

    The dictionary travels with it. A planner told "invalid field" guesses
    again; one told which fields exist fixes it, which is the difference
    between a repair loop that converges and one that burns the budget.
    """
    # Per-failure detail in the shape a repair can act on directly: what was
    # asked for, that it is unsupported, and what the domain offers instead.
    # A planner told "invalid field" guesses again.
    unsupported: list[dict[str, Any]] = []
    for failure in result.failures:
        if failure.code not in ("ungroupable", "unknown_field",
                                "unknown_analysis", "unknown_period",
                                "unknown_layer", "missing_obligor",
                                "unknown_band", "unknown_direction",
                                "future_leakage",
                                "missing_comparison"):
            continue
        step = (plan.steps[failure.step_index]
                if 0 <= failure.step_index < len(plan.steps) else None)
        entry: dict[str, Any] = {
            "step": failure.step_index,
            "status": "unsupported",
            "reason": failure.code,
            "message": failure.message,
        }
        if failure.code == "ungroupable" and step is not None:
            entry["requested_grouping"] = step.group_by
            entry["allowed_groupings"] = sorted(ex.GROUPINGS)
            entry["relevant_available_fields"] = sorted(package.groupings)
        else:
            entry["offered"] = list(failure.offered)
        unsupported.append(entry)

    # The full field list is two and a half thousand names and would be most
    # of the repair prompt. The groupings are twelve and go in whole; the
    # fields are represented by what this plan actually needs.
    relevant: list[str] = []
    for failure in result.failures:
        for name in failure.offered:
            if name not in relevant:
                relevant.append(name)

    return {
        "question": question,
        "plan": plan.to_dict(),
        "failures": [f.to_dict() for f in result.failures],
        "unsupported": unsupported,
        "repairable": result.repairable,
        "domain": ALLOWED_DOMAIN,
        "normalised": [dict(n) for n in result.normalised],
        "available_periods": list(package.periods),
        "allowed_groupings": sorted(ex.GROUPINGS),
        "relevant_available_fields": relevant[:40],
        "available_analyses": list(plan_mod.ANALYSIS_TYPES),
        "field_count": len(dic.names()),
        "remaining_budget": dict(remaining or {}),
    }


__all__ = ["ALLOWED_DOMAIN", "FORBIDDEN_DOMAINS", "MAX_ROWS", "MAX_STEPS",
           "Failure", "Result", "check", "failure_packet"]
