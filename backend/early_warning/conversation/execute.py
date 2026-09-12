"""
Running a validated plan, against this domain and no other.

Where the domain lock actually bites
-------------------------------------
The validator refuses a plan that names another domain. This module is the
second control and the one that would still hold if the first were removed:
every read here goes through `wide` and `v2_service`, which read the Early
Warning parquet partitions and nothing else. There is no connection, no
handle and no parameter through which another dataset could be reached, so
reaching one is not something this code declines to do — it is something it
has no way to express.

That is deliberate. A lock enforced only by a check is a lock that fails open
the day someone adds a branch that skips the check.

What comes back
---------------
Exact executed results, with the row count, the grain and the statements
that produced them. A result nobody can check against what was run is a
result the prose can quietly exceed.

Nothing raw escapes
-------------------
Every failure leaves this module as an `ExecutionError` carrying a code and
what the domain offers instead, because the pipeline already knows how to
turn that into a repair or an honest limitation. An unexpected exception
escaping here would end the conversational turn — no answer, no partial
answer, no explanation — for a reader who asked an ordinary question. That
is what a governed runtime is for.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from backend.early_warning import executable as ex
from backend.early_warning import facts as ff
from backend.early_warning import grain as grain_mod
from backend.early_warning import layers as layers_mod
from backend.early_warning import v2_service as svc
from backend.early_warning import wide
from backend.early_warning.conversation import plan as plan_mod

logger = logging.getLogger(__name__)


class ExecutionError(RuntimeError):
    """A step that could not run. Carries a repairable reason."""

    def __init__(self, message: str, *, code: str = "execution_failed",
                 offered: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.offered = list(offered or [])


@dataclass
class Executed:
    """One step's exact result."""

    step: plan_mod.Step
    rows: list[dict[str, Any]] = field(default_factory=list)
    figures: dict[str, Any] = field(default_factory=dict)
    row_count: int = 0
    grain: str = ""
    statement: str = ""
    duration_ms: int = 0
    warnings: list[str] = field(default_factory=list)
    #: The fact pack behind this step, where one scope produced it. The
    #: existing composer and rubric both read packs, so a step that produced
    #: one keeps it rather than flattening it into loose numbers.
    pack: ff.FactPack | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "analysis": self.step.analysis,
            "rows": list(self.rows), "figures": dict(self.figures),
            "row_count": self.row_count, "grain": self.grain,
            "statement": self.statement, "duration_ms": self.duration_ms,
            "warnings": list(self.warnings),
        }


def _frame(step: plan_mod.Step) -> pd.DataFrame:
    """The domain, at the month the step named, filtered as it asked.

    The only door to data in this module.
    """
    frame = wide.with_movement(step.period or None)
    if frame.empty:
        raise ExecutionError(
            f"No published data for {step.period!r}.",
            code="no_data", offered=list(svc.periods()))
    for column, value in (step.filters or {}).items():
        if column not in frame.columns:
            raise ExecutionError(
                f"Cannot filter on {column!r}: it is not a field in this "
                f"domain.", code="unknown_field",
                offered=sorted(frame.columns)[:8])
        if isinstance(value, bool):
            frame = frame[frame[column] == value]
        else:
            frame = frame[frame[column].astype(str).str.lower()
                          == str(value).lower()]
    return frame


def _population_figures(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"obligors": 0, "exposure": 0.0}
    exposure = float(frame["exposure"].sum())
    high = frame[frame["high_plus"]]
    return {
        "obligors": int(len(frame)),
        "exposure": round(exposure, 2),
        "portfolio_ews": round(
            float((frame["ews_score"] * frame["exposure"]).sum() / exposure), 2)
        if exposure else 0.0,
        "mean_ews": round(float(frame["ews_score"].mean()), 2),
        "high_plus_count": int(len(high)),
        "high_plus_exposure": round(float(high["exposure"].sum()), 2),
        "high_plus_exposure_pct": round(
            100.0 * float(high["exposure"].sum()) / exposure, 1)
        if exposure else 0.0,
    }


def _rows(frame: pd.DataFrame, step: plan_mod.Step) -> list[dict[str, Any]]:
    keep = ["customer_id", "customer_name"] + [
        m for m in step.measures if m in frame.columns]
    keep = [c for c in dict.fromkeys(keep) if c in frame.columns]
    ordered = (frame.sort_values(step.order_by, ascending=not step.descending)
               if step.order_by in frame.columns else frame)
    out = ordered.head(max(1, step.limit))[keep]
    return [{k: _plain(v) for k, v in row.items()}
            for row in out.to_dict("records")]


def _plain(value: Any) -> Any:
    if isinstance(value, float) and value != value:
        return None
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:  # noqa: BLE001
            return str(value)
    return value


def run(step: plan_mod.Step) -> Executed:
    """Execute one validated step, or fail in a way the turn can survive.

    The last boundary. Validation is meant to catch everything this module
    cannot run, and for the case that started this — a grouping the validator
    approved and the fact builder could not perform — it now does. But a
    control whose only guarantee is that the check upstream is complete is a
    control that ends a conversation the day the check is not.

    So anything unexpected in here becomes an `ExecutionError`, which the
    pipeline already handles as a repair-or-say-so path. A KeyError escaping
    to the caller takes the whole turn with it: no answer, no partial answer,
    no explanation — a 500 where the reader asked a question.
    """
    try:
        return _run(step)
    except ExecutionError:
        raise
    except ff.UnsupportedLevel as failure:
        raise ExecutionError(
            str(failure), code="ungroupable",
            offered=sorted(ex.GROUPINGS)) from failure
    except KeyError as failure:
        # A field the executor reached for and did not find. Named, because
        # `KeyError('dominant_subcategory')` in a log is a better clue than
        # anything a generic message would say.
        missing = str(failure).strip("'\"")
        logger.warning("An Early Warning %s step reached for %r and did not "
                       "find it.", step.analysis, missing)
        raise ExecutionError(
            f"The {step.analysis} step reached for {missing!r}, which this "
            f"domain does not carry where it was looked for.",
            code="unknown_field",
            offered=ex.alternatives(missing, role=ex.MEASURE)) from failure
    except Exception as failure:  # noqa: BLE001 - a turn must survive this
        logger.exception("An Early Warning %s step failed.", step.analysis)
        raise ExecutionError(
            f"The {step.analysis} step could not be completed: "
            f"{type(failure).__name__}: {failure}",
            code="execution_failed") from failure


def _run(step: plan_mod.Step) -> Executed:
    """The step itself."""
    started = time.perf_counter()
    analysis = step.analysis

    if analysis == plan_mod.METHODOLOGY:
        pack = ff.methodology()
        return _done(step, started, figures=dict(pack.figures),
                     grain="methodology", pack=pack,
                     statement="governed methodology metadata; no query run")

    if analysis == plan_mod.ACTION:
        # One obligor, or the population the question was about. Without the
        # second branch a population-scoped action step returned nothing, so
        # "should either be escalated?" was headlined by whatever else had
        # run and answered as a sector summary.
        if step.customer_id:
            pack = ff.borrower(step.customer_id)
            grain = "customer_latest"
        else:
            pack = ff.population_actions(step.period or None,
                                         only=step.filters or None)
            grain = "population_month"
        return _done(step, started,
                     figures=dict(pack.figures) if pack else {},
                     rows=list(pack.rows) if pack else [],
                     grain=grain, pack=pack,
                     statement=("governed action library and escalation "
                                "matrix; no analytical query run"))

    if analysis == plan_mod.EVIDENCE:
        signal = step.signal_key or _dominant_signal(step.customer_id, step.period)
        pack = (ff.signal_evidence(step.customer_id, signal, step.period)
                if signal else None)
        if pack is None:
            raise ExecutionError(
                f"No signal observation for {step.customer_id!r} in "
                f"{step.period!r}.", code="no_data")
        return _done(step, started, figures=dict(pack.figures),
                     grain="customer_month", pack=pack,
                     statement=f"early_warning_signal_observation[{signal}]")

    if analysis == plan_mod.LAYER:
        # A layer step used to fall through to the population branch, where
        # it read the whole book and the layer it named went nowhere. It has
        # its own pack: the nodes inside the layer for this obligor, which is
        # what "what external warning events are driving this borrower?"
        # asks for.
        if not step.customer_id:
            raise ExecutionError(
                f"A {step.layer or 'layer'} reading needs an obligor, and "
                f"the question named none.", code="no_obligor")
        pack = ff.layer(step.customer_id, step.layer)
        return _done(step, started, figures=dict(pack.figures),
                     rows=list(pack.rows), grain="customer_month", pack=pack,
                     statement=f"early_warning_layer_tree"
                               f"[customer_id={step.customer_id}, "
                               f"layer={step.layer}]")

    if analysis == plan_mod.BORROWER:
        pack = ff.borrower(step.customer_id)
        return _done(step, started, figures=dict(pack.figures),
                     grain="customer_latest", pack=pack,
                     rows=list(pack.rows)[:step.limit],
                     statement=f"early_warning_borrower_month"
                               f"[customer_id={step.customer_id}]")

    if analysis == plan_mod.DIAGNOSIS:
        # The slice the question asked for, carried into the tree. It was
        # being computed by the planner, validated, and then dropped here.
        pack = ff.diagnosis(step.period,
                            band="HIGH_PLUS" if step.filters.get("high_plus")
                            else None,
                            where={k: v for k, v in (step.filters or {}).items()
                                   if k != "high_plus"})
        return _done(step, started, figures=dict(pack.figures),
                     rows=list(pack.rows), grain="population_month", pack=pack,
                     statement=f"variance-reduction driver tree over "
                               f"early_warning_borrower_month[{step.period}]")

    if analysis == plan_mod.TRANSITION:
        pack = ff.transitions(step.comparison_period or None,
                              step.period or None,
                              only=step.filters or None,
                              from_band=step.from_band or None,
                              to_band=step.to_band or None,
                              direction=step.direction or "",
                              group_by=step.group_by or "",
                              limit=max(1, step.limit))
        cell = ", ".join(
            f"{k}={v}" for k, v in (("from", step.from_band),
                                    ("to", step.to_band),
                                    ("direction", step.direction)) if v)
        return _done(step, started, figures=dict(pack.figures),
                     rows=list(pack.rows), grain="population_transition",
                     pack=pack,
                     statement=f"early_warning_borrower_month"
                               f"[{step.comparison_period}] vs "
                               f"[{step.period}], band by band"
                               + (f", {cell}" if cell else ""))

    if analysis == plan_mod.MOVEMENT:
        pack = ff.movement(step.comparison_period or None, step.period or None,
                           where=step.filters or None,
                           customer_id=step.customer_id or "")
        return _done(step, started, figures=dict(pack.figures),
                     rows=list(pack.rows), grain="population_trend", pack=pack,
                     statement=f"early_warning_borrower_month"
                               f"[{step.comparison_period} -> {step.period}]")

    if analysis == plan_mod.GROUPING:
        # The slice the question asked for is applied before the grouping,
        # not after and not at all: "exposure by sector for obligors at High
        # or Very High" is a cut of the high-risk population, not of the book.
        only = dict(step.filters or {})
        # A grouping the question read ON a layer is ordered by that layer's
        # score. Same partition, different ranking — and the ranking is what
        # the reader asked for.
        rank_by = (layers_mod.BY_CODE[step.layer].ta_key
                   if layers_mod.is_code(step.layer) else "")
        pack = ff.level(step.group_by, step.period, only=only or None,
                        rank_by=rank_by)
        where = ", ".join(f"{k}={v!r}" for k, v in only.items())
        return _done(step, started, figures=dict(pack.figures),
                     rows=list(pack.rows), grain="group_month", pack=pack,
                     statement=f"early_warning_borrower_month[{step.period}] "
                               + (f"where {where} " if where else "")
                               + f"grouped by {step.group_by}"
                               + (f", ranked by {rank_by}" if rank_by else ""))

    frame = _frame(step)
    figures = _population_figures(frame)

    if analysis == plan_mod.CONCENTRATION:
        high = frame[frame["high_plus"]].sort_values("exposure", ascending=False)
        total = float(high["exposure"].sum())
        top5 = float(high.head(5)["exposure"].sum())
        figures["concentration"] = {
            "top_n": 5,
            "top_n_exposure": round(top5, 2),
            "high_plus_exposure": round(total, 2),
            "top_n_share_pct": round(100.0 * top5 / total, 1) if total else 0.0,
            "obligors": int(len(high)),
        }
        # It carries a pack like every other reading. Without one the
        # concentration a multi-part question asked about ran, produced
        # figures, and then had nothing to write from — so the part of the
        # question it answered never reached the page.
        pack = ff.FactPack(
            scope="concentration",
            label=_slice_label(step), period=step.period,
            figures=figures, rows=_rows(high, step),
            provenance=["early_warning_borrower_month"],
            caveats=[ff._NOT_CALIBRATED])
        return _done(step, started, figures=figures, pack=pack,
                     rows=_rows(high, step), grain="population_month",
                     statement=f"early_warning_borrower_month[{step.period}] "
                               f"where high_plus, ordered by exposure")

    # POPULATION, RANKING and COMPARISON all read the same frame. The step
    # carries a fact pack too: the composer and the rubric both read packs,
    # and a population step that returned loose figures would leave the
    # answer to be led by whichever later step happened to produce one.
    where = ", ".join(f"{k}={v!r}" for k, v in (step.filters or {}).items())
    pack = _population_pack(step)
    found = _rows(frame, step)

    if step.analysis == plan_mod.RANKING and pack is not None \
            and pack.scope == "layer_population":
        # A layer ranking already has its pack: `layer_population` orders by
        # the layer's own score and carries the corroboration counts. Rewrapping
        # it as a bare ranking would throw both away and hand the composer a
        # list of names with nothing to say about why they are on it.
        found = list(pack.rows)[:max(1, step.limit)]
        pack = ff.FactPack(
            scope=pack.scope, label=pack.label, period=pack.period,
            figures={**dict(pack.figures), "named": len(found),
                     "ordered_by": step.order_by},
            rows=found, provenance=list(pack.provenance),
            caveats=list(pack.caveats))
    elif step.analysis == plan_mod.RANKING and pack is not None:
        # A ranking is about the NAMES, and until this existed it was not.
        #
        # The ranking step reuses the population frame, so it used to return
        # the population's own pack — and the answer that came back to "which
        # obligors are High or Very High?" was the portfolio's average score.
        # The names were in the rows the whole time; nothing was written from
        # them, because no pack said this reading was about them.
        pack = ff.FactPack(
            scope="ranking",
            label=pack.label, period=pack.period,
            figures={**dict(pack.figures), "named": len(found),
                     "ordered_by": step.order_by or "exposure"},
            rows=list(found),
            provenance=list(pack.provenance), caveats=list(pack.caveats))

    return _done(step, started,
                 figures=dict(pack.figures) if pack else figures,
                 rows=found, grain="population_month", pack=pack,
                 statement=f"early_warning_borrower_month[{step.period}]"
                           + (f" where {where}" if where else ""))


def _slice_label(step: plan_mod.Step) -> str:
    """The population a step read, said the way a sentence says it."""
    named = [str(v) for k, v in (step.filters or {}).items()
             if k not in ("high_plus",) and not isinstance(v, bool)]
    return ", ".join(named) if named else "the corporate portfolio"


def _population_pack(step: plan_mod.Step) -> ff.FactPack | None:
    """The fact pack for the slice this step read.

    A named slice is a group; the unfiltered book is the portfolio. Both go
    through the same pack builders the rest of the product already uses, so
    the answer this pipeline composes and the answer the screen composes are
    the same answer.
    """
    filters = dict(step.filters or {})
    try:
        if layers_mod.is_code(step.layer):
            # A layer question's population is the obligors that layer fired
            # for. Reading the portfolio pack here answered "which obligors
            # carry external signals" with the whole book's average score.
            rest = {k: v for k, v in filters.items()
                    if k not in layers_mod.ACTIVE_FIELDS}
            rest.pop(layers_mod.FIRING_COUNT_FIELD, None)
            return ff.layer_population(step.layer, step.period or None,
                                       only=rest or None,
                                       limit=max(1, step.limit))
        filters.pop("high_plus", None)
        if not filters:
            return ff.portfolio(step.period or None)
        column, value = next(iter(filters.items()))
        return ff.group(column, str(value), step.period or None)
    except Exception as failure:  # noqa: BLE001 - fall back to loose figures
        raise ExecutionError(
            f"Could not read the population for {step.period!r}: {failure}",
            code="no_data") from failure


def _dominant_signal(customer_id: str, period: str | None) -> str:
    obs = svc.signal_observations(customer_id, period)
    if obs is None or obs.empty:
        return ""
    return str(obs.sort_values("signal_score", ascending=False)
               .iloc[0]["signal_key"])


def _done(step: plan_mod.Step, started: float, *,
          figures: dict[str, Any] | None = None,
          rows: list[dict[str, Any]] | None = None,
          grain: str = "", statement: str = "",
          pack: ff.FactPack | None = None) -> Executed:
    found = list(rows or [])
    return Executed(
        step=step, rows=found, figures=dict(figures or {}),
        row_count=len(found), grain=grain, statement=statement, pack=pack,
        duration_ms=int((time.perf_counter() - started) * 1000),
        warnings=list(pack.caveats) if pack else [],
    )


#: Proof, for the tests: the only module-level data doors this executor has.
DATA_DOORS: tuple[str, ...] = (
    "backend.early_warning.wide", "backend.early_warning.v2_service",
    "backend.early_warning.facts")


__all__ = ["DATA_DOORS", "Executed", "ExecutionError", "run"]
