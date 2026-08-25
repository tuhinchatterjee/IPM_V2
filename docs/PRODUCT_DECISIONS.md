# Product decisions

Decisions taken by the product owner, with what each one means in the code and
where it is enforced. This exists so a decision is not re-litigated every time
somebody new reads the same trade-off, and so that "why is it like this?" has an
answer that is not archaeology.

Each entry names the mechanism, not just the intent — a decision with no
mechanism is a preference.

---

## 1. Demonstration password

`creditprobe-demo`, for local demonstration only.

Four accounts are seeded on first start, one per role. The password is
documented in the README because a demonstration nobody can sign in to is not
one. Passwords are stored as Argon2id hashes and never in plain text; seeding is
idempotent and **never overwrites an existing password**, so a restart cannot
undo one somebody changed.

*Where:* `scripts/seed_demo_users.py`, `backend/auth/security.py`,
`docker/backend-entrypoint.sh`.

## 2. Signing in is compulsory by default

`REQUIRE_LOGIN` defaults to **true**. An unauthenticated request to anything
touching portfolio data or changing anything is refused with 401 rather than
treated as an Analyst, and the `X-IPM-Role` header cannot be used to get past
that refusal.

Turn it off (`REQUIRE_LOGIN=false`) only for a throwaway local session where
nobody has seeded an account.

Three endpoints stay open on purpose: the health check, the list of registered
analyses, and `auth/me` — which has to answer or nothing can render the login
form. None of them exposes portfolio data.

The interface asks the backend whether a session is required rather than being
told at build time, so the login gate cannot disagree with the thing enforcing
it.

*Where:* `backend/config.py`, `backend/api/permissions.py`,
`backend/api/auth.py` (`login_required` on `/auth/me`),
`frontend/src/components/layout/app-shell.tsx`.
*Tested:* `tests/api/test_login_required.py`.

## 3. Viewers cannot read raw governed rows

The Data Builder row-level grid, the column profiler and the governed export are
closed to the Viewer role. Viewers read approved analytical outputs, not the
rows underneath them.

*Where:* `RequireDataSteward` on the viewer endpoints in
`backend/api/routers/data_builder.py`.
*Tested:* `tests/api/test_dataset_viewer_api.py`.

## 4. Governed export caps at 50,000 rows

A mis-click must not pull the whole book onto a laptop. The cap is stated in the
response headers and in the file itself, so a truncated export cannot pass for a
complete one.

*Where:* `EXPORT_ROW_CAP` in `backend/services/data_builder.py`.

## 5. Filters stay a fixed vocabulary

Nine operators, one field at a time. No OR, no grouping, no compound
expressions — not yet. The field must be in the governed dictionary and the
operator must be on the list; the value is compared, never concatenated.

Adding boolean composition is adding a query language, and a query language is
the thing this product promises nobody has.

*Where:* `FILTER_OPS` in `backend/services/data_builder.py`.

## 6. Synthetic data stays coherent, and stays obviously synthetic

The demonstration datasets agree with each other by construction — arrears are
derived from the facility book's own days-past-due, so a facility 90 days down
in one is Stage 3 in the other. A demonstration that contradicts itself is worse
than no demonstration.

Every dataset carries a synthetic flag through the governed catalogue, the
interface labels it wherever its figures appear, and an export says so in the
file and in its filename.

*Where:* `scripts/generate_saudi_universe.py`.
*Tested:* `tests/engine/test_arrears_analyses.py`.

## 7. Every synthetic memo extract is marked SYNTHETIC

Natural-looking wording is fine and makes the demonstration better. Wording that
could be mistaken for real client information is not.

Every extract begins `SYNTHETIC EXTRACT — `, without exception. The marker
travels with the row, because a row outlives the screen it was read on: it gets
exported to a CSV, pasted into a deck, and read by somebody who never saw where
it came from.

*Where:* `SYNTHETIC_MARKER` in `scripts/generate_saudi_universe.py`.
*Tested:* `tests/engine/test_arrears_analyses.py` — asserted across every
published period, not a sample.

## 8. Credit File Signals is not scored, and claims nothing

It counts what the notes say. It does not say whether they were right, and no
relationship between commentary and credit outcomes is established or implied.

A scored version would need real validation and real governance behind it. Until
that exists, a number would be a fabrication wearing a decimal point.

*Where:* `backend/engine/functions/arrears.py`.
*Tested:* a test asserts neither contract asserts prediction.

## 9. A domain holding datasets cannot be force-deleted

Deleting is refused while anything depends on the domain, and the refusal names
what is in the way. Remap, replace or archive first. There is no override.

*Where:* `delete_domain` in `backend/services/data_builder.py`.

## 10. An archived domain leaves engine resolution

An archived domain's datasets stop being eligible when the engine resolves a
governed purpose. An analysis quietly going on reading a book the data office
has withdrawn — and somebody finding out nine months later — is exactly the
audit finding this product exists to prevent.

Archiving is **not** deletion:

- the rows stay on disk;
- the Data Builder viewer still serves them to anybody authorised to look;
- restoring the domain puts it straight back into resolution.

Resolution refuses by naming the archived domain, rather than reporting that
nothing is authoritative — which would send a steward hunting for a dataset
sitting right there.

A failed governance read **fails open**. The archive is a curation decision, not
a security boundary, and treating an unreachable database as "everything is
retired" would take the whole product down.

*Where:* `backend/data_access/authority.py`,
`backend/services/domain_status.py`, wired in `backend/api/main.py`.
*Tested:* `tests/services/test_archived_domains.py`.

## 11. "Continue where you left off" stays quiet

Below the fold, and visually subordinate: no card, no preview line, no icon per
row. It is a way back to something, not a thing to read.

*Where:* `frontend/src/app/page.tsx`.

## 12. The grid remembers how you arranged it

Column widths, hidden columns, frozen count and row density, stored **per user
and per dataset** — on the server, not in the browser, so somebody who spends an
afternoon arranging the facility grid finds it arranged the next morning and on
the other machine.

Saving replaces rather than merges: with a merge, un-hiding a column would be
impossible, because the absence of a key would be indistinguishable from not
mentioning it.

*Where:* `grid_preferences` table (migration `0009`), endpoints in
`backend/api/routers/data_builder.py`,
`frontend/src/components/data-builder/data-grid.tsx`.
*Tested:* `tests/api/test_grid_preferences.py`.

## 13. Trace opens collapsed, with an obvious way to expand

A map wider than the canvas opens collapsed to one node per analysis, which is
the level a reader starts at. **Expand all** is a labelled button, not an icon —
"how do I see the whole lineage" is the first question a reviewer has, and an
icon they must hover to identify is not an answer. Expanding fits the view
afterwards, or the newly-revealed nodes land off screen and it looks as though
nothing happened. Zoom and Fit view remain.

*Where:* `frontend/src/components/trace/reasoning-map.tsx`.
