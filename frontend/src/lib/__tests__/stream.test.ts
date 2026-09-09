import assert from "node:assert/strict";
import { test } from "node:test";

import {
  SSEParser,
  assemble,
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
