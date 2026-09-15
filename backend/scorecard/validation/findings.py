"""What the results mean together. §23, §24, §25.

A validation report that lists forty-eight test results and stops has done
the arithmetic and left the work undone. The findings that matter in a
scorecard are rarely visible in one test: a portfolio calibration inside its
limit while one segment sits well outside it, a characteristic whose
population has moved *and* whose information value has decayed, overrides
clustering at the cut-off *and* defaulting more than the scores they
overrode. Each half looks survivable. Together each is a different finding
with a different fix.

So this module does two things, and the order matters.

**Nothing is lost.** Every adverse result becomes a finding, whether or not
a pattern recognises it. A breach that no rule happens to match must not
vanish because the rules were written before it.

**Then the combinations are named.** A pattern is a deterministic rule over
result states and values — no model is asked, nothing is inferred, and a
pattern either matches its condition or does not. Where one matches, it
supersedes the single-test findings it is built from, because "MICRO is
under-predicted by 65% while the portfolio reads 1.13" is one finding, not
three, and reporting it three times buries it.

Severity is arithmetic
----------------------
Derived from what was measured: the state, how far outside the limit, how
much evidence stood behind it, and the model's recorded materiality. Not
from a judgement about how bad it feels. The formula is in `_severity` and
it is short enough to read.

What this module will not do
----------------------------
It does not write prose about a model. Every sentence a finding carries is
assembled from the result's own numbers and a fixed template, so a finding
can be reproduced from the results that made it. The narrative layer, where
one exists, sits above this and cites it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from backend.scorecard.validation import models as model_registry
from backend.scorecard.validation import registry as test_registry
from backend.scorecard.validation import runner as _runner
from backend.scorecard.validation import regulatory
from backend.scorecard.validation import states

FINDINGS_VERSION = "1.0.0"

CRITICAL = "CRITICAL"
HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
OBSERVATION = "OBSERVATION"

SEVERITIES: tuple[str, ...] = (CRITICAL, HIGH, MEDIUM, LOW, OBSERVATION)
SEVERITY_RANK: dict[str, int] = {s: i for i, s in enumerate(SEVERITIES)}

SEVERITY_MEANING: dict[str, str] = {
    CRITICAL: "The model is being used in a way the evidence does not "
              "support. Act before the next decision cycle.",
    HIGH: "A breach with material consequence. Act within this validation "
          "cycle.",
    MEDIUM: "A breach or a deterioration that needs a plan, not an "
            "emergency.",
    LOW: "Outside a limit, but small, or thinly evidenced. Monitor.",
    OBSERVATION: "Not a breach. Recorded because a reader would otherwise "
                 "have to work it out for themselves.",
}


@dataclass(frozen=True)
class Finding:
    """One thing wrong, and what would show it had been fixed.

    Frozen, like `Result`, and for the same reason: a finding is cited in a
    report and reproduced from its own evidence. `verify_by` is the field
    that makes it actionable — a finding that says what is wrong but not
    what would demonstrate a fix is a complaint.
    """

    finding_id: str
    title: str
    severity: str
    category: str
    #: One sentence a validator can file unedited, built from the numbers.
    what: str
    why_it_matters: str
    remediation: str
    #: Which test result, changed how, would show the remediation worked.
    verify_by: str
    #: The test ids this rests on. A finding with no evidence is an opinion.
    evidence: tuple[str, ...] = ()
    values: dict[str, Any] = field(default_factory=dict)
    segment: str = ""
    model_id: str = ""
    model_version: str = ""
    period: str = ""
    cbuae: tuple[str, ...] = ()
    #: The supervisory references this rests on. Derived in `assess` from
    #: the tests cited as evidence, never written here — a finding that
    #: quoted an article number of its own would be a second opinion about
    #: what a test evidences, and the two would eventually disagree.
    #: Where a pattern matched, the pattern's key. Empty for a single test.
    pattern: str = ""
    #: The single-test findings this one replaces, so nothing is reported
    #: twice and nothing is silently dropped.
    supersedes: tuple[str, ...] = ()
    confidence: str = ""
    #: The other categories this same finding must be read under.
    #:
    #: §14.5: a shared finding appears in Data, Calibration, Stability,
    #: Segmentation, the overall validation and the report — with the SAME
    #: id, the same values, the same sample dates and the same threshold. It
    #: is one finding seen from several categories, not several findings
    #: that happen to agree, and the distinction matters because a committee
    #: counting rows would otherwise count it four times.
    also_in: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(
                f"{self.severity!r} is not a severity. It is one of: "
                f"{', '.join(SEVERITIES)}.")
        if not self.evidence:
            raise ValueError(
                f"{self.finding_id} cites no test result. A finding with no "
                "evidence is an opinion, and this engine does not have "
                "opinions.")
        if not self.verify_by:
            raise ValueError(
                f"{self.finding_id} says what is wrong and not what would "
                "show it fixed, which makes it a complaint rather than a "
                "finding.")

    @property
    def rank(self) -> int:
        return SEVERITY_RANK[self.severity]

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings_version": FINDINGS_VERSION,
            "finding_id": self.finding_id, "title": self.title,
            "severity": self.severity,
            "severity_meaning": SEVERITY_MEANING[self.severity],
            "category": self.category, "what": self.what,
            "why_it_matters": self.why_it_matters,
            "remediation": self.remediation, "verify_by": self.verify_by,
            "evidence": list(self.evidence), "values": dict(self.values),
            "segment": self.segment, "model_id": self.model_id,
            "model_version": self.model_version, "period": self.period,
            # Shown under the label THIS installation may honestly use. The
            # internal ids stay on `cbuae` as the join key, and a retail
            # installation cites no supervisor's text at all.
            "references": [regulatory.shown_as(r) for r in self.cbuae],
            "cbuae": list(self.cbuae), "pattern": self.pattern,
            "supersedes": list(self.supersedes),
            "confidence": self.confidence,
            "also_in": list(self.also_in),
            # Every category this finding is read under, the owning one
            # first. One list, so a screen filtering by category never has
            # to decide whether `category` or `also_in` is authoritative.
            "categories": [self.category, *self.also_in],
            "category_titles": [
                test_registry.BY_CATEGORY_KEY[key].title
                for key in (self.category, *self.also_in)
                if key in test_registry.BY_CATEGORY_KEY],
        }


# ------------------------------------------------------------- how severe


#: How far outside a limit stops being "just outside". Expressed as a share
#: of the limit so one number serves an AUC floor of 0.65 and a PSI cap of
#: 0.25.
MATERIAL_BREACH = 0.20
SEVERE_BREACH = 0.50

#: A characteristic stability index at or above this has moved enough to
#: be named in a finding. Scorecard practice, seeded as demo policy, and the
#: same number the CSI limit uses — stated once here rather than inlined.
_CSI_NOTABLE = 0.10

#: A segmentation level whose share moved by this much is named. Ten
#: percentage points of a book is a different book.
_SHARE_NOTABLE = 0.10


def _subject_word(model: model_registry.Model) -> str:
    from backend.scorecard.validation.representativeness import _subject

    return _subject(model)[0]


#: The information-value floor the runner already applies, imported rather
#: than restated so the two cannot drift apart. Below it, "retained 0.41 of
#: its information value" is a ratio of two pieces of noise.
_IV_FLOOR = _runner.IV_FLOOR


def _distance(result: states.Result) -> float:
    """How far outside its limit, as a share of the limit. 0 where inside."""
    if result.limit is None or result.value is None or not result.limit:
        return 0.0
    if result.state != states.FAIL:
        return 0.0
    return abs(result.value - result.limit) / abs(result.limit)


def _severity(result: states.Result, model: model_registry.Model, *,
              floor: str = OBSERVATION) -> str:
    """Severity from what was measured. Never from how bad it sounds.

    Four inputs, in this order: the state, the distance outside the limit,
    the evidence behind it, and the model's recorded materiality. A thin
    sample cannot produce a CRITICAL, because a breach measured on ninety
    accounts is a reason to look again rather than to act.
    """
    if result.state == states.FAIL:
        gap = _distance(result)
        if gap >= SEVERE_BREACH:
            severity = CRITICAL
        elif gap >= MATERIAL_BREACH:
            severity = HIGH
        else:
            severity = MEDIUM
    elif result.state == states.WARNING:
        severity = MEDIUM
    elif result.state in (states.CALCULATION_ERROR, states.UNAVAILABLE):
        severity = MEDIUM
    elif result.state in (states.NOT_MATURED, states.INSUFFICIENT_SAMPLE):
        severity = LOW
    else:
        severity = floor

    # Materiality raises a *breach* by one step, and only a breach. A model
    # version column that is not being supplied is the same missing column
    # whether the model is tier 1 or tier 3, and promoting it to HIGH puts
    # it above findings that are actually about the model's fitness.
    if result.state in (states.FAIL, states.WARNING):
        # A LOW-materiality model with a real breach is still a real breach.
        if model.materiality == "HIGH" and severity in (HIGH, MEDIUM, LOW):
            severity = SEVERITIES[max(SEVERITY_RANK[severity] - 1, 0)]
        elif model.materiality == "LOW" and severity in (CRITICAL, HIGH,
                                                         MEDIUM):
            severity = SEVERITIES[min(SEVERITY_RANK[severity] + 1,
                                      len(SEVERITIES) - 1)]

    # Evidence has the last word, and it has to be last. A breach measured
    # on forty defaults is a reason to look again rather than to act, and on
    # a HIGH-materiality model the materiality step was undoing this cap and
    # handing back the CRITICAL it had just removed. Sample size is a
    # statement about whether the number can be relied on at all, so nothing
    # may raise a severity after it has spoken.
    if result.events and result.events < test_registry.MIN_EVENTS * 2 \
            and severity == CRITICAL:
        severity = HIGH
    return severity


def _confidence(result: states.Result) -> str:
    if not result.observations:
        return "NO SAMPLE RECORDED"
    if result.events and result.events < test_registry.MIN_EVENTS:
        return "LOW — fewer events than the engine's minimum"
    if result.observations < test_registry.MIN_OBS:
        return "LOW — fewer observations than the engine's minimum"
    if result.events and result.events >= test_registry.MIN_EVENTS * 5:
        return "HIGH"
    return "MODERATE"


# ------------------------------------------- one finding per adverse result


#: What each category's breaches mean and what to do about them. Keyed by
#: category so a new test inherits sensible language, and overridden per test
#: where the specific answer differs.
CATEGORY_REMEDY: dict[str, tuple[str, str, str]] = {
    test_registry.DISCRIMINATION: (
        "The model's ability to separate future defaults from non-defaults "
        "is below what it was approved on.",
        "Re-fit or re-develop. A discrimination shortfall is not fixed by "
        "recalibration — recalibration moves the level, not the ordering.",
        "the same discrimination test back inside its limit on a matured "
        "cohort after the re-fit"),
    test_registry.CALIBRATION: (
        "The probabilities the model produces do not match the outcomes "
        "observed.",
        "Recalibrate against the matured window, keeping the ordering. "
        "Check first whether the mismatch is uniform or concentrated in a "
        "segment: the two have different fixes.",
        "observed-over-expected returning inside its limit, and the segment "
        "calibration test agreeing with the portfolio one"),
    test_registry.STABILITY: (
        "The population being scored has moved away from the one the model "
        "was fitted on.",
        "Establish first whether the characteristic's *definition* changed "
        "or its *population* did. A definition change is a data-lineage fix "
        "upstream; a population change is a re-development question.",
        "the shift index returning inside its limit, or a documented "
        "re-development on the current population"),
    test_registry.VARIABLES: (
        "A characteristic is no longer behaving the way the approved "
        "specification says it does.",
        "Re-bin and re-fit that characteristic, or retire it. A variable "
        "scored against a relationship the data no longer shows is adding "
        "noise with confidence.",
        "the characteristic's ordering and information value restored, or "
        "its removal from the approved specification"),
    test_registry.USAGE: (
        "The model is not being used the way it was approved to be used.",
        "This is a policy and governance question before it is a modelling "
        "one. Establish who is overriding, on what authority, and whether "
        "the outcomes justify it.",
        "the override rate and the outcome gap between overridden and "
        "score-following decisions both inside their limits"),
    test_registry.SEGMENTATION: (
        "The model performs differently across the segments it is applied "
        "to.",
        "Either segment the model, or restrict its approved use to the "
        "segments where it performs. Applying one model across segments it "
        "fails on is a use question, not a fit question.",
        "each segment inside its limit, or a narrowed scope of approved "
        "use recorded on the model registry entry"),
    test_registry.DATA_QUALITY: (
        "The data the model is scored on does not meet the standard the "
        "validation needs.",
        "Fix upstream. A data-quality finding is not a model finding, and "
        "correcting it may change every other result in this report.",
        "the data-quality test passing, and the affected results re-run"),
    test_registry.CONCEPTUAL: (
        "Part of the evidence a validator needs is not on the record.",
        "Record it. Anything absent here is an assumption that a "
        "quantitative result is resting on.",
        "the evidence checklist complete on the model registry entry"),
    test_registry.IMPLEMENTATION: (
        "What is running is not demonstrably what was approved.",
        "Reconcile the production implementation against the approved "
        "specification before relying on any other result — every one of "
        "them describes the approved model.",
        "row-level replication with no mismatches"),
    test_registry.CHAMPION_CHALLENGER: (
        "The challenger's comparison against the champion does not support "
        "the conclusion being drawn from it.",
        "Compare on the identical population, at an equal approval rate, "
        "over a matured window, before proposing a replacement.",
        "the comparison repeated on the same population with the difference "
        "outside the champion's own confidence interval"),
    test_registry.ROBUSTNESS: (
        "The headline result depends on a choice that could have been made "
        "differently.",
        "State the dependency in the validation opinion. A result that "
        "moves materially when one segment or one window is excluded is a "
        "result with a caveat, not a result.",
        "the headline stable across windows and segment exclusions, or the "
        "dependency recorded as a limitation"),
}


def _single(result: states.Result,
            model: model_registry.Model) -> Finding | None:
    """One finding from one adverse result. Nothing is lost this way."""
    if not result.adverse and result.state not in (
            states.CALCULATION_ERROR, states.UNAVAILABLE):
        return None
    test = test_registry.BY_ID.get(result.test_id)
    if test is None:
        return None
    what, remedy, verify = CATEGORY_REMEDY.get(
        test.category,
        ("This test is outside its limit.",
         "Investigate and record the conclusion.",
         "the test returning inside its limit"))
    return Finding(
        finding_id=f"F-{result.test_id}",
        title=f"{test.name}: {states.STATE_LABELS[result.state]}",
        severity=_severity(result, model),
        category=test.category,
        what=result.detail,
        why_it_matters=what,
        remediation=result.remedy or remedy,
        verify_by=verify,
        evidence=(result.test_id,),
        values={"value": result.value, "limit": result.limit,
                "limit_source": result.limit_source},
        segment=result.segment, model_id=model.model_id,
        model_version=model.version, period=result.period,
        cbuae=test.cbuae, confidence=_confidence(result))


# --------------------------------------------------- the cross-test patterns


@dataclass(frozen=True)
class Pattern:
    """A combination of results that means something the parts do not."""

    key: str
    title: str
    #: The tests it reads. Documented so a reader can see its whole input.
    reads: tuple[str, ...]
    build: Any

    def apply(self, found: dict[str, states.Result],
              model: model_registry.Model) -> Finding | None:
        if any(t not in found for t in self.reads):
            return None
        return self.build(self, found, model)


def _aggregate_conceals_segment(pattern: Pattern,
                                found: dict[str, states.Result],
                                model: model_registry.Model
                                ) -> Finding | None:
    """A portfolio calibration inside its limit over a segment outside it.

    The single most common way a scorecard's real weakness stays invisible.
    Both results are correct. Read separately, the portfolio one is
    reassuring and the segment one is a row in a table. Read together they
    say the aggregate is averaging an over-prediction against an
    under-prediction, and that whoever prices the under-predicted segment is
    pricing it wrong.
    """
    portfolio, segment = found["CAL-OE"], found["SEG-CALIBRATION"]
    if not portfolio.measured or segment.state != states.FAIL:
        return None
    if portfolio.state == states.FAIL:
        return None  # then the portfolio number is not concealing anything

    worst = _worst_segment(segment)
    return Finding(
        finding_id="F-PATTERN-AGGREGATE-CONCEALS-SEGMENT",
        title="Portfolio calibration conceals a segment that is materially "
              "under-predicted",
        severity=_severity(segment, model, floor=MEDIUM),
        category=test_registry.CALIBRATION,
        what=(f"Observed over expected is {portfolio.value:.3f} across the "
              f"portfolio, inside its limit, while "
              f"{worst.get('segment', 'at least one segment')} is outside "
              f"it. The portfolio figure is an average of segments wrong in "
              "opposite directions, not evidence that the model is "
              "calibrated."),
        why_it_matters=(
            "Every decision taken at the segment level — pricing, limit, "
            "provision — uses the segment's probability, not the "
            "portfolio's. A portfolio number inside its limit is not "
            "evidence for any of them."),
        remediation=(
            "Recalibrate by segment, or restrict the model's approved use to "
            "the segments where the portfolio calibration holds. Do not "
            "recalibrate the portfolio: it is already at 1.0 and moving it "
            "would push the well-calibrated segments off."),
        verify_by=("SEG-CALIBRATION inside its limit for every segment, with "
                   "CAL-OE unchanged"),
        evidence=("CAL-OE", "SEG-CALIBRATION"),
        values={"portfolio_observed_over_expected": portfolio.value,
                "segments_outside_limit": segment.value,
                "worst_segment": worst.get("segment", "")},
        segment=str(worst.get("segment", "")),
        model_id=model.model_id, model_version=model.version,
        period=segment.period,
        pattern=pattern.key,
        supersedes=("F-SEG-CALIBRATION",),
        confidence=_confidence(segment))


def _drift_is_a_definition_change(pattern: Pattern,
                                  found: dict[str, states.Result],
                                  model: model_registry.Model
                                  ) -> Finding | None:
    """A characteristic that moved *and* lost its information value.

    Population drift and a definition change look identical in a CSI. They
    are different findings with different owners: drift is a re-development
    question for the modelling team, a definition change is a lineage defect
    for whoever owns the feed. The difference shows in the information
    value. A book whose composition shifted keeps a characteristic's
    predictive power; a column that changed meaning loses it, because the
    approved bins are now cutting a different quantity.
    """
    stability, information = found["STAB-CSI"], found["VAR-IV"]
    if stability.state != states.FAIL or not information.measured:
        return None

    moved = _worst_row(stability, "variable")
    decayed = {row.get("variable"): row for row in information.table}
    name = str(moved.get("variable", ""))
    entry = decayed.get(name)
    if entry is None or entry.get("retained") is None:
        return None
    # Retention is only meaningful where there was information to retain.
    # Below the floor the ratio is noise over noise, and a finding that
    # rests on it would name whichever characteristic happened to be
    # noisiest this month.
    if (entry.get("information_value_at_approval") or 0.0) < _IV_FLOOR:
        return None
    retained = float(entry["retained"])
    if retained >= 0.85:
        return None  # it moved and still works: population drift, not this

    return Finding(
        finding_id="F-PATTERN-DEFINITION-CHANGE",
        title=f"{name} has both moved and stopped predicting, which reads as "
              "a definition change rather than population drift",
        severity=_severity(stability, model, floor=MEDIUM),
        category=test_registry.STABILITY,
        what=(f"{name} has a characteristic stability index of "
              f"{stability.value:.4f} against its development distribution, "
              f"and retains {retained:.2f} of the information value it "
              f"carried at approval. A book whose composition shifted keeps "
              "a characteristic's predictive power; a column whose meaning "
              "changed does not, because the approved bins are cutting a "
              "different quantity."),
        why_it_matters=(
            "The two readings have different owners and different fixes. "
            "Treating a definition change as population drift sends a "
            "re-development request to the modelling team for a defect that "
            "lives in the data feed, and the re-developed model inherits it."),
        remediation=(
            f"Trace {name} to its source and compare the current definition "
            "against the one recorded at development, before any modelling "
            "work. If the definition changed, the fix is upstream and every "
            "result in this report should be re-run afterwards."),
        verify_by=(f"STAB-CSI for {name} inside its limit against a "
                   "re-stated development distribution, with its information "
                   "value restored"),
        evidence=("STAB-CSI", "VAR-IV"),
        values={"csi": stability.value, "information_value_retained": retained,
                "variable": name},
        model_id=model.model_id, model_version=model.version,
        period=stability.period,
        pattern=pattern.key,
        supersedes=("F-STAB-CSI",),
        confidence=_confidence(stability))


def _the_cut_off_is_not_believed(pattern: Pattern,
                                 found: dict[str, states.Result],
                                 model: model_registry.Model
                                 ) -> Finding | None:
    """Overrides that cluster at the cut-off and then default more.

    Either half alone is defensible. A high override rate can be a
    relationship bank doing its job. A worse outcome among overrides can be
    adverse selection nobody could have avoided. Together, concentrated at
    the boundary, they say the people using the model do not believe the
    cut-off — and are right often enough to keep doing it, or wrong often
    enough that it costs money. Both are findings; neither is visible in one
    test.
    """
    outcome = found["USE-OVERRIDE-OUTCOME"]
    matrix = found["USE-MATRIX"]
    if outcome.state != states.FAIL or not matrix.measured:
        return None

    hottest = _worst_row(matrix, "band", key="rate")
    return Finding(
        finding_id="F-PATTERN-CUT-OFF-NOT-BELIEVED",
        title="Overrides concentrate at the cut-off and default more than "
              "the decisions that followed the score",
        severity=_severity(outcome, model, floor=HIGH),
        category=test_registry.USAGE,
        what=(f"{outcome.detail} Overrides concentrate in band "
              f"{hottest.get('band', 'unknown')} "
              f"{str(hottest.get('direction', '')).lower()}, at "
              f"{float(hottest.get('rate', 0.0)):.2%} of that band."),
        why_it_matters=(
            "A cut-off that is routinely overridden at the boundary is not "
            "the cut-off in force. The decisions being taken are a different "
            "policy from the one that was approved, and the outcome gap says "
            "the departure is costing rather than saving."),
        remediation=(
            "Two separate actions. Establish the authority under which the "
            "boundary overrides are being taken and whether it is being "
            "exercised as delegated. Then re-examine the cut-off itself "
            "against the approval and bad-rate profile — if the score is "
            "right and the cut-off is wrong, the overrides are correcting a "
            "policy error rather than causing one."),
        verify_by=("USE-OVERRIDE-OUTCOME inside its limit, with the override "
                   "concentration at the cut-off band materially reduced"),
        evidence=("USE-OVERRIDE-OUTCOME", "USE-MATRIX", "USE-CUTOFF"),
        values={"outcome_ratio": outcome.value,
                "worst_band": hottest.get("band", ""),
                "band_override_rate": hottest.get("rate")},
        model_id=model.model_id, model_version=model.version,
        period=outcome.period,
        pattern=pattern.key,
        supersedes=("F-USE-OVERRIDE-OUTCOME",),
        confidence=_confidence(outcome))


def _holding_up_on_borrowed_power(pattern: Pattern,
                                  found: dict[str, states.Result],
                                  model: model_registry.Model
                                  ) -> Finding | None:
    """Discrimination inside its limit while a characteristic has decayed.

    A scorecard whose overall separation still passes while one of its
    inputs has stopped working is being carried by the others. It is not
    failing yet, and it will: the decayed characteristic is still consuming
    points in the equation, and whatever is compensating for it has no
    reason to keep doing so.
    """
    overall, information = found["DISC-AUC"], found["VAR-IV"]
    if overall.state == states.FAIL or not overall.measured:
        return None
    if not information.measured:
        return None
    # Same floor as `_drift_is_a_definition_change`, for the same reason: a
    # characteristic that carried 0.016 at approval and carries 0.007 now
    # has "lost 59%" of an amount that was never a signal.
    weakest = min(
        (row for row in information.table
         if row.get("retained") is not None
         and (row.get("information_value_at_approval") or 0.0) >= _IV_FLOOR),
        key=lambda row: float(row["retained"]), default=None)
    if weakest is None or float(weakest["retained"]) >= 0.75:
        return None

    return Finding(
        finding_id="F-PATTERN-BORROWED-POWER",
        title=(f"Discrimination still holds while "
               f"{weakest['variable']} has stopped contributing"),
        severity=MEDIUM if model.materiality != "HIGH" else HIGH,
        category=test_registry.VARIABLES,
        what=(f"Overall AUC is {overall.value:.4f}, inside its limit, while "
              f"{weakest['variable']} retains only "
              f"{float(weakest['retained']):.2f} of the information value it "
              f"carried at approval "
              f"({float(weakest['information_value']):.4f} now against "
              f"{float(weakest['information_value_at_approval']):.4f} then). "
              "The model is passing on the strength of its other "
              "characteristics."),
        why_it_matters=(
            "This is the finding that arrives a year early. Nothing has "
            "breached, so nothing is scheduled — and the characteristic is "
            "still consuming points in the equation while contributing "
            "nothing, so the first further deterioration in any other input "
            "has no slack to absorb it."),
        remediation=(
            f"Re-bin {weakest['variable']} on the current population and "
            "re-estimate its weight, or retire it and redistribute its "
            "points. Do this as scheduled work now rather than as an "
            "incident later."),
        verify_by=(f"VAR-IV showing {weakest['variable']} restored, or the "
                   "approved specification no longer containing it"),
        evidence=("DISC-AUC", "VAR-IV"),
        values={"auc": overall.value,
                "variable": weakest["variable"],
                "information_value_retained": weakest["retained"]},
        model_id=model.model_id, model_version=model.version,
        period=overall.period,
        pattern=pattern.key,
        confidence=_confidence(overall))


def _the_window_is_too_short(pattern: Pattern,
                             found: dict[str, states.Result],
                             model: model_registry.Model) -> Finding | None:
    """Most of the book has no realised outcome yet.

    An observation rather than a breach, and it belongs in the report
    because every outcome result above it is computed on the minority of the
    book that has matured. A reader who does not know that will read those
    results as describing the current book.
    """
    maturity = found["DATA-MATURITY"]
    if not maturity.measured or maturity.value is None:
        return None
    if maturity.value >= 0.6:
        return None
    return Finding(
        finding_id="F-PATTERN-SHORT-MATURED-WINDOW",
        title="Most of the book has no realised outcome yet",
        severity=LOW if maturity.value >= 0.3 else MEDIUM,
        category=test_registry.DATA_QUALITY,
        what=(f"{maturity.detail} Every outcome-based result in this report "
              f"is computed on the {maturity.value:.0%} of periods that have "
              "matured, and describes that window rather than the book as it "
              "stands today."),
        why_it_matters=(
            "The most recent cohorts are the ones a reader most wants an "
            "answer about, and they are precisely the ones no outcome test "
            "can reach. Stating the window is what stops a matured-window "
            "result being read as a current-book result."),
        remediation=(
            "No action on the model. Record the matured window on the face "
            "of the validation opinion, and schedule the re-run for when the "
            "next cohorts close."),
        verify_by="DATA-MATURITY rising as the open windows close",
        evidence=("DATA-MATURITY",),
        values={"matured_share": maturity.value},
        model_id=model.model_id, model_version=model.version,
        period=maturity.period,
        pattern=pattern.key,
        confidence=_confidence(maturity))


def _not_what_was_approved(pattern: Pattern,
                           found: dict[str, states.Result],
                           model: model_registry.Model) -> Finding | None:
    """The production score does not reproduce from its own specification.

    Escalated above everything else it appears with, because if this is true
    then every other result in the report is a result about a different
    model.
    """
    replication = found["IMPL-REPLICATE"]
    if replication.state != states.FAIL or replication.value is None:
        return None
    return Finding(
        finding_id="F-PATTERN-NOT-WHAT-WAS-APPROVED",
        title="The production score does not reproduce from the approved "
              "specification",
        severity=CRITICAL,
        category=test_registry.IMPLEMENTATION,
        what=replication.detail,
        why_it_matters=(
            "Every other result in this report describes the approved "
            "model. If the book was scored by something else, none of them "
            "describes what is running, and the validation opinion they "
            "support is an opinion about a model that is not in production."),
        remediation=(
            "Stop treating the rest of this report as evidence about the "
            "production model until the implementation reconciles. Identify "
            "the first divergent step — bins, weights, or the score mapping "
            "— and correct whichever of the two is wrong."),
        verify_by="IMPL-REPLICATE with no mismatched rows",
        evidence=("IMPL-REPLICATE",),
        values={"mismatch_rate": replication.value},
        model_id=model.model_id, model_version=model.version,
        period=replication.period,
        pattern=pattern.key,
        supersedes=("F-IMPL-REPLICATE",),
        confidence=_confidence(replication))


def _challenger_is_not_better(pattern: Pattern,
                              found: dict[str, states.Result],
                              model: model_registry.Model) -> Finding | None:
    """A challenger whose advantage is inside the champion's own noise.

    An observation, and a useful one: a challenger ahead by less than the
    champion's confidence interval is not ahead. This is the finding that
    stops a replacement being proposed on a difference that is sampling
    variation.
    """
    comparison, interval = found["CC-DISCRIMINATION"], found["ROB-BOOTSTRAP"]
    if not comparison.measured or not interval.measured:
        return None
    if comparison.value is None or comparison.value <= 0:
        return None
    row = interval.table[0] if interval.table else {}
    lower, upper = row.get("lower"), row.get("upper")
    if lower is None or upper is None:
        return None
    half_width = (float(upper) - float(lower)) / 2.0
    if comparison.value > half_width:
        return None
    return Finding(
        finding_id="F-PATTERN-CHALLENGER-INSIDE-THE-NOISE",
        title="The challenger's advantage is smaller than the champion's own "
              "sampling uncertainty",
        severity=OBSERVATION,
        category=test_registry.CHAMPION_CHALLENGER,
        what=(f"The challenger leads by {comparison.value:+.4f} in AUC, "
              f"against a 95% interval on the champion's own AUC of "
              f"[{float(lower):.4f}, {float(upper):.4f}] — a half-width of "
              f"{half_width:.4f}. On this population the difference is "
              "within what resampling the same book would produce."),
        why_it_matters=(
            "A replacement proposed on a difference this size is a "
            "replacement proposed on noise. It may still be the better "
            "model; this evidence does not show it."),
        remediation=(
            "Either measure the difference on more matured data, or compare "
            "the two models' intervals rather than their point estimates, "
            "before putting a replacement to a committee."),
        verify_by=("CC-DISCRIMINATION showing a difference larger than the "
                   "champion's interval half-width on a matured window"),
        evidence=("CC-DISCRIMINATION", "ROB-BOOTSTRAP"),
        values={"difference": comparison.value,
                "champion_interval_half_width": round(half_width, 6)},
        model_id=model.model_id, model_version=model.version,
        period=comparison.period,
        pattern=pattern.key,
        confidence=_confidence(comparison))


def _population_is_less_representative(pattern: Pattern,
                                      found: dict[str, states.Result],
                                      model: model_registry.Model
                                      ) -> Finding | None:
    """§14.3's findings panel: why the book is less like the fitted one.

    Assembled from the three tests that each see one part of it — the model
    inputs, the segmentation mix, and whether the event rate moved because
    the book changed shape. Reported as one finding because "indebtedness
    has shifted", "the mix has moved" and "composition explains none of the
    rate change" are three readings of one situation, and a validator acting
    on the first without the third re-develops a model that did not need it.
    """
    drift = found.get("DATA-INPUT-DRIFT")
    mix = found.get("DATA-REPRESENTATIVE")
    if drift is None or not drift.measured:
        return None

    moved = [row for row in drift.table
             if float(row.get("csi") or 0.0) >= _CSI_NOTABLE]
    unseen = sum(int(row.get("bins_unseen_at_development") or 0)
                 for row in drift.table)
    shifted: list[dict[str, Any]] = []
    if mix is not None and mix.measured:
        shifted = [row for row in mix.table
                   if abs(float(row.get("change") or 0.0)) >= _SHARE_NOTABLE]
    if not moved and not unseen and not shifted:
        return None

    reasons: list[str] = []
    if moved:
        worst = moved[0]
        reasons.append(
            f"{len(moved)} of {len(drift.table)} model inputs have a "
            f"characteristic stability index of {_CSI_NOTABLE:.2f} or more "
            f"against the development sample, the largest being "
            f"{worst['variable']} at {float(worst['csi']):.4f}")
    if shifted:
        worst_level = max(shifted,
                          key=lambda row: abs(float(row.get("change") or 0.0)))
        reasons.append(
            f"{worst_level['variable']}={worst_level['level']} has gone from "
            f"{float(worst_level['development_share']):.1%} of the book to "
            f"{float(worst_level['current_share']):.1%}")
    if unseen:
        reasons.append(
            f"{unseen} approved bin(s) are in use now that carried no "
            "development evidence")

    composition = ""
    standardised = found.get("DATA-MIXADJ")
    if standardised is not None and standardised.measured:
        share = abs(float(standardised.value or 0.0))
        composition = (
            f" Standardising the matured default rate onto the development "
            f"mix moves it by "
            f"{float(standardised.lineage.get('composition_effect') or 0.0):+.3%}, "
            f"so the change in shape accounts for {share:.1%} of the change "
            f"in the event rate and the rest is the same kind of "
            f"{_subject_word(model)} behaving differently.")

    return Finding(
        finding_id="F-PATTERN-LESS-REPRESENTATIVE",
        title="The population is less representative of the development "
              "sample than it was",
        severity=_severity(drift, model, floor=LOW),
        category=test_registry.DATA_QUALITY,
        what=("The population is less representative because "
              + "; ".join(reasons) + "." + composition),
        why_it_matters=(
            "A scorecard is fitted on a population and carries evidence "
            "about that population. Where the book has moved, the points "
            "attached to a bin are still the points fitted on customers who "
            "are no longer the ones in it, and every downstream number — the "
            "score, the PD, the stage, the expected loss — inherits that "
            "without saying so."),
        remediation=(
            "Take the inputs that moved to the modelling team with their "
            "development and current distributions attached, and decide "
            "per characteristic whether the bins still cut the risk. Where "
            "bins are in use with no development evidence, that decision "
            "cannot be deferred to the next cycle."),
        verify_by=("DATA-INPUT-DRIFT inside its limit against a re-stated "
                   "development distribution, with no bin in use that "
                   "carries no development evidence"),
        evidence=tuple(t for t in ("DATA-INPUT-DRIFT", "DATA-REPRESENTATIVE",
                                   "DATA-MIXADJ") if t in found),
        values={
            "inputs_drifted": len(moved),
            "inputs_compared": len(drift.table),
            "worst_input": (moved[0]["variable"] if moved else ""),
            "worst_input_csi": (float(moved[0]["csi"]) if moved else None),
            "bins_unseen_at_development": unseen,
            "segmentation_levels_moved": len(shifted),
        },
        model_id=model.model_id, model_version=model.version,
        period=drift.period,
        pattern=pattern.key,
        supersedes=("F-DATA-INPUT-DRIFT", "F-DATA-REPRESENTATIVE"),
        confidence=_confidence(drift))


def _shared_underprediction(pattern: Pattern,
                            found: dict[str, states.Result],
                            model: model_registry.Model) -> Finding | None:
    """§14.5. One under-prediction finding, read under four categories.

    It fires when the observed rate exceeds the predicted one ACROSS BANDS
    rather than in aggregate, because an aggregate O/E above 1 can be one
    band and a mix. Then it works the four explanations §14.5 names —
    composition, conditional risk, a horizon or definition mismatch, and
    calibration drift — and says which the evidence supports, rather than
    reaching for the first.

    Discrimination is reported alongside and never folded in. A model can
    rank perfectly and be calibrated to the wrong level; the fix for the
    second is a recalibration and the fix for the first is a
    re-development, and a finding that blurs them buys the wrong one.
    """
    aggregate, bands = found.get("CAL-OE"), found.get("CAL-BAND")
    if aggregate is None or not aggregate.measured or aggregate.value is None:
        return None
    if aggregate.state != states.FAIL or aggregate.value <= 1.0:
        return None
    rows = [row for row in (bands.table if bands is not None else [])
            if row.get("observed_default_rate") is not None
            and row.get("average_predicted_pd") is not None]
    if not rows:
        return None
    under = [row for row in rows
             if float(row["observed_default_rate"])
             > float(row["average_predicted_pd"])]
    if len(under) <= len(rows) / 2:
        return None  # not across bands: an aggregate artefact, not this

    # ---- the four explanations, each read off its own evidence -----------
    reads: list[str] = []
    values: dict[str, Any] = {
        "observed_over_expected": round(float(aggregate.value), 6),
        "limit": aggregate.limit,
        "limit_source": aggregate.limit_source,
        "bands_under_predicted": len(under),
        "bands": len(rows),
        "period": aggregate.period,
    }

    standardised = found.get("DATA-MIXADJ")
    if standardised is not None and standardised.measured:
        composition = float(standardised.lineage.get("composition_effect") or 0.0)
        conditional = float(
            standardised.lineage.get("conditional_risk_effect") or 0.0)
        values["composition_effect"] = round(composition, 6)
        values["conditional_risk_effect"] = round(conditional, 6)
        reads.append(
            "Changing composition: standardising onto the development mix "
            f"moves the matured default rate by {composition:+.3%} against "
            f"{conditional:+.3%} from conditional risk, so "
            + ("the book changing shape is the larger part of it"
               if abs(composition) > abs(conditional) else
               "this is not mainly the book changing shape"))

    horizon = found.get("DATA-ODR")
    if horizon is not None and horizon.measured:
        development = float(horizon.lineage.get("development_rate") or 0.0)
        development_pd = None
        for row in horizon.table:
            if row.get("population", "").startswith("Development"):
                development_pd = row.get("mean_predicted_pd")
        if development and development_pd:
            at_development = development / float(development_pd)
            values["development_observed_over_expected"] = round(
                at_development, 6)
            reads.append(
                "Horizon and default definition: the development sample "
                f"itself reads an O/E of {at_development:.2f}, "
                + ("which is the same order as today's, so the gap was "
                   "present at development and is a definition or horizon "
                   "mismatch rather than something the book has done since"
                   if abs(at_development - float(aggregate.value))
                   <= 0.5 * float(aggregate.value) else
                   "materially different from today's, so the gap has opened "
                   "since development rather than being built into it"))

    drift = found.get("CAL-DRIFT")
    if drift is not None and drift.measured and drift.value is not None:
        values["observed_over_expected_change"] = round(float(drift.value), 6)
        reads.append(
            f"Calibration drift: the O/E has moved {float(drift.value):+.3f} "
            "across the measurable cohorts, "
            + ("so the level is moving and a re-calibration has to be dated "
               "rather than applied as a constant"
               if abs(float(drift.value)) >= 0.25 else
               "so the level is stable and a constant re-calibration would "
               "hold"))

    ranking = found.get("DISC-KS") or found.get("DISC-AUC")
    separate = ""
    if ranking is not None and ranking.measured and ranking.value is not None:
        values["discrimination_test"] = ranking.test_id
        values["discrimination_value"] = round(float(ranking.value), 6)
        separate = (
            f" Discrimination is reported separately and is not part of this "
            f"finding: {ranking.test_id} is {float(ranking.value):.4f} and "
            f"{ranking.label.lower()}. "
            + ("The model ranks risk and is calibrated to the wrong level; "
               "those have different fixes."
               if ranking.state in (states.PASS, states.NO_LIMIT) else
               "Both are adverse, and they remain two findings."))

    where = [test_registry.CALIBRATION, test_registry.DATA_QUALITY,
             test_registry.STABILITY, test_registry.SEGMENTATION]
    return Finding(
        finding_id="F-PATTERN-UNDERPREDICTION",
        title=(f"Observed default exceeds predicted PD in {len(under)} of "
               f"{len(rows)} score bands"),
        severity=_severity(aggregate, model, floor=MEDIUM),
        category=test_registry.CALIBRATION,
        also_in=tuple(c for c in where[1:] if c in test_registry.CATEGORIES),
        what=(f"Over {aggregate.period}, observed default runs above the "
              f"predicted PD in {len(under)} of {len(rows)} score bands and "
              f"the aggregate observed-over-expected is "
              f"{float(aggregate.value):.3f} against a limit of "
              f"{aggregate.limit} ({aggregate.limit_source}). "
              + (" ".join(r + "." for r in reads) if reads else "")
              + separate),
        why_it_matters=(
            "A PD that is too low is not a ranking problem, it is a level "
            "problem, and everything priced or provisioned off the PD "
            "carries the same shortfall. Under IFRS 9 the expected credit "
            "loss is linear in PD, so a factor on the PD is a factor on the "
            "provision."),
        remediation=(
            "Re-calibrate the score-to-PD mapping on the latest closed "
            "cohorts and date the calibration, rather than re-fitting the "
            "scorecard. Confirm first that the outcome definition behind "
            "the observed rate is the one the PD was fitted to predict — "
            "the explanations above say whether that is where the gap "
            "starts."),
        verify_by=("CAL-OE inside its limit on the next closed cohort, with "
                   "the band-level observed rate no longer above the "
                   "predicted PD in a majority of bands"),
        evidence=tuple(t for t in ("CAL-OE", "CAL-BAND", "CAL-DRIFT",
                                   "DATA-MIXADJ", "DATA-ODR",
                                   "DISC-KS", "DISC-AUC") if t in found),
        values=values,
        model_id=model.model_id, model_version=model.version,
        period=aggregate.period,
        pattern=pattern.key,
        supersedes=("F-CAL-OE",),
        confidence=_confidence(aggregate))


def _a_local_inversion(pattern: Pattern, found: dict[str, states.Result],
                       model: model_registry.Model) -> Finding | None:
    """A rank inversion, with everything that decides what to do about it.

    §14.4 asks for the size, the support, the concentration and the
    persistence — and then asks something harder: to evaluate whether the
    inversion ACCOMPANIES a weaker KS rather than to claim it causes one.
    The two are separate measurements of the same score, and a run that
    asserts a direction between them has asserted something its own evidence
    does not contain. So this reports both and says they coincide.
    """
    ordering = found.get("DISC-RANK")
    if ordering is None or not ordering.measured or not ordering.value:
        return None
    spots = ordering.lineage.get("inversions") or []
    if not spots:
        return None
    worst = spots[0]
    persistence = worst.get("persistence") or {}
    concentration = worst.get("concentration") or {}

    separated = worst.get("separated_by_the_evidence")
    persistent = (persistence.get("assessable", 0) > 0
                  and persistence["inverted"] > persistence["assessable"] / 2)
    # Severity is the evidence, not the size. An inversion inside the
    # sampling noise in one cohort is an observation; the same pair
    # inverting in most closed cohorts is a finding whether or not either
    # single cohort separates.
    floor = (MEDIUM if separated or persistent else OBSERVATION)

    separate = ""
    ranking = found.get("DISC-KS") or found.get("DISC-AUC")
    if ranking is not None and ranking.measured and ranking.value is not None:
        weak = ranking.state in (states.FAIL, states.WARNING)
        separate = (
            f" {ranking.test_id} on the same population is "
            f"{float(ranking.value):.4f} and {ranking.label.lower()}. "
            + ("The inversion and the weaker separation accompany each "
               "other; neither of these results says which produced the "
               "other, and one run cannot."
               if weak else
               "The score separates defaulters from non-defaulters well "
               "overall, so this is a local ordering defect rather than a "
               "model that has stopped ranking."))

    peer = found.get("DISC-RANK-PEER")
    comparison = ""
    if peer is not None and peer.measured:
        comparison = " " + peer.detail

    return Finding(
        finding_id="F-PATTERN-LOCAL-INVERSION",
        title=(f"The default rate rises between {worst['riskier_band']} and "
               f"{worst['safer_band']}, against the score"),
        severity=_severity(ordering, model, floor=floor),
        category=test_registry.DISCRIMINATION,
        also_in=(test_registry.SEGMENTATION,),
        what=(f"{ordering.detail}{separate}{comparison}"),
        why_it_matters=(
            "A band that defaults more than the riskier band beneath it is "
            "a band being treated as safer than it is, and every decision "
            "keyed to the band — a limit increase, a collections priority, "
            "a pricing tier — is taken the wrong way round inside it. The "
            "portfolio statistic does not show this: the rank ordering of "
            "the book as a whole can be, and here is, unaffected."),
        remediation=(
            "Take the two bands and the concentration to whoever owns the "
            "binning specification. Where one segment dominates the "
            "inverting band, the question is whether it belongs in a "
            "separate segment rather than whether the scorecard needs "
            "re-fitting. Do not re-band on one cohort."),
        verify_by=("DISC-RANK reporting no adjacent inversion between the "
                   "same two bands on the next closed cohort"),
        evidence=tuple(t for t in ("DISC-RANK", "DISC-RANK-PEER", "DISC-KS",
                                   "DISC-AUC") if t in found),
        values={
            "inversions": int(ordering.value),
            "safer_band": worst["safer_band"],
            "riskier_band": worst["riskier_band"],
            "size": worst["size"],
            "accounts_safer": worst["accounts_safer"],
            "accounts_riskier": worst["accounts_riskier"],
            "intervals_overlap": worst["intervals_overlap"],
            "cohorts_inverted": persistence.get("inverted"),
            "cohorts_assessable": persistence.get("assessable"),
            "concentrated_in": (
                f"{concentration.get('field')}={concentration.get('level')}"
                if concentration else ""),
        },
        model_id=model.model_id, model_version=model.version,
        period=ordering.period,
        pattern=pattern.key,
        supersedes=("F-DISC-RANK",),
        confidence=_confidence(ordering))


PATTERNS: tuple[Pattern, ...] = (
    Pattern("not_what_was_approved",
            "Production does not match the specification",
            ("IMPL-REPLICATE",), _not_what_was_approved),
    Pattern("aggregate_conceals_segment",
            "Portfolio calibration conceals a segment",
            ("CAL-OE", "SEG-CALIBRATION"), _aggregate_conceals_segment),
    Pattern("cut_off_not_believed",
            "The cut-off is being overridden at its boundary",
            ("USE-OVERRIDE-OUTCOME", "USE-MATRIX"), _the_cut_off_is_not_believed),
    Pattern("definition_change",
            "Drift that is a definition change",
            ("STAB-CSI", "VAR-IV"), _drift_is_a_definition_change),
    Pattern("borrowed_power",
            "Passing on the strength of the other characteristics",
            ("DISC-AUC", "VAR-IV"), _holding_up_on_borrowed_power),
    Pattern("short_matured_window",
            "Most of the book has no outcome yet",
            ("DATA-MATURITY",), _the_window_is_too_short),
    Pattern("challenger_inside_the_noise",
            "A challenger advantage inside the champion's interval",
            ("CC-DISCRIMINATION", "ROB-BOOTSTRAP"), _challenger_is_not_better),
    Pattern("less_representative",
            "The book no longer resembles the development sample",
            ("DATA-INPUT-DRIFT",), _population_is_less_representative),
    Pattern("shared_underprediction",
            "Observed default above predicted PD across bands",
            ("CAL-OE", "CAL-BAND"), _shared_underprediction),
    Pattern("local_inversion",
            "The score inverts between two adjacent bands",
            ("DISC-RANK",), _a_local_inversion),
)


def _worst_segment(result: states.Result) -> dict[str, Any]:
    return _worst_row(result, "segment")


def _worst_row(result: states.Result, label: str,
               key: str = "") -> dict[str, Any]:
    """The row a result's own table puts first, or the largest on `key`."""
    rows = [row for row in result.table if label in row]
    if not rows:
        return {}
    if key:
        return max(rows, key=lambda row: float(row.get(key) or 0.0))
    return rows[0]


# ------------------------------------------------------------------ the run


def assess(results: list[states.Result],
           model: model_registry.Model) -> list[Finding]:
    """Every finding these results support, most severe first.

    Single-test findings first so nothing is lost, then the patterns, then
    the superseded singles are dropped — in that order, because a pattern
    that failed to match must leave its single-test findings standing.
    """
    found = {r.test_id: r for r in results}
    singles = {f.finding_id: f
               for f in (_single(r, model) for r in results) if f}

    patterns: list[Finding] = []
    for pattern in PATTERNS:
        made = pattern.apply(found, model)
        if made is not None:
            patterns.append(made)

    # Gini is 2·AUC − 1, so a discrimination shortfall reported by both is
    # the same finding written twice, and a reader who sees two rows counts
    # two problems. The AUC one is kept because it is the figure the limit
    # is usually set on.
    if "F-DISC-AUC" in singles and "F-DISC-GINI" in singles:
        singles.pop("F-DISC-GINI")

    superseded = {test_id for f in patterns for test_id in f.supersedes}
    kept = [f for key, f in singles.items() if key not in superseded]
    return rank([_cite(f) for f in (*patterns, *kept)])


def _cite(made: Finding) -> Finding:
    """Fill in the supervisory references from the evidence.

    Derived rather than declared. The test registry records what each test
    evidences; a finding restating that in its own words would be a second
    opinion about the same thing, and the first time a reference changed
    only one of them would be updated. A reader who wants to know why a
    finding cites MMS 10.4 can follow it to the tests that say so.
    """
    references: list[str] = []
    for test_id in made.evidence:
        test = test_registry.BY_ID.get(test_id)
        if test is None:
            continue
        references.extend(r for r in test.cbuae if r not in references)
    return replace(made, cbuae=tuple(references))


def rank(findings: list[Finding]) -> list[Finding]:
    """Most severe first; within a severity, patterns before single tests.

    A pattern outranks a single test at the same severity because it is the
    more complete statement of the same evidence, and a reader who stops
    after the first three rows should be reading the complete ones.
    """
    return sorted(findings,
                  key=lambda f: (f.rank, 0 if f.pattern else 1, f.finding_id))


def burning(findings: list[Finding], limit: int = 5) -> list[Finding]:
    """The few a model owner should act on first.

    Deliberately short, and deliberately not "everything at HIGH and above":
    a list of thirty urgent things is a list of nothing urgent. Where fewer
    than `limit` findings are severe, the list is shorter rather than padded
    with observations.
    """
    severe = [f for f in rank(findings)
              if f.severity in (CRITICAL, HIGH, MEDIUM)]
    return severe[:limit]


def summary(findings: list[Finding]) -> dict[str, Any]:
    counts = dict.fromkeys(SEVERITIES, 0)
    for made in findings:
        counts[made.severity] += 1
    return {
        "findings_version": FINDINGS_VERSION,
        "total": len(findings),
        "by_severity": counts,
        "patterns_matched": sorted({f.pattern for f in findings if f.pattern}),
        "burning": [f.finding_id for f in burning(findings)],
        "severity_meaning": SEVERITY_MEANING,
    }


__all__ = [
    "CRITICAL", "FINDINGS_VERSION", "HIGH", "LOW", "MEDIUM", "OBSERVATION",
    "PATTERNS", "SEVERITIES", "SEVERITY_MEANING", "Finding", "Pattern",
    "assess", "burning", "rank", "summary",
]
