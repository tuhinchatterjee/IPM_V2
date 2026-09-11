"""
Who may read the book, and which methods are offered.

**Thirty-eight GET routes answered a caller with no credential.** Among them
`/api/v1/workspace/investigations`, which returned saved investigations with
their titles and the questions people had asked; `/api/v1/ask/recent`, the
questions asked recently; `/api/v1/catalog` and
`/api/v1/data-builder/datasets/retail_facility_month`, the governed dictionary
and all 546 field definitions; `/api/v1/lenses`; and
`/api/v1/early-warning/taxonomy`, the rulebook.

`/api/v1/metrics` returned 401 correctly, which is the point: the mechanism
worked and these routes had not opted into it. Authentication declared per
handler fails OPEN, and a control that fails open cannot be audited by reading
the code — you have to call every route, which is how this was found.

The rule is inverted now: every path under the API prefix requires a signed-in
caller unless it is named in `PUBLIC_PATHS`, and every name there is something
a signed-OUT browser needs to render its sign-in page.

**And every certified analysis in this product was unrunnable.** All thirty
registered engine analyses read datasets this installation retired. Collateral
Coverage is how it was found: its own trigger question is "How much of the book
is secured?", the orchestrator matched that exact wording, the engine could not
run, and the fallback asked "Which figure should CreditProbe measure?" for a
question the metric catalogue answers one phrasing away.

**And a qualified word matched a bare metric name.** "What is our COLLATERAL
coverage?" was answered "ECL Coverage is 0.77%" — confidently, under a question
about collateral, from a metric this installation publishes and a measure it
does not.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

from backend.retail import profile

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

BACKEND = "http://localhost:8328"

#: What a signed-out caller must never be handed.
BANK_CONTENT = (
    "/api/v1/workspace/investigations",
    "/api/v1/investigations",
    "/api/v1/ask/recent",
    "/api/v1/ask/briefing",
    "/api/v1/catalog",
    "/api/v1/lenses",
    "/api/v1/analyses",
    "/api/v1/projects",
    "/api/v1/data-builder/datasets",
    "/api/v1/data-builder/datasets/retail_facility_month",
    "/api/v1/data-builder/domains",
    "/api/v1/data-builder/tree",
    "/api/v1/early-warning",
    "/api/v1/early-warning/taxonomy",
    "/api/v1/engine/analyses",
    "/api/v1/studio/clarifications",
)


def anonymous(path: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(BACKEND + path, timeout=20) as response:
            return response.status, response.read(2000).decode("utf-8",
                                                               "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read(2000).decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 - no server is not a pass
        pytest.skip(f"the retail backend is not answering: {e}")


class TestTheAPIIsDefaultDeny:
    @pytest.mark.parametrize("path", BANK_CONTENT)
    def test_bank_content_needs_a_signed_in_caller(self, path):
        status, _ = anonymous(path)
        assert status == 401, (
            f"{path} answered {status} to a caller with no credential")

    def test_the_sign_in_page_can_still_load(self):
        for path in ("/api/v1/health", "/api/v1/build", "/api/v1/auth/me",
                     "/api/v1/ai/status", "/api/v1/ask/mode",
                     "/api/v1/demo"):
            status, _ = anonymous(path)
            assert status == 200, (
                f"{path} is needed before anyone has signed in and it "
                f"answered {status}")

    def test_no_route_answers_that_is_not_on_the_allowlist(self):
        """The sweep that found it, kept as the gate."""
        from backend.api.main import PUBLIC_PATHS, _is_public

        try:
            with urllib.request.urlopen(BACKEND + "/openapi.json",
                                        timeout=30) as r:
                paths = json.loads(r.read())["paths"]
        except Exception as e:  # noqa: BLE001
            pytest.skip(f"the retail backend is not answering: {e}")

        open_routes = []
        for path, operations in sorted(paths.items()):
            if "get" not in operations or "{" in path:
                continue
            status, _ = anonymous(path)
            if 200 <= status < 300 and not _is_public(path):
                open_routes.append(path)
        assert open_routes == [], (
            f"{len(open_routes)} route(s) answer without a credential and are "
            f"not on the allowlist: {open_routes}")
        assert len(PUBLIC_PATHS) < 15, (
            "the allowlist is the whole security property; a long one is a "
            "default-allow wearing a different name")


class TestOnlyRunnableMethodsAreOffered:
    def test_no_offered_method_binds_an_engine_that_cannot_read_this_book(self):
        from backend.studio.library import (_engine_can_read_this_book,
                                            _engine_contracts,
                                            _published_datasets,
                                            active_definitions)

        published, contracts = _published_datasets(), _engine_contracts()
        assert published, "the catalogue file could not be read"
        dead = [m.id for m in active_definitions()
                if not _engine_can_read_this_book(m, published, contracts)]
        assert dead == [], (
            f"{len(dead)} method(s) are offered and cannot run: {dead[:8]}")

    def test_the_corporate_engines_are_the_ones_retired(self):
        from backend.studio.library import (_engine_contracts,
                                            _published_datasets)

        published, contracts = _published_datasets(), _engine_contracts()
        unrunnable = [cid for cid, needs in contracts.items()
                      if needs and not all(n in published for n in needs)]
        assert "collateral_coverage" in unrunnable
        assert len(unrunnable) >= 25, (
            "every registered engine analysis reads the corporate book; if "
            "that has changed, this gate needs rewriting rather than relaxing")

    def test_the_library_still_offers_most_of_itself(self):
        from backend.studio.library import active_definitions, all_definitions

        offered, defined = len(active_definitions()), len(all_definitions())
        assert offered > defined * 0.5, (
            f"only {offered} of {defined} methods survive the filter; the "
            "test is retiring more than the corporate book")


class TestAQualifiedWordIsNotABareMetric:
    def test_collateral_coverage_is_not_ECL_coverage(self):
        from backend.orchestration import metric_route

        assert metric_route.read(
            "What is our collateral coverage at August 2026?") is None

    @pytest.mark.parametrize("question,metric_id", [
        ("What is ECL coverage at August 2026?", "retail.ecl_coverage"),
        ("What is the coverage at August 2026?", "retail.ecl_coverage"),
        ("What is Stage 2 coverage at August 2026?", "retail.stage2.coverage"),
        ("Which product has the highest 30+ DPD rate?", "retail.dpd30_rate"),
    ])
    def test_the_metrics_this_book_publishes_still_answer(self, question,
                                                          metric_id):
        from backend.orchestration import metric_route

        routed = metric_route.read(question)
        assert routed is not None and routed.metric_id == metric_id
