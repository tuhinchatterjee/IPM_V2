# Adversarial review

The Data Builder release path read as somebody trying to break it, rather than
as somebody using it. Four defects were found; all four are fixed and each one
has a test that fails on the code that shipped before it.

Every case listed under **Held** was checked in the same pass and found sound.
Nothing here is asserted from reading the design — each line was probed.

---

## Found and fixed

### A period label reached the filesystem unsanitised

A period arrives from an upload form and reaches disk twice: the staging
directory and the published partition. The staging path stripped `/`; the
partition path stripped nothing at all; and neither stripped a dot segment.

    period = "../../../../tmp/pwned"
    → /home/user/IPM_V2/data/analytics/ifrs9_staging/period=../../../../tmp/pwned
    → resolves to /home/user/IPM_V2/data/tmp/pwned          — outside the lake

A data steward could write a parquet file anywhere the process could reach.
Sanitising the two paths separately is how a hole like this reopens, so the
label is now checked once, at the door, against a positive pattern — letters,
digits, spaces, dots, hyphens, underscores, bounded length, no dot segment —
and re-checked at publication, with the resolved partition asserted to be
inside the analytics directory.

Proved by `TestAPeriodLabelCannotReachOutOfTheLake` and
`TestTheUploadRouteRefusesItToo`.

### The release history answered anybody who asked

`GET /data-builder/datasets/{name}/periods` named no principal. Every other
route on that router does. Against the live server it returned HTTP 200 to an
unauthenticated caller, with the source filenames, checksums, who uploaded and
reviewed each version, and what the checks found.

It now requires a data steward, and a test asserts the declared dependency of
every route the period lifecycle added — on the declaration rather than on a
live 401, because a test client is configured to be signed in, so a route that
lost its dependency would answer 200 in a test and 200 to a stranger in
production.

Proved by `TestEveryReleaseRouteNamesWhoMayCallIt`.

### The period upload had no size cap

Every other upload route on the router applies `settings.max_upload_bytes` and
returns 413. This one read the whole body into memory with no ceiling, which is
a way to take the process down with a single request. The cap is applied, with
the same wording.

Proved by `TestAnUploadIsBounded`.

### Publishing a period left no audit record

Publishing changes what every later answer is computed from. It is the most
consequential action on that screen and it was the only one that wrote nothing
to `collaboration_audit`. A `DATA_PERIOD_PUBLISHED` row is now written inside
the same transaction as the publication — so the log cannot say it happened
when it did not — naming the actor, the dataset, the period, the version, the
row and field counts, the source filename and its SHA-256, and whether the
checks passed.

Proved by `TestPublishingLeavesARecord` in the release loop.

---

## Held

Each of these was on the list to break, and did not break.

| Risk | What was checked | Result |
|---|---|---|
| Hard-coded proxy values | Every corpus figure grepped across `backend/` | Only in a docstring explaining a defect; none reaches output |
| Hard-coded dataset lists | Catalogue, Data Builder and Ask read paths | All read the live governed catalogue; the fixed names that remain are declared blueprints and vocabulary, not resolution |
| One-chart assumptions / chart spam | `package.kinds_for` | Blocks follow `visualize`'s own decision; a table stands alone unless the chart leads |
| Wrong data version | Period releases supersede rather than overwrite | Superseded rows kept with `superseded_by_id`; the loop asserts it |
| Wrong period | Publication writes one partition | The loop asserts the other fifteen quarters are untouched |
| Dropped predicates, incorrect grain | Protected baseline groups `multi-condition`, `answer-grain` | 137 and 68 tests, green |
| Stale context | Protected baseline group `context-carry-forward` | 75 tests, green |
| Unsupported AI claims, untraceable figures | Protected baseline group `ecl-decomposition`, evidence gate | 115 tests, green |
| Schema bypass on upload | `check()` reads the dataset's own contract | Undeclared fields, missing declared fields, mixed periods and duplicate keys all refused |
| Unauthorized publication | Route dependencies | Staging, review, lock and discard are a steward's; publication is a publisher's |
| IDOR on a release id | Release routes | Authorisation is by role, which is this platform's model throughout; a release id names no user's private object |
| Version overwrite | `publish()` | Supersedes and records; never deletes |
| Duplicate events | `publish_data_release_event` | Idempotent on its event key; returns the existing message |
| Stale notification counts | Protected paths H0–H4, M1 | 3 → 2 → 1 → 0, header agrees, survives a reload |
| N+1 | `history()` | One query, ordered in the database |
| Unbounded preview queries | `PREVIEW_ROWS` 20, `PREVIEW_ROWS_MAX` 50, rows route `le=500` | Every read path capped |
| Page overflow | Protected paths and the Data Builder gate at 1440px | No horizontal overflow on any checked page |
| Broken sharing of multi-block results | `TestSharingKeepsEveryBlock` | The recipient's stored package carries every block, not the first |
| Secrets | `ANTHROPIC_API_KEY` across backend and frontend | Server-side only; redacted from failure responses; `.env` ignored by git |
