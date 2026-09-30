import assert from "node:assert/strict";
import test from "node:test";

import { compositionFigure, growthFigure } from "./llm-exchange-figures.ts";

test("context growth plots measured bytes and exact provider tokens per call", () => {
  const fig = growthFigure([
    { seq: 1, exchange_id: "a", purpose: "p", total_bytes: 2048, growth_bytes: 2048, messages: 1, tools: 5, system_bytes: 1000, tool_schema_bytes: 800, tool_result_bytes: 0, input_tokens_exact: 1200, output_tokens_exact: 30 },
    { seq: 2, exchange_id: "b", purpose: "p", total_bytes: 4096, growth_bytes: 2048, messages: 3, tools: 5, system_bytes: 1000, tool_schema_bytes: 800, tool_result_bytes: 1500, input_tokens_exact: 1800, output_tokens_exact: 40 },
  ]);
  assert.deepEqual(fig.data[0].y, [2, 4]);
  assert.deepEqual(fig.data[1].y, [1200, 1800]);
  assert.equal(fig.data[1].yaxis, "y2");
});

test("composition stacks every component of every call, in a fixed order", () => {
  const call = (seq: number, totals: Record<string, number>) =>
    ({ seq, context_composition: { totals_bytes: totals } }) as never;
  const fig = compositionFigure([call(1, { tool_result: 1024, system: 2048 }), call(2, { system: 2048 })]);
  assert.deepEqual(fig.data.map((t) => t.name), ["system", "tool result"]);
  assert.deepEqual(fig.data[1].y, [1, 0]);
  assert.equal(fig.layout.barmode, "stack");
});
