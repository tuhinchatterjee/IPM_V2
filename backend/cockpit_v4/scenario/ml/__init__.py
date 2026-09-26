"""The ECL emulators: trained offline, anchored at inference, honest at both.

Section 11. Method 2 answers "what would ECL be" with a model rather than
with proportional arithmetic, and almost every way of building one produces
something that scores beautifully and means nothing.

## The four traps, and where each is closed

**Manufacturing the label.** §11.1: *"Do not manufacture the training label
as PD × LGD × EAD and then claim the resulting model learned the bank's ECL
engine."* The target here is `ecl_rate` as the candidate release publishes
it, produced by `reference_ecl.py` from a per-scenario term structure with
survival, discounting and probability weighting. It is measurably not the
closed form -- Stage 1 sits about 4% away -- which is exactly why this
release exists and why `ML_ACCEPTANCE_TARGETS.md` makes the naive product a
declared reference model rather than a straw man.

**Leaking the target into X.** Every ECL column, every rate derived from
one, and the whole term structure are excluded, and `features.py` asserts
their absence rather than trusting the list.

**Leaking the future into training.** `split.py` divides by DISTINCT
REPORTING PERIOD and nothing else. Preprocessing statistics, hyperparameters
and blend weights are all fitted inside their own window; the test periods
are read once, at the end, to produce the numbers in the model card.

**Calling one model a blend.** `blend.py` fits non-negative weights on
out-of-fold predictions with a deterministic optimiser. If the answer is
1/0/0 it is reported as a single-model result in those words. A hardcoded
mixture presented as a fitted blend would be the most dishonest thing in
this package, so the outcome is published as data in
`whatif_*_model_metric` and repeated in the card.

## Two halves that never run together

* **Training** -- `features`, `split`, `components`, `blend`, `train` -- runs
  in `scripts/whatif/train_emulator.py`, inside the candidate virtual
  environment built from `requirements-whatif.txt`. None of it is imported
  by a chat turn, and a test walks the tree to keep it that way.
* **Inference** -- `infer` -- loads the frozen artifacts and applies §11.4's
  anchoring. It reports `MODEL_NOT_READY` rather than a number when the
  artifacts or the libraries are absent, which is the state the accepted
  environment is permanently in.

## What passing establishes

That an emulator can learn `reference_ecl.py` on a generated book, out of
time, within predeclared tolerances. **Not** agreement with a bank's ECL
engine, which is not available here and is marked unavailable rather than
approximated.
"""

from __future__ import annotations

#: The artifact version every model, card and metric row carries. A scenario
#: pinned to one version is never silently served another.
MODEL_VERSION = "whatif-ecl-emulator-2.0.0"

#: The three components §11.3 asks for. Two boosters and one deliberately
#: different model: a regularized additive fit is linear in its basis and
#: errs in different places, which is what makes a blend of them worth
#: having. Two boosters tuned on one dataset mostly agree.
XGBOOST = "xgboost"
LIGHTGBM = "lightgbm"
#: Version 1's third component, additive in the features' own units. Kept as
#: a name so a version-1 artifact directory still loads, and NOT in
#: `COMPONENTS`: it scored 0.32 and 1.82 mean fold WAPE against 0.03 and 0.08
#: for the boosters, because no sum of univariate terms equals a product and
#: `ecl_rate` is one. `ML_ACCEPTANCE_TARGETS_V2.md` section 4 has the argument.
ADDITIVE = "additive_spline"

#: Version 2's third component: the same family -- spline expansion into a
#: ridge -- additive in LOGS, where the target genuinely is additive.
ADDITIVE_LOG = "additive_log"

COMPONENTS: tuple[str, ...] = (XGBOOST, LIGHTGBM, ADDITIVE_LOG)

#: The declared reference model, carried through the card beside the blend
#: so that "better than nothing" is never the standard.
NAIVE_PRODUCT = "naive_ead_pd_lgd"

#: Below this weight a component is reported immaterial, by name (B3).
MATERIAL_WEIGHT = 0.05

#: The bounded search §11.6 asks to be declared in advance.
MAX_CONFIGS_PER_FAMILY = 12
MAX_FOLDS = 3
MAX_ROUNDS = 600
EARLY_STOPPING_PATIENCE = 50

#: Fixed, and recorded in the card beside every number they produced.
SEEDS: dict[str, int] = {XGBOOST: 20260928, LIGHTGBM: 20260929,
                         ADDITIVE: 20260930, ADDITIVE_LOG: 20260930,
                         "blend": 20260931}

#: What Method 2 says when it has no model to run. An existing error code:
#: section 19 maps a domain failure onto the contract the runtime already
#: knows, rather than growing it.
NOT_READY = "MODEL_NOT_READY"

__all__ = ["ADDITIVE", "ADDITIVE_LOG", "COMPONENTS", "EARLY_STOPPING_PATIENCE", "LIGHTGBM",
           "MATERIAL_WEIGHT", "MAX_CONFIGS_PER_FAMILY", "MAX_FOLDS",
           "MAX_ROUNDS", "MODEL_VERSION", "NAIVE_PRODUCT", "NOT_READY",
           "SEEDS", "XGBOOST"]
