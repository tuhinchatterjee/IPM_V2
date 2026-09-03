"""The Investigation Response Package.

One question does not imply one analysis, and one analysis does not imply one
chart.

What used to happen
-------------------
"Investigate the Shipping sector." ran four governed analyses — exposure at
default over the year, expected credit loss over the year, exposure by IFRS 9
stage, and the borrowers behind both — and every one of them computed real
rows. Twenty-four of them. What reached the reader was a four-row table of
sentences *about* those analyses, and nothing else: no stage distribution, no
movement pair, no named borrowers, no picture of any of it. Four analyses had
been paid for and one paragraph had been delivered.

The instinct is to raise a cap. There was no cap to raise. The response
contract itself said "an answer is one result", so a composed answer had to
flatten itself into a single table before it could be returned at all, and the
flattening was lossy by construction.

What happens now
----------------
An answer is a PACKAGE: an ordered list of typed blocks, each one a governed
analysis presented in the shape its own result earns. The count is emergent.
Nothing here decides "three charts"; it decides, for each analysis that
materially contributed, what that analysis is — a figure, a table, a picture,
a matrix, a bridge — and the totals fall out of that.

Two rules keep it from becoming a wall:

    an analysis that added nothing is not a block. The Analysis Portfolio
    Planner already refuses candidates whose marginal value is under
    ``MIN_MARGINAL_VALUE``; this module refuses, in addition, the ones that
    ran and came back with nothing to show.

    a block is drawn only if the drawing says something the table does not.
    `visualize.choose` already decides that, per result, from the result's own
    shape and the reader's stated intent. This module does not second-guess it
    and does not add a chart the visual selector declined — which is what
    keeps "table first, charts on request" true while the block count varies.

So a simple question yields one block, usually a table. A sector deterioration
review yields five or six, several of them drawn. Neither is a setting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

PACKAGE_VERSION = "1.0.0"

# ---------------------------------------------------------------- block kinds

#: A sentence or a paragraph. Every package has at least one, because §35's
#: floor is a paragraph and a table alone is not an answer.
NARRATIVE = "narrative"
#: One governed figure, large. A single value is a figure, not a chart: a bar
#: chart with one bar in it tells a reader nothing the number did not.
KPI = "kpi"
#: Rows and columns, checkable against the figures quoted in the prose.
TABLE = "table"
#: A drawing of the same rows. Never instead of the table — always beside it.
CHART = "chart"
#: Two categorical axes and a measure: a migration, a transition, a
#: cross-tabulation. A matrix read as a flat table loses the thing it is for.
MATRIX = "matrix"
#: A total explained as steps between two totals. A bridge is not a bar chart
#: of unrelated categories and must not be shown as one.
DECOMPOSITION = "decomposition"
#: What the blocks together mean, written over them rather than inside any one
#: of them.
SYNTHESIS = "synthesis"

KINDS: tuple[str, ...] = (NARRATIVE, KPI, TABLE, CHART, MATRIX,
                          DECOMPOSITION, SYNTHESIS)

#: The one bound on package size, and the only number in this module that
#: could be mistaken for a budget. It is not one.
#:
#: Twelve because that is what a COMPLETE segment deterioration review is:
#: exposure, three PDs, LGD, ECL, coverage, stage by balance and by account
#: count, grade slippage, the borrowers behind it, and the summary over them.
#: The bound was eight, and eight cut the three most actionable analyses off
#: the end of a Shipping review — the stage migration, the slippage and the
#: names — while keeping seven parameter movements. A cap that truncates the
#: answer to the question is worse than no cap.
#:
#: It is still a cap, because a page that keeps extending is the card wall
#: §36 forbids, and it still says nothing about charts: a package of twelve
#: blocks may contain one drawing or eleven, depending entirely on what the
#: twelve results are.
MAX_BLOCKS = 12

#: Visual kinds `visualize` may return that are NOT charts. A block whose
#: chosen visual is one of these earns no CHART kind.
_NOT_A_CHART = frozenset({"table", "kpi", ""})

#: Visual kinds that ARE the presentation, not a decoration of it. A heatmap of
#: a from/to migration is the finding; the table under it is the check.
_MATRIX_VISUALS = frozenset({"heatmap"})
_BRIDGE_VISUALS = frozenset({"waterfall"})


# --------------------------------------------------------------------- blocks


@dataclass(frozen=True)
class Block:
    """One governed analysis, presented.

    A block never carries figures of its own. It carries the INDEX of the
    executed step that computed them, so there is exactly one copy of every
    number in a response and no way for a block to disagree with the analysis
    it is describing.
    """

    block_id: str
    #: What to render, in order. A table-and-chart block is one block with two
    #: kinds, not two blocks — they are the same rows and a reader who
    #: collapses one expects to collapse both.
    kinds: tuple[str, ...]
    title: str
    #: The governed question this block answers, in the product's own words.
    #: Every block is a question CreditProbe could have been asked directly.
    question: str = ""
    #: Why this analysis is in the response at all.
    because: str = ""
    #: The one sentence this block establishes.
    finding: str = ""
    #: Which executed step holds the rows. -1 for a block with no step behind
    #: it, which only the synthesis is.
    step_index: int = -1
    role: str = "supporting"
    #: The visual shape chosen for these rows, or "" where none was.
    visual: str = ""
    #: Why that shape, in the visual selector's own words.
    visual_reason: str = ""
    row_count: int = 0
    #: Why this result earns these kinds. Recorded so a reader who wonders why
    #: one analysis was drawn and another was not can be told.
    why: str = ""

    @property
    def drawn(self) -> bool:
        return any(k in (CHART, MATRIX, DECOMPOSITION) for k in self.kinds)

    def to_dict(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "kinds": list(self.kinds),
            "title": self.title,
            "question": self.question,
            "because": self.because,
            "finding": self.finding,
            "step_index": self.step_index,
            "role": self.role,
            "visual": self.visual,
            "visual_reason": self.visual_reason,
            "row_count": self.row_count,
            "why": self.why,
            "drawn": self.drawn,
        }


@dataclass
class Package:
    """The response contract: an ordered list of blocks, and how it was chosen."""

    blocks: list[Block] = field(default_factory=list)
    #: Analyses that ran and are not blocks, with the reason. An investigation
    #: that shows four findings without saying what it looked at and dropped is
    #: asking to be trusted about the part nobody can see.
    withheld: list[dict[str, str]] = field(default_factory=list)
    version: str = PACKAGE_VERSION

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    @property
    def table_count(self) -> int:
        return sum(1 for b in self.blocks if TABLE in b.kinds)

    @property
    def chart_count(self) -> int:
        return sum(1 for b in self.blocks if b.drawn)

    @property
    def analysis_count(self) -> int:
        return sum(1 for b in self.blocks if b.step_index >= 0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "blocks": [b.to_dict() for b in self.blocks],
            "withheld": list(self.withheld),
            "counts": {
                "blocks": self.block_count,
                "analyses": self.analysis_count,
                "tables": self.table_count,
                "drawn": self.chart_count,
            },
        }


# ------------------------------------------------------------ the shape rules


def kinds_for(rows: list[dict[str, Any]] | None,
              columns: list[dict[str, Any]] | None,
              visual: Any = None) -> tuple[tuple[str, ...], str]:
    """Which block kinds one governed result earns, and why.

    `visual` is whatever `visualize.choose` returned for these rows — a
    `Visual`, a dict of one, or None. It is READ, never overridden: the visual
    selector is where "table first, charts on request" lives, and a second
    place deciding whether to draw is a second place to disagree with it. In
    particular a chart the selector DEMOTED (`chart_first` false, because the
    question asked for rows) stays demoted here: the block is a table, and the
    picture stays one click away in the toggle where the selector put it.
    """
    rows = list(rows or [])
    columns = list(columns or [])
    kind = _visual_kind(visual)
    leads = _chart_first(visual)

    if not rows:
        return (NARRATIVE,), ("The analysis returned no rows, so there is "
                              "nothing to tabulate or draw.")

    if kind in _MATRIX_VISUALS:
        return (MATRIX, TABLE), ("Two categorical axes and a measure: read as "
                                 "a flat table this loses the movement it is "
                                 "for.")

    if kind in _BRIDGE_VISUALS:
        return (DECOMPOSITION, TABLE), ("A total explained as steps between "
                                        "two totals, which is a bridge rather "
                                        "than a comparison of categories.")

    if len(rows) == 1 and _measure_count(columns) <= 1:
        return (KPI,), ("One row and one measure is a figure. A chart of a "
                        "single bar says nothing the number did not.")

    if kind in _NOT_A_CHART:
        return (TABLE,), ("The figures are the answer, and no drawing of them "
                          "would say more than they do.")

    if not leads:
        return (TABLE,), ("The question asked for rows, so the table leads "
                          f"and the {kind.replace('_', ' ')} is offered "
                          "beside it rather than in place of it.")

    return (TABLE, CHART), ("Drawn as well as tabulated: the shape of the "
                            "result carries part of the finding, and the "
                            "table underneath keeps it checkable.")


def _visual_kind(visual: Any) -> str:
    """The chart shape `visualize` settled on, whatever form it arrives in."""
    if visual is None:
        return ""
    for attr in ("chart", "kind", "shape", "type"):
        value = getattr(visual, attr, None)
        if isinstance(value, str) and value:
            return value
    if isinstance(visual, dict):
        for attr in ("chart", "kind", "shape", "type"):
            value = visual.get(attr)
            if isinstance(value, str) and value:
                return value
    return ""


def _chart_first(visual: Any) -> bool:
    """Whether the selector decided the drawing should lead."""
    if visual is None:
        return False
    value = getattr(visual, "chart_first", None)
    if value is None and isinstance(visual, dict):
        value = visual.get("chart_first")
    return bool(value)


def _visual_reason(visual: Any) -> str:
    if visual is None:
        return ""
    value = getattr(visual, "reason", None)
    if isinstance(value, str):
        return value
    if isinstance(visual, dict):
        return str(visual.get("reason") or "")
    return ""


def _measure_count(columns: list[dict[str, Any]]) -> int:
    """How many columns carry a figure rather than a label."""
    total = 0
    for column in columns:
        role = str(column.get("role") or column.get("kind") or "").lower()
        if role in {"dimension", "label", "identifier", "category"}:
            continue
        unit = str(column.get("unit") or "")
        fmt = str(column.get("format") or "")
        if role in {"measure", "metric", "value"} or unit or fmt:
            total += 1
    return total or max(len(columns) - 1, 0)


# ------------------------------------------------------------------- building


def block_for(step: Any, *, block_id: str, role: str = "supporting",
              question: str = "", because: str = "",
              finding: str = "") -> Block:
    """The block one executed step earns.

    Reads the step's own result rather than being told what shape it is, so a
    step whose analysis changed cannot end up described as something it is not.
    """
    result = getattr(step, "result", None) or {}
    rows = list(result.get("rows") or [])
    columns = list(result.get("columns") or [])
    visual = result.get("visual") or result.get("chart") or None
    kinds, why = kinds_for(rows, columns, visual)
    return Block(
        block_id=block_id,
        kinds=kinds,
        title=str(getattr(step, "title", "") or block_id),
        question=question,
        because=because,
        finding=finding,
        step_index=int(getattr(step, "index", -1)),
        role=role,
        visual=_visual_kind(visual) if CHART in kinds or MATRIX in kinds
        or DECOMPOSITION in kinds else "",
        visual_reason=_visual_reason(visual),
        row_count=len(rows),
        why=why,
    )


def build(steps: list[Any], *, notes: list[dict[str, str]] | None = None,
          synthesis: str = "") -> Package:
    """The package for a set of executed steps.

    The first step is the primary — the planner marked it, and the order here
    follows that marking rather than the order things happened to run in.
    A step that failed or returned nothing is withheld with its reason rather
    than shown as an empty block.
    """
    blocks: list[Block] = []
    withheld: list[dict[str, str]] = list(notes or [])

    for position, step in enumerate(steps):
        if len(blocks) >= MAX_BLOCKS:
            withheld.append({
                "title": str(getattr(step, "title", "") or ""),
                "why": (f"The response already carries {MAX_BLOCKS} blocks. "
                        "Beyond that a reader is scrolling, not reading."),
            })
            continue
        status = str(getattr(step, "status", "succeeded") or "")
        if status != "succeeded":
            withheld.append({
                "title": str(getattr(step, "title", "") or ""),
                "why": str(getattr(step, "error", "")
                           or "The analysis did not complete."),
            })
            continue
        meta = getattr(step, "result", None) or {}
        blocks.append(block_for(
            step,
            block_id=f"block_{position + 1}",
            role=str(getattr(step, "role", "") or "supporting"),
            question=str(meta.get("asked") or ""),
            because=str(getattr(step, "rationale", "") or ""),
            finding=str(meta.get("finding") or ""),
        ))

    if synthesis:
        blocks.insert(0, Block(
            block_id="synthesis", kinds=(SYNTHESIS,), title="What this says",
            finding=synthesis, step_index=-1, role="synthesis",
            why=("Written over the analyses rather than inside any one of "
                 "them, because no single block establishes it."),
        ))
    return Package(blocks=blocks, withheld=withheld)


__all__ = [
    "Block", "Package", "PACKAGE_VERSION", "MAX_BLOCKS", "KINDS",
    "NARRATIVE", "KPI", "TABLE", "CHART", "MATRIX", "DECOMPOSITION",
    "SYNTHESIS", "kinds_for", "block_for", "build",
]
