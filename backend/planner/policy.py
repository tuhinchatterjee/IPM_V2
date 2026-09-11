"""How hard the agent chases, and who hears about it when chasing fails.

`control.Policy` already holds every threshold the deterministic engine reads,
and `PlannerProject` already carries two of them per project — `reminder_days`
and `stale_after_days`. What was missing is the rest of the answer to the
question a project manager actually asks at the start of a project:

    How do you want the Agentic AI to work for this project?

That question has four sensible answers and one long one, so this module is
four named modes and a custom escape hatch. It is deliberately a *pure*
module: no session, no clock, no queue. It turns a mode and an optional
override document into two things — a `control.Policy` the existing engine
already knows how to read, and an `Escalation` the monitor reads when a
reminder has stopped working.

Why the modes are named rather than numeric
-------------------------------------------
"Remind at 7, 3, 1 and 0 days, chase overdue daily, escalate after 2" is a
correct description and a terrible question. A person setting up a project
knows whether it is routine or time-critical; they do not know what a good
staleness window is, and asking them invents a decision they cannot make.
The named modes carry the judgement; Custom exists for the deployment that has
learned something the defaults do not know.

Why `sentence()` is here and not in the UI
------------------------------------------
The user has to approve this policy as part of the draft, and approving a
thing means reading it back in words. If the sentence lived in the frontend
it would be written twice — once for the setup screen, once for the project
page — and the two would drift. One function, one wording, and the tests
assert the wording says what the numbers do.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from backend.planner import control

POLICY_VERSION = "1.0.0"

#: Minimal chasing. For a project whose owners already talk every day and
#: would find a reminder at seven days out an interruption.
MODE_LIGHT = "LIGHT"
#: The recommended default.
MODE_STANDARD = "STANDARD"
#: For dated commitments — a regulatory submission, a committee, a go-live.
MODE_CRITICAL = "CRITICAL"
#: Whatever this deployment has learned that the three above do not know.
MODE_CUSTOM = "CUSTOM"

MODES: tuple[str, ...] = (MODE_LIGHT, MODE_STANDARD, MODE_CRITICAL,
                          MODE_CUSTOM)

MODE_LABELS: dict[str, str] = {
    MODE_LIGHT: "Light",
    MODE_STANDARD: "Standard",
    MODE_CRITICAL: "Critical",
    MODE_CUSTOM: "Custom",
}

MODE_NOTES: dict[str, str] = {
    MODE_LIGHT: "Minimal reminders. For a project whose owners already talk "
                "every day.",
    MODE_STANDARD: "Recommended. Reminders before the date, a daily chase "
                   "afterwards, and escalation when that stops working.",
    MODE_CRITICAL: "For dated commitments. Earlier warning, closer follow-up "
                   "and faster escalation.",
    MODE_CUSTOM: "Set the thresholds yourself.",
}


@dataclass(frozen=True)
class Escalation:
    """What happens when reminding somebody has stopped working.

    Separate from `control.Policy` on purpose. `Policy` decides what the
    engine CALLS a task — late, near, quiet. This decides who gets told when
    that assessment has been true for long enough, which is a governance
    question rather than an analytical one.
    """

    #: Days past the due date before the task's escalation owner is told.
    #: `None` means this project never escalates on lateness alone.
    escalate_after_days: int | None = 2
    #: Days a task may sit blocked before the same thing happens. Blocked is
    #: escalated sooner than late, because somebody else has to act.
    escalate_blocked_after_days: int | None = 2
    #: How often the owner is chased once the date has passed. 1 is daily.
    overdue_every_days: int = 1
    #: Tell the project manager when the calculated critical path is at risk.
    notify_manager_on_critical_path: bool = True
    #: Days of unresolved critical delay before the sponsor hears about it.
    #: `None` means the sponsor is never paged automatically.
    notify_sponsor_after_days: int | None = 5
    #: Whether a named reviewer is reminded about a review they owe.
    remind_reviewers: bool = True
    #: Days before a milestone date at which its own escalation owner is told
    #: that the work under it will not land. `None` disables it.
    milestone_escalate_before_days: int | None = 3


@dataclass(frozen=True)
class Agentic:
    """One project's complete answer to "how should the agent behave?"."""

    mode: str = MODE_STANDARD
    policy: control.Policy = field(default_factory=control.Policy)
    escalation: Escalation = field(default_factory=Escalation)

    @property
    def label(self) -> str:
        return MODE_LABELS.get(self.mode, self.mode)


# --------------------------------------------------------------- the modes


_PRESETS: dict[str, Agentic] = {
    MODE_LIGHT: Agentic(
        mode=MODE_LIGHT,
        policy=control.Policy(
            due_soon_days=3, imminent_days=1, stale_after_days=14,
            chase_no_progress_days=1, reminder_days=(1, 0)),
        escalation=Escalation(
            escalate_after_days=None, escalate_blocked_after_days=5,
            overdue_every_days=3, notify_manager_on_critical_path=False,
            notify_sponsor_after_days=None, remind_reviewers=False,
            milestone_escalate_before_days=None)),
    MODE_STANDARD: Agentic(
        mode=MODE_STANDARD,
        policy=control.Policy(),
        escalation=Escalation()),
    MODE_CRITICAL: Agentic(
        mode=MODE_CRITICAL,
        policy=control.Policy(
            due_soon_days=14, imminent_days=5, stale_after_days=3,
            amber_overdue_count=1, dependency_slip_days=1,
            milestone_horizon_days=21, chase_no_progress_days=2,
            reminder_days=(14, 7, 3, 1, 0)),
        escalation=Escalation(
            escalate_after_days=1, escalate_blocked_after_days=1,
            overdue_every_days=1, notify_manager_on_critical_path=True,
            notify_sponsor_after_days=3, remind_reviewers=True,
            milestone_escalate_before_days=7)),
}


def preset(mode: str) -> Agentic:
    """The named mode, or Standard for anything unrecognised.

    Falls back rather than raising: a project row carrying a mode a later
    version removed should keep being monitored sensibly, not stop being
    monitored at all.
    """
    return _PRESETS.get(str(mode or "").upper(), _PRESETS[MODE_STANDARD])


# ------------------------------------------------------------ custom modes


#: The custom fields a person may set, and where each one lands. Named
#: explicitly so an unknown key in a stored document is ignored rather than
#: setattr'd onto a frozen dataclass, and so the API can validate against one
#: list instead of two.
_POLICY_KEYS: tuple[str, ...] = (
    "due_soon_days", "imminent_days", "stale_after_days",
    "amber_overdue_count", "dependency_slip_days", "milestone_horizon_days",
    "chase_no_progress_days",
)
_ESCALATION_KEYS: tuple[str, ...] = (
    "escalate_after_days", "escalate_blocked_after_days",
    "overdue_every_days", "notify_manager_on_critical_path",
    "notify_sponsor_after_days", "remind_reviewers",
    "milestone_escalate_before_days",
)

CUSTOM_KEYS: tuple[str, ...] = ("reminder_days", *_POLICY_KEYS,
                                *_ESCALATION_KEYS)

#: Nothing in this module may be set beyond these bounds. Not because the
#: numbers are sacred, but because a reminder window of 400 days and a chase
#: every 0 days are both ways of turning the agent off while believing it is
#: on, and neither should be reachable by typing in a box.
_BOUNDS: dict[str, tuple[int, int]] = {
    "due_soon_days": (1, 90),
    "imminent_days": (0, 60),
    "stale_after_days": (1, 90),
    "amber_overdue_count": (1, 50),
    "dependency_slip_days": (0, 60),
    "milestone_horizon_days": (1, 120),
    "chase_no_progress_days": (0, 60),
    "escalate_after_days": (0, 60),
    "escalate_blocked_after_days": (0, 60),
    "overdue_every_days": (1, 30),
    "notify_sponsor_after_days": (0, 120),
    "milestone_escalate_before_days": (0, 60),
}


class PolicyError(ValueError):
    """A custom policy that would not do what the person setting it thinks."""


def _bounded(key: str, value: Any) -> int:
    low, high = _BOUNDS[key]
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise PolicyError(f"{key} must be a whole number of days.") from exc
    if not low <= number <= high:
        raise PolicyError(
            f"{key} must be between {low} and {high}; {number} would make the "
            "agent effectively silent or unbearable.")
    return number


def _reminder_days(value: Any) -> tuple[int, ...]:
    if not isinstance(value, (list, tuple)):
        raise PolicyError("Reminder days must be a list of days before the "
                          "due date, for example [7, 3, 1, 0].")
    days: list[int] = []
    for item in value:
        try:
            day = int(item)
        except (TypeError, ValueError) as exc:
            raise PolicyError("Every reminder day must be a whole number of "
                              "days before the due date.") from exc
        if not 0 <= day <= 120:
            raise PolicyError("A reminder day must be between 0 (the due "
                              f"date) and 120; {day} is outside that.")
        days.append(day)
    if not days:
        raise PolicyError("A custom policy with no reminder days would never "
                          "remind anybody. Choose Light instead — it says so "
                          "on the tin.")
    # Descending and unique: the engine reads them as thresholds, and 3 twice
    # is one threshold that fires once, not a reason to send two messages.
    return tuple(sorted(set(days), reverse=True))


def custom(document: dict[str, Any] | None) -> Agentic:
    """A Custom policy, built on Standard and overridden field by field.

    Built on Standard rather than on nothing, so a person who sets one field
    gets a working policy rather than a policy that is only that field.
    """
    given = dict(document or {})
    unknown = sorted(set(given) - set(CUSTOM_KEYS))
    if unknown:
        raise PolicyError(
            "A custom monitoring policy does not have "
            + ", ".join(unknown)
            + ". It has: " + ", ".join(CUSTOM_KEYS) + ".")

    base = _PRESETS[MODE_STANDARD]
    policy_changes: dict[str, Any] = {}
    escalation_changes: dict[str, Any] = {}

    if "reminder_days" in given:
        policy_changes["reminder_days"] = _reminder_days(given["reminder_days"])
    for key in _POLICY_KEYS:
        if key in given:
            policy_changes[key] = _bounded(key, given[key])
    for key in _ESCALATION_KEYS:
        if key not in given:
            continue
        value = given[key]
        if key in ("notify_manager_on_critical_path", "remind_reviewers"):
            escalation_changes[key] = bool(value)
        elif value is None:
            # Explicit "never", which is different from "not mentioned".
            escalation_changes[key] = None
        else:
            escalation_changes[key] = _bounded(key, value)

    agentic = Agentic(
        mode=MODE_CUSTOM,
        policy=replace(base.policy, **policy_changes),
        escalation=replace(base.escalation, **escalation_changes))
    _coherent(agentic)
    return agentic


def _coherent(agentic: Agentic) -> None:
    """Refuse combinations that cannot mean what they say."""
    policy, escalation = agentic.policy, agentic.escalation
    if policy.imminent_days > policy.due_soon_days:
        raise PolicyError(
            f"A task cannot be imminent ({policy.imminent_days} days) further "
            f"out than it is due soon ({policy.due_soon_days} days).")
    if escalation.notify_sponsor_after_days is not None \
            and escalation.escalate_after_days is not None \
            and escalation.notify_sponsor_after_days < \
            escalation.escalate_after_days:
        raise PolicyError(
            "The sponsor would hear about a delay before the escalation owner "
            "does. Escalation runs owner → escalation owner → sponsor, so the "
            "sponsor threshold must not be the shortest.")


def resolve(mode: str, document: dict[str, Any] | None = None) -> Agentic:
    """One project's agentic behaviour, from what is stored on the row."""
    if str(mode or "").upper() == MODE_CUSTOM:
        return custom(document)
    return preset(mode)


def of(project: Any) -> Agentic:
    """The agentic behaviour of a project row.

    Reads the two columns the project already had — `reminder_days` and
    `stale_after_days` — as overrides on top of the mode, so a project created
    before modes existed keeps the behaviour it was configured with instead of
    silently adopting a preset's.
    """
    agentic = resolve(getattr(project, "agentic_mode", "") or MODE_STANDARD,
                      getattr(project, "agentic_policy", None))
    changes: dict[str, Any] = {}
    days = getattr(project, "reminder_days", None)
    if days:
        try:
            changes["reminder_days"] = _reminder_days(days)
        except PolicyError:
            pass  # a stored oddity must not stop the project being monitored
    stale = getattr(project, "stale_after_days", None)
    if stale:
        try:
            changes["stale_after_days"] = _bounded("stale_after_days", stale)
        except PolicyError:
            pass
    if not changes:
        return agentic
    return replace(agentic, policy=replace(agentic.policy, **changes))


def stamp(project: Any, agentic: Agentic,
          document: dict[str, Any] | None = None) -> None:
    """Write one project's agentic behaviour onto its row — all of it.

    `of()` reads `reminder_days` and `stale_after_days` as overrides on top of
    the mode, so that a project configured before modes existed keeps the
    behaviour it was given. That kindness to old rows is a trap for new ones:
    a project set to Critical while those two columns still hold the creation
    defaults is monitored on the defaults, and choosing Critical then changes
    escalation but not the reminders it was chosen for. So every caller that
    SETS a mode writes the mode's numbers through as well, here, in one place,
    and the override only ever applies to a row nobody has set a mode on.
    """
    project.agentic_mode = agentic.mode
    project.agentic_policy = (dict(document or {})
                              if agentic.mode == MODE_CUSTOM else {})
    project.reminder_days = list(agentic.policy.reminder_days)
    project.stale_after_days = int(agentic.policy.stale_after_days)


# ------------------------------------------------------------- in words


def _days(values: tuple[int, ...]) -> str:
    """"7, 3 and 1 days before" — with the due date named, not called zero."""
    before = [d for d in values if d > 0]
    on_the_day = 0 in values
    parts: list[str] = []
    if before:
        if len(before) == 1:
            parts.append(f"{before[0]} day{'s' if before[0] != 1 else ''} "
                         "before the due date")
        else:
            listed = ", ".join(str(d) for d in before[:-1])
            parts.append(f"{listed} and {before[-1]} days before the due date")
    if on_the_day:
        parts.append("on the due date")
    return " and ".join(parts) if parts else "never"


def sentence(agentic: Agentic) -> str:
    """The policy in one paragraph, for the person who has to approve it."""
    policy, escalation = agentic.policy, agentic.escalation
    lines = [f"CreditProbe will remind task owners "
             f"{_days(policy.reminder_days)}."]

    if escalation.overdue_every_days == 1:
        lines.append("Once a date has passed it chases the owner every day")
    else:
        lines.append("Once a date has passed it chases the owner every "
                     f"{escalation.overdue_every_days} days")
    lines[-1] += (f", and asks for an update when a task due within "
                  f"{policy.imminent_days} day"
                  f"{'s' if policy.imminent_days != 1 else ''} has had no "
                  f"progress reported for {policy.stale_after_days} days.")

    if escalation.escalate_after_days is None:
        lines.append("Lateness alone is never escalated automatically.")
    else:
        lines.append(
            f"A task still overdue after {escalation.escalate_after_days} day"
            f"{'s' if escalation.escalate_after_days != 1 else ''} is escalated "
            "to its escalation owner")
        if escalation.escalate_blocked_after_days is not None:
            lines[-1] += (f", and a task blocked for "
                          f"{escalation.escalate_blocked_after_days} day"
                          f"{'s' if escalation.escalate_blocked_after_days != 1 else ''} "
                          "is escalated the same way")
        lines[-1] += "."

    if escalation.notify_sponsor_after_days is not None:
        lines.append(
            "The sponsor is told when a critical delay is still unresolved "
            f"after {escalation.notify_sponsor_after_days} days.")
    if escalation.notify_manager_on_critical_path:
        lines.append("The project manager is told when the calculated "
                     "critical path is at risk.")
    if not escalation.remind_reviewers:
        lines.append("Reviewers are not reminded about reviews they owe.")
    if escalation.milestone_escalate_before_days is not None:
        lines.append(
            "A milestone whose work will not land is raised with its "
            f"escalation owner {escalation.milestone_escalate_before_days} "
            "days before the date.")
    return " ".join(lines)


def describe(agentic: Agentic) -> dict[str, Any]:
    """The whole policy as a document — for the API, and for storage."""
    return {
        "mode": agentic.mode,
        "label": agentic.label,
        "note": MODE_NOTES.get(agentic.mode, ""),
        "sentence": sentence(agentic),
        "reminder_days": list(agentic.policy.reminder_days),
        "due_soon_days": agentic.policy.due_soon_days,
        "imminent_days": agentic.policy.imminent_days,
        "stale_after_days": agentic.policy.stale_after_days,
        "amber_overdue_count": agentic.policy.amber_overdue_count,
        "dependency_slip_days": agentic.policy.dependency_slip_days,
        "milestone_horizon_days": agentic.policy.milestone_horizon_days,
        "chase_no_progress_days": agentic.policy.chase_no_progress_days,
        "escalate_after_days": agentic.escalation.escalate_after_days,
        "escalate_blocked_after_days":
            agentic.escalation.escalate_blocked_after_days,
        "overdue_every_days": agentic.escalation.overdue_every_days,
        "notify_manager_on_critical_path":
            agentic.escalation.notify_manager_on_critical_path,
        "notify_sponsor_after_days":
            agentic.escalation.notify_sponsor_after_days,
        "remind_reviewers": agentic.escalation.remind_reviewers,
        "milestone_escalate_before_days":
            agentic.escalation.milestone_escalate_before_days,
    }


#: Every custom setting, in the words the person setting it reads, with the
#: bounds the engine will enforce anyway. One list: the panel renders from it
#: and `custom()` validates against it, so a field cannot appear on screen
#: that the policy does not have, and a bound cannot be shown that the server
#: does not apply.
_SETTINGS: tuple[dict[str, Any], ...] = (
    {"key": "reminder_days", "kind": "days_list",
     "label": "Remind the owner this many days before the date",
     "help": "For example 7, 3, 1 and 0. Zero is the due date itself."},
    {"key": "due_soon_days", "kind": "days",
     "label": "Treat a task as due soon this many days out",
     "help": "How far ahead the agent starts paying attention."},
    {"key": "imminent_days", "kind": "days",
     "label": "Treat a task as imminent this many days out",
     "help": "Inside this window, silence is chased rather than noted."},
    {"key": "stale_after_days", "kind": "days",
     "label": "Call a task stale after this many days without an update",
     "help": "The agent asks the owner where it stands."},
    {"key": "chase_no_progress_days", "kind": "days",
     "label": "Chase an imminent task with no progress after this many days"},
    {"key": "overdue_every_days", "kind": "days",
     "label": "Once a date has passed, chase the owner every this many days"},
    {"key": "escalate_after_days", "kind": "days_or_never",
     "label": "Escalate an overdue task after this many days",
     "help": "Never means lateness alone is never escalated automatically."},
    {"key": "escalate_blocked_after_days", "kind": "days_or_never",
     "label": "Escalate a blocked task after this many days",
     "help": "A block needs somebody outside the team to move."},
    {"key": "notify_sponsor_after_days", "kind": "days_or_never",
     "label": "Tell the sponsor when a delay is unresolved after this long",
     "help": "The last rung. It cannot be shorter than the escalation "
             "threshold, or the sponsor hears before the escalation owner."},
    {"key": "milestone_escalate_before_days", "kind": "days_or_never",
     "label": "Warn about a milestone at risk this many days before its date"},
    {"key": "amber_overdue_count", "kind": "days",
     "label": "Turn the project amber at this many overdue tasks",
     "help": "Volume alone, whether or not any of them is critical."},
    {"key": "dependency_slip_days", "kind": "days",
     "label": "Treat a late dependency as a schedule threat after this long",
     "help": "Below this it is recorded as a slip rather than a threat."},
    {"key": "milestone_horizon_days", "kind": "days",
     "label": "Look this many days ahead of a milestone for unfinished work"},
    {"key": "notify_manager_on_critical_path", "kind": "flag",
     "label": "Tell the project manager when the critical path is at risk"},
    {"key": "remind_reviewers", "kind": "flag",
     "label": "Remind reviewers about reviews they owe"},
)


def settings() -> list[dict[str, Any]]:
    """The custom fields, with bounds and the Standard value as the default."""
    base = _PRESETS[MODE_STANDARD]
    shown = describe(base)
    out: list[dict[str, Any]] = []
    for spec in _SETTINGS:
        key = spec["key"]
        low, high = _BOUNDS.get(key, (0, 0))
        out.append({**spec, "default": shown.get(key),
                    "minimum": low if key in _BOUNDS else None,
                    "maximum": high if key in _BOUNDS else None})
    return out


def choices() -> list[dict[str, Any]]:
    """The four modes, described, for the setup screen."""
    return [
        {"mode": mode, "label": MODE_LABELS[mode], "note": MODE_NOTES[mode],
         "recommended": mode == MODE_STANDARD,
         "sentence": sentence(preset(mode)) if mode != MODE_CUSTOM else
         "Set the reminder, chase and escalation thresholds yourself."}
        for mode in MODES
    ]


__all__ = [
    "Agentic", "CUSTOM_KEYS", "Escalation", "MODES", "MODE_CRITICAL",
    "MODE_CUSTOM", "MODE_LABELS", "MODE_LIGHT", "MODE_NOTES", "MODE_STANDARD",
    "POLICY_VERSION", "PolicyError", "choices", "custom", "describe", "of",
    "preset", "resolve", "sentence", "settings", "stamp",
]
