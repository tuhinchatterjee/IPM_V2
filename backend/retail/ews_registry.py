"""Which Early Warning model is running, which one ran before, and what changed.

A model that cannot say what it replaced is not governed, it is just deployed.
This is the registry behind the Model Log: one record per version, each with
its configuration, its effective dates, the reason it was introduced, and its
measured performance.

Two things here are deliberately not shortcuts.

**The retired version is MEASURED, not remembered.** Version 2.0.0's figures
are not copied from an old run — they are recomputed on today's panel, over
the same facilities, the same months and the same outcomes as the active
version. That is possible because the versions differ in how the four layer
scores are COMBINED, not in the layers themselves: v2 weighted Bureau at a
flat rate regardless of the age of the observation, v3 decays it and hands the
released weight to the layers that still have something to say. Rescoring from
the stored layer columns reproduces v2 exactly rather than approximately, so
the comparison is like for like.

**Nothing is populated that cannot be computed.** Every metric on a version
record comes from `ews_performance` reading the published panel. Where a
metric cannot be produced — calibration against a score that is not a
probability, or a cohort with one outcome class — the record says so.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from backend.retail import ews_model as M
from backend.retail import ews_performance as P
from backend.retail import ews_score as S

ACTIVE = "3.0.0"
RETIRED = "retired"
CHALLENGER = "challenger"


@dataclass(frozen=True)
class Version:
    """One governed model version."""

    version_id: str
    model_version: str
    rulebook_version: str
    status: str
    effective_from: str
    effective_to: str
    development_sample: str
    validation_sample: str
    target: str
    horizon_months: int
    score_scale: str
    warning_threshold: float
    change_summary: str
    change_rationale: str
    bureau_treatment: str
    taxonomy_version: str
    #: How the version cuts a product below product level. Declared on the
    #: record rather than written into the comparison, so a third version
    #: says what IT does instead of inheriting a sentence about the second.
    segmentation: str
    created_by: str
    approved_by: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)


def _months() -> list[str]:
    try:
        return S.panel_months()
    except Exception:  # noqa: BLE001 - the registry still lists without a panel
        return []


def _window() -> tuple[str, str]:
    every = _months()
    return (every[0] if every else "", every[-1] if every else "")


def versions() -> tuple[Version, ...]:
    """The registry. Oldest first."""
    first, last = _window()
    half = every_half = len(_months()) // 2
    months = _months()
    dev_to = months[half - 1] if months and half else last
    return (
        Version(
            version_id="RET-EWS-MODEL-0002",
            model_version="2.0.0",
            rulebook_version="retail-ews-rulebook-1.0.0",
            status=RETIRED,
            effective_from=first,
            effective_to=dev_to,
            development_sample=f"{first} to {dev_to}",
            validation_sample=f"{dev_to} to {last}",
            target=P.TARGET_DEFINITION,
            horizon_months=P.HORIZON_MONTHS,
            score_scale="0-100, higher is worse",
            warning_threshold=float(M.SCALE.warning_cutoff),
            change_summary=(
                "First four-layer model. Behavioural, Affordability, Bureau "
                "and Facility combined on fixed product weights, with the "
                "Bureau layer carrying the same weight whatever the age of "
                "the observation behind it."),
            change_rationale=(
                "Replaced the six-layer, eleven-family rulebook with four "
                "layers and an explicit classifier / trigger / action "
                "structure."),
            bureau_treatment=(
                "Static. Bureau weighted at the product's base weight "
                "regardless of how many months since the last pull."),
            taxonomy_version="retail-subproduct-taxonomy-1.0.0",
            segmentation="Product and sub-product only.",
            created_by="Retail Credit Risk Analytics",
            notes=(
                "Retired by 3.0.0. Its figures below are recomputed on the "
                "current panel so the two versions are compared on the same "
                "facilities, months and outcomes.",)),
        Version(
            version_id="RET-EWS-MODEL-0003",
            model_version="3.0.0",
            rulebook_version="retail-ews-rulebook-1.0.0",
            status="active",
            effective_from=dev_to,
            effective_to="",
            development_sample=f"{first} to {dev_to}",
            validation_sample=f"{dev_to} to {last}",
            target=P.TARGET_DEFINITION,
            horizon_months=P.HORIZON_MONTHS,
            score_scale="0-100, higher is worse",
            warning_threshold=float(M.SCALE.warning_cutoff),
            change_summary=(
                "Bureau recency decay with weight redistribution; Salaried / "
                "Non-Salaried classification inside every product; the "
                "sub-product taxonomy renamed onto the Saudi-market-style "
                "ladder; effective layer weights stored per row."),
            change_rationale=(
                "The Bureau layer carried fifteen per cent of the score on "
                "an observation that could be two years old, so a stale "
                "external record counted as much as a fresh one. The weight "
                "now decays with the age of the pull and what it releases "
                "goes to the layers that still move every month."),
            bureau_treatment=(
                "W(age) = floor + (max - floor) x exp(-ln2 x age / half-life), "
                f"max {M.BUREAU_RECENCY.w_max:.0%}, floor "
                f"{M.BUREAU_RECENCY.w_floor:.0%}, half-life "
                f"{M.BUREAU_RECENCY.half_life_months:g} months. The released "
                "weight is redistributed across the dynamic layers in "
                "proportion to their base weights; the four always total one."),
            taxonomy_version=M.SUB_PRODUCT_TAXONOMY_VERSION,
            segmentation=("Salaried / Non-Salaried inside every product, read "
                          "from employment status, then sub-product."),
            created_by="Retail Credit Risk Analytics",
            notes=(
                "Active. Layer definitions, triggers and classifiers are "
                "unchanged from 2.0.0; what changed is how the four layers "
                "are weighted together.",)),
    )


def active() -> Version:
    return next(one for one in versions() if one.status == "active")


def get(model_version: str) -> Version | None:
    return next((one for one in versions()
                 if one.model_version == str(model_version)), None)


# ------------------------------------------------------------- config hashes

def config_hash(model_version: str) -> str:
    """A fingerprint of the configuration a version ran with.

    Over the parts that change the score: the layer weights, the severity
    bands, the cutoff, the hard triggers and the bureau treatment.
    """
    version = get(model_version)
    shape = {
        "model_version": model_version,
        "weights": {code: M.weights_for(code) for code in M.ALL_PRODUCTS},
        "severity_bands": [list(one) for one in M.SEVERITY_BANDS],
        "population_bands": [list(one) for one in M.POPULATION_BANDS],
        "cutoff": M.SCALE.warning_cutoff,
        "hard_triggers": [(h.key, h.floor_score) for h in M.HARD_TRIGGERS],
        "bureau": (version.bureau_treatment if version else ""),
        "taxonomy": (version.taxonomy_version if version else ""),
    }
    return hashlib.sha256(
        json.dumps(shape, sort_keys=True, default=str).encode()).hexdigest()[:16]


def data_manifest_hash() -> str:
    """A fingerprint of the panel the figures were measured over."""
    every = _months()
    shape = {"months": every, "panel_version": S.EWS_PANEL_VERSION,
             "domain": S.DOMAIN}
    return hashlib.sha256(
        json.dumps(shape, sort_keys=True).encode()).hexdigest()[:16]


# -------------------------------------------------------------- the rescoring

def _combine(parts: list[tuple[float, Any]], rows: int) -> Any:
    """The model's own roll-up, reused so a rescore is not a second formula."""
    import numpy as np

    remaining = np.ones(rows)
    for weight, score in parts:
        share = np.clip(float(weight) * np.nan_to_num(score) / 100.0, 0.0, 1.0)
        remaining = remaining * (1.0 - share)
    return 100.0 * (1.0 - remaining)


def rescore(panel: Any, model_version: str) -> Any:
    """The same observations, scored under one version's weighting.

    v3 is what the panel already carries. v2 differs only in weighting the
    Bureau layer statically, so its score is recomputed from the stored layer
    columns — exactly, not approximately.
    """
    import numpy as np

    if model_version == ACTIVE or not len(panel):
        return panel

    frame = panel.copy()
    rows = len(frame)
    product = frame["product_code"].astype(str).to_numpy()
    overall = np.zeros(rows)
    for code in M.ALL_PRODUCTS:
        mask = product == code
        if not mask.any():
            continue
        weights = M.weights_for(code)          # the static, v2 weighting
        # The same fixed reference the live scorer uses. Under v2 the weights
        # never move off their base, so this is the heaviest of them either
        # way; naming it the base heaviest keeps the two readable as one
        # arithmetic seen at two settings.
        heaviest = max(weights.values())
        blended = _combine(
            [(weights[layer.key] / heaviest,
              frame[layer.score_column].to_numpy(dtype=float))
             for layer in M.LAYERS if layer.score_column in frame],
            rows)
        overall = np.where(mask, blended, overall)

    # The hard-trigger floors are part of both versions and are reapplied the
    # same way, from the override the panel recorded.
    applied = frame.get("hard_trigger_applied")
    if applied is not None:
        for hard in M.HARD_TRIGGERS:
            hit = applied.astype(str).to_numpy() == hard.key
            overall = np.where(hit & (overall < hard.floor_score),
                               hard.floor_score, overall)

    frame["ews_score"] = np.round(np.clip(overall, M.SCALE.minimum,
                                          M.SCALE.maximum), 3)
    frame["ews_severity"] = [M.band_of(v) for v in frame["ews_score"]]
    return frame


#: Measured answers, held against the panel they were measured over. Running
#: the whole measurement twice per Model Log page load — once per version —
#: put twenty seconds in front of a reader for an answer that cannot change
#: until the panel is rebuilt.
_MEASURED: dict[tuple[str, str], dict[str, Any]] = {}
_PANEL: dict[str, Any] = {}


#: Comparisons, held like the measurements: rescoring the whole panel under
#: two versions is six seconds, and the answer is the same until the panel is
#: rebuilt.
_COMPARED: dict[tuple[str, str, str], dict[str, Any]] = {}


def forget() -> None:
    """Drop what is held. Called when the panel is rebuilt."""
    _MEASURED.clear()
    _PANEL.clear()
    _COMPARED.clear()


def _panel() -> Any:
    stamp = data_manifest_hash()
    held = _PANEL.get("stamp")
    if held != stamp:
        _PANEL.clear()
        _PANEL["stamp"] = stamp
        _PANEL["rows"] = P.observations()
    return _PANEL["rows"]


def performance(model_version: str = "") -> dict[str, Any]:
    """One version's measured performance over the published panel."""
    import copy

    which = str(model_version or ACTIVE)
    key = (which, data_manifest_hash())
    held = _MEASURED.get(key)
    if held is not None:
        return copy.deepcopy(held)
    panel = _panel()
    if not len(panel):
        return {"available": False,
                "because": "the panel holds too few months to observe an "
                           "outcome"}
    measured = P.measure(panel=rescore(panel, which), model_version=which)
    if len(_MEASURED) > 8:
        _MEASURED.clear()
    _MEASURED[key] = measured
    return copy.deepcopy(measured)


def _summary(measured: dict[str, Any]) -> dict[str, Any]:
    head = measured.get("headline") or {}
    stability = measured.get("stability") or {}
    lead = measured.get("lead_time") or {}
    hard = next((one for one in (measured.get("cohorts") or [])
                 if one.get("key") == "hard_trigger"), {})
    return {
        "ks": head.get("ks"), "gini": head.get("gini"), "auc": head.get("auc"),
        "pr_auc": head.get("pr_auc"),
        "precision": head.get("precision"), "recall": head.get("recall"),
        "f1": head.get("f1"), "lift_worst_decile": next(
            (one.get("lift") for one in
             ((next((c for c in (measured.get("cohorts") or [])
                     if c.get("key") == "clean"), {}) or {}).get("lift") or [])
             if one.get("decile") == 1), None),
        "alert_rate": head.get("alert_rate"),
        "false_positive_rate": head.get("false_positive_rate"),
        "psi": stability.get("psi_latest"),
        "lead_time_months": lead.get("median_months"),
        "hard_trigger_capture": (hard.get("threshold") or {}).get("recall"),
        "calibration": measured.get("calibration"),
    }


def record(model_version: str = "", *, with_performance: bool = True
           ) -> dict[str, Any]:
    """One version, as the Model Log shows it."""
    version = get(model_version or ACTIVE)
    if version is None:
        return {"available": False,
                "because": f"{model_version} is not in the registry."}
    out: dict[str, Any] = {
        "available": True,
        **{k: v for k, v in version.__dict__.items()},
        "notes": list(version.notes),
        "config_hash": config_hash(version.model_version),
        "data_manifest_hash": data_manifest_hash(),
        "weights": {code: M.weights_for(code) for code in M.ALL_PRODUCTS},
        "severity_bands": [{"from": low, "band": band}
                           for low, band in M.SEVERITY_BANDS],
        "hard_triggers": [{"key": h.key, "name": h.name,
                           "condition": h.condition,
                           "floor_score": h.floor_score, "band": h.band,
                           "because": h.because} for h in M.HARD_TRIGGERS],
        "bureau_recency": {
            "w_max": M.BUREAU_RECENCY.w_max,
            "w_floor": M.BUREAU_RECENCY.w_floor,
            "half_life_months": M.BUREAU_RECENCY.half_life_months,
            "formula": ("W(age) = floor + (max - floor) * "
                        "exp(-ln(2) * age / half_life)"),
            "basis": M.BUREAU_RECENCY.basis,
            "table": M.BUREAU_RECENCY.table(),
        } if version.model_version == ACTIVE else {
            "static": True,
            "statement": version.bureau_treatment,
        },
        "report_path": f"/api/v1/retail/ews/model-log/{version.model_version}"
                       "/report.docx",
    }
    if with_performance:
        measured = performance(version.model_version)
        out["performance"] = measured
        out["performance_summary"] = (_summary(measured)
                                      if measured.get("available") else {})
    return out


def log() -> dict[str, Any]:
    """The version table, §23."""
    rows = []
    for version in versions():
        measured = performance(version.model_version)
        rows.append({
            "version_id": version.version_id,
            "model_version": version.model_version,
            "rulebook_version": version.rulebook_version,
            "status": version.status,
            "effective_from": version.effective_from,
            "effective_to": version.effective_to,
            "development_sample": version.development_sample,
            "validation_sample": version.validation_sample,
            "score_scale": version.score_scale,
            "warning_threshold": version.warning_threshold,
            "change_summary": version.change_summary,
            "taxonomy_version": version.taxonomy_version,
            "config_hash": config_hash(version.model_version),
            "performance": (_summary(measured)
                            if measured.get("available") else {}),
            "performance_available": bool(measured.get("available")),
            "report_path": f"/api/v1/retail/ews/model-log/"
                           f"{version.model_version}/report.docx",
        })
    return {
        "available": True,
        "active_version": ACTIVE,
        "target_definition": P.TARGET_DEFINITION,
        "horizon_months": P.HORIZON_MONTHS,
        "calibration": P.CALIBRATION_STATEMENT,
        "data_manifest_hash": data_manifest_hash(),
        "months": _months(),
        "versions": rows,
        "cohorts": [{"key": c.key, "name": c.name, "meaning": c.meaning,
                     "caveat": c.caveat} for c in P.COHORTS],
        "disclaimer": M.DISCLAIMER,
    }


def predecessor(model_version: str) -> Version | None:
    """The version this one replaced, or None if it is the first."""
    every = versions()
    for index, one in enumerate(every):
        if one.model_version == str(model_version):
            return every[index - 1] if index else None
    return None


def compare(left: str, right: str = "") -> dict[str, Any]:
    """What changed between two versions, in configuration and in outcome.

    Called with one version, this reads "what changed AT this version": the
    right-hand side is the version asked for and the left-hand side is the one
    it replaced. Defaulting the other side to whichever version is active
    compared the active version with itself, and printed a table of a change
    against nothing — every configuration row identical, every metric moving
    by zero — which reads as a finding rather than as a missing comparison.
    """
    import copy

    if not right:
        earlier = predecessor(left)
        if earlier is None:
            return {"available": False,
                    "because": (f"{left} is the first version in the "
                                "registry, so there is nothing before it to "
                                "compare it with")}
        left, right = earlier.model_version, str(left)

    import numpy as np

    key = (str(left), str(right), data_manifest_hash())
    held = _COMPARED.get(key)
    if held is not None:
        return copy.deepcopy(held)

    one, two = get(left), get(right)
    if one is None or two is None:
        return {"available": False, "because": "unknown version"}
    if one.model_version == two.model_version:
        return {"available": False,
                "because": (f"{one.model_version} cannot be compared with "
                            "itself")}

    panel = _panel()
    if not len(panel):
        return {"available": False, "because": "no observations"}

    before = rescore(panel, one.model_version)
    after = rescore(panel, two.model_version)
    moved = (after["ews_score"].to_numpy(dtype=float)
             - before["ews_score"].to_numpy(dtype=float))
    changed_band = before["ews_severity"].to_numpy() != after["ews_severity"].to_numpy()
    exposure = panel.get("gross_carrying_amount_sar")
    exposure = (exposure.to_numpy(dtype=float) if exposure is not None
                else np.zeros(len(panel)))

    latest = panel["reporting_month"].max()
    here = panel["reporting_month"].to_numpy() == latest

    left_measured = P.measure(panel=before, model_version=one.model_version)
    right_measured = P.measure(panel=after, model_version=two.model_version)
    left_summary = _summary(left_measured) if left_measured.get("available") else {}
    right_summary = _summary(right_measured) if right_measured.get("available") else {}

    out = {
        "available": True,
        "left": one.model_version,
        "right": two.model_version,
        "configuration": [
            {"what": "Bureau treatment", "left": one.bureau_treatment,
             "right": two.bureau_treatment},
            {"what": "Sub-product taxonomy", "left": one.taxonomy_version,
             "right": two.taxonomy_version},
            {"what": "Classification", "left": one.segmentation,
             "right": two.segmentation},
            {"what": "Layers, triggers and classifiers",
             "left": f"{len(M.LAYERS)} layers, {len(M.all_triggers())} triggers",
             "right": f"{len(M.LAYERS)} layers, {len(M.all_triggers())} triggers"},
            {"what": "Severity thresholds",
             "left": str([list(b) for b in M.SEVERITY_BANDS]),
             "right": str([list(b) for b in M.SEVERITY_BANDS])},
            {"what": "Configuration hash",
             "left": config_hash(one.model_version),
             "right": config_hash(two.model_version)},
        ],
        "performance": {
            "left": left_summary, "right": right_summary,
            "change": {k: (None if left_summary.get(k) is None
                           or right_summary.get(k) is None
                           or not isinstance(right_summary.get(k), (int, float))
                           else round(float(right_summary[k])
                                      - float(left_summary[k]), 4))
                       for k in right_summary if k != "calibration"},
        },
        "population_impact": {
            "month": str(latest),
            # Not the newest month in the workspace. Both versions are measured
            # over the panel that HAS an outcome window, and the last
            # HORIZON_MONTHS month-ends do not yet, so the newest month the two
            # can be compared on is this one. Said here so a reader looking at
            # a later month in the workspace is not left to guess.
            "month_is": (
                f"the newest month with a full {P.HORIZON_MONTHS}-month "
                "outcome window, which is the population both versions are "
                "measured over"),
            "observations": int(here.sum()),
            "severity_changed": int(changed_band[here].sum()),
            "severity_changed_pct": round(
                float(changed_band[here].mean()) * 100, 2) if here.any() else 0.0,
            "exposure_severity_changed_sar": round(
                float(exposure[here & changed_band].sum()), 2),
            "exposure_severity_changed_pct": round(
                float(exposure[here & changed_band].sum())
                / float(exposure[here].sum()) * 100, 2)
                if exposure[here].sum() else 0.0,
            "score_moved_up": int((moved[here] > 0.001).sum()),
            "score_moved_down": int((moved[here] < -0.001).sum()),
            "mean_score_change": round(float(moved[here].mean()), 4)
                                 if here.any() else 0.0,
        },
        "disclaimer": M.DISCLAIMER,
    }
    if len(_COMPARED) > 8:
        _COMPARED.clear()
    _COMPARED[key] = out
    return copy.deepcopy(out)


__all__ = ["ACTIVE", "Version", "active", "compare", "config_hash",
           "data_manifest_hash", "get", "log", "performance", "record",
           "rescore", "versions"]
