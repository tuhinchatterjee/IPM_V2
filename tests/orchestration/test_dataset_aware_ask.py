"""Ask CreditProbe, about CreditProbe's own data.

Three questions and a thread:

    "What datasets do you have?"      every dataset, by domain, frequency-aware
    "Tell me about Corporate IFRS 9"  one dataset: overview, profile, real rows
    "Show Q1 2025"                    that dataset, at that period

Nothing here asserts a row count or a total. The catalogue changes whenever a
steward publishes, and a test that pinned "seventy-seven datasets" would fail
on the next publication while proving nothing about whether the product read
its own catalogue. What is asserted is the CONTRACT: the answer is derived from
the live catalogue, it says how often each dataset publishes and over what, it
profiles a field the way that field's kind deserves, and the thread keeps the
dataset and the period between turns.
"""

from __future__ import annotations

import pytest

from backend.metadata import frequency as fq
from backend.metadata import service as ms
from backend.orchestration import catalogue_answers as cat

# ------------------------------------------------------------- frequency


class TestHowOftenADatasetPublishes:

    @pytest.mark.parametrize("label,expected", [
        ("Q1 2026", fq.QUARTERLY), ("2026-Q1", fq.QUARTERLY),
        ("2026-03", fq.MONTHLY), ("Mar 2026", fq.MONTHLY),
        ("2026", fq.ANNUAL), ("FY2026", fq.ANNUAL),
        ("2026-03-31", fq.DAILY),
        ("period one", fq.IRREGULAR),
    ])
    def test_a_label_says_what_shape_it_is(self, label, expected) -> None:
        assert fq.shape_of(label) == expected

    def test_a_book_with_no_periods_has_no_frequency(self) -> None:
        """Reference data does not publish unpredictably; it does not publish."""
        assert fq.of([]) == fq.NONE

    def test_labels_that_disagree_are_irregular(self) -> None:
        """A book half quarterly and half annual cannot answer "the latest
        quarter" and must not be asked to."""
        assert fq.of(["Q1 2026", "2025"]) == fq.IRREGULAR

    def test_periods_sort_by_time_and_not_as_text(self) -> None:
        """"Q4 2025" is lexically after "Q2 2026" and chronologically before
        it. The catalogue that took the string maximum reported a period that
        had already passed as the most recent one published."""
        assert fq.latest_of(["Q4 2025", "Q2 2026", "Q1 2024"]) == "Q2 2026"
        assert fq.earliest_of(["Q4 2025", "Q2 2026", "Q1 2024"]) == "Q1 2024"

    def test_coverage_counts_in_the_units_the_book_publishes_in(self) -> None:
        said = fq.coverage(["Q1 2025", "Q2 2025", "Q3 2025"])
        assert "3 quarters" in said and "Q1 2025 to Q3 2025" in said

    def test_a_year_is_four_quarters_and_twelve_months(self) -> None:
        assert fq.steps_for_a_year(fq.QUARTERLY) == 4
        assert fq.steps_for_a_year(fq.MONTHLY) == 12

    def test_the_dataset_carries_its_own_frequency(self) -> None:
        found = ms.dataset("ifrs9_staging")
        assert found.frequency == fq.QUARTERLY
        assert found.period_word == "quarter"
        assert found.first_period and found.latest_period
        assert "quarters" in found.coverage


# ------------------------------------------------------- naming a dataset


class TestWhichDatasetASentenceNames:

    def test_a_technical_id_however_it_is_punctuated(self) -> None:
        for asked in ("Tell me about ifrs9_staging",
                      "Tell me about IFRS9 staging",
                      "open ifrs9staging"):
            assert cat.resolve(asked).name == "ifrs9_staging"

    def test_a_domain_and_a_grain_together(self) -> None:
        """The catalogue gives two IFRS 9 datasets near-identical names. The
        grain is the whole of what tells them apart, and neither "facility
        IFRS 9" nor "corporate IFRS 9" is a name the catalogue holds."""
        assert cat.resolve("Show me the Facility IFRS 9 dataset").name == \
            "ifrs9_staging"
        assert cat.resolve("Tell me about Corporate IFRS 9").name == \
            "corporate_ifrs9"

    def test_a_sentence_naming_no_dataset_resolves_to_nothing(self) -> None:
        assert cat.resolve("What is total ECL?") is None
        assert cat.resolve("Which customers are on the watchlist?") is None


class TestWhichQuestionThisIs:

    @pytest.mark.parametrize("asked", [
        "What datasets do you have?", "What data do you hold?",
        "List the datasets.", "Show me the data catalogue",
    ])
    def test_the_whole_catalogue(self, asked) -> None:
        assert cat.wants_catalogue(asked)

    def test_an_analytical_question_is_not_a_catalogue_question(self) -> None:
        assert not cat.wants_catalogue("What is total ECL?")
        assert not cat.wants_catalogue("Which sectors deteriorated?")

    @pytest.mark.parametrize("asked,expected", [
        ("Show Q1 2025", "Q1 2025"), ("Q1 2025", "Q1 2025"),
        ("Open Q4 2024.", "Q4 2024"),
        ("What is total ECL at Q1 2025?", ""),
        ("Which sectors deteriorated?", ""),
    ])
    def test_a_bare_period_is_only_a_bare_period(self, asked, expected) -> None:
        """A period inside a longer question is that question's period, not a
        new subject."""
        assert cat.bare_period(asked) == expected

    @pytest.mark.parametrize("asked,expected", [
        ("Show me 50 rows", 50), ("show me more", cat.PREVIEW_ROWS_MAX),
        ("Show me 500 rows", cat.PREVIEW_ROWS_MAX),
        ("Tell me about ifrs9_staging", cat.PREVIEW_ROWS),
    ])
    def test_how_many_rows_were_asked_for(self, asked, expected) -> None:
        assert cat.rows_wanted(asked) == expected


# ---------------------------------------------------------- the profile


class TestEachFieldIsProfiledAsWhatItIs:
    """Averaging an account number is the single clearest sign that a
    profiler does not know what it is looking at."""

    @pytest.fixture(scope="class")
    @classmethod
    def staging(cls):
        return ms.dataset("ifrs9_staging")

    @pytest.mark.parametrize("field,expected", [
        ("account_id", cat.IDENTIFIER),
        ("customer_id", cat.IDENTIFIER),
        ("ead", cat.AMOUNT),
        ("total_ecl", cat.AMOUNT),
        ("pd_12m_pct", cat.RATE),
        ("lgd_pct", cat.RATE),
        ("ecl_coverage_pct", cat.RATE),
        ("ifrs9_stage", cat.ORDINAL_CLASS),
        ("sector", cat.CATEGORY),
        ("dpd_days", cat.DURATION),
        ("period", cat.DATE),
    ])
    def test_the_kind_is_read_from_what_the_field_means(self, staging, field,
                                                        expected) -> None:
        found = staging.field(field)
        assert found is not None, f"{field} is not in the dataset"
        assert cat.profile_kind(found) == expected

    def test_every_kind_says_what_it_must_never_show(self, staging) -> None:
        """The negative half of each rule is the half that does the work."""
        for kind, rule in cat.PROFILE_RULES.items():
            assert rule["shows"] and rule["never"], kind


class TestTheOverviewIsTheDataAndNotOnlyADescription:

    @pytest.fixture(scope="class")
    @classmethod
    def seen(cls):
        return cat.overview(ms.dataset("ifrs9_staging"))

    def test_it_profiles_every_field(self, seen) -> None:
        assert len(seen.profile) == ms.dataset("ifrs9_staging").field_count

    def test_it_shows_actual_rows(self, seen) -> None:
        assert seen.shown == cat.PREVIEW_ROWS
        assert len(seen.observations) == cat.PREVIEW_ROWS
        assert seen.observation_columns

    def test_an_identifier_is_counted_and_never_averaged(self, seen) -> None:
        row = next(r for r in seen.profile if r["field"] == "account_id")
        assert "distinct" in row["profile"]
        assert "average" not in row["profile"].lower()
        assert "mean" not in row["profile"].lower()

    def test_a_class_is_distributed_and_says_why_not_averaged(self, seen) -> None:
        row = next(r for r in seen.profile if r["field"] == "ifrs9_stage")
        assert "%" in row["profile"]
        assert "no average" in row["profile"].lower()

    def test_a_rate_is_weighted_by_exposure(self, seen) -> None:
        row = next(r for r in seen.profile if r["field"] == "lgd_pct")
        assert "exposure-weighted" in row["profile"]
        assert "total" not in row["profile"].lower()

    def test_an_amount_is_totalled(self, seen) -> None:
        row = next(r for r in seen.profile if r["field"] == "ead")
        assert row["profile"].startswith("total ")

    def test_a_duration_is_banded(self, seen) -> None:
        row = next(r for r in seen.profile if r["field"] == "dpd_days")
        assert "90+" in row["profile"] and "median" in row["profile"].lower()

    def test_it_says_which_period_it_is_showing(self, seen) -> None:
        assert seen.period
        assert seen.period in seen.summary

    def test_a_period_the_dataset_does_not_publish_is_refused(self) -> None:
        out = cat.overview(ms.dataset("ifrs9_staging"), period="Q3 1999")
        assert "does not publish" in out.refusal
        assert not out.observations

    def test_more_rows_on_request_and_never_more_than_the_cap(self) -> None:
        found = ms.dataset("ifrs9_staging")
        assert cat.overview(found, limit=50).shown == 50
        assert cat.overview(found, limit=500).shown == cat.PREVIEW_ROWS_MAX


class TestTheListingIsTheLiveCatalogue:

    @pytest.fixture(scope="class")
    @classmethod
    def rows(cls):
        return cat.catalogue_rows()

    def test_it_lists_what_the_catalogue_holds(self, rows) -> None:
        # Everything readable EXCEPT the scorecard validation datasets, which
        # the general Cockpit may not discover. Listing them here would mean
        # the boundary had failed; leaving the subtraction out would mean this
        # test could no longer tell the difference.
        from backend.scorecard.domains import restricted_datasets

        blocked = restricted_datasets()
        readable = [d for d in ms.datasets()
                    if getattr(d, "readable", True) and d.name not in blocked]
        assert len(rows) == len(readable)
        assert not [r for r in rows if r["dataset"] in blocked]

    def test_it_is_ordered_by_domain(self, rows) -> None:
        domains = [r["domain"] for r in rows]
        assert domains == sorted(domains)

    def test_every_row_says_how_often_it_publishes(self, rows) -> None:
        assert all(r["frequency"] for r in rows)

    def test_a_dated_dataset_says_from_when_to_when_and_how_many(self, rows
                                                                  ) -> None:
        dated = [r for r in rows if r["periods"]]
        assert dated
        for row in dated:
            assert row["from"] != "—" and row["to"] != "—"

    def test_the_sentence_names_the_latest_period_chronologically(self, rows
                                                                   ) -> None:
        said = cat.catalogue_answer(rows)
        latest = fq.latest_of([str(r["to"]) for r in rows if r["periods"]])
        assert latest in said

    def test_reference_data_is_said_to_be_reference_data(self, rows) -> None:
        said = cat.catalogue_answer(rows)
        if any(not r["periods"] for r in rows):
            assert "reference data" in said


# --------------------------------------------------------------- the thread


class TestTheThreadKeepsTheDatasetAndThePeriod:
    """The canonical flow, through the same path a person's question takes.

    The second question inherits nothing and the third inherits everything: a
    reader who has just been shown a dataset and then types a period label
    means that dataset at that period, and asking them which dataset they meant
    is the product not listening.
    """

    @pytest.fixture(scope="class")
    @classmethod
    def thread(cls):
        from backend.orchestration import memory as wm
        from backend.orchestration.executor import answer_investigation

        memory = wm.WorkingMemory()
        turns = []
        for asked in ("What datasets do you have?",
                      "Tell me about Corporate IFRS 9",
                      "Show me the Facility IFRS 9 dataset",
                      "Show Q1 2025",
                      "Show me 50 rows"):
            investigation, answered = answer_investigation(
                asked, persist=False, memory=memory)
            memory = wm.observe(memory, answered, investigation)
            turns.append({
                "asked": asked,
                "status": investigation.status,
                "answer": investigation.narrative.direct_answer or "",
                "package": investigation.to_dict()["package"],
                "datasets": list(memory.datasets),
                "period": memory.current_period,
            })
        return turns

    def test_every_turn_is_answered(self, thread) -> None:
        stuck = [t["asked"] for t in thread if t["status"] != "succeeded"]
        assert not stuck

    def test_the_catalogue_turn_lists_more_than_one_domain(self, thread) -> None:
        assert "domains" in thread[0]["answer"]

    def test_naming_a_dataset_opens_that_dataset(self, thread) -> None:
        assert thread[1]["datasets"][0] == "corporate_ifrs9"
        assert thread[2]["datasets"][0] == "ifrs9_staging"

    def test_a_dataset_turn_is_a_profile_and_its_rows(self, thread) -> None:
        """Two blocks, not one. A profile is a description and a description
        is something a reader has to take on trust."""
        assert thread[1]["package"]["counts"]["analyses"] == 2
        titles = [b["title"] for b in thread[1]["package"]["blocks"]]
        assert any("field by field" in t for t in titles)
        assert any(t.startswith("First ") for t in titles)

    def test_a_bare_period_continues_the_dataset_on_the_table(self, thread
                                                               ) -> None:
        assert thread[3]["datasets"][0] == "ifrs9_staging"
        assert "This is Q1 2025" in thread[3]["answer"]
        assert any("Q1 2025" in b["title"]
                   for b in thread[3]["package"]["blocks"])

    def test_the_period_survives_into_the_next_turn(self, thread) -> None:
        """A follow-up that jumps silently back to the latest period shows a
        reader different rows under the same heading."""
        assert thread[3]["period"] == "Q1 2025"
        assert thread[4]["period"] == "Q1 2025"

    def test_more_rows_means_more_of_the_same_rows(self, thread) -> None:
        last = thread[4]["package"]["blocks"][-1]
        assert last["row_count"] == 50
        assert "Q1 2025" in last["title"]


class TestAnIfrs9ContextSettlesWhichExposureIsMeant:
    """"Which sectors have the highest Stage 2 exposure?" is one of the
    Cockpit's own starter questions, and it came back asking which of three
    exposure measures was meant — a question the sentence had already
    answered."""

    def test_it_answers_rather_than_asking(self) -> None:
        from backend.orchestration import orchestrator

        answered = orchestrator.answer(
            "Which sectors have the highest Stage 2 exposure?",
            use_certified=False)
        assert not answered.clarification
        assert answered.runtime is not None
        assert answered.runtime.row_count > 0

    def test_it_uses_the_exposure_impairment_uses(self) -> None:
        from backend.orchestration import orchestrator

        answered = orchestrator.answer(
            "Which sectors have the highest Stage 2 exposure?",
            use_certified=False)
        match = answered.build.matches[0]
        assert match.field == "ead"

    def test_the_sentence_names_the_measure_that_actually_ran(self) -> None:
        """The concept is labelled "drawn exposure" because that is its
        default. An answer computed from EAD headed "drawn exposure" is the
        right number under the name of a different measure."""
        from backend.orchestration import orchestrator

        answered = orchestrator.answer(
            "Which sectors have the highest Stage 2 exposure?",
            use_certified=False)
        assert answered.build.matches[0].label == "exposure at default"
        assert "drawn" not in (answered.build.summary or "")

    def test_a_bare_exposure_question_still_asks(self) -> None:
        """Settling it from context is not settling it always. With no
        impairment vocabulary in the sentence the three measures still differ
        by material amounts and guessing is worse than asking."""
        from backend.orchestration import orchestrator

        answered = orchestrator.answer("Show me the ten largest exposures.",
                                       use_certified=False)
        assert answered.clarification
