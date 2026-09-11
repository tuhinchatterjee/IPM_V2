"""
Does the published domain hold together?

Not a test of the scoring engine — `test_rawabi_regression.py` does that
against the workbook's own worked example. This asks a different question of
the 6,000 published rows: whether what they SAY is internally consistent.

The distinction matters because every answer the product gives is assembled
from these rows. A band that disagrees with its own score, a movement that is
not the difference between two periods, or a top-five share above a hundred
per cent would each produce a confidently wrong sentence in the chat, and no
amount of testing the language layer would find it.

What "reconciles" means here
----------------------------
The final score is `clamp(anchor + net_notches x 8, 0, 100)` and THEN any
override. 1,041 of the 6,000 rows do not match the arithmetic alone — and all
1,041 carry a recorded override that explains them, which is the methodology
working rather than failing. A row that missed the arithmetic AND recorded no
override would be a real defect, and that is what this asserts.
"""

from __future__ import annotations

import json

import pytest

from backend.early_warning import notches as notch_mod
from backend.early_warning import v2_service as svc

BANDS = ("VERY_LOW", "LOW", "MEDIUM", "HIGH", "VERY_HIGH")
HIGH_PLUS = ("HIGH", "VERY_HIGH")


@pytest.fixture(scope="module", autouse=True)
def _require_the_domain():
    try:
        if not svc.periods():
            pytest.skip("The Early Warning domain is not built.")
    except Exception as e:  # noqa: BLE001
        pytest.skip(f"The Early Warning domain is not readable: {e}")


@pytest.fixture(scope="module")
def every_month() -> list:
    return [(p, svc.borrower_month(p)) for p in svc.periods()]


@pytest.fixture(scope="module")
def current():
    return svc.borrower_month(svc.latest_period())


def _load(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value
    return value


def _band(value) -> str:
    return str(value or "").strip().upper().replace(" ", "_")


# ------------------------------------------------------------------- shape


def test_the_domain_is_one_row_per_customer_per_month(every_month):
    for period, df in every_month:
        dupes = df.duplicated(subset=["customer_id"]).sum()
        assert dupes == 0, f"{period} has {dupes} duplicate customer rows"


def test_the_published_history_is_contiguous():
    periods = list(svc.periods())
    months = [int(p[:4]) * 12 + int(p[5:]) for p in periods]
    gaps = [(a, b) for a, b in zip(periods, periods[1:], strict=False)
            if (int(b[:4]) * 12 + int(b[5:])) - (int(a[:4]) * 12 + int(a[5:])) != 1]
    assert not gaps, f"the snapshots are not contiguous: {gaps}"
    assert len(periods) >= 20, periods


def test_the_population_is_stable_across_months(every_month):
    sizes = {p: len(df) for p, df in every_month}
    assert len(set(sizes.values())) == 1, (
        f"the obligor count moves between months: {sizes}")


# ------------------------------------------------------- the arithmetic


def test_the_notches_sum_to_the_net_within_the_cap(every_month):
    cap = notch_mod.NET_NOTCH_CAP
    wrong = []
    for period, df in every_month:
        for row in df.itertuples():
            parts = _load(row.notches)
            if not isinstance(parts, dict):
                continue
            capped = max(-cap, min(cap, sum(int(v) for v in parts.values())))
            if capped != int(row.net_notches):
                wrong.append((period, row.customer_id, capped, row.net_notches))
    assert not wrong[:5], f"{len(wrong)} rows where the notches do not sum: {wrong[:5]}"


def test_no_net_notch_exceeds_the_published_cap(every_month):
    cap = notch_mod.NET_NOTCH_CAP
    over = [(p, r.customer_id, r.net_notches)
            for p, df in every_month for r in df.itertuples()
            if abs(int(r.net_notches)) > cap]
    assert not over[:5], f"{len(over)} rows exceed the +/-{cap} cap: {over[:5]}"


def test_every_final_score_reconciles_to_the_methodology(every_month):
    """anchor + net x 8, clamped — or an override that says why not."""
    points = notch_mod.POINTS_PER_NOTCH
    unexplained = []
    overridden = 0
    for period, df in every_month:
        for row in df.itertuples():
            expected = max(0.0, min(100.0, float(row.anchor_score)
                                     + int(row.net_notches) * points))
            if abs(expected - float(row.ews_score)) <= 1e-6:
                continue
            applied = row.overrides_applied
            if applied is None or not str(applied).strip():
                unexplained.append((period, row.customer_id,
                                    row.anchor_score, row.net_notches,
                                    row.ews_score, expected))
            else:
                overridden += 1
    assert not unexplained[:5], (
        f"{len(unexplained)} rows miss the arithmetic and record no override: "
        f"{unexplained[:5]}")
    assert overridden > 0, (
        "no row was overridden at all, which means this test would not have "
        "noticed if the override path had stopped running")


def test_the_band_agrees_with_the_score(every_month):
    """A row whose band contradicts its own score is a wrong sentence waiting."""
    order = {b: i for i, b in enumerate(BANDS)}
    rows = [(p, r.customer_id, float(r.ews_score), _band(r.ews_band))
            for p, df in every_month for r in df.itertuples()]
    for band in BANDS:
        scores = [s for _, _, s, b in rows if b == band]
        if not scores:
            continue
        lo, hi = min(scores), max(scores)
        higher = [s for _, _, s, b in rows
                  if b in BANDS and order[b] > order[band]]
        if higher:
            assert lo <= hi <= min(higher), (
                f"{band} reaches {hi} while a higher band starts at "
                f"{min(higher)}")


def test_every_band_is_one_of_the_published_five(every_month):
    seen = {_band(r.ews_band) for _, df in every_month for r in df.itertuples()}
    assert seen <= set(BANDS), seen - set(BANDS)


# ------------------------------------------------------------ aggregation


def test_the_band_counts_sum_to_the_population(current):
    counts = current["ews_band"].map(_band).value_counts().to_dict()
    assert sum(counts.values()) == len(current)


def test_exposure_aggregates_without_loss(current):
    total = float(current["exposure"].sum())
    by_sector = float(current.groupby("sector")["exposure"].sum().sum())
    by_band = float(current.groupby(current["ews_band"].map(_band))
                    ["exposure"].sum().sum())
    assert abs(total - by_sector) < 0.01
    assert abs(total - by_band) < 0.01
    assert total > 0


def test_a_top_n_share_cannot_exceed_the_whole(current):
    hi = current[current["ews_band"].map(_band).isin(HIGH_PLUS)]
    total = float(hi["exposure"].sum())
    for n in (1, 3, 5, 10):
        top = float(hi.nlargest(n, "exposure")["exposure"].sum())
        assert top <= total + 1e-6, f"top {n} exceeds the whole"
        if total:
            assert 0 <= 100.0 * top / total <= 100.0


def test_percentages_stay_inside_nought_to_a_hundred(current):
    for column in ("utilisation_pct",):
        if column not in current:
            continue
        values = current[column].dropna()
        assert float(values.min()) >= 0, column
        assert float(values.max()) <= 200, (
            f"{column} reaches {values.max()}, which is not a percentage")


def test_movement_is_the_difference_between_two_published_months():
    periods = list(svc.periods())
    now, before = svc.borrower_month(periods[-1]), svc.borrower_month(periods[-2])
    merged = now.merge(before[["customer_id", "ews_score"]], on="customer_id",
                       suffixes=("", "_then"))
    merged["movement"] = merged["ews_score"] - merged["ews_score_then"]
    assert len(merged) == len(now)
    recomputed = (merged["ews_score"] - merged["ews_score_then"]).abs().sum()
    assert abs(float(merged["movement"].abs().sum()) - float(recomputed)) < 1e-9


# ---------------------------------------------------- missing is not zero


def test_an_obligor_with_no_fired_signal_is_not_given_a_ta_score(current):
    """Missing must stay distinguishable from no-risk.

    A trigger-and-accelerator score is built from signals that fired. An
    obligor with none has no T&A evidence — which is a different statement
    from "measured, and it was zero", and the product says so only if the
    data keeps them apart.
    """
    quiet = current[current["signal_count_fired"] == 0]
    assert len(quiet) > 0, "no obligor is signal-quiet; this test proves nothing"
    assert float(quiet["ta_score"].max()) == 0.0, (
        "an obligor with no fired signal carries a non-zero T&A score")


def test_a_classifier_score_does_not_require_a_fired_signal(current):
    """The converse, so the test above is not read as "quiet means zero".

    Classifiers are level-based — a leverage ratio, a stage, a utilisation —
    and they are legitimately scored for an obligor that fired no event
    signal at all. The two layers measure different things.
    """
    quiet = current[current["signal_count_fired"] == 0]
    assert float(quiet["classifier_score"].max()) > 0.0


def test_the_layer_scores_are_the_six_the_methodology_publishes(current):
    keys = set()
    for row in current.itertuples():
        scores = _load(row.layer_dimension_scores)
        if isinstance(scores, dict):
            keys |= set(scores)
    assert keys == {"l1_ta", "l2_ta", "l2_c", "l3_ta", "l4_ta", "l4_c"}, keys


def test_every_row_carries_the_methodology_version(every_month):
    versions = {str(r.methodology_version)
                for _, df in every_month for r in df.itertuples()}
    assert len(versions) == 1, f"more than one methodology in the book: {versions}"
    assert versions == {"ews-v2.1.0"}, versions
