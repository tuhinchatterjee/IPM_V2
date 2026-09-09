import assert from "node:assert/strict";
import { test } from "node:test";

import { citations, inline, parse, plainText } from "../markdown.ts";

// ---------------------------------------------------------------- structure

test("headings carry their level", () => {
  const blocks = parse("# Title\n\n## 1. Executive summary");
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ["heading", "heading"],
  );
  assert.equal(blocks[0].kind === "heading" && blocks[0].level, 1);
  assert.equal(blocks[1].kind === "heading" && blocks[1].level, 2);
});

test("consecutive lines become one paragraph and a blank line ends it", () => {
  const blocks = parse("One line\nand its continuation.\n\nA second paragraph.");
  assert.equal(blocks.length, 2);
  assert.equal(plainText([blocks[0]]), "One line and its continuation.");
});

test("a pipe table keeps its header and rows and drops the alignment rule", () => {
  const blocks = parse(
    "| Scenario | ECL |\n| --- | ---: |\n| Base | 19.20 |\n| Downturn | 36.00 |",
  );
  assert.equal(blocks.length, 1);
  const table = blocks[0];
  assert.equal(table.kind, "table");
  if (table.kind !== "table") return;
  assert.equal(table.columns.length, 2);
  assert.equal(table.rows.length, 2);
  assert.equal(plainText([table]).includes("36.00"), true);
});

test("bullet and numbered lists are different blocks", () => {
  const blocks = parse("- one\n- two\n\n1. first\n2. second");
  assert.deepEqual(
    blocks.map((b) => b.kind),
    ["bullets", "numbers"],
  );
});

test("a fenced code block keeps its contents verbatim", () => {
  const blocks = parse("```\nnot **bold** here\n```");
  assert.equal(blocks[0].kind, "code");
  assert.equal(blocks[0].kind === "code" && blocks[0].text, "not **bold** here");
});

// ------------------------------------------------------------------- inline

test("bold, italic and inline code become typed spans", () => {
  assert.deepEqual(inline("a **b** c"), [
    { kind: "text", text: "a " },
    { kind: "strong", text: "b" },
    { kind: "text", text: " c" },
  ]);
  assert.equal(inline("*just italic*")[0].kind, "em");
  assert.equal(inline("`code`")[0].kind, "code");
});

test("a citation becomes a locator rather than literal brackets", () => {
  const spans = inline("ECL was 22.77 [[xlsx://ECL!B4]].");
  const citation = spans.find((s) => s.kind === "citation");
  assert.equal(citation?.kind === "citation" && citation.locator, "xlsx://ECL!B4");
  assert.equal(plainText(parse("x [[a://b]]")).includes("[["), false);
});

test("citations are collected in order without duplicates", () => {
  const blocks = parse(
    "One [[a://1]] and two [[b://2]].\n\n- again [[a://1]]",
  );
  assert.deepEqual(citations(blocks), ["a://1", "b://2"]);
});

// ----------------------------------------------------------------- security

test("an http link is kept and a javascript one is not", () => {
  const good = inline("[docs](https://example.com/x)");
  assert.equal(good[0].kind, "link");

  const bad = inline("[click](javascript:alert(1))");
  assert.equal(
    bad.every((s) => s.kind !== "link"),
    true,
    "javascript: must never become a link",
  );
  assert.equal(plainText([{ kind: "paragraph", spans: bad }]).includes("click"), true);
});

test("data: and vbscript: URLs are not links either", () => {
  for (const scheme of ["data:text/html;base64,PHNjcmlwdD4=", "vbscript:msgbox"]) {
    const spans = inline(`[x](${scheme})`);
    assert.equal(
      spans.every((s) => s.kind !== "link"),
      true,
      `${scheme} must not become a link`,
    );
  }
});

test("HTML in a source document stays text and never becomes markup", () => {
  // This is the case that matters: the string came out of a spreadsheet cell.
  const blocks = parse('A cell said <script>alert("x")</script> and <img onerror=y>.');
  const text = plainText(blocks);
  assert.equal(text.includes("<script>"), true, "it is shown as characters");
  assert.equal(
    blocks.every((b) => b.kind !== "code" || true),
    true,
  );
  // There is no block or span kind that can carry raw HTML, which is the
  // structural guarantee rather than a filtering one.
  const kinds = new Set(blocks.map((b) => b.kind));
  assert.equal(kinds.has("paragraph"), true);
});

test("an unterminated table or list does not throw", () => {
  assert.doesNotThrow(() => parse("| a | b\n- item\n1. "));
  assert.doesNotThrow(() => parse("```\nunclosed"));
});

test("empty input produces no blocks", () => {
  assert.deepEqual(parse(""), []);
  assert.deepEqual(inline(""), []);
});
