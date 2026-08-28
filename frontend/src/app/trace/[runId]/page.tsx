"use client";

import { useSearchParams } from "next/navigation";
import * as React from "react";
import { Clock, GitBranch, Layers, Sparkles } from "lucide-react";

import { DownloadCalculation } from "@/components/exports/download";
import { AgenticTrace } from "@/components/agentic/trace-panel";
import { ExportHistory } from "@/components/exports/history";
import { AuditLedger } from "@/components/trace/audit-ledger";
import { HealthMap } from "@/components/trace/health-map";
import { TraceLandscape } from "@/components/trace/landscape";
import { ModeSwitcher, useTraceMode } from "@/components/trace/modes";
import { NodeInspector } from "@/components/trace/node-inspector";
import { ModifyPanel, VersionSwitcher } from "@/components/trace/modify-panel";
import { ClusterList, ReasoningMap, type MapHighlight } from "@/components/trace/reasoning-map";
import { TraceStory } from "@/components/trace/story";
import { VersionCompare } from "@/components/trace/version-compare";
import { traceActions } from "@/components/trace/actions";
import { Badge } from "@/components/ui/badge";
import { BackLink } from "@/components/layout/back-link";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { fromTraceNode } from "@/lib/return-to";
import {
  api,
  type Narrative,
  type ProposedChange,
  type RunMode,
} from "@/lib/api";
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
/**
 * How this run was produced, in one phrase.
 *
 * Two facts, because a reader needs both: who read the question, and whether
 * the analysis was composed for it or selected from the registry.
 */
function readBy(mode: RunMode | undefined): string {
  const read =
    mode?.configured === true
      ? `read by ${String(mode?.model_name ?? "the configured model")}`
      : "read by the deterministic semantic planner";
  const built =
    mode?.fallback === true
      ? "answered from registered analyses"
      : mode?.execution === "metadata"
        ? "answered from the governed catalogue"
        : "composed for this question";
  return `Question ${read} · ${built}`;
}

export default function TraceDetailPage({ params }: { params: Promise<{ runId: string }> }) {
  const { runId } = React.use(params);
  return (
    <React.Suspense fallback={<Skeleton className="h-[32rem] w-full" />}>
      <TraceDetail runId={runId} />
    </React.Suspense>
  );
}

/**
 * The Trace, with its mode and its selected step in the address.
 *
 * §5 asks that opening a dataset in Data Builder from a Trace node and coming
 * back land on THAT node, in the mode it was being read in. A Back that returns
 * a reader to Story with nothing selected, after they had drilled into a join
 * in Lineage, has technically returned them and practically thrown away the
 * thing they were looking at. Both therefore live in the URL, so the link out
 * can carry them and the link back can restore them.
 */
function TraceDetail({ runId }: { runId: string }) {
  const id = Number(runId);
  const query = useSearchParams();

  const [version, setVersion] = React.useState<number | undefined>(undefined);
  const [selected, setSelected] = React.useState<string | null>(
    () => query.get("node"),
  );
  // Story, Lineage, Landscape or Audit. Remembered, and the selection survives
  // a switch — following a node from the story into the graph keeps it chosen.
  const [view, setView] = useTraceMode(query.get("mode"));
  const [proposed, setProposed] = React.useState<ProposedChange | null>(null);

  const investigation = useAsync(() => api.investigation(id, version), [id, version]);
  // The list of changes CreditProbe can make is served by the backend rather than
  // hard-coded here, so the two can never drift apart.
  const mode = useAsync(() => api.askMode(), []);
  const data = investigation.data;
  const graph = data?.graph;

  const node = React.useMemo(
    () => (selected ? (graph?.nodes.find((n) => n.id === selected) ?? null) : null),
    [graph, selected],
  );

  // Rewrite the address as the reader moves, so a link taken from here carries
  // exactly what is on screen. `replaceState` rather than a router push: the
  // mode and the selection are a view, not a place, and thirty entries in the
  // history stack for one Trace would break the browser's own Back.
  React.useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("mode", view);
    if (selected) url.searchParams.set("node", selected);
    else url.searchParams.delete("node");
    window.history.replaceState(window.history.state, "", url);
  }, [view, selected]);

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
      <BackLink href="/trace" label="Trace & Lineage" />

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
            {/* §46: the pack download lives in the Trace header itself, so it
                is present in Story, Lineage, Landscape and Audit alike — the
                mode is a way of reading this analysis, not four analyses. */}
            <div className="flex items-start justify-between gap-6">
              <div className="min-w-0">
                <p className="text-[11px] font-medium uppercase tracking-[0.16em] text-text-muted">
                  Analytical Reasoning Map
                </p>
                <h1 className="mt-2 max-w-3xl text-2xl font-semibold leading-tight tracking-tight text-text-primary">
                  {data.question || data.intent || `Analysis run ${id}`}
                </h1>
                {data.intent && data.question && (
                  <p className="mt-1.5 max-w-3xl text-sm text-text-secondary">{data.intent}</p>
                )}
              </div>
              <DownloadCalculation
                runId={id}
                version={data.version}
                className="shrink-0"
              />
            </div>

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
              {/* Who READ the question, and how the analysis was produced.
                  "Planned by CreditProbe (deterministic)" said neither, and
                  was the line that made it look like a model was involved when
                  none was — and like a model was NOT involved when one is. */}
              <span className="flex items-center gap-1.5">
                <Sparkles className="size-3.5" aria-hidden />
                {readBy(data.mode)}
              </span>
              {data.mode?.fallback === true && (
                <Badge variant="warning">Fallback: registered analyses</Badge>
              )}
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

          {/* §49: version comparison. The switcher moves between versions; the
              question a reader actually has is what a modification DID, and
              reading two graphs side by side is not an answer to it. */}
          {data.available_versions.length > 1 && (
            <VersionCompare
              runId={id}
              current={data}
              currentVersion={data.version}
              versions={data.available_versions}
            />
          )}

          {/* §26, §27 — the coordination behind this analysis, where a
              coordinated run produced it. Above the graph because the question
              "who decided to run this, and what else did they run" comes
              before "what were the forty steps". Absent for an ordinary
              analysis, which is most of them. */}
          <AgenticTrace analysisRunId={id} />

          {/* -------------------------------------------------- health map */}
          {/* Before the map, because the question a Trace is opened with is
              almost never "show me all forty steps" — it is "did anything go
              wrong, and where". */}
          <HealthMap
            graph={graph}
            selected={selected}
            onFocus={setSelected}
            className="pt-1"
          />

          {/* ------------------------------------------------ map + inspector */}
          {/* The map gets the full width. The inspector slides over it rather
              than sitting beside it: a permanent side panel would take a third
              of the canvas from a diagram that needs every pixel it can get. */}
          <div className="relative">
            <ModeSwitcher mode={view} onChange={setView} className="mb-3" />

            {view === "story" && (
              <TraceStory graph={graph} selected={selected} onSelect={setSelected} />
            )}
            {view === "lineage" && (
              <>
                <ReasoningMap
                  graph={graph}
                  selected={selected}
                  onSelect={setSelected}
                  highlight={highlight}
                  height={560}
                />
                {/* The same eight clusters, without the canvas.
                    A spatial diagram is unusable with a screen reader and
                    awkward with a keyboard, and "use the Audit tab instead"
                    sends that reader to a different view of a different thing.
                    This is the Lineage view's own content, in a list that
                    tabs — closed by default so it costs a sighted reader
                    nothing. */}
                <details className="mt-3 rounded-lg border border-border bg-surface">
                  <summary className="cursor-pointer px-4 py-2.5 text-[12px] font-medium text-text-secondary">
                    The same clusters as a list
                  </summary>
                  <ClusterList
                    graph={graph}
                    onSelect={setSelected}
                    className="border-t border-border p-4"
                  />
                </details>
              </>
            )}
            {view === "landscape" && (
              <TraceLandscape
                graph={graph}
                selected={selected}
                onSelect={setSelected}
              />
            )}
            {view === "audit" && (
              <div className="space-y-4">
                <AuditLedger
                  graph={graph}
                  selected={selected}
                  onSelect={setSelected}
                />
                {/* §41: the export activity belongs in the analysis's audit
                    history. A workbook leaves the product, so "who has a copy
                    of this, and which version" is a question somebody
                    eventually has to answer. */}
                <ExportHistory runId={id} />
              </div>
            )}
            {node && view !== "story" && (
              <div className="pointer-events-none absolute inset-y-0 right-0 flex w-full max-w-[26rem] p-3">
                <Card className="pointer-events-auto flex max-h-full w-full flex-col overflow-hidden p-0 shadow-xl">
                  <NodeInspector
                    node={node}
                    graph={graph}
                    onClose={() => setSelected(null)}
                    onSelect={setSelected}
                    from={fromTraceNode(id, view, node.id)}
                  />
                </Card>
              </div>
            )}
          </div>

          {/* In Story the inspector sits BELOW rather than over the text. The
              story is a column somebody is reading; a panel sliding across it
              hides the sentence that made them click. */}
          {node && view === "story" && (
            <Card className="overflow-hidden p-0">
              <NodeInspector
                node={node}
                graph={graph}
                onClose={() => setSelected(null)}
                onSelect={setSelected}
                from={fromTraceNode(id, view, node.id)}
              />
            </Card>
          )}

          {/* --------------------------------------------------------- modify */}
          <ModifyPanel
            runId={id}
            version={data.version}
            supported={mode.data?.supported_modifications ?? []}
            actions={traceActions(
              graph,
              data.mode,
              mode.data?.supported_modifications ?? [],
            )}
            onPreview={setProposed}
            onApplied={(newVersion) => {
              setVersion(newVersion);
              setSelected(null);
            }}
            disabled={stepCount === 0}
            disabledReason={
              "This trace was recorded before CreditProbe stored the plan behind it, so it cannot be " +
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
