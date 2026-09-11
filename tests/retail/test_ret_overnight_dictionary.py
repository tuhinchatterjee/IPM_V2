"""
The governed catalogue, reconciled against the book it describes.

Three hundred and two of `retail_facility_month`'s five hundred and forty-six
columns reached the reader with no definition. What they carried was their own
heading followed by a path into this repository —

    Account inflows 1m SAR. See docs/RETAIL_DATA_DICTIONARY.md.

— and that document is GENERATED from the same registry, so it said the same
sentence back. A bank's data steward does not have this repository at all.

Under the prose was arithmetic. `spec_for` guessed a column's type from its
name; a name ending in nothing recognised was declared `string`. Forty-four
numeric columns were declared that way, `behavioural_score` and `lgd_base` and
every point-in-time PD among them. `_rollup_for` refuses to average a string
and falls back to `max`, so

    "What is the average behavioural score at August 2026?"     754.59

was the HIGHEST score in the book, printed under the word average. The book
says 673.99.

Correcting the types uncovered the defect beneath it. `_ROLLUP` maps a unit to
an aggregation and was written in the CORPORATE catalogue's units — "SAR mn",
"%", "x", "grade", "notches". The retail catalogue publishes points,
probability, ratio, months, SAR, SAR/month and count, and only `days` appears
in both. Everything else missed the table and took the `sum` fallback:

    "What is the average 12-month PD at August 2026?"           476.76
    "What is the average debt burden ratio at August 2026?"  11,811.08

the sums of nineteen thousand probabilities and ratios. And nothing read the
word "average" at all — the sentence's own aggregation was never consulted.

Every assertion below reconciles the CATALOGUE against the PARQUET, or the
ANSWER against pandas. A dictionary checked against the code that wrote it
checks nothing.
"""

from __future__ import annotations

import glob

import pandas as pd
import pytest

from backend.orchestration import analysis_planner as ap
from backend.orchestration import orchestrator
from backend.retail import profile
from backend.retail import schema as sch

pytestmark = pytest.mark.skipif(
    not profile.is_retail(), reason="the corporate profile is active")

LATEST = "2026-08"


def _kind(dtype) -> str:
    text = str(dtype)
    if text.startswith(("int", "uint")):
        return "integer"
    if text.startswith("float"):
        return "number"
    if text == "bool":
        return "boolean"
    return "string"


@pytest.fixture(scope="module")
def published() -> pd.DataFrame:
    paths = glob.glob("data/retail/analytics/retail_facility_month/"
                      f"reporting_month={LATEST}/*.parquet")
    if not paths:
        pytest.skip("the shipped retail lake has not been built")
    return pd.read_parquet(paths[0])


@pytest.fixture(scope="module")
def catalogue_fields() -> dict[str, dict]:
    from backend.orchestration import context as governed_context

    datasets = {d.name: d for d in governed_context.all_datasets()}
    if "retail_facility_month" not in datasets:
        pytest.skip("the retail catalogue is not loaded")
    return {f["name"]: f
            for f in datasets["retail_facility_month"].fields}


class TestEveryFieldIsDefined:
    def test_no_field_points_the_reader_at_this_repository(
            self, catalogue_fields):
        pointing = sorted(n for n, f in catalogue_fields.items()
                          if "docs/" in str(f.get("definition") or ""))
        assert pointing == [], (
            f"{len(pointing)} fields send the reader to a path inside this "
            f"repository instead of defining themselves: {pointing[:6]}")

    def test_no_definition_merely_restates_the_heading(self, catalogue_fields):
        restating = []
        for name, field in catalogue_fields.items():
            definition = " ".join(str(field.get("definition") or "").split())
            heading = " ".join(str(field.get("business_name") or "").split())
            if not definition or definition.rstrip(".") == heading.rstrip("."):
                restating.append(name)
        assert restating == [], (
            f"{len(restating)} fields define themselves by their own name: "
            f"{restating[:6]}")

    def test_every_definition_is_a_sentence(self, catalogue_fields):
        too_short = sorted(n for n, f in catalogue_fields.items()
                           if len(str(f.get("definition") or "").split()) < 4)
        assert too_short == [], f"not definitions: {too_short[:6]}"


class TestTheDeclaredTypeIsTheTypeTheBookPublishes:
    def test_no_numeric_column_is_declared_text(self, published,
                                                catalogue_fields):
        wrong = [(c, catalogue_fields[c].get("type"))
                 for c in published.columns
                 if c in catalogue_fields
                 and _kind(published[c].dtype) in ("integer", "number")
                 and catalogue_fields[c].get("type") not in ("integer",
                                                             "number")]
        assert wrong == [], (
            "a numeric column declared text cannot be summed or averaged, so "
            f"the planner falls back to max: {wrong[:8]}")

    def test_no_text_column_is_declared_numeric(self, published,
                                                catalogue_fields):
        wrong = [(c, catalogue_fields[c].get("type"))
                 for c in published.columns
                 if c in catalogue_fields
                 and _kind(published[c].dtype) == "string"
                 and catalogue_fields[c].get("type") in ("integer", "number")]
        assert wrong == []

    def test_the_schema_and_the_catalogue_agree(self, published,
                                                catalogue_fields):
        """What `spec_for` says and what was published must be one thing."""
        disagreeing = [(c, sch.spec_for(c).data_type,
                        catalogue_fields[c].get("type"))
                       for c in published.columns if c in catalogue_fields
                       and sch.spec_for(c).data_type
                       != catalogue_fields[c].get("type")]
        assert disagreeing == [], (
            "the published catalogue is stale against the schema; rerun "
            "scripts/bootstrap_retail_installation.py after regenerating it")


class TestAnAggregationIsNeverMeaningless:
    @pytest.mark.parametrize("unit", ["points", "probability", "ratio",
                                      "months", "percentage points"])
    def test_nothing_that_cannot_be_added_is_added(self, unit):
        assert ap._ROLLUP.get(unit) == "avg", (
            f"a {unit} summed over nineteen thousand facilities is a number "
            "with no meaning")

    @pytest.mark.parametrize("unit", ["SAR", "SAR/month", "count"])
    def test_what_does_add_up_still_adds_up(self, unit):
        assert ap._ROLLUP.get(unit) == "sum"

    def test_every_unit_the_catalogue_publishes_is_in_the_table(self):
        from backend.orchestration import concepts as cx

        units = {c.unit for c in cx.CONCEPTS if c.unit}
        missing = sorted(u for u in units if u not in ap._ROLLUP)
        assert missing == [], (
            f"these units fall through to {ap._DEFAULT_ROLLUP!r}: {missing}")

    @pytest.mark.parametrize("question,wanted", [
        ("What is the average behavioural score?", "avg"),
        ("Show me the mean debt burden ratio", "avg"),
        ("What is the total exposure at default?", "sum"),
        ("What is the maximum days past due?", "max"),
        ("What is the minimum application score?", "min"),
    ])
    def test_the_word_the_reader_wrote_is_read(self, question, wanted):
        assert ap._asked_rollup(question) == wanted

    def test_a_sentence_that_names_none_is_left_to_the_unit(self):
        assert ap._asked_rollup("Show expected credit loss by product.") == ""

    @pytest.mark.parametrize("question", [
        "Show me the worst 10 customers by expected credit loss.",
        "Which product has the highest 30+ DPD rate?",
        "Show the largest exposures.",
        "Who are the best customers by application score?",
        "The top five customers by ECL.",
    ])
    def test_an_ordering_word_is_not_an_aggregation(self, question):
        """"worst 10 customers by ECL" grouped by customer with max(ECL).

        The ranking was then of each customer's largest FACILITY: the true
        top customer by ECL — 199,719.56 across two facilities — never
        appeared, and the share column was computed against 14,781,702
        rather than the book's 15,952,109.
        """
        assert ap._asked_rollup(question) == ""


class TestTheAnswersReconcileWithTheBook:
    def _rows(self, question: str) -> list[dict]:
        answered = orchestrator.answer(question)
        assert not answered.clarification, (
            f"{question!r} was not answered: {answered.clarification}")
        runtime = getattr(answered, "runtime", None)
        return list(getattr(runtime, "rows", None) or [])

    def test_an_average_score_is_an_average(self, published):
        rows = self._rows(f"What is the average behavioural score at "
                          f"{LATEST}?")
        got = float(rows[0]["behavioural_score"])
        assert got == pytest.approx(float(published.behavioural_score.mean()),
                                    rel=1e-9)

    def test_an_average_probability_is_between_zero_and_one(self, published):
        rows = self._rows(f"What is the average 12-month PD at {LATEST}?")
        got = float(next(iter(rows[0].values())))
        assert 0.0 < got < 1.0, "a probability of 476.76 is a sum of them"
        assert got == pytest.approx(float(published.pd_pit_12m_base.mean()),
                                    rel=1e-9)

    def test_an_average_ratio_is_a_ratio(self, published):
        rows = self._rows(f"What is the average debt burden ratio at "
                          f"{LATEST}?")
        got = float(rows[0]["debt_burden_ratio"])
        assert 0.0 < got < 5.0
        assert got == pytest.approx(float(published.debt_burden_ratio.mean()),
                                    rel=1e-9)

    def test_an_average_by_product_is_an_average_within_each_product(
            self, published):
        rows = self._rows(f"Show the average application score at origination "
                          f"by product at {LATEST}.")
        got = {r["product_label"]:
               round(float(r["application_score_at_origination"]), 6)
               for r in rows}
        want = {k: round(float(v), 6) for k, v in published.groupby(
            "product_label").application_score_at_origination.mean().items()}
        assert got == want

    def test_a_total_is_still_a_total(self, published):
        rows = self._rows(f"Show total exposure at default by product at "
                          f"{LATEST}.")
        got = {r["product_label"]: round(float(r["ead_base_sar"]), 2)
               for r in rows}
        want = {k: round(float(v), 2) for k, v in published.groupby(
            "product_label").ead_base_sar.sum().items()}
        assert got == want
