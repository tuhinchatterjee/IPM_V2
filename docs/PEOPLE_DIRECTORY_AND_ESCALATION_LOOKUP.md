# Finding a person: the directory, the pickers, and who an escalation reaches

*One search, used by messaging and by the Project Planner, written for the size
a real installation reaches.*

---

## 1. What was actually wrong

The messaging directory, the Planner's person-pickers and the agent's
recipient lookup were three separate queries that made the same mistake in
three places: each treated **"the first N rows that match"** as an answer.

On this installation the `users` table holds **8,599 ANALYST accounts**. That
number is what turns a tidy-looking cap into a defect:

| Symptom | Mechanism |
|---|---|
| A colleague "has no account" | `collaboration.directory` matched 7,919 rows for a role and returned 200 of them, with no count and no way to ask for the rest. The 201st person was unreachable and nothing on the screen said so. |
| An exact username did not come first | Every match was equal. Typing `a.rahman` competed on level terms with everyone whose job title contained the same letters. |
| Page two could hide somebody | Ordering was by first name alone. Every account sharing a first name came back in whatever order the database chose, so a second page could repeat or skip rows. |
| The Planner picker stopped at 500 | `copilot.people` had its own query, ordered by first name, capped at 500, with no total and **no `offset` on the route at all** — so the cap was not a page, it was a wall. |

The last row is the one that matters most, because the Project Planner's
escalation contact is chosen through that picker. A picker that cannot reach
somebody is a plan that cannot name them, and an escalation that never fires.

## 2. What replaces it

`backend/services/people.py` — one search, three guarantees.

**Ranked.** Most relevant first, and the tiers are explicit:

```
0  the term IS the username, the email, or the whole name
1  the term starts one of those
2  the term starts a word inside the name
3  the term appears inside an identity field (name, username, email, job title)
4  the term only appears in an attribute (role, team, department)
```

Tier 4 is deliberately last. **Nothing can make one of 8,599 analysts more
relevant than another**, which is why a role belongs to `role=` — a filter,
with a total and pages — rather than to the search box.

**Total-ordered.** The ordering ends in `User.id`, so no two rows ever tie.
That is what makes paging safe: page two cannot repeat page one, and nobody
can fall between two pages.

**Complete, and honest about it.** Every answer carries `total`, `limit`,
`offset` and `has_more`. `MAX_PAGE` is 500, and it is a page size, not a
limit on what is reachable — `offset` walks all of it.

Three ways in, chosen by what the caller already knows:

| Function | For | Guarantee |
|---|---|---|
| `search(...)` | somebody typing | ranked, paged, counted |
| `by_id` / `by_ids` | anything that already knows | exact, never paged, no cap |
| `resolve(identifier)` | an id, username or email | exact or `{}` — it never guesses |

**Two projections, so a picker cannot become a scrape.**
`DIRECTORY` carries email, job title, department and team. `CONTACT` — what
the Planner sees — carries exactly `user_id`, `name`, `username`, `role`.
Nothing else. Not the email, and not `is_active` either: whether somebody has
left is a quieter way of saying the same private thing.

## 3. Where it is now used

| Caller | Path |
|---|---|
| `collaboration.directory` / `directory_page` | `people.search(projection=DIRECTORY)` |
| `collaboration.recipient` | `people.resolve` |
| `GET /messages/directory` | paged, filtered, counted; `?role=`, `?team=`, `?department=` |
| `GET /messages/directory/{identifier}` | exact lookup, 404 when it is not certain |
| `copilot.people` (Planner pickers) | `people.search(projection=CONTACT)` |
| `copilot.person` | `people.by_id(projection=CONTACT)` |
| `GET /planner/copilot/people` | **now takes `offset`** — this was the wall |
| `monitor._names` (the agent naming an owner or a recipient) | `people.by_ids` — by id, never by search |

The escalation path is by id from end to end. A plan stores
`escalation_id`; `escalation.findings` returns the rung holding that id; the
sweep writes a `Notification` to that id and resolves the display name with
`by_ids`. **No part of delivering an escalation searches for a name.**

The message footer now says whose desk it stopped on:

```
Escalation: Zeynep Yilmaz (the project's escalation contact)
```

The rung alone said how far the message travelled but not who now holds it,
and a forwarded escalation with no name on it is one everybody assumes is
being handled by somebody else.

## 4. What the UI says now

Both pickers report what they are not showing:

* the message composer — *"Showing 50 of 8,601 people — type more of a name,
  username or email to narrow it."*
* the Planner person-picker — *"Showing 50 of 8,601 matches — type more of the
  name, username or email to narrow it."*

A truncated list that does not say it is truncated reads as "this is
everybody", and that is exactly how somebody concludes a colleague has no
account.

## 5. Evidence

`tests/services/test_people_search.py` — 18 tests against a **module fixture of
8,000 real inserted users** plus one account planted deliberately late in the
alphabet. It proves: the total is the truth rather than the page size; walking
pages reaches everybody exactly once; two identical queries return the same
sequence; page boundaries neither overlap nor drop; an exact username, email,
whole name and name-prefix each rank first; a role search ranks last; `by_ids`
resolves 1,000 ids at once; `resolve` refuses to guess; the CONTACT projection
never carries an email; a suspended account is not offered but is still
resolvable by id; and no password hash ever leaves the service.

`tests/planner/test_escalation_recipient.py` — 8 tests against another 8,000-user
fixture, including the end-to-end HTTP proof: publish a project whose escalation
contact is the 8,001st name, put a task 8 days past its date, `POST
/api/v1/planner/projects/{id}/sweep`, then read the `notifications` table and
assert the message landed **on that account**, names the project code, names
`M01-T01`, carries the contact's own name — and that **zero** accounts outside
the plan were told about it.

`tests/api/test_messaging_corrections.py` — the directory suite, including the
search-every-field test that first failed. For identity fields (first name, job
title, email, username) it still asserts the account appears in a ranked page.
For **group** fields (role, team) it now asserts something stronger than the
original: walk every page of the filter, and require that no page repeats an
account, that the walked set has exactly `total` members, and that the intended
account is among them. That is reachability and completeness, where the original
asserted only presence in the first 200 rows.

> This is the one place the fix departs from the literal wording of the earlier
> test, and it is deliberate. No ranking can put one of 8,599 equal role-matches
> in a first page; asserting that it does would be asserting a coincidence. The
> replacement is a strictly stronger claim about the same defect.

## 6. What is NOT covered

`GET /users/directory` — the *share* picker's source — still returns the whole
user table in one response and filters in the browser. It is complete and
deterministically ordered, so it does not hide anybody, but it does not scale:
on this installation that is an 8,600-row payload. It is a separate endpoint
with a different shape (people **and** teams) and a different consumer, and it
was out of the scope of this fix. Moving it onto `people.search` is the obvious
follow-up.

## 7. The live run, over real HTTP

`scripts/acceptance/directory_lookup.py` does the same thing against a
*running server* rather than an in-process app: it creates 8,000 accounts and
one escalation contact, signs in with real session cookies, drives the public
routes, and takes its accounts away again afterwards.

```
python -m scripts.acceptance.directory_lookup --api http://127.0.0.1:8099
```

The run on this HEAD:

```
Creating 8,000 accounts and one contact (tag 9774d605)…
  PASS  an exact username finds the intended account, first
        total=1 first=z.proof-9774d605
  PASS  the directory says how many it did not show
        showed 25 of 8001
  PASS  offset reaches the account that sorts last, on the page the service says it is on
        the contact is #8,000 of 8,001; asked for offset 7997 and they were row 3
  PASS  the same request twice returns the same slice
        40 rows, identical
  PASS  the Planner picker never hands back an email address
        fields: ['name', 'role', 'user_id', 'username']
  PASS  the agent ran over the published project
        HTTP 200
  PASS  the escalation contact, signed in, sees the escalation
        1 message(s) about PRF-9774D
  PASS  it names the overdue item, and says whose desk it stopped on
        PRF-9774D: Escalated to you M01-T01 Overdue work was due 2026-09-03 and
        is 8 days overdue. The owner has not resolved it. You are seeing this
        because you are the project's escalation contact. …
  PASS  nobody outside the plan was told about it
        0 leaked
Removing the accounts this proof created…

9 of 9 checks passed.
```

The work belonged to somebody else; the escalation contact was the account
that sorts **8,001st**; the chase reached them, signed in, in their own
notifications, and reached nobody else.
