"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";

import { ResultTable } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import type { TraceGraph, TraceNode } from "@/lib/api";
import { humanise } from "@/lib/format";
import { cn } from "@/lib/utils";

import { presentationFor } from "./node-presentation";

/**
 * The node inspector.
 *
 * Everything on this panel was stamped by the execution itself: which dataset,
 * which governed fields and their business definitions, which filters, how many
 * rows survived, which function at which version, how long it took, and the
 * content hash that decides whether a modification has to re-run it.
 *
 * Nothing here is a description written afterwards, which is the whole point of
 * the Trace and is stated on the panel so a reader knows what they are looking
 * at.
 */

const HIDDEN_CONFIG_KEYS = new Set(["_step", "_step_title"]);

export function NodeInspector({
  node,
  graph,
  onClose,
  onSelect,
}: {
  node: TraceNode | null;
  graph: TraceGraph;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  if (!node) {
    return (
      <div className="flex h-full flex-col justify-center gap-2 px-5 py-8">
        <p className="text-sm font-medium text-text-primary">Nothing selected</p>
        <p className="text-xs leading-relaxed text-text-muted">
          Choose a step on the map. Its dataset, governed variables, filters, row counts,
          function version and recorded output appear here — everything stamped while the
          analysis ran.
        </p>
      </div>
    );
  }

  const presentation = presentationFor(node.type);
  const Icon = presentation.icon;
  const parents = graph.edges.filter((e) => e.target === node.id).map((e) => e.source);
  const children = graph.edges.filter((e) => e.source === node.id).map((e) => e.target);
  const labelOf = (id: string) => graph.nodes.find((n) => n.id === id)?.label ?? id;

  const definitions = (node.config?.definitions ?? null) as Record<string, string> | null;
  const config = Object.fromEntries(
    Object.entries(node.config ?? {}).filter(
      ([k]) => !HIDDEN_CONFIG_KEYS.has(k) && k !== "definitions",
    ),
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
            <Icon
              className="size-3"
              style={{
                color: presentation.governed
                  ? "var(--ipm-trace-governed)"
                  : "var(--ipm-trace-interpretive)",
              }}
              aria-hidden
            />
            {presentation.label}
            <Badge variant={presentation.governed ? "accent" : "outline"} className="ml-1">
              {presentation.governed ? "Governed" : "Interpretive"}
            </Badge>
          </span>
          <p className="mt-1.5 text-sm font-medium leading-snug text-text-primary">
            {node.label}
          </p>
          <p className="mt-1 text-xs leading-relaxed text-text-muted">{presentation.blurb}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
          title="Close"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
        <dl className="divide-y divide-border">
          <Row label="Status" value={node.status} />
          {node.dataset && <Row label="Dataset" value={node.dataset} mono />}
          {node.function_id && (
            <Row label="Function" value={`${node.function_id} v${node.function_version}`} mono />
          )}
          {node.rows_in !== null && <Row label="Rows in" value={node.rows_in.toLocaleString()} />}
          {node.rows_out !== null && (
            <Row label="Rows out" value={node.rows_out.toLocaleString()} />
          )}
          {node.duration_ms !== null && <Row label="Duration" value={`${node.duration_ms}ms`} />}
          {node.content_hash && <Row label="Content hash" value={node.content_hash} mono />}
        </dl>

        {node.fields_used.length > 0 && (
          <Section title={`Governed variables (${node.fields_used.length})`}>
            <ul className="space-y-1.5">
              {node.fields_used.map((field) => (
                <li key={field} className="text-xs">
                  <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
                    {field}
                  </code>
                  {definitions?.[field] && (
                    <span className="ml-2 text-text-muted">{definitions[field]}</span>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        )}

        {Object.keys(config).length > 0 && (
          <Section title="What this step was configured to do">
            <dl className="divide-y divide-border">
              {Object.entries(config).map(([key, value]) => (
                <ConfigRow key={key} label={humanise(key)} value={value} />
              ))}
            </dl>
          </Section>
        )}

        {node.output_summary && Object.keys(node.output_summary).length > 0 && (
          <Section title="Recorded output">
            <dl className="divide-y divide-border">
              {Object.entries(node.output_summary)
                .slice(0, 12)
                .map(([key, value]) => (
                  <Row key={key} label={humanise(key)} value={String(value)} />
                ))}
            </dl>
          </Section>
        )}

        {node.output_preview && node.output_preview.length > 0 && (
          <Section title="Output preview">
            <div className="overflow-x-auto rounded-md border border-border">
              <ResultTable rows={node.output_preview} maxRows={5} />
            </div>
          </Section>
        )}

        {(parents.length > 0 || children.length > 0) && (
          <Section title="Dependencies">
            <div className="space-y-2">
              {parents.length > 0 && (
                <Lineage
                  icon={ArrowUp}
                  title="Feeds into this step"
                  ids={parents}
                  labelOf={labelOf}
                  onSelect={onSelect}
                />
              )}
              {children.length > 0 && (
                <Lineage
                  icon={ArrowDown}
                  title="This step feeds"
                  ids={children}
                  labelOf={labelOf}
                  onSelect={onSelect}
                />
              )}
            </div>
          </Section>
        )}

        {node.warnings.length > 0 && (
          <div className="rounded-md border border-warning/30 bg-warning-muted p-3">
            {node.warnings.map((warning) => (
              <p key={warning} className="text-xs text-warning">
                {warning}
              </p>
            ))}
          </div>
        )}

        {node.error && (
          <div className="rounded-md border border-negative/30 bg-negative-muted p-3 text-xs text-negative">
            {node.error}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
        {title}
      </p>
      {children}
    </div>
  );
}

/**
 * One configuration entry.
 *
 * Configuration is structured data — a list of validation rules, a map of
 * parameters — and printing it as raw JSON would make the panel look like a
 * developer console rather than an inspection of the analysis. Each shape gets
 * the presentation that reads best.
 */
function ConfigRow({ label, value }: { label: string; value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    const objects = value.filter(
      (v): v is Record<string, unknown> => typeof v === "object" && v !== null,
    );
    if (objects.length === value.length) {
      return (
        <div className="py-2">
          <p className="text-xs text-text-muted">
            {label} <span className="tabular">({value.length})</span>
          </p>
          <ul className="mt-1 space-y-1">
            {objects.slice(0, 8).map((item, i) => (
              <li key={i} className="text-xs leading-relaxed text-text-secondary">
                <span className="text-text-primary">
                  {String(item.name ?? item.label ?? item.analysis_id ?? `Item ${i + 1}`)}
                </span>
                {item.description ? ` — ${String(item.description)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      );
    }
    return <Row label={label} value={value.map(String).join(", ")} wrap />;
  }

  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <Row label={label} value="none" />;
    return (
      <div className="py-2">
        <p className="text-xs text-text-muted">{label}</p>
        <dl className="mt-1 space-y-0.5">
          {entries.slice(0, 12).map(([k, v]) => (
            <div key={k} className="flex items-start justify-between gap-3">
              <dt className="text-[11px] text-text-muted">{humanise(k)}</dt>
              <dd className="text-right text-[11px] text-text-secondary">
                {typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    );
  }

  return <Row label={label} value={String(value)} wrap />;
}

function Row({
  label,
  value,
  mono,
  wrap,
}: {
  label: string;
  value: string;
  mono?: boolean;
  wrap?: boolean;
}) {
  return (
    <div className="grid grid-cols-[minmax(90px,40%)_1fr] items-start gap-3 py-1.5">
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd
        className={cn(
          "text-right text-xs text-text-secondary",
          mono && "font-mono",
          wrap ? "break-words text-left" : "truncate",
        )}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

function Lineage({
  icon: Icon,
  title,
  ids,
  labelOf,
  onSelect,
}: {
  icon: typeof ArrowUp;
  title: string;
  ids: string[];
  labelOf: (id: string) => string;
  onSelect: (id: string) => void;
}) {
  return (
    <div>
      <p className="mb-1 flex items-center gap-1 text-[11px] text-text-muted">
        <Icon className="size-3" aria-hidden />
        {title}
      </p>
      <div className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onSelect(id)}
            className="max-w-full truncate rounded border border-border bg-surface-sunken px-1.5 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-accent hover:text-accent"
          >
            {labelOf(id)}
          </button>
        ))}
      </div>
    </div>
  );
}
