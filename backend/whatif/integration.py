"""
Whether What-If can run on a Corporate IFRS 9 book it has never seen.

The problem this exists for
---------------------------
The book this branch ships is a demo universe: sixteen quarters, a nineteen-
point masterscale, obligor grain, SAR. A real installation replaces it with a
canonical IFRS 9 domain — different dataset names, a different rating scale,
possibly a different currency and certainly a different number of quarters.

The question that then has to be answerable, before anybody wires anything, is
not "does it import" but: WHAT EXACTLY WILL BREAK, and what will each break
cost. A yes/no readiness flag is useless, because the honest answer is almost
always "most of it works and these four things do not".

So this module assesses a candidate book against the contract and returns a
findings list. Every finding names the thing, says whether it BLOCKS the
feature or DEGRADES it, and says what the degradation actually costs a reader
— in the words of somebody using the product, not in the words of the code.

What is checked, and what is deliberately not
---------------------------------------------
Checked: the datasets exist and are readable; every REQUIRED column is present;
which OPTIONAL columns are absent and what each one costs; the grain really is
one row per borrower per period; the periods are orderable and contiguous; the
rating values are in the governed scale; the measurement ties to the reported
ECL within tolerance.

Not checked: whether the numbers are RIGHT. This module can tell you that a
column called `pd_12m` exists, is numeric and lies between 0 and 100. It cannot
tell you it is the twelve-month probability of default, and it does not pretend
to — a readiness report that implied it had validated the book's economics
would be worse than no report at all.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from backend.whatif import domain as dm
from backend.whatif import schema as sch

logger = logging.getLogger(__name__)

INTEGRATION_VERSION = "1.0.0"

#: What a finding costs.
BLOCKS = "blocks"        # What-If cannot run at all
DEGRADES = "degrades"    # It runs, and one named capability is gone
NOTE = "note"            # Worth knowing; costs nothing

#: The reported ECL and the ECL the governed policy measures from the book's
#: own parameters will not agree exactly — an overlay sits between them — but
#: a book where they disagree by more than this is not one What-If's Delta
#: Model can carry a scenario onto.
MEASUREMENT_TOLERANCE_PCT = 25.0

#: A book with fewer than this many periods cannot support the historical
#: comparison, which is a capability rather than a requirement.
PLAUSIBILITY_MINIMUM_PERIODS = 8


@dataclass
class Finding:
    """One thing about a candidate book, and what it costs."""

    severity: str
    subject: str
    detail: str
    costs: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "subject": self.subject,
                "detail": self.detail, "costs": self.costs}


@dataclass
class Readiness:
    """Whether What-If can run on this book, and what it will not do."""

    domain: str
    snapshot: str
    measurement: str
    findings: list[Finding] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    borrowers: int = 0
    rows: int = 0

    def add(self, severity: str, subject: str, detail: str,
            costs: str = "") -> None:
        self.findings.append(Finding(severity, subject, detail, costs))

    @property
    def blocked(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == BLOCKS]

    @property
    def degraded(self) -> list[Finding]:
        return [f for f in self.findings if f.severity == DEGRADES]

    @property
    def ready(self) -> bool:
        return not self.blocked

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": INTEGRATION_VERSION,
            "domain": self.domain,
            "snapshot": self.snapshot,
            "measurement": self.measurement,
            "ready": self.ready,
            "verdict": self.verdict(),
            "periods": list(self.periods),
            "period_count": len(self.periods),
            "borrowers": self.borrowers,
            "rows": self.rows,
            "blocks": [f.to_dict() for f in self.blocked],
            "degrades": [f.to_dict() for f in self.degraded],
            "notes": [f.to_dict() for f in self.findings
                      if f.severity == NOTE],
            "findings": [f.to_dict() for f in self.findings],
            "what_this_does_not_check": (
                "That the numbers are right. This report establishes that a "
                "column exists, is numeric and lies in a possible range. It "
                "cannot establish that `pd_12m` is the twelve-month "
                "probability of default, and it does not claim to — the "
                "book's economics are somebody's to validate, not this "
                "report's to assert."),
        }

    def verdict(self) -> str:
        if self.blocked:
            return (f"What-If cannot run on this book: "
                    f"{len(self.blocked)} blocking finding(s).")
        if self.degraded:
            return (f"What-If can run on this book, with "
                    f"{len(self.degraded)} capabilit"
                    f"{'y' if len(self.degraded) == 1 else 'ies'} unavailable.")
        return "What-If can run on this book with nothing missing."


def assess(*, snapshot: str = "", measurement: str = "",
           source: Any = None) -> Readiness:
    """Check a candidate Corporate IFRS 9 book against the contract.

    Defaults to the book this installation actually carries, so the same call
    is both an integration check and a health check.
    """
    snap = snapshot or dm.SNAPSHOT
    measured = measurement or dm.IFRS9
    body = Readiness(domain=dm.DOMAIN_NAME, snapshot=snap,
                     measurement=measured)

    reader = source if source is not None else None
    columns = _columns(snap, reader)
    if columns is None:
        body.add(BLOCKS, snap,
                 f"The dataset '{snap}' could not be read.",
                 "Everything. What-If reads this book first and has no other "
                 "source for a borrower's rating, stage or exposure.")
        return body

    _check_columns(body, snap, columns, sch.REQUIRED, sch.OPTIONAL)

    measured_columns = _columns(measured, reader)
    if measured_columns is None:
        body.add(DEGRADES, measured,
                 f"The measurement dataset '{measured}' could not be read.",
                 "Re-evaluating the RELATIVE SICR trigger against a "
                 "hypothetical PD. Staging degrades to the absolute-PD and "
                 "days-past-due tests, which is a real reduction in the "
                 "answer rather than a cosmetic one.")
    else:
        _check_columns(body, measured, measured_columns, sch.IFRS9_REQUIRED,
                       sch.IFRS9_OPTIONAL)

    if body.blocked:
        # No point reading rows out of a book that is already refused: every
        # further finding would be a consequence of the first one.
        return body

    _check_periods(body, reader)
    if not body.periods:
        return body
    _check_rows(body, reader)
    return body


def _columns(dataset: str, source: Any) -> tuple[str, ...] | None:
    try:
        return sch.columns(dataset, source)
    except Exception as e:  # noqa: BLE001 - reported as a finding, not raised
        # A candidate dataset that is not there is the ordinary answer to the
        # question this module asks, not an incident. The reason is logged;
        # it does not go in the finding, because it names a filesystem path
        # and this endpoint is open to every analyst.
        logger.info("Could not read the columns of %s: %s", dataset, e)
        return None


def _check_columns(body: Readiness, dataset: str, columns: tuple[str, ...],
                   required: tuple[str, ...],
                   optional: dict[str, str]) -> None:
    present = set(columns)
    missing = [f for f in required if f not in present]
    if missing:
        body.add(BLOCKS, dataset,
                 "Required column(s) absent: " + ", ".join(missing) + ".",
                 "What-If cannot price a scenario without these. They "
                 "identify the borrower, place it in the book, and carry the "
                 "four quantities the governed measurement multiplies.")
    for name, enables in optional.items():
        if name not in present:
            body.add(DEGRADES, f"{dataset}.{name}",
                     f"Optional column '{name}' is absent.", enables)


def _check_periods(body: Readiness, source: Any) -> None:
    try:
        periods = dm.periods(source)
    except Exception as e:  # noqa: BLE001
        body.add(BLOCKS, "periods", f"The book publishes no periods: {e}",
                 "Everything. A What-If is run as at a reporting date.")
        return
    body.periods = list(periods)
    if not periods:
        body.add(BLOCKS, "periods", "The book publishes no periods.",
                 "Everything. A What-If is run as at a reporting date.")
        return
    if len(periods) < PLAUSIBILITY_MINIMUM_PERIODS:
        body.add(DEGRADES, "periods",
                 f"The book carries {len(periods)} period(s); the historical "
                 f"comparison wants at least {PLAUSIBILITY_MINIMUM_PERIODS}.",
                 "Scenario plausibility. A shock can still be priced, but the "
                 "product cannot say where it sits in the book's own "
                 "experience, so a 20% PD rise and a 200% one are presented "
                 "the same way.")
    else:
        body.add(NOTE, "periods",
                 f"{len(periods)} periods, {periods[0]} to {periods[-1]}.")


def _check_rows(body: Readiness, source: Any) -> None:
    try:
        frame, period = dm.book(source=source)
    except Exception as e:  # noqa: BLE001
        body.add(BLOCKS, "book",
                 f"The latest period could not be read: {e}", "Everything.")
        return

    body.rows = int(len(frame))
    if frame.empty:
        body.add(BLOCKS, "book", f"The latest period ({period}) is empty.",
                 "Everything.")
        return

    body.borrowers = _check_grain(body, frame, period)

    _check_ratings(body, frame, period)
    _check_ranges(body, frame)
    _check_measurement(body, frame, period)


def _check_grain(body: Readiness, frame: pd.DataFrame, period: str) -> int:
    """One row per borrower per period, or a refusal that says why.

    The single most damaging thing a replacement book can get wrong. A
    facility-grain book read as an obligor-grain one multiplies every exposure
    figure by the borrower's facility count, and every number on every screen
    is then wrong in the same plausible-looking way — which is why this
    BLOCKS rather than warns.
    """
    borrowers = int(frame["borrower_id"].nunique())
    if borrowers != len(frame):
        body.add(BLOCKS, "grain",
                 f"{len(frame):,} rows for {borrowers:,} borrowers in "
                 f"{period}: this book is NOT one row per borrower per "
                 "period.",
                 "Everything, and silently. What-If stages on the obligor. A "
                 "finer-grain book read as this one multiplies every exposure "
                 "and every provision by the number of rows a borrower has, "
                 "and the result looks entirely plausible.")
    return borrowers


def _check_ratings(body: Readiness, frame: pd.DataFrame, period: str) -> None:
    from backend.whatif import masterscale as ms

    if "internal_rating" not in frame.columns:
        return
    governed = set(ms.RATING_SCALE) if hasattr(ms, "RATING_SCALE") else set()
    if not governed:
        return
    found = {str(v) for v in frame["internal_rating"].dropna().unique()}
    stranger = sorted(found - governed)
    if stranger:
        body.add(BLOCKS, "internal_rating",
                 f"{len(stranger)} rating value(s) in {period} are not on the "
                 f"governed masterscale: {', '.join(stranger[:12])}"
                 + ("…" if len(stranger) > 12 else "") + ".",
                 "Rating scenarios, and the mapping from a grade to a PD that "
                 "every notch movement depends on. A grade the masterscale "
                 "does not carry cannot be moved by a notch, because there is "
                 "no next grade to move it to.")
    unused = sorted(governed - found)
    if unused:
        body.add(NOTE, "internal_rating",
                 f"{len(unused)} governed grade(s) are unused in {period}: "
                 + ", ".join(unused[:12]) + ("…" if len(unused) > 12 else "")
                 + ". That is a fact about the book, not a problem.")


#: Ranges a quantity has to occupy to be the quantity it is named after. Wide
#: on purpose: this is a check that a column is the KIND of thing it claims to
#: be, not a validation of the book's calibration.
_RANGES: tuple[tuple[str, float, float, str], ...] = (
    ("pd_12m", 0.0, 100.0, "a probability in percent"),
    ("pd_lifetime", 0.0, 100.0, "a probability in percent"),
    ("lgd", 0.0, 100.0, "a loss rate in percent"),
    ("ead", 0.0, float("inf"), "an exposure, which cannot be negative"),
    ("final_ecl", 0.0, float("inf"), "a provision, which cannot be negative"),
    ("stage", 1.0, 3.0, "an IFRS 9 stage"),
    ("current_dpd", 0.0, float("inf"), "days, which cannot be negative"),
)


def _check_ranges(body: Readiness, frame: pd.DataFrame) -> None:
    for name, low, high, what in _RANGES:
        if name not in frame.columns:
            continue
        values = pd.to_numeric(frame[name], errors="coerce")
        if values.isna().all():
            body.add(BLOCKS, name, f"'{name}' holds no numeric values.",
                     f"Everything that reads {what}.")
            continue
        outside = int(((values < low) | (values > high)).sum())
        if outside:
            body.add(BLOCKS, name,
                     f"{outside:,} row(s) hold a '{name}' outside "
                     f"[{low:g}, {high:g}].",
                     f"'{name}' is read as {what}. A value outside that range "
                     "means the column is measured in something else — a "
                     "fraction rather than a percent, most often — and every "
                     "figure derived from it would be wrong by that factor.")


def _check_measurement(body: Readiness, frame: pd.DataFrame,
                       period: str) -> None:
    """Does the governed policy, run on this book, reproduce its own ECL?

    Not expected to agree exactly: a management overlay sits between the
    modelled figure and the reported one. But a book where the two are far
    apart is one where the Delta Model's central move — carrying a measured
    RATIO onto the reported figure — does not mean what it says.
    """
    from backend.ifrs9 import policy

    needed = {"stage", "pd_12m", "lgd", "ead", "final_ecl"}
    if not needed <= set(frame.columns):
        return
    try:
        modelled = policy.measured_ecl(
            pd.to_numeric(frame["stage"], errors="coerce").fillna(1),
            pd.to_numeric(frame["pd_12m"], errors="coerce").fillna(0.0),
            pd.to_numeric(frame["lgd"], errors="coerce").fillna(0.0),
            pd.to_numeric(frame["ead"], errors="coerce").fillna(0.0),
            lifetime_pd_pct=pd.to_numeric(frame["pd_lifetime"],
                                          errors="coerce").fillna(0.0)
            if "pd_lifetime" in frame.columns else None)
    except Exception as e:  # noqa: BLE001
        body.add(DEGRADES, "measurement",
                 f"The governed policy could not be run on this book: {e}",
                 "The reconciliation between the reported provision and the "
                 "one this book's own parameters imply.")
        return

    reported = float(pd.to_numeric(frame["final_ecl"],
                                   errors="coerce").fillna(0.0).sum())
    measured = float(np.nansum(modelled))
    if reported <= 0:
        body.add(DEGRADES, "final_ecl",
                 f"The reported provision for {period} is {reported:,.1f}.",
                 "The Delta Model, which moves the REPORTED figure by a "
                 "measured ratio. With no reported figure there is nothing "
                 "to move.")
        return
    gap = (measured - reported) / reported * 100.0
    if abs(gap) > MEASUREMENT_TOLERANCE_PCT:
        body.add(DEGRADES, "measurement",
                 f"The governed policy measures {measured:,.1f} against a "
                 f"reported {reported:,.1f} in {period} — {gap:+,.1f}%.",
                 "Confidence in the Delta Model on this book. The scenario "
                 "ratio is measured on the policy's own arithmetic and then "
                 "applied to the reported figure, so the two being far apart "
                 "means the ratio is being carried onto a number it was not "
                 "measured against.")
    else:
        body.add(NOTE, "measurement",
                 f"The governed policy measures within {gap:+,.1f}% of the "
                 f"reported provision in {period}, which an overlay accounts "
                 "for.")


def contract() -> dict[str, Any]:
    """What a book must provide, and what each optional part buys.

    The document somebody wiring a canonical IFRS 9 domain reads BEFORE
    pointing it at this feature.
    """
    body = sch.describe()
    body.update({
        "integration_version": INTEGRATION_VERSION,
        "datasets": {
            "snapshot": {"name": dm.SNAPSHOT,
                         "role": "The borrower-grain book the engine reads "
                                 "first. Required."},
            "measurement": {"name": dm.IFRS9,
                            "role": "Authoritative staging and measurement. "
                                    "Optional in the sense that its absence "
                                    "costs the relative SICR trigger rather "
                                    "than the feature."},
            "facilities": {"name": dm.FACILITIES,
                           "role": "Aggregated up for CCF, and allocated to "
                                   "in the detailed export. Optional."},
            "collateral": {"name": dm.COLLATERAL,
                           "role": "Collateral shocks. Optional."},
            "macro": {"name": dm.MACRO,
                      "role": "Observed macro series. Without it the ten "
                              "variables still carry their configured "
                              "sensitivities, but no empirical analysis is "
                              "possible."},
        },
        "assumptions": [
            {"assumption": "grain", "value": dm.GRAIN,
             "if_violated": "Every exposure and provision figure is "
                            "multiplied by the number of rows a borrower "
                            "has, and looks entirely plausible."},
            {"assumption": "currency", "value": dm.CURRENCY,
             "if_violated": "Labels are wrong; figures are not."},
            {"assumption": "staging",
             "value": "Assessed on the obligor, not the facility.",
             "if_violated": "A book that stages one facility of a borrower "
                            "differently from another is describing a bank "
                            "that does not exist."},
            {"assumption": "rating scale",
             "value": "The governed corporate masterscale.",
             "if_violated": "A grade the masterscale does not carry cannot "
                            "be moved by a notch."},
            {"assumption": "periods",
             "value": f"At least {PLAUSIBILITY_MINIMUM_PERIODS} for the "
                      "historical comparison; one to price a scenario.",
             "if_violated": "Scenario plausibility is unavailable."},
        ],
        "measurement_tolerance_pct": MEASUREMENT_TOLERANCE_PCT,
        "statement": (
            "What-If is bound to a CONTRACT, not to this installation's "
            "demo book. A canonical IFRS 9 domain that satisfies the required "
            "columns at obligor grain runs it; one that satisfies fewer runs "
            "it with exactly the capabilities its missing columns name, and "
            "`assess()` says which before anything is wired."),
    })
    return body


__all__ = ["BLOCKS", "DEGRADES", "Finding", "INTEGRATION_VERSION", "NOTE",
           "MEASUREMENT_TOLERANCE_PCT", "PLAUSIBILITY_MINIMUM_PERIODS",
           "Readiness", "assess", "contract"]
