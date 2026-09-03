"""The metric picker has to find what somebody meant, not what they typed.

§8.3 is specific about the behaviour, and these tests are written against that
specification rather than against the implementation: typing three letters
must surface delinquency metrics, and adding a second word must *narrow* the
list rather than widen it. A picker that widens as you type is a picker that
sends people back to rebuilding numbers by hand.
"""

from __future__ import annotations

import pytest

from backend.metrics import library as lib
from backend.metrics import search as S
from backend.metrics.catalogue import ORIGIN_USER, STATUS_DRAFT, MetricDefinition

ALL = list(lib.ALL)


def names(hits) -> list[str]:
    return [hit.metric.name for hit in hits]


def ids(hits) -> list[str]:
    return [hit.metric.metric_id for hit in hits]


# ------------------------------------------------------- the §8.3 journey


def test_the_box_starts_empty_rather_than_showing_everything():
    """§8.3: do not show the entire metric catalogue by default."""
    assert S.search(ALL, "") == []
    assert S.search(ALL, "   ") == []


def test_three_letters_already_finds_the_delinquency_metrics():
    hits = S.search(ALL, "del", limit=8)
    assert hits, "typing 'del' found nothing at all"
    found = set(ids(hits))
    assert "retail.delinquent_balance" in found
    assert any(i.startswith("retail.dpd_") for i in found)


def test_adding_a_second_word_narrows_rather_than_widens():
    broad = S.search(ALL, "delinq", limit=50)
    narrow = S.search(ALL, "delinq 30", limit=50)
    assert 0 < len(narrow) < len(broad)
    assert set(ids(narrow)).issubset(set(ids(broad)))


def test_delinq_30_returns_only_thirty_day_metrics():
    """Every suggestion must be about 30 days, or the narrowing is a lie."""
    hits = S.search(ALL, "delinq 30", limit=50)
    assert hits
    assert "retail.dpd_30_count" in ids(hits)
    assert "retail.dpd_30_balance" in ids(hits)
    for hit in hits:
        assert "30" in hit.metric.name or "30" in " ".join(hit.metric.aliases)
    for unwanted in ("retail.dpd_60_count", "retail.dpd_90_count",
                     "retail.dpd_1_count"):
        assert unwanted not in ids(hits)


def test_a_typeahead_stays_short():
    assert len(S.search(ALL, "rate", limit=5)) <= 5
    assert len(S.search(ALL, "e")) <= S.DEFAULT_LIMIT


# ------------------------------------------------------------- the tiers


@pytest.mark.parametrize("query,expected", [
    ("npl rate", "corporate.npl_rate"),
    ("scorecard gini", "retail.scorecard.gini"),
    ("ecl coverage", "corporate.ifrs9.coverage"),
    ("stage 2 ratio", "corporate.ifrs9.stage2_share"),
    ("retail utilisation", "retail.utilisation"),
])
def test_an_exact_name_or_alias_wins_outright(query, expected):
    hits = S.search(ALL, query)
    assert ids(hits)[0] == expected
    assert hits[0].tier == S.TIER_EXACT


def test_the_words_people_actually_use_reach_the_same_metric():
    """"bad rate", "npl rate" and "default rate" are one number."""
    for phrasing in ("bad rate", "observed bad rate", "default rate"):
        top = ids(S.search(ALL, phrasing))[0]
        assert top == "retail.default_rate", phrasing


def test_case_and_punctuation_do_not_change_the_answer():
    plain = ids(S.search(ALL, "30 dpd account rate"))
    shouty = ids(S.search(ALL, "  30+  DPD, Account Rate! "))
    assert plain == shouty
    assert plain[0] == "retail.dpd_30_count"


def test_a_short_name_outranks_a_longer_one_with_the_same_prefix():
    hits = S.search(ALL, "ecl cov")
    assert ids(hits)[0] == "corporate.ifrs9.coverage"


def test_a_misspelling_still_finds_the_metric():
    hits = S.search(ALL, "utilisaton")
    assert "retail.utilisation" in ids(hits)
    assert all(hit.tier == S.TIER_FUZZY for hit in hits)


def test_a_near_miss_is_dropped_when_something_matched_properly():
    """Typing "30+ dpd" must not suggest the 60-day metric."""
    hits = S.search(ALL, "30+ dpd", limit=20)
    assert ids(hits)
    for hit in hits:
        assert hit.tier > S.TIER_FUZZY
    assert "retail.dpd_60_count" not in ids(hits)


def test_nonsense_finds_nothing_rather_than_something():
    assert S.search(ALL, "zzzqqxw") == []
    assert S.search(ALL, "how many kangaroos") == []


def test_every_hit_can_say_why_it_was_suggested():
    for query in ("del", "npl", "delinq 30", "utilisaton", "stage 2"):
        for hit in S.search(ALL, query):
            assert hit.why.strip(), f"{query} -> {hit.metric.name}"
            assert hit.matched in {"name", "alias", "id", "words", "spelling"}


def test_the_order_is_the_same_every_time():
    first = ids(S.search(ALL, "rate", limit=20))
    for _ in range(5):
        assert ids(S.search(list(reversed(ALL)), "rate", limit=20)) == first


# ------------------------------------------------------- what may be seen


def test_a_metric_is_never_suggested_over_data_the_asker_cannot_read():
    hits = S.search(ALL, "stage 2", readable={lib.BEHAVIOURAL})
    assert hits == []
    allowed = S.search(ALL, "stage 2", readable={lib.STAGING})
    assert "corporate.ifrs9.stage2_share" in ids(allowed)


def test_permission_is_applied_before_ranking_not_after():
    """A hidden metric must not consume a slot in the visible list."""
    unrestricted = S.search(ALL, "rate", limit=3)
    restricted = S.search(ALL, "rate", limit=3, readable={lib.STAGING,
                                                          lib.FACILITIES})
    assert len(restricted) == 3
    assert restricted != unrestricted
    for hit in restricted:
        assert set(hit.metric.datasets) <= {lib.STAGING, lib.FACILITIES}


def test_a_ratio_needs_every_dataset_it_reads():
    """Half a ratio is not a partial answer, it is no answer.

    No governed metric spans two datasets today — the formula checker refuses
    them — so this builds one rather than looping over an empty set and
    passing for the wrong reason. A user metric, or a later governed one, can
    reach this shape, and the rule has to already hold when it does.
    """
    from backend.metrics.formula import Formula, Side, Term

    across = MetricDefinition(
        metric_id="user.7.cross_book",
        name="Cross Book Coverage",
        definition="Corporate ECL over the retail balance. Nonsense as a "
                   "number; the point is that it reads two datasets.",
        formula=Formula(
            kind="percentage",
            numerator=Side(terms=(Term(id="top", label="ECL",
                                       dataset=lib.STAGING, aggregate="sum",
                                       field="ecl_amount"),)),
            denominator=Side(terms=(Term(id="bottom", label="Balance",
                                         dataset=lib.BEHAVIOURAL,
                                         aggregate="sum",
                                         field="current_balance"),)),
            scale=100.0),
        domain=lib.RETAIL, origin=ORIGIN_USER, status=STATUS_DRAFT)
    pool = [*ALL, across]
    assert set(across.datasets) == {lib.STAGING, lib.BEHAVIOURAL}

    assert across.metric_id in ids(S.search(pool, "cross book"))
    assert across.metric_id in ids(
        S.search(pool, "cross book", readable={lib.STAGING, lib.BEHAVIOURAL}))
    for half in (lib.STAGING, lib.BEHAVIOURAL):
        assert across.metric_id not in ids(
            S.search(pool, "cross book", readable={half})), half
    assert all(across.metric_id != m.metric_id
               for _, entries in S.browse(pool, readable={lib.STAGING})
               for m in entries)


def test_browse_is_the_deliberate_way_to_see_everything():
    grouped = S.browse(ALL)
    assert len(grouped) >= 2
    total = sum(len(entries) for _, entries in grouped)
    assert total == len(ALL)
    for _, entries in grouped:
        assert names_sorted(entries)


def names_sorted(entries: list[MetricDefinition]) -> bool:
    return [e.name for e in entries] == sorted(e.name for e in entries)


def test_browse_hides_what_may_not_be_read():
    grouped = S.browse(ALL, readable={lib.STAGING})
    for _, entries in grouped:
        for metric in entries:
            assert set(metric.datasets) <= {lib.STAGING}


# ------------------------------------------ what CreditProbe cannot answer


def test_an_unavailable_metric_explains_itself_instead_of_going_missing():
    found = S.unsupported_for(lib.UNSUPPORTED, "roll rate")
    assert found, "'roll rate' should be recognised even though it is absent"
    assert found[0].because.strip()
    assert found[0].needs


def test_an_unsupported_entry_is_never_offered_as_a_metric():
    for entry in lib.UNSUPPORTED:
        assert entry.metric_id not in ids(S.search(ALL, entry.name, limit=50))


def test_a_user_metric_is_searchable_and_carries_its_own_status():
    mine = MetricDefinition(
        metric_id="user.42.arrears_watch",
        name="Arrears Watch Ratio",
        definition="A ratio I built this morning.",
        formula=lib.ALL[0].formula,
        domain=lib.RETAIL,
        aliases=("arrears watch",),
        origin=ORIGIN_USER,
        status=STATUS_DRAFT,
        created_by=42)
    hits = S.search([*ALL, mine], "arrears watch")
    assert ids(hits)[0] == "user.42.arrears_watch"
    payload = hits[0].to_dict()
    assert payload["origin"] == ORIGIN_USER
    assert payload["governed"] is False
    assert payload["status"] == STATUS_DRAFT
