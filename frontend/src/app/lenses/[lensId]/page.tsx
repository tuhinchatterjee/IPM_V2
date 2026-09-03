"use client";

import Link from "next/link";
import * as React from "react";
import {
  GitBranch,
  History,
  Loader2,
  RotateCcw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { ResultView } from "@/components/analytics/result-view";
import { MetricTile } from "@/components/metrics/metric-tile";
import { DownloadResults } from "@/components/exports/download";
import { Badge } from "@/components/ui/badge";
import { BackLink } from "@/components/layout/back-link";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { CertificationBadge } from "@/components/ui/certified-mark";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type AnalysisRunResponse,
  type Lens,
  type RenderedLens,
  type RenderedPanel,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { fromLens, linkBack, type ReturnContext } from "@/lib/return-to";

/**
 * One Lens, live.
 *
 * Every panel executed just now, against whatever is published. Each carries
 * its own Trace, because a panel on a dashboard is exactly as much of a claim as
 * an answer to a question and deserves exactly as much lineage.
 *
 * The composer at the bottom changes the lens by asking. Each applied change is
 * a new revision with a sentence saying what changed, and the history below it
 * can put any earlier one back.
 */
export default function LensPage({
  params,
}: {
  params: Promise<{ lensId: string }>;
}) {
  const { lensId } = React.use(params);
  const id = Number(lensId);

  if (!Number.isFinite(id)) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        &ldquo;{lensId}&rdquo; is not a lens.
      </Card>
    );
  }
  return <LensView id={id} />;
}

function LensView({ id }: { id: number }) {
  const [nonce, setNonce] = React.useState(0);
  const rendered = useAsync(() => api.renderLens(id), [id, nonce]);

  const [request, setRequest] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [refusals, setRefusals] = React.useState<string[]>([]);
  const [changed, setChanged] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showHistory, setShowHistory] = React.useState(false);

  async function ask() {
    if (!request.trim() || busy) return;
    setBusy(true);
    setError(null);
    setRefusals([]);
    setChanged(null);
    try {
      const body = await api.askLens(id, request.trim());
      setRefusals(body.proposal.refusals);
      if (body.proposal.change_summary) {
        setChanged(body.proposal.change_summary);
        setRequest("");
        setNonce((n) => n + 1);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function restore(version: number) {
    setBusy(true);
    try {
      await api.restoreLens(id, version);
      setChanged(`Restored the definition from version ${version}.`);
      setNonce((n) => n + 1);
    } finally {
      setBusy(false);
    }
  }

  if (rendered.loading && !rendered.data) return <Skeleton className="h-96 w-full" />;
  if (rendered.error && !rendered.data) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {rendered.error}
      </Card>
    );
  }
  if (!rendered.data) return null;

  const { lens } = rendered.data;

  return (
    <div className="space-y-7">
      <BackLink href="/lenses" label="Lenses" />

      <Header lens={lens} rendered={rendered.data} />

      <LensBody rendered={rendered.data} lens={lens} />

      {changed && <p className="text-xs text-positive">{changed}</p>}
      {refusals.map((refusal) => (
        <p key={refusal} className="text-xs text-warning">
          {refusal}
        </p>
      ))}
      {error && <p className="text-xs text-negative">{error}</p>}

      <Card className="p-4">
        <label htmlFor="lens-ask" className="text-xs font-medium text-text-secondary">
          Change this lens
        </label>
        <div className="mt-1.5 flex flex-wrap gap-2">
          <input
            id="lens-ask"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void ask();
            }}
            placeholder="Add obligor concentration · remove the stress panel"
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <Button size="sm" onClick={ask} disabled={busy || !request.trim()}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
            Apply
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setShowHistory((h) => !h)}
          >
            <History aria-hidden />
            History
          </Button>
        </div>
      </Card>

      {showHistory && lens.revisions.length > 0 && (
        <Card className="divide-y divide-border">
          {lens.revisions.map((revision) => (
            <div
              key={revision.version}
              className="flex flex-wrap items-baseline gap-3 px-4 py-2.5"
            >
              <span className="w-16 shrink-0 text-xs tabular text-text-muted">
                v{revision.version}
              </span>
              <span className="min-w-0 flex-1 text-xs text-text-secondary">
                {revision.change_summary}
                {revision.request && (
                  <span className="block text-[11px] italic text-text-muted">
                    &ldquo;{revision.request}&rdquo;
                  </span>
                )}
              </span>
              <span className="shrink-0 text-[11px] text-text-muted">
                {revision.panel_count}{" "}
                {revision.panel_count === 1 ? "panel" : "panels"}
              </span>
              {revision.version !== lens.version && (
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={busy}
                  onClick={() => restore(revision.version)}
                >
                  <RotateCcw aria-hidden />
                  Put this back
                </Button>
              )}
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}

/**
 * The panels, grouped as the lens says to group them.
 *
 * A lens with no sections is one unbroken run, which is what every lens was
 * before metric tiles existed. A lens with sections reads as bands, because a
 * screen of eighteen equal tiles is a screen nobody reads top to bottom.
 *
 * Metric tiles sit three or four to a row; an analysis panel carries a whole
 * result table and takes the full width.
 */
function LensBody({
  rendered,
  lens,
}: {
  rendered: RenderedLens;
  lens: Lens;
}) {
  const from = fromLens(String(lens.id), lens.name);
  const sections =
    rendered.sections.length > 0
      ? rendered.sections
      : [
          {
            title: "",
            subtitle: "",
            panels: rendered.panels.map((_, index) => index),
          },
        ];

  return (
    <div className="space-y-8">
      {sections.map((section, index) => {
        const panels = section.panels
          .map((position) => rendered.panels[position])
          .filter(Boolean);
        if (panels.length === 0) return null;
        const tiles = panels.filter((panel) => panel.kind === "metric");
        const analyses = panels.filter((panel) => panel.kind !== "metric");
        return (
          <section key={`${section.title}-${index}`} className="space-y-3">
            {section.title && (
              <div>
                <h2 className="text-sm font-semibold tracking-tight text-text-primary">
                  {section.title}
                </h2>
                {section.subtitle && (
                  <p className="mt-0.5 max-w-3xl text-xs leading-relaxed text-text-muted">
                    {section.subtitle}
                  </p>
                )}
              </div>
            )}
            {tiles.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {tiles.map((panel, position) => (
                  <MetricTile
                    key={`${panel.metric_id}-${position}`}
                    panel={panel}
                  />
                ))}
              </div>
            )}
            {analyses.map((panel, position) => (
              <PanelView
                key={`${panel.analysis_id}-${position}`}
                panel={panel}
                from={from}
              />
            ))}
          </section>
        );
      })}

      {rendered.notes.length > 0 && <NotShownHere notes={rendered.notes} />}
    </div>
  );
}

/**
 * What this lens deliberately does not show, and why.
 *
 * A view that quietly omits the number somebody came for teaches them not to
 * trust it. One that names the metric, gives the reason and says what would be
 * needed does the opposite, and costs a paragraph.
 */
function NotShownHere({ notes }: { notes: RenderedLens["notes"] }) {
  return (
    <Card className="border-border/70 bg-surface-muted/40 p-4">
      <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
        Not on this lens
      </p>
      <ul className="mt-2 space-y-2.5">
        {notes.map((note) => (
          <li key={note.metric_id} className="text-xs leading-relaxed">
            <span className="font-medium text-text-secondary">{note.name}</span>
            <span className="text-text-muted"> — {note.because}</span>
            {note.needs.length > 0 && (
              <span className="mt-0.5 block text-[11px] text-text-muted">
                Would need: {note.needs.join("; ")}
              </span>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

function Header({ lens, rendered }: { lens: Lens; rendered: RenderedLens }) {
  return (
    <header>
      <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-text-muted">
        Lens
      </p>
      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
          {lens.name}
        </h1>
        <Badge variant="outline">version {lens.version}</Badge>
        <InfoPopover title="What you are looking at">
          <p>
            Every panel here was executed just now against the published data.
            Nothing is stored, so this lens cannot quietly go stale.
          </p>
          <p>
            Each panel carries its own Trace: a panel on a dashboard is exactly
            as much of a claim as an answer to a question.
          </p>
        </InfoPopover>
      </div>
      {lens.description && (
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          {lens.description}
        </p>
      )}
      <p className="mt-2 text-xs text-text-muted">
        {rendered.panels.length}{" "}
        {rendered.panels.length === 1 ? "panel" : "panels"}
        {rendered.period && <span> · {rendered.period}</span>}
        {rendered.note && (
          <span className={rendered.failed ? "text-negative" : "text-warning"}>
            {" "}
            · {rendered.note}
          </span>
        )}
      </p>
    </header>
  );
}

function PanelView({
  panel,
  from,
}: {
  panel: RenderedPanel;
  /** §5: Lens → Analysis → Trace → Back to Lens. */
  from: ReturnContext;
}) {
  if (panel.status !== "succeeded" || !panel.result) {
    return (
      <Card className="border-warning/30 p-4">
        <p className="flex items-start gap-2 text-sm text-warning">
          <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {panel.title || panel.analysis_id} could not be produced.
          {panel.error && (
            <span className="block text-xs text-text-muted">{panel.error}</span>
          )}
        </p>
      </Card>
    );
  }

  const run: AnalysisRunResponse = {
    analysis_id: panel.analysis_id,
    analysis_version: panel.analysis_version ?? "",
    certification: panel.certification ?? "draft",
    status: panel.status,
    params: panel.params,
    context: { period: null, filters: panel.filters },
    result: panel.result,
    duration_ms: panel.duration_ms ?? 0,
    error: null,
    trace: {
      nodes: [],
      edges: [],
      layers: [],
      stats: {
        node_count: 0,
        edge_count: 0,
        governed_nodes: 0,
        interpretive_nodes: 0,
      },
    },
    node_hashes: {},
    analysis_run_id: panel.analysis_run_id ?? null,
  };

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-border px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold tracking-tight text-text-primary">
              {panel.title || panel.analysis_id}
            </h2>
            <CertificationBadge certification={panel.certification ?? "draft"} />
          </div>
          {panel.note && (
            <p className="mt-0.5 max-w-2xl text-xs leading-relaxed text-text-muted">
              {panel.note}
            </p>
          )}
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <Button variant="ghost" size="sm" asChild>
            <Link href={linkBack(`/engine-builder/${panel.analysis_id}`, from)}>
              Method
            </Link>
          </Button>
          {/* §4: a lens panel showing a real run offers its results workbook. */}
          {panel.analysis_run_id ? (
            <DownloadResults
              runId={panel.analysis_run_id}
              variant="ghost"
              compact
            />
          ) : null}
          {panel.analysis_run_id ? (
            <Button variant="ghost" size="sm" asChild>
              <Link href={linkBack(`/trace/${panel.analysis_run_id}`, from)}>
                <GitBranch aria-hidden />
                Trace
              </Link>
            </Button>
          ) : (
            <Button variant="ghost" size="sm" disabled>
              <GitBranch aria-hidden />
              Trace
            </Button>
          )}
        </div>
      </div>
      <div className="px-5 py-4">
        <ResultView run={run} />
      </div>
    </Card>
  );
}
