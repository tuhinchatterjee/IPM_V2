"""
P0.4 — an ECL decomposition that does not depend on the order of its drivers.

Defect D: asked to decompose an ECL movement into exposure, stage migration,
PD, LGD and mix, and to attribute it to sectors and customers, CreditProbe
returned an ECL movement BY SECTOR — a true table answering a different
question.

The tests are built on diagnostic accounts whose answers are known by
construction, because the whole claim of this method is exactness and the only
way to test exactness is against a case where the right answer is arithmetic
rather than opinion.
"""

from __future__ import annotations

import math

import pytest

from backend.orchestration import decomposition as dc


def _account(account_id: str, *, ead: float = 100.0, stage: int = 1,
             pd_12m: float = 2.0, pd_lifetime: float = 6.0,
             lgd: float = 40.0, overlay: float = 0.0,
             sector: str = "Contracting", customer: str = "",
             name: str = "") -> dc.Account:
    """One diagnostic account whose modelled ECL is exactly EAD x PD x LGD.

    Setting `model_ecl` to the plain product makes the residual factor 1.0, so
    a test can reason about the five named drivers without the sixth moving.
    """
    used = pd_12m if stage <= 1 else pd_lifetime
    model = ead * used / 100.0 * lgd / 100.0
    return dc.Account(
        account_id=account_id, customer_id=customer or account_id,
        name=name or account_id, sector=sector, ead=ead, stage=stage,
        pd_12m=pd_12m, pd_lifetime=pd_lifetime, lgd=lgd,
        model_ecl=model, total_ecl=model + overlay)


# ------------------------------------------------------------- the attribution


def test_the_effects_sum_exactly_to_the_change_in_the_product():
    """The reconciliation identity, on the kernel itself. Everything else in
    this module is about choosing which factors to hand it."""
    opening = (100.0, 0.5, 1.0, 0.02, 0.4, 1.0)
    closing = (120.0, 0.6, 1.5, 0.03, 0.45, 1.1)
    effects = dc.shapley(opening, closing)
    assert sum(effects) == pytest.approx(math.prod(closing) - math.prod(opening),
                                         abs=1e-12)


def test_the_attribution_does_not_depend_on_the_order_of_the_factors():
    """The point of the method. The naive one-at-a-time attribution also
    reconciles, and hands every interaction term to whichever factor happened
    to move last — so the same book tells a different story depending on the
    order somebody wrote the loop in, and each version reconciles."""
    opening = (100.0, 0.5, 1.0, 0.02, 0.4, 1.0)
    closing = (120.0, 0.6, 1.5, 0.03, 0.45, 1.1)
    straight = dc.shapley(opening, closing)

    order = (3, 0, 5, 1, 4, 2)
    shuffled = dc.shapley(tuple(opening[i] for i in order),
                          tuple(closing[i] for i in order))
    for position, original in enumerate(order):
        assert shuffled[position] == pytest.approx(straight[original], abs=1e-12)


def test_a_factor_that_did_not_move_has_no_effect():
    """A decomposition that gives an unchanged driver a non-zero effect is
    telling a reader to investigate something that did not happen."""
    assert dc.shapley((2.0, 3.0, 5.0), (2.0, 4.0, 5.0)) == pytest.approx(
        (0.0, 10.0, 0.0), abs=1e-12)


def test_two_factors_moving_the_same_way_split_their_interaction_evenly():
    """1 x 1 -> 2 x 2 is a change of 3, and neither factor did more of it than
    the other. One-at-a-time would say 1 and 2."""
    assert dc.shapley((1.0, 1.0), (2.0, 2.0)) == pytest.approx((1.5, 1.5))


# --------------------------------------------------------------- the drivers


def test_exposure_growth_is_reported_as_exposure():
    opening = [_account("A", ead=100.0)]
    closing = [_account("A", ead=150.0)]
    out = dc.decompose(opening, closing)
    assert out.reconciles
    assert out.component(dc.EXPOSURE).effect == pytest.approx(out.movement)
    assert out.component(dc.PD).effect == pytest.approx(0.0, abs=1e-12)
    assert out.component(dc.LGD).effect == pytest.approx(0.0, abs=1e-12)


def test_a_stage_migration_is_reported_as_stage_migration_not_as_pd():
    """The account's twelve-month PD did not change. It moved to a lifetime
    horizon, and calling that a rise in PD would send a reader to the ratings
    team about a model that did exactly what SICR asked it to."""
    opening = [_account("A", stage=1, pd_12m=2.0, pd_lifetime=6.0)]
    closing = [_account("A", stage=2, pd_12m=2.0, pd_lifetime=6.0)]
    out = dc.decompose(opening, closing)
    assert out.reconciles
    assert out.component(dc.STAGE).effect == pytest.approx(out.movement)
    assert out.component(dc.PD).effect == pytest.approx(0.0, abs=1e-12)


def test_a_pd_rise_at_a_constant_horizon_is_reported_as_pd():
    opening = [_account("A", pd_12m=2.0)]
    closing = [_account("A", pd_12m=3.0)]
    out = dc.decompose(opening, closing)
    assert out.component(dc.PD).effect == pytest.approx(out.movement)
    assert out.component(dc.STAGE).effect == pytest.approx(0.0, abs=1e-12)


def test_an_lgd_rise_is_reported_as_lgd():
    out = dc.decompose([_account("A", lgd=40.0)], [_account("A", lgd=50.0)])
    assert out.component(dc.LGD).effect == pytest.approx(out.movement)


def test_exposure_moving_between_accounts_is_mix_not_exposure():
    """The book did not grow. Its composition changed, and the loss changed
    because the exposure landed on a worse borrower. Reporting that as an
    exposure effect would say the bank lent more, which it did not."""
    opening = [_account("SAFE", ead=100.0, pd_12m=1.0),
               _account("RISKY", ead=100.0, pd_12m=10.0)]
    closing = [_account("SAFE", ead=50.0, pd_12m=1.0),
               _account("RISKY", ead=150.0, pd_12m=10.0)]
    out = dc.decompose(opening, closing)
    assert out.reconciles
    assert out.movement > 0
    assert out.component(dc.MIX).effect == pytest.approx(out.movement)
    assert out.component(dc.EXPOSURE).effect == pytest.approx(0.0, abs=1e-9)


def test_the_overlay_is_attributed_rather_than_factorised():
    """An overlay is added on top of modelled ECL, not modelled. Inventing a
    factorisation for it would be arithmetic about somebody's judgement."""
    out = dc.decompose([_account("A", overlay=5.0)],
                       [_account("A", overlay=12.0)])
    assert out.component(dc.OVERLAY).effect == pytest.approx(7.0)
    assert out.movement == pytest.approx(7.0)
    assert out.reconciles


def test_the_model_residual_carries_what_the_product_form_does_not_explain():
    """P0.4: 'Do not pretend PD x LGD x EAD explains final ECL where overlays,
    lifetime horizon and discounting make it incomplete.' On a real book the
    product is well short of modelled ECL, and the gap has to be a named
    driver rather than a silent scaling of the PD effect."""
    opening = [dc.Account(account_id="A", ead=100.0, stage=1, pd_12m=2.0,
                          pd_lifetime=6.0, lgd=40.0,
                          model_ecl=0.8, total_ecl=0.8)]
    # Nothing moved but the model itself: same exposure, PD, LGD.
    closing = [dc.Account(account_id="A", ead=100.0, stage=1, pd_12m=2.0,
                          pd_lifetime=6.0, lgd=40.0,
                          model_ecl=1.2, total_ecl=1.2)]
    out = dc.decompose(opening, closing)
    assert out.component(dc.MODEL).effect == pytest.approx(0.4)
    for driver in (dc.EXPOSURE, dc.MIX, dc.STAGE, dc.PD, dc.LGD):
        assert out.component(driver).effect == pytest.approx(0.0, abs=1e-12)


# ------------------------------------------------------- the same-scope rule


def test_an_account_that_arrived_is_not_a_rise_in_pd():
    """It has one PD, not two. Folding arrivals into the drivers is the other
    common way a decomposition reconciles while lying."""
    out = dc.decompose([_account("A")], [_account("A"), _account("B")])
    assert out.arrived == 1
    assert out.component(dc.NEW_ACCOUNTS).effect == pytest.approx(0.8)
    assert out.component(dc.PD).effect == pytest.approx(0.0, abs=1e-12)
    assert out.reconciles


def test_an_account_that_left_takes_its_whole_opening_ecl_with_it():
    out = dc.decompose([_account("A"), _account("B")], [_account("A")])
    assert out.departed == 1
    assert out.component(dc.EXITED_ACCOUNTS).effect == pytest.approx(-0.8)
    assert out.reconciles


def test_a_population_with_nothing_in_common_says_so_rather_than_attributing():
    out = dc.decompose([_account("A")], [_account("B")])
    assert out.unavailable
    assert "no account is present in both periods" in out.unavailable


# ------------------------------------------------------- what it reports back


def test_everything_reconciles_on_a_mixed_book():
    """Every driver moving at once, plus an arrival and a departure. The whole
    claim of the method is that this still sums exactly."""
    opening = [
        _account("A", ead=100.0, pd_12m=2.0, lgd=40.0, sector="Contracting"),
        _account("B", ead=200.0, pd_12m=1.0, lgd=35.0, stage=2,
                 sector="Real Estate", overlay=3.0),
        _account("C", ead=50.0, pd_12m=8.0, lgd=60.0, sector="Energy"),
        _account("GONE", ead=80.0, pd_12m=4.0, sector="Energy"),
    ]
    closing = [
        _account("A", ead=140.0, pd_12m=3.5, lgd=45.0, stage=2,
                 sector="Contracting"),
        _account("B", ead=150.0, pd_12m=1.2, lgd=35.0, stage=3,
                 sector="Real Estate", overlay=9.0),
        _account("C", ead=50.0, pd_12m=6.0, lgd=55.0, sector="Energy"),
        _account("NEW", ead=300.0, pd_12m=2.5, sector="Manufacturing"),
    ]
    out = dc.decompose(opening, closing, opening_period="Q2 2025",
                       closing_period="Q2 2026")
    assert out.reconciles
    assert out.attributed == pytest.approx(out.movement, abs=1e-9)
    assert out.matched == 3
    assert out.arrived == 1
    assert out.departed == 1


def test_the_sector_contributions_sum_to_the_movement():
    """A ranking that does not add up to the total is a ranking of something
    else. Asked for with a top wide enough to hold every sector."""
    opening = [_account("A", sector="Contracting", pd_12m=2.0),
               _account("B", sector="Real Estate", pd_12m=1.0),
               _account("C", sector="Energy", pd_12m=5.0)]
    closing = [_account("A", sector="Contracting", pd_12m=4.0),
               _account("B", sector="Real Estate", pd_12m=1.0),
               _account("C", sector="Energy", pd_12m=3.0)]
    out = dc.decompose(opening, closing, top=50)
    assert sum(s.effect for s in out.sectors) == pytest.approx(out.movement,
                                                              abs=1e-9)


def test_contributors_are_ranked_by_absolute_effect():
    """A decomposition has two interesting tails. Ranking by signed value
    would show a reader ten improvements and no deteriorations on a book that
    improved overall — and the deterioration is the half they need."""
    opening = [_account("UP", sector="A", pd_12m=1.0),
               _account("DOWN", sector="B", pd_12m=10.0),
               _account("FLAT", sector="C", pd_12m=3.0)]
    closing = [_account("UP", sector="A", pd_12m=2.0),
               _account("DOWN", sector="B", pd_12m=1.0),
               _account("FLAT", sector="C", pd_12m=3.0)]
    out = dc.decompose(opening, closing, top=50)
    assert [s.name for s in out.sectors][:2] == ["B", "A"]
    assert out.sectors[-1].effect == pytest.approx(0.0, abs=1e-12)


def test_adverse_and_favourable_are_separated():
    opening = [_account("A", pd_12m=2.0, lgd=50.0)]
    closing = [_account("A", pd_12m=4.0, lgd=40.0)]
    out = dc.decompose(opening, closing)
    assert [c.key for c in out.adverse] == [dc.PD]
    assert [c.key for c in out.favourable] == [dc.LGD]


def test_the_waterfall_starts_at_opening_and_lands_on_closing():
    """A waterfall is only a faithful picture because the decomposition is
    exact: the bars have to land on the closing bar, or the chart is a lie
    with a nice shape."""
    out = dc.decompose([_account("A", pd_12m=2.0)], [_account("A", pd_12m=5.0)],
                       opening_period="Q1 2026", closing_period="Q2 2026")
    rows = out.waterfall()
    assert rows[0]["kind"] == "total"
    assert rows[0]["value"] == pytest.approx(out.opening_total)
    assert rows[-1]["kind"] == "total"
    assert rows[-1]["value"] == pytest.approx(out.closing_total)
    steps = sum(r["value"] for r in rows if r["kind"] == "delta")
    assert rows[0]["value"] + steps == pytest.approx(rows[-1]["value"])


def test_it_says_what_it_proves_and_what_it_does_not():
    """P0.4's last requirement. A decomposition read as causation is worse
    than no decomposition, because it names a culprit."""
    out = dc.decompose([_account("A")], [_account("A", pd_12m=4.0)])
    assert any("sum exactly" in s for s in out.proves())
    assert any("order" in s for s in out.proves())
    assert any("does not establish cause" in s for s in out.does_not_prove())
    assert any("overlay" in s for s in out.does_not_prove())


def test_a_decomposition_that_fails_says_so_rather_than_raising():
    """An attribution must not take the figures down with it."""
    out = dc.decompose([object()], [object()])  # type: ignore[list-item]
    assert out.unavailable
    assert out.components == []


def test_an_account_with_a_zero_factor_stays_in_the_reconciliation():
    """Nothing multiplicative produces a loss out of a zero exposure. The
    account still has to reconcile — dropping it would silently change the
    total the decomposition claims to explain."""
    opening = [dc.Account(account_id="A", ead=0.0, pd_12m=0.0, lgd=40.0,
                          model_ecl=0.0, total_ecl=0.0),
               _account("B", ead=100.0)]
    closing = [dc.Account(account_id="A", ead=100.0, pd_12m=3.0, lgd=40.0,
                          model_ecl=1.2, total_ecl=1.2),
               _account("B", ead=100.0)]
    out = dc.decompose(opening, closing)
    assert out.reconciles
    assert out.attributed == pytest.approx(out.movement, abs=1e-9)


# ------------------------------------------- the method definition on screen


def test_the_library_cases_agree_with_the_engine():
    """The diagnostic cases shown in Analysis Studio have to be true.

    A methodology owner reads those numbers and checks them with a pencil; a
    definition whose worked example disagrees with the engine is worse than one
    with no example, because it teaches the reader the wrong arithmetic. The
    expectations are written by hand in the library and asserted here against
    what the engine actually produces — never the other way round.
    """
    from backend.studio import library as lb

    method = next(m for m in lb.IFRS9 if m.id == dc.METHOD_ID)
    cases = {c.id: c for c in method.test_cases}
    assert cases, "the certified method carries no diagnostic cases"

    exposure = dc.decompose([_account("A", ead=100.0)],
                            [_account("A", ead=150.0)])
    stated = cases["exposure_only"].expected
    assert exposure.movement == pytest.approx(stated["movement"])
    assert exposure.component(dc.EXPOSURE).effect == pytest.approx(
        stated["exposure"])
    assert exposure.component(dc.PD).effect == pytest.approx(stated["pd"],
                                                             abs=1e-12)

    stage = dc.decompose([_account("A", stage=1)], [_account("A", stage=2)])
    stated = cases["stage_only"].expected
    assert stage.movement == pytest.approx(stated["movement"])
    assert stage.component(dc.STAGE).effect == pytest.approx(
        stated["stage_migration"])
    assert stage.component(dc.PD).effect == pytest.approx(stated["pd"],
                                                          abs=1e-12)

    arrival = dc.decompose([_account("A")], [_account("A"), _account("B")])
    stated = cases["arrival"].expected
    assert arrival.movement == pytest.approx(stated["movement"])
    assert arrival.component(dc.NEW_ACCOUNTS).effect == pytest.approx(
        stated["new_accounts"])

    stated = cases["order_neutral"].expected
    assert dc.shapley((1.0, 1.0), (2.0, 2.0)) == pytest.approx(
        (stated["factor_a"], stated["factor_b"]))


def test_the_certified_method_is_wired_to_a_real_implementation():
    """A certified entry whose engine name resolves to nothing is a tick with
    no method behind it, which devalues the honest ticks beside it."""
    from backend.studio import library as lb
    from backend.studio.model import Lifecycle

    method = next(m for m in lb.IFRS9 if m.id == dc.METHOD_ID)
    assert method.lifecycle == Lifecycle.CERTIFIED
    assert method.engine_analysis == dc.METHOD_ID
    assert method.methodology.strip()
    assert method.limitations.strip()
    assert method.required_fields


# --------------------------------------------------------- routing the question


@pytest.mark.parametrize("question", [
    "Decompose the change in total ECL over the latest year into changes "
    "associated with exposure, Stage migration, PD, LGD and portfolio mix. "
    "Show which sectors and customers contributed most.",
    "What drove the increase in ECL between Q1 2026 and Q2 2026?",
    "Bridge the movement in impairment from Q2 2025 to Q2 2026.",
    "Show me an ECL waterfall for the last year.",
    "Attribute the change in provisions to PD, LGD and exposure.",
])
def test_a_decomposition_question_is_recognised(question):
    assert dc.wants(question) is True


@pytest.mark.parametrize("question", [
    "How did ECL change between Q1 2026 and Q2 2026?",
    "What is total ECL by sector?",
    "What drove the increase in days past due?",
    "Show the top 10 borrowers by exposure at default.",
    "Which customers moved to Stage 2?",
])
def test_an_ordinary_question_is_not_routed_here(question):
    """Deliberately narrow. This method reads the whole book at row level and
    produces a nine-component attribution; running it for 'how did ECL change'
    would answer a simple question with a committee paper."""
    assert dc.wants(question) is False


def test_the_defect_d_question_no_longer_asks_which_exposure_is_meant():
    """Defect D, at the routing layer. 'exposure' in that question names a
    DRIVER, not the measure to compute — and the ambiguity gate read it as the
    measure, so the question that most needed this method was answered with a
    menu asking which exposure figure to use."""
    from backend.orchestration import orchestrator as orc

    question = ("Decompose the change in total ECL over the latest year into "
                "changes associated with exposure, Stage migration, PD, LGD "
                "and portfolio mix. Show which sectors and customers "
                "contributed most.")
    answered = orc.answer(question)
    assert not answered.clarification
    assert not answered.failure
    assert answered.result is not None

    found = answered.result.detail["decomposition"]
    assert found["reconciles"] is True
    assert found["attributed"] == pytest.approx(found["movement"], abs=1e-6)
    # Every objective the question named: the five drivers, the sectors and
    # the customers. Answering four of six is what Defect D was.
    named = {row["component"] for row in answered.result.rows}
    for key in (dc.EXPOSURE, dc.STAGE, dc.PD, dc.LGD, dc.MIX):
        assert dc.LABELS[key] in named
    assert found["sectors"]
    assert found["customers"]


def test_the_answer_is_drawn_as_a_waterfall_and_says_a_calculation_ran():
    """A decomposition reported as a metadata lookup would make the Trace say
    nothing was computed, which is the contradiction P0.9 exists to prevent."""
    from backend.orchestration import orchestrator as orc

    answered = orc.answer("Bridge the movement in ECL over the last year.")
    assert answered.result is not None
    assert answered.result.execution == "computed"
    assert answered.result.chart.get("chart") == "waterfall"
