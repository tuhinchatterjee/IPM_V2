"""The three scorecard models, as validation subjects. §5.

What a model IS, from a validator's point of view: which columns carry its
score and its predicted PD, which way is good, what it was fitted on, which
tests it can support, and what limits its results are compared against.

Why this and not the existing `backend/scorecard/registry.py`
---------------------------------------------------------------
That registry is the governance record: rows in Postgres, approvals,
transitions, findings raised against a version. It is the right place for
"who approved 1.1.0 and when", and it is deliberately not being duplicated
here.

What it does not carry is the *binding* between a model and the columns a
validation kernel needs: which field is the score, which is the PD, whether a
challenger exists, where the reference population lives. Those are how the
model is read rather than how it is governed, and putting them in the
database would mean a schema migration every time a dataset gained a column.

So this is a code-level binding, versioned with the code that reads it, and
it points at the governance registry by `registry_key` rather than restating
it. Two records, one about approval and one about wiring, and neither
pretending to be the other.

On the three
--------------
Retail Application and Retail Behaviour bind to the datasets the existing
retail build already writes. Saudi SME binds to the three this phase added.
There is no fourth entry and no way to add one at runtime, which is the same
boundary `domains.py` draws, expressed where a tool call will meet it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.scorecard import domains
from backend.scorecard.validation import registry as test_registry

MODELS_VERSION = "1.0.0"


class ModelError(LookupError):
    """A governed artefact this model points at is missing or malformed."""

#: The engine's score-direction vocabulary. `metrics.py` refuses anything
#: else rather than guessing, and this is the whole reason a Gini cannot come
#: back with its sign inverted.
HIGHER_IS_BETTER = "HIGHER_SCORE_IS_BETTER"
LOWER_IS_BETTER = "LOWER_SCORE_IS_BETTER"


@dataclass(frozen=True)
class Limit:
    """One threshold, and where it came from.

    `source` is not decoration. A conventional cut-off recorded without its
    provenance becomes a regulatory requirement the third time somebody reads
    the table, and a validator asked to defend it in a regulatory meeting has
    nothing to say. Everything seeded here says DEMO POLICY.
    """

    test_id: str
    #: The value a result is compared against.
    value: float
    #: True where a result ABOVE the limit is the problem (PSI, O/E); False
    #: where a result BELOW it is (AUC, Gini, KS).
    breach_above: bool
    source: str = "DEMO POLICY"
    #: How close to the limit is close enough to warn. Expressed as a share
    #: of the limit so one number works for a PSI of 0.25 and an AUC of 0.65.
    warn_within: float = 0.08
    note: str = ""

    def verdict(self, value: float) -> str:
        """PASS, WARNING or FAIL for this value. Deterministic, and here.

        Never asked of a model. §25 is explicit that the pass/fail decision
        is arithmetic against a governed limit, and an LLM that can decide a
        verdict can decide a different one next time.
        """
        from backend.scorecard.validation import states

        margin = abs(self.value) * self.warn_within
        if self.breach_above:
            if value > self.value:
                return states.FAIL
            return states.WARNING if value > self.value - margin else states.PASS
        if value < self.value:
            return states.FAIL
        return states.WARNING if value < self.value + margin else states.PASS

    def to_dict(self) -> dict[str, Any]:
        return {
            "test_id": self.test_id, "value": self.value,
            "breach_above": self.breach_above, "source": self.source,
            "warn_within": self.warn_within, "note": self.note,
        }


@dataclass(frozen=True)
class Model:
    """One scorecard, wired to the columns a validation kernel reads."""

    model_id: str
    name: str
    domain: str
    scorecard_type: str
    reference_number: str
    version: str
    challenger_version: str = ""
    portfolio: str = ""
    jurisdiction: str = ""
    intended_use: str = ""
    owner: str = ""
    validation_owner: str = ""
    materiality: str = "MEDIUM"
    tier: str = "TIER_2"
    status: str = "ACTIVE"

    # ---- how it is read --------------------------------------------------
    dataset: str = ""
    reference_dataset: str = ""
    decisions_dataset: str = ""
    period_field: str = "cohort_month"
    score_column: str = ""
    pd_column: str = ""
    challenger_score_column: str = ""
    challenger_pd_column: str = ""
    outcome_column: str = ""
    matured_column: str = "is_matured"
    score_direction: str = HIGHER_IS_BETTER

    # ---- what it is -------------------------------------------------------
    score_range: tuple[float, float] = (300.0, 900.0)
    base_score: float | None = None
    base_odds: float | None = None
    points_to_double_odds: float | None = None
    default_definition: str = ""
    performance_window_months: int = 12
    observation_window: str = ""
    development_population: str = ""
    segmentation_fields: tuple[str, ...] = ()
    binned_variables: tuple[str, ...] = ()
    cut_off: float | None = None
    known_limitations: tuple[str, ...] = ()
    #: The governance record this points at, rather than restates.
    registry_key: str = ""
    #: Which fitted equation in that record is the approved one. Empty means
    #: no coefficient equation is published for this model in this
    #: deployment, and the tests that need one say so rather than skipping
    #: quietly.
    equation_key: str = ""

    limits: tuple[Limit, ...] = field(default_factory=tuple)

    # ---- what it can support ---------------------------------------------

    def capabilities(self) -> set[str]:
        """Which test requirements this model actually satisfies.

        Derived from the wiring rather than declared, so a model that loses
        its PD column loses its calibration tests automatically instead of
        offering them and failing.
        """
        made: set[str] = set()
        if self.score_column:
            made.add(test_registry.NEEDS_SCORE)
        if self.outcome_column:
            made.add(test_registry.NEEDS_OUTCOME)
        if self.pd_column:
            made.add(test_registry.NEEDS_PD)
        if self.binned_variables:
            made.add(test_registry.NEEDS_BINS)
        if self.reference_dataset:
            made.add(test_registry.NEEDS_REFERENCE)
        if self.challenger_score_column:
            made.add(test_registry.NEEDS_CHALLENGER)
        if self.decisions_dataset:
            made.add(test_registry.NEEDS_DECISIONS)
        if self.equation_key:
            made.add(test_registry.NEEDS_EQUATION)
        return made

    def approved_spec(self) -> Any:
        """The binning specification this model was approved on.

        Resolved rather than stored, because the spec is a governed artefact
        that lives with the scorecard build. A copy held here would be a
        second version of the same thing, and the two would part company the
        first time either was rebuilt.

        Raises rather than returning None: a caller that asked for the
        approved bins and got nothing would have to decide what to do with
        that, and the only correct decision is to stop.
        """
        from backend.scorecard import build as retail_build
        from backend.scorecard.sme import build as sme_build

        if self.scorecard_type == "SME":
            return sme_build.spec()
        return retail_build.load_spec(self.scorecard_type)

    def approved_equation(self) -> Any:
        """The fitted coefficient equation this model was approved on.

        Resolved from the scorecard build's own record for the same reason
        as `approved_spec`: a copy kept here would be a second version of a
        governed artefact.
        """
        import json

        from backend.scorecard import build as retail_build
        from backend.scorecard import equation as equation_mod

        if not self.equation_key:
            raise ModelError(
                f"{self.name} has no published coefficient equation in this "
                "deployment, so its score cannot be independently "
                "reconstructed.")
        path = (retail_build.spec_root()
                / f"{self.scorecard_type.lower()}_models.json")
        if not path.exists():
            raise ModelError(f"{path.name} is not present")
        record = json.loads(path.read_text("utf-8"))["models"]
        if self.equation_key not in record:
            raise ModelError(
                f"{self.equation_key} is not one of the fitted equations in "
                f"{path.name}: {', '.join(sorted(record))}.")
        return equation_mod.Equation.from_dict(
            record[self.equation_key]["equation"])

    def limit_for(self, test_id: str) -> Limit | None:
        for limit in self.limits:
            if limit.test_id == test_id:
                return limit
        return None

    def applicable_tests(self, category: str = "") -> tuple[Any, ...]:
        return test_registry.applicable(self.capabilities(), category)

    def inapplicable_tests(self, category: str = "") -> tuple[Any, ...]:
        return test_registry.inapplicable(self.capabilities(), category)

    def to_dict(self) -> dict[str, Any]:
        return {
            "models_version": MODELS_VERSION,
            "model_id": self.model_id, "name": self.name,
            "domain": self.domain,
            "domain_label": domains.DOMAIN_LABELS.get(self.domain, ""),
            "scorecard_type": self.scorecard_type,
            "reference_number": self.reference_number,
            "version": self.version,
            "challenger_version": self.challenger_version,
            "portfolio": self.portfolio, "jurisdiction": self.jurisdiction,
            "intended_use": self.intended_use, "owner": self.owner,
            "validation_owner": self.validation_owner,
            "materiality": self.materiality, "tier": self.tier,
            "status": self.status,
            "dataset": self.dataset,
            "reference_dataset": self.reference_dataset,
            "decisions_dataset": self.decisions_dataset,
            "score_direction": self.score_direction,
            "score_range": list(self.score_range),
            "base_score": self.base_score, "base_odds": self.base_odds,
            "points_to_double_odds": self.points_to_double_odds,
            "default_definition": self.default_definition,
            "performance_window_months": self.performance_window_months,
            "observation_window": self.observation_window,
            "development_population": self.development_population,
            "segmentation_fields": list(self.segmentation_fields),
            "binned_variables": list(self.binned_variables),
            "cut_off": self.cut_off,
            "known_limitations": list(self.known_limitations),
            "registry_key": self.registry_key,
            "has_challenger": bool(self.challenger_score_column),
            "has_pd": bool(self.pd_column),
            "capabilities": sorted(self.capabilities()),
            "limits": [limit.to_dict() for limit in self.limits],
        }


# ------------------------------------------------------------- the three

#: The tests where the acceptable answer is not a matter of judgement.
#:
#: Most validation thresholds are conventions — an AUC floor of 0.70 is a
#: choice somebody made, and a model below it may still be fit for its use.
#: These are different. A duplicated primary key, a production score that
#: does not reproduce from its own specification, a coefficient scored
#: against its credit sense, an approved ordering the data has reversed, a
#: governance record with a hole in it: none of those has a defensible
#: non-zero tolerance, and leaving them unlimited would report each of them
#: as NO APPROVED LIMIT — a grey cell where a red one belongs.
#:
#: Everything not in this list stays unlimited until a model owner sets a
#: threshold, and reads as NO APPROVED LIMIT rather than as a pass. That is
#: the honest position: the number is real and nobody has said what is
#: acceptable.
def _structural_limits() -> tuple[Limit, ...]:
    zero = "There is no defensible non-zero tolerance for this."
    # No warning band. A structural requirement is met or it is not, and a
    # margin around zero would mean "nearly no duplicate keys".
    return (
        Limit("DATA-DUPLICATES", 0.0, breach_above=True, source="STRUCTURAL",
              warn_within=0.0,
              note=("A duplicated key means every rate in this report is a "
                    "count over a denominator that is wrong. " + zero)),
        Limit("IMPL-REPLICATE", 0.0, breach_above=True, source="STRUCTURAL",
              warn_within=0.0,
              note=("A row that does not reproduce from the approved "
                    "specification was scored by something else. " + zero)),
        Limit("VAR-SIGN", 0.0, breach_above=True, source="STRUCTURAL",
              warn_within=0.0,
              note=("A term scored against its own credit sense rewards what "
                    "predicts default. " + zero)),
        Limit("VAR-WOE", 0.0, breach_above=True, source="STRUCTURAL",
              warn_within=0.0,
              note=("A bin whose risk has reversed is still being scored "
                    "with the approved sign. " + zero)),
        *(Limit(test_id, 1.0, breach_above=False, source="STRUCTURAL",
                warn_within=0.0,
                note=("Evidence completeness. Anything not recorded cannot "
                      "be assessed, and a validation opinion resting on it "
                      "is resting on an assumption."))
          for test_id in ("CONC-PURPOSE", "CONC-DEFAULT", "CONC-WINDOWS",
                          "CONC-DIRECTION", "CONC-DOCUMENTATION")),
    )


#: Conventional scorecard-practice cut-offs, seeded as DEMO POLICY. Every one
#: says so. §25 is explicit that model-specific limits must be governed and
#: versioned rather than inherited from an industry rule of thumb, and the
#: honest way to ship a demonstration is to label the rules of thumb as what
#: they are.
def _standard_limits(*, auc: float, gini: float, ks: float,
                     oe_high: float, psi: float) -> tuple[Limit, ...]:
    return _structural_limits() + (
        Limit("DISC-AUC", auc, breach_above=False,
              note="Below this the model no longer ranks risk well enough "
                   "for the use it is approved for."),
        Limit("DISC-GINI", gini, breach_above=False),
        Limit("DISC-KS", ks, breach_above=False),
        Limit("CAL-OE", oe_high, breach_above=True,
              note="Observed over expected. Above this the model is "
                   "under-predicting default by more than the policy allows."),
        Limit("STAB-PSI", psi, breach_above=True,
              note="A conventional scorecard-practice cut-off, not a "
                   "regulatory threshold."),
        Limit("STAB-CSI", psi, breach_above=True,
              note="Same convention, applied per characteristic."),
    )


RETAIL_APPLICATION = Model(
    model_id="retail_application_champion",
    name="Retail Application Scorecard",
    domain=domains.SCORECARD_APPLICATION,
    scorecard_type="APPLICATION",
    reference_number="MDL-RTL-APP-001",
    version="1.1.0",
    challenger_version="1.2.0-C",
    portfolio="Retail unsecured and secured lending",
    jurisdiction="United Arab Emirates",
    intended_use="Application-time approve/decline and pricing band for new "
                 "retail credit applications.",
    owner="Retail Credit Risk",
    validation_owner="Model Risk & Validation",
    materiality="HIGH",
    tier="TIER_1",
    dataset="retail_application_scorecard_monthly_validation",
    reference_dataset="retail_application_scorecard_development_reference",
    period_field="application_month",
    score_column="score_incumbent",
    pd_column="pd_incumbent",
    challenger_score_column="score_challenger",
    challenger_pd_column="pd_challenger",
    outcome_column="actual_default",
    matured_column="matured_flag",
    default_definition="90 days past due or worse within twelve months of "
                       "the application date.",
    observation_window="Application month",
    development_population="2021-01..2022-12 applications, matured to a "
                           "twelve-month outcome.",
    known_limitations=(
        "No booked-account decision file is published for this scorecard in "
        "this deployment, so override and cut-off usage cannot be tested.",
        "No model version is stamped on the scored rows, so which version "
        "produced them cannot be evidenced.",
    ),
    segmentation_fields=("product_type", "application_channel",
                         "customer_segment"),
    binned_variables=(
        "bureau_score", "debt_burden_ratio", "employment_tenure_months",
        "bureau_max_dpd_12m", "bureau_enquiries_6m",
        "credit_card_utilisation"),
    registry_key="APPLICATION",
    equation_key="INCUMBENT",
    limits=_standard_limits(auc=0.70, gini=0.40, ks=0.30, oe_high=1.20,
                            psi=0.25),
)

RETAIL_BEHAVIOUR = Model(
    model_id="retail_behaviour_champion",
    name="Retail Behaviour Scorecard",
    domain=domains.SCORECARD_BEHAVIOUR,
    scorecard_type="BEHAVIORAL",
    reference_number="MDL-RTL-BEH-001",
    version="1.1.0",
    challenger_version="1.2.0-C",
    portfolio="Retail revolving and instalment accounts",
    jurisdiction="United Arab Emirates",
    intended_use="Monthly account-level risk grading for limit management, "
                 "collections prioritisation and IFRS 9 staging input.",
    owner="Retail Credit Risk",
    validation_owner="Model Risk & Validation",
    materiality="HIGH",
    tier="TIER_1",
    dataset="retail_behavioral_scorecard_monthly_validation",
    reference_dataset="retail_behavioral_scorecard_development_reference",
    period_field="observation_month",
    score_column="score_incumbent",
    pd_column="pd_incumbent",
    challenger_score_column="score_challenger",
    challenger_pd_column="pd_challenger",
    outcome_column="actual_default",
    matured_column="matured_flag",
    default_definition="90 days past due or worse within twelve months of "
                       "the observation date.",
    observation_window="Monthly account snapshot",
    development_population="2021-01..2022-12 monthly snapshots, matured to a "
                           "twelve-month outcome.",
    known_limitations=(
        "No decision file is published for this scorecard in this "
        "deployment, so override and cut-off usage cannot be tested.",
        "No model version is stamped on the scored rows, so which version "
        "produced them cannot be evidenced.",
    ),
    segmentation_fields=("product", "vintage"),
    binned_variables=(
        "max_dpd_6m", "utilisation_pct", "average_payment_ratio_3m",
        "bureau_score_latest", "missed_payment_count_6m", "months_on_book"),
    registry_key="BEHAVIORAL",
    equation_key="INCUMBENT",
    limits=_standard_limits(auc=0.72, gini=0.44, ks=0.32, oe_high=1.20,
                            psi=0.25),
)


def _sme() -> Model:
    """Built from the SME package so the wiring cannot drift from the data.

    The column names, the binned variables and the development window all
    come from the modules that write them. A hand-maintained copy here would
    be correct until the first rebuild.
    """
    from backend.scorecard.sme import build as sme_build
    from backend.scorecard.sme import synthetic as sme_synth

    return Model(
        model_id="sme_champion",
        name="Saudi SME Scorecard",
        domain=domains.SCORECARD_SME,
        scorecard_type="SME",
        reference_number="MDL-SME-KSA-001",
        version="1.0.0",
        challenger_version="1.1.0-C",
        portfolio="Saudi small and medium enterprise lending",
        jurisdiction="Kingdom of Saudi Arabia",
        intended_use="Application-time approve/decline, limit and pricing "
                     "for SME facilities up to the delegated authority "
                     "threshold.",
        owner="SME Credit",
        validation_owner="Model Risk & Validation",
        materiality="HIGH",
        tier="TIER_1",
        dataset=sme_build.MONTHLY,
        reference_dataset=sme_build.DEVELOPMENT,
        decisions_dataset=sme_build.DECISIONS,
        period_field="cohort_month",
        score_column="champion_score",
        pd_column="champion_pd_12m",
        challenger_score_column="challenger_score",
        challenger_pd_column="challenger_pd_12m",
        outcome_column="actual_default_12m",
        matured_column="is_matured",
        score_direction=HIGHER_IS_BETTER,
        base_score=sme_synth.BASE_SCORE,
        base_odds=sme_synth.BASE_ODDS,
        points_to_double_odds=sme_synth.POINTS_TO_DOUBLE_ODDS,
        default_definition="90 days past due or worse, or a credit-impaired "
                           "restructuring, within twelve months of the score "
                           "date.",
        performance_window_months=sme_synth.DEFAULT_HORIZON_MONTHS,
        observation_window="Monthly application cohort",
        development_population=(
            f"{sme_synth.DEVELOPMENT_MONTHS[0]}.."
            f"{sme_synth.DEVELOPMENT_MONTHS[-1]}"),
        segmentation_fields=("enterprise_size_class_proxy", "economic_sector",
                             "region"),
        binned_variables=tuple(sme_build.BINNED_VARIABLES),
        cut_off=600.0,
        known_limitations=(
            "Every input is generated. CreditProbe is not connected to a "
            "commercial bureau, a tax authority, an e-invoicing platform, a "
            "social-insurance register or a bank core system, and each field "
            "standing in for one of those carries `_proxy` in its name.",
            "The score-to-PD calibration was fitted on the development "
            "sample and has not been refitted since.",
        ),
        registry_key="SME",
        limits=_standard_limits(auc=0.65, gini=0.30, ks=0.20, oe_high=1.25,
                                psi=0.25),
    )


_CACHE: dict[str, Model] = {}


def all_models() -> tuple[Model, ...]:
    """The three, and only ever the three."""
    if "sme" not in _CACHE:
        _CACHE["sme"] = _sme()
    return (RETAIL_APPLICATION, RETAIL_BEHAVIOUR, _CACHE["sme"])


BY_ID: dict[str, Model] = {}


def get(model_id: str) -> Model:
    """One model by id, or a refusal that names the three.

    This is a security boundary as well as a lookup: a tool call arriving
    with a model id from a model-authored parameter reaches here, and there
    is no path by which a fourth id resolves.
    """
    wanted = str(model_id or "").strip().lower()
    for made in all_models():
        if made.model_id.lower() == wanted:
            return made
    raise domains.DomainRefused(
        str(model_id), domains.VALIDATION,
        f"{model_id!r} is not a scorecard this environment validates. The "
        f"three are: {', '.join(m.model_id for m in all_models())}.")


def for_scorecard_type(scorecard_type: str) -> Model:
    """One model by the engine's scorecard type. Refuses a fourth."""
    wanted = domains.require_scorecard_type(scorecard_type)
    for made in all_models():
        if made.scorecard_type == wanted:
            return made
    raise domains.DomainRefused(  # pragma: no cover - unreachable by construction
        wanted, domains.VALIDATION,
        f"No model is registered for scorecard type {wanted}.")


def summary() -> dict[str, Any]:
    return {
        "models_version": MODELS_VERSION,
        "models": [m.to_dict() for m in all_models()],
        "count": len(all_models()),
        "limits_are_demo_policy": (
            "Every limit seeded here is labelled DEMO POLICY. They are "
            "conventional scorecard-practice cut-offs, not regulatory "
            "thresholds, and a deployment governs and versions its own."),
    }


__all__ = [
    "HIGHER_IS_BETTER", "LOWER_IS_BETTER", "MODELS_VERSION",
    "RETAIL_APPLICATION", "RETAIL_BEHAVIOUR", "Limit", "Model", "all_models",
    "for_scorecard_type", "get", "summary",
]
