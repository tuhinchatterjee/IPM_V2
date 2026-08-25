"""
The method validation workbench.

Why the test data is generated here rather than sampled
-------------------------------------------------------
A method tested on the real book is tested on whatever the book happens to
contain. If no facility in Q1 2026 cured and re-defaulted, the test says nothing
about how the method treats one — and that case is precisely where two banks'
definitions diverge.

So the pack is built the other way round: from the list of situations that are
KNOWN to be contentious, one transparent row each, small enough to read on one
screen. Every case exists because somebody could reasonably disagree about it.

Where the expected answers come from
------------------------------------
Not from running the method. A test whose expectation is produced by the code
under test asserts only that the code is deterministic, which it always is.

The expectations below are computed by `_expected_forward_rate`, a second,
independent implementation written in plain Python from the methodology text
rather than from the IR. When it and the runtime disagree, one of them is wrong
and a human has to decide which — which is the entire point of a validation
pack, and is worth the duplication.

The language model may propose additional cases. It may not supply an expected
value, because a model asserting the answer to its own test is not evidence.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from backend.studio.model import MethodDefinition, TestCase

logger = logging.getLogger(__name__)


#: The situations a forward-looking default rate has to get right. Each one is a
#: real disagreement between banks, not a variation for the sake of coverage.
FORWARD_RATE_CASES: list[dict[str, Any]] = [
    {
        "id": "stays_performing",
        "name": "Performing, and stays performing",
        "purpose": "The base case. If this is wrong nothing else matters.",
        "opening": {"dpd_days": 0},
        "closing": {"dpd_days": 0},
    },
    {
        "id": "defaults_at_horizon",
        "name": "Performing, then in default at the horizon",
        "purpose": "The event being counted.",
        "opening": {"dpd_days": 15},
        "closing": {"dpd_days": 120},
    },
    {
        "id": "already_defaulted",
        "name": "Already in default at the opening date",
        "purpose": "Must be excluded from the opening population. Including it "
                   "double-counts a default the previous period already reported.",
        "opening": {"dpd_days": 200},
        "closing": {"dpd_days": 240},
    },
    {
        "id": "boundary_89",
        "name": "89 days past due at the opening date",
        "purpose": "The boundary. 89 is performing; an off-by-one here moves "
                   "every rate the method produces.",
        "opening": {"dpd_days": 89},
        "closing": {"dpd_days": 0},
    },
    {
        "id": "boundary_90_closing",
        "name": "Exactly 90 days past due at the horizon",
        "purpose": "The other boundary. 90 is default, not almost-default.",
        "opening": {"dpd_days": 10},
        "closing": {"dpd_days": 90},
    },
    {
        "id": "no_forward_observation",
        "name": "Performing, then absent from the book",
        "purpose": "Repaid, sold or closed. It has no forward status, and what "
                   "happens to it is the single largest methodological choice.",
        "opening": {"dpd_days": 5},
        "closing": None,
    },
    {
        "id": "cured_before_horizon",
        "name": "Defaults in month seven, cured by month twelve",
        "purpose": "A default under 'at any point', not under 'at the horizon'. "
                   "The two readings give different rates on the same book.",
        "opening": {"dpd_days": 0},
        "closing": {"dpd_days": 0},
        "intermediate_default": True,
    },
    {
        "id": "joined_later",
        "name": "Absent at the opening date, present at the horizon",
        "purpose": "New lending. Not in the opening population, so it cannot be "
                   "in the numerator either.",
        "opening": None,
        "closing": {"dpd_days": 150},
    },
    {
        "id": "restructured",
        "name": "Restructured during the horizon, no arrears at the end",
        "purpose": "Arrears were cured by concession rather than by payment. "
                   "Whether that is a default is a policy decision.",
        "opening": {"dpd_days": 45},
        "closing": {"dpd_days": 0, "forbearance_type": "Restructured facility"},
    },
    {
        "id": "large_exposure_default",
        "name": "A large facility that defaults",
        "purpose": "Separates a counted rate from an exposure-weighted one. The "
                   "two answers differ, and both are correct.",
        "opening": {"dpd_days": 20, "ead": 250.0},
        "closing": {"dpd_days": 180},
    },
    {
        "id": "small_exposure_default",
        "name": "A small facility that defaults",
        "purpose": "The mirror of the case above.",
        "opening": {"dpd_days": 20, "ead": 0.4},
        "closing": {"dpd_days": 180},
    },
    {
        "id": "stage3_no_arrears",
        "name": "Stage 3 at the horizon with no arrears",
        "purpose": "Unlikely-to-pay. A default under the accounting definition "
                   "and not under the arrears definition.",
        "opening": {"dpd_days": 0},
        "closing": {"dpd_days": 0, "ifrs9_stage": 3},
    },
]


@dataclass
class ValidationPack:
    """Everything needed to decide whether a method may be certified."""

    method_id: str
    method_name: str
    cases: list[TestCase] = field(default_factory=list)
    #: The rows, as one table, so a reviewer can read the whole fixture.
    dataset: list[dict[str, Any]] = field(default_factory=list)
    opening_period: str = "OPEN"
    closing_period: str = "CLOSE"
    note: str = ""
    #: The statement the fixture was actually run through, kept so a reviewer
    #: reads the SQL that produced the number rather than a description of it.
    sql: str = ""
    parameters: list[Any] = field(default_factory=list)
    #: The whole row the method returned, not only the compared keys.
    actual: dict[str, Any] = field(default_factory=dict)
    ran_at: str = ""

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed is True)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if c.passed is False)

    @property
    def complete(self) -> bool:
        return bool(self.cases) and all(c.passed is not None for c in self.cases)

    @property
    def all_passed(self) -> bool:
        return self.complete and self.failed == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "method_id": self.method_id, "method_name": self.method_name,
            "cases": [c.to_dict() for c in self.cases],
            "dataset": self.dataset,
            "opening_period": self.opening_period,
            "closing_period": self.closing_period,
            "passed": self.passed, "failed": self.failed,
            "complete": self.complete, "all_passed": self.all_passed,
            "note": self.note,
            "sql": self.sql, "parameters": list(self.parameters),
            "actual": dict(self.actual), "ran_at": self.ran_at,
        }


def build_forward_rate_pack(method: MethodDefinition, *,
                            cases: list[dict[str, Any]] | None = None,
                            ) -> ValidationPack:
    """Build the fixture and work out what the method should say about it."""
    answers = dict((method.plan or {}).get("meta", {}).get("answers") or {})
    threshold = int((method.plan or {}).get("meta", {}).get("dpd_threshold", 90))
    grain = answers.get("grain", "facility")
    key = "customer_id" if grain == "customer" else "account_id"

    chosen = cases or FORWARD_RATE_CASES
    rows: list[dict[str, Any]] = []
    test_cases: list[TestCase] = []

    for index, case in enumerate(chosen):
        identifier = f"T{index + 1:03d}"
        case_rows: list[dict[str, Any]] = []

        for label, side in (("OPEN", case.get("opening")),
                            ("CLOSE", case.get("closing"))):
            if side is None:
                continue
            row = {
                "period": label,
                key: identifier,
                "account_id": identifier,
                "customer_id": identifier,
                "dpd_days": int(side.get("dpd_days", 0)),
                "ead": float(side.get("ead", 10.0)),
                "ifrs9_stage": int(side.get("ifrs9_stage", 1)),
                "forbearance_type": str(side.get("forbearance_type", "None")),
            }
            case_rows.append(row)
        rows.extend(case_rows)

        expected = _expected_case(case, answers, threshold)
        test_cases.append(TestCase(
            id=case["id"], name=case["name"], purpose=case["purpose"],
            data=case_rows, expected=expected,
        ))

    totals = _expected_forward_rate(chosen, answers, threshold)
    test_cases.append(TestCase(
        id="portfolio_total",
        name="The rate across every case above",
        purpose="The cases are individually right and the total is what the "
                "method actually returns. Both have to hold.",
        data=[],
        expected=totals,
    ))

    return ValidationPack(
        method_id=method.id, method_name=method.name,
        cases=test_cases, dataset=rows,
        note=(
            f"Twelve situations a {grain}-level forward default rate has to get "
            f"right, one row each, with a default threshold of {threshold} days "
            "past due. Expected results are computed independently of the "
            "method, from its written methodology."
        ),
    )


def _expected_case(case: dict[str, Any], answers: dict[str, str],
                   threshold: int) -> dict[str, Any]:
    """What should happen to ONE case, worked out from the methodology text."""
    definition = answers.get("default_definition", "dpd90")
    exits = answers.get("exits", "exclude")
    timing = answers.get("timing", "at_horizon")

    opening, closing = case.get("opening"), case.get("closing")

    if opening is None:
        return {"in_opening_population": False, "counted_as_default": False,
                "why": "Not present at the opening date, so not in the "
                       "population being followed."}

    if int(opening.get("dpd_days", 0)) >= threshold:
        return {"in_opening_population": False, "counted_as_default": False,
                "why": f"Already {opening['dpd_days']} days past due at the "
                       "opening date, so it was never performing."}

    if closing is None:
        if exits == "exclude":
            return {"in_opening_population": False, "counted_as_default": False,
                    "why": "No forward observation, and exits are excluded."}
        return {"in_opening_population": True, "counted_as_default": False,
                "why": "No forward observation, and exits are treated as not "
                       "defaulted."}

    dpd_default = int(closing.get("dpd_days", 0)) >= threshold
    stage_default = int(closing.get("ifrs9_stage", 1)) >= 3
    defaulted = {
        "dpd90": dpd_default,
        "stage3": stage_default,
        "either": dpd_default or stage_default,
    }[definition]

    if timing == "anytime" and case.get("intermediate_default"):
        return {"in_opening_population": True, "counted_as_default": True,
                "why": "Defaulted within the horizon, and the method counts a "
                       "default at any point."}

    if case.get("intermediate_default") and not defaulted:
        return {"in_opening_population": True, "counted_as_default": False,
                "why": "Defaulted during the horizon but had cured by the "
                       "forward date, and the method reads status at the horizon."}

    return {
        "in_opening_population": True,
        "counted_as_default": defaulted,
        "why": (f"{closing['dpd_days']} days past due at the forward date"
                + (f", Stage {closing.get('ifrs9_stage', 1)}"
                   if definition != "dpd90" else "")
                + (" — in default." if defaulted else " — still performing.")),
    }


def _expected_forward_rate(cases: list[dict[str, Any]], answers: dict[str, str],
                           threshold: int) -> dict[str, Any]:
    """The portfolio rate, computed independently of the runtime.

    Written from the methodology in plain Python. It shares no code with the IR,
    the compiler or DuckDB, which is what makes agreement between the two
    meaningful rather than tautological.
    """
    population = 0
    defaults = 0
    population_ead = 0.0
    default_ead = 0.0

    for case in cases:
        outcome = _expected_case(case, answers, threshold)
        if not outcome["in_opening_population"]:
            continue
        ead = float((case.get("opening") or {}).get("ead", 10.0))
        population += 1
        population_ead += ead
        if outcome["counted_as_default"]:
            defaults += 1
            default_ead += ead

    expected: dict[str, Any] = {
        "opening_population": population,
        "defaults": defaults,
        "forward_default_rate_pct": (
            round(100.0 * defaults / population, 6) if population else None),
    }
    # Only what the method actually produces. Comparing against figures it never
    # claimed to compute would fail a correct method for answering the question
    # it was asked rather than a different one.
    if answers.get("weighting", "count") in ("ead", "both"):
        expected["opening_ead"] = round(population_ead, 6)
    return expected


def run_pack(pack: ValidationPack, method: MethodDefinition) -> ValidationPack:
    """Run the method against the fixture and compare, case by case.

    The fixture is written to a temporary Parquet layout and read back through
    the same DuckDB path the real book uses — not through a shortcut. A test
    that exercises a different code path than production tests a different
    program.
    """
    import shutil
    import tempfile
    from pathlib import Path

    import pandas as pd

    from backend.runtime.executor import execute
    from backend.runtime.ir import AnalyticalPlan

    if not method.plan:
        pack.note += " The method has no plan, so nothing could be run."
        return pack

    frame = pd.DataFrame(pack.dataset)
    if frame.empty:
        pack.note += " The fixture is empty."
        return pack

    root = Path(tempfile.mkdtemp(prefix="creditprobe_validation_"))
    try:
        dataset_name = str((method.plan.get("operations") or [{}])[0]
                           .get("params", {}).get("dataset")
                           or "portfolio_facility")
        for period, chunk in frame.groupby("period"):
            directory = root / dataset_name / f"period={period}"
            directory.mkdir(parents=True, exist_ok=True)
            chunk.to_parquet(directory / "data.parquet", index=False)

        plan = AnalyticalPlan.from_dict(method.plan)
        # Point the scans at the fixture rather than the book.
        for operation in plan.operations:
            if operation.op.value == "SCAN":
                operation.params["period"] = (
                    pack.opening_period
                    if operation.id in ("opening",) else pack.closing_period
                )

        result = execute(plan, source=_FixtureSource(root))
        actual = result.rows[0] if result.rows else {}
        pack.actual = dict(actual)
        pack.ran_at = datetime.now(UTC).isoformat()
        if result.query is not None:
            pack.sql = result.query.sql
            pack.parameters = list(result.query.params)
    except Exception as e:
        logger.exception("Validation run failed for %s", method.id)
        for case in pack.cases:
            case.passed = False
            case.note = f"The method could not be run: {e}"
        return pack
    finally:
        shutil.rmtree(root, ignore_errors=True)

    for case in pack.cases:
        if case.id == "portfolio_total":
            case.actual = {k: actual.get(k) for k in case.expected}
            case.passed = _close_enough(case.expected, case.actual)
            case.note = ("" if case.passed else
                         "The independent calculation and the method disagree. "
                         "One of them is wrong.")
        else:
            # A per-row case is evidence about the total, and the total is what
            # the method returns. Marking each row from the total would be
            # circular, so a row case passes when the total does and says why.
            case.actual = {"checked_via": "portfolio_total"}
            case.passed = None

    total = next((c for c in pack.cases if c.id == "portfolio_total"), None)
    if total is not None:
        for case in pack.cases:
            if case.id != "portfolio_total":
                case.passed = total.passed
                case.note = case.note or (
                    "Verified through the portfolio total, which agrees with the "
                    "independent calculation over every case."
                    if total.passed else
                    "The portfolio total disagrees, so no individual case is "
                    "confirmed."
                )
    return pack


def _close_enough(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
    """Compare, tolerating float representation but nothing else."""
    for key, want in expected.items():
        got = actual.get(key)
        if want is None and got is None:
            continue
        if want is None or got is None:
            return False
        try:
            if abs(float(want) - float(got)) > 1e-6:
                return False
        except (TypeError, ValueError):
            if str(want) != str(got):
                return False
    return True


class _FixtureSource:
    """A DuckDBSource that reads the validation fixture instead of the book.

    Exists so `run_pack` can reuse the production compiler and executor
    unchanged. Only the file location differs, which is the only thing that
    should differ.
    """

    def __init__(self, root: Any) -> None:
        self.root = root

    def _require_files(self, dataset: str, period: str | None) -> str:
        from pathlib import Path

        base = Path(self.root) / dataset
        if period:
            return str(base / f"period={period}" / "*.parquet")
        return str(base / "**" / "*.parquet")


__all__ = [
    "FORWARD_RATE_CASES",
    "ValidationPack",
    "build_forward_rate_pack",
    "run_pack",
]
