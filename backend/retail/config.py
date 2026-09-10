"""
The retail demonstration configuration, and the month range it pins.

One file — `config/retail_demo_config.json` — decides the seed, the size of the
book, the scenario set and, most importantly, `demo_as_of_month`. That last one
is the reason this module exists rather than a `datetime.today()` call scattered
through the generator: a demonstration whose totals move because somebody opened
it in a different month is not a demonstration, it is a rumour.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = ROOT / "config" / "retail_demo_config.json"

SCENARIOS: tuple[str, ...] = ("base", "upturn", "downturn")


def month_end(year: int, month: int) -> date:
    """The last calendar day of a month, without a dateutil dependency."""
    if month == 12:
        return date(year, 12, 31)
    first_of_next = date(year, month + 1, 1)
    return date.fromordinal(first_of_next.toordinal() - 1)


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    idx = year * 12 + (month - 1) + delta
    return idx // 12, idx % 12 + 1


def month_end_series(last_month: str, count: int) -> list[date]:
    """`count` consecutive month-ends ending at `last_month` ("YYYY-MM"), inclusive.

    Returned oldest first. This is the single definition of the published
    chronology: nothing else in the retail product is allowed to invent a month.
    """
    if count < 1:
        raise ValueError("count must be at least 1")
    year, month = (int(p) for p in last_month.split("-"))
    out: list[date] = []
    for back in range(count - 1, -1, -1):
        y, m = _shift_month(year, month, -back)
        out.append(month_end(y, m))
    return out


@dataclass(frozen=True)
class ScenarioSet:
    scenario_set_id: str
    scenario_set_version: str
    weights: dict[str, float]
    hazard_multiplier: dict[str, float]
    lgd_multiplier: dict[str, float]
    ead_multiplier: dict[str, float]
    recovery_delay_add_months: dict[str, int]

    def validate(self, tolerance: float = 1e-9) -> None:
        missing = [s for s in SCENARIOS if s not in self.weights]
        if missing:
            raise ValueError(f"scenario weights missing: {missing}")
        for name, w in self.weights.items():
            if not 0.0 <= w <= 1.0:
                raise ValueError(f"scenario weight for '{name}' is {w}, outside [0, 1]")
        total = sum(self.weights[s] for s in SCENARIOS)
        if abs(total - 1.0) > tolerance:
            raise ValueError(
                f"scenario weights sum to {total!r}, not 1.0 within {tolerance}. "
                "They are not normalised silently — say what they should be."
            )
        # The demo's ordered-scenario invariant is produced by these multipliers
        # being monotone, not by sorting the answers afterwards.
        if not (self.hazard_multiplier["upturn"] <= self.hazard_multiplier["base"]
                <= self.hazard_multiplier["downturn"]):
            raise ValueError("hazard multipliers are not ordered upturn <= base <= downturn")
        if not (self.lgd_multiplier["upturn"] <= self.lgd_multiplier["base"]
                <= self.lgd_multiplier["downturn"]):
            raise ValueError("LGD multipliers are not ordered upturn <= base <= downturn")
        if not (self.ead_multiplier["upturn"] <= self.ead_multiplier["base"]
                <= self.ead_multiplier["downturn"]):
            raise ValueError("EAD multipliers are not ordered upturn <= base <= downturn")


@dataclass(frozen=True)
class RetailDemoConfig:
    config_version: str
    generator_version: str
    seed: int
    disclosure: str
    demo_as_of_month: str
    months: int
    warmup_months: int
    portfolio: dict[str, Any]
    currency: str
    portfolio_country: str
    scenarios: ScenarioSet
    ecl: dict[str, Any]
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---------------------------------------------------------------- chronology

    @property
    def snapshot_dates(self) -> list[date]:
        """The published month-ends, oldest first. Exactly `months` of them."""
        return month_end_series(self.demo_as_of_month, self.months)

    @property
    def warmup_dates(self) -> list[date]:
        """Month-ends generated to give the first visible month real history.

        These are never published. A 3-month payment ratio at the first visible
        snapshot is computed from these, which is why they exist; they are not a
        licence to claim history a facility did not have.
        """
        first = self.snapshot_dates[0]
        y, m = _shift_month(first.year, first.month, -1)
        return month_end_series(f"{y:04d}-{m:02d}", self.warmup_months)

    @property
    def all_dates(self) -> list[date]:
        return self.warmup_dates + self.snapshot_dates

    @property
    def first_snapshot(self) -> date:
        return self.snapshot_dates[0]

    @property
    def last_snapshot(self) -> date:
        return self.snapshot_dates[-1]

    def validate(self) -> None:
        if self.months != 25:
            raise ValueError(
                f"months is {self.months}; the retail contract publishes exactly 25 "
                "consecutive month-ends (spec §4.2). Change it deliberately and "
                "re-version the manifest, or leave it at 25."
            )
        dates = self.snapshot_dates
        if len(set(dates)) != len(dates):
            raise ValueError("duplicate month-end in the published chronology")
        for earlier, later in zip(dates, dates[1:]):
            gap = (later.year * 12 + later.month) - (earlier.year * 12 + earlier.month)
            if gap != 1:
                raise ValueError(f"chronology is not consecutive: {earlier} -> {later}")
        self.scenarios.validate()

    def to_manifest(self) -> dict[str, Any]:
        return {
            "config_version": self.config_version,
            "generator_version": self.generator_version,
            "seed": self.seed,
            "demo_as_of_month": self.demo_as_of_month,
            "months": self.months,
            "warmup_months": self.warmup_months,
            "first_snapshot": self.first_snapshot.isoformat(),
            "last_snapshot": self.last_snapshot.isoformat(),
            "snapshot_dates": [d.isoformat() for d in self.snapshot_dates],
            "currency": self.currency,
            "portfolio_country": self.portfolio_country,
            "scenario_set_id": self.scenarios.scenario_set_id,
            "scenario_set_version": self.scenarios.scenario_set_version,
            "scenario_weights": dict(self.scenarios.weights),
            "is_synthetic": True,
            "disclosure": self.disclosure,
        }


def load_config(path: Path | None = None) -> RetailDemoConfig:
    p = path or DEFAULT_CONFIG_PATH
    raw = json.loads(p.read_text())
    cfg = RetailDemoConfig(
        config_version=raw["config_version"],
        generator_version=raw["generator_version"],
        seed=int(raw["seed"]),
        disclosure=raw["disclosure"],
        demo_as_of_month=raw["demo_as_of_month"],
        months=int(raw["months"]),
        warmup_months=int(raw["warmup_months"]),
        portfolio=raw["portfolio"],
        currency=raw["currency"],
        portfolio_country=raw["portfolio_country"],
        scenarios=ScenarioSet(
            scenario_set_id=raw["scenarios"]["scenario_set_id"],
            scenario_set_version=raw["scenarios"]["scenario_set_version"],
            weights={k: float(v) for k, v in raw["scenarios"]["weights"].items()},
            hazard_multiplier={k: float(v) for k, v in raw["scenarios"]["hazard_multiplier"].items()},
            lgd_multiplier={k: float(v) for k, v in raw["scenarios"]["lgd_multiplier"].items()},
            ead_multiplier={k: float(v) for k, v in raw["scenarios"]["ead_multiplier"].items()},
            recovery_delay_add_months={
                k: int(v) for k, v in raw["scenarios"]["recovery_delay_add_months"].items()
            },
        ),
        ecl=raw["ecl"],
        raw=raw,
    )
    cfg.validate()
    return cfg


@lru_cache(maxsize=1)
def get_config() -> RetailDemoConfig:
    return load_config()
