"""
Registered analytical capabilities.

Importing this package runs the @register decorators and populates the Engine
Registry, so every function module must be imported here.

  portfolio.py     Portfolio Summary, Stage Distribution, Sector Concentration,
                   Portfolio Trend
  migration.py     Stage Migration, DPD Migration, Rating Transition Matrix,
                   ECL Movement, Top Deteriorating Borrowers
  ifrs9.py         SICR Trigger Breakdown, Stage Migration Flow,
                   ECL Coverage by Stage, Approaching the SICR Threshold
  ratings.py       Rating Actions, Rating Grade Distribution,
                   Macroeconomic Context
  concentration.py Obligor Concentration, Collateral Coverage,
                   Vintage Performance, Watchlist Movement
  stress.py        Basic Management Stress Scenario
                   + High Utilisation Watchlist (deliberately USER_DEFINED, so
                     the product can be seen running an analysis that carries no
                     verification tick)
"""

from backend.engine.functions import (  # noqa: F401
    concentration,
    ifrs9,
    migration,
    portfolio,
    ratings,
    stress,
)

__all__ = ["concentration", "ifrs9", "migration", "portfolio", "ratings", "stress"]
