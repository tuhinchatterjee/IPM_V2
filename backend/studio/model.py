"""
Analysis Studio — the credit-risk method library.

What belongs here, and what does not
------------------------------------
The Analytical Runtime can perform sixty-odd generic operations: join, group,
window, rank, pivot. Those are technical primitives and they do not belong in a
library a credit officer browses — nobody opens a product looking for LEFT JOIN.

What belongs here is the other thing: named methodologies whose BUSINESS
definition matters and is worth arguing about. "One-Year Forward Observed
Default Rate" is not an operation, it is a decision — facility level or customer
level, default at the horizon or at any point before it, what to do with an
account that closed in month seven. Two banks compute it differently and both
are right, and the difference is worth writing down.

So the Studio is a library of definitions, and the Runtime is what executes them.

Certification is earned, not asserted
-------------------------------------
A method carries a lifecycle, and the double blue tick is the last state of it.
It requires an explicit methodology, a runnable implementation, test cases with
expected results, and every one of those tests passing. A definition somebody
typed is PRECONFIGURED and says so.

Marking three hundred entries "certified" because there are three hundred of
them would make the tick worthless, which would make the honest ones worthless
too. So the library is large and its certified subset is small, and the
interface never shows one as the other.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any


class Lifecycle(StrEnum):
    """How far a method has got, and therefore what it may claim.

    Deliberately linear. Something can move back to DRAFT — editing a certified
    method creates a new draft version and leaves the certified one standing —
    but it cannot skip a state, because each one is evidence the next depends on.
    """

    DRAFT = "draft"              # a definition, possibly incomplete
    BUILT = "built"              # has a runnable plan
    TESTED = "tested"            # has test cases, which have been run
    VALIDATED = "validated"      # every test passed
    CERTIFIED = "certified"      # validated AND signed off by a governance role

    #: Not a stage — a state a definition sits in when nobody has built it yet.
    PRECONFIGURED = "preconfigured"
    #: Shipped as an illustration of what could be built. Never runs.
    PREVIEW = "preview"
    #: The bank's own, forked from something or written from scratch.
    CUSTOM = "custom"
    DEPRECATED = "deprecated"


#: What each state is allowed to say about itself in the interface. The mapping
#: exists so a label is never composed at the call site, where it could drift.
LIFECYCLE_LABEL: dict[str, str] = {
    Lifecycle.DRAFT: "Draft",
    Lifecycle.BUILT: "Built · not yet tested",
    Lifecycle.TESTED: "Tested",
    Lifecycle.VALIDATED: "Validated",
    Lifecycle.CERTIFIED: "CreditProbe Certified",
    Lifecycle.PRECONFIGURED: "Preconfigured · review required",
    Lifecycle.PREVIEW: "Preview · definition only",
    Lifecycle.CUSTOM: "Custom · this bank's own",
    Lifecycle.DEPRECATED: "Deprecated",
}

#: The only states that earn the double blue tick.
CERTIFIED_STATES = frozenset({Lifecycle.CERTIFIED})

#: States whose methods can actually be executed.
RUNNABLE_STATES = frozenset({
    Lifecycle.BUILT, Lifecycle.TESTED, Lifecycle.VALIDATED,
    Lifecycle.CERTIFIED, Lifecycle.CUSTOM,
})


class Category(StrEnum):
    """How a credit officer looks for a method.

    Grouped by the question being asked, not by the mathematics — somebody
    hunting for a cure rate is thinking about recoveries, not about ratios.
    """

    PORTFOLIO_QUALITY = "Portfolio Quality"
    DEFAULT_DELINQUENCY = "Default & Delinquency"
    RATINGS = "Ratings"
    IFRS9 = "IFRS 9 / Impairment"
    MIGRATION = "Migration"
    CONCENTRATION = "Concentration"
    WATCHLIST = "Watchlist"
    EARLY_WARNING = "Early Warning"
    COLLATERAL = "Collateral"
    COVENANTS = "Covenants"
    EXPOSURE = "Exposure / Utilisation"
    VINTAGE = "Vintage / Cohort"
    RECOVERY = "Recovery / Cure"
    RISK_APPETITE = "Risk Appetite"
    STRESS = "Stress / Scenario"
    RETURN = "Return / Profitability"
    LIMITS = "Limits / Large Exposure"
    CUSTOM = "Custom Bank Methods"


@dataclass
class TestCase:
    """One transparent case, with the answer worked out in advance.

    The expected value is set by a person and stored, never computed by running
    the method — a test whose expectation comes from the thing under test
    asserts only that the code is deterministic.
    """

    id: str
    name: str
    #: Why this case exists. "A facility that cures and re-defaults" is the
    #: whole point of the row; without it a reviewer sees only numbers.
    purpose: str
    #: The rows, as plain dicts. Small enough to read on one screen.
    data: list[dict[str, Any]] = field(default_factory=list)
    expected: dict[str, Any] = field(default_factory=dict)
    #: Filled in by a run. Never stored as the expectation.
    actual: dict[str, Any] = field(default_factory=dict)
    passed: bool | None = None
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "purpose": self.purpose,
            "data": self.data, "expected": self.expected, "actual": self.actual,
            "passed": self.passed, "note": self.note,
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> TestCase:
        return TestCase(
            id=str(raw.get("id") or ""), name=str(raw.get("name") or ""),
            purpose=str(raw.get("purpose") or ""),
            data=list(raw.get("data") or []),
            expected=dict(raw.get("expected") or {}),
            actual=dict(raw.get("actual") or {}),
            passed=raw.get("passed"), note=str(raw.get("note") or ""),
        )


@dataclass
class MethodVersion:
    """One version of a method, and what changed to make it one."""

    version: str
    lifecycle: str = Lifecycle.DRAFT
    created_at: str = ""
    created_by: str = ""
    change_note: str = ""
    plan: dict[str, Any] | None = None
    certified_at: str = ""
    certified_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version, "lifecycle": self.lifecycle,
            "lifecycle_label": LIFECYCLE_LABEL.get(self.lifecycle, self.lifecycle),
            "created_at": self.created_at, "created_by": self.created_by,
            "change_note": self.change_note,
            "certified_at": self.certified_at, "certified_by": self.certified_by,
        }


@dataclass
class MethodDefinition:
    """One named credit-risk methodology.

    Most of these fields are metadata rather than mechanism, and that is
    deliberate: `when_not_to_use` and `limitations` are what stop a method being
    applied to a question it cannot answer, and they are the fields the planner
    reads when deciding whether to reach for it. A method with a perfect
    implementation and no applicability notes is a method that will be misused.
    """

    id: str
    name: str
    category: str
    #: What it measures, in one sentence a credit officer would recognise.
    definition: str = ""
    #: The business purpose. Why a bank computes this at all.
    purpose: str = ""
    #: The methodology in prose — the part two banks would argue about.
    methodology: str = ""

    lifecycle: str = Lifecycle.PRECONFIGURED
    version: str = "1.0.0"

    #: Other names for the same thing. Ask CreditProbe routes on these, so
    #: "ODR", "observed default rate" and "1Y ODR" all reach one method.
    aliases: list[str] = field(default_factory=list)

    # ---- applicability: what the planner reads to decide -------------------
    when_to_use: str = ""
    when_not_to_use: str = ""
    required_grain: str = ""
    required_history: str = ""
    required_domains: list[str] = field(default_factory=list)
    required_fields: list[str] = field(default_factory=list)
    applicable_segments: list[str] = field(default_factory=list)
    weighting_options: list[str] = field(default_factory=list)
    output_type: str = ""
    interpretation: str = ""
    limitations: str = ""

    # ---- implementation ----------------------------------------------------
    #: The Analytical IR that computes it. None for a definition nobody built.
    plan: dict[str, Any] | None = None
    #: A certified engine analysis, where one already implements this method.
    engine_analysis: str = ""

    test_cases: list[TestCase] = field(default_factory=list)
    versions: list[MethodVersion] = field(default_factory=list)

    owner: str = "Credit Risk Analytics"
    created_at: str = ""
    updated_at: str = ""
    certified_at: str = ""
    certified_by: str = ""
    #: Set when this was forked, so the lineage of a bank's variant is visible.
    forked_from: str = ""
    source: str = "creditprobe"   # creditprobe | bank

    # ---- derived -----------------------------------------------------------

    @property
    def is_certified(self) -> bool:
        return self.lifecycle in CERTIFIED_STATES

    @property
    def is_runnable(self) -> bool:
        return (self.lifecycle in RUNNABLE_STATES
                and bool(self.plan or self.engine_analysis))

    @property
    def lifecycle_label(self) -> str:
        return LIFECYCLE_LABEL.get(self.lifecycle, self.lifecycle)

    @property
    def tests_passing(self) -> int:
        return sum(1 for t in self.test_cases if t.passed is True)

    @property
    def tests_failing(self) -> int:
        return sum(1 for t in self.test_cases if t.passed is False)

    def fingerprint(self) -> str:
        """A hash of what this method COMPUTES, ignoring prose.

        Two methods with the same plan and the same required fields produce the
        same number whatever they are called, and this is how the Studio spots
        that somebody has re-created an existing method under a new name.
        """
        payload = json.dumps(
            {"plan": self.plan, "engine": self.engine_analysis,
             "fields": sorted(self.required_fields)},
            sort_keys=True, separators=(",", ":"), default=str,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:16]

    def search_text(self) -> str:
        """Everything a search should match, lower-cased."""
        return " ".join([
            self.id, self.name, self.category, self.definition, self.purpose,
            *self.aliases,
        ]).lower()

    # ---- lifecycle transitions --------------------------------------------

    def can_certify(self) -> tuple[bool, list[str]]:
        """Whether this method has earned the tick, and what is missing.

        Every reason, not the first — somebody preparing a method for sign-off
        needs the whole list.
        """
        missing: list[str] = []
        if not self.methodology.strip():
            missing.append("a written methodology")
        if not (self.plan or self.engine_analysis):
            missing.append("a runnable implementation")
        if not self.required_fields:
            missing.append("the governed fields it needs")
        if not self.test_cases:
            missing.append("test cases")
        elif self.tests_failing:
            missing.append(f"{self.tests_failing} failing test case(s) to be fixed")
        elif any(t.passed is None for t in self.test_cases):
            missing.append("the test cases to have been run")
        if not self.limitations.strip():
            missing.append("a statement of what it does NOT tell you")
        return (not missing, missing)

    def bump(self, *, change_note: str, by: str = "",
             lifecycle: str = Lifecycle.DRAFT) -> MethodVersion:
        """Record the current state as a version and start a new one.

        Called when a certified method is edited. The certified version stays in
        the history exactly as it was signed off — that is the whole reason for
        keeping versions rather than a modified-at timestamp.
        """
        self.versions.append(MethodVersion(
            version=self.version, lifecycle=self.lifecycle,
            created_at=self.updated_at or self.created_at,
            change_note=change_note, plan=self.plan,
            certified_at=self.certified_at, certified_by=self.certified_by,
        ))
        major, minor, patch = (self.version.split(".") + ["0", "0"])[:3]
        self.version = f"{major}.{int(minor) + 1}.0"
        self.lifecycle = lifecycle
        self.certified_at = ""
        self.certified_by = ""
        self.updated_at = datetime.now(UTC).isoformat()
        return self.versions[-1]

    # ---- serialisation -----------------------------------------------------

    def to_dict(self, *, full: bool = True) -> dict[str, Any]:
        brief = {
            "id": self.id, "name": self.name, "category": self.category,
            "definition": self.definition,
            "lifecycle": self.lifecycle, "lifecycle_label": self.lifecycle_label,
            "is_certified": self.is_certified, "is_runnable": self.is_runnable,
            "version": self.version, "aliases": list(self.aliases),
            "owner": self.owner, "source": self.source,
            "test_count": len(self.test_cases),
            "tests_passing": self.tests_passing,
            "tests_failing": self.tests_failing,
        }
        if not full:
            return brief
        return {
            **brief,
            "purpose": self.purpose, "methodology": self.methodology,
            "when_to_use": self.when_to_use, "when_not_to_use": self.when_not_to_use,
            "required_grain": self.required_grain,
            "required_history": self.required_history,
            "required_domains": list(self.required_domains),
            "required_fields": list(self.required_fields),
            "applicable_segments": list(self.applicable_segments),
            "weighting_options": list(self.weighting_options),
            "output_type": self.output_type,
            "interpretation": self.interpretation,
            "limitations": self.limitations,
            "plan": self.plan,
            "engine_analysis": self.engine_analysis,
            "test_cases": [t.to_dict() for t in self.test_cases],
            "versions": [v.to_dict() for v in self.versions],
            "created_at": self.created_at, "updated_at": self.updated_at,
            "certified_at": self.certified_at, "certified_by": self.certified_by,
            "forked_from": self.forked_from,
            "fingerprint": self.fingerprint(),
            "can_certify": self.can_certify()[0],
            "certification_gaps": self.can_certify()[1],
        }

    @staticmethod
    def from_dict(raw: dict[str, Any]) -> MethodDefinition:
        return MethodDefinition(
            id=str(raw["id"]), name=str(raw.get("name") or raw["id"]),
            category=str(raw.get("category") or Category.CUSTOM),
            definition=str(raw.get("definition") or ""),
            purpose=str(raw.get("purpose") or ""),
            methodology=str(raw.get("methodology") or ""),
            lifecycle=str(raw.get("lifecycle") or Lifecycle.PRECONFIGURED),
            version=str(raw.get("version") or "1.0.0"),
            aliases=list(raw.get("aliases") or []),
            when_to_use=str(raw.get("when_to_use") or ""),
            when_not_to_use=str(raw.get("when_not_to_use") or ""),
            required_grain=str(raw.get("required_grain") or ""),
            required_history=str(raw.get("required_history") or ""),
            required_domains=list(raw.get("required_domains") or []),
            required_fields=list(raw.get("required_fields") or []),
            applicable_segments=list(raw.get("applicable_segments") or []),
            weighting_options=list(raw.get("weighting_options") or []),
            output_type=str(raw.get("output_type") or ""),
            interpretation=str(raw.get("interpretation") or ""),
            limitations=str(raw.get("limitations") or ""),
            plan=raw.get("plan"),
            engine_analysis=str(raw.get("engine_analysis") or ""),
            test_cases=[TestCase.from_dict(t) for t in (raw.get("test_cases") or [])],
            versions=[MethodVersion(**v) if isinstance(v, dict) else v
                      for v in (raw.get("versions") or [])],
            owner=str(raw.get("owner") or "Credit Risk Analytics"),
            created_at=str(raw.get("created_at") or ""),
            updated_at=str(raw.get("updated_at") or ""),
            certified_at=str(raw.get("certified_at") or ""),
            certified_by=str(raw.get("certified_by") or ""),
            forked_from=str(raw.get("forked_from") or ""),
            source=str(raw.get("source") or "creditprobe"),
        )


__all__ = [
    "CERTIFIED_STATES",
    "LIFECYCLE_LABEL",
    "RUNNABLE_STATES",
    "Category",
    "Lifecycle",
    "MethodDefinition",
    "MethodVersion",
    "TestCase",
]
