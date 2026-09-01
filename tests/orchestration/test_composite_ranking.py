"""Composite risk concepts, and the grain a borrower question keeps.

The defect
-----------
    "Which borrowers have the strongest evidence of liquidity stress?
     Consider cash balances, working-capital movements, short-term debt,
     utilisation, repayment patterns, interest burden and upcoming
     maturities."

came back as one row: the portfolio's utilisation, and how it moved between
two quarters. A question naming a population, a judgement and seven kinds of
evidence was answered with one number about none of them.

Four mechanisms had to fail together, and each is pinned separately below so
that a fix to one which quietly undoes another fails here rather than in front
of a client.
"""

from __future__ import annotations

import pytest

Q5 = ("Which borrowers have the strongest evidence of liquidity stress? "
      "Consider cash balances, working-capital movements, short-term debt, "
      "utilisation, repayment patterns, interest burden and upcoming "
      "maturities.")

#: §6's list, plus Q5 itself. Every one of these is a question about WHICH
#: BORROWERS, phrased the way a credit officer would say it out loud rather
#: than the way the catalogue names its columns.
BORROWER_QUESTIONS = (
    Q5,
    "Which companies are running into liquidity trouble?",
    "Who is beginning to run short of cash?",
    "Which borrowers are drawing more heavily because they are under "
    "financial pressure?",
    "Rank the customers showing the strongest liquidity warning signs.",
    "Who has both rising utilisation and weakening debt-service capacity?",
    "Which names look most vulnerable to a liquidity squeeze?",
)


# ---------------------------------------------------------------------------
# 1. The population grain, which nothing in an explanation clause may override.
# ---------------------------------------------------------------------------


class TestABorrowerQuestionStaysABorrowerQuestion:
    """§1: "which borrowers", "which names", "who", "rank borrowers"."""

    @pytest.mark.parametrize("question", BORROWER_QUESTIONS)
    def test_the_requested_grain_is_the_borrower(self, question):
        from backend.orchestration import grain as gr

        want = gr.requested(question)
        assert want.grain == gr.CUSTOMER, (
            f"{question!r} was read as {want.grain}: {want.because}")
        assert want.explicit, (
            "the grain was inferred from the source rather than read from the "
            "question, so nothing downstream is obliged to honour it")

    def test_who_is_a_borrower_word(self):
        """The one that was missing.

        "Who has both rising utilisation and weakening debt-service capacity?"
        names no noun at all, fell through to the source's own grain, and
        answered with five hundred facility rows. There is no reading of "who"
        that means a facility or the whole book.
        """
        from backend.orchestration import grain as gr

        assert gr.requested("Who is under the most pressure?").grain == \
            gr.CUSTOMER

    def test_an_explicit_facility_noun_still_wins(self):
        """So "who" cannot have become a blanket override.

        `_FACILITY_WORDS` is tested before the customer words, and
        "facilities whose utilisation rose" is a facility question with a
        relative pronoun in it.
        """
        from backend.orchestration import grain as gr

        assert gr.requested(
            "Which facilities whose utilisation rose are on watch?"
        ).grain == gr.FACILITY

    def test_a_portfolio_question_is_still_a_portfolio_question(self):
        from backend.orchestration import grain as gr

        assert gr.requested(
            "Show days past due and the NPL ratio for the portfolio."
        ).grain == gr.PORTFOLIO

    def test_the_planner_reads_grain_from_one_place(self):
        """`analysis_planner._grain` used to carry its own copy of the
        borrower vocabulary, and the two drifted: `grain` learned "who" and it
        did not. Two lists of borrower words is one list too many.
        """
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration import grain as gr

        for question in BORROWER_QUESTIONS:
            assert ap._grain(None, question, "portfolio_facility") == \
                gr.CUSTOMER, question


# ---------------------------------------------------------------------------
# 2. The composite itself.
# ---------------------------------------------------------------------------


class TestTheGovernedComposite:
    """"Liquidity stress" is not a column, and the catalogue can still answer
    it: eight published fields on the facility position are exactly what a
    credit officer would look at."""

    @staticmethod
    def _found(question=Q5):
        from backend.data_access import get_catalog
        from backend.orchestration import composites as cmp

        return cmp.find(question, get_catalog())

    @pytest.mark.parametrize("question", BORROWER_QUESTIONS[:5] +
                             (BORROWER_QUESTIONS[6],))
    def test_the_liquidity_phrasings_all_resolve(self, question):
        assert self._found(question) is not None, question

    def test_an_unrelated_question_resolves_to_no_composite(self):
        """The pattern must not be a synonym for "credit question"."""
        for question in ("What is total exposure by sector at Q2 2026?",
                         "Which borrowers moved from Stage 1 to Stage 2?",
                         "Show the top 5 sectors by EAD."):
            assert self._found(question) is None, question

    def test_every_signal_reads_a_field_the_catalogue_carries(self):
        from backend.data_access import get_catalog

        catalogue = get_catalog()
        found = self._found()
        assert found is not None
        for signal in found.available:
            fields = set(catalogue.dataset(signal.dataset).fields)
            for column in signal.columns:
                assert column in fields, (
                    f"{signal.key} reads {signal.dataset}.{column}, which the "
                    f"catalogue does not carry")

    def test_the_dimensions_it_used_are_named(self):
        found = self._found()
        assert found is not None
        for wanted in ("facility utilisation", "utilisation movement",
                       "delinquency / arrears", "payment behaviour",
                       "debt-service capacity", "covenant pressure",
                       "watchlist status"):
            assert wanted in found.dimensions, wanted

    def test_what_the_catalogue_cannot_supply_is_named_too(self):
        """§3: state specifically what cannot be computed.

        Four of the seven dimensions Q5 asks for are genuinely not in the
        book. Answering on the other three and saying so about none of them is
        the more dangerous failure, because the answer looks complete.
        """
        found = self._found()
        assert found is not None
        missing = " ".join(found.unavailable).lower()
        for wanted in ("cash", "working-capital", "short-term debt",
                       "maturities"):
            assert wanted in missing, f"{wanted!r} is not declared unavailable"

    def test_a_composite_with_one_signal_is_refused(self):
        """One signal is not a composite — it is that measure under a name
        that promises more, which is the substitution this exists to stop."""
        from backend.orchestration import composites as cmp

        thin = cmp.Resolved(composite=cmp.LIQUIDITY_STRESS,
                            available=(cmp.LIQUIDITY_STRESS.signals[0],),
                            missing=cmp.LIQUIDITY_STRESS.signals[1:])
        assert not thin.usable

    def test_a_signal_declares_its_threshold_in_words(self):
        """A threshold nobody can read is a weight, and a weight needs an
        owner."""
        for signal in cmp_signals():
            assert signal.sentence(), signal.key
            assert signal.field in signal.sentence()


def cmp_signals():
    from backend.orchestration import composites as cmp

    return cmp.LIQUIDITY_STRESS.signals


# ---------------------------------------------------------------------------
# 3. The plan it builds.
# ---------------------------------------------------------------------------


class TestTheCompositePlan:

    @staticmethod
    def _build(question=Q5):
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration import context as ctx
        from backend.orchestration.capability import Reading

        return ap.plan(Reading(intent="ANALYSIS", objective=question),
                       ctx.retrieve(question), question=question)

    def test_it_is_a_ranking_at_borrower_grain(self):
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration import grain as gr

        build = self._build()
        assert build.shape == ap.RANKING
        assert build.grain == gr.CUSTOMER

    def test_it_is_a_ranking_and_not_a_cohort(self):
        """A cohort requires every condition at once. Eight conditions over
        this book leave nobody, which is a true answer to a question nobody
        asked. "Strongest evidence" ranks the population."""
        build = self._build()
        assert not build.conditions, (
            "the composite was planned as a filter, so a borrower missing one "
            "of eight signals drops off the answer entirely")

    def test_the_grain_contract_holds(self):
        from backend.orchestration import grain as gr

        contract = gr.contract_of(self._build())
        assert contract is not None
        assert contract.ok
        assert contract.got == gr.CUSTOMER

    def test_one_signal_column_per_signal_and_a_count_over_them(self):
        build = self._build()
        meta = (build.plan or {}).get("meta") or {}
        flags = list(meta.get("signal_columns") or [])
        assert len(flags) == len(meta["composite"]["signals"])
        ops = {op["op"] for op in build.plan["operations"]}
        assert {"SCAN", "DERIVE", "GROUP", "SORT", "LIMIT"} <= ops

    def test_a_borrower_counts_each_problem_once(self):
        """`max` and not `sum` over the facilities.

        A borrower with the same problem on four lines has one problem.
        Summing would rank it above a borrower with four different ones, and
        the thing being measured is breadth of evidence.
        """
        build = self._build()
        group = next(op for op in build.plan["operations"]
                     if op["op"] == "GROUP")
        for aggregate in group["params"]["aggregates"]:
            if str(aggregate["as"]).startswith("signal_"):
                assert aggregate["function"] == "max", aggregate

    def test_the_ranking_is_by_evidence_then_size(self):
        build = self._build()
        order = next(op for op in build.plan["operations"]
                     if op["op"] == "SORT")["params"]["by"]
        assert order[0]["column"].endswith("_signals")
        assert order[0]["direction"] == "desc"

    def test_the_plan_carries_everything_the_trace_needs(self):
        """§5: population, evidence dimensions, periods, calculations,
        unavailable dimensions, ranking logic."""
        build = self._build()
        meta = (build.plan or {}).get("meta") or {}
        composite = meta.get("composite") or {}
        assert composite.get("signals")
        assert composite.get("dimensions")
        assert composite.get("unavailable")
        assert composite.get("ranking")
        assert composite.get("means")
        assert composite.get("dataset")
        assert build.period
        # Every operation says what it does, in words.
        for op in build.plan["operations"]:
            assert op.get("label"), op["id"]

    def test_the_unavailable_dimensions_reach_the_answer(self):
        build = self._build()
        said = " ".join(build.warnings).lower()
        assert "cash" in said and "working-capital" in said

    def test_a_stated_count_is_honoured(self):
        build = self._build(
            "Rank the top 10 customers showing liquidity stress.")
        assert build.top_n == 10


# ---------------------------------------------------------------------------
# 4. The vocabulary gaps that fed the defect.
# ---------------------------------------------------------------------------


class TestTheVocabularyGaps:

    def test_debt_service_capacity_is_dscr(self):
        """It resolved to nothing, so "rising utilisation AND weakening
        debt-service capacity" ran on utilisation alone."""
        import re

        from backend.orchestration.concepts import CONCEPTS

        for phrase in ("debt-service capacity", "capacity to service its debt",
                       "debt service coverage", "DSCR"):
            found = {c.id for c in CONCEPTS
                     if re.search(c.pattern, phrase, re.IGNORECASE)}
            assert "dscr" in found, phrase

    def test_capacity_alone_is_not_dscr(self):
        """So the widening cannot match every sentence with "capacity" in
        it."""
        import re

        from backend.orchestration.concepts import CONCEPTS

        found = {c.id for c in CONCEPTS
                 if re.search(c.pattern, "the sector capacity", re.IGNORECASE)}
        assert "dscr" not in found

    def test_a_composite_question_is_within_the_governed_universe(self):
        """The coverage gate refused these outright: `liquidity`, `trouble`
        and `companies` are none of them column names, so the token scan
        concluded the bank had published nothing on the subject. It has."""
        from backend.orchestration import coverage

        for question in BORROWER_QUESTIONS:
            assert coverage.check(question).covered, question

    def test_something_genuinely_absent_is_still_refused(self):
        """So the coverage exemption cannot have become "always covered"."""
        from backend.orchestration import coverage

        assert not coverage.check("Which CEOs resigned last quarter?").covered

    def test_ordinary_english_is_not_corrected_into_a_governed_term(self):
        """"run short of cash" became "run SORT of cash" — `sort` is governed,
        `short` is not, and they are one letter apart. The question then
        described nothing the catalogue held."""
        from backend.orchestration import spelling

        for question in ("Who is beginning to run short of cash?",
                         "Which names look most vulnerable to a squeeze?"):
            assert not spelling.normalise(question).changes, question

    def test_a_real_typo_is_still_corrected(self):
        """The corrector still earns its place."""
        from backend.orchestration import spelling

        fixed = spelling.normalise(
            "Show me the five largest Real Estste customers by EAD.")
        assert ("Estste", "estate") in fixed.changes


# ---------------------------------------------------------------------------
# 5. Through the real route, on the real book.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


def _ask(client, question):
    reply = client.post("/api/v1/ask", json={"question": question},
                        headers={"X-IPM-Role": "ANALYST"})
    assert reply.status_code == 200, reply.text
    return reply.json()


class TestWhatTheUserSees:
    """§7's manual check, as a test. The suite was green while this question
    returned one portfolio number, so the route is the thing to assert on."""

    @pytest.mark.parametrize("question", BORROWER_QUESTIONS)
    def test_every_phrasing_returns_borrowers(self, client, question):
        body = _ask(client, question)
        assert body.get("status") == "succeeded", (
            f"{question!r} → {body.get('status')}: "
            f"{(body.get('narrative') or {}).get('direct_answer')}")

        rows = ((body.get("steps") or [{}])[0].get("result") or {}).get("rows")
        assert rows, "no rows"
        assert "customer_id" in rows[0], (
            f"answered at the wrong grain — the first row is keyed on "
            f"{sorted(rows[0])[:4]}")
        assert len(rows) > 1, (
            "a question about WHICH BORROWERS came back as a single row, "
            "which is the defect this file exists for")

    def test_the_answer_says_what_the_leading_number_is(self, client):
        """"The 25 largest customers by the measure" is what the generic
        ranking sentence produced: a count of signals under a heading that
        calls it a measure and does not name it."""
        body = _ask(client, Q5)
        direct = ((body.get("narrative") or {}).get("direct_answer") or "")
        assert "signal" in direct.lower(), direct
        assert "the measure" not in direct.lower(), direct

    def test_the_leading_borrower_has_its_evidence_itemised(self, client):
        """A count nobody can decompose is a score, and a score needs an
        owner. The signals that fired are named."""
        body = _ask(client, Q5)
        findings = " ".join(
            f.get("text", "")
            for f in ((body.get("narrative") or {}).get("findings") or []))
        assert "utilisation" in findings.lower() or \
               "arrears" in findings.lower(), findings

    def test_the_answer_states_what_it_could_not_compute(self, client):
        body = _ask(client, Q5)
        said = " ".join((body.get("narrative") or {}).get("caveats") or [])
        assert "cash" in said.lower(), said

    def test_no_figure_in_the_answer_is_ungrounded(self, client):
        """The composite's thresholds are declared on the plan and shown on
        the Trace, so quoting one is not an invented figure — but the check
        must still be running."""
        body = _ask(client, Q5)
        said = " ".join((body.get("narrative") or {}).get("caveats") or [])
        assert "could not be traced" not in said, said

    def test_the_ranking_is_ordered_by_evidence(self, client):
        body = _ask(client, Q5)
        rows = ((body.get("steps") or [{}])[0].get("result") or {})["rows"]
        column = next(c for c in rows[0] if c.endswith("_signals"))
        counts = [int(r[column]) for r in rows]
        assert counts == sorted(counts, reverse=True), counts
        assert counts[0] >= 2, (
            "the leading borrower shows fewer than two signals, so the "
            "ranking is not finding the evidence it claims to")

    def test_a_borrower_row_carries_the_signals_behind_its_score(self, client):
        body = _ask(client, Q5)
        rows = ((body.get("steps") or [{}])[0].get("result") or {})["rows"]
        flags = [c for c in rows[0] if c.startswith("signal_")]
        assert len(flags) >= 2
        column = next(c for c in rows[0] if c.endswith("_signals"))
        # The count is the sum of the flags, checkable by eye against the row.
        assert int(rows[0][column]) == sum(int(rows[0][f]) for f in flags)


class TestAPeriodIsNotAThreshold:
    """"over the last four REPORTING periods" put a 4 on every condition.

    The guard that stops a length of time being read as a magnitude looked for
    the time unit immediately after the number. One adjective — "reporting" —
    was enough to slip past it, so "leverage has increased, EBITDA margins
    have declined and debt-service capacity has weakened over the last four
    reporting periods" acquired "more than 4" on all three, plus "more than
    4%" on headroom and "more than 4x" on DSCR. A question about four
    quarters of history became a question about a magnitude nobody named.
    """

    @staticmethod
    def _magnitude(fragment):
        from backend.orchestration.semantics import find_movement

        found = find_movement(fragment)
        return getattr(found, "magnitude", None) or getattr(found, "value", 0)

    def test_a_modifier_between_the_number_and_the_unit_is_allowed(self):
        for fragment in (
            "leverage has increased over the last four reporting periods",
            "ECL rose over the last three calendar quarters",
            "utilisation rose over two fiscal years",
        ):
            assert not self._magnitude(fragment), fragment

    def test_a_real_magnitude_is_still_read(self):
        """So the widened guard cannot have swallowed every threshold."""
        assert self._magnitude("ECL rose more than 20%") == 20.0
        assert self._magnitude("headroom fell more than 15 percent") == 15.0

    def test_the_acceptance_question_gets_its_conditions_unqualified(self):
        """Q3, through the planner: five conditions, none of them carrying a
        threshold the question did not state."""
        from backend.orchestration import analysis_planner as ap
        from backend.orchestration import context as ctx
        from backend.orchestration.capability import Reading

        question = (
            "Find borrowers whose leverage has increased, EBITDA margins have "
            "declined and debt-service capacity has weakened over the last "
            "four reporting periods. Which of these also have covenant "
            "pressure or negative rating migration?")
        build = ap.plan(Reading(intent="ANALYSIS", objective=question),
                        ctx.retrieve(question), question=question)
        assert build.conditions, "the conditions were lost entirely"
        for condition in build.conditions:
            assert not getattr(condition, "value", 0), (
                f"{condition} carries a threshold the question did not state")
