# Collaboration: sending work, saying things, and being told

How CreditProbe AI moves an object from the person who produced it to the
person who has to decide about it, and keeps the conversation where the
decision has to live.

Everything here is internal. There is no email, no push, no webhook. What the
product owes a user is that work addressed to them is visible the moment they
open CreditProbe — not that it arrives somewhere else first.

---

## The objects

Four things can be sent, and they are the four things that carry institutional
weight:

| Object | What it is | Versioned |
|---|---|---|
| Project | the master workspace | no |
| Investigation | one conversational thread | by message count |
| Analysis run | one execution, with a Trace | by run id |
| Saved Analysis | a run somebody kept | by analysis version |

A workflow item records the object AND the version it was at when it was sent.
A decision taken against version 3 must not silently become a decision about
version 7, and the only way to prevent that is to write down which one was in
front of the reviewer.

## The request

`POST /api/v1/workspace/workflow`

```json
{
  "object_type": "investigation",
  "object_id": "1890",
  "object_version": "2",
  "title": "Contracting Stage 2 deterioration — Q2 pack",
  "recipients": [6, 7],
  "teams": [2],
  "action": "sign_off",
  "priority": "high",
  "due_at": "2026-09-04T00:00:00Z",
  "note": "Both signatures needed before the committee."
}
```

**Recipients are a set.** People and teams, in one request. A team is a
recipient of the ITEM and a set of people for the purpose of NOTIFYING, and the
expansion happens at read time rather than being stored — somebody who joins
Credit Review today sees what Credit Review was sent yesterday.

**The action is not the state.** `action` is what is being asked FOR;
`state` is where the asking has got to. Conflating them is why a workflow list
ends up unable to distinguish an approval nobody has looked at from one that
has been granted.

### The seven actions

`review` · `comment` · `approve` · `request_changes` · `fyi` · `sign_off` ·
`assign_action`

### The nine states

| Stored id | Shown as | Meaning |
|---|---|---|
| `draft` | Draft | not sent |
| `submitted` | Sent | with its recipients |
| `opened` | Opened | a recipient has looked at it |
| `in_review` | In review | somebody has taken it up |
| `commented` | Commented | something has been said, nothing decided |
| `approved` | Approved | a judgement, and final |
| `rejected` | Changes requested | a judgement, and final |
| `completed` | Completed | the work is done — not a judgement |
| `withdrawn` | Cancelled | the sender took it back |

Two stored ids read differently from the words on screen. They are deliberately
NOT renamed: they are the state machine that projects, tests and every stored
decision depend on, and rewriting them would edit history that exists precisely
so it cannot be edited.

`opened` and `commented` are things that HAPPEN to a sent item rather than
decisions taken about it, so every open state can reach them and neither closes
anything. `approved`, `rejected` and `completed` are final for that submission:
wanting another look means sending again, which creates a new item and leaves
the first decision standing.

## The conversation

`POST /api/v1/workspace/workflow/{id}/messages`

Replies (`parent_id`), mentions (`[{"user_id": 4}]`) and attachments
(`[{"type": "investigation", "id": "91"}]`), and any message can be marked
resolved.

A message is a status as well as a message: saying something on a sent item
moves it to `commented`, which tells the sender there is something to read
without claiming a decision has been taken.

**A mention is not a comment.** Everybody on the item is notified `commented`;
anybody named is notified `mentioned` instead. An inbox that cannot tell
"somebody said something on a thread you are on" from "somebody asked you
specifically" is one people stop reading.

## The inbox

`GET /api/v1/workspace/workflow/inbox` returns five lists:

- **assigned_to_me** — open and sent to me, directly or through a team
- **sent_by_me** — open and sent by me
- **mentions** — open items where somebody named me
- **due_soon** — assigned to me, with a due date inside a week
- **completed** — closed, however it closed

## Notifications

In the header, on every screen, with an unread count. Each one deep-links to
the exact object, carrying a return context so Back comes back to the inbox.
A notification whose object type has no page renders as text rather than as a
link: a link that lands on a 404 is worse than no link, because the reader
concludes the product is broken rather than that there is nothing to open.

## Permissions

Enforced on the endpoint, not in the interface.

| Role | May |
|---|---|
| ADMINISTRATOR | everything |
| DATA_STEWARD | data workflows, publication, and review |
| ANALYST | create investigations, analyses and projects; send; comment; decide |
| VIEWER | read what is shared with them, and comment or reply |

A Viewer's one write is a comment. That is deliberate and it is load-bearing:
sending somebody an object asking them to comment on it and then refusing their
reply is a failure that would have gone unnoticed, because the request would
simply have looked unanswered.

## The audit trail

`workflow_events` is append-only. Every transition writes its own row with the
actor, the time and the comment, and there is no update path — only inserts. A
decision is evidence; editing it would make the record worthless.

## What is deliberately absent

- **External email.** A deployment decision with its own approvals.
- **Editing a message.** The thread is part of the record.
- **Deleting a decision.** Withdraw the item; the history stands.
- **A separate mentions table.** A mention lives in the message that made it,
  so there is no second place for it to exist and disagree.
