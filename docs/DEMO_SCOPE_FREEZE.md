# Client-demo scope freeze

Frozen for the demonstration on this release candidate. Nothing outside CORE
DEMO is on the twenty-minute path, and nothing marked HIDDEN appears in the
navigation while Demo Mode is on.

The classification lives in `frontend/src/lib/navigation.ts` beside each item,
not only here, so a screen cannot be in one state in the sidebar and another
in a document. `demo-check.ps1` and the route crawl both read the same file.

---

## The four classes

| Class | What it means |
|---|---|
| **CORE DEMO** | Shown, and must be reliable. A failure here is a NO-GO. |
| **OPTIONAL DEMO** | Shown only if every check passes. The presenter may skip it and nothing is lost. |
| **ADMIN PREVIEW** | Reachable by an authorized user, deliberately not on the walkthrough. |
| **HIDDEN** | Removed from navigation while Demo Mode is on. |

**HIDDEN removes the LINK, not the route.** Anyone who types the address still
gets the page. Hiding a screen is presentation, never security — the API
behind every one of them enforces permission whatever the sidebar shows.

---

## CORE DEMO — eight capabilities

| Screen | Why it is core |
|---|---|
| **Cockpit** (`/`) | Every question is asked here. |
| **Projects** (`/projects`) | The Project journey, and the scope isolation that goes with it. |
| **Investigations** (`/investigations`) | Conversational threads, global and Project-only. |
| **Analyses** (`/analyses`) | Saved results with their data version and Trace. |
| **Analysis Studio** (`/studio`) | Certified methodology — the answer to "how do you know this is right?". |
| **Data Builder** (`/data-builder`) | Governed datasets, relationships, publication state. |
| **Trace & Lineage** (`/trace`) | How an answer was produced. The heart of the demonstration. |
| **Workflow** (`/workflow`) | Send, review, approve, with an append-only history. |

Each one is `status: "live"` and each was visited by the route crawl for
ADMIN, ANALYST and VIEWER.

---

## OPTIONAL DEMO — four

| Screen | Show it when | What not to promise |
|---|---|---|
| **Lenses** (`/lenses`) | There is time and the audience asks about dashboards. | Nothing; it is real. One published Lens is seeded. |
| **Stress Testing** (`/stress`) | The audience asks about scenarios. | — |
| **Early Warning** (`/early-warning`) | The audience asks about predictive signals. | **Read the label out.** It is a prototype signal fitted on synthetic data and is not a validated model. |
| **Playbooks** (`/playbooks`) | The audience asks about standing instructions. | **Do not promise scheduling.** Manual and on-publication triggers run; scheduled ones are not wired to a scheduler. |

---

## ADMIN PREVIEW — four

Reachable by an authorized user; not on the walkthrough. Compelling to a
technical audience and irrelevant to a CRO.

| Screen | Roles | Note |
|---|---|---|
| **Agent Operations** (`/agent-operations`) | ADMIN, DATA_STEWARD | The twelve specialists, every run and what it cost, schedules, policies, approvals. |
| **AI Intelligence Studio** (`/ai-studio`) | ADMIN, DATA_STEWARD | Includes **Feedback & Learning**. Show on request; §23 says not to make it a long part of the demonstration. |
| **Users & Teams** (`/users`) | **ADMIN** | Restricted in this phase. The route crawl found an ANALYST and a VIEWER being offered this link and getting a 403 the moment they clicked: the endpoint's permission was right and the invitation was wrong. |
| **Settings** (`/settings`) | all | Themes, roles, model configuration. |

---

## HIDDEN — one

| Screen | Why |
|---|---|
| **Documents** (`/documents`) | Its cards are fixed sample records wired to nothing. It is honestly labelled "Placeholder by design", and an honest placeholder is still the first dead end a client would find. Removed from navigation while Demo Mode is on; the route and its label remain. |

---

## Not in the navigation at all

Reachable only from an object that links to them, and unchanged by this
phase:

* `/engine-builder/*` — the registered engine analyses behind a method.
* `/analysis/{id}` — one analysis definition.
* `/early-warning/lab` — the factor lab.
* `/data-builder/dataset/{name}`, `/data-builder/domain/*`,
  `/data-builder/new`, `/data-builder/inbox`, `/data-builder/browse`.
* `/lenses/cro` — the CRO lens.
* `/studio/new`, `/investigations/saved/{id}`, `/projects/{id}`,
  `/trace/{runId}`, `/documents/{id}`.

---

## API-only in this build

These have working, tested APIs and **no screen**. The client runbook
demonstrates them with `curl` and says that is what they are.
`backend/proof/matrix.py` records them `BACKEND_ONLY`.

| Capability | Endpoints |
|---|---|
| Regulatory circular knowledge | `/api/v1/regulatory/*` (13) |
| Teaching corpus import | `/api/v1/teaching-corpus/*` (3) |

Building a screen for either would be new architecture, which §1 forbids in
this phase. The backend is preserved for later completion.

---

## What was NOT changed

No capability was removed, renamed or degraded to fit the demonstration. The
scope freeze adds a classification and hides one link. Everything that worked
on `0458f96` still works, and `docs/DEMO_KNOWN_LIMITATIONS.md` states what
does not.
