"""
The teaching corpus: where cases come from, before they are reviewed.

§13. Three sources, and the distinction between them is recorded on every case
rather than lost once they are in one table:

``migrate``   Cases that already existed — the Phase 0 curriculum, the
              complex-query corpus, and the certified Analysis Studio methods.
              Nothing here is new material; it is existing reviewed work put
              into the governed schema.
``canonical`` Cases authored for this phase, in the families migration leaves
              empty.

Why the corpus lives in the factory and the library lives in the backend
------------------------------------------------------------------------
The dependency runs factory → backend and never the other way. A backend
module that can import the factory can reach the sealed holdout one line
later, and the whole point of the seal is that the line is never there to be
extended. So this package imports `backend.teaching.schema`, and nothing in
`backend/` imports this.

Nothing here reads the holdout. The import-graph test that has covered
`intelligence_factory` since P1 covers this package too.
"""

from intelligence_factory.teaching import migrate

__all__ = ["migrate"]
