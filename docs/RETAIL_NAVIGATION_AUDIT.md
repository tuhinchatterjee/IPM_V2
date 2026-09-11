# Retail navigation audit — every entry, detail and return journey

Driven in Chromium against the frontend and backend the retail launcher
serves, signed in as the demonstration user, at 1440×900 unless a case says
otherwise. Evidence: `docs/evidence/retail_functionality/navigation.json` and
the screenshots beside it.

"Click succeeded" is never the assertion. Each case reads the destination, the
restored state and any data that changed.

## The ten mandatory cases

| ID | Journey | What was verified | Result |
|---|---|---|---|
| NAV-01 | Cockpit → answer → its Trace → Back | Back returns to **that conversation**, at the turn it was opened from (`/investigations/<id>#turn-1`), not to the Trace index and not to the home page | **PASS** |
| NAV-02 | the same return | The returned screen still carries the question, the month `2026-08` and the completed result — nothing was re-run and no default scope replaced it | **PASS** |
| NAV-03 | What-If → run → save → leave the module → return → reopen | The saved scenario survives leaving, and reopens with its own pinned inputs ("20% relative") and its own month, stated on screen as "as it ran at 2026-08" | **PASS** |
| NAV-04 | Cockpit → Early Warning → browser Back → browser Forward | One Back undoes one intentional navigation; Forward redoes it; no loop, no blank screen, no double entry | **PASS** |
| NAV-05 | a conversation URL opened directly in the same session | Renders the conversation, still signed in, with a working in-app parent — no sign-in redirect loop and no dead end | **PASS** |
| NAV-06 | overlay → Escape | Closes and leaves the page usable; the composer is enabled and clickable afterwards | **PASS** |
| NAV-07 | an unsaved scenario name, then leaving | The What-If composer holds no document-style edit: a scenario is not persisted until Save is pressed, and leaving neither saves it silently nor reports a save that did not happen | **N/A, with the reason recorded** |
| NAV-08 | leave the Cockpit while a question is running, then return | The pending answer does not appear in Early Warning, and returning does not resubmit it | **PASS** |
| NAV-09 | 1280×800 (MacBook 13) and 1024×768 | The composer and its Send stay visible and unobstructed — the element at the centre of the composer IS the composer, so nothing sticky covers it — and a long answer still scrolls | **PASS** |
| NAV-10 | a stale link (`/investigations/999999`) | An informative, recoverable screen rather than a crash or an endless loader | **PASS** |

## Every non-root screen, and how a person gets out of it

| Screen | Return control | Where it goes |
|---|---|---|
| `/investigations/<id>` (a conversation) | `BackLink` | the context it was opened from — the Cockpit, Investigations, or a project — read from the link that opened it |
| `/trace/<runId>` (the evidence) | `BackLink` | the conversation and the exact turn, when opened from an answer; the Trace index when opened directly |
| `/what-if` (the retail What-If) | root of its module | navigation; a saved run reopens in place, and **Clear conversation** ends the thread without touching saved runs |
| `/analysis/<id>`, `/lenses/<id>`, `/data-builder/dataset/<name>` | `BackLink` | their own index, or the screen that linked to them |
| Root modules (`/`, `/what-if`, `/early-warning`, `/investigations`, …) | none, by design | a Back button on a root page is a control that means nothing |

## Two navigation defects found and fixed

**The investigation list rows were unlabelled buttons.** Three rows on
`/investigations` were `<button>` elements carrying no identity: nothing on
them said which conversation they opened, so assistive technology announced
three identical controls. They now carry `aria-label="Open investigation: …"`
and `data-investigation-id`.

**A composer that would not send on Enter.** The What-If box required
Cmd/Ctrl+Enter while the Cockpit box sent on Enter. A user who had just been
talking to the Cockpit pressed Enter here, got a blank line, pressed it again,
and concluded the box was dead. Both boxes now send on Enter, keep a line on
Shift+Enter, and ignore an Enter pressed to choose an IME candidate.

## What this audit does not cover

* **Customer 360** (`/borrower-360`) is reachable and renders, but it still
  shows the previous module's layout; there is no retail customer to open from
  it, so no drill-down-and-return journey exists to test. Recorded as BLOCKED
  under CP-10 rather than passed against the API behind it.
* **Modal dialogs.** The retail surface reaches no modal dialog from the
  Cockpit or What-If: the information affordances are popovers that close on
  blur, and NAV-06 tested Escape on one. A modal introduced later needs its own
  case.
