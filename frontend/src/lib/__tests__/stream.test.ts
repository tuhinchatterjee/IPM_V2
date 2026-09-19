import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SSEParser,
  assemble,
  draftSections,
  elapsed,
  stateLabel,
  toPlaybookEvent,
  type PlaybookStreamEvent,
} from "../stream.ts";

function event(
  kind: PlaybookStreamEvent["kind"],
  data: Record<string, unknown>,
  seq = 1,
): PlaybookStreamEvent {
  return { seq, kind, data };
}

test("a whole event in one chunk parses", () => {
  const parser = new SSEParser();
  const events = parser.push('id: 4\nevent: delta\ndata: {"text":"hi"}\n\n');
  assert.deepEqual(events, [{ id: "4", event: "delta", data: '{"text":"hi"}' }]);
});

test("an event split across reads is not lost", () => {
  // The failure this prevents is silent: a parser that assumes one read is one
  // event drops text at random under load and is perfect in a demonstration.
  const parser = new SSEParser();
  assert.deepEqual(parser.push("id: 4\nevent: de"), []);
  assert.deepEqual(parser.push('lta\ndata: {"text":"h'), []);
  const events = parser.push('i"}\n\n');
  assert.deepEqual(events, [{ id: "4", event: "delta", data: '{"text":"hi"}' }]);
});

test("a read that ends between the two terminating newlines holds the event", () => {
  const parser = new SSEParser();
  assert.deepEqual(parser.push('event: delta\ndata: {"text":"hi"}\n'), []);
  assert.equal(parser.push("\n").length, 1);
});

test("several events in one read all come out, in order", () => {
  const parser = new SSEParser();
  const events = parser.push(
    'id: 1\nevent: state\ndata: {"state":"drafting"}\n\n' +
      'id: 2\nevent: delta\ndata: {"text":"a"}\n\n' +
      'id: 3\nevent: delta\ndata: {"text":"b"}\n\n',
  );
  assert.deepEqual(
    events.map((e) => e.id),
    ["1", "2", "3"],
  );
});

test("a keep-alive comment produces no event and clears itself", () => {
  const parser = new SSEParser();
  assert.deepEqual(parser.push(": keep-alive\n\n"), []);
  assert.equal(parser.pending, "");
});

test("only one space after the colon is eaten", () => {
  const parser = new SSEParser();
  const [e] = parser.push("event: delta\ndata:   spaced\n\n");
  assert.equal(e.data, "  spaced");
});

test("multi-line data is rejoined with newlines", () => {
  const parser = new SSEParser();
  const [e] = parser.push("event: delta\ndata: one\ndata: two\n\n");
  assert.equal(e.data, "one\ntwo");
});

test("CRLF line endings parse the same", () => {
  const parser = new SSEParser();
  const [e] = parser.push('id: 7\r\nevent: delta\r\ndata: {"text":"hi"}\r\n\r\n');
  assert.equal(e.id, "7");
  assert.equal(e.data, '{"text":"hi"}');
});

test("a Playbook event carries its seq as a number", () => {
  const parsed = toPlaybookEvent({
    id: "12",
    event: "delta",
    data: '{"text":"hi"}',
  });
  assert.deepEqual(parsed, { seq: 12, kind: "delta", data: { text: "hi" } });
});

test("an event kind nobody defined is ignored rather than rendered", () => {
  assert.equal(
    toPlaybookEvent({ id: "1", event: "surprise", data: "{}" }),
    null,
  );
});

test("a frame whose JSON does not parse is dropped, not shown as text", () => {
  assert.equal(
    toPlaybookEvent({ id: "1", event: "delta", data: '{"text":' }),
    null,
  );
});

test("deltas assemble into the answer so far", () => {
  const { text, done } = assemble([
    event("state", { state: "drafting" }),
    event("delta", { text: "# Report\n\n" }, 2),
    event("delta", { text: "It rose." }, 3),
  ]);
  assert.equal(text, "# Report\n\nIt rose.");
  assert.equal(done, false);
});

test("the current state is the latest one, not the first", () => {
  const { state, detail } = assemble([
    event("state", { state: "reviewing_sources", detail: "3 sources" }),
    event("state", { state: "rendering", detail: "docx" }, 2),
  ]);
  assert.equal(state, "rendering");
  assert.equal(detail, "docx");
});

test("done carries the version that was written", () => {
  const { done, version } = assemble([
    event("delta", { text: "It rose." }),
    event("artifact", { version: 2 }, 2),
    event("done", { version: 2 }, 3),
  ]);
  assert.equal(done, true);
  assert.equal(version, 2);
});

test("a failure discards the half answer rather than showing it as the answer", () => {
  const { text, error, done } = assemble([
    event("delta", { text: "Weighted ECL rose to" }),
    event("error", { message: "The provider went away." }, 2),
  ]);
  assert.equal(text, "");
  assert.equal(error, "The provider went away.");
  assert.equal(done, true);
});

test("a stop is distinguishable from a failure", () => {
  const { cancelled, error } = assemble([
    event("error", { message: "This generation was stopped.", cancelled: true }),
  ]);
  assert.equal(cancelled, true);
  assert.match(error, /stopped/);
});

test("nothing at all assembles to nothing, not to an error", () => {
  const { text, done, error } = assemble([]);
  assert.equal(text, "");
  assert.equal(done, false);
  assert.equal(error, "");
});

test("a real state reads as words, and an unknown one is not hidden", () => {
  assert.equal(stateLabel("reviewing_sources"), "Reading the sources");
  assert.equal(stateLabel("rendering", "docx"), "Building the files — docx");
  assert.equal(stateLabel("something_new"), "something new");
});

// --------------------------------------------------------------------------
// The step log, the clock and the draft.
//
// Every one of these exists because a real seven-minute run was
// indistinguishable from a dead one: two scalars overwritten on each
// milestone, no timestamp on any event, a heartbeat the parser discarded, and
// nothing at all emitted while the document was being written.
// --------------------------------------------------------------------------

test("milestones are kept in order, not collapsed to the latest", () => {
  const view = assemble([
    event("state", { state: "reviewing_sources", at: 0.2 }, 1),
    event("state", { state: "drafting", detail: "create_document running", at: 3.1 }, 2),
    event("state", { state: "rendering", detail: "building docx", at: 190.4 }, 3),
  ]);
  assert.deepEqual(
    view.steps.map((s) => [s.state, s.at, s.done]),
    [
      ["reviewing_sources", 0.2, true],
      ["drafting", 3.1, true],
      ["rendering", 190.4, false],
    ],
  );
  // The old shape survives, because the status line still uses it.
  assert.equal(view.state, "rendering");
});

test("the same step repeated is one step", () => {
  // The backend emits `reviewing_sources` twice at the start of every turn.
  // A list that showed it twice would be reporting the implementation.
  const view = assemble([
    event("state", { state: "reviewing_sources", at: 0.1 }, 1),
    event("state", { state: "reviewing_sources", at: 0.3 }, 2),
    event("state", { state: "drafting", at: 1.0 }, 3),
  ]);
  assert.deepEqual(view.steps.map((s) => s.state),
    ["reviewing_sources", "drafting"]);
});

test("the last step is finished when the run ends", () => {
  const view = assemble([
    event("state", { state: "drafting", at: 1 }, 1),
    event("done", { version: 1, at: 200 }, 2),
  ]);
  assert.equal(view.steps[0].done, true);
});

test("elapsed comes from the newest event and never goes backwards", () => {
  const view = assemble([
    event("state", { state: "drafting", at: 3.1 }, 1),
    event("delta", { text: "hello", at: 190.0 }, 2),
    // An out-of-order arrival must not rewind the clock.
    event("state", { state: "rendering", at: 12.0 }, 3),
  ]);
  assert.equal(view.at, 190.0);
});

test("a heartbeat says how long the worker has been quiet, and moves nothing else", () => {
  const view = assemble([
    event("state", { state: "drafting", at: 3.1 }, 1),
    event("ping", { quiet_for: 47.5 }, 0),
  ]);
  assert.equal(view.quietFor, 47.5);
  // The ping is written by the reader, not the worker, so it is not evidence
  // that the generation has got any further.
  assert.equal(view.at, 3.1);
  assert.equal(view.steps.length, 1);
});

test("the draft is kept apart from the answer", () => {
  const view = assemble([
    event("delta", { text: "I will write that now.", at: 1 }, 1),
    event("draft_delta", { text: "## 1. Executive summary\n\nBody.", at: 40 }, 2),
  ]);
  assert.equal(view.text, "I will write that now.");
  assert.equal(view.draft, "## 1. Executive summary\n\nBody.");
  // Two different things. Merging them would put the whole report in the
  // message column beside the file card that already holds it.
  assert.ok(!view.text.includes("Executive summary"));
});

test("a failure discards the draft as well as the answer", () => {
  const view = assemble([
    event("delta", { text: "half an answer", at: 1 }, 1),
    event("draft_delta", { text: "## Half a document", at: 2 }, 2),
    event("error", { message: "The provider did not respond in time." }, 3),
  ]);
  assert.equal(view.text, "");
  assert.equal(view.draft, "");
  assert.equal(view.error, "The provider did not respond in time.");
});

test("a plan names the steps before any of them has happened", () => {
  const view = assemble([
    event("plan", { steps: ["Write the document", "Build the DOCX file"], at: 2 }, 1),
  ]);
  assert.deepEqual(view.plan, ["Write the document", "Build the DOCX file"]);
  assert.equal(view.steps.length, 0, "a plan is not a step that happened");
});

test("sections are counted from the draft that arrived, with no denominator", () => {
  const draft = "# Title\n\n## 1. Scope\n\nBody\n\n## 2. Method\n\nBody\n\n### 2.1 Detail\n";
  assert.equal(draftSections(draft), 2, "## only — a title is not a section");
  assert.equal(draftSections(""), 0);
  assert.equal(draftSections("##nospace"), 0);
});

test("elapsed reads as a person would say it", () => {
  assert.equal(elapsed(0), "0s");
  assert.equal(elapsed(8.7), "8s");
  assert.equal(elapsed(60), "1m 0s");
  assert.equal(elapsed(252), "4m 12s");
  assert.equal(elapsed(-5), "0s", "a negative clock is a bug, not a display");
});

test("an unknown event kind is dropped rather than shown", () => {
  assert.equal(toPlaybookEvent({ id: "1", event: "reasoning", data: "{}" }), null);
});

test("the new kinds are accepted", () => {
  for (const kind of ["draft_delta", "plan", "ping"]) {
    const parsed = toPlaybookEvent({ id: "1", event: kind, data: "{}" });
    assert.equal(parsed?.kind, kind);
  }
});
