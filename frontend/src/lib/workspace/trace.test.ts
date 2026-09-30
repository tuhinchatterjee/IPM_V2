import assert from "node:assert/strict";
import test from "node:test";

import { shortHash, snapshotName } from "./trace-format.ts";

test("TRC01 snapshot names are safe file stems the server accepts", () => {
  const re = /^[a-z0-9][a-z0-9_-]{0,60}$/;
  for (const [id, i] of [["whatif-waterfall-selected", 0], ["../../etc/passwd", 1], [null, 2], ["Lens KPI · M005", 3], ["---", 4]] as const) {
    const name = snapshotName(id, i);
    assert.match(name, re, `${id} -> ${name}`);
  }
  assert.equal(snapshotName("whatif-waterfall-selected", 0), "whatif-waterfall-selected");
  assert.equal(snapshotName(null, 2), "chart-3");
});

test("TRC02 hashes are shortened for display but never invented", () => {
  const h = "a".repeat(60) + "beef";
  assert.equal(shortHash(h), "aaaaaaaaaa…beef");
  assert.equal(shortHash(""), "—");
  assert.equal(shortHash(null), "—");
});
