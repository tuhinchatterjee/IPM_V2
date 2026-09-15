import assert from "node:assert/strict";
import { test, beforeEach } from "node:test";

import {
  EMPTY,
  clearDraft,
  readDraft,
  saveDraft,
} from "../playbook-draft.ts";

/** A sessionStorage stand-in, and one that can be made to fail on demand. */
class Box implements Storage {
  private data = new Map<string, string>();
  throws = false;
  get length() { return this.data.size; }
  clear() { this.data.clear(); }
  key(i: number) { return [...this.data.keys()][i] ?? null; }
  getItem(k: string) {
    if (this.throws) throw new Error("blocked");
    return this.data.get(k) ?? null;
  }
  setItem(k: string, v: string) {
    if (this.throws) throw new Error("blocked");
    this.data.set(k, v);
  }
  removeItem(k: string) {
    if (this.throws) throw new Error("blocked");
    this.data.delete(k);
  }
}

let box: Box;

beforeEach(() => {
  box = new Box();
  (globalThis as { window?: unknown }).window = { sessionStorage: box };
});

test("a draft survives the trip to the dashboard and back", () => {
  saveDraft(7, { prompt: "Sharpen section 1", analyses: [11, 12],
    task: { kind: "edit", scope: "1. Summary" }, scrollY: 420 });
  const draft = readDraft(7);
  assert.equal(draft.prompt, "Sharpen section 1");
  assert.deepEqual(draft.analyses, [11, 12]);
  assert.equal(draft.task.scope, "1. Summary");
  assert.equal(draft.scrollY, 420);
});

test("saving one field leaves the others alone", () => {
  saveDraft(7, { prompt: "half a sentence", analyses: [3] });
  saveDraft(7, { scrollY: 99 });
  const draft = readDraft(7);
  assert.equal(draft.prompt, "half a sentence");
  assert.deepEqual(draft.analyses, [3]);
  assert.equal(draft.scrollY, 99);
});

test("drafts do not leak between workspaces", () => {
  saveDraft(7, { prompt: "mine" });
  saveDraft(8, { prompt: "theirs" });
  assert.equal(readDraft(7).prompt, "mine");
  assert.equal(readDraft(8).prompt, "theirs");
});

test("a workspace with no draft reads empty rather than undefined", () => {
  assert.deepEqual(readDraft(99), EMPTY);
});

test("clearing removes it", () => {
  saveDraft(7, { prompt: "x" });
  clearDraft(7);
  assert.equal(readDraft(7).prompt, "");
});

test("storage that throws costs a retype, never an error", () => {
  // A private window, or site data blocked. The status page must still open.
  box.throws = true;
  assert.doesNotThrow(() => saveDraft(7, { prompt: "x" }));
  assert.doesNotThrow(() => clearDraft(7));
  assert.deepEqual(readDraft(7), EMPTY);
});

test("corrupt stored JSON reads as an empty draft", () => {
  box.setItem("playbook:draft:7", "{not json");
  assert.deepEqual(readDraft(7), EMPTY);
});

test("a stored draft of the wrong shape is not trusted", () => {
  box.setItem("playbook:draft:7",
    JSON.stringify({ prompt: 42, analyses: ["a", 2], task: "edit" }));
  const draft = readDraft(7);
  assert.equal(draft.prompt, "");
  assert.deepEqual(draft.analyses, [2]);
  assert.equal(draft.task.kind, "");
});
