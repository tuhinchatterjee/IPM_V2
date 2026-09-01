"""When a measurement stops describing the system it measured. §87.

A snapshot is a photograph. It stays true about the moment it was taken and
stops being true about now the instant anything underneath it changes, and
§87 names nine such things — the Brain, the release, the code, a model role,
a prompt, the ontology, the methods, the relationship contracts, the
evaluation set.

The distinction that matters
-----------------------------
§87 is explicit: **the historical snapshot remains immutable.** Staleness is
not a correction and does not rewrite anything. It is a label on the CURRENT
display saying that the newest measurement predates a change, so the number
on screen is describing a system that no longer exists.

Why the axes are named individually
------------------------------------
"Stale" tells a reader to re-run something. "Stale: the ontology changed on
the 14th" tells them what to re-run and roughly how much to expect, and lets
them decide that a prompt-only change probably did not move Computation &
Evidence. A single boolean throws that away, and the person who has to
schedule the re-evaluation is exactly the person who needed it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

STALENESS_VERSION = "1.0.0"

#: §87's nine axes: (field on the record, what it is, what a change to it
#: plausibly affects). The third element is guidance for a reader deciding
#: how urgent a re-evaluation is — a prompt change and an ontology change
#: are both staleness and they are not the same amount of it.
AXES: tuple[tuple[str, str, str], ...] = (
    ("brain_version", "the active Brain",
     "everything. A different Brain is a different set of learned "
     "behaviours, and no dimension can be assumed unaffected."),
    ("intelligence_release_id", "the Intelligence Release",
     "everything the release froze: teaching, prompts, policies and "
     "routing together."),
    ("build_sha", "the application code",
     "potentially anything. Code changes are the axis most often assumed "
     "harmless, and 'we only changed the formatter' is how a rounding "
     "difference reaches a regulatory return."),
    ("model_role_configuration", "which model serves which role",
     "Understanding & Context and Judgment & Presentation first, and "
     "latency and cost immediately."),
    ("prompt_versions", "the prompts",
     "Understanding & Context and Judgment & Presentation. Rarely "
     "Computation & Evidence, which is deterministic."),
    ("ontology_version", "the credit-risk ontology",
     "Understanding & Context and Analytical Design, and every teaching "
     "case whose concepts resolve through it."),
    ("method_version", "the certified methods",
     "Computation & Evidence directly. A method change moves the numbers "
     "themselves, not the words about them."),
    ("relationship_version", "the governed relationship contracts",
     "Analytical Design and Computation & Evidence: a changed join path "
     "changes which rows an answer is computed over."),
    ("development_set_version", "the evaluation set",
     "the comparability of every figure. Two scores over two different "
     "case sets are not comparable, and the difference between them is "
     "not improvement."),
)

AXIS_IDS: tuple[str, ...] = tuple(a for a, _, _ in AXES)

EXPECTED_AXES = 9
if len(AXES) != EXPECTED_AXES:
    raise AssertionError(
        f"§87 names {EXPECTED_AXES} staleness axes; this module has "
        f"{len(AXES)}.")

#: The axis that does not merely make a measurement old but makes it
#: incomparable. A changed evaluation set means the before and after are
#: measuring different things, and reporting the difference as improvement
#: is the oldest way to report one.
INCOMPARABLE: frozenset[str] = frozenset({"development_set_version"})

CURRENT = "CURRENT"
STALE = "STALE — RE-EVALUATE"
INCOMPARABLE_LABEL = "NOT COMPARABLE — THE EVALUATION SET CHANGED"


@dataclass
class Staleness:
    """Whether the newest measurement still describes the running system."""

    label: str = CURRENT
    changed: tuple[tuple[str, str, str]] | tuple = ()
    findings: list[str] = field(default_factory=list)

    @property
    def stale(self) -> bool:
        return self.label != CURRENT

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "stale": self.stale,
            "changed_axes": [
                {"axis": axis, "was": was, "now": now,
                 "what_it_is": dict((a, w) for a, w, _ in AXES).get(axis, ""),
                 "plausibly_affects":
                     dict((a, e) for a, _, e in AXES).get(axis, "")}
                for axis, was, now in self.changed],
            "findings": list(self.findings),
            "historical_snapshot_unchanged": True,
            "note": (
                "Staleness is a label on what is displayed now, not a "
                "correction. The snapshot stays exactly as it was recorded: "
                "it is still true about the moment it was taken, and only "
                "stopped being true about today."
            ),
        }


def assess(snapshot: dict[str, Any],
           current: dict[str, Any]) -> Staleness:
    """Compare a snapshot's versions against what is running now.

    A missing value on either side counts as a change rather than as a
    match. "We do not know what the ontology version was" and "it is the
    same" are different, and defaulting the difference towards CURRENT
    leaves a stale number on screen with no label.
    """
    changed: list[tuple[str, str, str]] = []
    for axis in AXIS_IDS:
        was = _text(snapshot.get(axis))
        now = _text(current.get(axis))
        if was != now:
            changed.append((axis, was or "unknown", now or "unknown"))

    report = Staleness(changed=tuple(changed))
    if not changed:
        return report

    if any(axis in INCOMPARABLE for axis, _, _ in changed):
        report.label = INCOMPARABLE_LABEL
        report.findings.append(
            "the evaluation set changed, so the before and after are "
            "measuring different things. The difference between them is not "
            "improvement, and re-running the current set against the "
            "baseline is the only way to get a comparable figure")
    else:
        report.label = STALE
        names = ", ".join(dict((a, w) for a, w, _ in AXES)[axis]
                          for axis, _, _ in changed)
        report.findings.append(
            f"{names} changed since this was measured. The figures on "
            "screen describe a system that no longer exists")
    return report


def _text(value: Any) -> str:
    """One comparable string, for a version that may be a dict.

    `prompt_versions` and `model_role_configuration` are mappings, and
    comparing them by identity would make every reload look like a change.
    """
    if value is None:
        return ""
    if isinstance(value, dict):
        return ";".join(f"{k}={v}" for k, v in sorted(value.items()))
    return str(value)
