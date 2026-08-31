"""What the analyst may do to the data, and what it cannot. §4.

The strongest claim in this suite is a negative one, and it is structural
rather than defensive: the analytical IR has no verb for a write. There is no
INSERT in `OpType`, no UPDATE, no DROP, no COPY, no ATTACH. A model cannot
emit one because there is nothing to emit it into — it names a tool and passes
typed arguments, and CreditProbe builds the plan.

That is worth a test rather than a comment, because the alternative
architecture — let the model write SQL, refuse the dangerous strings — is what
every injection advisory of the last twenty years is about, and the day
somebody adds a tool taking a query string is the day this suite should fail.
"""

from __future__ import annotations

import pytest

from backend.analyst import safety, tools
from backend.analyst.safety import Principal, Refused


class TestTheLanguageHasNoWriteVerb:

    def test_the_ir_cannot_express_a_write(self):
        from backend.runtime.ir import OpType

        spelled = {member.value.upper() for member in OpType}
        for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
                     "TRUNCATE", "COPY", "ATTACH", "INSTALL", "LOAD", "GRANT",
                     "REVOKE", "MERGE", "REPLACE", "VACUUM"):
            assert verb not in spelled, (
                f"OpType now spells {verb}. The analyst's safety argument is "
                "that the language has no write verb; it now has one.")

    def test_every_allowed_operation_is_a_real_one(self):
        """The allow-list cannot drift away from the IR it describes."""
        from backend.runtime.ir import OpType

        spelled = {member.value for member in OpType}
        unknown = safety.ALLOWED_OPERATIONS - spelled
        assert not unknown, f"the allow-list names operations that do not exist: {unknown}"

    def test_no_tool_accepts_a_query_string(self):
        """The day one does, this fails, which is the day to think about it."""
        suspicious = {"sql", "query", "statement", "expression", "raw"}
        for tool in tools.REGISTRY:
            named = set(tool.arguments) & suspicious
            assert not named, (
                f"{tool.name} takes {named}. A tool taking a query string "
                "needs safety.refuse_writes applied to it and a test here.")


class TestTheBeltBesideTheBraces:
    """`refuse_writes` exists for the tool nobody has written yet."""

    @pytest.mark.parametrize("text", [
        "DROP TABLE portfolio_facility",
        "delete from facilities where 1=1",
        "SELECT 1; TRUNCATE corporate_ifrs9",
        "ATTACH '/tmp/other.db'",
        "INSTALL httpfs",
        "copy facilities to '/tmp/out.csv'",
    ])
    def test_a_write_is_refused(self, text):
        with pytest.raises(Refused):
            safety.refuse_writes(text)

    @pytest.mark.parametrize("text", [
        "read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('https://elsewhere/x.parquet')",
        "../../etc/shadow",
        "file:///etc/hosts",
    ])
    def test_reaching_outside_the_lake_is_refused(self, text):
        with pytest.raises(Refused):
            safety.refuse_writes(text)

    @pytest.mark.parametrize("text", [
        "borrowers whose leverage increased",
        "Al Rajhi Contracting 4471",
        "Q2 2026",
        "utilisation_pct",
    ])
    def test_an_ordinary_argument_passes(self, text):
        """The counter-test. A guard that refuses borrower names is a guard
        somebody switches off."""
        safety.refuse_writes(text)


class TestAToolCannotBeBypassed:

    def test_an_unknown_tool_is_refused_by_name(self, analyst):
        found = tools.call(analyst, "read_the_database", {})
        assert found.refused
        assert "not a governed tool" in found.refused

    def test_a_missing_required_argument_is_refused(self, analyst):
        found = tools.call(analyst, "describe_dataset", {})
        assert found.refused
        assert "dataset" in found.refused

    def test_a_field_the_dataset_does_not_have_is_refused_by_name(
            self, analyst):
        """Not dropped. Silently ignoring a condition answers a different
        question from the one that was asked."""
        found = tools.call(analyst, "query_dataset", {
            "dataset": "portfolio_facility",
            "where": [{"field": "secret_score", "op": "gt", "value": 1}]})
        assert found.refused
        assert "secret_score" in found.refused

    def test_a_comparison_outside_the_governed_set_is_refused(self, analyst):
        found = tools.call(analyst, "query_dataset", {
            "dataset": "portfolio_facility",
            "where": [{"field": "ead", "op": "regex", "value": ".*"}]})
        assert found.refused
        assert "regex" in found.refused

    def test_an_aggregate_outside_the_governed_set_is_refused(self, analyst):
        found = tools.call(analyst, "aggregate_dataset", {
            "dataset": "portfolio_facility", "group_by": ["sector"],
            "measures": [{"function": "stddev_samp", "field": "ead"}]})
        assert found.refused
        assert "stddev_samp" in found.refused

    def test_a_dataset_outside_the_principals_scope_is_invisible(self):
        """Absent from discovery, not listed-and-refused.

        A model told a dataset exists will spend turns trying to reach it, and
        the refusal itself says something about a book the principal may not
        see.
        """
        narrow = Principal(user_id=3, role="ANALYST",
                           datasets=frozenset({"portfolio_facility"}))
        listed = tools.call(narrow, "list_datasets", {})
        names = {row["dataset"] for row in listed.rows}
        assert names == {"portfolio_facility"}

        refused = tools.call(narrow, "describe_dataset",
                             {"dataset": "corporate_ifrs9"})
        assert refused.refused
        assert "not a governed dataset" in refused.refused

    def test_a_join_with_no_declared_relationship_is_refused(self, analyst):
        """A join CreditProbe has not declared is not one it will make."""
        found = tools.call(analyst, "join_governed_datasets", {
            "left": "portfolio_facility",
            "right": "retail_application_scorecard_monthly_validation"})
        assert found.refused
        assert "relationship" in found.refused.lower()

    def test_a_declared_join_is_made_on_the_declared_key(self, analyst):
        found = tools.call(analyst, "join_governed_datasets", {
            "left": "portfolio_facility", "right": "facility_delinquency",
            "limit": 3})
        if found.refused:
            pytest.skip(f"no declared relationship here: {found.refused}")
        assert found.total_rows > 0
        assert "account_id" in found.purpose


class TestTheResultIsBounded:

    def test_a_tool_cannot_return_more_than_the_ceiling(self, analyst):
        found = tools.call(analyst, "query_dataset", {
            "dataset": "portfolio_facility", "limit": 100_000})
        assert found.total_rows <= safety.MAX_TOOL_ROWS

    def test_the_model_sees_fewer_rows_than_the_result_holds(self, analyst):
        found = tools.call(analyst, "query_dataset", {
            "dataset": "portfolio_facility", "limit": 200})
        assert len(found.rows) <= safety.MAX_ROWS_TO_MODEL
        assert found.total_rows >= len(found.rows)

    def test_every_analysis_plan_carries_a_deterministic_order(self, analyst):
        """§11. Two borrowers on the same figure must not come back in
        whichever order the engine felt like."""
        found = tools.call(analyst, "rank_entities", {
            "dataset": "portfolio_facility", "entity": "sector",
            "measure": "ead", "top": 5})
        assert not found.refused, found.refused
        sorts = [op for op in found.plan["operations"] if op["op"] == "SORT"]
        assert sorts, "the plan has no SORT"
        assert len(sorts[-1]["params"]["by"]) >= 2, (
            "the sort has no tie-break")

    def test_the_same_call_twice_returns_the_same_rows(self, analyst):
        first = tools.call(analyst, "rank_entities", {
            "dataset": "portfolio_facility", "entity": "sector",
            "measure": "ead", "top": 10})
        second = tools.call(analyst, "rank_entities", {
            "dataset": "portfolio_facility", "entity": "sector",
            "measure": "ead", "top": 10})
        assert first.hash() == second.hash()


class TestPermission:

    def test_a_role_gets_only_the_tools_it_may_use(self, viewer):
        described = {t["name"] for t in tools.describe_all(viewer)}
        for tool in tools.REGISTRY:
            if viewer.may(tool.capability):
                assert tool.name in described
            else:
                assert tool.name not in described

    def test_a_capability_the_role_lacks_is_refused(self):
        nobody = Principal(user_id=9, role="NOT_A_ROLE")
        assert not nobody.capabilities
        found = tools.call(nobody, "query_dataset",
                           {"dataset": "portfolio_facility"})
        assert found.refused
        assert "may not use" in found.refused

    def test_the_check_is_before_the_handler(self):
        """A refusal that happened after the query ran is not a refusal."""
        nobody = Principal(user_id=9, role="NOT_A_ROLE")
        found = tools.call(nobody, "query_dataset",
                           {"dataset": "portfolio_facility"})
        assert found.rows == []
        assert found.total_rows == 0
