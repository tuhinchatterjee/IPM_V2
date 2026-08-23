"""
The HTTP surface of IPM.

Every capability is exposed here rather than being called directly by a screen.
That boundary is what lets the front end be replaced without touching the engine,
and what lets the engine be reused by a scheduled job, a notebook or another
system (docs/ARCHITECTURE.md §7).

  main.py      the FastAPI application, middleware and error handling
  schemas.py   response shapes — the contract the TypeScript client mirrors
  routers/     one module per capability area
"""
