# Cross-capability review

Every module in this platform has its own tests, and they pass. This document
is about the joins between them — the places where two capabilities that each
work produce, together, something that does not.

Five flows were walked end to end through the real routes against the real
governed data. Three were already sound. Two were not, and a third defect fell
out of the second while it was being fixed.

---

## The flows, and what they proved

### 1. Data Builder → catalogue → Ask

**Sound.** A period published through the Data Builder lifecycle is answerable
by Ask before anybody restarts anything: publication refreshes the governed
catalogue and extends the period coverage the analytical engine reads.

Proved by steps 7 to 11 of `tests/api/test_data_release_loop.py`, which
publishes a real quarter into `ifrs9_staging` and then asks five questions
about it — what periods exist, show me the new one, a figure at it, a grouped
analysis at it, and a comparison with the quarter before.

### 2. Data Builder → Messages

**Sound.** Publication announces itself through Messages, the announcement is
in a real inbox, opening it reduces that reader's unread count, and it carries
a call to action the product can honour.

Proved by steps 12 to 14 of the same file.

### 3. A multi-analysis investigation → save → share → the recipient

**Sound.** An investigation with several analytical blocks arrives with all of
them. The recipient reading one chart where the sender saw five is the sharing
defect that class exists to prevent, and it is asserted on the stored package's
own block count rather than on the first block.

Proved by `TestSharingKeepsEveryBlock` at the end of the same file.

### 4. Ask → the dataset a conversation established → the analysis that follows

**Was broken. Fixed.** See P4-1 below.

### 5. A saved investigation, after the data underneath it moves

**Was broken. Fixed.** See P4-3 below.

---

## P4-1 — the book a conversation is reading did not reach the next question

**What happened.** A reader who asked about one dataset and then asked an
analytical question was answered from a different dataset, with nothing on
screen saying so.

Concept resolution binds each concept in a question to one governed field
before the base dataset is chosen, and it took the *declared default* candidate
regardless of what the conversation had established. Thirty-one governed
concepts in this installation live in more than one dataset — twelve-month PD
is in both `ifrs9_staging` and `portfolio_facility`, internal rating is in both
`customer_ratings` and `portfolio_facility` — so the reader's choice of book
was silently overruled on every one of them.

`ConversationState.datasets` was filled only by a previous *analysis*, so a
thread that established its dataset by asking about it carried nothing at all.

**The fix.** The dataset a thread is reading is now a preference, threaded from
working memory through the planner into both concept resolution and base
selection. It is deliberately weak:

- an explicit qualifier in the sentence still wins outright;
- a steward's declaration that a source is authoritative still wins;
- `_base_dataset` still ranks the reporting calendar first, then how much of
  the question's scope a source can express, and only then this;
- a preferred dataset that does not carry the concept is ignored entirely;
- every use of it is written into the match's reason, so the answer says which
  source it read and why.

The order within the preference is the analysis that ran, then the datasets the
conversation merely looked at.

**Proved by** `TestTheThreadsDatasetSettlesAConcept`,
`TestThePreferenceIsOnlyEverATieBreak` and `TestTheWholeThread` in
`tests/orchestration/test_cross_capability.py`. The last of these walks the
seam as a reader meets it: the same question reads `ifrs9_staging` on its own,
`portfolio_facility` after the thread named the facility book, and
`ifrs9_staging` again after the thread named that one.

## P4-2 — a dataset name the catalogue does not hold was answered with the catalogue

**What happened.** "Show me the Facility Master dataset" — a name a bank might
well use internally, and one no governed dataset here carries — was answered
with "There are 77 governed datasets, holding 6,953,276 rows". That answers a
question nobody asked, and it hides the thing the reader most needs to know:
that the name was not recognised.

The sentence resolved no dataset, so it fell past the dataset branch and was
picked up by the general metadata route as a question about the book.

**The fix.** A sentence that names a dataset the catalogue does not hold is now
told so, with the nearest governed names offered. A pronoun, a period label or
a request for more rows is still a follow-up about the dataset already on the
table, not a name — those continue to work as they did.

**Proved by** `TestAnUnknownDatasetNameIsSaidToBeUnknown`, which also asserts
the negative: the answer must not contain the whole-catalogue count.

## P4-3 — a version that did not exist was answered with the newest one

**What happened.** `investigations.load(id, version=N)` fell back to the newest
stored version when `N` was not there. Somebody following a link to version 1
of a report that had since been refreshed would have read today's figures under
version 1's heading, with nothing on the page to say the number had moved.

An investigation is evidence of what the book said when it was run. Being able
to go back to it is the entire point of saving one.

**The fix.** A version that is not there is refused, and the refusal names the
versions that are.

**Proved by** `TestASavedVersionIsASnapshot`, which also checks that version 1
returns what version 1 computed rather than recomputing it, and that a saved
version records which reporting period it read.

---

## Still open, and recorded rather than hidden

**The concept ontology does not offer every dataset that could serve a
question.** `corporate_ifrs9` carries `stage` and `ead` at borrower grain, but
is not registered as a candidate for those concepts, so a thread reading it
cannot be answered from it even for a question it could serve. P4-1's mechanism
is in place and will honour it the moment the ontology offers it; registering
the candidates is an ontology change with a much wider blast radius than a
cross-capability review, and it is not made here.

Reproduction: ask "Tell me about Corporate IFRS 9", then "What is total
exposure at default by IFRS 9 stage?". The second is answered from
`ifrs9_staging`. Location: the candidate lists in
`backend/orchestration/concepts.py`.

Note that this is not a wrong answer — both books are governed and the answer
says which one it read — but it is not the one the reader asked for either.
