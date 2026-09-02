# The internal workflow: users, mailboxes, and governed object sharing

CreditProbe could produce analysis and could not hand it to anybody. This is the
part a credit team actually runs on — an administrator who can create
colleagues, a private mailbox for each of them, and messages that carry governed
CreditProbe objects rather than a link and a hope.

Read this before changing anything under `backend/services/collaboration.py`,
`backend/models/collaboration.py`, or `frontend/src/components/messages/`.

---

## 1. What was reused, and what was deliberately not

| Existing thing | Decision |
| --- | --- |
| `users` table (`backend/db/models.py`) | **Reused.** There is no second identity. A participant is a `users.id`, a sender is a `users.id`. Extended with `job_title`, `department`, `updated_at`, `deactivated_at`, `deactivated_by`. |
| Session cookie + `Account` (`backend/api/auth.py`) | **Reused unchanged.** No new authentication. |
| `Role` / `Principal` / `require()` (`backend/api/permissions.py`) | **Reused unchanged.** Nothing here can grant a permission the registry does not already recognise. |
| `notifications` table | **Reused.** A message writes a Notification row through the same path everything else uses, so the header badge does not fork into two numbers that disagree. |
| `workflow_items` + friends | **Left alone.** That model is ANCHORED: every row is a review of one governed object, and `object_type`/`object_id` are the reason the row exists. Right for "certify this analysis"; wrong for "here are three things, please look before the committee". |
| `Investigation`, `SavedAnalysis` | **Read, never modified.** Sharing writes a grant beside them. |
| `publish_dataset` (Data Builder) | **Untouched.** The new event hook is called BY a publisher; it does not reach into one. |

**Why a second model beside `workflow_items` rather than a widening of it.** A
message has a subject, a body, zero or many attachments of *different* kinds,
and it is addressed to a PERSON rather than raised against an object. A message
with no attachment is still a message; a certification with no covering note is
still a certification. Forcing both through one table would have made
`object_type`/`object_id` nullable, which is the point at which the column stops
meaning anything.

---

## 2. Authorization: participation, and only participation

A `thread_participants` row is the **only** thing that lets anybody read a
thread. Not the sender, not a role, not a URL somebody was given.

Two consequences worth stating plainly:

* **A thread you are not in returns what an absent thread returns.** `NotFound`,
  not `NotPermitted`. "You may not read thread 4193" confirms that thread 4193
  exists and that somebody is talking in it, and an inbox that answers that
  question for strangers leaks its own shape. The same rule governs drafts and
  file downloads.
* **An ADMIN is not a participant in other people's conversations.**
  Administering users and reading their mail are different powers, and
  collapsing them would make the inbox a place nobody says anything real in.
  Where governance genuinely needs to see who sent what, `collaboration_audit`
  answers it without exposing bodies.

Every read path in the service starts with `_must_participate`. The router
contains no authorization logic at all — it resolves the calling user and hands
the id down. There is no user id in any messaging path for that reason: a route
that took one would be a route somebody could point at a colleague.

### Object sharing is a grant, not a link

Sending an investigation does not make it public and does not copy it. It writes
an `object_shares` row and a snapshot of what the object looked like at the
time. `can_read_object` consults, in order: ownership, an un-revoked grant,
then ADMIN.

The sender must already be able to read it — checked at ATTACH time, so the
refusal names the object rather than arriving as a silent gap in the
recipient's inbox. You cannot share your way into giving away something you
were never shown.

`revoked_at` rather than a delete: "who has access today" and "what was shared
with whom in March" are different questions, and a bank needs both answerable
from the same table.

---

## 3. Three properties the schema holds, not the code

These are database constraints because a guard that lives in one function is a
guard a second caller walks around.

1. **A system message has no user behind it.**
   `CHECK ((sender_type='SYSTEM' AND sender_user_id IS NULL) OR (sender_type='USER' AND sender_user_id IS NOT NULL))`.
   No request body and no future service can dress a person up as the product,
   and there is no "CreditProbe AI" account for an administrator to sign into.
2. **One publication is one message.** `event_key` is UNIQUE. A release replayed
   after a restart or a retry hits the index and returns the message that
   already exists.
3. **An attached file is bytes this database holds.** `message_artifacts.content`
   is `BYTEA` with a SHA-256. A path under `/tmp` is a working attachment until
   the first restart and a 404 for the rest of the object's life.

---

## 4. The data model

```
message_threads       subject, origin (USER|SYSTEM), message_count, last_message_at
  messages            sender_type, sender_user_id, body, status (draft|sent),
                      request_type (fyi|review|action), request_status,
                      priority, due_at, event_key, actions, context
    message_recipients  user_id, kind (to|cc)      — written at SEND, not compose
    message_attachments attachment_type, object_id, object_version,
                        artifact_id, label, meta   — meta is a SNAPSHOT
  thread_participants   user_id, addressed, read_at, archived_at

message_artifacts     filename, content_type, size_bytes, sha256, content
object_shares         object_type, object_id, user_id, granted_by, revoked_at
request_status_events message_id, from_status, to_status, actor_id, note
collaboration_audit   action, actor_type, actor_id, object_type, object_id,
                      subject_user_id, detail
```

Migration **0032**, single head.

**Why `read_at` and `archived_at` are on the participant, not the message.** An
inbox is a personal view of shared content. One reader marking a thread read
must not mark it read for everyone, and one person filing a conversation away
must not remove it from anybody else's inbox.

**Why a draft has no recipients.** The addressee list on an unsent message is
part of a private document. Writing `message_recipients` at compose time would
put a row in somebody's name for a message they may never be sent. Recipients,
participation, share grants, the notification and the audit row are all written
in one transaction at SEND — which is also the moment the body stops being
editable.

---

## 5. Workflow: three kinds, four states

`FOR INFORMATION` · `REQUEST REVIEW` · `ACTION REQUIRED`

A risk team needs to tell those three apart; it does not need a nine-state
approval ladder to do it, and the ladder that genuinely needs one already exists
in `workflow_items`.

```
open ──→ in_review ──→ responded ──→ closed
  └──────────────────────↗    ↖────────┘  (responded may be reconsidered)
```

Nothing returns to `open`, and `closed` is terminal. A transition the machine
does not allow is refused with a message naming what IS allowed. Every move
writes a `request_status_events` row: "it says Responded" is a much weaker fact
than "she moved it to Responded on the 4th, and this is what she said".

---

## 6. CreditProbe as a sender

`send_system_message` is the only way the product writes to anybody. It accepts
no sender parameter — impersonation is not something the function can express.

### The Data Builder hook

```python
from backend.services.collaboration import publish_data_release_event

publish_data_release_event(
    session,
    dataset="portfolio_facility",
    dataset_label="Corporate IFRS 9",
    domain="corporate_credit",
    period="Q3 2026",
    previous_period="Q2 2026",     # omit → no "Compare" button
    version="7",                    # part of the idempotency key
    row_count=16_521,               # omit → the message does not claim one
    borrower_count=4_128,           # omit → the message does not claim one
    validated=True,                 # None → says "published", not "validated"
    published_at="2026-09-02 12:00 UTC",
    published_by_id=steward.id,
    recipients=[...],               # omit → the governed default, below
)
```

**Call it once, after the release is durable.** Every fact is a parameter and
nothing is looked up behind the caller's back. This is the integration contract
Data Builder 2.0 should call; Data Builder itself is unchanged by this work.

Three rules the composer follows:

* **A count nobody supplied is absent, not estimated.** Same rule the answer
  path lives by: a reader must be able to trust a number in a CreditProbe
  message the way they trust one in an answer.
* **"Validated" is claimed only when the publisher said so.** `None` means they
  did not record an outcome, and the message says the narrower thing.
* **An action appears only when the product can honour it.** "Compare with the
  previous quarter" needs a previous quarter; without one the button is absent
  rather than present and then apologetic.

### Who is told

`data_release_recipients()`, in order:

1. If the publisher named people, those people. An explicit choice at
   publication time is the most accurate signal there is.
2. Otherwise everybody holding a role that can act on new data — ADMIN,
   DATA_STEWARD and ANALYST. A VIEWER is not notified: a dataset arriving is not
   a thing they can do anything about.

Not "everybody", on purpose. A notification everyone receives about everything
is one everyone learns to dismiss, and the first thing dismissed with it is the
one that mattered.

### Actions the CTAs perform

| Action | What it does |
| --- | --- |
| `open_dataset` | Opens the Data Builder browser on that dataset. |
| `start_investigation` | Opens the Cockpit composer pre-filled with a question about THIS dataset at THIS period, carrying structured `context`. |
| `compare_previous_period` | Same, with both periods named. Offered only when a previous period is known. |

---

## 7. Audit

Written inside the caller's transaction, so a record cannot outlive a
rolled-back action.

`USER_CREATED` · `USER_UPDATED` · `USER_DEACTIVATED` · `USER_REACTIVATED` ·
`MESSAGE_SENT` · `MESSAGE_REPLIED` · `MESSAGE_READ` · `MESSAGE_ARCHIVED` ·
`OBJECT_SHARED` · `FILE_DOWNLOADED` · `WORKFLOW_STATUS_CHANGED` ·
`SYSTEM_NOTIFICATION_CREATED`

Deliberately **not** surfaced in the conversational UI. It is evidence for the
governance surfaces; an inbox that narrates its own audit log is an inbox nobody
can read.

---

## 8. Files

Whitelisted by extension (`.xlsx .xls .csv .pdf .docx .txt .json .png .jpg
.jpeg`), capped at 25 MB, hashed on the way in. The whitelist is the security
control and the hash is the governance one; neither substitutes for the other.
Nothing executable is on the list, and a blacklist of executables is a list
somebody always finds one more item for.

Download authorization is checked **per request** against participation in a
thread the file hangs off, so losing access to a conversation loses access to
its attachments. A creator may always fetch their own upload back.

---

## 9. Performance

The list endpoint returns counts and kinds; the thread endpoint returns content.
A fifty-row inbox that loaded fifty workbooks to draw itself is a page nobody
waits for.

`_thread_summaries` issues a **fixed** number of queries whatever the page size
— the threads, my participation, the last sent message of each, the attachment
counts, and the people named — rather than walking the ORM relationship per row.
Indexes: `ix_thread_participants_inbox (user_id, archived_at, read_at)`,
`ix_messages_thread`, `ix_messages_drafts`, `ix_message_recipients_user`,
`ix_object_shares_user`.

Search is a `LIKE` over subject, body and attachment label, always **inside**
the participation join. Not applied after it: a search that finds a thread and
then hides it has already told the searcher that the thread exists. Indexed
full-text search is the right answer at a scale this product is not at, and
building it now would be infrastructure ahead of need.

---

## 10. Security model, and what it was tested against

`tests/api/test_messaging_security.py` runs the matrix over HTTP with three
separately signed-in people, with `REQUIRE_LOGIN=true`:

* A cannot read a B↔C thread, and the refusal is indistinguishable from an
  absent one.
* A cannot read, edit or send B's draft.
* A cannot download an attachment from a thread they are not in, by any id.
* A cannot attach somebody else's stored file.
* A cannot share a governed object they cannot read.
* A non-admin cannot create a user, and the messaging feature opened no side
  door into administration.
* A header cannot replace a session.
* No refusal leaks a stack trace, a SQL fragment or a provider name.

---

## 11. The SSO boundary

**There is no enterprise SSO here, and nothing in this work claims there is.**

Authentication today is a username, an Argon2 password hash and a signed session
cookie, with a header-based role switch that `REQUIRE_LOGIN=true` closes. That
is a real local authentication model and it is not an identity provider.

What this work does is make the application-level user model clean enough to sit
behind one later: `users.id` is the only identity anything references, and
nothing in the messaging or sharing layer reads a username, an email or a role
string to make an authorization decision. An SSO adapter that maps an external
subject to a `users.id` — creating the row on first sign-in — is the whole
integration. No table below `users` would change.

---

## 12. Known limitations

Truthfully, and none of them hidden:

1. **No DataVersion rows on a script-built lake.** The demonstration lake is
   built by `scripts/generate_saudi_universe.py` and friends, which write
   Parquet directly rather than going through `publish_dataset`. So
   `seed_data_release` falls back to the governed catalogue for the period and
   the row count. Both are measured, neither is composed, but the message
   carries no `validated` claim and no publisher name on such a deployment —
   because nobody recorded them.
2. **Search is `LIKE`, not an index.** Correct and authorization-safe; it will
   want a trigram or full-text index before a mailbox reaches six figures.
3. **No forward.** Reply and reply-to-thread are implemented. Forwarding a
   message to somebody outside the thread would need a decision about whether
   the attachments' share grants travel with it, and inventing that answer
   without asking would be exactly the silent permission escalation §8 of the
   brief forbids.
4. **No CC-only distinction in the UI.** The API accepts `cc` and stores the
   distinction; the thread view lists participants without separating them.
5. **Attachment upload is one file at a time.** Multi-select would be a
   frontend change only.
6. **`report` attachments share the file path.** A generated PDF or DOCX is
   attached as stored bytes with `attachment_type: "report"`. There is no
   integration yet that pushes an export into a message automatically — a user
   downloads it and attaches it.
7. **No external email, Slack or push.** Out of scope, and deliberately so: the
   product's promise is that work addressed to you is visible when you open
   CreditProbe.
