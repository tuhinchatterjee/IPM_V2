"""§47's named permissions, enforced rather than hidden.

§47's closing instruction is the reason this file exists: **do not rely on
frontend hiding.** A permission that is only a hidden menu item is a
permission an attacker has, and the only way to know the backend actually
holds the line is to call the routes as each role and read the status code.

Every route asserted here is one the brief names as governed. The test that
matters most is the last one: every write route in the new subsystems is
refused to a VIEWER, checked by enumerating the OpenAPI document rather than
by a list somebody maintains — because a list somebody maintains is a list
that stops including the route added last week.
"""

from __future__ import annotations

import pytest

from backend.api import permissions as pm


def headers(role: str) -> dict[str, str]:
    return {"X-IPM-Role": role}


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


# ============================================================= the catalogue


#: §47's eighteen, verbatim.
SECTION_47 = (
    "AI_BRAIN_VIEW", "AI_BRAIN_EXPORT", "AI_BRAIN_IMPORT",
    "AI_BRAIN_EVALUATE", "AI_BRAIN_MERGE", "AI_BRAIN_ACTIVATE",
    "AI_BRAIN_ROLLBACK", "AI_BRAIN_DELETE_CANDIDATE",
    "REGULATORY_DOCUMENT_UPLOAD", "REGULATORY_REVIEW", "REGULATORY_APPROVE",
    "REGULATORY_CONFLICT_RESOLVE", "REGULATORY_METHOD_PROMOTE",
    "REGULATORY_RELEASE_APPROVE",
    "FEEDBACK_VIEW_OWN", "FEEDBACK_REVIEW", "FEEDBACK_ADJUDICATE",
    "FEEDBACK_RELEASE",
)


def test_every_permission_section_47_names_exists():
    assert len(SECTION_47) == 18
    missing = [name for name in SECTION_47 if name not in pm.NAMED]

    assert missing == []


def test_every_named_permission_says_what_it_lets_somebody_do():
    """A permission nobody can describe gets granted to everybody."""
    for name, (roles, means) in pm.NAMED.items():
        assert len(means) > 30, name
        assert roles, name


def test_an_unknown_permission_is_refused_rather_than_granted():
    """The permissive version turns a typo in a route decorator into an open
    door, and the door is open for as long as nobody reads that line."""
    assert pm.holds("ADMIN", "AI_BRAIN_VEIW") is False
    assert pm.holds("NOT_A_ROLE", "AI_BRAIN_VIEW") is False


def test_activating_a_brain_is_the_narrowest_brain_permission():
    """It is the one that changes what every answer is made of."""
    assert pm.NAMED["AI_BRAIN_ACTIVATE"][0] == frozenset({pm.Role.ADMIN})
    assert pm.Role.DATA_STEWARD in pm.NAMED["AI_BRAIN_IMPORT"][0]


def test_evaluating_and_activating_are_held_by_different_sets():
    """§16 puts a measured evaluation before approval so the person who runs
    the numbers and the person who accepts them can be different people."""
    assert pm.NAMED["AI_BRAIN_EVALUATE"][0] != pm.NAMED["AI_BRAIN_ACTIVATE"][0]


def test_leaving_feedback_is_the_widest_permission_in_the_product():
    """A user who was shown an answer and then refused the ability to say it
    was wrong has been asked for their trust and denied the means to
    withdraw it."""
    assert pm.Role.VIEWER in pm.NAMED["FEEDBACK_VIEW_OWN"][0]
    assert pm.Role.VIEWER not in pm.NAMED["FEEDBACK_ADJUDICATE"][0]


def test_the_catalogue_renders_as_data():
    rows = pm.catalogue()

    assert len(rows) == len(pm.NAMED)
    for row in rows:
        assert row["permission"]
        assert row["means"]
        assert row["roles"]


# ======================================================= enforced, not hidden


READ_ROUTES = [
    "/api/v1/brain/overview",
    "/api/v1/brain/ledger",
    "/api/v1/brain/installations",
    "/api/v1/brain/security",
    "/api/v1/regulatory-intelligence/schema",
    "/api/v1/regulatory-intelligence/requirements",
    "/api/v1/continuous-learning/cockpit",
    "/api/v1/continuous-learning/partitions",
]


@pytest.mark.parametrize("path", READ_ROUTES)
def test_a_viewer_is_refused_by_the_backend_not_by_a_hidden_menu(client,
                                                                 path):
    assert client.get(path, headers=headers("VIEWER")).status_code == 403


@pytest.mark.parametrize("path,role,expected", [
    # An analyst may ask how the product has been performing. §77 requires
    # every improvement claim to travel with its sample, and a claim only
    # administrators can check is a claim.
    ("/api/v1/continuous-learning/cockpit", "ANALYST", 200),
    ("/api/v1/continuous-learning/measurement-rules", "ANALYST", 200),
    # A steward may read the Brain Center and may not activate anything.
    ("/api/v1/brain/overview", "DATA_STEWARD", 200),
    ("/api/v1/regulatory-intelligence/schema", "ANALYST", 200),
])
def test_reading_is_wider_than_changing(client, path, role, expected):
    assert client.get(path, headers=headers(role)).status_code == expected


WRITE_ROUTES = [
    ("/api/v1/brain/imports/x/activate", {}),
    ("/api/v1/brain/security/signers", {"key_id": "k", "reason": "r"}),
    ("/api/v1/regulatory-intelligence/requirements/x/promote", {}),
    ("/api/v1/continuous-learning/baselines",
     {"instance_id": "i", "build_sha": "a", "development_set_version": "d"}),
]


@pytest.mark.parametrize("path,body", WRITE_ROUTES)
def test_an_analyst_may_not_change_the_intelligence_layer(client, path, body):
    assert client.post(path, json=body,
                       headers=headers("ANALYST")).status_code == 403


def test_no_new_write_route_is_open_to_a_viewer(client):
    """Enumerated from the live OpenAPI document rather than from a list.

    A list somebody maintains is a list that stops including the route added
    last week, and that route is the one worth checking.
    """
    from backend.api.main import create_app

    governed = ("/api/v1/brain/", "/api/v1/regulatory-intelligence/",
                "/api/v1/continuous-learning/")
    paths = create_app().openapi()["paths"]
    checked = 0

    for path, methods in paths.items():
        if not path.startswith(governed) or "post" not in methods:
            continue
        # Substitute something for any path parameter; the route should
        # refuse on the permission before it ever looks the id up.
        concrete = path
        while "{" in concrete:
            start = concrete.index("{")
            end = concrete.index("}", start)
            concrete = concrete[:start] + "x" + concrete[end + 1:]
        response = client.post(concrete, json={}, headers=headers("VIEWER"))
        assert response.status_code == 403, f"{concrete} -> {response.status_code}"
        checked += 1

    assert checked >= 10, "the enumeration found too few routes to be a check"
