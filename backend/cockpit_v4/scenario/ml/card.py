"""The model card, and the frozen artifacts it describes.

Section 11.7 lists what a card must contain and the list is long on purpose:
provenance, target, features, exclusions, split dates, row and entity and
period counts, preprocessing, component settings, the ACTUAL weights,
metrics, subgroup errors, support limits, library versions and artifact
hashes. Every one of those is a thing somebody has asked about a model after
the fact and been unable to find out.

Two rules this module follows without exception:

**A failed gate is written as FAILED, with its measured value.** Not omitted,
not rounded to the threshold, not described as "close to". The gates were
predeclared in `ML_ACCEPTANCE_TARGETS.md` before any of this ran, and a card
that softened one would make the whole exercise decorative.

**Nothing here claims bank validation.** The card says, in its first
paragraph and again at the end, that the target was produced by
`reference_ecl.py` on a generated book, and that agreement with a bank's ECL
engine is not established and was not tested. That sentence is the most
important one in the document.

`freeze()` writes the artifacts and hashes them, so a card and the model it
describes can be checked against each other later.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from backend.cockpit_v4.scenario import ml
from backend.cockpit_v4.scenario.ml import blend as bl
from backend.cockpit_v4.scenario.ml import features as ft
from backend.cockpit_v4.scenario.ml import train as tr


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze(result: Any, feature_names: Sequence[str], out_dir: Path
           ) -> dict[str, str]:
    """Write the components and the blend, and return their hashes.

    Each component is saved in its own library's format, and the blend is
    JSON -- weights, feature order, target, denominator and model version.
    The feature ORDER is part of the artifact because a model fed the same
    columns in a different order is a different model with no error message.
    """
    import pickle

    out_dir.mkdir(parents=True, exist_ok=True)
    hashes: dict[str, str] = {}
    for name, fitted in result.components.items():
        target = out_dir / f"{name}.pkl"
        target.write_bytes(pickle.dumps(fitted.model))
        hashes[name] = digest(target)

    manifest = out_dir / "blend.json"
    manifest.write_text(json.dumps({
        "model_version": result.model_version,
        "domain_id": result.domain_id,
        "release_id": result.release_id,
        "target": ft.TARGET,
        "denominator": ft.DENOMINATOR,
        "features": list(feature_names),
        "categorical": sorted(set(feature_names) & ft.CATEGORICAL),
        "weights": result.blended.by_name,
        "headline": result.blended.headline,
        "component_hashes": hashes,
        "libraries": result.libraries,
        "seeds": {c: f.seed for c, f in result.components.items()},
        "train_periods": list(result.assignment.train),
        "validate_periods": list(result.assignment.validate),
        "test_periods": list(result.assignment.test),
        "embargoed_periods": list(result.assignment.embargoed),
        "gates": result.gates,
        "origin": "SYNTHETIC_DEMO",
    }, indent=2, sort_keys=True), encoding="utf-8")
    hashes["blend"] = digest(manifest)
    return hashes


def _gate_table(result: Any) -> list[str]:
    lines = ["| Gate | What | Threshold | Measured | Outcome |",
             "|---|---|---|---|---|"]
    for name, gate in sorted(result.gates.items()):
        mark = "PASSED" if gate["passed"] else "**FAILED**"
        lines.append(
            f"| {name} | {gate['what']} | {gate['threshold']:.3f} | "
            f"{gate['measured']:.4f} | {mark} |")
    return lines


def markdown(result: Any) -> str:
    """`MODEL_CARD_*.md`, with everything section 11.7 asks for."""
    book = result.domain_id.title()
    counts = result.counts
    blended: bl.Blend = result.blended
    lines: list[str] = [
        f"# Model card — {book} ECL emulator",
        "",
        f"`{result.model_version}` · trained on `{result.release_id}`",
        "",
        "> **This model was trained on a generated book.** Its target is "
        "the declared ECL rate produced by "
        "`backend/cockpit_v4/scenario/reference_ecl.py`, a calculator "
        "written for this demonstration. Passing every gate below "
        "establishes that an emulator can learn that calculator on that "
        "book. **It does not establish agreement with any bank's ECL "
        "engine**, which is not available here and was not tested.",
        "",
        "## Outcome",
        "",
    ]
    if result.passed:
        lines += ["Every predeclared gate passed.", ""]
    else:
        lines += [
            f"**{len(result.failures())} predeclared gate(s) FAILED.** They "
            f"are reported here as measured, the thresholds in "
            f"`ML_ACCEPTANCE_TARGETS.md` are unchanged, and Method 2 reports "
            f"its limitation to the reader rather than returning a number "
            f"that looks like the other methods'.",
            "",
        ]
        lines += [f"* {failure}" for failure in result.failures()] + [""]

    lines += _gate_table(result)
    lines += [
        "",
        "Thresholds come from `docs/whatif/ML_ACCEPTANCE_TARGETS.md`, which "
        "was committed **before** this model was fitted and before the test "
        "split was read.",
        "",
        "## The declared reference model",
        "",
        "| Model | Test WAPE | Test bias |",
        "|---|---|---|",
        f"| Blend | {result.metrics['test_wape']:.4f} | "
        f"{result.metrics['test_bias']:+.4f} |",
        f"| `{ml.NAIVE_PRODUCT}` (ead × pd × lgd) | "
        f"{result.reference.get('wape', 0.0):.4f} | "
        f"{result.reference.get('bias', 0.0):+.4f} |",
        "",
    ]
    better = result.metrics["test_wape"] < result.reference.get("wape", 1e9)
    # A fit that landed on one component produced a single model, and every
    # sentence about it has to say so. Calling it a blend because three were
    # offered would describe the intention rather than the result.
    noun = "single model" if blended.is_single_model else "blend"
    lines += [
        (f"The {noun} beats the naive product on the test split."
         if better else
         f"**The {noun} does not beat the naive product on the test "
         f"split.** That is reported rather than buried: the reference "
         f"model exists so that 'better than nothing' is never the "
         f"standard."),
        "",
        ("## The weight fit, and what it produced"
         if blended.is_single_model else "## The blend"),
        "",
        blended.headline,
        "",
        "| Component | Weight | Material | Library | Seed | Alone (OOF MSE) |",
        "|---|---|---|---|---|---|",
    ]
    for component, weight in blended.by_name.items():
        fitted = result.components[component]
        lines.append(
            f"| {component} | {weight:.4f} | "
            f"{'yes' if weight >= ml.MATERIAL_WEIGHT else 'no'} | "
            f"{fitted.library_version or 'n/a'} | {fitted.seed} | "
            f"{blended.single_component_errors.get(component, 0.0):.6f} |")
    lines += [
        "",
        f"Weights are the exact non-negative, sum-to-one solution over the "
        f"simplex, fitted on {blended.observations:,} **out-of-fold** "
        f"predictions — predictions each component made for periods it had "
        f"not trained on. Solved by enumerating the faces of the simplex "
        f"rather than by an iterative optimiser, so the weights do not "
        f"depend on a library version.",
        "",
        (("The fit put every unit of weight on one component, so nothing "
          "was blended. The comparison below is that component against the "
          "two the optimiser set aside, on the same out-of-fold rows."
          if blended.is_single_model else
          "Blending improved on every single component.")
         if bl.beats_every_component(blended)
         else "**Blending did not improve on the best single component** on "
              "the out-of-fold rows. Reported as measured."),
        "",
        "## The split",
        "",
        result.assignment.describe(),
        "",
        "| | Periods | Rows |",
        "|---|---|---|",
        f"| Train | {counts.get('train_periods', 0)} | |",
        f"| Validate | {counts.get('validate_periods', 0)} | |",
        f"| Development (train + validate) | "
        f"{counts.get('train_periods', 0) + counts.get('validate_periods', 0)}"
        f" | {counts.get('development_rows', 0):,} |",
        f"| Embargoed | {counts.get('embargoed_periods', 0)} | |",
        f"| Test | {counts.get('test_periods', 0)} | "
        f"{counts.get('test_rows', 0):,} |",
        f"| Out-of-fold rows the weights were fitted on | | "
        f"{counts.get('out_of_fold_rows', 0):,} |",
        "",
        f"Train: `{result.assignment.train[0]}`–"
        f"`{result.assignment.train[-1]}` · Validate: "
        f"`{result.assignment.validate[0]}`–"
        f"`{result.assignment.validate[-1]}` · Test: "
        f"`{result.assignment.test[0]}`–`{result.assignment.test[-1]}` · "
        f"Embargoed: {', '.join(f'`{p}`' for p in result.assignment.embargoed)}",
        "",
        f"{counts.get('entities', 0):,} distinct entities, "
        f"{counts.get('rows', 0):,} rows, {counts.get('features', 0)} "
        f"features. The split assignment is persisted per row, so these "
        f"counts can be checked rather than trusted.",
        "",
        "## Target and exclusions",
        "",
        f"**Target:** `{ft.TARGET}` — the declared ECL rate on the declared "
        f"denominator `{ft.DENOMINATOR}`, converted back to currency for "
        f"every metric above. Not ECL as a share of total exposure.",
        "",
        "**Excluded from the feature matrix, and asserted absent** — by name "
        "and by substring, so a column added to the release later is caught "
        "by the rule rather than by somebody remembering:",
        "",
        "```",
        "  " + "\n  ".join(sorted(ft.BANNED)),
        "```",
        "",
        "`pd_pit_12m`, `pd_lifetime` and `lgd_pct` are deliberately KEPT. "
        "They are inputs to the calculator, not outputs of it, and excluding "
        "them would leave an emulator predicting ECL from sector and region. "
        "The naive reference model above is what stops that being a free "
        "pass.",
        "",
        "## Component settings",
        "",
    ]
    for component, fitted in result.components.items():
        lines += [
            f"### {component}",
            "",
            "```json",
            json.dumps(fitted.config, indent=2, sort_keys=True),
            "```",
            "",
            f"{len(fitted.trials)} configurations tried against a "
            f"{ml.MAX_CONFIGS_PER_FAMILY}-per-family budget; "
            f"{ml.MAX_FOLDS} expanding-window folds; "
            f"{fitted.rounds or 'n/a'} boosting rounds at the early-stopping "
            f"point, against a {ml.MAX_ROUNDS}-round cap with patience "
            f"{ml.EARLY_STOPPING_PATIENCE}. Seed {fitted.seed}.",
            "",
            "| Configuration | Mean fold WAPE |",
            "|---|---|",
        ]
        for trial in sorted(fitted.trials, key=lambda t: t.mean_error):
            lines.append(
                f"| `{json.dumps(trial.config, sort_keys=True)}` | "
                f"{trial.mean_error:.5f} |")
        lines.append("")

    lines += [
        "## Subgroup errors",
        "",
        f"A group is gated at {tr.MATERIAL_GROUP} test observations. Smaller "
        f"groups stay in this table with their counts and are excluded from "
        f"the gate rather than from the report — a reader should see where "
        f"the model is untested.",
        "",
        "`Share of test ECL` is DIAGNOSTIC and gates nothing. WAPE divides "
        "by the group's own total, so a group carrying almost no ECL can "
        "post a large relative error on a trivial absolute one. That is "
        "worth seeing and it is not a reason to move a threshold: the gate "
        "is written in relative terms, applied in relative terms, and a "
        "failure above is reported as a failure.",
        "",
        "| Dimension | Value | Test rows | ECL (SAR mn) | Share of test ECL "
        "| WAPE | Bias | Gated |",
        "|---|---|---|---|---|---|---|---|",
    ]
    worst = max((g["wape"] for g in result.subgroups if g["material"]),
                default=0.0)
    for group in sorted(result.subgroups,
                        key=lambda g: (g["group_dimension"],
                                       -g["observations"])):
        flag = (" **<- G4**"
                if group["material"] and group["wape"] >= worst > 0 else "")
        lines.append(
            f"| {group['group_dimension']} | {group['group_value']} | "
            f"{group['observations']:,} | "
            f"{group.get('ecl_sar_mn', 0.0):,.2f} | "
            f"{group.get('share_of_test_ecl', 0.0) * 100:.2f}% | "
            f"{group['wape']:.4f}{flag} | "
            f"{group['bias']:+.4f} | "
            f"{'yes' if group['material'] else 'no'} |")

    lines += [
        "",
        "## Provenance",
        "",
        "| | |",
        "|---|---|",
        f"| Release | `{result.release_id}` |",
        "| Origin | SYNTHETIC_DEMO |",
        "| Target produced by | `reference_ecl.py` |",
        f"| Model version | `{result.model_version}` |",
    ]
    for library, version in sorted(result.libraries.items()):
        lines.append(f"| {library} | {version or 'not installed'} |")
    lines += [
        "",
        "Artifacts and their SHA-256 hashes are in "
        "`artifacts/whatif/<book>/blend.json`, which also carries the "
        "feature order — a model fed the same columns in a different order "
        "is a different model with no error message.",
        "",
        "## Support limits, and what this is not",
        "",
        "* Fitted over the training window's own ranges. A scenario that "
        "moves a feature outside them is an extrapolation and is labelled "
        "one.",
        "* Explainability output describes **association in the fitted "
        "function**. It is not causal and is labelled that way wherever it "
        "appears.",
        "* Agreement with any bank's ECL engine is **not established and "
        "was not tested**. There is no bank engine here to compare against.",
        "* Every figure above is measured on a generated book. Nothing in "
        "this card is a statement about a real portfolio.",
        "",
    ]
    return "\n".join(lines)


__all__ = ["digest", "freeze", "markdown"]
