"""
The Guided Risk Workspace: shared governed objects and the workspaces around
the Advanced Cockpit engine.

Nothing here is a second analytical engine. Cohorts are frozen through
`scenario/cohort.py`, scenarios execute through `scenario/` (the same engine
the Cockpit chat reaches through `scenario/bridge.py`), portfolio data is read
through the V4 catalogue session of the book in use (`catalog.open_session`),
and every model call is observed by `backend/llm/exchange.py`. This package
adds the persistent OBJECTS (cohort, scenario definition, scenario result,
lens, lens observation, metric definition, alert, message share), the seeded
governed content that makes the product usable on first launch, and the HTTP
surface the workspaces use.

Mounted only when `COCKPIT_V4_GUIDED_WORKSPACE` is on (see `flags.py`); with
it off the V4 application is the accepted application.
"""
