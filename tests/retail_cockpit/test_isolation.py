"""The Cockpit answers from Cockpit Data, and from nothing else.

Every case here tries to reach past the published projection -- by SQL, by
file, by release id, by thread id, by artifact id, by catalogue -- and the
assertion is always the same shape: the attempt is refused BEFORE the read,
not filtered afterwards. A denial that happens after the bytes have been
touched is not isolation, it is a redaction.

The other four published domains are fingerprinted before and after, with
the retail application's own mechanism, so "nothing else was touched" is a
measurement rather than a claim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import ScriptedResult, final, intent, tool_call  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
LATEST = "2026-08"

#: Every book this deployment publishes that the Cockpit must NOT read.
OTHER_DOMAINS = ("Early Warning Data", "Credit Scorecard Data",
                 "What-If Analysis Data")


# ---- the executable surface -------------------------------------------

@pytest.mark.parametrize("sql,why", [
    ("SELECT * FROM corp_facility_quarter",
     "a relation from the other book"),
    ("SELECT ead_sar_mn FROM retail_account_month UNION ALL "
     "SELECT ead_sar_mn FROM corp_facility_quarter",
     "the other book reached through a UNION"),
    ("ATTACH 'x.duckdb' AS other",
     "a second database attached to the session"),
    ("SELECT * FROM read_parquet('data/retail/analytics/**/*.parquet')",
     "the source lake read directly, around the release"),
    ("SELECT * FROM read_csv_auto('/etc/passwd')",
     "a file on the host"),
    ("COPY retail_account_month TO '/tmp/leak.csv'",
     "the book copied out of the session"),
    ("INSTALL httpfs",
     "an extension that would add network reads"),
    ("SELECT * FROM glob('/**')",
     "the filesystem enumerated"),
])
def test_the_session_refuses_to_reach_outside_the_release(
        chain_runtime, sql, why):
    """Refused by the SESSION itself, whatever the validator did first."""
    import duckdb

    from backend.cockpit_v4 import catalog as cat

    session = cat.open_session(catalog=chain_runtime.catalog, reuse=True)
    with pytest.raises(duckdb.Error) as raised:
        session.connection.execute(sql)
    # And it failed for the right reason, not because of a typo.
    message = str(raised.value).lower()
    assert any(word in message for word in
               ("not found", "permission", "denied", "disabled", "no files",
                "catalog error", "binder error", "io error", "not allowed",
                "cannot", "invalid")), (why, message)


def test_external_access_is_locked_and_cannot_be_turned_back_on(
        chain_runtime):
    """`enable_external_access=false` plus `lock_configuration=true`."""
    import duckdb

    from backend.cockpit_v4 import catalog as cat

    session = cat.open_session(catalog=chain_runtime.catalog, reuse=True)
    external = session.connection.execute(
        "SELECT current_setting('enable_external_access')").fetchone()[0]
    assert external in (False, "false", 0), external
    with pytest.raises(duckdb.Error):
        session.connection.execute("SET enable_external_access = true")


def test_the_session_holds_only_this_release(chain_runtime):
    """One book is materialised, and it is ours."""
    from backend.cockpit_v4 import catalog as cat

    session = cat.open_session(catalog=chain_runtime.catalog, reuse=True)
    tables = {r[0] for r in session.connection.execute(
        "SELECT table_name FROM information_schema.tables").fetchall()}
    assert tables == set(chain_runtime.catalog.relations()), tables
    assert not any(t.startswith("corp_") for t in tables)

    # The governance columns are CONSUMED by the materialisation filter and
    # are not in the session at all. That is stronger than filtering on
    # them at query time: there is no release id and no tenant id to write
    # a predicate against, because only one release's rows were ever
    # materialised. A query cannot ask for another book's rows, correctly
    # or incorrectly.
    from backend.retail_cockpit_adapter.publish import GOVERNANCE

    for relation in sorted(tables):
        columns = {r[0] for r in session.connection.execute(
            f'SELECT * FROM "{relation}" LIMIT 0').description}
        assert not (columns & set(GOVERNANCE)), (relation,
                                                 columns & set(GOVERNANCE))

    # And the rows that ARE there are this release's, counted.
    from backend.cockpit_v4 import lake

    published = lake.read_manifest(
        chain_runtime.catalog.dataset_release_id)["row_counts"]
    for relation in sorted(tables):
        held = session.connection.execute(
            f'SELECT COUNT(*) FROM "{relation}"').fetchone()[0]
        assert held == published[relation], (relation, held,
                                             published[relation])


# ---- the model-visible surface ----------------------------------------

def _ask_the_catalogue(runtime, **overrides) -> str:
    """One `inspect_catalog` call, exactly as the model's tool makes it."""
    from backend.cockpit_v4 import catalog_tool, contracts, domain_resolver

    scope = domain_resolver.scope_for(
        runtime.catalog.domain_id, tenant_id=runtime.catalog.tenant_id,
        release_id=runtime.catalog.dataset_release_id)
    blank = contracts.Intent(
        query_mode="DATA_ANALYSIS", owner="COCKPIT",
        understood_request="what this book holds", response_language="en",
        blocking_ambiguities=(), resolved_assumptions=(),
        canonical_mappings=(), excluded_parts=(), public_rationale="")
    request = contracts.CatalogRequest(
        intent=blank, query=overrides.get("query", ""),
        relation_ids=overrides.get("relation_ids", ()),
        field_ids=overrides.get("field_ids", ()),
        detail=overrides.get("detail", ("discovery",)),
        reporting_periods=(), sample_rows=0, cursor="")
    service = catalog_tool.CatalogService(catalog=runtime.catalog,
                                          scope=scope)
    return str(service.inspect(request)).lower()


def test_the_catalogue_the_model_sees_names_only_this_book(chain_runtime):
    named = _ask_the_catalogue(chain_runtime, detail=("discovery",))
    assert "corp_" not in named
    for other in ("early_warning", "scorecard", "whatif", "what_if"):
        assert other not in named, other


def test_a_field_from_the_other_book_is_not_resolved(chain_runtime):
    answer = _ask_the_catalogue(
        chain_runtime, detail=("fields",),
        field_ids=("corp_facility_quarter.ead_sar_mn",
                   "corp_borrower_quarter.ebitda_sar_mn"))
    # It may SAY the field is unknown. It must never carry a definition
    # for it: a definition is the other book's metadata, leaked.
    assert "trailing twelve-month" not in answer
    assert "earnings before" not in answer


# ---- the request surface ----------------------------------------------

def test_a_run_may_not_name_its_own_release(chain_store, chain_release):
    """A caller-chosen release is how one thread reads another's book."""
    thread = chain_store.create_thread(
        tenant_id="demo-tenant", principal_id="u1", domain_id="retail",
        release_id=chain_release)
    record, _ = chain_store.accept_run(
        thread_id=thread, tenant_id="demo-tenant", principal_id="u1",
        question="anything", mode="standard",
        release_id="v4-saudi-corporate-20q-v4", domain_id="retail",
        ui_filters={}, idempotency_key="", body_digest="",
        startup_sha="t", deadline_at="")
    from backend.cockpit_v4 import analytical_runtime as arun

    with pytest.raises(Exception) as raised:
        arun.for_run(record, store=chain_store)
    assert "corporate" in str(raised.value).lower() or \
           "not" in str(raised.value).lower()


def test_another_tenants_thread_is_not_readable(chain_store, chain_release):
    """Tenant scoping is server-side; an id from elsewhere reveals nothing."""
    theirs = chain_store.create_thread(
        tenant_id="someone-else", principal_id="them", domain_id="retail",
        release_id=chain_release)
    owner = chain_store.thread_owner(theirs)
    assert owner == ("someone-else", "them")
    # The store records WHOSE it is, and the route compares before it reads.
    assert owner[0] != "demo-tenant"
    assert chain_store.thread_context(theirs, tenant_id="demo-tenant") is None


def test_another_tenants_artifact_is_not_readable(drive_chain, chain_store):
    """An artifact id guessed from another tenant returns nothing."""
    from test_chains import EAD_BY_PRODUCT, MONEY, _analysis, _finish

    _, _, record = drive_chain(
        "Total exposure at default by product this month",
        [_analysis(EAD_BY_PRODUCT, objective="EAD by product",
                   grain="product", unit=MONEY,
                   fields=("retail_account_month.ead_sar_mn",)),
         lambda m: _finish(m, dimension="product", measure="ead_sar_mn",
                           unit=MONEY)])
    body = chain_store.get_run(record.run_id).final_response
    artifact_id = body["numeric_claims"][0]["evidence"]["artifact_id"]

    assert chain_store.get_artifact(artifact_id,
                                    tenant_id="demo-tenant") is not None
    assert chain_store.get_artifact(artifact_id,
                                    tenant_id="someone-else") is None


# ---- the other books are untouched ------------------------------------

def test_the_other_published_domains_are_byte_identical_afterwards():
    """Fingerprinted with the retail application's own mechanism."""
    from backend.retail import domains as retail_domains

    before = retail_domains.reconcile()
    from backend.cockpit_v4 import catalog as cat
    from backend.cockpit_v4 import domains as dom

    catalog = cat.build(domain_id="retail",
                        release_id=dom.DEFAULT_RELEASES[dom.RETAIL],
                        tenant_id="demo-tenant")
    session = cat.open_session(catalog=catalog, reuse=True)
    session.connection.execute(
        f"SELECT COUNT(*) FROM retail_account_month "
        f"WHERE reporting_month = '{LATEST}'").fetchone()
    after = retail_domains.reconcile()
    assert before == after, (before, after)
