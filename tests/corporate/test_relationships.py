"""
Upstream, downstream and lateral, on groups built by hand. R2 §2.

Built by hand on purpose. The generator produces plenty of groups, but it does
not produce them on demand: to prove that a sister company is found by going
up to the shared owner and back down again, you need a group that HAS a shared
owner and exactly one sibling, and you need to know which one it is. A test
that searched the generated universe for such a shape would pass by luck and
fail when the seed changed.

The direction rules are the whole of §2. `A OWNS B` read from B is a parent
and read from A is a subsidiary — the same row of the same dataset — so a
classifier that got the direction wrong would show a credit officer a parent
where a subsidiary stands, which is the opposite of what they need to know.
"""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from backend.corporate import graphdata
from backend.corporate import relationships as rel


def node(node_id: str, label: str = "", kind: str = "Corporate"
         ) -> dict[str, Any]:
    return {"node_id": node_id, "label": label or node_id, "node_type": kind,
            "detail": ""}


def owns(source: str, target: str, *, pct: float = 60.0,
         votes: float | None = None) -> dict[str, Any]:
    return {"edge_id": f"{source}->{target}", "edge_type": graphdata.OWNS,
            "from_node": source, "to_node": target, "ownership_pct": pct,
            "voting_pct": pct if votes is None else votes,
            "source": "Commercial Registry filing", "confidence": 0.97}


def guarantees(source: str, target: str, *, amount: float = 100.0
               ) -> dict[str, Any]:
    return {"edge_id": f"{source}~{target}", "edge_type": graphdata.PROVIDES,
            "from_node": source, "to_node": target, "amount": amount,
            "source": "Audited group structure note", "confidence": 0.92}


#: PARENT owns CENTRE and SISTER; CENTRE owns CHILD; GUARANTOR guarantees
#: CENTRE. One of each direction, and nothing ambiguous.
FAMILY_NODES = [node("PARENT", "Holding Company"), node("CENTRE", "The Borrower"),
                node("SISTER", "Sister Company"), node("CHILD", "Subsidiary"),
                node("GUARANTOR", "Support Provider")]
FAMILY_EDGES = [owns("PARENT", "CENTRE", pct=80.0),
                owns("PARENT", "SISTER", pct=70.0),
                owns("CENTRE", "CHILD", pct=100.0),
                guarantees("GUARANTOR", "CENTRE", amount=250.0)]


def classify(depth: int = 2) -> dict[str, rel.Related]:
    parties = rel.classify("CENTRE", FAMILY_NODES, FAMILY_EDGES, depth=depth)
    return {p.node_id: p for p in parties}


class TestWhichWayTheRelationshipRuns:
    def test_the_owner_of_this_borrower_is_upstream(self) -> None:
        assert classify()["PARENT"].direction == rel.UPSTREAM

    def test_what_this_borrower_owns_is_downstream(self) -> None:
        assert classify()["CHILD"].direction == rel.DOWNSTREAM

    def test_the_guarantor_is_upstream(self) -> None:
        # Credit support comes from above whether or not it owns a share.
        found = classify()["GUARANTOR"]
        assert found.direction == rel.UPSTREAM
        assert found.relationship == "Guarantor"
        assert found.amount == 250.0

    def test_the_sister_is_lateral_not_a_parent(self) -> None:
        found = classify()["SISTER"]
        assert found.direction == rel.LATERAL
        assert found.depth == 2

    def test_the_sister_names_the_owner_it_is_shared_with(self) -> None:
        # "Sister company" alone is an assertion. Naming the shared owner
        # makes it something a person can check against the filings.
        found = classify()["SISTER"]
        assert "Holding Company" in found.relationship
        assert found.via == ["CENTRE", "PARENT", "SISTER"]

    def test_the_same_edge_reads_both_ways(self) -> None:
        # PARENT->CENTRE and CENTRE->CHILD are the same edge TYPE, and the
        # classification of the two ends is opposite. This is the bug the
        # module exists to prevent.
        found = classify()
        assert found["PARENT"].relationship == "Shareholder"
        assert found["CHILD"].relationship == "Investment"

    def test_a_direct_relationship_is_depth_one(self) -> None:
        found = classify()
        assert found["PARENT"].depth == 1
        assert found["CHILD"].depth == 1

    def test_no_sisters_are_found_at_depth_one(self) -> None:
        # Not a limitation being papered over: at depth 1 the question asked
        # is "who is DIRECTLY related", and a sister is not.
        found = classify(depth=1)
        assert "SISTER" not in found
        assert "PARENT" in found

    def test_the_centre_is_never_one_of_its_own_relations(self) -> None:
        assert "CENTRE" not in classify()


class TestControlAndEconomicsAreNotTheSame:
    def test_a_majority_of_the_votes_is_control(self) -> None:
        parties = rel.classify(
            "CENTRE", [node("OWNER"), node("CENTRE")],
            [owns("OWNER", "CENTRE", pct=30.0, votes=80.0)], depth=1)
        assert parties[0].controls is True

    def test_a_minority_of_the_votes_is_not_control_however_large_the_stake(
            self) -> None:
        # 90% of the economics and 10% of the votes. A dual-class structure,
        # and the officer who reads only the ownership column gets it wrong.
        parties = rel.classify(
            "CENTRE", [node("OWNER"), node("CENTRE")],
            [owns("OWNER", "CENTRE", pct=90.0, votes=10.0)], depth=1)
        assert parties[0].controls is False
        assert parties[0].significant is True

    def test_an_explicit_control_edge_is_control_with_no_percentage(
            self) -> None:
        edge = {"edge_id": "c", "edge_type": graphdata.CONTROLS,
                "from_node": "OWNER", "to_node": "CENTRE"}
        parties = rel.classify("CENTRE", [node("OWNER"), node("CENTRE")],
                               [edge], depth=1)
        assert parties[0].controls is True
        assert parties[0].relationship == "Controlling entity"

    def test_a_small_stake_is_neither_control_nor_significant(self) -> None:
        parties = rel.classify(
            "CENTRE", [node("OWNER"), node("CENTRE")],
            [owns("OWNER", "CENTRE", pct=5.0)], depth=1)
        assert parties[0].controls is False
        assert parties[0].significant is False


class TestExposureAcrossTheGroup:
    @staticmethod
    def _book() -> pd.DataFrame:
        return pd.DataFrame([
            {"borrower_id": "CENTRE", "period": "Q2 2026",
             "exposure_at_default": 100.0},
            {"borrower_id": "SISTER", "period": "Q2 2026",
             "exposure_at_default": 250.0},
            {"borrower_id": "CHILD", "period": "Q2 2026",
             "exposure_at_default": 50.0},
        ])

    def test_only_borrowers_carry_an_exposure(self) -> None:
        parties = rel.classify("CENTRE", FAMILY_NODES, FAMILY_EDGES, depth=2)
        rel.attach_exposure(parties, self._book(), "Q2 2026")
        found = {p.node_id: p for p in parties}
        assert found["SISTER"].is_borrower is True
        assert found["SISTER"].exposure == 250.0
        # A holding company is a node, not a borrower. Marking it rather than
        # defaulting it to zero is the difference between "owes nothing" and
        # "is not a borrower".
        assert found["PARENT"].is_borrower is False
        assert found["PARENT"].exposure is None

    def test_the_group_total_includes_the_borrower_the_screen_is_about(
            self) -> None:
        parties = rel.classify("CENTRE", FAMILY_NODES, FAMILY_EDGES, depth=2)
        rel.attach_exposure(parties, self._book(), "Q2 2026")
        network = rel.Network(centre="CENTRE", centre_label="The Borrower",
                              period="Q2 2026", as_of="2026-06-30",
                              view="group", depth=2, parties=parties,
                              centre_exposure=100.0)
        assert network.group_exposure == 400.0
        assert network.to_dict()["group_borrowers"] == 3

    def test_a_truncated_network_reports_its_total_as_a_floor(self) -> None:
        network = rel.Network(centre="CENTRE", centre_label="x",
                              period="Q2 2026", as_of="2026-06-30",
                              view="group", depth=2, truncated=True)
        assert network.to_dict()["exposure_is_floor"] is True

    def test_a_period_with_no_book_leaves_every_party_unmarked(self) -> None:
        parties = rel.classify("CENTRE", FAMILY_NODES, FAMILY_EDGES, depth=2)
        rel.attach_exposure(parties, self._book(), "Q1 2020")
        assert not any(p.is_borrower for p in parties)


class TestTheShapeItPublishes:
    def test_every_direction_is_present_even_when_empty(self) -> None:
        # A screen that has to branch on whether a direction exists is one
        # that will show "beside" only when something is beside, and a reader
        # cannot tell an empty group from an unbuilt one.
        network = rel.Network(centre="X", centre_label="X", period="Q2 2026",
                              as_of="2026-06-30", view="group", depth=2)
        directions = [g["direction"] for g in network.to_dict()["groups"]]
        assert directions == list(rel.DIRECTIONS)

    def test_every_direction_carries_the_question_it_answers(self) -> None:
        network = rel.Network(centre="X", centre_label="X", period="Q2 2026",
                              as_of="2026-06-30", view="group", depth=2)
        for group in network.to_dict()["groups"]:
            assert group["question"].endswith("?")

    def test_a_party_publishes_both_percentages_separately(self) -> None:
        parties = rel.classify(
            "CENTRE", [node("OWNER"), node("CENTRE")],
            [owns("OWNER", "CENTRE", pct=90.0, votes=10.0)], depth=1)
        shown = parties[0].to_dict()
        assert shown["ownership_pct"] == 90.0
        assert shown["voting_pct"] == 10.0
        assert shown["controls"] is False

    def test_a_missing_percentage_is_none_rather_than_zero(self) -> None:
        # Zero would say "owns nothing"; the guarantee edge carries no
        # ownership at all, which is a different fact.
        parties = rel.classify("CENTRE",
                               [node("G"), node("CENTRE")],
                               [guarantees("G", "CENTRE")], depth=1)
        assert parties[0].ownership_pct is None


class TestAgainstTheRealUniverse:
    @pytest.fixture(scope="class")
    @classmethod
    def network(cls) -> Any:
        from backend.corporate import service

        try:
            period = service.latest_period()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"the corporate lake is not built: {exc}")
        frame = service._load("corporate_ownership_edges")
        holdings = frame[frame["from_node"].astype(str).str.startswith("HOLD-")
                         & frame["to_node"].astype(str).str.startswith("CORP-")]
        if holdings.empty:
            pytest.skip("no holding company owns a borrower in this build")
        counts = holdings.groupby("from_node").size().sort_values(
            ascending=False)
        child = holdings[holdings["from_node"] == counts.index[0]][
            "to_node"].iloc[0]
        return service.relationship_network(str(child), period, depth=2)

    def test_a_borrower_under_a_holding_company_has_an_owner_above_it(
            self, network: Any) -> None:
        assert network.by_direction(rel.UPSTREAM), \
            "a borrower owned by a holding company shows nothing above it"

    def test_its_siblings_are_beside_it_rather_than_above(self,
                                                          network: Any) -> None:
        beside = network.by_direction(rel.LATERAL)
        assert beside, "a holding company with several subsidiaries has no sisters"
        assert all(p.depth == 2 for p in beside)

    def test_the_group_exposure_is_at_least_the_borrower_s_own(
            self, network: Any) -> None:
        if network.centre_exposure is None:
            pytest.skip("the centre is not on the book in this period")
        assert network.group_exposure >= network.centre_exposure

    def test_every_party_says_what_it_is(self, network: Any) -> None:
        for party in network.parties:
            assert party.relationship.strip(), \
                f"{party.node_id} is in the group with no stated relationship"
