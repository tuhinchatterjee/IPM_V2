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

So this module is a thin, explicit layer over the governed policy:

  * every rule says whether its basis is GOVERNED or a WHAT-IF ASSUMPTION;
  * the default set reproduces `policy.stage_of` EXACTLY, so a thread that
    changes nothing gets the reported book back;
  * a thread may enable, disable, re-threshold or add rules, and the resulting
    rule set carries a version fingerprint that is persisted with the saved
    What-If and stamped into the trace.

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

#: How the enabled rules combine. ANY is the governed reading — a borrower
#: trips Stage 2 if any trigger fires.
ANY = "ANY"
ALL = "ALL"
COMBINATIONS: tuple[str, ...] = (ANY, ALL)


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


def _defaults() -> tuple[Rule, ...]:
    """The governed three, plus the two What-If assumptions, switched off.

    The governed rules are enabled and carry the policy's own thresholds, so an
    unmodified policy reproduces `policy.stage_of` exactly. The assumptions are
    present but OFF: a rating downgrade is not a SICR trigger in this policy,
    and turning it on is a decision somebody has to make and be seen to make.
    """
    return (
        Rule(RELATIVE_PD, "Relative PD increase", RELATIVE_PD,
             policy.SICR_PD_RATIO, policy.SICR_PD_ABSOLUTE,
             enabled=True, governed=True),
        Rule(ABSOLUTE_PD, "Absolute PD level", ABSOLUTE_PD,
             policy.SICR_ABSOLUTE_PD, 0.0, enabled=True, governed=True),
        Rule(DAYS_PAST_DUE, "Days past due", DAYS_PAST_DUE,
             policy.SICR_DPD_DAYS, 0.0, enabled=True, governed=True),
        Rule(RATING_NOTCHES, "Rating deterioration", RATING_NOTCHES,
             2.0, 0.0, enabled=False, governed=False,
             note="Rule A. Off by default: a notch is not a governed SICR "
                  "trigger in this policy."),
        Rule(SCENARIO_PD_RATIO, "PD against the pre-scenario level",
             SCENARIO_PD_RATIO, 2.0, 0.0, enabled=False, governed=False,
             note="Rule B. Compares the scenario PD against the borrower's own "
                  "pre-scenario PD rather than against origination."),
    )


@dataclass(frozen=True)
class StagingPolicy:
    """The staging criteria one thread runs on."""

    rules: tuple[Rule, ...] = field(default_factory=_defaults)
    combination: str = ANY
    #: Free text a person may attach when they change the criteria.
    note: str = ""

    # ------------------------------------------------------------ identity

    @property
    def is_default(self) -> bool:
        return (self.rules == _defaults()) and self.combination == ANY

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
        return f"{STAGING_VERSION}+{'default' if self.is_default else self.fingerprint}"

    def rule(self, key: str) -> Rule | None:
        for found in self.rules:
            if found.key == key:
                return found
        return None

    @property
    def enabled(self) -> tuple[Rule, ...]:
        return tuple(r for r in self.rules if r.enabled)

    # ------------------------------------------------------------ editing

    def with_rule(self, key: str, **changes: Any) -> StagingPolicy:
        """A copy with one rule changed. Unknown keys are refused, not ignored."""
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
        if rule.kind not in KINDS:
            raise StagingError(
                f"'{rule.kind}' is not a staging rule this engine can apply. "
                f"The kinds are: {', '.join(KINDS)}.")
        if self.rule(rule.key) is not None:
            raise StagingError(f"A staging rule called '{rule.key}' already exists.")
        return replace(self, rules=(*self.rules, replace(rule, governed=False)))

    def removed(self, key: str) -> StagingPolicy:
        found = self.rule(key)
        if found is None:
            raise StagingError(f"There is no staging rule called '{key}'.")
        if found.governed:
            raise StagingError(
                f"'{key}' is a governed rule. It can be disabled, which is "
                "recorded, but not removed — the reported book was staged on it.")
        return replace(self, rules=tuple(r for r in self.rules if r.key != key))

    def combined(self, how: str) -> StagingPolicy:
        said = str(how or "").strip().upper()
        if said not in COMBINATIONS:
            raise StagingError(
                f"Staging rules combine with {' or '.join(COMBINATIONS)}, not '{how}'.")
        return replace(self, combination=said)

    def reset(self) -> StagingPolicy:
        return StagingPolicy()

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
        current = pd.to_numeric(frame.get(pd_column), errors="coerce").fillna(0.0) \
            if pd_column in frame.columns else pd.Series(np.zeros(rows))
        out: dict[str, np.ndarray] = {}
        for rule in self.enabled:
            if rule.kind == RELATIVE_PD and origination_column in frame.columns:
                origination = pd.to_numeric(frame[origination_column], errors="coerce")
                ratio = current / origination.replace(0, np.nan)
                absolute = current - origination
                out[rule.key] = ((ratio >= rule.threshold)
                                 & (absolute >= rule.floor)).fillna(False).to_numpy()
            elif rule.kind == ABSOLUTE_PD:
                out[rule.key] = (current >= rule.threshold).to_numpy()
            elif rule.kind == DAYS_PAST_DUE and dpd_column in frame.columns:
                dpd = pd.to_numeric(frame[dpd_column], errors="coerce").fillna(0.0)
                out[rule.key] = (dpd >= rule.threshold).to_numpy()
            elif rule.kind == RATING_NOTCHES and notches_column in frame.columns:
                notches = pd.to_numeric(frame[notches_column], errors="coerce").fillna(0.0)
                out[rule.key] = (notches >= rule.threshold).to_numpy()
            elif rule.kind == SCENARIO_PD_RATIO and baseline_pd_column in frame.columns:
                base = pd.to_numeric(frame[baseline_pd_column], errors="coerce")
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
        return np.where(defaulted | late, 3, np.where(deemed, 2, 1))

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
                "rules": [r.to_dict() for r in self.rules]}

    def describe(self) -> dict[str, Any]:
        """The criteria as a screen shows them."""
        body = self.to_dict()
        body["version"] = self.version
        body["fingerprint"] = self.fingerprint
        body["is_default"] = self.is_default
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
                       note=str(body.get("note") or ""))
        return cls(rules=tuple(rules),
                   combination=str(body.get("combination") or ANY),
                   note=str(body.get("note") or ""))


def default() -> StagingPolicy:
    """The governed criteria, which reproduce the reported book."""
    return StagingPolicy()


__all__ = [
    "ABSOLUTE_PD", "ALL", "ANY", "BASIS_ASSUMPTION", "BASIS_GOVERNED",
    "COMBINATIONS", "DAYS_PAST_DUE", "KINDS", "RATING_NOTCHES", "RELATIVE_PD",
    "Rule", "SCENARIO_PD_RATIO", "STAGING_OWNER", "STAGING_VERSION",
    "StagingError", "StagingPolicy", "default",
]
