"""A plan the size of a real one.

§46 asks for this explicitly and it is worth its own file: every query in
`query.py` is written to be independent of how many rows it returns, and the
only way to know whether that is still true is to put a thousand rows behind
it and count.

Two things are measured, and the query count matters more than the clock.
Wall time on a busy machine is noisy; a query count is exact, and an N+1 shows
up as "1,203 queries" long before it shows up as a slow page.
"""

from __future__ import annotations

import time
import uuid

import pytest
from sqlalchemy import event

from tests.conftest import database_available

#: Big enough that an N+1 is unmissable, small enough to build in a fixture.
TASKS = 800

#: What the reads are allowed to cost, whatever the row count.
#:
#: These are ceilings with room in them, not measurements — a limit set to
#: exactly what the code does today fails on the next honest refactor and
#: teaches people to raise it without looking. What they catch is an ORDER OF
#: MAGNITUDE change, which is what an N+1 is.
BUDGET = {
    "project_detail": 20,
    "portfolio": 20,
    "my_work": 20,
    "attention": 20,
    "brief": 20,
    "export": 25,
}


@pytest.fixture(scope="module", autouse=True)
def _needs_database():
    if not database_available():
        pytest.skip("the Project Planner is a PostgreSQL feature")


class Principal:
    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self.role = "ADMIN"

    def has(self, _allowed) -> bool:
        return True


class Counter:
    """Counts SQL statements on the engine, not on one session."""

    def __init__(self) -> None:
        self.count = 0
        self.statements: list[str] = []

    def __enter__(self):
        from backend.db.engine import engine

        self._engine = engine
        event.listen(engine, "before_cursor_execute", self._seen)
        return self

    def __exit__(self, *_exc):
        event.remove(self._engine, "before_cursor_execute", self._seen)
        return False

    def _seen(self, _conn, _cursor, statement, *_rest):
        self.count += 1
        self.statements.append(statement[:120])


@pytest.fixture(scope="module")
def big():
    """One project with eight hundred tasks, built once."""
    from sqlalchemy import select

    from backend.db.engine import get_session
    from backend.db.models import User
    from backend.models.planner import PlannerTask
    from backend.planner import service as svc

    tag = uuid.uuid4().hex[:8]
    with get_session() as session:
        owner = User(username=f"perf-{tag}", password_hash="x",
                     role="ANALYST", first_name="Perf", last_name="Owner")
        session.add(owner)
        session.flush()
        who = Principal(int(owner.id))

        project = svc.create_project(
            session, who, code=f"PERF-{tag[:6].upper()}",
            name="A plan the size of a real one", status="ACTIVE",
            manager_id=int(owner.id), start_date="2026-01-05",
            target_end_date="2026-12-18")
        session.flush()
        pid = int(project.id)

        workstreams = [
            int(svc.create_workstream(
                session, who, pid, code=f"WS-{n}", name=f"Workstream {n}",
                lead_id=int(owner.id)).id)
            for n in range(1, 9)]
        session.flush()

        # Inserted directly rather than through create_task: eight hundred
        # validated writes take a minute, and what this file measures is the
        # READ path. The rows are identical either way.
        session.add_all([
            PlannerTask(
                project_id=pid, workstream_id=workstreams[i % 8],
                code=f"T-{i:04d}", title=f"Task {i}",
                owner_id=int(owner.id), status="IN_PROGRESS",
                percent_complete=i % 100,
                start_date=None, due_date=None, weight=1.0,
                created_by=int(owner.id), updated_by=int(owner.id))
            for i in range(TASKS)])
        session.commit()

        held = session.execute(
            select(PlannerTask.id).where(
                PlannerTask.project_id == pid)).scalars().all()
        return {"id": pid, "user": int(owner.id), "tasks": len(held)}


def _measure(name: str, fn) -> tuple[object, int, float]:
    started = time.perf_counter()
    with Counter() as counter:
        result = fn()
    elapsed = time.perf_counter() - started
    budget = BUDGET[name]
    assert counter.count <= budget, (
        f"{name} ran {counter.count} queries for {TASKS} tasks "
        f"(budget {budget}). First few:\n"
        + "\n".join(counter.statements[:8]))
    return result, counter.count, elapsed


def test_the_fixture_is_actually_large(big):
    """Guards the rest of the file.

    Every assertion below is meaningless against a project with four tasks in
    it, and a fixture that silently built four would make this whole file
    report success while measuring nothing.
    """
    assert big["tasks"] >= TASKS


def test_project_detail_is_a_fixed_number_of_queries(big):
    from backend.db.engine import get_session
    from backend.planner import query as pq

    with get_session() as session:
        who = Principal(big["user"])
        detail, queries, seconds = _measure(
            "project_detail", lambda: pq.project_detail(session, who,
                                                        big["id"]))
    assert len(detail["tasks"]) == big["tasks"]
    assert seconds < 5, f"{seconds:.1f}s"


def test_the_portfolio_does_not_scale_with_tasks(big):
    from backend.db.engine import get_session
    from backend.planner import query as pq

    with get_session() as session:
        who = Principal(big["user"])
        book, _queries, seconds = _measure(
            "portfolio", lambda: pq.portfolio(session, who))
    assert book["projects"], "the portfolio came back empty"
    assert seconds < 5, f"{seconds:.1f}s"


def test_my_work_does_not_scale_with_tasks(big):
    from backend.db.engine import get_session
    from backend.planner import query as pq

    with get_session() as session:
        who = Principal(big["user"])
        work, _queries, seconds = _measure(
            "my_work", lambda: pq.my_work(session, who))
    assert sum(work["counts"].values()) == big["tasks"], \
        "every task is owned by this person, so all of them belong in a bucket"
    assert seconds < 5, f"{seconds:.1f}s"


def test_attention_does_not_scale_with_tasks(big):
    from backend.db.engine import get_session
    from backend.planner import query as pq

    with get_session() as session:
        who = Principal(big["user"])
        _items, _queries, seconds = _measure(
            "attention", lambda: pq.attention(session, who))
    assert seconds < 5, f"{seconds:.1f}s"


def test_the_brief_does_not_scale_with_tasks(big):
    from backend.db.engine import get_session
    from backend.planner import agent as ai

    with get_session() as session:
        who = Principal(big["user"])
        brief, _queries, seconds = _measure(
            "brief", lambda: ai.project_brief(session, who, big["id"]))
    assert brief["statements"]
    assert seconds < 5, f"{seconds:.1f}s"


def test_the_export_reads_the_plan_in_a_fixed_number_of_queries(big):
    """The workbook is the one read that MUST load every row.

    Its cost is allowed to scale with rows — the file contains them — but not
    with queries. Eight hundred tasks fetched one at a time would be eight
    hundred round trips for a download somebody is watching a spinner for.
    """
    from backend.db.engine import get_session
    from backend.planner import workbook as wb

    with get_session() as session:
        who = Principal(big["user"])
        content, _queries, seconds = _measure(
            "export", lambda: wb.export(session, who, big["id"]))
    assert len(content) > 20_000
    assert seconds < 20, f"{seconds:.1f}s"
