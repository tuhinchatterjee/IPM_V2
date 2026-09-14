import assert from "node:assert/strict";
import { beforeEach, describe, it } from "node:test";

import * as store from "../thread-store.ts";

// A stand-in for the browser's, so the guards can be driven both ways.
function fakeStorage(fail = false) {
  const held = new Map<string, string>();
  return {
    getItem: (k: string) => { if (fail) throw new Error("blocked"); return held.get(k) ?? null; },
    setItem: (k: string, v: string) => { if (fail) throw new Error("blocked"); held.set(k, v); },
    removeItem: (k: string) => { if (fail) throw new Error("blocked"); held.delete(k); },
    held,
  };
}

beforeEach(() => {
  (globalThis as { sessionStorage?: unknown }).sessionStorage = fakeStorage();
});

describe("a thread has an address", () => {
  it("makes ids that differ", () => {
    const seen = new Set(Array.from({ length: 50 }, () => store.newThreadId()));
    assert.equal(seen.size, 50);
  });

  it("reads a thread out of the address", () => {
    assert.equal(store.threadFromQuery("?thread=t1abcdef&band=HIGH"), "t1abcdef");
    assert.equal(store.threadFromQuery("?band=HIGH"), "");
  });

  it("ignores a thread id it did not write", () => {
    // An id out of a URL is somebody else's text, and it is about to be
    // used as a storage key.
    for (const bad of ["../../etc", "<script>", "a b", "x", "'; DROP--"]) {
      assert.equal(store.threadFromQuery(`?thread=${encodeURIComponent(bad)}`), "");
    }
  });

  it("puts the thread in the address without disturbing the filter", () => {
    const query = store.queryWithThread("?ews_band=HIGH&dpd_min=30", "t1abcdef");
    const back = new URLSearchParams(query);
    assert.equal(back.get("ews_band"), "HIGH");
    assert.equal(back.get("dpd_min"), "30");
    assert.equal(back.get("thread"), "t1abcdef");
  });

  it("takes the thread back out again", () => {
    const query = store.queryWithThread("?thread=t1abcdef&ews_band=HIGH", "");
    assert.equal(new URLSearchParams(query).get("thread"), null);
    assert.equal(new URLSearchParams(query).get("ews_band"), "HIGH");
  });
});

describe("a thread survives a Back", () => {
  it("comes back as it went in", () => {
    const thread: store.RememberedThread = {
      id: "t1abcdef",
      turns: [{ id: "x", question: "why?", answer: { a: 1 }, progress: null }],
      summary: { turns: 1 },
      scope: { label: "early warning band High", spec: { filters: {} } },
    };
    store.remember(thread);
    assert.deepEqual(store.recall("t1abcdef"), thread);
  });

  it("is nothing for a thread nobody stored", () => {
    assert.equal(store.recall("t9zzzzzz"), null);
    assert.equal(store.recall(""), null);
  });

  it("is forgotten when asked", () => {
    store.remember({ id: "t1abcdef", turns: [] });
    store.forget("t1abcdef");
    assert.equal(store.recall("t1abcdef"), null);
  });

  it("keeps threads apart", () => {
    store.remember({ id: "t1aaaaaa", turns: [{ id: "a", question: "one", answer: null, progress: null }] });
    store.remember({ id: "t1bbbbbb", turns: [{ id: "b", question: "two", answer: null, progress: null }] });
    assert.equal(store.recall("t1aaaaaa")!.turns[0].question, "one");
    assert.equal(store.recall("t1bbbbbb")!.turns[0].question, "two");
  });
});

describe("storage that will not work is not a crash", () => {
  it("reads nothing rather than throwing", () => {
    (globalThis as { sessionStorage?: unknown }).sessionStorage = fakeStorage(true);
    assert.equal(store.recall("t1abcdef"), null);
  });

  it("writes nothing rather than throwing", () => {
    (globalThis as { sessionStorage?: unknown }).sessionStorage = fakeStorage(true);
    assert.doesNotThrow(() => store.remember({ id: "t1abcdef", turns: [] }));
    assert.doesNotThrow(() => store.forget("t1abcdef"));
  });

  it("reads nothing out of something that is not a thread", () => {
    const storage = fakeStorage();
    storage.held.set("ews-thread:t1abcdef", "{not json");
    (globalThis as { sessionStorage?: unknown }).sessionStorage = storage;
    assert.equal(store.recall("t1abcdef"), null);

    storage.held.set("ews-thread:t1abcdef", '{"id":"t1abcdef"}');
    assert.equal(store.recall("t1abcdef"), null, "no turns array is not a thread");
  });
});
