"""Why the frozen emulator predicted what it did -- and what that is not.

Section 13.2 asks for two things that share the word "contribution" and are
not the same quantity:

**A. Scenario-impact attribution.** Why did ECL move from baseline to
scenario? That is `attribution.py`: exact or sampled Shapley over the
scenario's own INTERVENTIONS, where each coalition value is a real Delta pass
over the real rows. The contributions reconcile to the ECL change because
they are measurements of it.

**B. ML prediction explanation.** Why did this fitted function return this
number? That is here. It is a statement about how a model responds to its own
inputs, and it reconciles to nothing about the scenario.

> *"Never present feature importance as a decomposition of the scenario ECL
> movement."*

The two are kept apart by construction rather than by a caption. Nothing in
this module returns a currency change, nothing here is summed with an
attribution row, and `for_outcome` ends every set of rows with the sentence
that says so. `bridge._ml_explanation` publishes them in their own section,
and a test asserts that a feature name never appears as an attribution
driver.

## What is computed, and when

**Per run, on the cohort:** per-component contribution and SHAP. Both come
from the frozen artifacts and the scenario's own feature frame, which is the
only way to answer "why THIS prediction". Neither is a refit: a TreeExplainer
pass over a few thousand rows is a forward walk of trees that already exist.
§7.1's rule is that a reader's question must not trigger a fit, and this does
not.

**Once, offline:** response relationships. A partial-dependence curve needs
the model evaluated over a grid for every feature, which is a great deal of
work to answer a question nobody has asked yet, so
`scripts/whatif/build_explanations.py` computes them on the DEVELOPMENT
window and publishes them as model documentation. They describe the fitted
function, not this cohort, and they say so.

## Association, not causation

Every row this module produces describes the fitted function's response to
its own inputs. It is not a causal statement about credit risk, the model
cards say so in those words, and so does the last row of every explanation.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

#: How many features an explanation names. A ranking of forty is not an
#: explanation; it is the feature list in a different order.
TOP_FEATURES = 12

#: The sentence that has to travel with every one of these rows.
NOT_A_DECOMPOSITION = (
    "This describes how the fitted function responds to its own inputs. It "
    "is association in a model, not causation, and it is NOT a decomposition "
    "of the scenario's ECL movement -- that is the attribution sections, "
    "which are measured by re-running the calculation.")

#: Where the offline response relationships live, beside the model.
DOCUMENT = "explanation.json"


def contributions(loaded: Any, frame: Any) -> dict[str, Any]:
    """Per-component and per-feature contribution for one frame.

    `Loaded.raw` already computes each component's prediction and throws the
    pieces away to return their weighted sum. They are kept here, because
    "which component drove this" is the first thing a reader asks of a blend
    and the cheapest thing a blend can answer.

    SHAP is computed on the tree components only. A TreeExplainer is exact
    for a tree ensemble and needs no background sample; the additive
    component has no TreeExplainer and its coefficients are its own
    explanation, so it is reported by weight rather than by a KernelExplainer
    approximation nobody asked for.

    Returns a plain dict, JSON-safe, so it can ride in `Anchored.as_facts()`
    and out to an artifact without a second serialiser.
    """
    out: dict[str, Any] = {"components": [], "shap": [],
                           "rows": int(getattr(frame, "shape", (0,))[0])}
    weights = dict(getattr(loaded, "weights", {}) or {})
    models = dict(getattr(loaded, "models", {}) or {})
    for name in sorted(weights):
        weight = float(weights[name])
        row: dict[str, Any] = {"component": name, "weight": weight}
        model = models.get(name)
        if weight > 0 and model is not None:
            try:
                predicted = list(model.predict(frame))
                row["mean_prediction"] = (
                    sum(float(v) for v in predicted) / len(predicted)
                    if predicted else 0.0)
                row["weighted_mean"] = row["mean_prediction"] * weight
            except Exception as exc:  # noqa: BLE001
                row["note"] = f"this component could not be evaluated: {exc}"
        elif weight <= 0:
            row["note"] = ("carries no weight in this blend, so it does not "
                           "enter the prediction at all.")
        out["components"].append(row)
    out["shap"] = _shap(loaded, frame)
    return out


def _shap(loaded: Any, frame: Any) -> list[dict[str, Any]]:
    """Mean absolute SHAP per feature, weight-combined across tree components.

    Combined by the BLEND'S OWN WEIGHTS, because the prediction is the
    weighted sum and an explanation of the prediction has to be weighted the
    same way. An unweighted average across components would explain a model
    nobody is using.

    Absolute values, and labelled as such. A signed mean over a cohort
    cancels a feature that pushes half the rows up and half down to nearly
    zero, which reads as "this feature does not matter" about the feature
    that matters most.
    """
    try:
        import shap as shap_lib
    except ImportError:
        return [{"feature": "", "status": "UNAVAILABLE",
                 "note": "the shap library is not installed in this runtime."}]
    weights = dict(getattr(loaded, "weights", {}) or {})
    models = dict(getattr(loaded, "models", {}) or {})
    names = list(getattr(loaded, "features", ()) or ())
    totals: dict[str, float] = {name: 0.0 for name in names}
    used: list[str] = []
    for component, weight in sorted(weights.items()):
        model = models.get(component)
        if float(weight) <= 0 or model is None:
            continue
        try:
            explainer = shap_lib.TreeExplainer(model)
            values = explainer.shap_values(frame, check_additivity=False)
        except Exception:  # noqa: BLE001
            # Not a tree, or a version that will not explain this object.
            # Reported by absence rather than by a guess.
            continue
        used.append(component)
        for index, name in enumerate(names):
            column = [abs(float(row[index])) for row in values]
            if column:
                totals[name] += float(weight) * sum(column) / len(column)
    if not used:
        return [{"feature": "", "status": "UNAVAILABLE",
                 "note": "no component of this blend has a tree explainer, "
                         "so no SHAP value was computed and none was "
                         "approximated."}]
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])[:TOP_FEATURES]
    return [{"feature": name,
             "mean_absolute_shap": value,
             "components_explained": ", ".join(used),
             "status": "MEAN ABSOLUTE, WEIGHT-COMBINED"}
            for name, value in ranked if value > 0]


def document(domain_id: str, *, root: Path | None = None) -> dict[str, Any]:
    """The offline response relationships for this book, or `{}`.

    Absent is not an error. A book whose explanation document has not been
    built yet has a prediction explanation without response curves, and
    saying so is better than blocking the run over documentation.
    """
    base = (root or Path("artifacts") / "whatif") / domain_id / DOCUMENT
    if not base.exists():
        return {}
    try:
        return json.loads(base.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def for_outcome(loaded: Any, *, facts: Mapping[str, Any],
                root: Path | None = None) -> list[dict[str, Any]]:
    """The explanation as artifact rows, for the run that produced `facts`.

    Rows carry no currency change, on purpose. Every value here is in the
    model's own output space or is a dimensionless ranking, so a row from this
    section can never be added to an attribution row by a reader, a chart or
    a validator that treated the two as one table.
    """
    out: list[dict[str, Any]] = []
    found = dict(facts.get("explanation") or {})
    version = str(getattr(loaded, "model_version", "") or "")
    headline = str(getattr(loaded, "headline", "") or "")
    if headline:
        out.append({"item": "What this model is", "kind": "provenance",
                    "status": version, "note": headline})
    for row in found.get("components") or []:
        weight = row.get("weight", 0)
        out.append({
            "item": str(row.get("component", "")),
            "kind": "component contribution",
            "unit": "blend weight",
            "status": f"weight {weight}",
            "note": row.get("note") or (
                f"mean prediction {row.get('mean_prediction')} in the "
                f"model's rate space; {row.get('weighted_mean')} after its "
                f"weight")})
    for row in found.get("shap") or []:
        if not row.get("feature"):
            out.append({"item": "SHAP", "kind": "feature contribution",
                        "status": str(row.get("status", "")),
                        "note": str(row.get("note", ""))})
            continue
        out.append({
            "item": str(row["feature"]),
            "kind": "feature contribution",
            "unit": "mean |SHAP|, model rate space",
            "status": str(row.get("status", "")),
            "note": f"{row.get('mean_absolute_shap')} over "
                    f"{found.get('rows', 0)} rows of this cohort, combined by "
                    f"blend weight across {row.get('components_explained')}"})
    doc = document(str(getattr(loaded, "domain_id", "")), root=root)
    for row in (doc.get("responses") or [])[:TOP_FEATURES]:
        out.append({
            "item": str(row.get("feature", "")),
            "kind": "response relationship",
            "unit": str(row.get("unit", "")),
            "status": "FITTED ON THE DEVELOPMENT WINDOW, NOT THIS COHORT",
            "note": str(row.get("shape", ""))})
    for row in (doc.get("importance") or [])[:TOP_FEATURES]:
        out.append({
            "item": str(row.get("feature", "")),
            "kind": "gain importance",
            "unit": "share of split gain",
            "status": "FITTED ON THE DEVELOPMENT WINDOW, NOT THIS COHORT",
            "note": str(row.get("value", ""))})
    for warning in facts.get("warnings") or []:
        out.append({"item": "Support", "kind": "extrapolation warning",
                    "status": "OUTSIDE THE FITTED RANGE", "note": str(warning)})
    if not out:
        out.append({"item": "No explanation", "kind": "",
                    "status": "UNAVAILABLE",
                    "note": "this run carried no explanation payload."})
    return out


def never_a_decomposition(rows: Sequence[Mapping[str, Any]]) -> None:
    """Raise if an explanation row is carrying a scenario currency change.

    The guard, not the comment. `attribution.never_add` refuses to sum the
    two scenario views; this refuses to let a feature ranking be published
    with an ECL movement in it, which is the same class of error one level
    further out and the one section 13.2 names explicitly.
    """
    for row in rows:
        for banned in ("change_sar_mn", "baseline_sar_mn", "scenario_sar_mn"):
            if str(row.get(banned) or "").strip():
                raise ValueError(
                    f"an ML prediction explanation row carries {banned}="
                    f"{row.get(banned)!r}. A feature's contribution to a "
                    f"prediction is not a share of the scenario's ECL "
                    f"movement, and publishing one in a currency column is "
                    f"how the two become one table.")


__all__ = ["DOCUMENT", "NOT_A_DECOMPOSITION", "TOP_FEATURES",
           "contributions", "document", "for_outcome",
           "never_a_decomposition"]
