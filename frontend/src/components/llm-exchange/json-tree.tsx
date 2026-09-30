"use client";

/**
 * A collapsible, searchable JSON viewer for recorded exchanges.
 *
 * Renders data as React text nodes only -- a recorded prompt or tool result
 * is untrusted text and is never interpreted as markup.
 */

import * as React from "react";
import { ChevronDown, ChevronRight, Copy, Download, WrapText } from "lucide-react";

import { downloadText } from "@/components/viz/chart-card";
import { cn } from "@/lib/utils";

function matches(value: unknown, needle: string): boolean {
  if (!needle) return true;
  try {
    return JSON.stringify(value).toLowerCase().includes(needle.toLowerCase());
  } catch {
    return false;
  }
}

function Node({
  name,
  value,
  depth,
  needle,
  expandAll,
}: {
  name: string;
  value: unknown;
  depth: number;
  needle: string;
  expandAll: boolean;
}) {
  const isObject = value !== null && typeof value === "object";
  const [open, setOpen] = React.useState(depth < 2 || expandAll);
  const [openedFor, setOpenedFor] = React.useState(expandAll);
  if (openedFor !== expandAll) {
    setOpenedFor(expandAll);
    setOpen(depth < 2 || expandAll);
  }
  if (!matches(value, needle) && !name.toLowerCase().includes(needle.toLowerCase())) return null;
  if (!isObject) {
    const text = typeof value === "string" ? value : JSON.stringify(value);
    const hit = needle && text.toLowerCase().includes(needle.toLowerCase());
    return (
      <div className="pl-4">
        <span className="text-text-muted">{name}: </span>
        <span className={cn("whitespace-pre-wrap break-words", typeof value === "string" ? "text-accent" : "text-text-primary", hit && "bg-warning-muted")}>
          {typeof value === "string" ? `"${text}"` : text}
        </span>
      </div>
    );
  }
  const entries = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as const)
    : Object.entries(value as Record<string, unknown>);
  return (
    <div className="pl-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex items-center gap-0.5 text-text-secondary hover:text-text-primary"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        <span>{name}</span>
        <span className="text-text-muted">
          {Array.isArray(value) ? ` [${entries.length}]` : ` {${entries.length}}`}
        </span>
      </button>
      {open && (
        <div className="border-l border-border pl-1">
          {entries.map(([k, v]) => (
            <Node key={k} name={k} value={v} depth={depth + 1} needle={needle} expandAll={expandAll} />
          ))}
        </div>
      )}
    </div>
  );
}

export function JsonTree({
  value,
  filename,
  testId,
}: {
  value: unknown;
  filename: string;
  testId?: string;
}) {
  const [needle, setNeedle] = React.useState("");
  const [raw, setRaw] = React.useState(false);
  const [wrap, setWrap] = React.useState(true);
  const [expandAll, setExpandAll] = React.useState(false);
  const text = React.useMemo(() => JSON.stringify(value, null, 2), [value]);
  return (
    <div className="rounded-md border border-border bg-surface-sunken" data-testid={testId}>
      <div className="flex flex-wrap items-center gap-2 border-b border-border p-2 text-xs">
        <input
          value={needle}
          onChange={(e) => setNeedle(e.target.value)}
          placeholder="Search this payload"
          aria-label="Search this payload"
          className="min-w-[12rem] flex-1 rounded border border-border bg-surface px-2 py-1"
        />
        <button type="button" onClick={() => setRaw((v) => !v)} className="rounded border border-border px-2 py-1">
          {raw ? "Tree" : "Raw JSON"}
        </button>
        <button type="button" onClick={() => setExpandAll((v) => !v)} className="rounded border border-border px-2 py-1">
          {expandAll ? "Collapse" : "Expand all"}
        </button>
        <button
          type="button"
          onClick={() => setWrap((v) => !v)}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-1"
          aria-pressed={wrap}
        >
          <WrapText className="h-3 w-3" /> Wrap
        </button>
        <button
          type="button"
          onClick={() => void navigator.clipboard?.writeText(text)}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-1"
        >
          <Copy className="h-3 w-3" /> Copy
        </button>
        <button
          type="button"
          onClick={() => downloadText(text, filename, "application/json")}
          className="inline-flex items-center gap-1 rounded border border-border px-2 py-1"
        >
          <Download className="h-3 w-3" /> Download
        </button>
      </div>
      <div className="max-h-[32rem] overflow-auto p-2 font-mono text-[11px] leading-relaxed">
        {raw ? (
          <pre className={cn(wrap ? "whitespace-pre-wrap break-words" : "whitespace-pre")}>
            {needle
              ? text
                  .split("\n")
                  .filter((l) => l.toLowerCase().includes(needle.toLowerCase()))
                  .join("\n")
              : text}
          </pre>
        ) : (
          <Node name="$" value={value} depth={0} needle={needle} expandAll={expandAll} />
        )}
      </div>
    </div>
  );
}
