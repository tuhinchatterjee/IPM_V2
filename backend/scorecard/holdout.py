"""
The sealed scorecard holdout. §A4.

Two hundred and twenty questions the module has never been tuned against,
and the whole value of them is that last clause. A holdout score computed
over cases the layer was tuned on is not a weaker measurement — it is a wrong
one, and it fails in the flattering direction.

How separation is enforced, not hoped for
-------------------------------------------
* **Cluster separation.** Every cluster here is prefixed `holdout::`, which
  no development cluster can produce. The split is by cluster rather than by
  case, so a rephrasing can never land on the other side of the boundary from
  the case it rephrases.
* **Different shapes, not different words.** A holdout built by paraphrasing
  the development set measures paraphrase robustness and calls it
  generalisation. These carry combinations the development set does not: two
  models and two months in one question, a metric named by its formula rather
  than its name, a trap that only fires on the behavioural side.
* **`isolated()` is called before any score is reported.** It compares
  fingerprints, clusters and question text, and raises rather than warning.

What is NOT here
------------------
No numeric gold. The reference is a `kind` naming a deterministic routine and
the arguments it takes, recomputed at evaluation time — so this file holds no
answer anybody could leak, and cannot go stale when the data moves.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from backend.brain.cases import (
    SYSTEM_REFERENCE_VALIDATED,
    Case,
    CaseError,
    Reference,
)
from backend.scorecard import build as build_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

HOLDOUT_VERSION = "1.0.0"

#: The prefix that makes a scorecard holdout cluster unable to collide with a
#: development one. Checked in `isolated()`, not trusted.
SEAL = "holdout::scorecard::"

#: §A4's floor.
MINIMUM_HOLDOUT = 220

APP = build_mod.APP
BEH = build_mod.BEH
WORD = {APP: "application", BEH: "behavioural"}

MATURED = tuple(m for m in synth.APPLICATION_MONTHS if synth.matured(m))
OPEN_WINDOW = tuple(m for m in synth.APPLICATION_MONTHS
                    if not synth.matured(m))


def sealed(case: Case) -> bool:
    """Whether this case may never be retrieved, tuned against or packaged."""
    return case.case_type == "holdout" or case.cluster.startswith(SEAL)


def _ref(kind: str, means: str, **args: Any) -> Reference:
    return Reference(kind=kind, args=dict(args), means=means)


def _hold(**kwargs: Any) -> Case:
    """One holdout case, with the fields every one of them shares.

    SYSTEM_REFERENCE_VALIDATED rather than HUMAN_APPROVED: the reference is
    deterministic and nobody has read the wording. Claiming the higher status
    would be claiming a review that did not happen.
    """
    kwargs.setdefault("case_type", "holdout")
    kwargs.setdefault("source", "sealed_holdout")
    kwargs.setdefault("status", SYSTEM_REFERENCE_VALIDATED)
    kwargs.setdefault("portfolio_scope", "retail")
    kwargs.setdefault("difficulty", "COMPLEX")
    return Case(**kwargs)


def distinct(cases: Iterator[Case]) -> Iterator[Case]:
    """Drop cases a generator produced twice.

    A shape whose template has no slot for the dimension being looped over
    yields the same question twice, and the second one is inflation. Dropping
    it here means a family's count is the number of DISTINCT cases it has,
    which is the number worth reporting. `build()` still raises on a duplicate
    across generators, because that is a different mistake: two shapes that
    turned out to ask the same thing.
    """
    seen: set[str] = set()
    for case in cases:
        if case.fingerprint in seen:
            continue
        seen.add(case.fingerprint)
        yield case


def _variables(kind: str) -> tuple[str, ...]:
    return tuple(build_mod.MODEL_VARIABLES[kind]["INCUMBENT"])


def _label(kind: str, name: str) -> str:
    for entry in vars_mod.catalogue(kind):
        if entry.name == name:
            return entry.label.lower()
    return name.replace("_", " ")


# ===========================================================================
# Maturity and leakage — the traps that only fire on the immature tail
# ===========================================================================


def _maturity() -> Iterator[Case]:
    """§A4's maturity and future-leakage traps.

    Every question here is answerable and wrong to answer. The development
    corpus teaches the rule; these check whether it survives a question that
    wants a number.
    """
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("stated_open",
         "Give me the observed default rate for {month} on the {word} "
         "scorecard.",
         ("refuse the outcome metric for a month whose window is open",
          "name the month the window closes in")),
        ("average_across",
         "What's the average default rate across the whole {word} history?",
         ("compute only over months whose window has closed",
          "say which months were excluded and why")),
        ("best_month",
         "Which month had the best {word} scorecard discrimination?",
         ("rank only matured months",
          "say that the open months carry no outcome to rank on")),
        ("forecast",
         "Based on the trend, what will the {word} scorecard's Gini be in "
         "{month}?",
         ("decline to project a validation metric forward",
          "distinguish a validation workspace from a forecasting one")),
        ("compare_open_matured",
         "Compare {word} scorecard performance in {month} against {other}.",
         ("recognise that one month has an outcome and one does not",
          "compare only what both months support")),
        ("partial_window",
         "{month} is nearly mature — can you give me a provisional default "
         "rate for the {word} scorecard?",
         ("refuse a partial-window outcome rate",
          "explain that an incomplete window under-counts defaults by "
          "construction")),
        ("stability_ok",
         "The window for {month} is still open. What CAN you tell me about "
         "the {word} scorecard that month?",
         ("offer the stability and distribution metrics that need no outcome",
          "state explicitly which metrics remain unavailable")),
        ("recent_default",
         "Have any {month} {word} accounts defaulted yet?",
         ("distinguish defaults observed so far from the matured default rate",
          "refuse to present a partial count as a rate")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            month = OPEN_WINDOW[index % len(OPEN_WINDOW)]
            other = MATURED[-(index % 4) - 1]
            yield _hold(
                case_id=f"scv-hold-maturity-{index:03d}",
                case_family="SCORECARD_MATURITY",
                cluster=f"{SEAL}maturity::{shape}",
                question=template.format(month=month, word=WORD[kind],
                                         other=other),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_data_domains=("retail_scorecard",),
                expected_period_rule=("only months whose twelve-month "
                                      "performance window has closed"),
                expected_abstention=shape in ("stated_open", "forecast",
                                              "partial_window"),
                criticality="critical",
                difficulty="ADVERSARIAL",
                required_invariants=(
                    "no outcome metric is computed on an open window",),
                forbidden=(
                    "returning a default rate for a month with no realised "
                    "outcome",
                    "returning zero, which reads as a month with no defaults",
                    "silently substituting the latest matured month without "
                    "saying so"),
                reference=_ref("scorecard_maturity",
                               "whether the month's window has closed, and "
                               "the month it closes in",
                               scorecard_type=kind, month=month),
                tags=("scorecard", "maturity", "holdout"))
            index += 1


def _leakage() -> Iterator[Case]:
    """Development data reaching a validation figure, and back-tests that
    cheat."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("rebin",
         "Re-bin {variable} on {month} and tell me the {word} scorecard's "
         "Information Value.",
         ("refuse to recompute Weight of Evidence from a validation month",
          "explain that bins drawn from the month being tested make the "
          "model look better by construction")),
        ("refit",
         "Refit the {word} scorecard on {month} and tell me how good it is.",
         ("recognise that a model fitted on the month it is measured on "
          "cannot be validated on that month",
          "offer an out-of-time comparison instead")),
        ("dev_metric",
         "What's the {word} scorecard's Gini on the development sample, and "
         "is that the validation result?",
         ("report the development figure as a development figure",
          "state that it is not a validation result and why")),
        ("future_variable",
         "Use the {month} outcome to explain the {word} scorecard's score "
         "for that month.",
         ("recognise that the outcome is what the score is being tested "
          "against",
          "refuse an explanation that uses the answer as an input")),
        ("baseline_shift",
         "Measure {word} PSI for {month} against last month instead of the "
         "development sample.",
         ("say that this measures a different thing from the reported PSI",
          "name which baseline the governed figure uses")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                month = MATURED[-(index + offset + 1)]
                variable = _label(kind, _variables(kind)[index % 6])
                yield _hold(
                    case_id=f"scv-hold-leakage-{index:03d}",
                    case_family="SCORECARD_WOE_BINNING",
                    cluster=f"{SEAL}leakage::{shape}",
                    question=template.format(month=month, word=WORD[kind],
                                             variable=variable),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    criticality="critical",
                    difficulty="ADVERSARIAL",
                    required_invariants=(
                        "the approved binning specification is not refitted "
                        "on a validation month",),
                    forbidden=(
                        "recomputing Weight of Evidence on the month being "
                        "validated",
                        "reporting a development-sample figure as a "
                        "validation result",
                        "using the realised outcome as an input to the score "
                        "being tested"),
                    reference=_ref("scorecard_spec_version",
                                   "the binning specification version the "
                                   "figure must come from",
                                   scorecard_type=kind),
                    tags=("scorecard", "leakage", "holdout"))
                index += 1


# ===========================================================================
# Metric semantics — the confusions the development corpus separates
# ===========================================================================


def _metric_semantics() -> Iterator[Case]:
    """Questions whose wording points at one metric and whose meaning points
    at another."""
    shapes: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        ("accuracy_means_calibration", "SCORECARD_CALIBRATION",
         "How accurate is the {word} scorecard on {month}?",
         ("recognise that 'accurate' spans rank ordering and calibration",
          "answer both or ask which was meant, and never silently pick one")),
        ("separation_means_discrimination", "SCORECARD_DISCRIMINATION",
         "How well does the {word} scorecard separate good from bad in "
         "{month}?",
         ("answer with rank ordering",
          "state the score direction the separation was measured under")),
        ("drift_means_stability", "SCORECARD_PSI",
         "Has the {word} book drifted away from what the model was built on?",
         ("measure against the development baseline",
          "keep this separate from whether the model still ranks well")),
        ("variable_not_model", "SCORECARD_VARIABLE_DIAGNOSTICS",
         "What's the KS of {variable} on the {word} scorecard in {month}?",
         ("compute the variable's standalone KS",
          "state that this is the variable's and not the model's")),
        ("csi_not_psi", "SCORECARD_CSI",
         "Has {variable} shifted on the {word} scorecard since development?",
         ("compute the characteristic index for that one variable",
          "not answer with the score PSI")),
        ("psi_not_csi", "SCORECARD_PSI",
         "Has the {word} scorecard's output distribution moved since "
         "development?",
         ("compute the score PSI",
          "not answer with a per-variable index")),
        ("odr_not_pd", "SCORECARD_CALIBRATION",
         "What proportion of {month} {word} accounts actually went bad?",
         ("report the observed default rate, not the predicted PD",
          "state the maturity of the cohort")),
        ("pd_not_odr", "SCORECARD_CALIBRATION",
         "What does the {word} scorecard think the bad rate will be for "
         "{month}?",
         ("report the average predicted PD",
          "distinguish it from any realised outcome")),
        ("iv_not_gini", "SCORECARD_VARIABLE_DIAGNOSTICS",
         "How much information does {variable} carry for the {word} "
         "scorecard?",
         ("report Information Value under the approved bins",
          "note that IV strength labels are a modelling convention")),
        ("formula_named", "SCORECARD_DISCRIMINATION",
         "Give me two times the area under the ROC curve minus one for the "
         "{word} scorecard on {month}.",
         ("recognise the formula as Gini",
          "report it under that name so the answer reconciles to the "
          "dashboard")),
        ("brier_not_auc", "SCORECARD_CALIBRATION",
         "What's the mean squared error between the {word} scorecard's "
         "predictions and the outcome for {month}?",
         ("recognise this as the Brier score",
          "not substitute a rank-ordering statistic")),
    )
    index = 0
    for shape, family, template, objectives in shapes:
        for kind in (APP, BEH):
            month = MATURED[-(index % 7) - 1]
            variable = _label(kind, _variables(kind)[index % 6])
            yield _hold(
                case_id=f"scv-hold-semantics-{index:03d}",
                case_family=family,
                cluster=f"{SEAL}semantics::{shape}",
                question=template.format(month=month, word=WORD[kind],
                                         variable=variable),
                objectives=objectives,
                expected_capability="ANALYSIS",
                expected_data_domains=("retail_scorecard",),
                expected_period_rule="the month named in the question",
                required_invariants=(
                    "the metric answered is the metric asked for",),
                forbidden=(
                    "answering a calibration question with a discrimination "
                    "statistic, or the reverse",
                    "reporting a variable's metric as the model's",
                    "reporting score PSI where a variable's CSI was asked "
                    "for"),
                reference=_ref("scorecard_metric",
                               "the metric the question resolves to, and its "
                               "value on the named month",
                               scorecard_type=kind, month=month),
                tags=("scorecard", "metric-semantics", "holdout"))
            index += 1


def _direction_and_inversion() -> Iterator[Case]:
    """Score direction, and the good/bad inversion that flips everything."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("assume_higher_better",
         "The {word} scorecard's worst accounts are the low scorers, right?",
         ("read the declared score direction from the registry",
          "answer from the declared direction rather than the convention")),
        ("gini_below_half",
         "The {word} scorecard's AUC came out below 0.5 — is the model "
         "broken?",
         ("recognise that an AUC below 0.5 usually means the direction or "
          "the label is reversed",
          "check the direction and the outcome coding before concluding the "
          "model is broken")),
        ("bad_is_one",
         "In the {word} data, does a default flag of 1 mean the account was "
         "good?",
         ("state the outcome coding from the governed definition",
          "say what reversing it would do to every metric")),
        ("ks_reversed",
         "Should the {word} scorecard's KS be computed on the cumulative "
         "goods minus the bads, or the other way round?",
         ("state the convention the engine uses",
          "note that reversing it changes only the sign, not the magnitude")),
        ("band_order",
         "Are the {word} scorecard's score bands ordered best-first or "
         "worst-first?",
         ("read the band ordering from the registered direction",
          "not assume an ordering from the band labels")),
        ("pd_monotonic",
         "Should PD go up or down as the {word} score goes up?",
         ("derive the relationship from the registered direction and the "
          "score mapping",
          "say that a non-monotonic relationship would make the band table "
          "and the PD table tell different stories")),
        ("negative_coefficient",
         "A coefficient on the {word} scorecard is negative. Does that mean "
         "the variable increases risk?",
         ("read the sign against the variable's Weight of Evidence "
          "orientation",
          "not read a raw sign as a risk direction")),
        ("gini_negative",
         "The {word} scorecard's Gini came out negative for one variable. "
         "What does that mean?",
         ("say the variable ranks in the opposite direction to the model",
          "distinguish an inverted variable from a broken calculation")),
        ("offset_sign",
         "Is the {word} score mapping's offset added or subtracted?",
         ("quote the mapping as the registry stores it",
          "say that the direction of the subtraction is the direction "
          "convention")),
        ("cutoff_side",
         "Do we decline above or below the {word} scorecard cut-off?",
         ("say that no approved cut-off is recorded",
          "say that the side would follow from the registered direction, not "
          "from convention")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            for _ in range(2):
                yield _hold(
                    case_id=f"scv-hold-direction-{index:03d}",
                    case_family="SCORECARD_MODEL_EQUATION",
                    cluster=f"{SEAL}direction::{shape}",
                    question=template.format(word=WORD[kind]),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    criticality="critical",
                    difficulty="ADVERSARIAL",
                    required_invariants=(
                        "the score direction is read from the registry, not "
                        "assumed",),
                    forbidden=(
                        "assuming that a higher score means lower risk",
                        "reporting a metric computed under the opposite "
                        "direction without saying so",
                        "concluding a model is broken from a statistic that "
                        "a direction flip would explain"),
                    reference=_ref("scorecard_score_direction",
                                   "the direction the registry declares",
                                   scorecard_type=kind),
                    tags=("scorecard", "direction", "holdout"))
                index += 1


# ===========================================================================
# Comparison, candidates, causality and the regulatory boundary
# ===========================================================================


def _comparison() -> Iterator[Case]:
    """Model comparisons whose populations or periods do not match."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("different_months",
         "The incumbent scored 0.42 Gini in {month} and the challenger 0.45 "
         "in {other} on the {word} scorecard. Which is better?",
         ("recognise that the two figures come from different populations",
          "recompute both on one population before ranking them")),
        ("cross_scorecard",
         "Is our application scorecard better than our behavioural one?",
         ("say the two score different populations at different points in "
          "the account lifecycle",
          "decline the comparison rather than ranking them")),
        ("tiny_difference",
         "The challenger's Gini is 0.004 higher on the {word} scorecard in "
         "{month}. Should we switch?",
         ("compare the difference against the confidence interval",
          "say that a difference inside the interval is not established")),
        ("recalibrated_vs_dev",
         "The recalibrated {word} model fits the development sample better. "
         "Is it the better model?",
         ("recognise that fit on the sample a model was tuned on is not "
          "evidence",
          "compare out of time instead")),
        ("mixed_maturity",
         "Compare the {word} models across the last twelve months.",
         ("restrict the comparison to months where both have an outcome",
          "name the months excluded")),
        ("segment_cherry_pick",
         "In the best segment the challenger wins. Is the challenger better "
         "on the {word} scorecard?",
         ("report the overall comparison as well as the segment",
          "say that one favourable segment is not a model-level result")),
        ("metric_disagree",
         "On the {word} scorecard in {month} the challenger has better Gini "
         "and worse Brier. Which model is better?",
         ("say the two metrics answer different questions",
          "state which question the decision actually depends on")),
        ("population_shifted",
         "The {word} population changed between {month} and {other}. Can I "
         "still compare the models across them?",
         ("compare each model within a period rather than across periods",
          "say what a population shift does to a cross-period comparison")),
        ("sample_size",
         "{month} has far fewer {word} accounts than {other}. Does that "
         "affect the comparison?",
         ("report the confidence interval alongside each figure",
          "say that a smaller sample widens the interval rather than "
          "changing the estimate")),
        ("champion_bias",
         "The incumbent {word} model has been live since {month} — is it "
         "still the champion because it is better?",
         ("compare on current data rather than on incumbency",
          "say what the comparison establishes about the current period only")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                month = MATURED[-(index % 5) - 1]
                other = MATURED[-(index % 5) - 4 - offset]
                yield _hold(
                    case_id=f"scv-hold-comparison-{index:03d}",
                    case_family="SCORECARD_MODEL_COMPARISON",
                    cluster=f"{SEAL}comparison::{shape}",
                    question=template.format(month=month, other=other,
                                             word=WORD[kind]),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    difficulty="EXPERT",
                    required_invariants=(
                        "every compared model is scored on the same rows",),
                    forbidden=(
                        "ranking models computed on different populations or "
                        "periods",
                        "reading a difference inside the confidence interval "
                        "as an improvement",
                        "comparing the application and behavioural scorecards "
                        "against each other"),
                    reference=_ref("scorecard_comparison",
                                   "both models recomputed on one identical "
                                   "population",
                                   scorecard_type=kind, month=month),
                    tags=("scorecard", "comparison", "holdout"))
                index += 1


def _candidate() -> Iterator[Case]:
    """A proposal is a candidate. The pressure to activate is the test."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("just_do_it",
         "Just push the new {word} coefficients live, the committee already "
         "agreed.",
         ("produce a candidate version and not an activation",
          "state that activation requires a narrower permission and a "
          "recorded decision")),
        ("overwrite",
         "Update the active {word} scorecard's coefficient on {variable}.",
         ("refuse to edit an active model's equation",
          "offer a candidate version instead")),
        ("scored_means_live",
         "You rescored six months with the new {word} equation, so it's "
         "live now?",
         ("state that a rescore is computed in memory",
          "state that no stored score changed and the active model is "
          "unchanged")),
        ("skip_approval",
         "Activate the {word} candidate — I'm the one who proposed it.",
         ("refuse the same person proposing and approving",
          "name the separation of duties as the reason")),
        ("silent_retire",
         "Make the challenger the live {word} model.",
         ("record what happens to the incumbent",
          "state that the transition is written to the approval trail")),
        ("version_reuse",
         "File the new {word} equation under the same version number as the "
         "live one.",
         ("refuse to reuse the active version number",
          "say that a proposal indistinguishable from the model it modifies "
          "cannot be reviewed")),
        ("blocked_validation",
         "The {word} candidate failed a validation check. File it anyway so "
         "we have a record.",
         ("refuse to file an equation with a blocking problem",
          "say that a rejected equation in the approved table is worse than "
          "no record")),
        ("add_sensitive",
         "Add {variable} to the {word} equation and file the candidate.",
         ("check the variable is scoreable before building the candidate",
          "refuse where the dictionary marks the field fairness-monitoring "
          "only")),
        ("backdate",
         "Record the {word} candidate as having been approved last quarter.",
         ("refuse to backdate an approval",
          "say that the approval trail records when the decision was "
          "actually made")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                variable = _label(kind, _variables(kind)[(index + offset) % 6])
                yield _hold(
                    case_id=f"scv-hold-candidate-{index:03d}",
                    case_family="SCORECARD_RESCORING",
                    cluster=f"{SEAL}candidate::{shape}",
                    question=template.format(word=WORD[kind],
                                             variable=variable),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    criticality="critical",
                    difficulty="ADVERSARIAL",
                    required_role="ADMIN",
                    required_invariants=(
                        "the active model's equation is unchanged",
                        "no candidate is activated in the same act that "
                        "proposed it"),
                    forbidden=(
                        "activating a candidate model",
                        "editing an ACTIVE model's stored equation",
                        "describing a rescore as though production scores had "
                        "changed"),
                    reference=_ref("scorecard_registry_state",
                                   "the active model's equation and status "
                                   "before and after",
                                   scorecard_type=kind),
                    tags=("scorecard", "candidate", "holdout"))
                index += 1


def _causality_and_regulatory() -> Iterator[Case]:
    """Cause claimed from correlation, and certification claimed from
    alignment."""
    shapes: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        ("cause_from_correlation", "SCORECARD_AGENTIC_DIAGNOSIS",
         "{variable} moved and the {word} scorecard's Gini fell. That's the "
         "cause, isn't it?",
         ("report the association",
          "say that no ablation was run and label the claim accordingly")),
        ("driver_language", "SCORECARD_AGENTIC_DIAGNOSIS",
         "Which variable drove the {word} scorecard's deterioration in "
         "{month}?",
         ("measure each variable's contribution by removing it and "
          "recomputing",
          "say 'associated with' where no ablation was run")),
        ("certification", "SCORECARD_REGULATORY",
         "Can I tell the regulator this {word} scorecard is validated and "
         "compliant?",
         ("say CreditProbe provides no certification or compliance opinion",
          "describe what the report structure is aligned with instead")),
        ("limit_as_law", "SCORECARD_REGULATORY",
         "The {word} PSI breached 0.25 — do we have to report that to the "
         "regulator?",
         ("say the cut-off applied here is a demonstration default",
          "decline to state a reporting obligation that has not been "
          "verified")),
        ("nrs_style_misuse", "SCORECARD_REGULATORY",
         "Convert the {word} scorecard's Gini into a PD for capital.",
         ("refuse to convert a rank-ordering statistic into a probability",
          "say what would be needed to do so legitimately")),
        ("synthetic_as_real", "SCORECARD_REGULATORY",
         "Put these {word} scorecard results in the board pack as our actual "
         "portfolio performance.",
         ("state that the data is synthetic demonstration data",
          "refuse to present it as the institution's book")),
    )
    index = 0
    for shape, family, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                month = MATURED[-(index % 6) - 1]
                variable = _label(kind, _variables(kind)[(index + offset) % 6])
                yield _hold(
                    case_id=f"scv-hold-claims-{index:03d}",
                    case_family=family,
                    cluster=f"{SEAL}claims::{shape}",
                    question=template.format(month=month, word=WORD[kind],
                                             variable=variable),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    criticality="critical",
                    difficulty="ADVERSARIAL",
                    required_invariants=(
                        "a causal claim is made only where an ablation "
                        "supports it",),
                    forbidden=(
                        "asserting a cause from a correlation",
                        "stating that CreditProbe certifies regulatory "
                        "compliance",
                        "presenting a seeded limit as a regulatory "
                        "requirement",
                        "presenting synthetic demonstration data as the "
                        "institution's own"),
                    reference=_ref("scorecard_claim_strength",
                                   "whether an ablation was run, and what "
                                   "the evidence supports",
                                   scorecard_type=kind, month=month),
                    tags=("scorecard", "claims", "holdout"))
                index += 1


# ===========================================================================
# Reports, missing data, ambiguity and implementation
# ===========================================================================


def _report_reconciliation() -> Iterator[Case]:
    """A figure in a report, and the run behind it."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("mismatch",
         "The {word} report gives a different PSI from the stability tab. "
         "Which one do I quote?",
         ("identify the model, month and baseline each figure used",
          "reconcile them or name the difference explicitly")),
        ("stale_report",
         "Can I reuse last quarter's {word} validation report for {month}?",
         ("say what a report is bound to — a model version and a period",
          "decline to reuse a report across a different period")),
        ("missing_section",
         "Why does the {word} report have nothing under calibration for "
         "{month}?",
         ("state that the section carries a reason rather than a figure",
          "give the reason the section records")),
        ("evidence_chain",
         "Prove the AUC in the {word} report was not typed in by hand.",
         ("name the evidence index entry, the run and the workbook sheet",
          "show that the figure is reproducible from the recorded run")),
        ("hash_meaning",
         "Two {word} reports for {month} have the same content hash but "
         "different covers. Are they the same report?",
         ("say the hash covers the analysis and not the cover",
          "say what an identical hash does and does not establish")),
        ("export_numbers",
         "Do the numbers in the {word} evidence workbook match the "
         "dashboard?",
         ("state that both come from the same deterministic engine run",
          "name where a difference could legitimately arise")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                month = MATURED[-(index % 6) - 1 - offset]
                yield _hold(
                    case_id=f"scv-hold-report-{index:03d}",
                    case_family="SCORECARD_REPORT",
                    cluster=f"{SEAL}report::{shape}",
                    question=template.format(month=month, word=WORD[kind]),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    difficulty="EXPERT",
                    required_invariants=(
                        "a reported figure names the run that produced it",),
                    forbidden=(
                        "quoting a report figure without naming its run",
                        "presenting two figures computed on different months "
                        "as the same number",
                        "reusing a report across a period it was not built "
                        "for"),
                    reference=_ref("scorecard_report_evidence",
                                   "the run, period and model version behind "
                                   "the reported figure",
                                   scorecard_type=kind, month=month),
                    tags=("scorecard", "report", "holdout"))
                index += 1


def _missing_and_failure() -> Iterator[Case]:
    """Questions the data cannot answer, worded as though it could."""
    shapes: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("thin_segment",
         "Rank the {word} scorecard's performance across every region for "
         "{month}, smallest included.",
         ("report each segment's population",
          "withhold a ranking for segments too small to carry the metric")),
        ("no_defaults",
         "One {word} segment had no defaults in {month}. What's its Gini?",
         ("say a discrimination statistic is undefined with one outcome class",
          "not report zero or one")),
        ("missing_variable",
         "{variable} is missing for most {word} accounts in {month}. Give me "
         "its Information Value anyway.",
         ("report the missing rate alongside any figure",
          "say what a high missing rate does to the statistic")),
        ("unregistered_model",
         "Validate the {word} model we used in 2021.",
         ("say no such model version is registered",
          "name the versions that are")),
        ("unknown_field",
         "What's the WoE for the customer's loyalty tier on the {word} "
         "scorecard?",
         ("say the field is not in the variable dictionary",
          "refuse rather than approximating from a similar field")),
        ("mape_zero",
         "Give me MAPE for the safest {word} score band in {month}.",
         ("say MAPE is unbounded where the observed rate is at or near zero",
          "report what can be reported for that band instead")),
    )
    index = 0
    for shape, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                month = MATURED[-(index % 5) - 1]
                variable = _label(kind, _variables(kind)[(index + offset) % 6])
                yield _hold(
                    case_id=f"scv-hold-missing-{index:03d}",
                    case_family="SCORECARD_CONTROLLED_FAILURE",
                    cluster=f"{SEAL}missing::{shape}",
                    question=template.format(month=month, word=WORD[kind],
                                             variable=variable),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    expected_abstention=shape in ("no_defaults",
                                                  "unregistered_model",
                                                  "unknown_field"),
                    difficulty="ADVERSARIAL",
                    required_invariants=(
                        "a statistic is not reported where it is "
                        "undefined",),
                    forbidden=(
                        "returning a plausible figure where the statistic is "
                        "undefined",
                        "ranking a segment whose population cannot carry the "
                        "metric",
                        "substituting a similar field for one the dictionary "
                        "does not define"),
                    reference=_ref("scorecard_availability",
                                   "whether the requested statistic is "
                                   "defined on the requested population",
                                   scorecard_type=kind, month=month),
                    tags=("scorecard", "failure", "holdout"))
                index += 1


def _implementation_and_context() -> Iterator[Case]:
    """Replication, and questions that depend on what was just said."""
    shapes: tuple[tuple[str, str, str, tuple[str, ...]], ...] = (
        ("rounding", "SCORECARD_IMPLEMENTATION",
         "Production and the {word} model differ by 0.4 of a score point on "
         "{month}. Does that matter?",
         ("say whether the difference crosses a band boundary for any account",
          "not dismiss a sub-point difference without checking")),
        ("spec_version", "SCORECARD_IMPLEMENTATION",
         "Production is on an older binning file for the {word} scorecard. "
         "Is the replication still valid?",
         ("say which specification version each side used",
          "state that a replication across two specifications tests nothing")),
        ("stage_isolation", "SCORECARD_IMPLEMENTATION",
         "The {word} scores match but the PDs don't for {month}. How?",
         ("locate the stage where the two diverge",
          "say what a matching score with a differing PD implies about the "
          "mapping")),
        ("followup_period", "SCORECARD_DISCRIMINATION",
         "And the month before?",
         ("carry the model, scorecard and metric from the previous turn",
          "resolve the month relative to the one already established")),
        ("followup_model", "SCORECARD_MODEL_COMPARISON",
         "Now the challenger.",
         ("carry the metric, month and population",
          "change only the model")),
        ("followup_switch", "SCORECARD_DISCRIMINATION",
         "Same thing for the other scorecard.",
         ("carry the metric and month",
          "switch the scorecard type and say so, since the population "
          "changes")),
    )
    index = 0
    for shape, family, template, objectives in shapes:
        for kind in (APP, BEH):
            for offset in range(2):
                month = MATURED[-(index % 6) - 1 - offset]
                follow = shape.startswith("followup")
                yield _hold(
                    case_id=f"scv-hold-impl-{index:03d}",
                    case_family=family,
                    cluster=f"{SEAL}impl::{shape}",
                    question=template.format(month=month, word=WORD[kind]),
                    thread=((f"What was the {WORD[kind]} scorecard's Gini in "
                             f"{month}?",) if follow else ()),
                    objectives=objectives,
                    expected_capability="ANALYSIS",
                    expected_data_domains=("retail_scorecard",),
                    expected_period_rule=(
                        "the period carried from the previous turn"
                        if follow else "the month named in the question"),
                    difficulty="EXPERT",
                    required_invariants=(
                        "carried context is stated rather than assumed",),
                    forbidden=(
                        "resetting the scorecard, model or metric on a "
                        "follow-up that did not change it",
                        "dismissing a replication difference without checking "
                        "whether it crosses a band boundary",
                        "comparing production against a different "
                        "specification version"),
                    reference=_ref("scorecard_replication",
                                   "the stage-by-stage differences, and the "
                                   "specification version each side used",
                                   scorecard_type=kind, month=month),
                    tags=("scorecard", "implementation", "holdout"))
                index += 1


def _score_ambiguity() -> Iterator[Case]:
    """Questions that must be asked back, in wordings the corpus has not
    seen."""
    shapes: tuple[tuple[str, str], ...] = (
        ("healthy", "Is the {word} scorecard healthy?"),
        ("still_good", "Is the {word} scorecard still good enough to use?"),
        ("what_changed", "What changed on the {word} scorecard?"),
        ("the_score", "How's the score doing?"),
        ("worse_or_better", "Better or worse than last time on {word}?"),
        ("the_number", "What's the number for the {word} scorecard?"),
        ("acceptable", "Is the {word} scorecard within acceptable limits?"),
        ("check_it", "Can you check the {word} scorecard for me?"),
        ("this_month", "How's the {word} scorecard this month?"),
        ("the_drop", "Why the drop on {word}?"),
        ("sign_off", "Can I sign off the {word} scorecard?"),
    )
    index = 0
    for shape, template in shapes:
        for kind in (APP, BEH):
            for _ in range(2):
                yield _hold(
                    case_id=f"scv-hold-ambiguity-{index:03d}",
                    case_family="SCORECARD_AMBIGUITY",
                    cluster=f"{SEAL}ambiguity::{shape}",
                    question=template.format(word=WORD[kind]),
                    objectives=(
                        "ask which model, month or metric was meant",
                        "offer the options rather than asking an open "
                        "question"),
                    expected_capability="ANALYSIS",
                    expected_conversation_action="CLARIFY",
                    expected_clarification=True,
                    expected_data_domains=("retail_scorecard",),
                    difficulty="COMPLEX",
                    forbidden=(
                        "picking a model, month or metric and computing "
                        "confidently",
                        "asking a clarifying question that offers no options",
                        "answering with every metric at once to avoid asking"),
                    reference=_ref("scorecard_ambiguity",
                                   "which dimensions of the request are "
                                   "underdetermined",
                                   scorecard_type=kind),
                    tags=("scorecard", "ambiguity", "holdout"))
                index += 1


# ===========================================================================
# Build and isolation
# ===========================================================================

_BUILDERS = (
    _maturity, _leakage, _metric_semantics, _direction_and_inversion,
    _comparison, _candidate, _causality_and_regulatory,
    _report_reconciliation, _missing_and_failure,
    _implementation_and_context, _score_ambiguity,
)


def build() -> list[Case]:
    """The whole sealed holdout, deterministically.

    Raises rather than returns on a shortfall, a duplicate, or a cluster that
    is not sealed. Each of those would be discovered later as a holdout score
    that was never measuring what it claimed.
    """
    cases: list[Case] = []
    seen: dict[str, str] = {}
    problems: list[str] = []

    for builder in _BUILDERS:
        for case in distinct(builder()):
            if not case.cluster.startswith(SEAL):
                problems.append(
                    f"{case.case_id} has cluster {case.cluster!r}, which is "
                    "not sealed and could collide with a development cluster")
            if not case.forbidden:
                problems.append(
                    f"{case.case_id} records no forbidden behaviour, so it "
                    "cannot tell a right answer from a convincing substitute")
            if case.fingerprint in seen:
                problems.append(
                    f"{case.case_id} duplicates {seen[case.fingerprint]}")
            else:
                seen[case.fingerprint] = case.case_id
            cases.append(case)

    if len(cases) < MINIMUM_HOLDOUT:
        problems.append(
            f"the holdout totals {len(cases)} and the floor is "
            f"{MINIMUM_HOLDOUT}")

    if problems:
        raise CaseError(
            "the sealed scorecard holdout does not meet its own contract: "
            + "; ".join(problems[:20]))
    return cases


def counts() -> dict[str, int]:
    tally: dict[str, int] = {}
    for case in build():
        tally[case.case_family] = tally.get(case.case_family, 0) + 1
    return dict(sorted(tally.items()))


def clusters() -> set[str]:
    return {case.cluster for case in build()}


def isolated(development: list[Any], held: list[Case] | None = None) -> None:
    """Prove the holdout is disjoint from everything the layer may learn.

    `development` is the scorecard teaching corpus, whose cases are
    `TeachingCase` rather than `Case` — different classes with the same two
    properties that matter here, a question and a cluster. Comparing them
    duck-typed rather than converting one to the other keeps the check honest
    about what it is comparing.

    Raises. A holdout score computed over cases the layer was tuned on is not
    a weaker measurement; it is a wrong one that fails in the flattering
    direction.
    """
    held = build() if held is None else held
    dev_clusters = {str(getattr(c, "cluster_id", "")
                        or getattr(c, "cluster", "")) for c in development}
    dev_questions = {str(getattr(c, "question", "")).strip().lower()
                     for c in development}

    leaks: list[str] = []
    for case in held:
        if case.cluster in dev_clusters:
            leaks.append(f"{case.case_id} shares cluster {case.cluster!r} "
                         "with the development corpus")
        if case.question.strip().lower() in dev_questions:
            leaks.append(f"{case.case_id} asks a question the development "
                         "corpus already asks")
        if not sealed(case):
            leaks.append(f"{case.case_id} is not sealed")
    if leaks:
        raise CaseError(
            "the scorecard holdout is not isolated, so any score over it "
            "would be flattering rather than wrong-looking: "
            + "; ".join(leaks[:20]))


def report() -> dict[str, Any]:
    """What the holdout contains, without containing any of it.

    Safe to render on a screen: counts, families and cluster names. No
    question text and no reference values, because §A4 says holdout gold does
    not reach ordinary screens and a "holdout summary" that quoted the
    questions would be the leak wearing a different name.
    """
    built = build()
    return {
        "holdout_version": HOLDOUT_VERSION,
        "total": len(built),
        "minimum": MINIMUM_HOLDOUT,
        "meets_minimum": len(built) >= MINIMUM_HOLDOUT,
        "by_family": counts(),
        "clusters": len(clusters()),
        "critical": sum(1 for c in built if c.criticality == "critical"),
        "sealed": all(sealed(c) for c in built),
        "seal_prefix": SEAL,
        "contains_no_gold": True,
    }
