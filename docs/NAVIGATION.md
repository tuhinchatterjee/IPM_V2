# Return context: where "Back" goes

CreditProbe AI has thirty-four screens and almost all of them are reachable
from more than one place. A Trace opens from the Cockpit, from a message inside
an Investigation, from a Lens tile and from a saved Analysis. A dataset opens
from Data Builder, from a relationship map and from a Trace node.

A fixed "Back to Trace & Lineage" is therefore wrong five times out of six, and
the browser's own Back is the only honest control on the screen — which is a
way of saying the product has no navigation model.

## The contract

A link that leaves one screen for another carries WHERE IT CAME FROM. Three
query parameters do the carrying:

| Parameter | Carries |
|---|---|
| `returnTo` | a complete in-product URL |
| `returnLabel` | what the Back control says |
| `returnType` | what kind of thing the source was |

`returnTo` is a full URL, so everything worth preserving travels inside it and
needs no parameter of its own:

```
scroll anchor            /investigations/12#turn-3
selected tab             /projects/4?tab=investigations
selected visualization   /analysis/91?view=chart
selected trace mode      /trace/57?mode=lineage&node=join_1
dataset period           /data-builder/dataset/ecl_facility?period=2025Q2
```

`returnType` exists so a destination can adapt its wording and a source that
has been deleted can be recognised rather than followed into a 404.

## Building a link

`lib/return-context.ts` has one named builder per source in the product, and
they are the only sanctioned way to construct a return href. A call site that
hand-rolls the string gets the anchor wrong once and nobody notices for a
release, so there are no hand-rolled ones.

```ts
import { linkBack, fromInvestigation } from "@/lib/return-to";

<Link href={linkBack(`/trace/${runId}`, fromInvestigation(id, title, seq))}>
```

| Builder | Returns to |
|---|---|
| `fromCockpit()` | `/` |
| `fromInvestigation(id, title, seq?)` | the exact turn |
| `fromProject(id, name, tab?)` | the project on that tab |
| `fromSavedAnalysis(id, title)` | that row in the Analyses list |
| `fromLens(id, name)` | the lens |
| `fromBorrower(accountId, name)` | Early Warning, that row reopened |
| `fromDataset(name, period?)` | the dataset at that period |
| `fromTraceNode(runId, mode?, node?)` | that node, in that mode |

## Reading it back

```ts
const back = useReturnTo({ href: "/investigations", label: "Investigations" });
```

Only same-origin relative paths are honoured. A `returnTo` arrives in a query
string, so trusting it would let any link anywhere turn a Back button into an
off-site redirect. `//evil.example` is a protocol-relative URL and
`javascript:` is a scheme; both are refused, and the caller's own default is
used instead. That rule is a security boundary and is unit-tested rather than
exercised by clicking around.

`<BackLink>` wraps this and is what every full-screen detail view renders.

## Landing on the anchor

The App Router restores a hash on a full page load and not reliably after a
client-side navigation — and in this product the element being anchored to,
turn nine of an investigation, is usually not in the document yet when the
navigation completes.

```ts
useAnchorScroll(Boolean(thread));   // scroll once the turns exist
```

`ready` rather than a poll: a Back that jumps the reader somewhere half a
second after they have started reading is worse than one that does not jump.

## State that had to move into the address

Three screens held state that a return link could not carry, so it moved:

- the **Project's tab**, rewritten with `history.replaceState` as the reader
  switches
- the **Trace's mode and selected node**, the same way — `replaceState` rather
  than a router push, because thirty history entries for one Trace would break
  the browser's own Back
- **Early Warning's opened facility**, because a borrower there is an expanded
  row rather than a page, and which one is open is the only thing that
  distinguishes two visits to the same URL

## The paths §5 names

| Journey | Lands on |
|---|---|
| Cockpit → Investigation → Trace | the exact turn |
| Cockpit → Investigation → Method | the exact turn |
| Project → Investigation → Trace | the investigation, then the project's tab |
| Saved Analysis → Trace | that row in Analyses |
| Lens → Analysis → Trace | the lens |
| Early Warning → Borrower → Investigation → Trace | that borrower's row |
| Data Builder → Dataset → Relationship map | the dataset, at its period |
| Trace → Dataset in Data Builder | the same node, in the same mode |
| Dynamic Analysis Run → detail | the source conversation |

Each is walked end to end in `lib/__tests__/back-paths.test.ts` — the link is
built the way the screen builds it and read back the way the destination reads
it, because a unit test of one builder cannot catch a journey that loses its
context at the second hop.

**Early Warning is the one path that could not be built as written.** §5 asks
for Borrower → Trace, and a signal score is a fitted model rather than a
governed engine run, so a borrower has no Trace of its own. What it has is
"Investigate this borrower", which opens an Investigation carrying that exact
row as its Back — so the journey completes by way of the analysis that does
produce a Trace.
