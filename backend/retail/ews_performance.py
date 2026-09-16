"""Does the Early Warning Score actually rank the customers who go wrong?

Everything here is computed from the published Early Warning Score domain and
the outcomes that followed in it. Nothing is asserted, nothing is typed in,
and where the data cannot answer a question this says so instead of filling
the box.

The target
----------
A score is only as meaningful as the event it is scored against, so the event
is written down once, here, and every figure on the Model Log is measured
against it:

    A facility DETERIORATES within the outcome window if, in the next
    `HORIZON_MONTHS` month-ends, it enters 30+ days past due, enters default,
    or reaches IFRS 9 Stage 3 — having been in none of those states at the
    month it was scored.

"Having been in none of those states" is the part that matters. A facility
already ninety days down does not need an early warning, and a model measured
including those is measuring its own inputs. That is why performance is cut
by STARTING state rather than reported once:

    A  DPD = 0, not in default, no hard trigger   — the real question
    B  DPD 1-30                                    — already slipping
    C  DPD < 90, excluding terminal states         — broad pre-default
    D  hard-trigger population                     — operational capture

Cohort D is reported separately and labelled for what it is. A score that
floors a ninety-day facility at CRITICAL will "capture" it perfectly, and
calling that discrimination would be a lie told with a real number.

Calibration
-----------
Not reported. The Early Warning Score ranks and explains; it is not a fitted
probability, so a Brier score or an observed-to-expected ratio against it
would be arithmetic with no meaning. The Model Log says so in those words
rather than leaving an empty chart.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from backend.retail import ews_model as M
from backend.retail import ews_score as S

#: How far ahead the outcome is measured. Three month-ends: long enough for a
#: warning to be worth something, short enough that twenty months of panel
#: still leaves seventeen scoreable months.
HORIZON_MONTHS = 3

TARGET_DEFINITION = (
    "Enters 30+ days past due, enters default, or reaches IFRS 9 Stage 3 "
    f"within {HORIZON_MONTHS} month-ends of being scored, having been in none "
    "of those states at the scoring month."
)

CALIBRATION_STATEMENT = (
    "Not applicable — the Early Warning Score is a ranking score, not a "
    "calibrated probability of default. Calibration, Brier score and "
    "observed-to-expected are not reported because the score does not claim "
    "to be a probability."
)


@dataclass(frozen=True)
class Cohort:
    key: str
    name: str
    meaning: str
    caveat: str = ""


COHORTS: tuple[Cohort, ...] = (
    Cohort("clean", "Absolute clean (DPD = 0)",
           "Scored while fully up to date, not in default and with no hard "
           "trigger firing. The population an early warning is FOR."),
    Cohort("early_arrears", "Early arrears (DPD 1-30)",
           "Already missed something, not yet thirty days down."),
    Cohort("pre_default", "Broad pre-default (DPD < 90)",
           "Everything short of the terminal states."),
    Cohort("hard_trigger", "Hard-trigger population",
           "DPD 90+, in default, or IFRS 9 Stage 3 at the scoring month.",
           "Operational capture, not discrimination: the model floors these "
           "customers by rule, so a high capture rate here measures the "
           "override working, not the score ranking."),
)


# ------------------------------------------------------------ the arithmetic

def _roc(scores: Any, events: Any) -> dict[str, Any]:
    """ROC, KS and the gains curve, computed once over sorted scores."""
    import numpy as np

    order = np.argsort(-scores, kind="mergesort")
    hit = events[order].astype(float)
    positives, negatives = float(hit.sum()), float((1 - hit).sum())
    if positives == 0 or negatives == 0:
        return {"available": False,
                "because": "the window holds only one outcome class"}

    tpr = np.concatenate([[0.0], np.cumsum(hit) / positives])
    fpr = np.concatenate([[0.0], np.cumsum(1 - hit) / negatives])
    auc = float(np.trapezoid(tpr, fpr))
    ks_at = int(np.argmax(tpr - fpr))
    share = np.arange(len(tpr)) / max(len(tpr) - 1, 1)

    # Precision-recall, over the same ordering.
    caught = np.cumsum(hit)
    seen = np.arange(1, len(hit) + 1)
    precision = caught / seen
    recall = caught / positives
    pr_auc = float(np.trapezoid(precision, recall))

    points = np.linspace(0, len(tpr) - 1, num=min(40, len(tpr))).astype(int)

    # GINI IS DERIVED FROM THE AUC AS PUBLISHED, NOT FROM THE ONE BEHIND IT.
    #
    # These were rounded independently off the full-precision AUC, so the two
    # figures on screen did not satisfy the identity that relates them. A
    # reader who doubles the published 0.5825 and subtracts one gets 0.1650,
    # and the panel beside it says 0.1649. Both are correctly rounded and the
    # pair is still wrong, because the only AUC a reader has is the one they
    # can see.
    #
    # Whose figures reconcile matters more here than a digit of precision that
    # is never displayed: the discarded difference is below the fourth decimal
    # place, and the thing it buys is that the arithmetic checks out.
    #
    # It is a latent defect rather than a new one — it needed an AUC that
    # rounds across the boundary, and the retail book only produced one after
    # the card cohort's calibration changed.
    published_auc = round(auc, 4)
    return {
        "available": True,
        "auc": published_auc,
        "gini": round(2 * published_auc - 1, 4),
        "ks": round(float(np.max(tpr - fpr)), 4),
        "ks_at_share": round(float(share[ks_at]), 4),
        "pr_auc": round(pr_auc, 4),
        "base_rate": round(positives / (positives + negatives), 6),
        "roc": [{"fpr": round(float(fpr[i]), 4), "tpr": round(float(tpr[i]), 4)}
                for i in points],
        "gains": [{"share": round(float(share[i]), 4),
                   "captured": round(float(tpr[i]), 4)} for i in points],
        "pr": [{"recall": round(float(recall[min(i, len(recall) - 1)]), 4),
                "precision": round(float(precision[min(i, len(precision) - 1)]), 4)}
               for i in points[1:]],
    }


#: What a decile table may and may not say when the score has heavy ties.
LIFT_TIE_NOTE = (
    "Most of the book scores exactly zero: nothing has fired on it, which is "
    "the ordinary state of a performing facility. A decile boundary drawn "
    "inside that block does not separate anybody, so every observation on the "
    "same score is given the outcome rate of all of them together. Deciles "
    "that fall wholly inside one score therefore read the same, and that is "
    "the honest reading: the score does not rank within a tie, and a table "
    "that showed them differing would be reporting the order the rows "
    "happened to arrive in.")


def _lift(scores: Any, events: Any, deciles: int = 10) -> list[dict[str, Any]]:
    """Event rate by score decile, worst-scoring decile first.

    Ties are resolved before the cut rather than after it. Sixty per cent of
    the panel sits on exactly zero, so deciles five to ten fall inside a
    single score; cutting the sorted array there and reporting each block's
    own rate produces six different numbers out of one undifferentiated
    population, and the differences are the row order, not the model.
    """
    import numpy as np

    order = np.argsort(-scores, kind="mergesort")
    hit = events[order].astype(float)
    ranked = scores[order].astype(float)
    base = float(hit.mean()) if len(hit) else 0.0

    # Every observation carries the outcome rate of everyone on its own score.
    if len(ranked):
        groups, first = np.unique(ranked, return_inverse=True)
        totals = np.bincount(first, weights=hit, minlength=len(groups))
        counts = np.bincount(first, minlength=len(groups))
        shared = (totals / np.maximum(counts, 1))[first]
    else:
        shared = hit

    out = []
    edges = np.linspace(0, len(hit), deciles + 1).astype(int)
    for index in range(deciles):
        lo, hi = edges[index], edges[index + 1]
        block, raw = shared[lo:hi], hit[lo:hi]
        if not len(block):
            continue
        rate = float(block.mean())
        span = ranked[lo:hi]
        out.append({
            "decile": index + 1,
            "customers": int(len(block)),
            "events": int(raw.sum()),
            "score_from": round(float(span.max()), 3),
            "score_to": round(float(span.min()), 3),
            # True when the whole decile sits on one score, so it is not a
            # rank at all — it is a slice of a tie.
            "within_one_score": bool(span.max() == span.min()),
            "event_rate": round(rate, 6),
            "lift": round(rate / base, 4) if base else None,
        })
    return out


def _at_threshold(scores: Any, events: Any, cutoff: float) -> dict[str, Any]:
    """The confusion matrix at the warning cutoff, and what it implies."""
    import numpy as np

    flagged = scores >= cutoff
    tp = int(np.sum(flagged & (events == 1)))
    fp = int(np.sum(flagged & (events == 0)))
    fn = int(np.sum(~flagged & (events == 1)))
    tn = int(np.sum(~flagged & (events == 0)))
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    specificity = tn / (tn + fp) if (tn + fp) else 0.0
    return {
        "cutoff": cutoff,
        "true_positive": tp, "false_positive": fp,
        "false_negative": fn, "true_negative": tn,
        "alert_rate": round(float(flagged.mean()), 6) if len(flagged) else 0.0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(2 * precision * recall / (precision + recall), 4)
              if (precision + recall) else 0.0,
        "balanced_accuracy": round((recall + specificity) / 2, 4),
        "false_positive_rate": round(fp / (fp + tn), 4) if (fp + tn) else 0.0,
        "false_negative_rate": round(fn / (fn + tp), 4) if (fn + tp) else 0.0,
    }


def _psi(expected: Any, actual: Any, bands: int = 10) -> float | None:
    """Population stability between two score distributions."""
    import numpy as np

    if not len(expected) or not len(actual):
        return None
    edges = np.linspace(0.0, 100.0, bands + 1)
    e = np.histogram(expected, bins=edges)[0] / len(expected)
    a = np.histogram(actual, bins=edges)[0] / len(actual)
    keep = (e > 0) & (a > 0)
    if not keep.any():
        return None
    return round(float(np.sum((a[keep] - e[keep]) * np.log(a[keep] / e[keep]))), 4)


# ----------------------------------------------------------- the panel reads

def _terminal(frame: Any) -> Any:
    """Rows in a state an early warning is too late for."""
    import numpy as np
    import pandas as pd

    dpd = pd.to_numeric(frame.get("dpd"), errors="coerce").fillna(0.0)
    stage = pd.to_numeric(frame.get("ifrs9_stage"), errors="coerce").fillna(0)
    default = frame.get("current_default_flag")
    default = (default.fillna(False).astype(bool)
               if default is not None else pd.Series(False, index=frame.index))
    return np.asarray((dpd >= 90) | (stage >= 3) | default)


def _deteriorated(frame: Any) -> Any:
    """Rows that have gone wrong by this month's standard."""
    import numpy as np
    import pandas as pd

    dpd = pd.to_numeric(frame.get("dpd"), errors="coerce").fillna(0.0)
    stage = pd.to_numeric(frame.get("ifrs9_stage"), errors="coerce").fillna(0)
    default = frame.get("current_default_flag")
    default = (default.fillna(False).astype(bool)
               if default is not None else pd.Series(False, index=frame.index))
    return np.asarray((dpd >= 30) | (stage >= 3) | default)


def observations(months: list[str] | None = None) -> Any:
    """One row per facility per scoreable month, with the outcome that followed.

    A month is scoreable when `HORIZON_MONTHS` further months exist to observe
    it in. The last three months of the panel therefore have no outcome and are
    excluded rather than counted as non-events, which would understate every
    event rate in the report.
    """
    import numpy as np
    import pandas as pd

    every = months or S.panel_months()
    if len(every) <= HORIZON_MONTHS:
        return pd.DataFrame()

    read = {month: S.read(month) for month in every}
    future_bad: dict[str, dict[str, bool]] = {}
    for month in every:
        frame = read[month]
        future_bad[month] = dict(zip(frame["facility_id"].astype(str),
                                     _deteriorated(frame)))

    out = []
    for index, month in enumerate(every[:-HORIZON_MONTHS]):
        frame = read[month]
        ids = frame["facility_id"].astype(str).to_numpy()
        already = _deteriorated(frame)
        terminal = _terminal(frame)
        dpd = pd.to_numeric(frame.get("dpd"), errors="coerce").fillna(0.0).to_numpy()

        after = np.zeros(len(frame), dtype=bool)
        for ahead in every[index + 1:index + 1 + HORIZON_MONTHS]:
            seen = future_bad[ahead]
            after |= np.array([bool(seen.get(one, False)) for one in ids])

        block = pd.DataFrame({
            "reporting_month": month,
            "facility_id": ids,
            "customer_id": frame["customer_id"].astype(str).to_numpy(),
            "product_code": frame["product_code"].astype(str).to_numpy(),
            "classification": (frame["classification"].astype(str).to_numpy()
                               if "classification" in frame else "UNCLASSIFIED"),
            "sub_product": (frame["sub_product"].astype(str).to_numpy()
                            if "sub_product" in frame else ""),
            "ews_score": pd.to_numeric(frame["ews_score"],
                                       errors="coerce").fillna(0.0).to_numpy(),
            "ews_severity": frame["ews_severity"].astype(str).to_numpy(),
            # Carried so a PRIOR model version can be measured on exactly the
            # same observations: the layers are the version's inputs, and only
            # the weights that combine them changed.
            **{layer.score_column: pd.to_numeric(
                frame[layer.score_column], errors="coerce").fillna(0.0).to_numpy()
               for layer in M.LAYERS if layer.score_column in frame},
            "bureau_recency_months": pd.to_numeric(
                frame.get("bureau_recency_months"),
                errors="coerce").to_numpy(dtype=float)
                if "bureau_recency_months" in frame else np.nan,
            "hard_trigger_applied": (
                frame["hard_trigger_applied"].astype(str).to_numpy()
                if "hard_trigger_applied" in frame else ""),
            "gross_carrying_amount_sar": pd.to_numeric(
                frame.get("gross_carrying_amount_sar"),
                errors="coerce").fillna(0.0).to_numpy()
                if "gross_carrying_amount_sar" in frame else 0.0,
            "dpd": dpd,
            "already_bad": already,
            "terminal": terminal,
            # The event: went wrong in the window, having been fine when scored.
            "event": np.where(already, False, after),
            "hard_trigger": (frame["hard_trigger_applied"].astype(str).to_numpy()
                             != "") if "hard_trigger_applied" in frame
                            else np.zeros(len(frame), dtype=bool),
        })
        out.append(block)
    return pd.concat(out, ignore_index=True) if out else pd.DataFrame()


def _cohort_rows(panel: Any, cohort: str) -> Any:
    if cohort == "clean":
        return panel[(panel["dpd"] == 0) & (~panel["terminal"])
                     & (~panel["hard_trigger"])]
    if cohort == "early_arrears":
        return panel[(panel["dpd"] >= 1) & (panel["dpd"] <= 30)
                     & (~panel["terminal"])]
    if cohort == "pre_default":
        return panel[(panel["dpd"] < 90) & (~panel["terminal"])]
    if cohort == "hard_trigger":
        return panel[panel["terminal"] | panel["hard_trigger"]]
    return panel


def _measure(rows: Any, *, cutoff: float) -> dict[str, Any]:
    import numpy as np

    if not len(rows):
        return {"available": False, "because": "no observations in this cut",
                "observations": 0}
    scores = rows["ews_score"].to_numpy(dtype=float)
    events = rows["event"].to_numpy().astype(int)
    if events.sum() == 0 or events.sum() == len(events):
        return {"available": False,
                "because": ("every observation in this cut has the same "
                            "outcome, so discrimination cannot be measured"),
                "observations": int(len(rows)),
                "events": int(events.sum())}

    measured = _roc(scores, events)
    measured.update({
        "observations": int(len(rows)),
        "events": int(events.sum()),
        "event_rate": round(float(events.mean()), 6),
        "threshold": _at_threshold(scores, events, cutoff),
        "lift": _lift(scores, events),
    })
    if any(row.get("within_one_score") for row in measured["lift"]):
        measured["lift_note"] = LIFT_TIE_NOTE
    return measured


def _lead_time(panel: Any, *, cutoff: float) -> dict[str, Any]:
    """How many months of warning the score gave before things went wrong.

    Measured per facility: the first month the score crossed the cutoff, and
    the month it first deteriorated. Facilities that were warned only in the
    same month they went wrong count as zero months of warning, not as a miss,
    and facilities never warned are counted as misses rather than dropped.
    """
    import numpy as np
    import pandas as pd

    if not len(panel):
        return {"available": False, "because": "no observations"}

    months = sorted(panel["reporting_month"].unique())
    order = {month: index for index, month in enumerate(months)}
    frame = panel.copy()
    frame["index"] = frame["reporting_month"].map(order)

    went_wrong = frame[frame["event"]].groupby("facility_id")["index"].min()
    warned = frame[frame["ews_score"] >= cutoff].groupby(
        "facility_id")["index"].min()
    joined = pd.DataFrame({"wrong": went_wrong}).join(
        pd.DataFrame({"warned": warned}), how="left")
    if not len(joined):
        return {"available": False, "because": "nothing deteriorated"}

    lead = (joined["wrong"] - joined["warned"]).where(
        joined["warned"].notna() & (joined["warned"] <= joined["wrong"]))
    caught = lead.notna()
    values = lead[caught].to_numpy(dtype=float)
    return {
        "available": True,
        "facilities_that_deteriorated": int(len(joined)),
        "warned_before_or_with": int(caught.sum()),
        "never_warned_in_time": int((~caught).sum()),
        "mean_months": round(float(np.mean(values)), 2) if len(values) else None,
        "median_months": round(float(np.median(values)), 2) if len(values) else None,
        "at_least_1_month_early_pct": round(
            float((values >= 1).mean()) * 100, 2) if len(values) else 0.0,
        "at_least_2_months_early_pct": round(
            float((values >= 2).mean()) * 100, 2) if len(values) else 0.0,
        "distribution": [
            {"months_early": int(k), "facilities": int(v)}
            for k, v in sorted(pd.Series(values).astype(int)
                               .value_counts().items())],
    }


def _stability(panel: Any, *, cutoff: float) -> dict[str, Any]:
    """Whether the score distribution and the alert rate are holding still."""
    import numpy as np

    months = sorted(panel["reporting_month"].unique())
    if len(months) < 2:
        return {"available": False, "because": "one month cannot drift"}
    first = panel[panel["reporting_month"] == months[0]]["ews_score"].to_numpy()

    series, severities = [], []
    for month in months:
        here = panel[panel["reporting_month"] == month]
        scores = here["ews_score"].to_numpy()
        series.append({
            "month": month,
            "psi_vs_first": _psi(first, scores),
            "alert_rate": round(float((scores >= cutoff).mean()), 6),
            "mean_score": round(float(np.mean(scores)), 3),
            "observations": int(len(here)),
        })
        counts = here["ews_severity"].value_counts(normalize=True)
        severities.append({"month": month,
                           **{band: round(float(counts.get(band, 0.0)), 4)
                              for _, band in M.SEVERITY_BANDS}})
    latest = series[-1]["psi_vs_first"]
    return {
        "available": True,
        "baseline_month": months[0],
        "psi_latest": latest,
        "reading": ("stable" if latest is not None and latest < 0.1 else
                    "some shift" if latest is not None and latest < 0.25 else
                    "material shift" if latest is not None else "not measured"),
        "series": series,
        "severity_mix": severities,
        "bands": "PSI below 0.10 stable, 0.10-0.25 some shift, above 0.25 material.",
    }


def _by(panel: Any, column: str, *, cutoff: float,
        labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
    out = []
    for value in sorted(panel[column].dropna().unique()):
        rows = panel[panel[column] == value]
        measured = _measure(rows, cutoff=cutoff)
        out.append({
            "key": str(value),
            "label": (labels or {}).get(str(value), str(value)),
            "observations": measured.get("observations", 0),
            "events": measured.get("events", 0),
            "event_rate": measured.get("event_rate"),
            "auc": measured.get("auc"),
            "gini": measured.get("gini"),
            "ks": measured.get("ks"),
            "available": measured.get("available", False),
            "because": measured.get("because", ""),
        })
    return out


def measure(months: list[str] | None = None, panel: Any = None,
            *, model_version: str = "") -> dict[str, Any]:
    """Everything the Model Log reports, measured over the published panel.

    `panel` lets a caller hand in the same observations rescored under a
    different model version, so two versions are compared on identical
    facilities, months and outcomes rather than on two different books.
    """
    cutoff = float(M.SCALE.warning_cutoff)
    panel = observations(months) if panel is None else panel
    if not len(panel):
        return {"available": False,
                "because": (f"the panel holds too few months to observe a "
                            f"{HORIZON_MONTHS}-month outcome")}

    scored_months = sorted(panel["reporting_month"].unique())
    cohorts = []
    for cohort in COHORTS:
        rows = _cohort_rows(panel, cohort.key)
        measured = _measure(rows, cutoff=cutoff)
        meaningful = cohort.key != "hard_trigger"
        if not meaningful and measured.get("available"):
            # These facilities are already in the state the model exists to
            # anticipate, so almost none of them can "deteriorate" again
            # inside the window and a rank statistic over them measures
            # nothing. Reporting an AUC here — it comes out near zero — would
            # be a real number that misleads. What IS meaningful is whether
            # the model is flagging them at all, which is the override
            # working, so that is what is reported and it is named as capture.
            flagged = rows["ews_score"].to_numpy(dtype=float) >= cutoff
            measured = {
                "available": True,
                "observations": int(len(rows)),
                "events": int(rows["event"].sum()),
                "discrimination_reported": False,
                "why_no_discrimination": (
                    "These facilities are already 90+ days past due, in "
                    "default or in Stage 3 when scored. The outcome the "
                    "model is measured against cannot happen to them again "
                    "inside the window, so ROC, Gini and KS over this cohort "
                    "would be arithmetic without meaning and are not shown."),
                "capture": {
                    "flagged": int(flagged.sum()),
                    "capture_rate": round(float(flagged.mean()), 4)
                                    if len(flagged) else 0.0,
                    "at_critical": int(
                        (rows["ews_severity"].to_numpy() == "CRITICAL").sum()),
                    "at_critical_rate": round(float(
                        (rows["ews_severity"].to_numpy() == "CRITICAL").mean()), 4)
                        if len(rows) else 0.0,
                    "meaning": ("Operational capture: the share of the "
                                "already-bad population the score flags. It "
                                "measures the hard-trigger overrides firing, "
                                "not the score ranking anything."),
                },
            }
        cohorts.append({
            "key": cohort.key, "name": cohort.name, "meaning": cohort.meaning,
            "caveat": cohort.caveat,
            "discrimination_meaningful": meaningful,
            **measured,
        })

    headline = next((one for one in cohorts if one["key"] == "clean"), None)
    product_labels = {code: code.replace("_", " ").title()
                      for code in M.ALL_PRODUCTS}
    return {
        "available": True,
        "model_version": model_version or M.EWS_MODEL_VERSION,
        "panel_version": S.EWS_PANEL_VERSION,
        "target_definition": TARGET_DEFINITION,
        "horizon_months": HORIZON_MONTHS,
        "warning_cutoff": cutoff,
        "scored_months": scored_months,
        "observations": int(len(panel)),
        "events": int(panel["event"].sum()),
        "calibration": CALIBRATION_STATEMENT,
        "headline": {
            "cohort": "clean",
            "auc": (headline or {}).get("auc"),
            "gini": (headline or {}).get("gini"),
            "ks": (headline or {}).get("ks"),
            "pr_auc": (headline or {}).get("pr_auc"),
            "precision": ((headline or {}).get("threshold") or {}).get("precision"),
            "recall": ((headline or {}).get("threshold") or {}).get("recall"),
            "f1": ((headline or {}).get("threshold") or {}).get("f1"),
            "alert_rate": ((headline or {}).get("threshold") or {}).get("alert_rate"),
            "false_positive_rate": ((headline or {}).get("threshold") or {})
                                   .get("false_positive_rate"),
        },
        "cohorts": cohorts,
        "by_product": _by(_cohort_rows(panel, "pre_default"), "product_code",
                          cutoff=cutoff, labels=product_labels),
        "by_classification": _by(_cohort_rows(panel, "pre_default"),
                                 "classification", cutoff=cutoff,
                                 labels=dict(M.CLASSIFICATION_LABELS)),
        "by_sub_product": _by(_cohort_rows(panel, "pre_default"), "sub_product",
                              cutoff=cutoff,
                              labels=dict(M.SUB_PRODUCT_LABELS)),
        "stability": _stability(panel, cutoff=cutoff),
        "lead_time": _lead_time(_cohort_rows(panel, "pre_default"),
                                cutoff=cutoff),
        "severity_event_rates": [
            {"band": band,
             "observations": int(len(panel[panel["ews_severity"] == band])),
             "events": int(panel[panel["ews_severity"] == band]["event"].sum()),
             "event_rate": round(float(
                 panel[panel["ews_severity"] == band]["event"].mean()), 6)
                 if len(panel[panel["ews_severity"] == band]) else None}
            for _, band in M.SEVERITY_BANDS],
        "score_distribution": [
            {"band": f"{low:g}-{low + 10:g}",
             "events": int(panel[(panel["ews_score"] >= low)
                                 & (panel["ews_score"] < low + 10)]["event"].sum()),
             "non_events": int(len(panel[(panel["ews_score"] >= low)
                                         & (panel["ews_score"] < low + 10)])
                               - panel[(panel["ews_score"] >= low)
                                       & (panel["ews_score"] < low + 10)]["event"].sum())}
            for low in range(0, 100, 10)],
        "disclaimer": M.DISCLAIMER,
    }


__all__ = ["CALIBRATION_STATEMENT", "COHORTS", "HORIZON_MONTHS",
           "TARGET_DEFINITION", "measure", "observations"]
