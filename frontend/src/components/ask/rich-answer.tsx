import { Fragment } from "react";

import { readRichText, type Block, type Span } from "@/components/ask/rich-text";

/**
 * The renderer for a structured CreditProbe answer.
 *
 * Every element here is a React element built from typed blocks. Nothing is
 * injected as HTML, so an answer containing markup shows the markup rather
 * than executing it.
 *
 * The visual job is whitespace and hierarchy. A product answer is read the way
 * a memo is read - the reader scans the headings, stops at the one that
 * matters and reads two short paragraphs - and that only works if the headings
 * are visibly headings and the paragraphs are visibly short.
 */

function Spans({ spans }: { spans: Span[] }) {
  return (
    <>
      {spans.map((span, index) => {
        if (span.kind === "bold") {
          return (
            <strong key={index} className="font-semibold text-text-primary">
              {span.text}
            </strong>
          );
        }
        if (span.kind === "italic") {
          return (
            <em key={index} className="italic">
              {span.text}
            </em>
          );
        }
        return <Fragment key={index}>{span.text}</Fragment>;
      })}
    </>
  );
}

/**
 * A process flow, as text.
 *
 * Steps wrap rather than scroll, so a seven-step flow stays readable on a
 * laptop instead of running off the side of the panel.
 */
function Flow({ steps }: { steps: string[] }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 rounded-lg border border-border bg-surface-raised px-4 py-3">
      {steps.map((step, index) => (
        <Fragment key={`${step}-${index}`}>
          {index > 0 && (
            <span aria-hidden className="text-text-muted">
              →
            </span>
          )}
          <span className="font-mono text-[11px] uppercase tracking-[0.06em] text-text-secondary">
            {step}
          </span>
        </Fragment>
      ))}
    </div>
  );
}

function Table({ columns, rows }: { columns: string[]; rows: string[][] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-[13px]">
        <thead>
          <tr>
            {columns.map((column) => (
              <th
                key={column}
                className="border-b border-border py-2 pr-4 text-left font-medium text-text-muted"
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {row.map((cell, cellIndex) => (
                <td
                  key={cellIndex}
                  className="border-b border-border/60 py-2 pr-4 align-top text-text-secondary"
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function One({ block }: { block: Block }) {
  switch (block.kind) {
    case "heading":
      if (block.level === 2) {
        return (
          <h2 className="mt-2 text-[15px] font-semibold tracking-[-0.01em] text-text-primary">
            <Spans spans={block.spans} />
          </h2>
        );
      }
      return (
        <h3 className="mt-1 text-[13px] font-semibold text-text-primary">
          <Spans spans={block.spans} />
        </h3>
      );
    case "bullets":
      return (
        <ul className="flex list-none flex-col gap-2 pl-0">
          {block.items.map((item, index) => (
            <li key={index} className="relative pl-4 leading-[1.55] text-text-secondary">
              <span
                aria-hidden
                className="absolute left-0 top-[0.62em] h-[3px] w-[3px] rounded-full bg-text-muted"
              />
              <Spans spans={item} />
            </li>
          ))}
        </ul>
      );
    case "flow":
      return <Flow steps={block.steps} />;
    case "quote":
      return (
        <blockquote className="border-l-2 border-border-strong pl-3 text-text-secondary">
          <Spans spans={block.spans} />
        </blockquote>
      );
    case "table":
      return <Table columns={block.columns} rows={block.rows} />;
    default:
      return (
        <p className="leading-[1.55] text-text-secondary">
          <Spans spans={block.spans} />
        </p>
      );
  }
}

/**
 * A structured answer, rendered.
 *
 * `gap-4` between blocks is the whitespace the remediation asked for, and it
 * is applied here rather than by the composer: the backend emits blank lines,
 * the layout turns them into space.
 */
export function RichText({ markdown }: { markdown: string }) {
  const blocks = readRichText(markdown);
  if (blocks.length === 0) return null;
  return (
    <div className="flex flex-col gap-4 text-[15px]">
      {blocks.map((block, index) => (
        <One key={index} block={block} />
      ))}
    </div>
  );
}
