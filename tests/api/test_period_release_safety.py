"""What a period release must refuse.

Everything here was found by reading the Data Builder release path as
somebody trying to break it rather than as somebody using it, and every
case in it was a real hole in the code that shipped before this file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import database_available

# ============================================== a period label is not a path


class TestAPeriodLabelCannotReachOutOfTheLake:
    """A period arrives from an upload form and reaches the filesystem twice —
    the staging directory and the published partition.

    The staging path stripped "/" and the partition path did not, and neither
    stripped a dot segment, so `period=../../../../tmp/x` wrote a parquet
    file outside the data lake entirely. Sanitising the two paths separately
    is how that reopens, so the label is checked once, at the door.
    """

    def test_real_period_labels_are_accepted(self) -> None:
        from backend.services.data_periods import check_period_label

        for label in ("Q3 2026", "2026-09", "FY2026", "Sep 2026", "2026",
                      "H1 2026", "M09_2026", "2026.09"):
            assert check_period_label(label) == label

    def test_whitespace_is_normalised_not_rejected(self) -> None:
        from backend.services.data_periods import check_period_label

        assert check_period_label("  Q3   2026 ") == "Q3 2026"

    @pytest.mark.parametrize("label", [
        "../../../../tmp/pwned",
        "..",
        "../Q3 2026",
        "Q3 2026/../..",
        "a/b",
        "/etc/passwd",
        "",
        "   ",
        "./x",
        "x" * 70,
        "\x00Q1 2026",
        "-leading-hyphen",
    ])
    def test_anything_that_is_not_a_label_is_refused(self, label) -> None:
        from backend.services.data_builder import DataBuilderError
        from backend.services.data_periods import check_period_label

        with pytest.raises(DataBuilderError):
            check_period_label(label)

    def test_the_staging_directory_stays_under_the_raw_layer(self) -> None:
        from backend.config import settings
        from backend.services.data_periods import _staging_dir

        root = Path(settings.raw_dir).resolve()
        staged = _staging_dir("ifrs9_staging", "Q3 2026").resolve()
        assert str(staged).startswith(str(root))

    def test_a_traversing_label_never_produces_a_directory(self) -> None:
        from backend.services.data_builder import DataBuilderError
        from backend.services.data_periods import _staging_dir

        with pytest.raises(DataBuilderError):
            _staging_dir("ifrs9_staging", "../../../../tmp/pwned")


@pytest.mark.skipif(not database_available(),
                    reason="staging a period needs the governed catalogue")
class TestTheUploadRouteRefusesItToo:
    """The check has to be at the door, not only in the helper."""

    def test_staging_refuses_a_label_that_is_a_path(self) -> None:
        from backend.db.engine import get_session
        from backend.services.data_builder import DataBuilderError
        from backend.services.data_periods import stage

        with get_session() as session, pytest.raises(DataBuilderError) as raised:
            stage(session, "ifrs9_staging", content=b"period\nx\n",
                  filename="x.csv", period="../../../../tmp/pwned")
        assert "reporting period label" in str(raised.value)


# ==================================================== who may read and write


@pytest.mark.skipif(not database_available(),
                    reason="the release routes need the platform database")
class TestEveryReleaseRouteNamesWhoMayCallIt:
    """The history route did not, and answered an unauthenticated caller with
    source filenames, checksums, who uploaded and reviewed each version, and
    what the checks found.

    Asserted on the declared dependency rather than on a live 401, because a
    test client is configured to be signed in: a route that lost its
    dependency would still answer 200 in a test and 200 to a stranger in
    production, which is exactly the failure this must catch.
    """

    #: Every route the period lifecycle added, and who may call it. The
    #: paths carry the router's own prefix, without the /api/v1 the app
    #: mounts it under.
    ROUTES = {
        ("POST", "/data-builder/datasets/{name}/periods/upload"):
            "RequireDataSteward",
        ("GET", "/data-builder/datasets/{name}/periods"): "RequireDataSteward",
        ("POST", "/data-builder/periods/{release_id}/review"):
            "RequireDataSteward",
        ("POST", "/data-builder/periods/{release_id}/lock"):
            "RequireDataSteward",
        ("POST", "/data-builder/periods/{release_id}/discard"):
            "RequireDataSteward",
        ("POST", "/data-builder/periods/{release_id}/publish"):
            "RequirePublisher",
    }

    @staticmethod
    def _endpoints():
        """Every route on the Data Builder router, by method and path.

        Read from the router the endpoints are registered on rather than from
        the app: the app wraps each router in a lazy include, so `app.routes`
        knows about forty-three routes and none of these.
        """
        from backend.api.routers.data_builder import router

        found = {}
        for route in router.routes:
            for method in getattr(route, "methods", None) or ():
                found[(method, getattr(route, "path", ""))] = route
        return found

    def test_every_one_of_them_is_registered(self) -> None:
        found = self._endpoints()
        for key in self.ROUTES:
            assert key in found, f"{key[0]} {key[1]} is not registered"

    def test_every_one_of_them_requires_a_principal(self) -> None:
        import inspect

        found = self._endpoints()
        for key in self.ROUTES:
            signature = inspect.signature(found[key].endpoint)
            # `from __future__ import annotations` leaves the annotation as
            # the string "Principal" on some of these, so both forms count.
            named = [
                name for name, parameter in signature.parameters.items()
                if "Principal" in (
                    getattr(parameter.annotation, "__name__", "")
                    or str(parameter.annotation))
            ]
            assert named, f"{key[0]} {key[1]} names nobody who may call it"

    def test_each_one_asks_for_the_right_role(self) -> None:
        """A steward stages, reviews and locks. Publishing is a publisher."""
        import inspect

        from backend.api import permissions

        found = self._endpoints()
        for key, wanted in self.ROUTES.items():
            default = inspect.signature(
                found[key].endpoint).parameters["principal"].default
            assert default is getattr(permissions, wanted), (
                f"{key[0]} {key[1]} does not ask for {wanted}")


# ================================================== an upload has a ceiling


class TestAnUploadIsBounded:
    """An upload route with no size cap is a way to take the process down with
    one request. Every other upload route on this router had one; this one
    was added without it."""

    def test_the_route_applies_the_configured_cap(self) -> None:
        source = Path("backend/api/routers/data_builder.py").read_text()
        route = source.split("async def upload_period(", 1)[1].split(
            "\n@router", 1)[0]
        assert "settings.max_upload_bytes" in route
        assert "REQUEST_ENTITY_TOO_LARGE" in route
