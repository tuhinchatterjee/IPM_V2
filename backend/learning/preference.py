"""
Channel A: what may change immediately, per user. §13.

The distinction this module exists to hold
--------------------------------------------
    A. IMMEDIATE USER-PREFERENCE LEARNING — chart versus table, theme,
       density, answer length, currency scale, suggestion visibility,
       feedback prompt visibility, palette. "This is presentation preference,
       not analytical truth."

    B. GOVERNED ANALYTICAL LEARNING — concept interpretation, officer
       selection, dataset selection, method selection, plan structure,
       clarification behaviour, regulatory answers, analytical
       interpretation. "Do not apply these immediately from raw feedback."

The two are one careless line apart. "The user prefers less detail" is A; "the
user prefers the shorter number" is B wearing A's clothes. So channel A is a
CLOSED SET, enumerated here, and anything outside it cannot be applied
immediately whatever a caller passes — `apply` refuses rather than ignores, so
a mistake is loud.

Per user, per tenant, and reversible
--------------------------------------
A preference belongs to one person. It is not evidence about the product, it
does not aggregate into a metric that changes anything, and it is undone by
changing it back. Nothing here is a learning candidate and nothing here
reaches another user.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

PREFERENCE_VERSION = "1.0.0"

# ---------------------------------------------------------------------------
# The closed set. §13's channel A, and nothing else.
# ---------------------------------------------------------------------------

#: name -> (allowed values, default, what it is). A preference with no
#: enumerated values would let "answer_length" be set to a paragraph of
#: instructions, which is a prompt injection with a settings screen.
SETTINGS: dict[str, tuple[tuple[str, ...], str, str]] = {
    "result_form": (("auto", "table", "chart"), "auto",
                    "Whether a result is drawn as a table or a chart when "
                    "both would be valid."),
    "theme": (("system", "light", "dark"), "system",
              "The visual theme."),
    "density": (("comfortable", "compact"), "comfortable",
                "How much room the interface gives each row."),
    "answer_length": (("brief", "standard", "full"), "standard",
                      "How much of the working an answer shows."),
    "currency_scale": (("auto", "units", "thousands", "millions"), "auto",
                       "The scale figures are shown at."),
    "suggestions": (("on", "off"), "on",
                    "Whether follow-up questions are offered."),
    "feedback_prompt": (("on", "reduced", "off"), "on",
                        "How often the feedback prompt appears. §7 requires "
                        "the user be able to reduce or hide it."),
    "chart_palette": (("default", "high_contrast", "print"), "default",
                      "The chart palette."),
}

NAMES: tuple[str, ...] = tuple(SETTINGS)

#: Things that look like preferences and are not. Named so that a refusal can
#: say WHY rather than "unknown setting", which reads as a bug.
NOT_PREFERENCES: dict[str, str] = {
    "dataset": "which governed source an answer reads",
    "method": "which governed method an answer uses",
    "period": "which reporting period an answer covers",
    "grain": "what one row of an answer is",
    "officer": "which officer level the work is done at",
    "agents": "which specialists are engaged",
    "model": "which model serves a role",
    "threshold": "where a clarification or an abstention threshold sits",
    "interpretation": "what an answer says about its own figures",
    "rounding": "how a computed figure is rounded",
}


class PreferenceError(Exception):
    """Something a preference may not be, or may not do."""


@dataclass
class Preference:
    """One user's presentation settings, per tenant."""

    user_id: str = ""
    tenant: str = ""
    values: dict[str, str] = field(default_factory=dict)
    #: The thread ids where the user asked not to be prompted again. §7.
    muted_threads: list[str] = field(default_factory=list)
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    schema_version: str = PREFERENCE_VERSION

    def get(self, name: str) -> str:
        if name not in SETTINGS:
            raise PreferenceError(f"{name!r} is not a presentation setting")
        return self.values.get(name, SETTINGS[name][1])

    @property
    def prompts_muted(self) -> bool:
        return self.get("feedback_prompt") == "off"

    def thread_muted(self, thread_id: str) -> bool:
        return str(thread_id) in self.muted_threads

    def to_dict(self) -> dict[str, Any]:
        return {
            "user": self.user_id, "tenant": self.tenant,
            "values": {name: self.get(name) for name in NAMES},
            "muted_threads": list(self.muted_threads),
            "prompts_muted": self.prompts_muted,
            "settings": {name: {"values": list(values), "default": default,
                                "what": what}
                         for name, (values, default, what)
                         in SETTINGS.items()},
            "updated_at": self.updated_at.isoformat(),
            "schema_version": self.schema_version,
        }


def apply(preference: Preference, name: str, value: str) -> Preference:
    """Set one presentation preference, immediately, for this user.

    The only thing in the whole learning package that takes effect without a
    review, and the refusals are why that is safe: a name outside the closed
    set is refused with a sentence saying what it actually is, and a value
    outside the enumeration is refused with the list.
    """
    if name in NOT_PREFERENCES:
        raise PreferenceError(
            f"{name!r} is {NOT_PREFERENCES[name]}, which is analytical "
            "behaviour rather than presentation. §13 puts it in the governed "
            "channel: it changes through review, evaluation and a Learning "
            "Release, not through a setting.")
    if name not in SETTINGS:
        raise PreferenceError(
            f"{name!r} is not a presentation setting. The set is closed: "
            + ", ".join(NAMES))
    allowed, _, _ = SETTINGS[name]
    if value not in allowed:
        raise PreferenceError(
            f"{value!r} is not a value for {name!r}: " + ", ".join(allowed))
    preference.values[name] = value
    preference.updated_at = datetime.now(UTC)
    return preference


def mute_thread(preference: Preference, thread_id: str) -> Preference:
    """"Don't ask again in this thread." §7."""
    thread = str(thread_id).strip()
    if not thread:
        raise PreferenceError("muting needs the thread it applies to")
    if thread not in preference.muted_threads:
        preference.muted_threads.append(thread)
    preference.updated_at = datetime.now(UTC)
    return preference


def from_feedback(event: Any) -> list[tuple[str, str]]:
    """The presentation preferences a piece of feedback implies, if any.

    Deliberately conservative and deliberately NOT applied here: this returns
    what could be OFFERED to the user ("show shorter answers from now on?"),
    because a product that silently changes its own behaviour because somebody
    said "too much detail" once has made a decision the user did not.

    Returns nothing at all unless every category reported is a presentation
    one. A user who says the answer was too long AND used the wrong period has
    reported a correctness failure, and reading the first half as a preference
    quietly discards the second.
    """
    from backend.learning import feedback as fb

    if not getattr(event, "presentation_only", False):
        return []
    chosen = set(getattr(event, "categories", None) or [])
    out: list[tuple[str, str]] = []
    if "too_much_detail" in chosen:
        out.append(("answer_length", "brief"))
    if "too_little_detail" in chosen:
        out.append(("answer_length", "full"))
    if "wrong_visual" in chosen:
        wanted = str(getattr(getattr(event, "correction", None),
                             "expected_visualization", "") or "").lower()
        if wanted in ("table", "chart"):
            out.append(("result_form", wanted))
    del fb
    return out


__all__ = ["NAMES", "NOT_PREFERENCES", "PREFERENCE_VERSION", "Preference",
           "PreferenceError", "SETTINGS", "apply", "from_feedback",
           "mute_thread"]
