"""The one place CreditProbe keeps what it knows about its own data.

Why this package exists
-----------------------
Three surfaces answered "how many data domains do you have?" and gave three
different numbers on the same deployment:

  * the Data Builder screen said 45, because it listed rows in the
    `data_domains` table and thirty-eight of them were leftovers from an
    earlier generator taxonomy holding no datasets at all;
  * the analyst's `list_data_domains` tool said 5, because it grouped the
    file catalogue by the domain each dataset happens to name, so a heading
    with nothing under it did not exist;
  * `backend.services.data_domains` said 7, because that is how many business
    headings a credit officer is meant to see.

All three were reading something true. None of them was reading the same
thing, and a product that disagrees with itself about its own catalogue cannot
be trusted about anything computed from it.

So the catalogue has one reader. This package holds it. Domains are the
business headings — the list a person is shown is the list the AI counts.
Datasets, fields, grain, periods and row counts come from the governed
catalogue and the published lake, which is where they actually live. Nothing
here reads a row of credit data; it reads how much of it there is.

What reads this
---------------
The Data Builder overview, the analyst's discovery tools, the orchestrator's
data-capability handlers, the dataset dictionary and the Trace. A surface that
keeps its own copy of any of this is a surface that will disagree again, and
`tests/metadata/test_reconciliation.py` fails when one does.
"""

from backend.metadata.service import (
    METADATA_VERSION,
    UNPLACED,
    Catalogue,
    Dataset,
    Domain,
    Field,
    Relationship,
    catalogue,
    counts,
    coverage,
    dataset,
    datasets,
    domain,
    domains,
    fields,
    invalidate,
    periods,
    relationships,
    search,
)

__all__ = [
    "METADATA_VERSION",
    "UNPLACED",
    "Catalogue",
    "Dataset",
    "Domain",
    "Field",
    "Relationship",
    "catalogue",
    "counts",
    "coverage",
    "dataset",
    "datasets",
    "domain",
    "domains",
    "fields",
    "invalidate",
    "periods",
    "relationships",
    "search",
]
