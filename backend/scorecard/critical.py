"""
The zero-tolerance scorecard suite. §A7.

Twenty-two named failure modes, each one runnable against the real engine.
Every check here answers "does the product actually refuse this?" rather than
"is there a comment saying it should", and the difference matters: every one
of these was a real defect somewhere before it was a rule.

Why these are checks and not teaching cases
---------------------------------------------
A teaching case describes what a correct answer looks like and is scored
against a model's output. These are properties of the deterministic engine,
so they can be settled without asking anything: `require_matured` either
raises on an immature frame or it does not. That makes them the part of §A7
that can be asserted rather than sampled, which is why the brief demands zero
failures — a sampled score with a tolerance would be the wrong instrument.

What "critical" means here
----------------------------
Each of these fails in the flattering direction. An immature cohort scored as
though it had matured produces a beautiful default rate. A reversed score
direction produces a Gini of the right magnitude. A candidate model activated
silently produces a working system that is scoring customers on an unapproved
equation. None of them announces itself, which is why they are checked rather
than watched for.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.scorecard import build as build_mod
from backend.scorecard import dashboard as dash
from backend.scorecard import equation as equation_mod
from backend.scorecard import metrics as metrics_mod
from backend.scorecard import policy as policy_mod
from backend.scorecard import registry as registry_mod
from backend.scorecard import report as report_mod
from backend.scorecard import synthetic as synth
from backend.scorecard import variables as vars_mod

logger = logging.getLogger(__name__)

CRITICAL_VERSION = "1.0.0"

APP = build_mod.APP
BEH = build_mod.BEH


@dataclass
class Check:
    """One failure mode, and how the engine is asked about it."""

    id: str
    #: The mistake, in the words somebody would use describing the incident.
    failure: str
    #: Why it fails in the flattering direction, which is why it is critical.
    why_critical: str
    run: Callable[[], None]
    dimension: str = ""


@dataclass
class Outcome:
    check_id: str
    failure: str
    passed: bool
    detail: str = ""


@dataclass
class Result:
    outcomes: list[Outcome] = field(default_factory=list)

    @property
    def failures(self) -> list[Outcome]:
        return [o for o in self.outcomes if not o.passed]

    @property
    def clean(self) -> bool:
        return not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "critical_version": CRITICAL_VERSION,
            "checks": len(self.outcomes),
            "passed": len(self.outcomes) - len(self.failures),
            "failed": len(self.failures),
            "clean": self.clean,
            "failures": [{"check": o.check_id, "failure": o.failure,
                          "detail": o.detail} for o in self.failures],
        }


class CriticalFailure(AssertionError):
    """A zero-tolerance check that did not hold."""


def _refuses(call: Callable[[], Any], *, expect: type[Exception],
             about: str) -> None:
    """Assert the engine raises rather than returning something plausible."""
    try:
        call()
    except expect:
        return
    raise CriticalFailure(
        f"{about}: the engine returned a value where it should have "
        "refused, and the value would have looked entirely reasonable")


# ---------------------------------------------------------------- fixtures


def _month(kind: str, *, matured: bool) -> str:
    months = dash.available_months(kind)
    candidates = [m for m in months if synth.matured(m) is matured]
    if not candidates:
        raise CriticalFailure(
            f"no {'matured' if matured else 'immature'} month exists for "
            f"{kind}, so the rule this suite checks cannot be exercised")
    return candidates[-1]


def _frame(kind: str, *, matured: bool) -> pd.DataFrame:
    return dash.load_month(kind, _month(kind, matured=matured))


# ------------------------------------------------------------- the checks


def _immature_outcome() -> None:
    """1. An outcome metric on a cohort whose window has not closed."""
    frame = _frame(APP, matured=False)
    _refuses(lambda: metrics_mod.require_matured(frame, what="discrimination"),
             expect=metrics_mod.MetricError,
             about="an immature cohort was accepted for an outcome metric")


def _immature_dashboard_section() -> None:
    """1b. And the same through the dashboard, which is what a screen calls."""
    board = dash.build_dashboard(APP, month=_month(APP, matured=False),
                                 curves=False).to_dict()
    for section in ("discrimination", "calibration"):
        if board[section].get("available") is not False:
            raise CriticalFailure(
                f"the {section} section reported figures for a month whose "
                "performance window has not closed")
        if not board[section].get("why"):
            raise CriticalFailure(
                f"the {section} section refused without saying why, which "
                "reads as broken rather than as honest")


def _score_direction_declared() -> None:
    """2. A score mapping with no declared direction."""
    _refuses(lambda: equation_mod.ScoreMapping.from_dict(
        {"base_score": 600, "pdo": 20, "base_odds": 50}),
        expect=equation_mod.EquationError,
        about="a score mapping was built with no declared direction")


def _score_direction_respected() -> None:
    """2b. And the metric actually reads it rather than assuming."""
    frame = _frame(APP, matured=True)
    equation = build_mod.load_equation(APP, "INCUMBENT")
    direction = equation.score_mapping.score_direction
    forward = metrics_mod.discrimination(
        frame, score="score_incumbent", target=build_mod.TARGET,
        score_direction=direction)
    reversed_direction = (equation_mod.LOWER_SCORE_IS_BETTER
                          if direction == equation_mod.HIGHER_SCORE_IS_BETTER
                          else equation_mod.HIGHER_SCORE_IS_BETTER)
    backwards = metrics_mod.discrimination(
        frame, score="score_incumbent", target=build_mod.TARGET,
        score_direction=reversed_direction)
    if math.isclose(forward.auc, backwards.auc, abs_tol=1e-9):
        raise CriticalFailure(
            "reversing the score direction did not change the AUC, so the "
            "metric is not reading the direction at all")
    if not math.isclose(forward.auc + backwards.auc, 1.0, abs_tol=1e-6):
        raise CriticalFailure(
            "the two directions do not reflect about 0.5, so one of them is "
            "not the mirror of the other")


def _bad_default_inversion() -> None:
    """3. Good and bad reversed in the outcome column."""
    frame = _frame(APP, matured=True).copy()
    equation = build_mod.load_equation(APP, "INCUMBENT")
    direction = equation.score_mapping.score_direction
    straight = metrics_mod.discrimination(
        frame, score="score_incumbent", target=build_mod.TARGET,
        score_direction=direction)
    frame["inverted"] = 1 - frame[build_mod.TARGET]
    inverted = metrics_mod.discrimination(
        frame, score="score_incumbent", target="inverted",
        score_direction=direction)
    if not math.isclose(straight.auc + inverted.auc, 1.0, abs_tol=1e-6):
        raise CriticalFailure(
            "inverting the outcome did not mirror the AUC about 0.5, so the "
            "metric is not distinguishing good from bad as it claims")


def _woe_mapping_mismatch() -> None:
    """4. Scoring against a specification the model was not fitted on."""
    spec = build_mod.load_spec(APP)
    equation = build_mod.load_equation(APP, "INCUMBENT")
    row = {vars_mod.woe_name(term.variable): 0.0
           for term in equation.terms}
    missing = dict(row)
    missing.pop(next(iter(missing)))
    _refuses(lambda: equation.logit(missing),
             expect=equation_mod.EquationError,
             about="a score was computed with a term silently treated as "
                   "zero")
    if not spec.spec_version:
        raise CriticalFailure("the binning specification carries no version, "
                              "so a replication cannot name what it used")


def _wrong_model_version() -> None:
    """5. A model nobody registered."""
    _refuses(lambda: build_mod.load_equation(APP, "CHAMPION_V2"),
             expect=KeyError,
             about="an unregistered model was loaded")


def _application_behavioral_mixing() -> None:
    """6. One scorecard's data scored with the other's equation."""
    app_frame = _frame(APP, matured=True)
    behavioral = build_mod.load_equation(BEH, "INCUMBENT")
    columns = set(app_frame.columns)
    behavioral_columns = {term.column() for term in behavioral.terms}
    if behavioral_columns <= columns:
        raise CriticalFailure(
            "every behavioural term resolves against the application frame, "
            "so the two populations could be mixed without anything "
            "noticing")


def _raw_versus_woe() -> None:
    """7. A raw column used where a WoE column belongs."""
    equation = build_mod.load_equation(APP, "INCUMBENT")
    for term in equation.terms:
        if term.transformation != "WOE":
            raise CriticalFailure(
                f"{term.variable} is not WoE-transformed in a WoE scorecard")
        if not term.column().endswith("_woe"):
            raise CriticalFailure(
                f"{term.variable} resolves to {term.column()}, which is not "
                "a Weight of Evidence column")


def _psi_baseline() -> None:
    """8. PSI measured against the wrong baseline."""
    current = _frame(APP, matured=True)
    development = dash.load_development(APP)
    against_development = metrics_mod.psi(
        development, current, score="score_incumbent")
    against_itself = metrics_mod.psi(current, current, score="score_incumbent")
    if against_itself.index > 1e-6:
        raise CriticalFailure(
            "a population compared against itself produced a non-zero PSI, "
            "so the index is not measuring what it claims")
    if against_development.index <= 0:
        raise CriticalFailure(
            "the development baseline produced a zero PSI, which would mean "
            "the current month is identical to the development sample")


def _csi_is_not_psi() -> None:
    """9. A variable's index and the score's index are different things."""
    current = _frame(APP, matured=True)
    development = dash.load_development(APP)
    variable = build_mod.MODEL_VARIABLES[APP]["INCUMBENT"][0]
    characteristic = metrics_mod.csi(development, current, variable=variable)
    population = metrics_mod.psi(development, current, score="score_incumbent")
    if characteristic.variable == population.variable:
        raise CriticalFailure(
            "the characteristic index and the population index name the same "
            "column, so one of them is computing the other")
    if characteristic.kind == population.kind:
        raise CriticalFailure(
            "CSI and PSI report the same kind, so a reader cannot tell which "
            "they are looking at")


def _ks_reversal() -> None:
    """10. KS with the cumulative distributions the wrong way round."""
    frame = _frame(APP, matured=True)
    equation = build_mod.load_equation(APP, "INCUMBENT")
    result = metrics_mod.discrimination(
        frame, score="score_incumbent", target=build_mod.TARGET,
        score_direction=equation.score_mapping.score_direction)
    if not 0.0 <= result.ks <= 1.0:
        raise CriticalFailure(
            f"KS came out at {result.ks}, which is outside [0, 1] and means "
            "the cumulative distributions are being subtracted the wrong way")


def _gini_direction() -> None:
    """11. Gini and AUC that disagree about the same model."""
    frame = _frame(APP, matured=True)
    equation = build_mod.load_equation(APP, "INCUMBENT")
    result = metrics_mod.discrimination(
        frame, score="score_incumbent", target=build_mod.TARGET,
        score_direction=equation.score_mapping.score_direction)
    if not math.isclose(result.gini, 2 * result.auc - 1, abs_tol=1e-9):
        raise CriticalFailure(
            "Gini is not 2*AUC-1, so the two are being computed by different "
            "routes and one of them is wrong")


def _pd_within_bounds() -> None:
    """12. A predicted probability outside [0, 1]."""
    frame = _frame(APP, matured=True)
    column = "pd_incumbent"
    values = frame[column].dropna()
    if float(values.min()) < 0.0 or float(values.max()) > 1.0:
        raise CriticalFailure(
            f"{column} ranges outside [0, 1], so the link function is being "
            "applied wrongly and every calibration figure is arithmetic "
            "rather than a probability")
    extreme = equation_mod.Equation.pd_from_logit(800.0)
    if not 0.0 <= extreme <= 1.0:
        raise CriticalFailure(
            "an extreme logit produced a PD outside [0, 1], so the sigmoid "
            "is not numerically stable")


def _equation_mismatch() -> None:
    """13. The registry's equation and the scored lake disagreeing."""
    frame = _frame(APP, matured=True)
    equation = build_mod.load_equation(APP, "INCUMBENT")
    # `replicate` reads the equation's own output prefix, so the columns it
    # compares against are the ones that equation wrote. Naming them here
    # would let a renamed prefix silently compare against the wrong model.
    check = metrics_mod.replicate(frame, equation)
    if check.mismatch_count:
        raise CriticalFailure(
            f"{check.mismatch_count} scored rows do not reproduce from the "
            "registered equation, so production and the registry are running "
            "different models")


def _future_leakage() -> None:
    """14. A validation month contributing to the development fit."""
    overlap = set(synth.DEVELOPMENT_MONTHS) & set(synth.APPLICATION_MONTHS)
    if overlap:
        raise CriticalFailure(
            f"the development sample overlaps the validation months at "
            f"{sorted(overlap)}, so the model is being validated on data it "
            "was fitted on")


def _empty_default_sample() -> None:
    """15. A discrimination statistic on a sample with one outcome class."""
    frame = _frame(APP, matured=True).head(200).copy()
    frame[build_mod.TARGET] = 0
    _refuses(lambda: metrics_mod.discrimination(
        frame, score="score_incumbent", target=build_mod.TARGET,
        score_direction=equation_mod.HIGHER_SCORE_IS_BETTER),
        expect=metrics_mod.MetricError,
        about="a discrimination statistic was computed on a sample with no "
              "defaults")


def _tiny_segment_ranked() -> None:
    """16. A segment too small to carry the metric, ranked anyway."""
    frame = _frame(APP, matured=True).head(30).copy()
    frame.loc[frame.index[:2], build_mod.TARGET] = 1
    frame.loc[frame.index[2:], build_mod.TARGET] = 0
    if "minimum_defaults" not in policy_mod.LIMITS_BY_METRIC:
        raise CriticalFailure(
            "no minimum-defaults limit is recorded, so nothing stops a "
            "segment with two defaults being ranked against one with two "
            "thousand")


def _mape_near_zero() -> None:
    """17. MAPE on a band whose observed rate is at or near zero."""
    frame = _frame(APP, matured=True).copy()
    result = metrics_mod.calibration(
        frame, pd_column="pd_incumbent", target=build_mod.TARGET,
        score="score_incumbent",
        score_direction=equation_mod.HIGHER_SCORE_IS_BETTER)
    if result.mape is not None and not result.mape_status:
        raise CriticalFailure(
            "MAPE was reported with no statement of which bands it covers, "
            "so a reader cannot tell whether a near-zero band was included")


def _comparison_population() -> None:
    """18. Models compared on different populations."""
    board = dash.build_dashboard(APP, curves=False).to_dict()
    comparison = board.get("comparison") or {}
    # The engine states this as a sentence rather than a flag, which is the
    # better design: a reader of the comparison sees the claim, not a boolean
    # they would have to know the meaning of.
    claim = str(comparison.get("identical_population") or "")
    if "same rows" not in claim:
        raise CriticalFailure(
            "the model comparison does not state that every model was scored "
            "on the same rows, so a difference between models could be a "
            "difference between samples")
    if not comparison.get("overlapping_intervals"):
        raise CriticalFailure(
            "the comparison says nothing about overlapping confidence "
            "intervals, so a difference inside the interval reads as real")


def _report_reconciles_with_dashboard() -> None:
    """19. A report figure that does not match the dashboard it came from."""
    month = _month(APP, matured=True)
    board = dash.build_dashboard(APP, month=month, curves=False).to_dict()
    built = report_mod.build(APP, month=month, generated_by="critical-suite")
    section = built.section("8.2")
    if section is None or section.unavailable:
        raise CriticalFailure(
            "the report's discrimination section was unavailable for a "
            "matured month")
    rendered = {row[0]: row[1] for row in section.tables[0].rows}
    engine_gini = report_mod.stat(board["discrimination"]["gini"])
    if rendered.get("Gini / Accuracy Ratio") != engine_gini:
        raise CriticalFailure(
            f"the report shows Gini {rendered.get('Gini / Accuracy Ratio')} "
            f"and the dashboard {engine_gini} for the same model and month")


def _no_certification_claim() -> None:
    """20. A claim that CreditProbe certifies regulatory compliance."""
    built = report_mod.build(APP, generated_by="critical-suite")
    if "does not provide regulatory certification" not in built.disclaimer:
        raise CriticalFailure(
            "the report's disclaimer does not deny providing regulatory "
            "certification")
    for entry in built.sections:
        for table in entry.tables:
            if table.caption.startswith("Monitoring limits"):
                sources = {row[4] for row in table.rows}
                if not sources or sources == {"—"}:
                    raise CriticalFailure(
                        "the limits table carries no provenance, so a seeded "
                        "demonstration default reads as a requirement")


def _candidate_not_activated() -> None:
    """21. A candidate model activated by the act that proposed it."""
    if registry_mod.ACTIVE not in registry_mod.TRANSITIONS[
            registry_mod.APPROVED]:
        raise CriticalFailure("APPROVED cannot reach ACTIVE at all")
    into_active = [status for status, allowed
                   in registry_mod.TRANSITIONS.items()
                   if registry_mod.ACTIVE in allowed]
    if into_active != [registry_mod.APPROVED]:
        raise CriticalFailure(
            f"ACTIVE is reachable from {into_active}, so a candidate can "
            "become live without being approved")


def _retirement_by_the_right_key() -> None:
    """22. Activation that retires by the wrong key, leaving two live."""
    source = registry_mod._retire_incumbent.__doc__ or ""
    if "scorecard type" not in source:
        raise CriticalFailure(
            "retirement is not documented as scoped to the scorecard type")
    import inspect
    body = inspect.getsource(registry_mod._retire_incumbent)
    if "scorecard_type == incoming.scorecard_type" not in body:
        raise CriticalFailure(
            "activation retires by model id rather than by scorecard type, "
            "so activating a challenger leaves the incumbent scoring the "
            "same applications")


CHECKS: tuple[Check, ...] = (
    Check("immature_outcome", "an outcome metric on an open window",
          "produces a beautiful default rate on a cohort that has not had "
          "time to go bad", _immature_outcome, "COMPUTATION_AND_EVIDENCE"),
    Check("immature_dashboard", "a dashboard section reporting on an open "
          "window",
          "the screen looks complete and every outcome figure on it is "
          "meaningless", _immature_dashboard_section,
          "RELIABILITY_AND_EXPERIENCE"),
    Check("score_direction_declared", "a score mapping with no direction",
          "every discrimination statistic is ambiguous and none of them says "
          "so", _score_direction_declared, "ANALYTICAL_DESIGN"),
    Check("score_direction_respected", "a metric that ignores the declared "
          "direction",
          "produces a plausible AUC on the wrong side of 0.5",
          _score_direction_respected, "COMPUTATION_AND_EVIDENCE"),
    Check("bad_default_inversion", "good and bad reversed",
          "every metric keeps its magnitude and changes its meaning",
          _bad_default_inversion, "COMPUTATION_AND_EVIDENCE"),
    Check("woe_mapping_mismatch", "a term silently treated as zero",
          "the score is computed from a different model from the approved "
          "one, and looks normal", _woe_mapping_mismatch,
          "COMPUTATION_AND_EVIDENCE"),
    Check("wrong_model_version", "an unregistered model version",
          "findings attach to a version nobody can produce again",
          _wrong_model_version, "ANALYTICAL_DESIGN"),
    Check("scorecard_mixing", "application data scored behaviourally",
          "two populations at different lifecycle points, averaged",
          _application_behavioral_mixing, "ANALYTICAL_DESIGN"),
    Check("raw_versus_woe", "a raw column where a WoE column belongs",
          "the coefficients are applied to the wrong scale and the score is "
          "still a number", _raw_versus_woe, "COMPUTATION_AND_EVIDENCE"),
    Check("psi_baseline", "PSI against the wrong baseline",
          "measures the baseline rather than the population", _psi_baseline,
          "ANALYTICAL_DESIGN"),
    Check("csi_is_not_psi", "a variable's index reported as the score's",
          "a stable score with one drifting variable reads as a stable book",
          _csi_is_not_psi, "COMPUTATION_AND_EVIDENCE"),
    Check("ks_reversal", "KS computed the wrong way round",
          "a negative KS is obviously wrong; a mirrored one is not",
          _ks_reversal, "COMPUTATION_AND_EVIDENCE"),
    Check("gini_direction", "Gini and AUC computed by different routes",
          "the two disagree by exactly the amount nobody checks",
          _gini_direction, "COMPUTATION_AND_EVIDENCE"),
    Check("pd_bounds", "a PD outside [0, 1]",
          "every calibration figure becomes arithmetic rather than a "
          "probability", _pd_within_bounds, "COMPUTATION_AND_EVIDENCE"),
    Check("equation_mismatch", "production and the registry running "
          "different models",
          "the validation report validates a model nobody is using",
          _equation_mismatch, "COMPUTATION_AND_EVIDENCE"),
    Check("future_leakage", "validation months inside the development fit",
          "the model is validated on data it was fitted on and looks "
          "excellent", _future_leakage, "ANALYTICAL_DESIGN"),
    Check("empty_default_sample", "discrimination with one outcome class",
          "an undefined statistic reported as a number", _empty_default_sample,
          "COMPUTATION_AND_EVIDENCE"),
    Check("tiny_segment", "a segment too small to carry the metric",
          "the noisiest segment becomes the headline finding",
          _tiny_segment_ranked, "JUDGMENT_AND_PRESENTATION"),
    Check("mape_near_zero", "MAPE on a near-zero band",
          "an unbounded ratio reported as a percentage error",
          _mape_near_zero, "COMPUTATION_AND_EVIDENCE"),
    Check("comparison_population", "models compared on different populations",
          "a difference between samples reported as a difference between "
          "models", _comparison_population, "ANALYTICAL_DESIGN"),
    Check("report_reconciliation", "a report figure that does not match the "
          "dashboard",
          "two numbers for one fact, and whichever is quoted first wins",
          _report_reconciles_with_dashboard, "JUDGMENT_AND_PRESENTATION"),
    Check("no_certification_claim", "a claim of regulatory certification",
          "the one claim this product must never make",
          _no_certification_claim, "JUDGMENT_AND_PRESENTATION"),
    Check("candidate_not_activated", "a candidate activated without approval",
          "customers scored on an equation no committee saw",
          _candidate_not_activated, "RELIABILITY_AND_EXPERIENCE"),
    Check("retirement_key", "activation that retires by the wrong key",
          "two live scorecards deciding the same applications",
          _retirement_by_the_right_key, "RELIABILITY_AND_EXPERIENCE"),
)


def run() -> Result:
    """Every check, with the failures named rather than counted."""
    result = Result()
    for check in CHECKS:
        try:
            check.run()
        except CriticalFailure as exc:
            result.outcomes.append(Outcome(check.id, check.failure, False,
                                           str(exc)))
        except Exception as exc:  # a check that cannot run has not passed
            result.outcomes.append(Outcome(
                check.id, check.failure, False,
                f"the check could not run: {type(exc).__name__}: {exc}"))
        else:
            result.outcomes.append(Outcome(check.id, check.failure, True))
    if result.failures:
        logger.error("scorecard critical suite: %d failure(s)",
                     len(result.failures))
    return result


def catalogue() -> list[dict[str, str]]:
    """What the suite covers, for a report that names it."""
    return [{"id": c.id, "failure": c.failure,
             "why_critical": c.why_critical, "dimension": c.dimension}
            for c in CHECKS]


__all__ = ["CHECKS", "CRITICAL_VERSION", "Check", "CriticalFailure",
           "Outcome", "Result", "catalogue", "run"]
