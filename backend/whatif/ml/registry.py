"""
Where a trained model lives, how it is sealed, and why one is never quietly
replaced.

The artifact format is a security decision, not a preference
------------------------------------------------------------
`backend/brain/security.py` refuses `.pkl`, `.joblib`, `.pt` and `.pth` on
import, and says why: "a pickle is a program, not data: loading one executes
it". Its allowlist already contains `.json`. XGBoost can serialise a booster to
its own JSON, so the model is stored that way and NOTHING about that control
needs relaxing. UBJSON would be smaller and is not on the allowlist, so it is
not used.

The card is sealed the same way local training runs are
--------------------------------------------------------
`backend/learning/models.py::seal()` refuses — rather than redacts — an
artifact carrying a credential or a client identifier, then hashes it. That
function is reused here rather than reimplemented, so a What-If model is held
to the same standard as every other model this product trains. XGBoost writes
feature NAMES into its JSON, which is exactly the route by which a borrower id
could end up in an artifact, and `features.check()` stops that upstream.

Candidate, then active
----------------------
A retrained model arrives as a CANDIDATE. Nothing promotes it automatically.
The active model keeps answering until somebody looks at both sets of numbers
and says so, and every previous version stays on disk. The operation people
want under deadline pressure — overwrite the live model and move on — is the
one that must not exist.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REGISTRY_VERSION = "1.0.0"

ACTIVE = "ACTIVE"
CANDIDATE = "CANDIDATE"
RETIRED = "RETIRED"
STATES: tuple[str, ...] = (CANDIDATE, ACTIVE, RETIRED)

ARTIFACT = "model.json"
CARD = "card.json"
INDEX = "index.json"


class RegistryError(ValueError):
    """A model that cannot be stored, loaded or activated."""


def root() -> Path:
    """Where models live: beside the catalogue, not in the data lake.

    The lake is rebuilt by a generator and is reproducible from a seed. A
    trained model is not — it is an artifact somebody validated — so it does
    not belong somewhere a rebuild would erase.
    """
    from backend.config import settings

    path = Path(settings.metadata_dir) / "whatif_models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _index_path() -> Path:
    return root() / INDEX


def _read_index() -> dict[str, Any]:
    path = _index_path()
    if not path.exists():
        return {"registry_version": REGISTRY_VERSION, "active": "", "models": []}
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        raise RegistryError(f"The model index could not be read: {e}") from e


def _write_index(body: dict[str, Any]) -> None:
    _index_path().write_text(json.dumps(body, indent=2, sort_keys=True))


def next_version() -> str:
    """A version derived from the date, with a counter for the same day."""
    today = datetime.now(UTC).strftime("%Y.%m.%d")
    existing = {m["version"] for m in _read_index().get("models", [])}
    if today not in existing:
        return today
    for n in range(2, 100):
        candidate = f"{today}.{n}"
        if candidate not in existing:
            return candidate
    raise RegistryError("Too many models trained today.")  # pragma: no cover


@dataclass
class Card:
    """Everything a reader needs to judge a model, and to rebuild it."""

    version: str
    state: str = CANDIDATE
    algorithm: str = "XGBoost regressor (gradient-boosted trees)"
    target: str = ""
    target_definition: str = ""
    features: list[str] = field(default_factory=list)
    feature_count: int = 0
    split: dict[str, Any] = field(default_factory=dict)
    hyperparameters: dict[str, Any] = field(default_factory=dict)
    seed: int = 0
    rows: dict[str, int] = field(default_factory=dict)
    training: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    out_of_time: dict[str, Any] = field(default_factory=dict)
    slices: dict[str, Any] = field(default_factory=dict)
    #: One model with Stage as a feature, or one model per Stage? The
    #: comparison that chose, re-measured on every fit.
    stage_study: dict[str, Any] = field(default_factory=dict)
    ranges: dict[str, Any] = field(default_factory=dict)
    encoding: dict[str, Any] = field(default_factory=dict)
    importance: list[dict[str, Any]] = field(default_factory=list)
    shap: dict[str, Any] = field(default_factory=dict)
    artifact_sha256: str = ""
    artifact_bytes: int = 0
    artifact_format: str = "xgboost-native-json"
    built_at: str = ""
    built_by: str = ""
    predecessor: str = ""
    activated_at: str = ""
    activated_by: str = ""
    reason: str = ""
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_dict(cls, body: dict[str, Any]) -> Card:
        known = {k: v for k, v in body.items() if k in cls.__annotations__}
        return cls(**known)


#: Stated on every model card. These are properties of the DATA, and a card
#: that omitted them would let a reader take the R-squared at face value.
LIMITATIONS: tuple[str, ...] = (
    "On this book the reported ECL is close to a closed form — applicable PD x "
    "LGD x EAD x the scenario weighting, plus a management overlay on a small "
    "share of rows. A model given PD, LGD and Stage can therefore reproduce "
    "the rate almost exactly, so a very high R-squared here is MECHANICAL and "
    "is not evidence of predictive skill.",
    "The observed macroeconomic series in this installation are generated from "
    "a single latent cycle factor, so GDP growth, the oil price and the policy "
    "rate move together by construction. There are effectively sixteen "
    "independent macro observations, not fifty thousand. Macro variables are "
    "therefore NOT model features, and the ten-variable macro What-If runs on "
    "declared sensitivities instead.",
    "The model estimates a rate, not a cash flow. There is no contractual "
    "cash-flow projection, no lifetime PD term structure and no "
    "effective-interest discounting.",
    "It is anchored to the reported ECL and can only move it. It never "
    "restates the book.",
)


#: Fields that change over a model's life without changing the MODEL. A seal
#: that covered these would break the moment somebody activated the thing it
#: was protecting, which would teach everyone to ignore the check.
MUTABLE: frozenset[str] = frozenset({
    "state", "activated_at", "activated_by", "reason", "artifact_sha256",
})


def _sealed_content(card: dict[str, Any]) -> dict[str, Any]:
    """The part of a card the hash covers: what the model IS, not where it is."""
    return {k: v for k, v in card.items() if k not in MUTABLE}


def _seal(card: dict[str, Any], artifact: bytes) -> str:
    """Refuse a card carrying an identifier or a credential, then hash both.

    Reuses the sealer the rest of the product trains against, so a What-If
    model cannot be stored under a weaker rule than a Brain model. The hash
    binds the artifact BYTES to the card that describes them, so a model whose
    metrics were edited after validation, or whose bytes were swapped, will not
    load.
    """
    from backend.learning.models import scan

    content = _sealed_content(card)
    problems = scan(content)
    if problems:
        raise RegistryError(
            "This model card cannot be sealed: " + "; ".join(problems))
    body = json.dumps(content, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode() + artifact).hexdigest()


def save(trained: Any, *, version: str = "", built_by: str = "",
         reason: str = "", importance: list[dict[str, Any]] | None = None,
         shap: dict[str, Any] | None = None) -> Card:
    """Store a trained model as a CANDIDATE. Never as the active one."""
    from backend.whatif.ml import features as ft

    chosen = version or next_version()
    artifact = trained.artifact()
    if not artifact.lstrip().startswith(b"{"):
        raise RegistryError(
            "The model artifact is not JSON. Only XGBoost native JSON is "
            "stored — a pickle is a program, not data.")

    index = _read_index()
    card = Card(
        version=chosen, state=CANDIDATE,
        target=ft.TARGET,
        target_definition=ft.describe()["target_definition"],
        features=list(trained.feature_names),
        feature_count=len(trained.feature_names),
        split=trained.split.to_dict(),
        hyperparameters={k: v for k, v in trained.hyperparameters.items()},
        seed=int(trained.hyperparameters.get("random_state", 0)),
        rows=dict(trained.rows), training=dict(trained.training),
        validation=dict(trained.validation),
        out_of_time=dict(trained.out_of_time),
        slices=dict(trained.slices), ranges=dict(trained.ranges),
        stage_study=dict(trained.stage_study),
        encoding=trained.encoding.to_dict(),
        importance=list(importance or []), shap=dict(shap or {}),
        artifact_bytes=len(artifact),
        built_at=datetime.now(UTC).isoformat(timespec="seconds"),
        built_by=str(built_by or "system"),
        predecessor=str(index.get("active") or ""),
        reason=str(reason or ""),
        warnings=list(trained.warnings),
        limitations=list(LIMITATIONS))
    card.artifact_sha256 = _seal(card.to_dict(), artifact)

    folder = root() / chosen
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ARTIFACT).write_bytes(artifact)
    (folder / CARD).write_text(json.dumps(card.to_dict(), indent=2,
                                          sort_keys=True, default=str))

    index["models"] = [m for m in index.get("models", [])
                       if m.get("version") != chosen]
    index["models"].append({"version": chosen, "state": CANDIDATE,
                            "built_at": card.built_at,
                            "predecessor": card.predecessor})
    index["models"].sort(key=lambda m: m["built_at"])
    _write_index(index)
    return card


def cards() -> list[Card]:
    """Every stored model, oldest first."""
    index = _read_index()
    out = []
    for entry in index.get("models", []):
        path = root() / entry["version"] / CARD
        if not path.exists():
            continue
        try:
            body = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):  # pragma: no cover
            continue
        body["state"] = entry.get("state", body.get("state", CANDIDATE))
        out.append(Card.from_dict(body))
    return out


def card(version: str) -> Card:
    for found in cards():
        if found.version == version:
            return found
    raise RegistryError(f"There is no model version '{version}'.")


def active_version() -> str:
    return str(_read_index().get("active") or "")


def active() -> Card | None:
    version = active_version()
    if not version:
        return None
    try:
        return card(version)
    except RegistryError:  # pragma: no cover - an index pointing at nothing
        return None


def activate(version: str, *, actor: str = "", reason: str = "") -> Card:
    """Promote a candidate. The previous active model is retired, not deleted."""
    found = card(version)
    index = _read_index()
    previous = str(index.get("active") or "")
    if previous == version:
        raise RegistryError(f"Model {version} is already the active model.")
    for entry in index.get("models", []):
        if entry.get("version") == previous:
            entry["state"] = RETIRED
        if entry.get("version") == version:
            entry["state"] = ACTIVE
    index["active"] = version
    _write_index(index)

    found.state = ACTIVE
    found.activated_at = datetime.now(UTC).isoformat(timespec="seconds")
    found.activated_by = str(actor or "system")
    if reason:
        found.reason = reason
    (root() / version / CARD).write_text(
        json.dumps(found.to_dict(), indent=2, sort_keys=True, default=str))
    _log({"event": "activated", "version": version, "predecessor": previous,
          "actor": found.activated_by, "at": found.activated_at,
          "reason": reason})
    return found


def load_booster(version: str = "") -> Any:
    """The stored model, read back from its JSON.

    The hash is checked first. A model whose bytes have changed since it was
    sealed is refused rather than loaded, because a model that scored one way
    and predicts another is worse than no model.
    """
    from xgboost import XGBRegressor

    chosen = version or active_version()
    if not chosen:
        raise RegistryError(
            "No ML model has been activated. Train one, or use the Delta "
            "Model.")
    found = card(chosen)
    path = root() / chosen / ARTIFACT
    if not path.exists():
        raise RegistryError(f"Model {chosen} has no stored artifact.")
    artifact = path.read_bytes()
    body = json.loads((root() / chosen / CARD).read_text())
    expected = found.artifact_sha256
    recomputed = _seal(body, artifact)
    if expected and recomputed != expected:
        raise RegistryError(
            f"Model {chosen} does not match the hash it was sealed with. It "
            "will not be loaded.")
    model = XGBRegressor()
    model.load_model(bytearray(artifact))
    return model


def _log(entry: dict[str, Any]) -> None:
    """Append to the change log. Never rewritten, only added to."""
    path = root() / "changelog.jsonl"
    with path.open("a") as handle:
        handle.write(json.dumps(entry, sort_keys=True, default=str) + "\n")


def changelog() -> list[dict[str, Any]]:
    path = root() / "changelog.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:  # pragma: no cover
            continue
    return out


def record_build(card_: Card) -> None:
    """Note a training run in the change log, whether or not it is activated."""
    _log({"event": "trained", "version": card_.version,
          "predecessor": card_.predecessor, "actor": card_.built_by,
          "at": card_.built_at, "reason": card_.reason,
          "split": card_.split, "seed": card_.seed,
          "validation": card_.validation, "out_of_time": card_.out_of_time,
          "artifact_sha256": card_.artifact_sha256})


def compare(left: str, right: str) -> dict[str, Any]:
    """Two models side by side, on the measures that decide a promotion."""
    a, b = card(left), card(right)
    rows = []
    for label, key in (("R²", "r2"), ("MAE", "mae"), ("RMSE", "rmse"),
                       ("WAPE %", "wape")):
        for scope in ("validation", "out_of_time"):
            first = (getattr(a, scope) or {}).get(key)
            second = (getattr(b, scope) or {}).get(key)
            better = None
            if isinstance(first, (int, float)) and isinstance(second, (int, float)):
                better = (second > first) if key == "r2" else (second < first)
            rows.append({"metric": f"{label} ({scope.replace('_', ' ')})",
                         "left": first, "right": second, "right_better": better})
    return {"left": left, "right": right, "rows": rows,
            "left_state": a.state, "right_state": b.state,
            "note": ("A promotion is a judgement, not an arithmetic result. "
                     "These figures inform it; they do not make it.")}


__all__ = [
    "ACTIVE", "ARTIFACT", "CANDIDATE", "CARD", "Card", "INDEX", "LIMITATIONS",
    "MUTABLE", "REGISTRY_VERSION", "RETIRED", "RegistryError", "STATES", "activate",
    "active", "active_version", "card", "cards", "changelog", "compare",
    "load_booster", "next_version", "record_build", "root", "save",
]
