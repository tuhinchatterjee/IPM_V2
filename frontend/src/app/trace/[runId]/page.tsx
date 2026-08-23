"use client";

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Clock, GitBranch, Layers, Sparkles } from "lucide-react";

import { NodeInspector } from "@/components/trace/node-inspector";
import { ModifyPanel, VersionSwitcher } from "@/components/trace/modify-panel";
import { ReasoningMap, type MapHighlight } from "@/components/trace/reasoning-map";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type Narrative, type ProposedChange } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Trace detail — the Analytical Reasoning Map for one investigation.
 *
 * The page answers three questions, in this order:
 *
 *   How was this produced?      the map, with every step inspectable
 *   What does that step say?    the inspector, showing what execution stamped
 *   What if I change it?        Ask / Modify Trace, previewed then branched
 *
 * Every version ever produced stays reachable from the switcher at the top. A
 * modification never overwrites what a colleague already read.
 */
export default function TraceDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = React.use(params);
  const id = Number(runId);

  const [version, setVersion] = React.useState<number | undefined>(undefined);
  const [selected, setSelected] = React.useState<string | null>(null);
  const [proposed, setProposed] = React.useState<ProposedChange | null>(null);

  const investigation = useAsync(() => api.investigation(id, version), [id, version]);
  // The list of changes IPM can make is served by the backend rather than
  // hard-coded here, so the two can never drift apart.
  const mode = useAsync(() => api.askMode(), []);
  const data = investigation.data;
  const graph = data?.graph;

  const node = React.useMemo(
    () => (selected ? (graph?.nodes.find((n) => n.id === selected) ?? null) : null),
    [graph, selected],
  );

  const highlight: MapHighlight | undefined = React.useMemo(() => {
    if (!proposed?.understood) return undefined;
    return {
      changed: proposed.affected_nodes,
      downstream: proposed.downstream_nodes,
    };
  }, [proposed]);

  const narrative = (data?.narrative ?? {}) as Partial<Narrative>;
  const stepCount = data?.steps.length ?? 0;

  return (
    <div className="space-y-6">
      <Button variant="ghost" size="sm" asChild className="-ml-2">
        <Link href="/trace">
          <ArrowLeft aria-hidden />
          Trace &amp; Lineage
        </Link>
      </Button>

      {investigation.loading && <Skeleton className="h-[32rem] w-full" />}
      {investigation.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {investigation.error}
        </Card>
      )}

      {data && graph && (
        <>
          {/* --------------------------------------------------------- header */}
          <header className="border-b border-border pb-5">
            <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
              Analytical Reasoning Map
            </p>
            <h1 className="mt-2 max-w-3xl text-2xl font-semibold leading-tight tracking-tight text-text-primary">
              {data.question || data.intent || `Analysis run ${id}`}
            </h1>
            {data.intent && data.question && (
              <p className="mt-1.5 max-w-3xl text-sm text-text-secondary">{data.intent}</p>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-text-muted">
              <span className="flex items-center gap-1.5">
                <Layers className="size-3.5" aria-hidden />
                {graph.stats.node_count} steps · {graph.stats.governed_nodes} governed ·{" "}
                {graph.stats.interpretive_nodes} interpretive
              </span>
              <span className="flex items-center gap-1.5">
                <Clock className="size-3.5" aria-hidden />
                {data.duration_ms ?? "—"}ms
                {data.created_at ? ` · ${data.created_at.slice(0, 16).replace("T", " ")}` : ""}
              </span>
              <span className="flex items-center gap-1.5">
                <Sparkles className="size-3.5" aria-hidden />
                Planned by {data.mode?.planner === "demo" ? "IPM (deterministic)" : data.mode?.planner}
              </span>
              <Badge variant="outline">{data.label}</Badge>
            </div>

            {data.available_versions.length > 1 && (
              <div className="mt-4 flex flex-wrap items-center gap-3">
                <span className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-[0.11em] text-text-muted">
                  <GitBranch className="size-3.5" aria-hidden />
                  Versions
                </span>
                <VersionSwitcher
                  versions={data.available_versions}
                  current={data.version}
                  onSelect={(v) => {
                    setVersion(v);
                    setSelected(null);
                    setProposed(null);
                  }}
                />
              </div>
            )}
          </header>

          {/* ------------------------------------------------ map + inspector */}
          {/* The map gets the full width. The inspector slides over it rather
              than sitting beside it: a permanent side panel would take a third
              of the canvas from a diagram that needs every pixel it can get. */}
          <div className="relative">
            <ReasoningMap
              graph={graph}
              selected={selected}
              onSelect={setSelected}
              highlight={highlight}
              height={520}
            />
            {node && (
              <div className="pointer-events-none absolute inset-y-0 right-0 flex w-full max-w-[26rem] p-3">
                <Card className="pointer-events-auto flex max-h-full w-full flex-col overflow-hidden p-0 shadow-xl">
                  <NodeInspector
                    node={node}
                    graph={graph}
                    onClose={() => setSelected(null)}
                    onSelect={setSelected}
                  />
                </Card>
              </div>
            )}
          </div>

          {/* --------------------------------------------------------- modify */}
          <ModifyPanel
            runId={id}
            version={data.version}
            supported={mode.data?.supported_modifications ?? []}
            onPreview={setProposed}
            onApplied={(newVersion) => {
              setVersion(newVersion);
              setSelected(null);
            }}
            disabled={stepCount === 0}
            disabledReason={
              "This trace was recorded before IPM stored the plan behind it, so it cannot be " +
              "modified. Re-run the analysis to get a modifiable version."
            }
          />

          {/* ------------------------------------------------------- findings */}
          {narrative.summary && (
            <Card className="p-5">
              <h3 className="text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
                Findings on this version
              </h3>
              <p className="mt-2 max-w-3xl text-sm leading-relaxed text-text-primary">
                {narrative.summary}
              </p>
              {narrative.findings && narrative.findings.length > 0 && (
                <ul className="mt-3 space-y-1.5">
                  {narrative.findings.slice(0, 6).map((finding, i) => (
                    <li key={i} className="flex gap-2 text-xs leading-relaxed text-text-secondary">
                      <span aria-hidden className="text-text-muted">
                        ·
                      </span>
                      <span>{finding.text}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          <p className="border-t border-border pt-4 text-xs leading-relaxed text-text-muted">
            Trace is emitted <strong>by</strong> execution. Every row count, duration, function
            version and content hash on this map was stamped as the analysis ran — not written
            afterwards, and never written by a language model.
          </p>
        </>
      )}
    </div>
  );
}
