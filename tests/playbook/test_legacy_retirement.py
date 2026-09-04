"""The earlier Playbooks feature is retired, and nothing it touched broke.

A removal has two halves that fail in opposite directions, and both are worth
pinning permanently rather than checking once by hand.

The first half is that the old feature is actually gone: no navigation entry
pointing at a route nobody serves, no API path answering under the old name,
no module a later import could resurrect, no table left in the schema holding
rows nothing reads. A half-removed feature is worse than either state, because
the parts that remain look maintained.

The second half is that the removal took only what belonged to the old
feature. Playbooks ran certified analyses through the engine registry and the
engine runner, and tested thresholds against their results. None of that was
Playbooks' — it is CreditProbe's analytical infrastructure, shared with Ask,
Investigations, Lenses and the Studio — and deleting it because one caller
went away would have been the expensive kind of mistake, the kind found weeks
later by a different feature.

So: four tests that the old thing is gone, and one that the shared thing it
stood on is still standing.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: What the old feature owned outright, and what it merely borrowed. The
#: distinction is the whole point of this module, so it is written down rather
#: than left to the reader of the assertions below.
LEGACY_ONLY = (
    "backend.services.playbooks",
    "backend.api.routers.playbooks",
)

#: Borrowed, not owned. Each of these outlived the feature because other parts
#: of CreditProbe were already standing on it.
SHARED = (
    "backend.engine.registry",
    "backend.engine.runner",
    "backend.services.lenses",
    "backend.brain.compatibility",
)


# ======================================================== the old thing is gone


def test_the_old_navigation_entry_is_gone():
    """No entry pointing at `/playbooks`, and exactly one Playbook.

    A stale navigation entry is the most visible way a removal goes wrong: the
    route stops existing, the link does not, and the first person to click it
    gets a 404 with the product's own chrome around it.
    """
    nav = (ROOT / "frontend/src/lib/navigation.ts").read_text(encoding="utf-8")

    assert 'href: "/playbooks"' not in nav, (
        "the earlier Playbooks feature still has a navigation entry")
    assert nav.count('href: "/playbook"') == 1, (
        "the Playbook must appear once and point at the committee pack system")

    entry = nav[nav.index('href: "/playbook"'):][:1400]
    assert 'label: "Playbook"' in nav
    assert 'group: "Govern"' in entry


def test_the_old_public_route_is_retired():
    """`/playbooks` is not served, by the frontend or the API.

    Retired rather than redirected, deliberately. A redirect from a standing
    analytical instruction to a committee pack would tell somebody the two are
    the same object under two names, and they are not.
    """
    assert not (ROOT / "frontend/src/app/playbooks").exists(), (
        "the old /playbooks page directory is still present")

    from backend.api.main import create_app

    paths = create_app().openapi()["paths"]
    legacy = [p for p in paths if "/playbooks" in p]
    assert legacy == [], f"the old API is still mounted: {legacy}"

    # And the name now belongs to exactly one thing.
    assert [p for p in paths if "/playbook" in p], (
        "the committee pack system should own the /playbook API surface")


def test_no_protected_feature_depends_on_the_removed_implementation():
    """Nothing imports what was deleted.

    An import that survives a deletion is a landmine: it passes every test
    that does not exercise that path, and fails in front of whoever does.
    """
    for module in LEGACY_ONLY:
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(module)

    from backend.models import platform

    for gone in ("Playbook", "PlaybookRun"):
        assert not hasattr(platform, gone), (
            f"backend.models.platform still exports {gone}, so something can "
            "still reference a table that no longer exists")

    # A source sweep as well as an import check: a reference inside a function
    # body never runs during collection and would not be caught above.
    offenders = []
    for path in list((ROOT / "backend").rglob("*.py")) + \
            list((ROOT / "scripts").rglob("*.py")):
        if "__pycache__" in str(path):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in ("services.playbooks", "routers.playbooks",
                       "PlaybookRun", "import Playbook,"):
            if needle in text:
                offenders.append(f"{path.relative_to(ROOT)}: {needle}")
    assert offenders == [], "\n".join(offenders)


@pytest.mark.usefixtures("session")
def test_the_legacy_tables_are_gone_from_the_schema(session):
    """`playbooks` and `playbook_runs` are dropped, and the new ones exist.

    Checked against the live schema rather than against the migration file,
    because a migration that was written is not a migration that ran.
    """
    from sqlalchemy import text

    left = session.execute(text(
        "select tablename from pg_tables "
        "where tablename in ('playbooks', 'playbook_runs')")).all()
    assert [r[0] for r in left] == [], (
        "a legacy table is still in the schema, holding rows nothing reads")

    made = session.execute(text(
        "select count(*) from pg_tables where tablename like 'playbook\\_%'"
    )).scalar()
    assert made >= 15, (
        f"the committee pack schema is incomplete: {made} tables")


def test_the_removal_is_reversible_in_the_migration():
    """0039's downgrade puts the old tables back.

    Not because anybody should run it — the rows are gone either way — but
    because a revision that cannot be stepped back is one nobody can deploy
    with confidence, and the schema half of the removal is recoverable even
    though the data half is not.
    """
    text = (ROOT / "alembic/versions/0039_playbook_committee_intelligence.py"
            ).read_text(encoding="utf-8")

    upgrade = text[text.index("def upgrade("):text.index("def downgrade(")]
    downgrade = text[text.index("def downgrade("):]

    assert 'op.drop_table("playbooks")' in upgrade
    assert 'op.drop_index("ix_playbook_runs_playbook"' in upgrade
    assert '"playbooks",' in downgrade, (
        "downgrade does not recreate the table upgrade dropped")
    assert '"playbook_runs",' in downgrade


# =================================================== the shared thing still is


def test_the_shared_infrastructure_the_feature_stood_on_still_works():
    """Certified analyses, the runner, Lenses and Brain compatibility.

    Playbooks resolved certified analyses through the engine registry and ran
    them through the engine runner. Both are CreditProbe's, not the removed
    feature's, and both have other callers. This test exists so that a future
    reader tracing why the registry is still here finds an answer rather than
    a guess.
    """
    for module in SHARED:
        importlib.import_module(module)

    from backend.engine.registry import get_registry

    registered = get_registry().all()
    assert len(registered) >= 20, (
        f"the certified analysis registry has shrunk to {len(registered)} — "
        "the Playbooks removal must not have taken analyses with it")
    assert all(getattr(a, "id", None) for a in registered)

    from backend.engine.runner import persist_run, run_analysis

    assert callable(run_analysis) and callable(persist_run)


def test_brain_compatibility_declares_the_new_module_not_the_old_name():
    """The portable Brain's module set is a contract with other deployments.

    Renamed rather than dropped: a package built against this deployment
    should say it needs `playbook`, and a deployment that has the committee
    pack system should satisfy it. Leaving `playbooks` there would have
    described a capability nothing provides.
    """
    source = (ROOT / "backend/brain/compatibility.py").read_text(
        encoding="utf-8")

    assert '"playbook"' in source
    assert '"playbooks"' not in source, (
        "the Brain still advertises a module this deployment does not have")
