# The Arab National Bank card demonstration

One continuous story, from the product noticing something to a recommendation
somebody could take to a credit committee. It needs no preparation on the day:
launch it and the finding is already on the Cockpit.

Everything in it is **synthetic demonstration data**. Alpha Card is a
demonstration product. No figure, threshold or policy here describes Arab
National Bank, and none of it is a statement about any bank's performance.

## Running it

```
launchers/anb/start-anb.command     # frontend 5330, backend 8330
launchers/anb/stop-anb.command
```

Two digits away from the frozen 5328/8328 presentation, not one, and the
launcher refuses to start on the frozen ports, refuses to bind a port it does
not own, and stops only processes it recorded itself. The two builds are
different **checkouts** of this repository, each with its own `data/retail`, so
rebuilding one cannot move the other's numbers underneath it.

First time on a machine:

```
uv sync
.venv/bin/python scripts/build_retail_demo.py            # ~11 minutes
cp .env.anb.example .env.anb                             # edit DATABASE_URL
.venv/bin/python -m alembic upgrade head
.venv/bin/python scripts/seed_demo_users.py
.venv/bin/python scripts/bootstrap_retail_installation.py  # ~25 minutes
```

The bootstrap runs the portfolio review, which is what puts the card on the
Cockpit. Nothing else needs doing.

## The journey

**The Cockpit.** Under *Requires attention*: **Credit cards: rising population
in 1-29 DPD**, high severity. Not a default-rate finding, and it says so.

**The drawer.** Click it. The bottom line, the figures, the arithmetic behind
the severity, and the month-on-month delinquency ladder. 0 DPD is a figure
rather than a line — at roughly 84% it would flatten every bucket the case is
about onto the floor of the axis — and a link under the chart draws all five on
one axis for anyone who wants to check.

**Investigate.** The button at the bottom of the drawer. The investigation opens
with the case at the top of it: same title, same conclusion, same figures, same
chart. Then the composer.

**The five questions.** Type them, or anything close to them.

| # | Ask | What comes back |
|---|-----|-----------------|
| 1 | *Can you split the 1-29 DPD population into 1-9, 10-19 and 20-29 DPD and show me the trend?* | 20-29 DPD at 3.6x its recent baseline and 78% of the bucket; 1-9 and 10-19 flat |
| 2 | *How is the behavioural score distribution for these 20-29 DPD customers? Show me how it has moved.* | Weak and very weak from 10% to 78% of the same accounts |
| 3 | *But the behavioural score may simply be worse because these customers are already 20-29 DPD. Can you decompose the deterioration by the behavioural-model variables and tell me what is really driving it?* | 58% of the fall from variables carrying no arrears information; utilisation 42% → 97%; a quarter of the fall happened while the cohort was still current |
| 4 | *Okay, what is causing this? Where is this stress concentrated?* | Alpha Card: 27% of the book, 86% of the new cases, on a 15x gradient by origination band |
| 5 | *What should we do about it?* | A band-by-band plan in SAR, each reduction computed from that band's own excess risk |

Each answer opens with its conclusion, then its chart, then two to five
observations. Every figure is computed from the published book when the question
is asked; the same question returns the same figures.

### If a question does not land

The route is deliberately narrow and declines rather than guesses. Questions 4
and 5 name nothing on their own — "what should we do about **it**?" — so they
are answered from the card book **only inside this investigation**. Asked
anywhere else they fall through to the ordinary planner, which is the point.
Inside the thread, phrase them any way you like.

## Why the figures are what they are

**The 20-29 concentration is a mechanism, not a nudge.** Alpha Card was issued
as a campaign book on a common early-month statement cycle, so an account that
misses that cycle is 20-29 days past due at month-end rather than somewhere
uniform in 1-29. That is why 1-9 and 10-19 do not move.

**The behavioural deterioration runs ahead of the arrears.** Utilisation,
repayment and cash advances deteriorate over the quarter before the missed
cycle. This is how the book was generated, so the timing argument in the third
answer is a property of the data rather than a claim about it.

**Alpha Card changes nobody's presence on the book.** It decides which programme
each card sits in, applied to applications that were already booked. No card
vintage's exposure, ECL or staging moves because of it.

## Two questions the room will ask

**"The Cockpit also says Credit Card 30+ DPD has risen for three months. Which
is it?"** Both. The other case weights the delinquency ladder by balance; this
one counts accounts. They diverge because the cohort is drawing down its limits
— card balances rose 11% in the month — so the accounts already past due carry
more of a larger book without any more customers falling behind. The card says
so itself, in its last two sentences.

**"Is 25% off the limit a real recommendation?"** It is a policy-review
proposal, and the answer says so. The reduction applies to the **starting limit
on business not yet written**, where it is a policy parameter. A limit already
granted is contractual; what is proposed against those accounts is monitoring,
paused increases and customer contact. Reducing a limit reduces exposure at
default, not probability of default, and the answer does not claim otherwise.

## What holds it together

`backend/retail/anb_demo.py` computes every figure. The Risk Case, its drawer,
the thread header and all five answers read those functions, so the number on
the card and the number three answers later are one computation read twice
rather than two that happen to agree.

The acceptance gates are in
`tests/retail/test_ret_anb_card_investigation.py`. They assert ranges and
relationships rather than decimals, because a test pinning a figure fails the
first time anybody improves the generator and passes forever if the story
quietly stops being true.

```
.venv/bin/python -m pytest tests/retail/test_ret_anb_card_investigation.py
```
