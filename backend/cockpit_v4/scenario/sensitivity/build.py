"""Turning a built book into its published sensitivity artifact.

The one place that joins the three halves of this package: `panel.py` reduces
a release to twenty period-level observations, `estimate.py` fits a slope to
each factor, `readiness.py` says what that slope may be called, and this
module writes the result into the frame `whatif_*_sensitivity` declares.

It is imported by `scripts/whatif/seed_candidate.py`, which publishes, and by
`scripts/whatif/build_sensitivities.py`, which writes the methodology cards
and checks them against what was published. Nothing a chat turn reaches
imports it -- section 7.1's *"Training work is never an unannounced side
effect of asking a question"* is kept by the import graph, not by a comment.

`verify()` runs section 7.2's finite-difference check on every row before it
is published: the analytic `q(1−q)·β` is compared with the slope the fitted
function actually has, measured by walking `parameter_after`. A missing
logistic derivative, a factor of a hundred or an inverse link applied twice
all show up there as a disagreement rather than as a plausible number.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from backend.cockpit_v4 import domains as dom
from backend.cockpit_v4.scenario.generate import macro as mv
from backend.cockpit_v4.scenario.sensitivity import artifact as art
from backend.cockpit_v4.scenario.sensitivity import estimate as est
from backend.cockpit_v4.scenario.sensitivity import panel
from backend.cockpit_v4.scenario.sensitivity import readiness as rd

#: How much the analytic derivative and the measured one may differ, relative
#: to the analytic one. They are two routes to the same number and agree to
#: far better than this; the tolerance exists so that the check fails on a
#: mistake rather than on the last bit of a float.
DERIVATIVE_TOLERANCE = 1e-6


@dataclass(frozen=True)
class _Shape:
    exposure_relation: str
    artifact_relation: str
    key: str
    period_column: str


SHAPES: dict[str, _Shape] = {
    dom.CORPORATE: _Shape("corp_facility_quarter", "whatif_corp_sensitivity",
                          "facility_id", "reporting_quarter"),
    dom.RETAIL: _Shape("retail_account_month", "whatif_retail_sensitivity",
                       "account_id", "reporting_month"),
}


@dataclass(frozen=True)
class Artifact:
    """A fitted artifact, before it becomes parquet."""

    domain_id: str
    book: panel.Book
    fits: tuple[est.Fit, ...]
    rows: tuple[dict[str, Any], ...]
    digest: str

    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for fit in self.fits:
            counts[fit.verdict.status] = counts.get(fit.verdict.status, 0) + 1
        return counts

    def supported(self) -> tuple[est.Fit, ...]:
        return tuple(f for f in self.fits if f.verdict.publishable)

    def responses(self) -> dict[tuple[str, str], float]:
        """The stated ranking measure, keyed for `artifact.rank`."""
        return {(f.parameter, f.factor_id): f.standardised_response
                for f in self.fits}


def verify(fits: Sequence[est.Fit]) -> list[str]:
    """Section 7.2's finite-difference validation. Returns the failures."""
    bad: list[str] = []
    for fit in fits:
        measured = est.finite_difference(fit)
        scale = max(abs(fit.native_derivative), 1e-12)
        if abs(measured - fit.native_derivative) / scale > DERIVATIVE_TOLERANCE:
            bad.append(
                f"{fit.parameter}/{fit.factor_id} lag {fit.lag}: published "
                f"{fit.native_derivative:.8f}, measured {measured:.8f}")
    return bad


def fit_release(frames: dict[str, Any], *, domain_id: str, release_id: str,
                periods: Sequence[str],
                tenant_id: str) -> Artifact:
    """Fit one built release and produce its artifact rows.

    Raises if the finite-difference check fails. A published derivative that
    disagrees with the function it claims to describe is not a row to ship
    with a warning attached.
    """
    domain_id = dom.parse(domain_id)
    shape = SHAPES[domain_id]
    book = panel.read_book(
        frames, domain_id=domain_id, release_id=release_id, periods=periods,
        exposure_relation=shape.exposure_relation, key=shape.key,
        period_column=shape.period_column)
    fits = panel.fit_book(book)
    failures = verify(fits)
    if failures:
        raise AssertionError(
            "the published native derivative disagrees with the slope the "
            "fitted function actually has:\n  " + "\n  ".join(failures))

    digest = book.digest
    rows = art.rows(
        fits, domain_id=domain_id, period=book.periods[-1],
        period_column=shape.period_column, release_id=release_id,
        fingerprint=digest, tenant_id=tenant_id,
        conventions=panel.conventions(domain_id), method=est.METHOD,
        fitted_at=book.periods[-1],
        unavailable=panel.unavailable(domain_id))
    return Artifact(domain_id=domain_id, book=book, fits=tuple(fits),
                    rows=tuple(rows), digest=digest)


def frame(fitted: Artifact) -> Any:
    """The artifact as the DataFrame `lake.publish` expects."""
    import pandas as pd

    return pd.DataFrame(list(fitted.rows))


def attach(build: Any, *, tenant_id: str) -> Artifact:
    """Fit a `lake.Build` in place and return the artifact that was attached.

    This is what makes a published candidate carry real sensitivities rather
    than `corporate.pending_artifact_rows`'s honest placeholder: the build is
    already in memory, so the fit reads the same numbers that are about to
    become parquet and there is no window in which the two could differ.
    """
    fitted = fit_release(
        build.frames, domain_id=build.domain_id, release_id=build.release_id,
        periods=build.periods, tenant_id=tenant_id)
    build.frames[SHAPES[fitted.domain_id].artifact_relation] = frame(fitted)
    build.notes["sensitivity_input_digest"] = fitted.digest
    build.notes["sensitivity_cohort"] = {
        "exposures": fitted.book.cohort_size,
        "weight_period": fitted.book.weight_period,
        "excluded_ever_defaulted": fitted.book.excluded_defaulted,
        "excluded_not_in_every_period": fitted.book.excluded_partial}
    build.notes["sensitivity_readiness"] = fitted.by_status()
    return fitted


def card(fitted: Artifact, *, fingerprint: str) -> str:
    """`SENSITIVITY_CARD_*.md`: what was fitted, on what, and what it isn't.

    Section 7.4 asks for the estimation window, transformation, lag, native
    units, the evaluation point, uncertainty, the readiness status and the
    limitation, for every factor -- and for the ranking measure to be stated
    rather than inferred from the order. All of that is here, and so is the
    sentence that the whole card is about generated data.
    """
    book = fitted.book
    noun = "quarter" if fitted.domain_id == dom.CORPORATE else "month"
    label = "Corporate" if fitted.domain_id == dom.CORPORATE else "Retail"
    counts = fitted.by_status()
    slopes = [art.from_row(r) for r in fitted.rows]
    ranked = art.rank([s for s in slopes if s.parameter == "pd_pit_12m"],
                      fitted.responses())

    lines: list[str] = [
        f"# Macro sensitivity card — {label}",
        "",
        f"`{book.release_id}` · artifact `{art.ARTIFACT_VERSION}` · "
        f"estimator `{est.METHOD}`",
        "",
        "> **Fitted on generated data.** Every number below was estimated "
        "from a synthetic book against a generated macroeconomic panel. It "
        "establishes that the estimator recovers a relationship that was put "
        "into the data on purpose. **It is not a bank-validated sensitivity, "
        "and the panel is not observed economic history.**",
        "",
        "## What was fitted",
        "",
        "```",
        "y_t  =  logit(q_t) − logit(q_{t−1})",
        "x_t  =  z_{t−lag} − z_{t−lag−1}        z in native units",
        "y_t  =  α + β x_t + ε_t                ridge, penalty "
        f"{est.PENALTY}",
        "```",
        "",
        f"The published slope is **not** β. It is `q(1−q) × β`, in percentage "
        f"points of the parameter per one native unit of the factor, "
        f"evaluated at a stated `q` and a stated `z`. Every row was checked "
        f"against a finite difference of the fitted function to within "
        f"{DERIVATIVE_TOLERANCE:g} relative.",
        "",
        "## The sample",
        "",
        "| | |",
        "|---|---|",
        f"| Calendar | {len(book.periods)} {noun}s, "
        f"{book.periods[0]}–{book.periods[-1]} |",
        f"| Distinct macro observations | **{len(book.periods)}** — not "
        f"{book.cohort_size * len(book.periods):,} exposure-{noun}s |",
        f"| Fixed cohort | {book.cohort_size:,} exposures present in every "
        f"{noun} and performing throughout |",
        f"| Excluded, ever defaulted | {book.excluded_defaulted:,} |",
        f"| Excluded, not in every {noun} | {book.excluded_partial:,} |",
        f"| Weights | EAD frozen at {book.weight_period} |",
        f"| Scenario | {panel.FIT_SCENARIO} |",
        f"| Lags considered | {', '.join(str(x) for x in est.LAGS)}, chosen "
        f"on training-only forward validation error |",
        f"| Training share | {est.TRAINING_SHARE:.0%} of the differenced "
        f"series |",
        f"| Uncertainty | {rd.RESAMPLES} contiguous "
        f"{rd.BLOCK_PERIODS}-{noun} block resamples, seed "
        f"{rd.RESAMPLE_SEED} |",
        f"| Input digest | `{fitted.digest[:16]}…` |",
        "",
        "## Readiness",
        "",
        "| Status | Rows |",
        "|---|---|",
    ]
    for status in rd.STATUSES:
        if counts.get(status):
            lines.append(f"| `{status}` | {counts[status]} |")
    absent = len(panel.unavailable(fitted.domain_id))
    if absent:
        lines.append(f"| `{rd.UNAVAILABLE}` | {absent * 3} "
                     f"({absent} factors × 3 parameters) |")
    lines += [
        "",
        f"The complexity ceiling is `max(1, floor((training − 5) / 5))`, "
        f"which on this history is "
        f"{rd.max_effective_df(max((f.training_periods for f in fitted.fits), default=0)):.0f}"
        f". **The ceiling is read as governing predictor complexity; the "
        f"intercept is not charged against it.** Counting the intercept, a "
        f"single-regressor ridge scores about 1.9 and every row here would be "
        f"`{rd.DIAGNOSTIC_ONLY}` — including an intercept-only model at "
        f"exactly 1.0, which is why that reading cannot be what a budget for "
        f"'how much complexity does this history support' means. The slopes "
        f"and their intervals would be identical under either reading; only "
        f"automatic translation would stop.",
        "",
        "## PD sensitivities, ranked",
        "",
        "Ranked by the **response of the parameter to one training-period "
        "standard deviation of the factor** — stated here rather than left to "
        "be inferred from the order, and magnitude is not evidence of causal "
        "importance.",
        "",
        "| Factor | Name | Lag | Slope (pp per native unit) | 95% interval | "
        "Sign stability | VIF | Readiness |",
        "|---|---|---|---|---|---|---|---|",
    ]
    by_key = {(f.parameter, f.factor_id, f.lag): f for f in fitted.fits}
    for slope in ranked:
        fit = by_key.get((slope.parameter, slope.factor_id, slope.lag))
        if fit is None:
            continue
        name = mv.BY_ID[slope.factor_id].name
        lines.append(
            f"| {slope.factor_id} | {name} | {slope.lag} | "
            f"{slope.native_derivative:+.4f} | "
            f"{fit.ci_low:+.4f} to {fit.ci_high:+.4f} | "
            f"{fit.sign_stability:.0%} | {fit.collinearity:.2f} | "
            f"`{fit.verdict.status}` |")

    lines += [
        "",
        "## Factors this book does not carry",
        "",
        "An absent factor is `UNAVAILABLE`. It is never a sensitivity of "
        "zero, and no value is imputed for it from a related series.",
        "",
        "| Factor | Why |",
        "|---|---|",
    ]
    for factor_id, reason in panel.unavailable(fitted.domain_id):
        lines.append(f"| {factor_id} | {reason} |")

    lines += [
        "",
        "## Using a slope",
        "",
        "Section 7.4's worked example, which is also an oracle in "
        "`tests/cockpit_v4/test_whatif_sensitivity.py`:",
        "",
        "> Unemployment 6.0% cut by 10% is **5.4%**, a change of **−0.6 "
        "percentage points** — not −4% and not a ten-point move. At a slope "
        "of +0.20 PD points per unemployment point, a baseline PD of 3.00% "
        "becomes **2.88%**.",
        "",
        f"Two translations are offered by name and neither is substituted "
        f"for the other: `{art.LINEAR}` is the reader's own "
        f"sensitivity-times-change reading, and `{art.NONLINEAR}` adds the "
        f"fitted linear-predictor change to the observed baseline logit and "
        f"inverts, so a zero shock returns the observed baseline exactly. A "
        f"shock outside the fitted range carries an extrapolation warning.",
        "",
        "A row whose readiness is not `SUPPORTED_ESTIMATE` is **refused** for "
        "automatic translation. The reader may still state the parameter "
        "change they want to assume, and it is then applied and labelled as "
        f"`{rd.USER_ASSUMPTION}` rather than as an estimate.",
        "",
        "## Staleness",
        "",
        f"Each row stores `source_release_id` and a `source_fingerprint` of "
        f"`{fitted.digest[:16]}…`. That fingerprint is a SHA-256 over the "
        f"exact period-level series the fit consumed, not the release's own "
        f"fingerprint (`{fingerprint[:16]}…`): an artifact stored inside the "
        f"release it describes cannot carry a fingerprint taken over bytes "
        f"that include it. A fit whose stored digest does not match the one "
        f"recomputed from the release in use is `{rd.STALE}` and is refused.",
        "",
    ]
    return "\n".join(lines)


__all__ = ["Artifact", "DERIVATIVE_TOLERANCE", "SHAPES", "attach", "card",
           "fit_release", "frame", "verify"]
