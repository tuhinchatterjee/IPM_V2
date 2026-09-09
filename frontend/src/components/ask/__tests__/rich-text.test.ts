import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { isStructured, readRichText, readSpans } from "../rich-text.ts";

/**
 * The renderer half of the product-answer defect.
 *
 * The backend composed headings, bullets and blank lines; the answer surface
 * put the whole string inside one paragraph, where HTML collapses every
 * newline. These tests hold the reader that makes the structure survive.
 */

const OVERVIEW = [
  "I'm CreditProbe AI — your AI Risk Officer for the credit book.",
  "",
  "My job is simple: **Help you see risk earlier.**",
  "",
  "- **Where is risk building?**",
  "- **Which exposures deteriorated?**",
  "",
  "## What that means day to day",
  "",
  "### See around corners",
  "",
  "Deterioration surfaces early.",
  "",
  "> See earlier → Investigate deeper → Act sooner",
].join("\n");

describe("reading a composed answer", () => {
  it("keeps every block separate rather than collapsing them", () => {
    const blocks = readRichText(OVERVIEW);
    assert.equal(blocks.length, 7);
    assert.deepEqual(
      blocks.map((b) => b.kind),
      ["paragraph", "paragraph", "bullets", "heading", "heading", "paragraph", "flow"],
    );
  });

  it("reads heading levels", () => {
    const blocks = readRichText(OVERVIEW);
    const headings = blocks.filter((b) => b.kind === "heading");
    assert.deepEqual(
      headings.map((b) => (b.kind === "heading" ? b.level : 0)),
      [2, 3],
    );
  });

  it("reads a process flow as steps rather than as a sentence", () => {
    const flow = readRichText(OVERVIEW).at(-1);
    assert.equal(flow?.kind, "flow");
    assert.deepEqual(flow?.kind === "flow" ? flow.steps : [], [
      "See earlier",
      "Investigate deeper",
      "Act sooner",
    ]);
  });

  it("reads every bullet as its own item", () => {
    const bullets = readRichText(OVERVIEW).find((b) => b.kind === "bullets");
    assert.equal(bullets?.kind === "bullets" ? bullets.items.length : 0, 2);
  });

  it("reads a pipe table", () => {
    const blocks = readRichText(
      ["| Signal | Severity |", "| --- | --- |", "| Revenue fell | CONCERN |"].join("\n"),
    );
    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].kind, "table");
    if (blocks[0].kind === "table") {
      assert.deepEqual(blocks[0].columns, ["Signal", "Severity"]);
      assert.deepEqual(blocks[0].rows, [["Revenue fell", "CONCERN"]]);
    }
  });

  it("never produces one giant block from a structured answer", () => {
    for (const block of readRichText(OVERVIEW)) {
      if (block.kind !== "paragraph") continue;
      const text = block.spans.map((s) => s.text).join("");
      assert.ok(text.length < 400, `paragraph too long: ${text.slice(0, 60)}`);
    }
  });
});

describe("inline emphasis", () => {
  it("reads bold before italic, so ** never leaks to the screen", () => {
    const spans = readSpans("plain **bold** and *slanted*");
    assert.deepEqual(
      spans.map((s) => s.kind),
      ["text", "bold", "text", "italic"],
    );
    assert.ok(!spans.some((s) => s.text.includes("*")));
  });

  it("leaves markup-free text alone", () => {
    assert.deepEqual(readSpans("no emphasis here"), [
      { kind: "text", text: "no emphasis here" },
    ]);
  });
});

describe("markup is never treated as HTML", () => {
  it("keeps a tag as text, so nothing in an answer can become an element", () => {
    const blocks = readRichText("<script>alert(1)</script> is just text");
    assert.equal(blocks.length, 1);
    assert.equal(blocks[0].kind, "paragraph");
    const text =
      blocks[0].kind === "paragraph" ? blocks[0].spans.map((s) => s.text).join("") : "";
    assert.ok(text.includes("<script>"));
  });
});

describe("choosing which renderer an answer gets", () => {
  it("treats a one-sentence analytical answer as plain prose", () => {
    assert.equal(isStructured("293 customers were downgraded and ECL rose."), false);
  });

  it("treats a composed product answer as structured", () => {
    assert.equal(isStructured(OVERVIEW), true);
  });

  it("treats an empty answer as neither", () => {
    assert.equal(isStructured(""), false);
    assert.equal(isStructured("   "), false);
  });
});
