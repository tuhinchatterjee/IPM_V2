"""
Which path makes a document, and why. Chapter 08.

Two exist and both stay:

    SKILL   the provider's document tooling, driven in a sandbox. Richer
            layout, and it costs a provider call and minutes of latency.
    LOCAL   `backend/playbook/render/`. Deterministic, fast, free, and the
            only path that can convert an existing version without asking a
            model to write anything.

Chapter 08 asks for the better one per task rather than a blanket switch, and
is equally clear that the local renderer "must not be the hidden sole
authoring system that flattens all requests into a minimal fixed schema".

So the choice is made here, explicitly, and the answer travels with the file:
`playbook_artifact_files.renderer` already records which path produced each
artifact, and `_usable` decides per format, so a Skill file that validates is
kept as it came and only a format that will not open falls back.

The rule
--------
* A conversion never uses the provider. The document is already written;
  re-authoring it would spend money to produce a different report under the
  same version number.
* Otherwise, use SKILL when it is actually available, and LOCAL when it is
  not. Availability is a runtime fact, not a hope: it needs the feature turned
  on AND a configured provider.

What this deliberately does not do
----------------------------------
It never makes the conversation depend on a document tool. An unavailable
path means a document is rendered the other way, or — if neither can produce a
format — that one format is reported as failed. Chapter 04's ordinary question
does not touch this module at all.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.playbook import capabilities, provider

SKILL = capabilities.SKILL
LOCAL = capabilities.LOCAL


@dataclass(frozen=True)
class Choice:
    """The path, and the reason, so a diagnostic can say why."""

    path: str
    reason: str
    skill_available: bool

    def as_dict(self) -> dict:
        return {"path": self.path, "reason": self.reason,
                "skill_available": self.skill_available}


def skill_available() -> bool:
    """Whether the provider's document tooling can actually run right now.

    Both halves are required. The feature flag alone is a preference; without
    a configured provider there is nothing to drive the sandbox, and reporting
    the Skill path as available would make the capability audit a wish.
    """
    return bool(provider.SKILL_RENDERING and provider.status().configured)


def choose(*, converting: bool = False) -> Choice:
    """Which path should make this artifact."""
    if converting:
        return Choice(
            LOCAL,
            "a conversion reuses the version that already exists, so no "
            "provider call is made",
            skill_available())
    if skill_available():
        return Choice(SKILL, "the provider's document tooling is available",
                      True)
    return Choice(
        LOCAL,
        "the provider's document tooling is not enabled on this deployment, "
        "so documents are rendered locally",
        False)


def report() -> dict:
    """What to show in a capability audit. Chapter 02's three states."""
    default = choose()
    return {
        "paths": {
            SKILL: {
                "state": "implemented" if skill_available()
                         else "available_but_disabled",
                "detail": ("driven through the provider's code execution and "
                           "document Skills"),
                "enable": "PLAYBOOK_SKILL_RENDERING=1 with a configured "
                          "provider",
            },
            LOCAL: {
                "state": "implemented",
                "detail": ("CreditProbe's own renderers; also the only path "
                           "for converting an existing version"),
            },
        },
        "default": default.as_dict(),
    }
