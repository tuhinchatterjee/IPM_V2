/**
 * A small Markdown reader for Playbook's answers.
 *
 * Why this exists rather than a dependency
 * ----------------------------------------
 * This product renders text that came out of documents a user uploaded, and
 * those documents are untrusted. Every general-purpose Markdown renderer has an
 * HTML escape hatch, which then has to be closed again with a sanitiser, which
 * is a second dependency and a second thing to keep current. There is no escape
 * hatch here: this reader produces a typed tree of blocks and inline spans, and
 * the component that renders it emits React elements. Nothing anywhere becomes
 * `dangerouslySetInnerHTML`, so `<script>` in a spreadsheet cell is four
 * characters of text and can never be anything else.
 *
 * It is deliberately small: headings, paragraphs, bullet and numbered lists,
 * pipe tables, fenced code, bold, italic, inline code, links and Playbook's own
 * `[[locator]]` citations. Anything it does not recognise stays as text, which
 * is the right failure for a reader whose input is somebody's report.
 *
 * The parser mirrors backend/playbook/document.py, so what the author writes,
 * what is stored, what is rendered in the thread and what is written into the
 * Word file are all the same structure read the same way.
 */

export type Inline =
  | { kind: "text"; text: string }
  | { kind: "strong"; text: string }
  | { kind: "em"; text: string }
  | { kind: "code"; text: string }
  | { kind: "link"; text: string; href: string }
  | { kind: "citation"; locator: string };

export type Block =
  | { kind: "heading"; level: number; spans: Inline[] }
  | { kind: "paragraph"; spans: Inline[] }
  | { kind: "bullets"; items: Inline[][] }
  | { kind: "numbers"; items: Inline[][] }
  | { kind: "table"; columns: Inline[][]; rows: Inline[][][] }
  | { kind: "code"; text: string };

/**
 * Only these schemes may become a link.
 *
 * `javascript:` is the reason this list is an allowlist rather than a blocklist:
 * a source document can contain any string at all, and a renderer that decides
 * what to forbid will always be one scheme behind.
 */
const SAFE_SCHEME = /^(https?:|mailto:|\/)/i;

const CITATION = /\[\[([^\]]+)\]\]/;
const LINK = /\[([^\]]+)\]\(([^)\s]+)\)/;
const STRONG = /\*\*([^*]+)\*\*/;
const EM = /(?<!\*)\*([^*]+)\*(?!\*)/;
const CODE = /`([^`]+)`/;

/** Split one line of text into typed spans. Never produces markup. */
export function inline(text: string): Inline[] {
  if (!text) return [];
  const patterns: { re: RegExp; make: (m: RegExpMatchArray) => Inline }[] = [
    { re: CITATION, make: (m) => ({ kind: "citation", locator: m[1].trim() }) },
    {
      re: LINK,
      make: (m) =>
        SAFE_SCHEME.test(m[2])
          ? { kind: "link", text: m[1], href: m[2] }
          : // A link we will not follow becomes its own text, so the reader
            // still sees what the document said without it being clickable.
            { kind: "text", text: `${m[1]} (${m[2]})` },
    },
    { re: STRONG, make: (m) => ({ kind: "strong", text: m[1] }) },
    { re: EM, make: (m) => ({ kind: "em", text: m[1] }) },
    { re: CODE, make: (m) => ({ kind: "code", text: m[1] }) },
  ];

  let earliest: { index: number; length: number; span: Inline } | null = null;
  for (const { re, make } of patterns) {
    const match = text.match(re);
    if (match?.index === undefined) continue;
    if (earliest === null || match.index < earliest.index) {
      earliest = { index: match.index, length: match[0].length, span: make(match) };
    }
  }
  if (earliest === null) return [{ kind: "text", text }];

  const before = text.slice(0, earliest.index);
  const after = text.slice(earliest.index + earliest.length);
  return [
    ...(before ? [{ kind: "text", text: before } as Inline] : []),
    earliest.span,
    ...inline(after),
  ];
}

function cells(line: string): string[] {
  return line.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
}

function isRule(line: string): boolean {
  const parts = cells(line);
  return parts.length > 0 && parts.every((c) => /^:?-{1,}:?$/.test(c));
}

/** Read Markdown into blocks. Unrecognised syntax stays as text. */
export function parse(source: string): Block[] {
  const lines = (source ?? "").replace(/\r\n/g, "\n").split("\n");
  const blocks: Block[] = [];
  let paragraph: string[] = [];

  const flush = () => {
    if (paragraph.length) {
      blocks.push({ kind: "paragraph", spans: inline(paragraph.join(" ").trim()) });
      paragraph = [];
    }
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      flush();
      const body: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        body.push(lines[i]);
        i += 1;
      }
      blocks.push({ kind: "code", text: body.join("\n") });
      continue;
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(trimmed);
    if (heading) {
      flush();
      blocks.push({
        kind: "heading",
        level: heading[1].length,
        spans: inline(heading[2].trim()),
      });
      continue;
    }

    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      flush();
      const raw: string[] = [];
      while (
        i < lines.length &&
        lines[i].trim().startsWith("|") &&
        lines[i].trim().endsWith("|")
      ) {
        raw.push(lines[i]);
        i += 1;
      }
      i -= 1;
      const usable = raw.filter((r) => !isRule(r));
      if (usable.length) {
        const [header, ...body] = usable;
        blocks.push({
          kind: "table",
          columns: cells(header).map(inline),
          rows: body.map((r) => cells(r).map(inline)),
        });
      }
      continue;
    }

    const bullet = /^[-*•]\s+(.*)$/.exec(trimmed);
    const numbered = /^\d+[.)]\s+(.*)$/.exec(trimmed);
    if (bullet || numbered) {
      flush();
      const kind = bullet ? "bullets" : "numbers";
      const items: Inline[][] = [];
      while (i < lines.length) {
        const current = lines[i].trim();
        const b = /^[-*•]\s+(.*)$/.exec(current);
        const n = /^\d+[.)]\s+(.*)$/.exec(current);
        const match = kind === "bullets" ? b : n;
        if (!match) break;
        items.push(inline(match[1].trim()));
        i += 1;
      }
      i -= 1;
      blocks.push(
        kind === "bullets"
          ? { kind: "bullets", items }
          : { kind: "numbers", items },
      );
      continue;
    }

    if (!trimmed) {
      flush();
      continue;
    }
    paragraph.push(trimmed);
  }
  flush();
  return blocks;
}

/** Every citation in a document, in order, deduplicated. */
export function citations(blocks: Block[]): string[] {
  const found: string[] = [];
  const walk = (spans: Inline[]) => {
    for (const span of spans) {
      if (span.kind === "citation" && !found.includes(span.locator)) {
        found.push(span.locator);
      }
    }
  };
  for (const block of blocks) {
    if (block.kind === "heading" || block.kind === "paragraph") walk(block.spans);
    if (block.kind === "bullets" || block.kind === "numbers") {
      block.items.forEach(walk);
    }
    if (block.kind === "table") {
      block.columns.forEach(walk);
      block.rows.forEach((row) => row.forEach(walk));
    }
  }
  return found;
}

/** The plain text of a document, for copying and for length checks. */
export function plainText(blocks: Block[]): string {
  const spanText = (spans: Inline[]): string =>
    spans
      .map((s) =>
        s.kind === "citation" ? "" : s.kind === "link" ? s.text : s.text,
      )
      .join("");
  const out: string[] = [];
  for (const block of blocks) {
    if (block.kind === "heading" || block.kind === "paragraph") {
      out.push(spanText(block.spans));
    } else if (block.kind === "bullets" || block.kind === "numbers") {
      block.items.forEach((item) => out.push(spanText(item)));
    } else if (block.kind === "table") {
      out.push(block.columns.map(spanText).join(" | "));
      block.rows.forEach((row) => out.push(row.map(spanText).join(" | ")));
    } else {
      out.push(block.text);
    }
  }
  return out.filter(Boolean).join("\n");
}
