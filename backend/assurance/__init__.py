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
"""

from backend.assurance import dimensions, panel, record

__all__ = ["dimensions", "panel", "record"]
