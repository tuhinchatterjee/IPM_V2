"""
What identifies one execution.

A plan hash answers "is this the same computation". It cannot answer "should
this produce the same numbers", because the same computation run against a
restated dataset or a re-declared join is entitled to a different answer. These
tests check that the four hashes separate those cases rather than blurring them.
"""

from __future__ import annotations

import dataclasses

import pytest

from backend.data_access.catalog import get_catalog
from backend.orchestration import multi
from backend.orchestration.vocabulary import get_vocabulary
from backend.runtime import fingerprint as fp
from backend.runtime.executor import execute
from backend.services import relationships as rel_service
from tests.conftest import database_available

QUESTION = ("Show Real Estate customers whose ECL increased more than 20%, "
            "rating deteriorated at least two notches, and EAD did not decline "
            "over the latest year.")


@pytest.fixture(scope="module", autouse=True)
def require_database():
    if not database_available():
        pytest.skip("needs the platform database")


@pytest.fixture(scope="module")
def built():
    from backend.db.engine import SessionLocal

    session = SessionLocal()
    try:
        active = rel_service.active_relationships(session)
    finally:
        session.close()
    vocabulary = get_vocabulary()
    request = multi.read_question(
        QUESTION, catalogue=get_catalog(), periods=vocabulary.periods,
        dimensions=vocabulary.dimensions, relationships=active)
    return multi.build_plan(request, catalogue=get_catalog())


@pytest.fixture(scope="module")
def plan(built):
    """The planner emits the IR as data; the runtime parses it. Both are the
    same plan, and the fingerprint is a property of the parsed one."""
    from backend.runtime.ir import AnalyticalPlan

    return AnalyticalPlan.from_dict(built.plan)


@pytest.fixture(scope="module")
def result(built):
    return execute(built.plan, question=QUESTION)


def test_a_run_carries_four_hashes_and_one_that_binds_them(result):
    marks = result.fingerprint
    for part in ("plan", "data", "relationships", "parameters", "run"):
        assert marks[part], f"{part} is not recorded"
        assert len(marks[part]) == fp.DIGEST


def test_the_same_plan_run_twice_fingerprints_the_same(built):
    first = execute(built.plan, question=QUESTION)
    second = execute(built.plan, question=QUESTION)
    assert first.fingerprint["run"] == second.fingerprint["run"]


def test_a_different_period_moves_the_parameter_hash_and_nothing_else(plan):
    """The same analysis at a different quarter is visibly the same analysis."""
    moved = _at_other_period(plan)
    if moved is None:
        pytest.skip("the plan does not bind a period to move")
    before = fp.fingerprint(plan)
    after = fp.fingerprint(moved)
    assert before["parameters"] != after["parameters"]
    assert before["plan"] != after["plan"], (
        "a period is part of the IR too, so the plan hash moves with it")
    assert before["run"] != after["run"]


def test_a_re_declared_relationship_moves_the_hash_without_touching_the_plan(
        result):
    """The case a plan hash alone cannot see.

    A steward changing a cardinality changes what the analysis means without
    changing a character of the IR. If that did not move the run hash, two runs
    that disagree would look identical.
    """
    marks = result.fingerprint
    assert marks["relationships_used"], "the worked example walks relationships"

    bumped = [dict(entry, version=int(entry["version"] or 0) + 1)
              for entry in marks["relationships_used"]]
    assert fp._hash(bumped) != marks["relationships"]

    same_plan = fp.fingerprint(result.plan, joins=result.joins)
    assert same_plan["plan"] == marks["plan"]


def test_the_dataset_versions_are_recorded_not_just_hashed(result):
    """A hash nobody can explain is a hash nobody will trust."""
    names = {entry["dataset"] for entry in result.fingerprint["datasets"]}
    assert "portfolio_facility" in names
    for entry in result.fingerprint["datasets"]:
        assert entry["version"], f"{entry['dataset']} has no version"


def test_a_dataset_the_catalogue_cannot_resolve_is_recorded_as_unknown():
    """Dropping it would let two different reads hash the same."""
    from backend.runtime.ir import AnalyticalPlan, Operation, OpType

    plan = AnalyticalPlan(operations=[Operation(
        id="s", op=OpType.SCAN,
        params={"dataset": "no_such_dataset", "period": "Q2 2026"})])
    versions = fp.dataset_versions(plan)
    assert versions == [{"dataset": "no_such_dataset", "version": "unknown",
                         "origin": "unknown", "periods": ["Q2 2026"]}]


def test_a_self_join_is_not_counted_as_a_relationship():
    """The opening-to-closing join a movement analysis makes is not something
    a steward can re-declare, so it does not belong in the relationship hash."""
    joins = [{"step": "movement", "relationship_id": None},
             {"step": "j1", "relationship_id": 7, "relationship_version": 2,
              "cardinality": "many_to_one"}]
    used = fp.relationship_versions(joins)
    assert [entry["relationship_id"] for entry in used] == [7]


def test_the_fingerprint_reaches_the_trace(result):
    node = result.graph.nodes.get("fingerprint")
    assert node is not None
    assert node.config["run"] == result.fingerprint["run"]
    assert node.is_governed, "a hash of governed facts is itself governed"


def _at_other_period(plan):
    """The same plan with every bound period replaced by another one."""
    from backend.runtime.ir import OpType

    periods = sorted({str(o.params.get("period")) for o in plan.operations
                      if o.op is OpType.SCAN and o.params.get("period")})
    if len(periods) < 2:
        return None
    swap = {periods[0]: periods[-1], periods[-1]: periods[0]}
    operations = []
    for operation in plan.operations:
        params = dict(operation.params)
        if params.get("period") in swap:
            params["period"] = swap[params["period"]]
        operations.append(dataclasses.replace(operation, params=params))
    return dataclasses.replace(plan, operations=operations)
