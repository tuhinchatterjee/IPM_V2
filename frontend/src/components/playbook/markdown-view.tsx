"use client";

import * as React from "react";

import type { Block, Inline } from "@/lib/markdown";
import { parse } from "@/lib/markdown";
import { cn } from "@/lib/utils";

/**
 * Render Playbook's answers.
 *
 * Every node here is a React element built from a typed span. There is no
 * `dangerouslySetInnerHTML` anywhere in this file and there must never be one:
 * the text being rendered came out of documents somebody uploaded, so the only
 * safe rendering is one where markup is structurally unrepresentable rather
 * than filtered out afterwards.
 *
 * Citations render as a small superscript marker rather than as inline
 * `[[locator]]`, which is a debugging artefact and not something a credit
 * committee should have to read past.
 */

function Spans({ spans }: { spans: Inline[] }) {
  return (
    <>
      {spans.map((span, i) => {
        switch (span.kind) {
          case "strong":
            return (
              <strong key={i} className="font-semibold text-text-primary">
                {span.text}
              </strong>
            );
          case "em":
            return (
              <em key={i} className="italic">
                {span.text}
              </em>
            );
          case "code":
            return (
              <code
                key={i}
                className="mono rounded bg-surface-sunken px-1 py-0.5 text-[0.9em]"
              >
                {span.text}
              </code>
            );
          case "link":
            return (
              <a
                key={i}
                href={span.href}
                className="text-accent underline underline-offset-2"
                rel="noreferrer noopener"
                target="_blank"
              >
                {span.text}
              </a>
            );
          case "citation":
            return (
              <sup
                key={i}
                title={span.locator}
                className="mono ml-0.5 cursor-help text-[10px] text-text-muted"
              >
                [src]
              </sup>
            );
          default:
            return <React.Fragment key={i}>{span.text}</React.Fragment>;
        }
      })}
    </>
  );
}

function Heading({ level, spans }: { level: number; spans: Inline[] }) {
  const cls =
    level <= 1
      ? "mt-5 text-base font-semibold text-text-primary"
      : level === 2
        ? "mt-4 text-sm font-semibold text-text-primary"
        : "mt-3 text-sm font-medium text-text-primary";
  // The document's own h1 is its title, which is already shown above the
  // thread, so headings render one level down to keep the page outline sane.
  const Tag = (`h${Math.min(level + 1, 6)}` as unknown) as keyof React.JSX.IntrinsicElements;
  return React.createElement(Tag, { className: cls }, <Spans spans={spans} />);
}

export function MarkdownView({
  source,
  blocks,
  className,
}: {
  source?: string;
  blocks?: Block[];
  className?: string;
}) {
  const parsed = React.useMemo(
    () => blocks ?? parse(source ?? ""),
    [blocks, source],
  );

  return (
    <div className={cn("prose-ai space-y-2 text-sm", className)}>
      {parsed.map((block, i) => {
        switch (block.kind) {
          case "heading":
            return <Heading key={i} level={block.level} spans={block.spans} />;
          case "bullets":
            return (
              <ul key={i} className="ml-4 list-disc space-y-1">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <Spans spans={item} />
                  </li>
                ))}
              </ul>
            );
          case "numbers":
            return (
              <ol key={i} className="ml-4 list-decimal space-y-1">
                {block.items.map((item, j) => (
                  <li key={j}>
                    <Spans spans={item} />
                  </li>
                ))}
              </ol>
            );
          case "table":
            return (
              // A wide table scrolls inside its own box. Without this a
              // committee-sized table pushes the whole thread sideways, which
              // browser acceptance checks for and a reader notices first.
              <div
                key={i}
                className="my-3 overflow-x-auto rounded-md border border-border"
              >
                <table className="w-full border-collapse text-xs">
                  <thead>
                    <tr className="bg-surface-sunken">
                      {block.columns.map((column, j) => (
                        <th
                          key={j}
                          scope="col"
                          className="border-b border-border px-3 py-2 text-left font-semibold text-text-primary"
                        >
                          <Spans spans={column} />
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, j) => (
                      <tr key={j} className="odd:bg-surface even:bg-surface-sunken/40">
                        {row.map((cell, k) => (
                          <td
                            key={k}
                            className="border-b border-border px-3 py-1.5 align-top tabular"
                          >
                            <Spans spans={cell} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "code":
            return (
              <pre
                key={i}
                className="mono overflow-x-auto rounded-md bg-surface-sunken p-3 text-xs"
              >
                {block.text}
              </pre>
            );
          default:
            return (
              <p key={i} className="leading-relaxed">
                <Spans spans={block.spans} />
              </p>
            );
        }
      })}
    </div>
  );
}
