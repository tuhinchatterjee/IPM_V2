"""
Why this borrower is High Risk — and why counting signals cannot answer it.

The defect
----------
Overall risk was the number of signals firing. That is a fact about the RULE
BOOK, not about the borrower. A name with six stale-valuation and
old-statements observations outranked one in covenant breach, thirty days past
due and downgraded two notches, because six is more than three.

What a credit committee actually weighs
---------------------------------------
Eight things, each of which either holds or does not:

*   **severity** — how bad the worst individual condition is;
*   **persistence** — whether it has been true for more than one quarter;
*   **materiality** — how much money is behind it;
*   **trajectory** — worsening, holding or coming back;
*   **breadth** — how many INDEPENDENT risk families agree, which is different
    from how many signals fired: four liquidity signals are one observation
    told four ways;
*   **credit events** — an arrears, a breach, a downgrade, a restructuring.
    Something HAPPENED, and that outranks any measure crossing a line;
*   **credit-quality relevance** — whether the IFRS 9 and rating evidence has
    moved with it;
*   **external corroboration** — whether somebody outside the bank agrees.

and one that pushes the other way:

*   **mitigating evidence** — collateral cover, improving trajectory, a
    resolved warning. A framework that can only ever escalate is a framework
    nobody argues with, and therefore one nobody trusts.

There is no score. Each rule produces a SENTENCE, and a reader who disagrees
with the level can see which rule put it there and argue with that rule.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from backend.early_warning import classifiers as cls
from backend.early_warning import signals as sg
from backend.early_warning import taxonomy as tx

ASSESSMENT_VERSION = "1.0.0"
ASSESSMENT_OWNER = tx.THRESHOLD_OWNER

HIGH = "HIGH"
MEDIUM = "MEDIUM"
LOW = "LOW"
LEVELS: tuple[str, ...] = (HIGH, MEDIUM, LOW)
LEVEL_RANK: dict[str, int] = {HIGH: 3, MEDIUM: 2, LOW: 1}

LEVEL_MEANS: dict[str, str] = {
    HIGH: ("Evidence from more than one part of the credit picture, and "
           "either a credit event or a severe condition that has persisted."),
    MEDIUM: ("Something real is moving, but it is either confined to one part "
             "of the picture or has not persisted."),
    LOW: ("Nothing beyond routine observations, or what fired has since come "
          "back."),
}

#: Section 11H. What the BORROWER is doing, not what the rule did.
HEALTHY = "Healthy"
WATCH_STATE = "Watch"
NEW_WARNING = "New warning"
WORSENING_WARNING = "Worsening warning"
PERSISTENT_WARNING = "Persistent warning"
HIGH_CONCERN = "High concern"
IMPROVING_STATE = "Improving"
RESOLVED = "Resolved"

STATES: tuple[str, ...] = (HEALTHY, WATCH_STATE, NEW_WARNING,
                           WORSENING_WARNING, PERSISTENT_WARNING,
                           HIGH_CONCERN, IMPROVING_STATE, RESOLVED)

STATE_MEANS: dict[str, str] = {
    HEALTHY: "Within every governed threshold in the current observation period.",
    WATCH_STATE: ("Close to a threshold in the current observation period "
                  "without crossing it."),
    NEW_WARNING: ("Crossed its threshold this observation period, having been "
                  "within it in the previous one."),
    WORSENING_WARNING: ("Beyond its threshold in both the current and previous "
                        "observation periods, and further beyond than it was."),
    PERSISTENT_WARNING: ("Beyond its threshold in both the current and the "
                         "previous observation period."),
    HIGH_CONCERN: ("A severe condition, or a credit event, in the current "
                   "observation period."),
    IMPROVING_STATE: ("Still beyond its threshold, but moving back towards it "
                      "since the previous observation period."),
    RESOLVED: ("Beyond its threshold in the previous observation period and "
               "within it in the current one."),
}

#: Signals that record something HAPPENING rather than a level being crossed.
#: Derived from the taxonomy's own TAC classification, so a signal cannot be
#: treated as an event here and as a threshold there.
CREDIT_EVENTS: frozenset[str] = frozenset(
    s.key for s in tx.SIGNALS if s.tac == tx.ACTION_BASED)

#: And the subset of those that a credit committee would call SERIOUS: the
#: severe ones. Derived, not listed, so a threshold owner who reclassifies a
#: signal's severity moves it here without anybody remembering to. Arrears are
#: included by the same test — they are severe, and being past due is a fact
#: about payment rather than a measure approaching a line, whatever detection
#: mechanism records it.
GRAVE_EVENTS: frozenset[str] = frozenset(
    s.key for s in tx.SIGNALS
    if s.severity == tx.SEVERE
    and (s.tac == tx.ACTION_BASED or s.booked_accounting
         or "dpd" in s.field or "past_due" in s.field))

#: The families that carry credit-quality relevance: if these have moved, the
#: bank's own recorded view of the borrower has moved.
CREDIT_QUALITY: frozenset[str] = frozenset({tx.RATING, tx.IFRS9})

#: And the ones that say somebody outside the bank agrees.
EXTERNAL_FAMILIES: frozenset[str] = frozenset({tx.EXTERNAL, tx.NETWORK})

#: Exposure at which a warning stops being a monitoring item, in the reporting
#: currency. Owned by the same function that owns the signal thresholds; not a
#: regulatory figure.
MATERIAL_EXPOSURE = 500.0

#: Independent families that must agree before breadth counts. Two, because
#: one family saying the same thing four ways is one observation.
BREADTH_FAMILIES = 2


@dataclass(frozen=True)
class Reason:
    """One rule that held, and the sentence it produces."""

    rule: str
    says: str
    pushes: str  # HIGH, MEDIUM or LOW

    def to_dict(self) -> dict[str, Any]:
        return {"rule": self.rule, "says": self.says, "pushes": self.pushes}


@dataclass
class Assessment:
    """The borrower's overall Early Warning risk, and why."""

    level: str = LOW
    reasons: list[Reason] = field(default_factory=list)
    mitigating: list[Reason] = field(default_factory=list)
    #: The families that carry firing evidence, so breadth is inspectable.
    families: tuple[str, ...] = ()
    #: The families that corroborate — those carrying evidence OTHER than the
    #: families the gravity itself sits in. Corroboration that counts the
    #: evidence which raised the concern is not corroboration.
    corroborating: tuple[str, ...] = ()
    #: Which patterns matched.
    patterns: list[cls.Match] = field(default_factory=list)
    #: What is new, persistent, worsening and resolved this period.
    new: tuple[str, ...] = ()
    persistent: tuple[str, ...] = ()
    worsening: tuple[str, ...] = ()
    resolved: tuple[str, ...] = ()
    improving: tuple[str, ...] = ()
    #: The TAC split, as counts a reader can check.
    tac_counts: dict[str, int] = field(default_factory=dict)
    primary_concern: str = ""
    why_now: str = ""

    @property
    def means(self) -> str:
        return LEVEL_MEANS[self.level]

    def because(self) -> list[str]:
        return [r.says for r in self.reasons]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level, "means": self.means,
            "reasons": [r.to_dict() for r in self.reasons],
            "mitigating": [r.to_dict() for r in self.mitigating],
            "families": list(self.families),
            "family_labels": [tx.FAMILIES.get(f, f) for f in self.families],
            "corroborating": list(self.corroborating),
            "patterns": [m.to_dict() for m in self.patterns if m.fired],
            "new": list(self.new), "persistent": list(self.persistent),
            "worsening": list(self.worsening), "resolved": list(self.resolved),
            "improving": list(self.improving),
            "tac": dict(self.tac_counts),
            "primary_concern": self.primary_concern,
            "why_now": self.why_now,
            "owner": ASSESSMENT_OWNER, "version": ASSESSMENT_VERSION,
        }


def _exposure(row: dict[str, Any] | None) -> float:
    if not row:
        return 0.0
    for name in ("ead", "drawn_exposure", "total_outstanding", "exposure"):
        try:
            found = float(row.get(name) or 0)
        except (TypeError, ValueError):
            continue
        if found:
            return found
    return 0.0


def state_of(observation: sg.Observation) -> str:
    """Section 11H: what the borrower is doing, in credit language."""
    if not observation.fired:
        return RESOLVED if observation.lifecycle == sg.CURED else HEALTHY
    if observation.severity == tx.SEVERE:
        return HIGH_CONCERN
    if observation.lifecycle == sg.NEW:
        return NEW_WARNING
    if observation.lifecycle == sg.WORSENING:
        return WORSENING_WARNING
    if observation.lifecycle == sg.IMPROVING:
        return IMPROVING_STATE
    if observation.lifecycle == sg.PERSISTING:
        return PERSISTENT_WARNING
    return WATCH_STATE


def assess(standing: Any, row: dict[str, Any] | None = None) -> Assessment:
    """The overall Early Warning risk for one borrower, and why. Section 11G.

    `standing` is a `signals.Standing` — the borrower's whole position at one
    period. `row` is its own record, defaulting to the one the standing was
    read from, because materiality is a fact about the facility rather than
    about any signal.
    """
    fired = [o for o in getattr(standing, "fired", []) if o.fired]
    cured = list(getattr(standing, "cured", []))
    untested = {o.signal for o in getattr(standing, "untested", [])}
    #: Every governed signal this deployment could actually test. A classifier
    #: that needs a field this installation does not carry must say so rather
    #: than quietly not matching.
    tested = {s.key for s in tx.SIGNALS} - untested
    keys = {o.signal for o in fired}
    families = tuple(sorted({o.family for o in fired}))
    if row is None:
        row = getattr(standing, "record", None)
    exposure = _exposure(row)

    found = Assessment(
        families=families,
        new=tuple(o.signal for o in fired if o.lifecycle == sg.NEW),
        persistent=tuple(o.signal for o in fired
                         if o.lifecycle == sg.PERSISTING),
        worsening=tuple(o.signal for o in fired
                        if o.lifecycle == sg.WORSENING),
        improving=tuple(o.signal for o in fired
                        if o.lifecycle == sg.IMPROVING),
        resolved=tuple(o.signal for o in cured if not o.fired),
        patterns=cls.classify(keys, tested),
    )
    found.tac_counts = {
        tx.THRESHOLD_BASED: sum(
            1 for o in fired if o.signal in tx.BY_KEY
            and tx.BY_KEY[o.signal].tac == tx.THRESHOLD_BASED),
        tx.ACTION_BASED: sum(
            1 for o in fired if o.signal in tx.BY_KEY
            and tx.BY_KEY[o.signal].tac == tx.ACTION_BASED),
        tx.CLASSIFIER_BASED: sum(1 for m in found.patterns if m.fired),
    }

    def add(rule: str, says: str, pushes: str) -> None:
        found.reasons.append(Reason(rule=rule, says=says, pushes=pushes))

    def mitigate(rule: str, says: str) -> None:
        found.mitigating.append(Reason(rule=rule, says=says, pushes=LOW))

    #: The rules that establish GRAVITY — that something serious is true — as
    #: opposed to the rules below them, which say the same evidence is visible
    #: in more than one place. The names of the gravity rules that held, and
    #: the families they sit in, so corroboration can be measured against
    #: something OTHER than the evidence that raised the concern.
    gravity_reasons: list[str] = []
    gravity_families: set[str] = set()

    def grave(rule: str, says: str, sources: list[str]) -> None:
        gravity_reasons.append(rule)
        gravity_families.update(sources)
        add(rule, says, HIGH)

    severe = [o for o in fired if o.severity == tx.SEVERE]
    matched = [m for m in found.patterns if m.fired]

    # ---- gravity 1: a severe credit event. Something serious HAPPENED.
    grave_events = [o for o in fired if o.signal in GRAVE_EVENTS]
    if grave_events:
        grave("severe_credit_event",
              "A serious credit event is recorded against this exposure: "
              + ", ".join(sorted(o.label for o in grave_events))
              + ". This is something that happened, not a measure "
                "approaching a line.",
              [o.family for o in grave_events])

    # ---- gravity 2: a severe condition that did not go away
    persisted = [o for o in severe
                 if o.lifecycle in (sg.PERSISTING, sg.WORSENING)]
    if persisted:
        grave("severe_persistent",
              f"{len(persisted)} severe condition"
              f"{'s have' if len(persisted) != 1 else ' has'} now been beyond "
              "threshold in two consecutive observation periods: "
              + ", ".join(sorted(o.label for o in persisted))
              + ". One quarter is a reading; two is a direction.",
              [o.family for o in persisted])

    # ---- gravity 3: a recognised pattern the threshold owner classes severe
    for match in matched:
        if match.classifier.severity == tx.SEVERE:
            grave(f"classifier:{match.classifier.key}", match.why(),
                  [tx.BY_KEY[k].family for k in match.matched
                   if k in tx.BY_KEY])

    # ---- a severe condition that is new and has not yet persisted
    if severe and not persisted and not grave_events:
        add("severe_new",
            f"{len(severe)} severe condition"
            f"{'s' if len(severe) != 1 else ''} fired for the first time this "
            "period: " + ", ".join(sorted(o.label for o in severe))
            + ". Serious, but one observation period is not yet a direction.",
            MEDIUM)

    # ---- other credit events: real, recorded, but not on their own severe
    other_events = [o for o in fired
                    if o.signal in CREDIT_EVENTS
                    and o.signal not in GRAVE_EVENTS]
    if other_events:
        add("credit_event",
            "Recorded against the exposure this period: "
            + ", ".join(sorted(o.label for o in other_events)) + ".", MEDIUM)

    # ---- breadth: INDEPENDENT families, not signal count. Reported as a
    # sentence whatever the level, because a reader asking why a name is only
    # Medium is asking exactly this.
    if len(families) >= BREADTH_FAMILIES:
        add("breadth",
            f"{len(families)} independent parts of the credit picture are "
            "showing warnings at once — "
            + ", ".join(tx.FAMILIES.get(f, f) for f in families)
            + ". One family saying the same thing several ways is one "
              "observation; several families agreeing is a pattern.", MEDIUM)

    # ---- patterns the threshold owner does not class severe
    for match in matched:
        if match.classifier.severity != tx.SEVERE:
            add(f"classifier:{match.classifier.key}", match.why(), MEDIUM)

    # ---- credit-quality relevance
    quality = [o for o in fired if o.family in CREDIT_QUALITY]
    if quality:
        add("credit_quality",
            "The bank's own recorded view has moved with it: "
            + ", ".join(sorted(o.label for o in quality)) + ".", MEDIUM)

    # ---- external corroboration
    external = [o for o in fired if o.family in EXTERNAL_FAMILIES]
    if external:
        add("external_corroboration",
            "Evidence from outside the borrower's own accounts agrees: "
            + ", ".join(sorted(o.label for o in external)) + ".", MEDIUM)

    # ---- materiality. It says who should read this, not how risky it is: a
    # small facility can be in as much trouble as a large one, and a framework
    # that says otherwise is ranking the bank's interest rather than the
    # borrower's condition.
    if exposure >= MATERIAL_EXPOSURE and fired:
        add("materiality",
            f"Exposure of {exposure:,.1f} {tx.CURRENCY} mn is above the "
            f"{MATERIAL_EXPOSURE:,.0f} materiality the threshold owner set, so "
            "a warning here is worth somebody's time.", MEDIUM)

    # ---- trajectory
    if found.worsening:
        add("worsening",
            f"{len(found.worsening)} condition"
            f"{'s are' if len(found.worsening) != 1 else ' is'} further beyond "
            "the threshold than in the previous observation period.", MEDIUM)

    # ---- what pushes the other way
    if found.resolved:
        mitigate("resolved",
                 f"{len(found.resolved)} warning"
                 f"{'s have' if len(found.resolved) != 1 else ' has'} come "
                 "back within threshold since the previous period.")
    if found.improving and not found.worsening:
        mitigate("improving",
                 f"{len(found.improving)} condition"
                 f"{'s are' if len(found.improving) != 1 else ' is'} moving "
                 "back towards its threshold.")
    if row and not gravity_reasons:
        try:
            cover = float(row.get("collateral_coverage_pct") or 0)
        except (TypeError, ValueError):
            cover = 0.0
        if cover >= 100.0:
            mitigate("collateral_cover",
                     f"Collateral covers {cover:,.0f}% of the exposure, so the "
                     "loss given default is not the whole exposure.")

    # ---- the level. Two parts, both required, exactly as LEVEL_MEANS says.
    #
    # An earlier draft took the worst of the reasons above: any one of eight
    # rules holding made a borrower High. On this book that made 88% of names
    # High, because on a stressed portfolio most of those rules hold for most
    # borrowers most of the time — breadth of two families is the MEDIAN. A
    # High list containing seven names in eight is not a list anybody works.
    #
    # So gravity and corroboration are both required, and neither substitutes
    # for the other. Gravity is that something serious is true; corroboration
    # is that it is visible somewhere other than where it started. A covenant
    # breach on a name whose every other measure is within threshold is a
    # covenant breach — a Medium, and a conversation. The same breach on a
    # name whose liquidity and IFRS 9 position have moved with it is a High.
    corroborating = tuple(f for f in families if f not in gravity_families)
    found.corroborating = corroborating
    has_gravity = bool(gravity_reasons)
    corroborated = len(corroborating) >= BREADTH_FAMILIES

    if has_gravity and corroborated:
        found.level = HIGH
    elif has_gravity or (corroborated and (severe or found.worsening)):
        found.level = MEDIUM
    else:
        found.level = LOW

    if has_gravity and not corroborated:
        add("not_corroborated",
            f"Serious, but confined: the evidence sits in "
            f"{len(families)} famil{'y' if len(families) == 1 else 'ies'} and "
            f"nothing else in the credit picture has moved with it.", MEDIUM)

    # The rule that lets the framework come DOWN. Without one, every borrower
    # ratchets upwards forever and the level stops carrying information.
    #
    # It applies where nothing serious is established and the only thing
    # holding the borrower at Medium is trajectory — and where the trajectory
    # is, on balance, the other way: more conditions came back within
    # threshold or moved towards it than moved further beyond it. A name with
    # one measure drifting and four recovering is recovering.
    recovering = len(found.resolved) + len(found.improving)
    if (found.level == MEDIUM and not has_gravity and not severe
            and recovering > len(found.worsening)):
        found.level = LOW
        found.mitigating.append(Reason(
            rule="mitigated",
            says=f"Nothing serious is established, and {recovering} condition"
                 f"{'s are' if recovering != 1 else ' is'} recovering against "
                 f"{len(found.worsening)} getting worse.", pushes=LOW))

    found.primary_concern = _primary(fired, matched)
    found.why_now = _why_now(found, fired)
    return found


def _primary(fired: list[sg.Observation],
             matched: list[cls.Match]) -> str:
    """The one thing to say first."""
    if not fired:
        return "Nothing beyond routine observations."
    for pool in (GRAVE_EVENTS, CREDIT_EVENTS):
        events = [o for o in fired if o.signal in pool]
        if events:
            return sorted(events, key=lambda o: tx.SEVERITY_RANK.get(
                o.severity, 0), reverse=True)[0].label
    if matched:
        return matched[0].classifier.label
    severe = [o for o in fired if o.severity == tx.SEVERE]
    if severe:
        return severe[0].label
    return sorted(fired, key=lambda o: tx.SEVERITY_RANK.get(o.severity, 0),
                  reverse=True)[0].label


def _why_now(found: Assessment, fired: list[sg.Observation]) -> str:
    """What changed THIS period, as opposed to what is simply true."""
    if found.new:
        labels = [o.label for o in fired if o.signal in set(found.new)]
        return ("New this period: " + ", ".join(sorted(labels)[:3])
                + ("…" if len(labels) > 3 else "") + ".")
    if found.worsening:
        labels = [o.label for o in fired if o.signal in set(found.worsening)]
        return ("Worse this period: " + ", ".join(sorted(labels)[:3])
                + ("…" if len(labels) > 3 else "") + ".")
    if found.persistent:
        return (f"Nothing new — {len(found.persistent)} condition"
                f"{'s' if len(found.persistent) != 1 else ''} carried over "
                "from the previous observation period.")
    if found.resolved:
        return f"{len(found.resolved)} warning(s) resolved this period."
    return "No change this period."


def describe() -> dict[str, Any]:
    """The methodology, as a reader can check it."""
    return {
        "owner": ASSESSMENT_OWNER,
        "version": ASSESSMENT_VERSION,
        "levels": [{"level": k, "means": v} for k, v in LEVEL_MEANS.items()],
        "states": [{"state": k, "means": STATE_MEANS[k]} for k in STATES],
        "rule": {
            "high": "Gravity AND corroboration. Neither substitutes for the "
                    "other.",
            "gravity": "A severe credit event, a severe condition present in "
                       "two consecutive observation periods, or a pattern the "
                       "threshold owner classes severe.",
            "corroboration": f"At least {BREADTH_FAMILIES} risk families "
                             "carrying evidence OTHER than the families the "
                             "gravity sits in.",
            "medium": "Gravity without corroboration, or corroboration with a "
                      "severe or worsening condition but nothing established.",
            "low": "Neither, or what fired has since come back.",
        },
        "inputs": [
            {"input": "Credit events",
             "rule": "An arrears, a breach, a downgrade, a restructuring or a "
                     "watchlist addition. Something happened."},
            {"input": "Severity and persistence",
             "rule": "A severe condition present in both the current and "
                     "previous observation periods."},
            {"input": "Breadth across independent families",
             "rule": f"At least {BREADTH_FAMILIES} independent risk families, "
                     "counted OUTSIDE the families the gravity sits in. Four "
                     "liquidity signals are one observation told four ways."},
            {"input": "Recognised patterns",
             "rule": f"{len(cls.CLASSIFIERS)} configured classifiers, each "
                     "with its rule written down."},
            {"input": "Credit-quality relevance",
             "rule": "Whether the rating and IFRS 9 evidence has moved too."},
            {"input": "External corroboration",
             "rule": "Whether evidence from outside the borrower's own "
                     "accounts agrees."},
            {"input": "Materiality",
             "rule": f"Exposure at or above {MATERIAL_EXPOSURE:,.0f} "
                     f"{tx.CURRENCY} mn."},
            {"input": "Trajectory",
             "rule": "Whether conditions are further beyond their thresholds "
                     "than last period."},
            {"input": "Mitigating evidence",
             "rule": "Resolved warnings, improving trajectory and collateral "
                     "cover push the level DOWN. A framework that can only "
                     "escalate is one nobody trusts."},
        ],
        "not_used": [
            {"input": "Materiality, as a driver of the level",
             "why": "A small facility can be in as much trouble as a large "
                    "one. Exposure decides who reads the warning, not how "
                    "serious it is."},
            {"input": "Signal count",
             "why": "It is a fact about the rule book rather than about the "
                    "borrower. Six stale-valuation observations are not worse "
                    "than one covenant breach."},
        ],
        "tac": {letter: {"type": kind, "means": tx.TAC_MEANS[kind]}
                for kind, letter in tx.TAC_LETTER.items()},
    }


__all__ = ["ASSESSMENT_OWNER", "ASSESSMENT_VERSION", "Assessment",
           "BREADTH_FAMILIES", "CREDIT_EVENTS", "HEALTHY", "HIGH",
           "GRAVE_EVENTS", "HIGH_CONCERN", "IMPROVING_STATE", "LEVELS",
           "LEVEL_MEANS",
           "LEVEL_RANK", "LOW", "MATERIAL_EXPOSURE", "MEDIUM", "NEW_WARNING",
           "PERSISTENT_WARNING", "RESOLVED", "Reason", "STATES", "STATE_MEANS",
           "WATCH_STATE", "WORSENING_WARNING", "assess", "describe",
           "state_of"]
