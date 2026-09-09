# The internal workflow: users, mailboxes, and governed object sharing

CreditProbe could produce analysis and could not hand it to anybody. This is the
part a credit team actually runs on — an administrator who can create
colleagues, a private mailbox for each of them, and messages that carry governed
CreditProbe objects rather than a link and a hope.

Read this before changing anything under `backend/services/collaboration.py`,
`backend/models/collaboration.py`, or `frontend/src/components/messages/`.

---

## 0. Three concepts, and the boundaries between them

The 1.1 correction exists because these three had blurred into each other. They
are separate, and the separation is the product:

### A. MESSAGES — all communication between people

Everything one person sends another is a message and stays a message. Plain
text, a shared analysis, an investigation, a report, a workbook, a review
request, an action request, a notification from CreditProbe itself. **What a
message CARRIES never changes what it IS.** A message with an analysis attached
is not "a shared analysis" filed somewhere else; it is a message that carries an
analysis, and it lives in the same Inbox and the same Sent as every other
message. Moving a review request from Open to Responded does not move the
conversation out of anybody's mailbox either — a request is a message with a
state, not a record in a different system.

Mailboxes are views over those messages, never folders a message is moved
between: **Inbox, Sent, Drafts, Archived, Action required.**

### B. WORKFLOW — administrative oversight, and nothing else

`/workflow` is an **administrator-only operational view of how work is running
across the institution**. Who is active, who has unread work piling up, whose
review requests have gone past their date, who has stopped signing in. Per user:
role, team, job title, status, last active, message activity counts, shared
object counts, and a link to Administration → Users.

It is **not a mailbox**. No conversation is listed there, no message is
relocated there, and there are no mailbox tabs on it.

It is **not surveillance**. There is no subject line and no message body
anywhere in it, because there is no route that would return one to an
administrator. Reading a conversation requires being in it, and administering an
account is not being in it. Where governance genuinely needs to know who sent
what to whom, `collaboration_audit` answers that by act rather than by content —
and `tests/api/test_messaging_corrections.py` sends a message with a unique
string as its subject and body, then asserts that string appears in neither the
overview nor the per-user profile.

Non-administrators do not see Workflow in the sidebar, and
`/api/v1/messages/admin/*` refuses them at the route. The navigation is the
courtesy; the route is the control.

A person's own review queue — what has been sent to *them* for approval, what
*they* are waiting on — was never oversight, and now lives at **`/reviews`**
("My reviews"), which everybody sees.

### C. NOTIFICATIONS — derived, never a separate truth

Every badge, tab, tile and card in the product reads **one** endpoint,
`GET /api/v1/messages/counts`, through **one** frontend store,
`frontend/src/lib/attention.ts`. Nothing else fetches counts. Reading a message
refreshes that store, and the header badge, the mailbox tab, the summary tile
and the workspace card all move together, immediately, with no reload and no
route change.

Before the correction each of those four fetched its own number, and they
drifted the moment one of them forgot a predicate — which is how a badge
survives a message being read. A count that is sometimes wrong is worse than no
count, because the reader cannot tell which time it is.

**The audit of every badge in the header**, since there are two and they used to
overlap:

| Badge | Shows | Source |
| --- | --- | --- |
| Envelope (`UnreadMessages`) | unread conversations + open requests addressed to me | `attention_summary`, via the shared store |
| Bell (`NotificationCentre`) | everything else that happened — an agent run, a data release, a review raised against an object, being named on a workflow item | `workflow.notifications`, excluding `object_type = 'message_thread'` |

They are now **disjoint**. Delivering a message still writes a `notifications`
row — that row is the record that the person was told, and the audit and the
message itself depend on nothing here — but the bell no longer counts it,
because the envelope already does. A reader with one unread message used to see
a 1 and a 20 with no way to tell whether they were about the same thing.

---

## 0a. The mailbox contract

Each mailbox is one predicate, evaluated in the backend. Nothing below is a
frontend filter over a wider result, and nothing below is decided by workflow
state.

| Mailbox / count | Predicate |
| --- | --- |
| **Inbox** | a `thread_participants` row for me with `addressed = true` and `archived_at IS NULL`. One row per conversation. |
| **Unread** | the above, with `read_at IS NULL`. |
| **Sent** | `messages.sender_user_id = me AND status = 'SENT'`. What I sent — never what happened to it afterwards, and never derived from `request_status`. |
| **Drafts** | `messages.sender_user_id = me AND status = 'DRAFT'`. A draft has no recipients until it is sent. |
| **Archived** | addressed participation with `archived_at IS NOT NULL`. Archiving is a fact about MY copy; the conversation stays in everybody else's Inbox. |
| **Action required** | distinct SENT messages naming me in `message_recipients` whose `request_type` is `review` or `action` and whose `request_status` is still open. A filter over messages, not a queue they were moved into. Being copied into a thread is not being asked to do something. |
| **Shared with me** | un-revoked `object_shares` rows in my name. |

Three consequences worth stating, because each was a reported defect:

* **Sending to yourself is a real send.** People mail themselves constantly — to
  file a result where they will see it tomorrow, to keep a copy of what they
  sent a colleague, to check a share works before using it on somebody else.
  A self-addressed message appears **once in Sent and once in Inbox**, unread,
  and any governed object on it is granted to the sender like any other
  recipient. `_resolve_recipients` deliberately does not filter `sender_id`;
  previously it did, which left the message with no recipients at all and the
  send was then refused as empty.
* **The author's own message is never unread to them.** Starting a conversation
  writes the author's participation with `addressed = false`, so it does not
  appear in their own Inbox — unless they addressed themselves, in which case
  the recipient loop finds that same row and flips it, and the two cases become
  indistinguishable, which is what "I sent this to myself" means. Writing a
  reply also marks the author's own row read: their own words must never appear
  in their own unread count.
* **Action required lists conversations; the count counts requests.** One
  conversation can hold two open requests, so the list is the smaller of the
  pair. Every other count equals the total of the box it names, and
  `TestOneSummaryReconcilesWithTheBoxes` asserts exactly that.

### Sending twice is sending once

The composer mints a `client_token` on the first press of Send and reuses it for
any retry. The backend stores it in the same unique `event_key` column system
messages use, so a double-click or a request the browser retried after a timeout
collides at the index and returns the first message rather than delivering a
second copy. A send with no token is not collapsed — two genuinely repeated
messages are two messages.

### Sharing is picked, not pasted

`GET /api/v1/messages/shareable?object_type=analysis` returns the governed
objects **this sender can actually read**, as cards. Every one has been through
`can_read_object` for the person asking, so a card that appears can be attached
and a card that cannot be attached does not appear. Pasting a URL was a guess
that could point at something deleted, something the sender could not read, or
something that was not an analysis at all — and the sender found out only when
the send failed.

---

## 1. What was reused, and what was deliberately not

| Existing thing | Decision |
| --- | --- |
| `users` table (`backend/db/models.py`) | **Reused.** There is no second identity. A participant is a `users.id`, a sender is a `users.id`. Extended with `job_title`, `department`, `updated_at`, `deactivated_at`, `deactivated_by`. |
| Session cookie + `Account` (`backend/api/auth.py`) | **Reused unchanged.** No new authentication. |
| `Role` / `Principal` / `require()` (`backend/api/permissions.py`) | **Reused unchanged.** Nothing here can grant a permission the registry does not already recognise. |
| `notifications` table | **Reused.** A message writes a Notification row through the same path everything else uses. The unread MESSAGE count is a separate and more precise question, answered by `attention_summary` — see §0C. |
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

Truthfully, and none of them hidden.

**Closed by the 1.1 correction** (kept here so the history is legible): the
recipient directory returning nothing until something was typed; a
self-addressed message being refused as having no recipients; the personal
review queue occupying the Workflow page; four independent count fetches that
drifted; and the sender of a governed object not being granted it.

**Still open:**

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
   distinction; the thread view lists participants without separating them, and
   the composer offers no CC field.
5. **Attachment upload is one file at a time.** Multi-select would be a
   frontend change only.
6. **`report` attachments share the file path.** A generated PDF or DOCX is
   attached as stored bytes with `attachment_type: "report"`. There is no
   integration yet that pushes an export into a message automatically — a user
   downloads it and attaches it.
7. **No external email, Slack or push.** Out of scope, and deliberately so: the
   product's promise is that work addressed to you is visible when you open
   CreditProbe.
8. **Unread is counted per conversation, not per message.** One Inbox row is one
   conversation, opening it reads everything currently in it, and the badge
   counts rows. A thread with three unread replies counts once. This is
   deliberate — the number matches what the reader sees in the list — but it is
   a choice, not an inevitability, and a per-message count would need a
   `message_reads` table rather than a `read_at` on participation.
9. **Development databases carry test-fixture accounts.** A database that has
   had the suite run against it accumulates users with no name and no email.
   They are real rows and are not deleted, so the directory ranks named,
   reachable people first rather than hiding anybody. On a clean deployment the
   ranking is a no-op.
10. **The admin overview pages at 500 users.** Nine grouped aggregates,
    independent of the number of users, then one page of rows. Beyond a few
    thousand accounts the per-user counts would want materialising rather than
    recomputing on each load.
