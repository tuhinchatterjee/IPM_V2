"""
Registered analytical capabilities.

Importing this package runs the @register decorators and populates the Engine
Registry, so every function module must be imported here.

Ten CreditProbe Certified analyses, plus one deliberately USER_DEFINED example that
demonstrates a user-built analysis running without a verification tick:

  portfolio.py   Portfolio Summary, Stage Distribution, Sector Concentration,
                 Portfolio Trend
  migration.py   Stage Migration, DPD Migration, Rating Transition Matrix,
                 ECL Movement, Top Deteriorating Borrowers
  stress.py      Basic Management Stress Scenario
                 + High Utilisation Watchlist (USER_DEFINED)
"""

from backend.engine.functions import migration, portfolio, stress  # noqa: F401

__all__ = ["migration", "portfolio", "stress"]
