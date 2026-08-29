"""
Investigation assurance. Part F, §178-§215.

    "Do not call operational assurance 'accuracy' where no independent
     reference answer exists."

What this package replaced
--------------------------
A flat wall of ninety-odd checks that nobody read. Every reader arrived with a
different question and the wall answered none of them, because it never said
what any check was FOR.

``dimensions``  six top-level dimensions, each answering a question a person
                actually has, with all ninety-five detailed checks preserved
                underneath — the dimension is where you notice a problem and
                the subcomponent is where you fix it.
``record``      an immutable record per answer: what ran, what it found, and
                what may honestly be claimed from it. Critical gates before
                coverage gate before score, so a record with a failed
                invariant never gets a number somebody could quote.
``panel``       "HOW CREDITPROBE PERFORMED", assembled for a reader.
``store``       the records, persisted. Written once and never rescored:
                staleness is computed against today's runtime rather than
                stored, so a record keeps saying what was true when it was
                made while a reader still learns the world has moved.
``access``      who may read a review — inherited from the Investigation it
                describes, because two permission models over the same
                content diverge, and the one that diverges upward is a leak.
``reviews``     §186's recent Investigation Reviews: eight views written as
                predicates over one row set, so FAILED and LOW ASSURANCE
                cannot drift into two definitions of failure.
``review``      §189-§199's full review of one turn and its thread.
``comparison``  §200's rerun comparison, whose first job is deciding whether
                a comparison is legitimate at all.
``trends``      §201-§203: the six tiles that replaced the twenty-five-card
                wall, their trends by cohort, and how each dimension
                actually affected an outcome.
"""

from backend.assurance import (
    access,
    comparison,
    dimensions,
    panel,
    record,
    review,
    reviews,
    store,
    trends,
)

__all__ = ["access", "comparison", "dimensions", "panel", "record", "review",
           "reviews", "store", "trends"]
