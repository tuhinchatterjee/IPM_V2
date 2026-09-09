"""Playbook — one product, two subsystems that arrived separately.

CreditProbe's Playbook is the governed home for evidence a person chose to
keep. It reached that shape from two directions at once, and this package
holds both rather than picking a winner, because each does something the other
does not.

THE COMMITTEE PACK SYSTEM — the durable system of record. `service`, `access`,
`readiness`, `snapshots`, `findings`, `actions`, `compare`, `monitor`,
`narrative`, `export`, `import_`, `materiality`, `generation`, `agent`, `demo`.
A committee pack is not a document: it is a governed record of what a forum was
told, which numbers, where they came from, what it decided and what somebody
then had to do. Every figure on a pack is a SNAPSHOT rather than a live
calculation, which is what makes a pack still true a quarter later.

THE CHAT-FIRST WORKSPACE — how a person actually makes one. `workspace_service`,
`repository`, `store`, `library`, `document`, `evidence`, `grounding`, `calc`,
`capabilities`, `validate`, `provider`, `prompts`, plus `ingest/` for reading
uploaded documents and `render/` for writing Word, PDF, PowerPoint and Excel.
Turning evidence somebody chose — uploaded documents, and analyses explicitly
exported here — into a report, a deck or a workbook by describing what is
wanted.

WHY BOTH NAMES EXIST. Both subsystems arrived with a module called `service`.
The committee one keeps the name because it is the system of record; the
workspace one is `workspace_service`. That is the only rename the merge
required — the other thirty modules never collided.

The bridge between them, so an exported analysis becomes a block a committee
pack can carry, is the remaining work and is tracked in the integration ledger.
"""
