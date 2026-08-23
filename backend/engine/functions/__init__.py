"""
Registered analytical capabilities — one module per analysis.

Importing this package is what runs the @register decorators and populates the
Engine Registry, so every new function module must be imported here.

Phase 2 adds the ten certified analyses:

    portfolio_summary        stage_distribution      stage_migration
    dpd_migration            rating_transition       sector_concentration
    ecl_movement             top_deteriorating       portfolio_trend
    stress_basic

Each will arrive with a declared AnalysisContract, an implementation built on the
proven maths in backend/data_loader.py, and its own golden-value test suite.
"""
