"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, ChevronRight, Cpu, Sparkles } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { ResultTable } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type TraceNode } from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Trace detail.
 *
 * Loads the real stored graph — nodes, edges, layers, content hashes — and shows
 * it as a structured, inspectable preview. Every value on this page came from
 * the executor stamping it as the analysis ran.
 *
 * The interactive canvas is the next phase. This view is deliberately complete
 * rather than decorative: each node can be opened and shows exactly what it did.
 */

const NODE_LABEL: Record<string, string> = {
  PLAN: "Analysis request",
  DATASET: "Dataset",
  VARIABLE: "Variables",
  FILTER: "Filters and period",
  TRANSFORMATION: "Transformation",
  AGGREGATION: "Aggregation",
  CALCULATION: "Calculation",
  ENGINE_FUNCTION: "Engine function",
  RESULT: "Result",
  USER_PROMPT: "User prompt",
  LLM_INTENT: "LLM interpretation",
  LLM_EXPLANATION: "LLM explanation",
  VISUALIZATION: "Visualisation",
};

export default function TraceDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = React.use(params);
  const id = Number(runId);
  const [selected, setSelected] = React.useState<string | null>(null);

  const trace = useAsync(() => api.trace(id), [id]);
  const graph = trace.data?.graph;
  const byId = React.useMemo(() => {
    const map = new Map<string, TraceNode>();
    for (const n of graph?.nodes ?? []) map.set(n.id, n);
    return map;
  }, [graph]);

  const node = selected ? byId.get(selected) : null;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/trace">
          <ArrowLeft aria-hidden />
          Trace
        </Link>
      </Button>

      {trace.loading && <Skeleton className="h-96 w-full" />}
      {trace.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">{trace.error}</Card>
      )}

      {trace.data && graph && (
        <>
          <PageHeader
            title={`Trace · ${trace.data.analysis_id ?? "analysis"}`}
            description={`Analysis run ${trace.data.analysis_run_id} · ${trace.data.status} · ${trace.data.duration_ms ?? "—"}ms · recorded ${trace.data.created_at?.slice(0, 19).replace("T", " ") ?? "—"}`}
            status="partial"
            phase="Interactive graph next"
            actions={
              <div className="flex items-center gap-2">
                <Badge variant="outline">
                  {trace.data.label} · v{trace.data.version}
                </Badge>
                <Badge variant="accent">{graph.stats.node_count} nodes</Badge>
              </div>
            }
          />

          <div className="grid gap-3 sm:grid-cols-4">
            <Tile label="Nodes" value={graph.stats.node_count} />
            <Tile label="Edges" value={graph.stats.edge_count} />
            <Tile
              label="Governed"
              value={graph.stats.governed_nodes}
              hint="Carry numbers the bank must defend"
              tone="governed"
            />
            <Tile
              label="Interpretive"
              value={graph.stats.interpretive_nodes}
              hint="Produced by judgement, not arithmetic"
              tone="interpretive"
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-[1.3fr_1fr]">
            {/* ------------------------------------------------ layered graph */}
            <Card className="p-5">
              <h3 className="mb-1 text-sm font-semibold text-text-primary">Execution graph</h3>
              <p className="mb-4 text-xs text-text-muted">
                Laid out in dependency layers. Each node was stamped as the analysis ran. Select
                one to inspect it.
              </p>
              <div className="space-y-2">
                {graph.layers.map((layer, depth) => (
                  <div key={depth} className="flex items-start gap-3">
                    <span className="mt-2 w-6 shrink-0 text-right text-[10px] font-medium text-text-muted tabular">
                      L{depth}
                    </span>
                    <div className="flex flex-1 flex-wrap gap-2">
                      {layer.map((nodeId) => {
                        const n = byId.get(nodeId);
                        if (!n) return null;
                        const active = selected === nodeId;
                        return (
                          <button
                            key={nodeId}
                            type="button"
                            onClick={() => setSelected(nodeId)}
                            className={cn(
                              "flex min-w-40 max-w-64 flex-col items-start gap-0.5 rounded-md border-l-2 px-3 py-2 text-left transition-colors",
                              active
                                ? "border-l-accent bg-accent-muted"
                                : "bg-surface-sunken hover:bg-surface-hover",
                              !active &&
                                (n.is_governed
                                  ? "border-l-[var(--ipm-trace-governed)]"
                                  : "border-l-[var(--ipm-trace-interpretive)]"),
                            )}
                          >
                            <span className="flex items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-text-muted">
                              {n.is_governed ? (
                                <Cpu className="size-2.5" aria-hidden />
                              ) : (
                                <Sparkles className="size-2.5" aria-hidden />
                              )}
                              {NODE_LABEL[n.type] ?? n.type}
                            </span>
                            <span className="line-clamp-2 text-xs text-text-primary">
                              {n.label}
                            </span>
                            {n.rows_out !== null && (
                              <span className="text-[10px] text-text-muted tabular">
                                {n.rows_out.toLocaleString()} rows
                              </span>
                            )}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>

              <div className="mt-5 flex flex-wrap items-center gap-4 border-t border-border pt-3 text-[11px] text-text-muted">
                <span className="flex items-center gap-1.5">
                  <span
                    className="h-3 w-0.5 rounded-full"
                    style={{ backgroundColor: "var(--ipm-trace-governed)" }}
                    aria-hidden
                  />
                  Governed — deterministic engine
                </span>
                <span className="flex items-center gap-1.5">
                  <span
                    className="h-3 w-0.5 rounded-full"
                    style={{ backgroundColor: "var(--ipm-trace-interpretive)" }}
                    aria-hidden
                  />
                  Interpretive — judgement, never arithmetic
                </span>
              </div>
            </Card>

            {/* ------------------------------------------------ node inspector */}
            <Card className="p-5">
              <h3 className="mb-4 text-sm font-semibold text-text-primary">
                {node ? "Node detail" : "Select a node"}
              </h3>
              {!node ? (
                <p className="text-sm text-text-muted">
                  Choose a step in the graph to see the dataset, variables, filters, parameters,
                  function version, row counts and output it recorded.
                </p>
              ) : (
                <div className="space-y-4">
                  <div>
                    <Badge variant={node.is_governed ? "accent" : "warning"}>
                      {NODE_LABEL[node.type] ?? node.type}
                    </Badge>
                    <p className="mt-2 text-sm text-text-primary">{node.label}</p>
                  </div>

                  <dl className="divide-y divide-border text-sm">
                    <Row label="Status" value={node.status} />
                    {node.dataset && <Row label="Dataset" value={node.dataset} mono />}
                    {node.function_id && (
                      <Row
                        label="Function"
                        value={`${node.function_id} v${node.function_version}`}
                        mono
                      />
                    )}
                    {node.rows_in !== null && (
                      <Row label="Rows in" value={node.rows_in.toLocaleString()} />
                    )}
                    {node.rows_out !== null && (
                      <Row label="Rows out" value={node.rows_out.toLocaleString()} />
                    )}
                    {node.duration_ms !== null && (
                      <Row label="Duration" value={`${node.duration_ms}ms`} />
                    )}
                    {node.content_hash && <Row label="Content hash" value={node.content_hash} mono />}
                  </dl>

                  {node.fields_used.length > 0 && (
                    <div>
                      <p className="mb-1.5 text-xs font-medium text-text-secondary">
                        Variables read ({node.fields_used.length})
                      </p>
                      <div className="flex flex-wrap gap-1">
                        {node.fields_used.map((f) => (
                          <code
                            key={f}
                            className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-text-secondary"
                          >
                            {f}
                          </code>
                        ))}
                      </div>
                    </div>
                  )}

                  {Object.keys(node.config).length > 0 && (
                    <div>
                      <p className="mb-1.5 text-xs font-medium text-text-secondary">Configuration</p>
                      <pre className="max-h-56 overflow-auto rounded-md border border-border bg-surface-sunken p-3 font-mono text-[10px] leading-relaxed text-text-secondary">
                        {JSON.stringify(node.config, null, 2)}
                      </pre>
                    </div>
                  )}

                  {node.output_preview && node.output_preview.length > 0 && (
                    <div>
                      <p className="mb-1.5 text-xs font-medium text-text-secondary">
                        Output preview
                      </p>
                      <div className="overflow-hidden rounded-md border border-border">
                        <ResultTable rows={node.output_preview} maxRows={5} />
                      </div>
                    </div>
                  )}

                  {node.warnings.length > 0 && (
                    <div className="rounded-md border border-warning/30 bg-warning-muted p-3">
                      {node.warnings.map((w) => (
                        <p key={w} className="text-xs text-warning">
                          {w}
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
              )}
            </Card>
          </div>

          {/* ---------------------------------------------------------- edges */}
          <Card className="p-5">
            <h3 className="mb-3 text-sm font-semibold text-text-primary">
              Dependencies
              <span className="ml-2 text-xs font-normal text-text-muted">
                {graph.edges.length} edges
              </span>
            </h3>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5">
              {graph.edges.map((e, i) => (
                <span
                  key={i}
                  className="flex items-center gap-1 font-mono text-[11px] text-text-muted"
                >
                  {byId.get(e.source)?.label.slice(0, 28) ?? e.source}
                  <ChevronRight className="size-3" aria-hidden />
                  {byId.get(e.target)?.label.slice(0, 28) ?? e.target}
                </span>
              ))}
            </div>
          </Card>

          <Card className="border-info/30 bg-info-muted p-4 text-sm text-info">
            The interactive canvas — pan, zoom, and an “Ask / Modify Trace” prompt that branches to
            a new version and re-runs only the affected steps — is the next phase. The graph model,
            content hashing and version storage it needs are already in place and are what this
            page reads.
          </Card>
        </>
      )}
    </div>
  );
}

function Tile({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: number;
  hint?: string;
  tone?: "governed" | "interpretive";
}) {
  return (
    <Card className="p-4">
      <p className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-text-muted">
        {tone && (
          <span
            className="size-2 rounded-full"
            style={{
              backgroundColor:
                tone === "governed"
                  ? "var(--ipm-trace-governed)"
                  : "var(--ipm-trace-interpretive)",
            }}
            aria-hidden
          />
        )}
        {label}
      </p>
      <p className="mt-1.5 text-2xl font-semibold text-text-primary tabular">{value}</p>
      {hint && <p className="mt-0.5 text-[11px] text-text-muted">{hint}</p>}
    </Card>
  );
}

function Row({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 py-1.5">
      <dt className="shrink-0 text-xs text-text-muted">{label}</dt>
      <dd className={cn("text-right text-xs text-text-secondary", mono && "font-mono")}>{value}</dd>
    </div>
  );
}
