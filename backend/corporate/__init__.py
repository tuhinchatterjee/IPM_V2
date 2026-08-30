"""Corporate Borrower 360 and the corporate relationship graph. Part B.

The retail scorecard module answers "is this model still working". This one
answers a different question - "what is this borrower, and what is it
connected to" - and the two share nothing but the platform they run on.

Layout
------
``domains``     the nineteen governed Data Builder domains, B3
``universe``    the synthetic corporate universe, B1: entities, sixteen
                quarters, and the observed relationships between them
``lineage``     every Borrower 360 field's authoritative source, B5
``snapshot``    the semantic snapshot, B2/B4 - fast, denormalised, and
                never authoritative over the domain it copied from
``resolution``  entity resolution across source systems, B7
``search``      borrower and cohort search, B6

Everything here is generated. Every row carries ``origin = SYNTHETIC_DEMO``
and describes no real company, no real ownership structure and no real
bank's book.
"""

from __future__ import annotations

#: Stamped on every row of every dataset this package generates. B1.
ORIGIN = "SYNTHETIC_DEMO"

#: Said in full wherever a report, an export or a screen shows these figures.
NOT_CLIENT_DATA = (
    "Synthetic demonstration data. It describes no real company, no real "
    "ownership structure and no real bank's book, and must not be presented "
    "as client data."
)
