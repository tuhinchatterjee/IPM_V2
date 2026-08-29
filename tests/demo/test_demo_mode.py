"""Demo Mode and the demonstration workspace.

The client-demo release-candidate brief, §4, §9 and §12.

What is worth testing here is not that a boolean reads a variable. It is that
the two modes stay DISTINCT, that the reset list and the protected list can
never overlap, and that the setting a client is told to use actually turns the
thing on — which is exactly what was broken when this phase opened.
"""

from __future__ import annotations

import pathlib

import pytest

from backend.demo import mode
from backend.demo import workspace as ws
from backend.release import demo_safe


@pytest.fixture
def clean_env(monkeypatch):
    for name in (mode.ENV, *demo_safe.ENV_NAMES):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ------------------------------------------------------------------ Demo Mode


def test_demo_mode_is_off_unless_it_is_turned_on(clean_env):
    """Fail-closed in the direction that matters.

    A production deployment must not acquire a synthetic-data label by
    forgetting to set something.
    """
    assert mode.enabled() is False
    assert mode.posture().on is False
    assert mode.posture().label == ""


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_the_switch_accepts_the_words_people_type(clean_env, value):
    clean_env.setenv(mode.ENV, value)
    assert mode.enabled() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "maybe"])
def test_anything_else_is_off(clean_env, value):
    clean_env.setenv(mode.ENV, value)
    assert mode.enabled() is False


def test_every_guarantee_follows_from_the_one_switch(clean_env):
    """§4's list, as one object rather than nine functions to probe.

    A deployment in Demo Mode with schedules still firing is not in Demo Mode.
    Deriving every consequence from the one setting is what stops that
    combination existing.
    """
    clean_env.setenv(mode.ENV, "true")
    found = mode.posture()

    assert found.on is True
    assert found.label == "DEMO - SYNTHETIC DATA"
    assert found.data_release == mode.DATA_RELEASE
    assert set(found.guarantees) == set(mode.GUARANTEES)
    assert found.guarantees["synthetic_label"] is True
    assert found.guarantees["background_schedules"] is False
    assert found.guarantees["external_communication"] is False
    assert found.guarantees["automatic_publication"] is False
    assert mode.schedules_may_fire() is False
    assert mode.may_communicate_externally() is False
    assert mode.may_publish_automatically() is False
    assert mode.requires_confirmation() is True


def test_off_the_guarantees_are_absent_rather_than_false(clean_env):
    """"False" would read as a promise that external communication IS
    happening. Absent is the truthful shape when the mode is off."""
    assert mode.posture().guarantees == {}


def test_the_two_modes_are_independent(clean_env):
    """A pilot on real client data wants Demo Safe Mode and must NOT have
    Demo Mode, which would label the client's own portfolio synthetic."""
    clean_env.setenv(demo_safe.ENV, "true")

    assert demo_safe.enabled() is True
    assert mode.enabled() is False


# -------------------------------------------------------------- Demo Safe Mode


@pytest.mark.parametrize("name", demo_safe.ENV_NAMES)
def test_either_documented_name_turns_demo_safe_mode_on(clean_env, name):
    """The defect this phase found.

    `backend/release/demo_safe.py` read AI_DEMO_SAFE_MODE while
    `orchestrator.demo_safe()` read DEMO_SAFE_MODE, and `.env.example`
    documented the second. Setting the documented one enabled the ROUTING
    half of Demo Safe Mode and left the half that decides whether an answer
    may be SHOWN switched off — a mode whose whole purpose is to refuse a
    wrong answer, half on, looking on.
    """
    from backend.orchestration import orchestrator

    clean_env.setenv(name, "true")

    assert demo_safe.enabled() is True, name
    assert orchestrator.demo_safe() is True, name


def test_env_example_only_documents_switches_the_code_reads():
    """The setting a client is told to use must be one the code honours.

    Read from `.env.example` rather than restated, so the document and the
    code cannot drift apart again — which is precisely how Demo Safe Mode
    came to be documented under a name half of it did not read.
    """
    root = pathlib.Path(__file__).resolve().parents[2]
    text = (root / ".env.example").read_text(encoding="utf-8")

    assert "DEMO_SAFE_MODE=" in text
    assert any(f"{name}=" in text for name in demo_safe.ENV_NAMES)
    assert f"{mode.ENV}=" in text, (
        f"{mode.ENV} turns Demo Mode on and .env.example does not mention it")


def test_the_demo_switches_reach_the_container():
    """Both were read by the backend, documented in .env.example, and passed
    to no container — so setting either had no effect inside Docker, which is
    the only place the demonstration runs."""
    root = pathlib.Path(__file__).resolve().parents[2]
    compose = (root / "docker-compose.yml").read_text(encoding="utf-8")

    assert f"{mode.ENV}:" in compose, "Demo Mode is not passed to any service"
    assert "DEMO_SAFE_MODE:" in compose, (
        "Demo Safe Mode is not passed to any service")


# ---------------------------------------------------------------- the workspace


def test_the_reset_list_and_the_protected_list_never_overlap():
    """A table cannot be both emptied and protected.

    Checked as a property rather than trusted, because the cost of getting it
    wrong is deleting the teaching library on the morning of a demonstration.
    """
    both = set(ws.RESET_ORDER) & ws.PROTECTED_TABLES
    assert both == set(), sorted(both)


def test_the_governed_platform_is_protected():
    """The line between WORKSPACE and GOVERNED PLATFORM, asserted by name."""
    for table in ("teaching_cases", "dataset_definitions", "field_definitions",
                  "users", "alembic_version", "learning_releases",
                  "regulatory_releases"):
        assert table in ws.PROTECTED_TABLES, table
        assert table not in ws.RESET_ORDER, table


def test_children_are_emptied_before_their_parents():
    """A reset that deleted projects before investigations would be blocked by
    a foreign key halfway through and leave the workspace in neither state."""
    order = list(ws.RESET_ORDER)
    for child, parent in (
        ("investigation_messages", "investigations"),
        ("investigations", "projects"),
        ("project_status_events", "projects"),
        ("workflow_events", "workflow_items"),
        ("workflow_recipients", "workflow_items"),
        ("lens_revisions", "lenses"),
        ("playbook_runs", "playbooks"),
        ("agent_tasks", "agent_runs"),
    ):
        assert order.index(child) < order.index(parent), f"{child} vs {parent}"


def test_the_test_accounts_are_named_not_matched():
    """A pattern that removed a real account because it started with `wf_`
    would be a far worse failure than one test row left on screen."""
    assert "wf_author" in ws.TEST_ACCOUNTS
    assert all(isinstance(name, str) and name for name in ws.TEST_ACCOUNTS)
    demo = {username for username, _, _ in ws.DEMO_ACCOUNTS}
    assert demo & set(ws.TEST_ACCOUNTS) == set(), (
        "a demonstration account is on the removal list")


def test_the_four_demo_accounts_cover_the_roles_the_brief_asks_for():
    roles = {role for _, role, _ in ws.DEMO_ACCOUNTS}
    assert {"ADMIN", "DATA_STEWARD", "ANALYST", "VIEWER"} <= roles
