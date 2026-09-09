"""
The staging criteria a What-If thread runs on, and who is allowed to change them.

Why this module exists
----------------------
`backend.ifrs9.policy` holds the GOVERNED corporate staging policy: the three
IFRS 9 SICR triggers, the default presumption, and the measurement basis. That
policy is not a What-If setting. It is what produced the reported book, and the
base column of every scenario answer ties to it.

But a What-If conversation genuinely needs to ask "what if we staged this
differently?" — a credit officer wants to know how many names move if a
two-notch downgrade is treated as a SICR event, or if a doubling against the
pre-shock PD counts rather than against origination. Those are ASSUMPTIONS a
person is making, not requirements the standard imposes, and the difference has
to survive into the answer or the answer is misleading.

So this module holds TWO rule sets, and keeping them apart is the whole
design:

  * `reported()` — the rule set that produced the REPORTED BOOK. The governed
    three triggers, at the policy's own thresholds. It reproduces
    `policy.stage_of` exactly, and `test_the_reported_rule_set_is_the_governed
    _policy` proves it borrower by borrower on the real book. Nothing a thread
    does can change it, because the base column of every scenario answer ties
    to the accounts through it.

  * `default()` — the default rule set a WHAT-IF SCENARIO is staged on. The
    same governed three, PLUS the two scenario rules the product requires:
    Rule A, a rating deterioration of two notches or more; and Rule B, a
    scenario PD at or above twice the borrower's own pre-scenario level. Both
    are enabled, because a simulation that cannot recognise a two-notch
    downgrade as a significant increase in credit risk is not simulating the
    question anyone asked.

The two never meet. The baseline side of a comparison is staged by
`reported()`; the scenario side by the thread's own rule set, which starts as
`default()`. So enabling Rule A moves names in the SCENARIO and cannot move a
single name in the reported book — and every result says which rule set
produced which column.

Beyond that:

  * every rule says whether its basis is GOVERNED or a WHAT-IF ASSUMPTION;
  * a thread may enable, disable, re-threshold, add or remove rules and choose
    how they combine, and the resulting rule set carries a version fingerprint
    that is persisted with the saved What-If and stamped into the trace.

What this module will not do
----------------------------
It will not let a rule CURE a stage. Stage 3 is a fact about the borrower, and
a scenario that argues a defaulted name back into Stage 1 is not a scenario. It
will not manufacture a default either: no rule produces Stage 3. Both of those
are enforced here rather than left to the caller to remember.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
import pandas as pd

from backend.ifrs9 import policy

STAGING_OWNER = "Credit Risk Analytics"
STAGING_VERSION = "1.0.0"

#: The rule came from the governed policy that produced the reported book.
BASIS_GOVERNED = ("Governed corporate IFRS 9 policy. This is what staged the "
                  "reported book; changing it changes the comparison, not just "
                  "the scenario.")
#: The rule is a What-If assumption somebody chose. Never described as an IFRS 9
#: requirement, because it is not one.
BASIS_ASSUMPTION = ("A CreditProbe What-If assumption, set by the person asking "
                    "the question. Not a requirement of IFRS 9.")

# ------------------------------------------------------------------- kinds

RELATIVE_PD = "relative_pd"
ABSOLUTE_PD = "absolute_pd"
DAYS_PAST_DUE = "days_past_due"
RATING_NOTCHES = "rating_notches"
SCENARIO_PD_RATIO = "scenario_pd_ratio"

KINDS: tuple[str, ...] = (RELATIVE_PD, ABSOLUTE_PD, DAYS_PAST_DUE,
                          RATING_NOTCHES, SCENARIO_PD_RATIO)

#: What each kind of rule is, for a screen that offers to ADD one. A person
#: composing a rule has to know what the number they type means and what the
#: book needs to carry for it to be answerable, so both are stated here rather
#: than left to a tooltip.
KIND_CATALOGUE: tuple[dict[str, Any], ...] = (
    {"kind": RELATIVE_PD, "label": "Relative PD increase",
     "threshold_means": "multiple of the PD at origination",
     "threshold_unit": "x", "has_floor": True,
     "floor_means": "and at least this many percentage points higher",
     "needs": "pd_at_origination_pct"},
    {"kind": ABSOLUTE_PD, "label": "Absolute PD level",
     "threshold_means": "12-month PD at or above this level",
     "threshold_unit": "%", "has_floor": False, "floor_means": "",
     "needs": "pd_12m"},
    {"kind": DAYS_PAST_DUE, "label": "Days past due",
     "threshold_means": "days past due at or above this many",
     "threshold_unit": "days", "has_floor": False, "floor_means": "",
     "needs": "current_dpd"},
    {"kind": RATING_NOTCHES, "label": "Rating deterioration",
     "threshold_means": "notches of deterioration under the scenario",
     "threshold_unit": "notches", "has_floor": False, "floor_means": "",
     "needs": "the scenario to move a rating"},
    {"kind": SCENARIO_PD_RATIO, "label": "PD against the pre-scenario level",
     "threshold_means": "multiple of the borrower's own pre-scenario PD",
     "threshold_unit": "x", "has_floor": False, "floor_means": "",
     "needs": "pd_12m"},
)

#: How the enabled rules combine. ANY is the governed reading — a borrower
#: trips Stage 2 if any trigger fires.
ANY = "ANY"
ALL = "ALL"
COMBINATIONS: tuple[str, ...] = (ANY, ALL)

# ------------------------------------------------------------------ scopes

#: The rule set that staged the reported book. Fixed, and not a What-If
#: setting: the base column of every scenario answer ties to the accounts
#: through it.
SCOPE_REPORTED = "reported_book"
#: The rule set a What-If SCENARIO is staged on. Starts from the governed three
#: plus Rule A and Rule B, and a thread may change it.
SCOPE_WHATIF = "what_if"
SCOPES: tuple[str, ...] = (SCOPE_REPORTED, SCOPE_WHATIF)

SCOPE_LABEL = {
    SCOPE_REPORTED: "Reported-book staging policy",
    SCOPE_WHATIF: "What-If staging policy",
}
SCOPE_NOTE = {
    SCOPE_REPORTED: (
        "The governed corporate IFRS 9 policy that staged the reported book. "
        "It is shown so the comparison is legible; it is not editable, and no "
        "What-If rule can move a borrower in it."),
    SCOPE_WHATIF: (
        "The rules the SCENARIO is staged on. It starts from the governed "
        "three plus the two What-If scenario rules, and this thread may change "
        "it. Changing it changes the scenario column only."),
}


def _column(frame: pd.DataFrame, name: str) -> pd.Series:
    """One numeric column, even where the caller handed us a duplicated name.

    A frame carrying two columns of the same name returns a DataFrame from
    `frame[name]`, and every rule downstream would then compare a table
    against a threshold. Taking the first is arbitrary, so this refuses to
    guess and takes the LAST — the one an assignment would have written.
    """
    if name not in frame.columns:
        return pd.Series(np.zeros(len(frame)), index=frame.index)
    found = frame[name]
    if isinstance(found, pd.DataFrame):
        found = found.iloc[:, -1]
    return pd.to_numeric(found, errors="coerce").fillna(0.0)


class StagingError(ValueError):
    """A staging rule that cannot be applied, stated rather than ignored."""


@dataclass(frozen=True)
class Rule:
    """One staging trigger, with its threshold and where it came from."""

    key: str
    name: str
    kind: str
    threshold: float
    #: The second threshold, where a rule has one. The governed relative-PD
    #: test needs both a ratio AND an absolute floor; everything else uses 0.0.
    floor: float = 0.0
    enabled: bool = True
    governed: bool = True
    note: str = ""

    @property
    def basis(self) -> str:
        return BASIS_GOVERNED if self.governed else BASIS_ASSUMPTION

    def describe(self) -> str:
        if self.kind == RELATIVE_PD:
            return (f"12-month PD at least {self.threshold:g}x its level at "
                    f"origination AND at least {self.floor:.2f} percentage "
                    "points higher")
        if self.kind == ABSOLUTE_PD:
            return f"12-month PD at or above {self.threshold:g}%"
        if self.kind == DAYS_PAST_DUE:
            return f"{self.threshold:g} or more days past due"
        if self.kind == RATING_NOTCHES:
            return (f"rating deteriorates by {self.threshold:g} or more "
                    "notches under the scenario")
        if self.kind == SCENARIO_PD_RATIO:
            return (f"scenario 12-month PD at least {self.threshold:g}x the "
                    "borrower's pre-scenario PD")
        return self.kind

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "name": self.name, "kind": self.kind,
                "threshold": self.threshold, "floor": self.floor,
                "enabled": self.enabled, "governed": self.governed,
                "basis": self.basis, "rule": self.describe(),
                "note": self.note}


#: Rule A and Rule B, in the product's own numbering. Named here because both
#: rule sets refer to them and the numbering is what the requirement uses.
RULE_A = RATING_NOTCHES
RULE_B = SCENARIO_PD_RATIO


def _governed() -> tuple[Rule, ...]:
    """The three triggers of the governed corporate policy, at its thresholds."""
    return (
        Rule(RELATIVE_PD, "Relative PD increase", RELATIVE_PD,
             policy.SICR_PD_RATIO, policy.SICR_PD_ABSOLUTE,
             enabled=True, governed=True),
        Rule(ABSOLUTE_PD, "Absolute PD level", ABSOLUTE_PD,
             policy.SICR_ABSOLUTE_PD, 0.0, enabled=True, governed=True),
        Rule(DAYS_PAST_DUE, "Days past due", DAYS_PAST_DUE,
             policy.SICR_DPD_DAYS, 0.0, enabled=True, governed=True),
    )


def _scenario_rules(*, enabled: bool) -> tuple[Rule, ...]:
    """Rule A and Rule B, as the requirement states them.

    A: a rating deterioration of two notches or more is a significant increase
       in credit risk, so Stage 1 becomes Stage 2.
    B: a scenario 12-month PD at or above twice the borrower's own pre-scenario
       PD is a significant increase in credit risk, so Stage 1 becomes Stage 2.

    Neither is a requirement of IFRS 9 and both say so. They are the
    assumptions a scenario is run under, which is a different thing from the
    policy that measured the book.
    """
    return (
        Rule(RATING_NOTCHES, "Rating deterioration (Rule A)", RATING_NOTCHES,
             2.0, 0.0, enabled=enabled, governed=False,
             note="Rule A. A downgrade of this many notches or more under the "
                  "scenario is treated as a significant increase in credit "
                  "risk. On in the What-If rule set; never part of the policy "
                  "that staged the reported book."),
        Rule(SCENARIO_PD_RATIO, "PD against the pre-scenario level (Rule B)",
             SCENARIO_PD_RATIO, 2.0, 0.0, enabled=enabled, governed=False,
             note="Rule B. Compares the scenario PD against the borrower's own "
                  "PRE-SCENARIO PD rather than against origination, which is "
                  "the comparison a scenario is actually about. On in the "
                  "What-If rule set; never part of the policy that staged the "
                  "reported book."),
    )


def _reported_rules() -> tuple[Rule, ...]:
    """What staged the reported book: the governed three, and nothing else.

    Rule A and Rule B are carried here too, switched OFF and not switchable,
    so a reader comparing the two rule sets on screen sees the same five rows
    and can tell at a glance which two are the difference.
    """
    return (*_governed(), *_scenario_rules(enabled=False))


def _whatif_rules() -> tuple[Rule, ...]:
    """What a What-If scenario is staged on: the governed three, plus A and B."""
    return (*_governed(), *_scenario_rules(enabled=True))


def _defaults() -> tuple[Rule, ...]:
    """The default rule set for a What-If thread."""
    return _whatif_rules()


@dataclass(frozen=True)
class StagingPolicy:
    """The staging criteria one thread runs on."""

    rules: tuple[Rule, ...] = field(default_factory=_defaults)
    combination: str = ANY
    #: Free text a person may attach when they change the criteria.
    note: str = ""
    #: Which of the two rule sets this is. A reported-book policy is a fact
    #: about the accounts; a What-If policy is an assumption about a scenario.
    scope: str = SCOPE_WHATIF

    # ------------------------------------------------------------ identity

    @property
    def label(self) -> str:
        return SCOPE_LABEL.get(self.scope, SCOPE_LABEL[SCOPE_WHATIF])

    @property
    def editable(self) -> bool:
        """The reported-book rule set is shown, never edited."""
        return self.scope != SCOPE_REPORTED

    @property
    def is_default(self) -> bool:
        expected = (_reported_rules() if self.scope == SCOPE_REPORTED
                    else _whatif_rules())
        return self.rules == expected and self.combination == ANY

    @property
    def fingerprint(self) -> str:
        """A stable hash of the criteria, stamped into the trace and the save.

        Content-addressed rather than a counter, so two threads that chose the
        same criteria are recognisably running the same rules.
        """
        body = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(body.encode()).hexdigest()[:16]

    @property
    def version(self) -> str:
        """The version stamped on a result.

        A default set names itself rather than hashing, because "what-if
        default" is what a reader needs to see; anything edited carries the
        fingerprint of exactly what it was edited to.
        """
        if not self.is_default:
            return f"{STAGING_VERSION}+{self.fingerprint}"
        named = "reported-book" if self.scope == SCOPE_REPORTED else "what-if-default"
        return f"{STAGING_VERSION}+{named}"

    def rule(self, key: str) -> Rule | None:
        for found in self.rules:
            if found.key == key:
                return found
        return None

    @property
    def enabled(self) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.enabled)

    # ------------------------------------------------------------ editing

    def _may_edit(self) -> None:
        if not self.editable:
            raise StagingError(
                "The reported-book staging policy cannot be edited. It is what "
                "staged the accounts, and the base column of every What-If "
                "ties to it. Change the What-If staging policy instead.")

    def with_rule(self, key: str, **changes: Any) -> StagingPolicy:
        """A copy with one rule changed. Unknown keys are refused, not ignored."""
        self._may_edit()
        found = self.rule(key)
        if found is None:
            raise StagingError(
                f"There is no staging rule called '{key}'. The rules are: "
                + ", ".join(r.key for r in self.rules))
        allowed = {"threshold", "floor", "enabled", "name", "note"}
        unknown = set(changes) - allowed
        if unknown:
            raise StagingError(
                f"A staging rule has no {', '.join(sorted(unknown))} to set.")
        if "threshold" in changes:
            value = float(changes["threshold"])
            if value < 0:
                raise StagingError("A staging threshold cannot be negative.")
            changes["threshold"] = value
        if "floor" in changes:
            changes["floor"] = float(changes["floor"])
        return replace(self, rules=tuple(
            replace(r, **changes) if r.key == key else r for r in self.rules))

    def added(self, rule: Rule) -> StagingPolicy:
        """A copy with one more rule. A rule the caller added is never governed."""
        self._may_edit()
        if rule.kind not in KINDS:
            raise StagingError(
                f"'{rule.kind}' is not a staging rule this engine can apply. "
                f"The kinds are: {', '.join(KINDS)}.")
        if self.rule(rule.key) is not None:
            raise StagingError(f"A staging rule called '{rule.key}' already exists.")
        return replace(self, rules=(*self.rules, replace(rule, governed=False)))

    def removed(self, key: str) -> StagingPolicy:
        self._may_edit()
        found = self.rule(key)
        if found is None:
            raise StagingError(f"There is no staging rule called '{key}'.")
        if found.governed:
            raise StagingError(
                f"'{key}' is a governed rule. It can be disabled, which is "
                "recorded, but not removed — the reported book was staged on it.")
        return replace(self, rules=tuple(r for r in self.rules if r.key != key))

    def combined(self, how: str) -> StagingPolicy:
        self._may_edit()
        said = str(how or "").strip().upper()
        if said not in COMBINATIONS:
            raise StagingError(
                f"Staging rules combine with {' or '.join(COMBINATIONS)}, not '{how}'.")
        return replace(self, combination=said)

    def reset(self) -> StagingPolicy:
        """Back to the default set for this scope."""
        return (reported() if self.scope == SCOPE_REPORTED else StagingPolicy())

    # ------------------------------------------------------------ applying

    def fired(self, frame: pd.DataFrame, *,
              pd_column: str = "pd_12m",
              origination_column: str = "pd_at_origination_pct",
              dpd_column: str = "current_dpd",
              notches_column: str = "notches_moved",
              baseline_pd_column: str = "pd_12m_baseline") -> dict[str, np.ndarray]:
        """Which rules fired, per borrower, as one boolean array per rule.

        Every enabled rule appears in the result even when the column it needs
        is absent — as all-False, with the absence reported by `unread()` — so a
        caller can never mistake "the data could not answer this" for "the rule
        did not fire".
        """
        rows = len(frame)
        current = _column(frame, pd_column)
        out: dict[str, np.ndarray] = {}
        for rule in self.enabled:
            if rule.kind == RELATIVE_PD and origination_column in frame.columns:
                origination = _column(frame, origination_column)
                ratio = current / origination.replace(0, np.nan)
                absolute = current - origination
                out[rule.key] = ((ratio >= rule.threshold)
                                 & (absolute >= rule.floor)).fillna(False).to_numpy()
            elif rule.kind == ABSOLUTE_PD:
                out[rule.key] = (current >= rule.threshold).to_numpy()
            elif rule.kind == DAYS_PAST_DUE and dpd_column in frame.columns:
                dpd = _column(frame, dpd_column)
                out[rule.key] = (dpd >= rule.threshold).to_numpy()
            elif rule.kind == RATING_NOTCHES and notches_column in frame.columns:
                notches = _column(frame, notches_column)
                out[rule.key] = (notches >= rule.threshold).to_numpy()
            elif rule.kind == SCENARIO_PD_RATIO and baseline_pd_column in frame.columns:
                base = _column(frame, baseline_pd_column)
                ratio = current / base.replace(0, np.nan)
                out[rule.key] = (ratio >= rule.threshold).fillna(False).to_numpy()
            else:
                out[rule.key] = np.zeros(rows, dtype=bool)
        return out

    def unread(self, frame: pd.DataFrame) -> list[str]:
        """Enabled rules the data cannot answer. Reported, never silently skipped."""
        needs = {RELATIVE_PD: "pd_at_origination_pct",
                 DAYS_PAST_DUE: "current_dpd",
                 RATING_NOTCHES: "notches_moved",
                 SCENARIO_PD_RATIO: "pd_12m_baseline"}
        missing = []
        for rule in self.enabled:
            column = needs.get(rule.kind)
            if column and column not in frame.columns:
                missing.append(
                    f"'{rule.name}' could not be evaluated: the book does not "
                    f"carry {column}.")
        return missing

    def sicr(self, frame: pd.DataFrame, **columns: str) -> np.ndarray:
        """Whether a SICR is deemed to have occurred, per borrower."""
        fired = self.fired(frame, **columns)
        if not fired:
            return np.zeros(len(frame), dtype=bool)
        stack = np.vstack(list(fired.values()))
        return stack.any(axis=0) if self.combination == ANY else stack.all(axis=0)

    def stage(self, frame: pd.DataFrame, *,
              default_flag_column: str = "default_flag",
              dpd_column: str = "current_dpd",
              **columns: str) -> np.ndarray:
        """The Stage these criteria produce.

        Stage 3 is never produced by a staging RULE. It is the default
        presumption — a recorded default, or the governed days-past-due
        threshold — and no scenario assumption reaches it. A scenario does not
        cure a default and does not create one.
        """
        rows = len(frame)
        defaulted = (pd.to_numeric(frame.get(default_flag_column), errors="coerce")
                     .fillna(0) > 0).to_numpy() if default_flag_column in frame.columns \
            else np.zeros(rows, dtype=bool)
        late = (pd.to_numeric(frame.get(dpd_column), errors="coerce").fillna(0)
                >= policy.DEFAULT_DPD_DAYS).to_numpy() \
            if dpd_column in frame.columns else np.zeros(rows, dtype=bool)
        deemed = self.sicr(frame, dpd_column=dpd_column, **columns)
        measured = np.where(defaulted | late, 3, np.where(deemed, 2, 1))
        return (self._carried(frame, measured)
                if self.scope == SCOPE_REPORTED else measured)

    def _carried(self, frame: pd.DataFrame,
                 measured: np.ndarray) -> np.ndarray:
        """The reported book's stage, which has a memory.

        A borrower whose trigger stops firing does not return to Stage 1 the
        same quarter — it serves a probation first, which is the curing rule an
        IFRS 9 book operates and the reason its Stage 2 population does not
        oscillate on a PD that moved by a hundredth.

        That makes the stage a function of history, so a single quarter's row
        can only be staged if it CARRIES that history. The book stores it: the
        stage it was carrying last quarter, and how many consecutive quarters
        it has been clear. Where a frame does not carry them — a hypothetical,
        a hand-built row, an older extract — the measured stage is returned and
        the rule set says as much rather than inventing a history.
        """
        if not {"prior_stage", "sicr_clear_quarters"} <= set(frame.columns):
            return measured
        prior = (pd.to_numeric(frame["prior_stage"], errors="coerce")
                 .fillna(pd.Series(measured, index=frame.index)).to_numpy())
        served = (pd.to_numeric(frame["sicr_clear_quarters"], errors="coerce")
                  .fillna(0).to_numpy())
        # Deterioration lands at once; an improvement waits for its probation.
        improving = measured < prior
        return np.where(improving & (served < policy.STAGE_2_PROBATION_QUARTERS),
                        prior, measured).astype(int)

    def reasons(self, frame: pd.DataFrame, index: int, **columns: str) -> tuple[str, ...]:
        """Why one borrower is where it is, in a reader's words."""
        fired = self.fired(frame, **columns)
        return tuple(rule.describe() for rule in self.enabled
                     if fired.get(rule.key) is not None and bool(fired[rule.key][index]))

    # ------------------------------------------------------------ carrying

    def to_dict(self) -> dict[str, Any]:
        return {"owner": STAGING_OWNER,
                "policy_version": STAGING_VERSION,
                "combination": self.combination,
                "note": self.note,
                "scope": self.scope,
                "rules": [r.to_dict() for r in self.rules]}

    def describe(self) -> dict[str, Any]:
        """The criteria as a screen shows them."""
        body = self.to_dict()
        body["version"] = self.version
        body["fingerprint"] = self.fingerprint
        body["is_default"] = self.is_default
        body["label"] = self.label
        body["scope_note"] = SCOPE_NOTE.get(self.scope, "")
        body["editable"] = self.editable
        body["combination_note"] = (
            "A borrower trips Stage 2 if ANY enabled rule fires."
            if self.combination == ANY else
            "A borrower trips Stage 2 only if EVERY enabled rule fires.")
        body["default_presumption"] = (
            f"Stage 3 where a default is recorded, or at "
            f"{policy.DEFAULT_DPD_DAYS}+ days past due. No What-If rule "
            "produces or cures Stage 3.")
        body["measurement"] = {
            "Stage 1": "12-month expected credit loss",
            "Stage 2": "Lifetime expected credit loss",
            "Stage 3": "Lifetime expected credit loss"}
        return body

    @classmethod
    def from_dict(cls, body: dict[str, Any] | None) -> StagingPolicy:
        """Rebuild saved criteria. An unreadable body returns the default set."""
        scope = str((body or {}).get("scope") or SCOPE_WHATIF)
        if scope not in SCOPES:
            scope = SCOPE_WHATIF
        if not body:
            return cls()
        rules = []
        for raw in body.get("rules") or []:
            try:
                rules.append(Rule(
                    key=str(raw["key"]), name=str(raw.get("name") or raw["key"]),
                    kind=str(raw["kind"]), threshold=float(raw.get("threshold") or 0.0),
                    floor=float(raw.get("floor") or 0.0),
                    enabled=bool(raw.get("enabled", True)),
                    governed=bool(raw.get("governed", False)),
                    note=str(raw.get("note") or "")))
            except (KeyError, TypeError, ValueError) as e:
                raise StagingError(f"A saved staging rule could not be read: {e}") from e
        if not rules:
            return cls(combination=str(body.get("combination") or ANY),
                       note=str(body.get("note") or ""), scope=scope)
        return cls(rules=tuple(rules),
                   combination=str(body.get("combination") or ANY),
                   note=str(body.get("note") or ""), scope=scope)


def reported() -> StagingPolicy:
    """The rule set that staged the REPORTED BOOK.

    The governed three, at the policy's own thresholds, combined with ANY.
    `test_the_reported_rule_set_is_the_governed_policy` asserts this produces
    `policy.stage_of` borrower for borrower on the real book, which is what
    makes it a second reading of one source of truth rather than a second
    source of truth.
    """
    return StagingPolicy(rules=_reported_rules(), scope=SCOPE_REPORTED)


def default() -> StagingPolicy:
    """The default rule set a What-If SCENARIO is staged on.

    The governed three PLUS Rule A (a two-notch deterioration) and Rule B (a
    scenario PD at twice the pre-scenario level). Both are on: the product's
    requirement is that a What-If recognises them, and a simulation that
    cannot see a two-notch downgrade is not answering the question.

    This does not change the reported book. The baseline column of every
    comparison is staged by `reported()`.
    """
    return StagingPolicy()


__all__ = [
    "ABSOLUTE_PD", "ALL", "ANY", "BASIS_ASSUMPTION", "BASIS_GOVERNED",
    "COMBINATIONS", "DAYS_PAST_DUE", "KINDS", "RATING_NOTCHES", "RELATIVE_PD",
    "KIND_CATALOGUE", "RULE_A", "RULE_B", "Rule", "SCENARIO_PD_RATIO", "SCOPES", "SCOPE_LABEL",
    "SCOPE_NOTE", "SCOPE_REPORTED", "SCOPE_WHATIF", "STAGING_OWNER",
    "STAGING_VERSION", "StagingError", "StagingPolicy", "default", "reported",
]
