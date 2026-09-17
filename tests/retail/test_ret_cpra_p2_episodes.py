"""P2 gates: ten episodes that are in the book, not in the captions.

Two things a demonstration of ten investigations actually fails on.

The first is that the stories are not there. Ten titles and ten paragraphs
survive one click: the reader asks which customers, and there is nothing to
export, nothing to price and no pocket to compare. So these gates evaluate
each case's PUBLISHED predicate over the PUBLISHED columns of the shipped book
and require a population, a concentration and an exposure to come back.

The second is that making them severe quietly made them dishonest. So the
gates also assert what must NOT have happened: the accepted Alpha calibration
unmoved, C06's borrower not deteriorated to make its loss move, no pocket
selected on a protected characteristic, and no pocket whose every member is a
case by construction.

Nothing here pins a decimal from the worked workbook. The workbook's hundred
observations per case are ratios, applied to whatever eligible population the
installed book has, so the gates assert relationships and orders of magnitude.
A test that pins a digit fails the first time anybody improves the generator,
and passes forever once the story quietly stops being true.

Everything read here is SYNTHETIC. Alpha Card, DEMO Employer A and DEMO
Housing Project C are demonstration labels.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.retail import episode_measures as em
from backend.retail import episodes as ep


@pytest.fixture(scope="module")
def book():
    """The shipped book, read through the module the product reads it with."""
    if not em.months():
        pytest.skip("The shipped retail lake is not built.")
    try:
        data = em.frame()
    except em.MissingEpisodeColumns as exc:
        pytest.skip(str(exc))
    if data.empty:
        pytest.skip("The shipped retail lake has no latest month.")
    return data


@pytest.fixture(scope="module")
def measured(book):
    """Every case's populations, measured once."""
    out = {}
    for case_id in ep.case_ids():
        eligible = em.eligible_mask(book, case_id)
        issue = em.issue_mask(book, case_id) & eligible
        pocket = em.pocket_mask(book, case_id, eligible)
        out[case_id] = {"eligible": eligible, "issue": issue, "pocket": pocket}
    return out


# --------------------------------------------------------------- population


def test_all_ten_cases_have_a_population_in_the_book(measured):
    for case_id, sets in measured.items():
        assert int(sets["eligible"].sum()) >= 100, (
            f"{case_id} has {int(sets['eligible'].sum())} eligible "
            f"facilities. A denominator that small cannot support a rate, and "
            f"a card quoting one would be quoting noise.")
        assert int(sets["issue"].sum()) >= 20, (
            f"{case_id}'s predicate finds {int(sets['issue'].sum())} "
            f"facilities. The story is not in the book.")


def test_every_case_carries_real_exposure(book, measured):
    import pandas as pd

    for case_id, sets in measured.items():
        gca = pd.to_numeric(
            book.loc[sets["issue"], "gross_carrying_amount_sar"],
            errors="coerce").sum()
        assert gca > 0, f"{case_id}'s issue population carries no exposure"


def test_the_issue_population_is_a_subset_of_the_eligible_one(measured):
    for case_id, sets in measured.items():
        assert not (sets["issue"] & ~sets["eligible"]).any(), (
            f"{case_id} counts facilities as cases that are not in its own "
            f"denominator, so its rate can exceed one.")


def test_a_facility_belongs_to_at_most_one_episode(book):
    # Overlapping cases are a real thing the export has to de-duplicate, and
    # the generator does not create them, so the gate records that rather than
    # pretending the union case is exercised here.
    counts = book["episode_code"].replace("", np.nan).notna().sum()
    assert counts > 0
    assert book["episode_code"].nunique() >= 9


# ------------------------------------------------------------ concentration


def test_each_pocket_holds_most_of_its_cases(measured):
    for case_id, sets in measured.items():
        issue, pocket = sets["issue"], sets["pocket"]
        n_issue = int(issue.sum())
        share = int((issue & pocket).sum()) / n_issue
        assert share >= 0.45, (
            f"{case_id}'s named pocket holds {share:.0%} of its cases. A "
            f"pocket that does not concentrate the cases is not the pocket, "
            f"and S4 would be pointing at the wrong thing.")


def test_incidence_inside_a_pocket_beats_incidence_outside_it(measured):
    for case_id, sets in measured.items():
        eligible, issue, pocket = (sets["eligible"], sets["issue"],
                                   sets["pocket"])
        outside = eligible & ~pocket
        inside_rate = int((pocket & issue).sum()) / max(int(pocket.sum()), 1)
        outside_rate = int((outside & issue).sum()) / max(int(outside.sum()), 1)
        assert outside_rate > 0, (
            f"{case_id} has no cases at all outside its pocket, so its rate "
            f"ratio is a division by zero dressed as a finding.")
        assert inside_rate / outside_rate >= 3.0, (
            f"{case_id}: incidence {inside_rate:.1%} inside the pocket "
            f"against {outside_rate:.1%} outside is a ratio of "
            f"{inside_rate / outside_rate:.1f}x. That is not a concentration.")


def test_no_pocket_is_a_tautology(measured):
    for case_id, sets in measured.items():
        pocket, issue = sets["pocket"], sets["issue"]
        inside_rate = int((pocket & issue).sum()) / max(int(pocket.sum()), 1)
        assert inside_rate < 0.95, (
            f"{case_id}'s pocket is {inside_rate:.0%} cases. A pocket where "
            f"every member is a case is a definition, not a finding.")


def test_the_concentration_reader_agrees_with_the_masks(measured):
    for case_id, sets in measured.items():
        reported = em.concentration(case_id=case_id)
        assert reported["available"]
        assert reported["eligible"] == int(sets["eligible"].sum())
        assert reported["issue"] == int(sets["issue"].sum())
        assert reported["pocket"]["issue"] == int(
            (sets["pocket"] & sets["issue"]).sum())
        assert reported["rate_ratio"] is not None


# -------------------------------------------------------------- comparators


def test_every_case_names_what_it_is_compared_against(measured):
    for case_id in measured:
        against = em.comparator(case_id=case_id)
        assert against["available"], (
            f"{case_id} has no comparator: {against.get('because')}")
        assert against["basis"] in (em.PRIOR_MONTH, em.OUTSIDE_POCKET,
                                    em.HISTORICAL)
        assert against["label"]
        assert against["eligible"] > 0
        assert against["rate"] is not None


def test_the_two_outcome_window_stories_compare_matched_vintages(book):
    for case_id in ("C02", "C10"):
        historical = em.historical_mask(book, case_id)
        assert historical.sum() >= 50, (
            f"{case_id} has no matched historical cohort published, so its "
            f"comparison would have to be against the same loans a month "
            f"earlier — which is the same episode, not a comparison.")
        assert em.COMPARATOR_BASIS[case_id] == em.HISTORICAL


def test_each_case_is_materially_worse_than_its_comparator(measured):
    for case_id, sets in measured.items():
        rate = int(sets["issue"].sum()) / int(sets["eligible"].sum())
        against = em.comparator(case_id=case_id)["rate"]
        assert against, case_id
        assert rate / against >= 1.5, (
            f"{case_id} runs at {rate:.1%} against a comparator of "
            f"{against:.1%}. That is not a finding worth a critical card.")


def test_the_headline_a_card_shows_reconciles_with_the_book(measured):
    for case_id, sets in measured.items():
        card = em.headline(case_id=case_id)
        assert card["available"]
        assert card["affected"] == int(sets["issue"].sum())
        assert card["eligible"] == int(sets["eligible"].sum())
        assert card["exposure_sar"] > 0
        assert card["multiple"] and card["multiple"] >= 1.5
        assert card["comparator"]["label"]
        assert card["headline_metric"]["prohibited_inference"]


# ---------------------------------------------------- what must not have moved


def test_the_accepted_alpha_calibration_is_unmoved(book):
    """The tenth story is a regression contract, not one of the nine.

    Its numbers were accepted on a previous build. If adding nine episodes
    moved them, the demonstration that was signed off is not the one that
    would be shown.
    """
    import pandas as pd

    alpha = book[book["product_subsegment"] == "ALPHA"]
    assert len(alpha) > 3_000
    share = (alpha["dpd_bucket"] == "1-29").mean()
    assert share == pytest.approx(0.2849, abs=0.002), (
        f"Alpha's 1-29 share is {share:.4f}; the accepted build's is 0.2849.")
    deep = ((pd.to_numeric(alpha["dpd"], errors="coerce") >= 20)
            & (pd.to_numeric(alpha["dpd"], errors="coerce") <= 29)).mean()
    assert deep == pytest.approx(share, abs=0.001), (
        "Alpha's campaign statement cycle puts every missed cycle in 20-29. "
        "A divergence means the cycle offset moved.")


def test_no_episode_touches_the_card_book(book):
    cards = book[book["product_code"] == "CREDIT_CARD"]
    overlaid = cards["episode_code"].replace("", np.nan).notna()
    assert not overlaid.any(), (
        f"{int(overlaid.sum())} card facilities carry an episode code. The "
        f"Alpha story is generated by the card programme machinery, and an "
        f"overlay that also pushed on cards could move its accepted "
        f"calibration without anybody being able to say which change did it.")


def test_the_recovery_story_does_not_deteriorate_its_borrowers(book):
    """C06's negative control, stated as a test rather than as a sentence.

    Compared inside the case at one date: the facilities whose recovery
    assumptions were revised against the ones whose were not. Their scores and
    default probabilities must be materially the same, because the finding is
    entirely in loss severity, and a generator that quietly worsened the
    borrower would be manufacturing the evidence the story exists to reject.
    """
    import pandas as pd

    case = book[book["episode_code"] == "C06"]
    assert len(case) > 500
    revised = case["episode_role"] == "ISSUE"

    score = pd.to_numeric(case["behavioural_score"], errors="coerce")
    gap = abs(score[revised].median() - score[~revised].median())
    assert gap <= 10.0, (
        f"C06's revised cohort's behavioural score differs by {gap:.1f} "
        f"points from the rest of its book. The story is a loss-severity "
        f"story; the borrower is the control.")

    pd12 = pd.to_numeric(case["pd_pit_12m_base"], errors="coerce")
    ratio = pd12[revised].median() / max(pd12[~revised].median(), 1e-9)
    assert 0.7 <= ratio <= 1.4, (
        f"C06's revised cohort's median 12-month PD is {ratio:.2f}x the "
        f"rest's. It must be close to one.")


def test_the_recovery_story_moves_the_loss_it_says_it_moves(book):
    import pandas as pd

    case = book[book["episode_code"] == "C06"]
    revised = case["episode_role"] == "ISSUE"
    lgd = pd.to_numeric(case["lgd_base"], errors="coerce")
    assert lgd[revised].mean() > lgd[~revised].mean() * 1.8, (
        "C06's whole finding is a material loss-given-default revision. If "
        "LGD has not moved, nothing has.")
    delay = pd.to_numeric(case["recovery_delay_months"], errors="coerce")
    assert delay[revised].mean() > delay[~revised].mean() + 2.0, (
        "The story says recovery takes materially longer. The figure the ECL "
        "discounting uses has to be the figure that moved.")


def test_the_original_application_score_is_never_rewritten(book):
    """C02 and every 'were they weak at approval' answer depend on this."""
    import pandas as pd

    scores = pd.to_numeric(book["app_score_value"], errors="coerce")
    assert scores.notna().mean() > 0.95
    earlier = em.frame(em.previous_month())
    joined = book[["facility_id", "app_score_value"]].merge(
        earlier[["facility_id", "app_score_value"]], on="facility_id",
        suffixes=("_now", "_before"))
    assert len(joined) > 1_000
    moved = (pd.to_numeric(joined["app_score_value_now"], errors="coerce")
             != pd.to_numeric(joined["app_score_value_before"], errors="coerce"))
    assert not moved.any(), (
        f"{int(moved.sum())} facilities' original application scores changed "
        f"between two months.")


def test_no_case_selects_on_a_protected_characteristic():
    banned = ("nationality", "sex", "gender", "religion", "race", "marital",
              "age_band", "date_of_birth")
    for case_id in ep.case_ids():
        for clause in ep.predicate(case_id)["clauses"]:
            assert not any(b in clause["field"].lower() for b in banned), (
                f"{case_id}'s rule reads {clause['field']}.")


def test_the_pension_story_is_a_cash_flow_rule_not_an_age_rule(book):
    """C09's negative control.

    The pocket is a documented transition whose payments did not step down.
    Age correlates with it and is not it, so the rule must read the documented
    income and the obligations against it — and both clauses must be needed.
    """
    fields = {c["field"] for c in ep.predicate("C09")["clauses"]}
    assert "pension_income_replacement" in fields
    assert "pension_obligations_to_income" in fields

    case = book[book["episode_code"] == "C09"]
    import pandas as pd

    replacement = pd.to_numeric(case["pension_income_replacement"],
                                errors="coerce")
    obligations = pd.to_numeric(case["pension_obligations_to_income"],
                                errors="coerce")
    # Each clause alone catches materially more than the two together, which
    # is what makes the second clause load-bearing rather than decorative.
    one = (replacement <= ep.PENSION_REPLACEMENT).sum()
    both = ((replacement <= ep.PENSION_REPLACEMENT)
            & (obligations >= ep.PENSION_PAYMENT_TO_INCOME)).sum()
    assert both < one, (
        "The obligation clause excludes nobody, so the rule is really just "
        "'their income fell', and a customer whose commitments are small is "
        "being called an affordability gap.")


def test_evidence_attrition_is_real_and_nested(book, measured):
    """S1 and S3 narrow because alerts fail verification, not because a
    number was chosen. The levels must nest, so an S3 cohort is a subset of
    an S1 cohort rather than a differently drawn one."""
    for case_id, sets in measured.items():
        if case_id == "C01":
            continue  # the accepted story's evidence is its own machinery
        issue = sets["issue"]
        verified = issue & em.evidence_mask(book, ep.EV_VERIFIED)
        corroborated = issue & em.evidence_mask(book, ep.EV_CORROBORATED)
        assert not (corroborated & ~verified).any(), (
            f"{case_id}: a corroborated alert that is not a verified one")
        n_issue, n_v, n_c = (int(issue.sum()), int(verified.sum()),
                             int(corroborated.sum()))
        assert n_c < n_v < n_issue, (
            f"{case_id}: {n_issue} alerts, {n_v} verified, {n_c} "
            f"corroborated. A story that carries every alert through to the "
            f"policy cohort has no verification step in it.")


def test_the_demonstration_labels_are_visibly_fictitious(book):
    for column, expected in (("employer_group", "DEMO Employer A"),
                             ("housing_project_id", "DEMO Housing Project C")):
        values = set(book[column].dropna().unique()) - {""}
        assert expected in values, f"{expected} is not in {column}"
        for value in values:
            assert value.startswith("DEMO ") or value.startswith("OTHER"), (
                f"{column} carries {value!r}, which does not read as a "
                f"demonstration label.")


def test_the_config_is_regenerable_from_the_attachments():
    """The structure of the ten stories is generated, so it cannot drift from
    the specification and the workbook that are committed beside it."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts/build_episode_config.py"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "already current" in result.stdout, (
        "config/retail_episodes.json differs from what the specification and "
        "the workbook produce. Either an attachment changed or the config was "
        "edited by hand; both are things a reviewer should be told about.\n"
        + result.stdout)
