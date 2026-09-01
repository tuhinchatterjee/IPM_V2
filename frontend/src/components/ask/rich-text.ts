/**
 * A small, safe reader for the structured answers CreditProbe composes.
 *
 * Why this exists
 * ---------------
 * Product answers arrive as Markdown: headings, bold, bullets, short
 * paragraphs and process flows. The answer surface rendered them inside a
 * single `<p>`, which collapses every newline and turns a structured executive
 * answer into a wall of prose. That was half of the defect; the backend
 * emitting upper-cased run-on sections was the other half.
 *
 * What it deliberately does NOT do
 * --------------------------------
 * It does not render HTML. There is no `dangerouslySetInnerHTML` anywhere in
 * this path: the reader returns typed blocks and spans, React renders them as
 * elements, and any `<script>` in an answer is text on the screen rather than
 * a tag in the document. An answer is composed from governed registries and is
 * not user input, but a renderer that only becomes safe when its input is
 * trusted is one paste away from not being safe.
 *
 * The supported subset is exactly what the composer emits, and no more:
 * `##`/`###`/`####` headings, `**bold**`, `*italic*`, `-` bullets, blockquote
 * process flows, pipe tables, and paragraphs.
 */

export type Span =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "italic"; text: string };

export type Block =
  | { kind: "heading"; level: 2 | 3 | 4; spans: Span[] }
  | { kind: "paragraph"; spans: Span[] }
  | { kind: "bullets"; items: Span[][] }
  | { kind: "flow"; steps: string[] }
  | { kind: "quote"; spans: Span[] }
  | { kind: "table"; columns: string[]; rows: string[][] };

/** The arrow the composer joins process-flow steps with. */
export const FLOW_ARROW = "→";

const HEADING = /^(#{2,4})\s+(.*\S)\s*$/;
const BULLET = /^[-*]\s+(.*)$/;
const TABLE_DIVIDER = /^\|[\s:|-]+\|$/;

/**
 * Inline emphasis. Bold before italic, because `**x**` also matches the
 * italic pattern and reading it as italic would leave stray asterisks on the
 * screen.
 */
export function readSpans(text: string): Span[] {
  const spans: Span[] = [];
  const pattern = /\*\*([^*]+)\*\*|\*([^*]+)\*/g;
  let at = 0;
  let found = pattern.exec(text);
  while (found !== null) {
    if (found.index > at) {
      spans.push({ kind: "text", text: text.slice(at, found.index) });
    }
    if (found[1] !== undefined) {
      spans.push({ kind: "bold", text: found[1] });
    } else {
      spans.push({ kind: "italic", text: found[2] ?? "" });
    }
    at = found.index + found[0].length;
    found = pattern.exec(text);
  }
  if (at < text.length) spans.push({ kind: "text", text: text.slice(at) });
  return spans.length > 0 ? spans : [{ kind: "text", text }];
}

function readTable(lines: string[]): Block | null {
  const rows = lines
    .filter((line) => line.trim().startsWith("|"))
    .map((line) =>
      line
        .trim()
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split("|")
        .map((cell) => cell.trim()),
    );
  if (rows.length < 1) return null;
  const columns = rows[0];
  const body = rows.slice(1).filter((_row, index) => {
    const raw = lines.filter((line) => line.trim().startsWith("|"))[index + 1];
    return raw !== undefined && !TABLE_DIVIDER.test(raw.trim());
  });
  return { kind: "table", columns, rows: body };
}

/** One block of Markdown as a typed block, or null if it is empty. */
function readBlock(block: string): Block | null {
  const lines = block.split("\n").filter((line) => line.trim().length > 0);
  if (lines.length === 0) return null;

  const heading = HEADING.exec(lines[0]);
  if (heading) {
    const level = Math.min(4, Math.max(2, heading[1].length)) as 2 | 3 | 4;
    return { kind: "heading", level, spans: readSpans(heading[2]) };
  }

  if (lines.every((line) => BULLET.test(line.trim()))) {
    return {
      kind: "bullets",
      items: lines.map((line) => readSpans((BULLET.exec(line.trim()) as RegExpExecArray)[1])),
    };
  }

  if (lines[0].trim().startsWith(">")) {
    const said = lines
      .map((line) => line.trim().replace(/^>\s?/, ""))
      .join(" ")
      .trim();
    if (said.includes(FLOW_ARROW)) {
      return {
        kind: "flow",
        steps: said
          .split(FLOW_ARROW)
          .map((step) => step.trim())
          .filter((step) => step.length > 0),
      };
    }
    return { kind: "quote", spans: readSpans(said) };
  }

  if (lines[0].trim().startsWith("|")) {
    const table = readTable(lines);
    if (table) return table;
  }

  return { kind: "paragraph", spans: readSpans(lines.join(" ")) };
}

/**
 * A composed answer as blocks.
 *
 * Blank lines separate blocks, which is what makes the whitespace the composer
 * emits actually reach the screen.
 */
export function readRichText(markdown: string): Block[] {
  const said = String(markdown ?? "").replace(/\r\n/g, "\n");
  const out: Block[] = [];
  for (const chunk of said.split(/\n\s*\n/)) {
    const block = readBlock(chunk);
    if (block) out.push(block);
  }
  return out;
}

/**
 * Whether an answer carries structure worth rendering as blocks.
 *
 * An analytical direct answer is one sentence and must keep rendering exactly
 * as it did: this is the test that decides which of the two an answer is, and
 * it looks for structure rather than for a route, so any answer that gains
 * structure later renders correctly without another change here.
 */
export function isStructured(markdown: string): boolean {
  const said = String(markdown ?? "");
  if (!said.trim()) return false;
  return (
    /^#{2,4}\s/m.test(said) ||
    /^[-*]\s/m.test(said) ||
    /^>\s/m.test(said) ||
    /^\|/m.test(said) ||
    /\n\s*\n/.test(said)
  );
}
