import assert from "node:assert/strict";
import test from "node:test";

import { counts, segments } from "./exchange-segments.ts";

const REQUEST = {
  system: [{ type: "text", text: "You are the analyst." }, { type: "text", text: "Rules." }],
  messages: [
    { role: "user", content: "USER REQUEST (original wording, unmodified):\nHow many facilities?" },
    { role: "assistant", content: [{ type: "text", text: "I will query." }, { type: "tool_use", id: "tu-1", name: "execute_analysis", input: { sql: "SELECT 1" } }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "tu-1", content: '{"rows": [[2996]]}' }] },
    { role: "assistant", content: [{ type: "tool_use", id: "tu-2", name: "finalize_response", input: { narrative: "3,000" } }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "tu-2", is_error: true, content: '{"status": "rejected", "error_code": "UNBOUND_NUMBER"}' }] },
    { role: "user", content: [{ type: "tool_result", tool_use_id: "tu-3", content: [{ type: "text", text: '{"status": "rejected", "message": "x"}' }] }] },
  ],
};

test("EXS01 every part of the request is labelled in the order sent", () => {
  const s = segments(REQUEST, { text: "", tool_calls: [{ id: "tu-4", name: "finalize_response", input: { narrative: "2,996" } }] });
  assert.deepEqual(
    s.map((x) => `${x.side}:${x.kind}`),
    [
      "request:SYSTEM",
      "request:SYSTEM",
      "request:USER",
      "request:ASSISTANT",
      "request:TOOL CALL",
      "request:TOOL RESULT",
      "request:TOOL CALL",
      "request:VALIDATOR",
      "request:VALIDATOR",
      "response:TOOL CALL",
    ],
  );
  assert.equal(s[4].name, "execute_analysis");
  assert.equal(s[7].id, "tu-2");
  assert.match(s[7].text, /UNBOUND_NUMBER/);
});

test("EXS02 counts cover all six kinds; a plain tool result is never called a validator", () => {
  const c = counts(segments(REQUEST));
  assert.deepEqual(c, { SYSTEM: 2, USER: 1, ASSISTANT: 1, "TOOL CALL": 2, "TOOL RESULT": 1, VALIDATOR: 2 });
  const plain = segments({ messages: [{ role: "user", content: [{ type: "tool_result", tool_use_id: "a", content: '{"rows": [["rejected loans", 3]]}' }] }] });
  assert.equal(plain[0].kind, "TOOL RESULT");
});

test("EXS03 string system text and an empty request are handled", () => {
  assert.deepEqual(segments({ system: "S" }).map((s) => s.kind), ["SYSTEM"]);
  assert.deepEqual(segments(null), []);
});
