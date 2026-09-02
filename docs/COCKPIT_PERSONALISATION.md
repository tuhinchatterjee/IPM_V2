# The Cockpit greeting

## What it is

The Cockpit opens on a greeting: *Good morning, Mr. Sajid*. The time of day
comes from the reader's own clock; the name is a **preference**, chosen by the
person being greeted and stored against their account.

The default for this installation is **Mr. Sajid**. Nothing is hard-coded into
the Cockpit — the default is one constant,
`backend/services/preferences.DEFAULT_GREETING_NAME`, and a different
deployment changes that line.

## A preference is not an identity

This is the distinction the whole design exists to hold.

**A greeting is presentation.** Which name the screen prints is a matter of
taste: "Mr. Sajid", "Dr. Ahmed", "Corporate Risk Team".

**An account is identity.** It decides permissions, ownership, approval
authority, and every line of the audit trail.

Those two must never be the same field. A greeting stored on the user record
would mean that changing what the screen says changes who the system thinks you
are, and a Trace that recorded the name somebody typed into a settings box
would not be an audit trail.

So the greeting lives in `user_preferences.preferences` under the namespaced key
`cockpit.greeting_name`, and `Account` — the identity — is not touched by
anything in the preferences module. `tests/api/test_preferences.py` asserts it
directly: the username, first name, last name, role, email, active flag, the
identity `/auth/me` reports, and the permission set are all compared before and
after a change and must be identical.

## What may be stored

Text a person will read, and nothing else. It is rendered as plain text, so
markup and control characters are **refused at the door** rather than escaped on
the way out: a value that cannot be stored cannot be mis-rendered later by a
surface that forgot to escape it.

| Accepted | Refused |
| --- | --- |
| `Mr. Sajid`, `Ms. Fatima`, `Dr. Ahmed` | empty or whitespace-only |
| `Sajid`, `Corporate Risk Team` | `<script>…</script>`, `Mr. <b>Sajid</b>` |
| `Al-Rashid`, `O'Brien` | `javascript:…`, `{{name}}`, `&lt;` |
| up to 48 characters | control characters, anything over 48 |

Whitespace is trimmed and collapsed, so `Mr.   Sajid` and `Mr. Sajid` are stored
as the same name — two people who typed the same thing should not look
different.

A refused value never overwrites the stored one.

## The control

A pencil in the top-right of the header, beside the theme, role and status
controls. Clicking it opens a compact popover: the field, a **live preview** of
what the Cockpit will actually say, and Reset / Cancel / Save.

A pencil rather than a permanently open form. Personalising a greeting is
something a person does once; a settings panel sitting on the header forever
costs every reader attention for a choice almost none of them will make twice.

Saving updates the heading **immediately** — the Cockpit and the dialog read the
same provider state, so there is no reload and no moment where the screen and
the stored preference disagree.

Reset restores the default and leaves every other preference alone.

## Where the code is

| Concern | File |
| --- | --- |
| Validation and storage | `backend/services/preferences.py` |
| API — read, set, reset | `backend/api/routers/preferences.py` |
| Provider, hook and control | `frontend/src/components/system/personalisation.tsx` |
| Where it is greeted | `frontend/src/app/page.tsx` |
| Tests | `tests/api/test_preferences.py`, `frontend/src/components/system/__tests__/greeting.test.ts` |

Every route reads and writes the **calling** user's own preferences. There is
no user id in any path, because a preference is not something one account sets
for another, and a route that accepted one would be a route somebody could use
to change what a colleague's screen says.

## Verified, and not yet verified

**Verified.** 33 backend tests (validation, persistence across connections,
per-user isolation, reset, and the identity-separation guarantees), 4 frontend
tests on the time-of-day rule, and the full request cycle exercised against a
running server with a real signed-in session:

```
PUT  /api/v1/preferences/greeting-name  {"greeting_name":"Dr. Ahmed"}
  → {"greeting_name":"Dr. Ahmed","greeting_name_is_default":false,…}
GET  /api/v1/preferences
  → {"greeting_name":"Dr. Ahmed",…}
DELETE /api/v1/preferences/greeting-name
  → {"greeting_name":"Mr. Sajid","greeting_name_is_default":true,…}
```

**Not yet verified.** The ten-step browser click-through — open the control,
change the name, save, confirm the immediate update, reload, confirm it
persisted, reset, confirm the default returns. The script exists at
`scripts/accept-personalisation.mjs`; it needs a frontend served against a
backend running with `REQUIRE_LOGIN=true` and a signed-in session, which the
sandbox run did not achieve. Reaching the Reset step requires the save to have
happened, so the last two steps are unproven in a browser even though the API
underneath them is proven.
