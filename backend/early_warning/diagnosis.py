"""
What the current high-risk population has in common.

A driver tree, and what it is not
---------------------------------
This fits a small tree over whatever population is selected, choosing each
split by how much it reduces variance in the early warning score. It is a
description of the population in front of you, not a model: it says what the
obligors currently scoring badly share, and it does not say who deteriorates
next. Those are different claims and only one of them is supported.

So the caveats travel with the result rather than sitting in a footnote. A
leaf is a hypothesis for a portfolio action, to be confirmed on the obligors
it names — never an approval or decline rule. That distinction is the whole
reason the tree is worth having: it turns "eight names are bad" into "the
bad names are the small exposures in arrears, which suggests the large ones
are already being managed and the small ones are not", which is a portfolio
action rather than eight separate escalations.

Why a minimum leaf as a share
-----------------------------
A fixed minimum leaf that is sensible on two dozen obligors is meaningless
on a book of thousands, and a tree that splits down to three names has found
noise and called it a finding. The floor is therefore a share of the
population with an absolute lower bound, so the same code is honest at both
sizes.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.early_warning import facts as ff

#: No leaf smaller than this share of the population being diagnosed. Fixed
#: from the root rather than recomputed per node — see `leaf_floor`.
MIN_LEAF_SHARE = 0.10

#: ...and never smaller than this many obligors, however large the book.
MIN_LEAF_ABSOLUTE = 3

#: How deep the tree may go. Two splits is four leaves, which is as much as a
#: reader can hold and act on; deeper trees describe noise.
MAX_DEPTH = 2

DESCRIPTIVE_ONLY = (
    "Descriptive, not predictive. This says what the current high-risk "
    "population has in common; it does not say which obligor deteriorates "
    "next. Treat a leaf as a hypothesis for a portfolio action and confirm "
    "it on the obligors it names — never as an approval or decline rule.")

NOT_FITTED = (
    "Splits are chosen by variance reduction on this population at this "
    "period. Refit at each run; a leaf is not a model.")


@dataclass
class Split:
    """One candidate partition of a population."""

    column: str
    label: str
    threshold: float | None = None
    #: For a categorical split, the values that fall on the "yes" side.
    values: tuple[str, ...] = ()

    def describe(self) -> str:
        if self.threshold is not None:
            return f"{self.label} >= {self.threshold:g}"
        return f"{self.label} is {' or '.join(self.values)}"

    def mask(self, frame: pd.DataFrame) -> pd.Series:
        if self.threshold is not None:
            return frame[self.column] >= self.threshold
        return frame[self.column].astype(str).isin(self.values)


@dataclass
class Node:
    """One population in the tree, and what it looks like."""

    label: str
    obligors: int
    exposure: float
    mean_ews: float
    high_plus: int
    depth: int
    split: str | None = None
    children: list["Node"] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"label": self.label, "obligors": self.obligors,
                "exposure": round(self.exposure, 2),
                "mean_ews": round(self.mean_ews, 2),
                "high_plus": self.high_plus, "depth": self.depth,
                "split": self.split,
                "children": [c.to_dict() for c in self.children]}

    def leaves(self) -> list["Node"]:
        if not self.children:
            return [self]
        return [leaf for child in self.children for leaf in child.leaves()]


#: The partitions worth testing. Each is something a credit officer can act
#: on: you can sweep the arrears book or review the large exposures, but you
#: cannot act on "obligors whose score is high", which is the tautology a
#: naive candidate set produces.
def candidate_splits(frame: pd.DataFrame) -> list[Split]:
    found: list[Split] = []
    if "dpd" in frame:
        for threshold in (30, 90):
            if frame["dpd"].max() >= threshold > frame["dpd"].min():
                found.append(Split("dpd", "Days past due", float(threshold)))
    if "exposure" in frame and len(frame) > 3:
        median = float(frame["exposure"].median())
        if median > 0:
            found.append(Split("exposure", "Exposure (SAR m)", round(median, 1)))
    if "utilisation_pct" in frame:
        for threshold in (80.0, 90.0):
            if frame["utilisation_pct"].max() >= threshold > frame["utilisation_pct"].min():
                found.append(Split("utilisation_pct", "Utilisation %", threshold))
    if "ifrs9_stage" in frame and frame["ifrs9_stage"].nunique() > 1:
        found.append(Split("ifrs9_stage", "IFRS 9 stage", 2.0))
    if "segment" in frame and 1 < frame["segment"].nunique() <= 12:
        worst = (frame.groupby("segment")["ews_score"].mean()
                 .sort_values(ascending=False))
        if len(worst) > 1:
            found.append(Split("segment", "Segment", values=(str(worst.index[0]),)))
    if "dominant_layer" in frame and frame["dominant_layer"].nunique() > 1:
        worst = (frame.groupby("dominant_layer")["ews_score"].mean()
                 .sort_values(ascending=False))
        if len(worst) > 1:
            found.append(Split("dominant_layer", "Dominant layer",
                               values=(str(worst.index[0]),)))
    return found


def leaf_floor(population: int) -> int:
    """The smallest leaf this population may be split into.

    Taken from the population being diagnosed and then held fixed at every
    depth. Recomputing it per node lets the floor shrink as the tree
    descends, so a second split can isolate a handful of names that the
    first split was forbidden from isolating — which is precisely the
    "found noise and called it a finding" outcome the floor exists to
    prevent.
    """
    return max(MIN_LEAF_ABSOLUTE, int(population * MIN_LEAF_SHARE))


def _variance_reduction(frame: pd.DataFrame, split: Split,
                         floor: int | None = None) -> float | None:
    """How much of the score's spread this split explains.

    None when either side would be below the minimum leaf, so a split that
    isolates a handful of names can never be chosen however well it separates
    them.
    """
    yes = split.mask(frame)
    left, right = frame[yes], frame[~yes]
    if floor is None:
        floor = leaf_floor(len(frame))
    if len(left) < floor or len(right) < floor:
        return None
    total = float(frame["ews_score"].var(ddof=0))
    if total <= 0:
        return None
    weighted = ((len(left) * float(left["ews_score"].var(ddof=0))
                 + len(right) * float(right["ews_score"].var(ddof=0)))
                / len(frame))
    return total - weighted


def _node(frame: pd.DataFrame, label: str, depth: int) -> Node:
    return Node(
        label=label, obligors=int(len(frame)),
        exposure=float(frame["exposure"].sum()),
        mean_ews=float(frame["ews_score"].mean()),
        high_plus=int(frame["ews_band"].isin(ff.HIGH_PLUS).sum()),
        depth=depth)


def _grow(frame: pd.DataFrame, label: str, depth: int, floor: int) -> Node:
    node = _node(frame, label, depth)
    if depth >= MAX_DEPTH or len(frame) < 2 * floor:
        return node
    best: tuple[float, Split] | None = None
    for split in candidate_splits(frame):
        gain = _variance_reduction(frame, split, floor)
        if gain is not None and (best is None or gain > best[0]):
            best = (gain, split)
    if best is None:
        return node
    _, split = best
    yes = split.mask(frame)
    node.split = split.describe()
    node.children = [
        _grow(frame[yes], split.describe(), depth + 1, floor),
        _grow(frame[~yes], f"not {split.describe()}", depth + 1, floor),
    ]
    return node


def tree(period: str | None = None, *, band: str | None = None,
         segment: str | None = None,
         where: dict[str, Any] | None = None) -> dict[str, Any]:
    """Fit the driver tree over the selected population.

    `band`, `segment` and `where` select the population the same way the
    screen does, so the tree describes whatever the reader is looking at
    rather than always the whole book.

    `where` is the general form and the one the conversational planner
    supplies. Without it, "why has the Contracting sector deteriorated?"
    planned a diagnosis WITH a sector filter, the executor dropped the
    filter on the floor because this function had nowhere to put it, and the
    reader was told what the whole book's high-risk names have in common —
    a real finding about a population they had not asked about.
    """
    frame = ff._with_derived(ff.svc.borrower_month(period))
    label = "all obligors in scope"
    if band == "HIGH_PLUS":
        frame = frame[frame["ews_band"].isin(ff.HIGH_PLUS)]
        label = "obligors at high or above"
    elif band in ff.BAND_ORDER:
        frame = frame[frame["ews_band"] == band]
        label = f"obligors at {band.replace('_', ' ').lower()}"
    if segment:
        frame = frame[frame["segment"].astype(str) == str(segment)]
        label = f"{label} in {segment}"
    named: list[str] = []
    for column, value in (where or {}).items():
        if column in ("high_plus",) or column not in frame.columns:
            continue
        if isinstance(value, bool):
            frame = frame[frame[column] == value]
            named.append(column.replace("_", " "))
        else:
            frame = frame[frame[column].astype(str).str.lower()
                          == str(value).lower()]
            named.append(str(value))
    if named:
        label = f"{label} in {', '.join(named)}"

    if frame.empty:
        return {"period": period or ff.svc.latest_period(),
                "population": label, "root": None, "leaves": [],
                "reading": "There is nothing in this population to describe.",
                "caveats": [DESCRIPTIVE_ONLY, NOT_FITTED]}

    floor = leaf_floor(len(frame))
    root = _grow(frame, label, 0, floor)
    leaves = sorted(root.leaves(), key=lambda n: n.mean_ews, reverse=True)
    return {
        "period": period or ff.svc.latest_period(),
        "population": label,
        "min_leaf": floor,
        "min_leaf_share": MIN_LEAF_SHARE,
        "max_depth": MAX_DEPTH,
        "root": root.to_dict(),
        "leaves": [n.to_dict() for n in leaves],
        "strongest_split": root.split,
        "reading": _reading(root, leaves),
        "caveats": [DESCRIPTIVE_ONLY, NOT_FITTED],
    }


def _reading(root: Node, leaves: list[Node]) -> str:
    """What the tree is telling you, said once, in the shape a reader acts on."""
    if not root.split or len(leaves) < 2:
        return (f"No partition separates this population: all "
                f"{root.obligors} obligors sit at a mean score of "
                f"{root.mean_ews:.1f} without a driver that divides them.")
    worst, best = leaves[0], leaves[-1]
    parts = [
        f"{root.split} is the strongest partition. Obligors meeting it "
        f"average {_side(root, True):.1f} against {_side(root, False):.1f} "
        f"for the rest."]
    if worst.depth > 1:
        parts.append(
            f"The weakest leaf is \"{worst.label}\": {worst.obligors} "
            f"obligors averaging {worst.mean_ews:.1f}, against "
            f"{best.mean_ews:.1f} for \"{best.label}\". That is the "
            f"population to act on, and it is a population action rather "
            f"than a series of single-name escalations.")
    return " ".join(parts)


def _side(root: Node, yes: bool) -> float:
    if len(root.children) < 2:
        return root.mean_ews
    return root.children[0 if yes else 1].mean_ews


__all__ = ["MIN_LEAF_SHARE", "MIN_LEAF_ABSOLUTE", "MAX_DEPTH", "leaf_floor",
           "DESCRIPTIVE_ONLY", "NOT_FITTED", "Split", "Node",
           "candidate_splits", "tree"]
