"use client";

/**
 * Render a parsed answer as React elements.
 *
 * Every node becomes an element. No HTML string is ever constructed, so there
 * is no `dangerouslySetInnerHTML` on this path and nothing to sanitize: text
 * that looks like markup is displayed as text, because that is all it is.
 *
 * The styling aims at a readable executive answer — a comfortable measure,
 * real paragraph spacing, headings that are distinct without shouting, and
 * tables that scroll rather than break the column.
 */

import * as React from "react";

// `markdown-parse` rather than `markdown`: a `.ts` and a `.tsx` with the
// same stem resolve differently in tsc and in the bundler, and the
// bundler resolved this file to itself.
import {
  parseMarkdown,
  type Block,
  type Inline,
} from "./markdown-parse";

function renderInline(nodes: Inline[], keyPrefix = ""): React.ReactNode {
  return nodes.map((node, i) => {
    const key = `${keyPrefix}${i}`;
    switch (node.kind) {
      case "text":
        return <React.Fragment key={key}>{node.value}</React.Fragment>;
      case "strong":
        return (
          <strong key={key} className="font-semibold text-slate-900">
            {renderInline(node.children, `${key}-`)}
          </strong>
        );
      case "em":
        return <em key={key}>{renderInline(node.children, `${key}-`)}</em>;
      case "code":
        return (
          <code
            key={key}
            className="rounded bg-slate-100 px-1 py-0.5 font-mono text-[0.85em] text-slate-800"
          >
            {node.value}
          </code>
        );
      case "link":
        return (
          <a
            key={key}
            href={node.href}
            target="_blank"
            rel="noreferrer noopener"
            className="text-sky-700 underline underline-offset-2"
          >
            {renderInline(node.children, `${key}-`)}
          </a>
        );
      default:
        return null;
    }
  });
}

function renderBlock(block: Block, key: string): React.ReactNode {
  switch (block.kind) {
    case "heading": {
      const common = "font-semibold text-slate-900";
      if (block.level === 2) {
        return (
          <h2 key={key} className={`mt-5 mb-2 text-base ${common} first:mt-0`}>
            {renderInline(block.children, `${key}-`)}
          </h2>
        );
      }
      if (block.level === 3) {
        return (
          <h3 key={key} className={`mt-4 mb-1.5 text-sm ${common}`}>
            {renderInline(block.children, `${key}-`)}
          </h3>
        );
      }
      return (
        <h4
          key={key}
          className="mt-3 mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500"
        >
          {renderInline(block.children, `${key}-`)}
        </h4>
      );
    }
    case "paragraph":
      return (
        <p key={key} className="my-2 text-sm leading-relaxed text-slate-700">
          {renderInline(block.children, `${key}-`)}
        </p>
      );
    case "bullets":
      return (
        <ul key={key} className="my-2 space-y-1.5 pl-5">
          {block.items.map((item, i) => (
            <li
              key={`${key}-${i}`}
              className="list-disc text-sm leading-relaxed text-slate-700 marker:text-slate-400"
            >
              {renderInline(item, `${key}-${i}-`)}
            </li>
          ))}
        </ul>
      );
    case "ordered":
      return (
        <ol key={key} start={block.start} className="my-2 space-y-1.5 pl-5">
          {block.items.map((item, i) => (
            <li
              key={`${key}-${i}`}
              className="list-decimal text-sm leading-relaxed text-slate-700 marker:text-slate-400"
            >
              {renderInline(item, `${key}-${i}-`)}
            </li>
          ))}
        </ol>
      );
    case "quote":
      return (
        <blockquote
          key={key}
          className="my-3 border-l-2 border-slate-300 pl-3 text-sm italic leading-relaxed text-slate-600"
        >
          {renderInline(block.children, `${key}-`)}
        </blockquote>
      );
    case "code":
      return (
        <pre
          key={key}
          className="my-3 overflow-x-auto rounded bg-slate-900 p-3 text-xs leading-relaxed text-slate-100"
        >
          <code>{block.value}</code>
        </pre>
      );
    case "table":
      return (
        <div key={key} className="my-3 overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {block.header.map((cell, i) => (
                  <th
                    key={`${key}-h${i}`}
                    className="border-b border-slate-300 px-2 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-slate-500"
                  >
                    {renderInline(cell, `${key}-h${i}-`)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {block.rows.map((row, r) => (
                <tr key={`${key}-r${r}`}>
                  {row.map((cell, c) => (
                    <td
                      key={`${key}-r${r}c${c}`}
                      className="border-b border-slate-100 px-2 py-1.5 align-top text-slate-700"
                    >
                      {renderInline(cell, `${key}-r${r}c${c}-`)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      );
    case "rule":
      return <hr key={key} className="my-4 border-slate-200" />;
    default:
      return null;
  }
}

/** An answer, rendered. */
export function Markdown({ source }: { source: string }) {
  const blocks = React.useMemo(() => parseMarkdown(source), [source]);
  return (
    <div data-testid="v4-markdown" className="max-w-[68ch]">
      {blocks.map((block, i) => renderBlock(block, `b${i}`))}
    </div>
  );
}
