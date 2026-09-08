"use client";

import Link from "next/link";
import * as React from "react";
import {
  ChartColumn,
  GitBranch,
  History,
  LayoutGrid,
  Loader2,
  Pencil,
  RotateCcw,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { ResultView } from "@/components/analytics/result-view";
import { ChartTile } from "@/components/metrics/chart-tile";
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
import { ChartBuilder } from "@/components/lenses/chart-builder";
import {
  EditableCard,
  LensEditBar,
  describeChange,
  saveLayout,
} from "@/components/lenses/edit-mode";
import { LayoutEditor } from "@/components/lenses/layout-editor";
import {
  LensChangesPanel,
  MetricHistoryPanel,
} from "@/components/lenses/lens-changes";
import { LensInterpretationPanel } from "@/components/lenses/lens-interpretation";
import { LensScopeBar } from "@/components/lenses/lens-scope";
import { FormulaBuilder } from "@/components/lenses/formula-builder";
import { MetricBuilder } from "@/components/lenses/metric-builder";
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
  // Null means "whatever the lens opens on" — its declared period, or each
  // metric's own latest. A period is only in the URL of the request once
  // somebody has picked one, so the lens's own default is not silently
  // replaced by whatever was showing when the page first loaded.
  const [period, setPeriod] = React.useState<string | null>(null);
  // `keepPrevious`: a lens re-renders underneath the person using it — a
  // period change, or a metric added from inside edit mode — and blanking the
  // body for that moment unmounts whatever they were in the middle of along
  // with it. The metric builder was losing its locked step to a reload it had
  // itself asked for. The previous render is still true until the new one
  // arrives, so it stays up until then.
  const rendered = useAsync(
    () => api.renderLens(id, period ?? undefined),
    [id, nonce, period],
    { keepPrevious: true },
  );
  const view = rendered.data;

  const [request, setRequest] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [refusals, setRefusals] = React.useState<string[]>([]);
  const [changed, setChanged] = React.useState<string | null>(null);
  const [error, setError] = React.useState<string | null>(null);
  const [showHistory, setShowHistory] = React.useState(false);
  // §32. Which tile's two histories are open, if any. One at a time: a page
  // with every tile's history expanded is a page nobody reads.
  const [historyFor, setHistoryFor] = React.useState<string | null>(null);
  const [arranging, setArranging] = React.useState(false);
  const [charting, setCharting] = React.useState(false);

  // §12–§17. Edit mode is a state of the lens page rather than a different
  // screen, because what somebody is arranging is the cards with their real
  // numbers on them — a list of titles reordered well often looks wrong as
  // tiles.
  const [editing, setEditing] = React.useState(false);
  const [order, setOrder] = React.useState<RenderedPanel[] | null>(null);
  const [dragging, setDragging] = React.useState<number | null>(null);
  const [addingMetric, setAddingMetric] = React.useState(false);
  const [saving, setSaving] = React.useState(false);

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

  if (rendered.loading && !view) return <Skeleton className="h-96 w-full" />;
  if (rendered.error && !view) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {rendered.error}
      </Card>
    );
  }
  if (!view) return null;

  const { lens } = view;
  const cards = order ?? view.panels;

  function startEditing() {
    setOrder(view ? [...view.panels] : []);
    setEditing(true);
    setArranging(false);
    setCharting(false);
    setChanged(null);
  }

  function stopEditing() {
    setEditing(false);
    setOrder(null);
    setAddingMetric(false);
    setDragging(null);
  }

  function move(from: number, to: number) {
    setOrder((current) => {
      const list = [...(current ?? view?.panels ?? [])];
      if (from === to || from < 0 || to < 0 || from >= list.length) return list;
      const [moved] = list.splice(from, 1);
      list.splice(to, 0, moved);
      return list;
    });
  }

  async function commit() {
    if (!order || !view) return;
    setSaving(true);
    setError(null);
    try {
      await saveLayout(id, order, describeChange(view, order));
      stopEditing();
      setChanged("Saved the arrangement as a version of its own.");
      setNonce((n) => n + 1);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  /**
   * §16 and §17. Adding a metric from an existing lens uses the same builder
   * the creation flow uses — the same library, the same definition editor, the
   * same real-data preview, the same lock — and coming back leaves the lens in
   * edit mode, because somebody who was arranging it was still arranging it.
   */
  async function attach(metricId: string) {
    if (!view) return;
    setSaving(true);
    setError(null);
    try {
      const next = [
        ...(order ?? view.panels),
        {
          kind: "metric",
          metric_id: metricId,
          analysis_id: "",
          title: "",
          visual: "kpi",
          params: {},
          filters: {},
          period: "",
          note: "",
          status: "succeeded",
          error: null,
          result: null,
        } as unknown as RenderedPanel,
      ];
      await saveLayout(id, next, `Added ${metricId} from the lens.`);
      setChanged(`Added ${metricId}.`);
      setNonce((n) => n + 1);
      // Stay in edit mode, and re-seed the order from the reload below.
      setOrder(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-7">
      <BackLink href="/lenses" label="Lenses" />

      <Header
        lens={lens}
        rendered={view}
        editing={editing}
        onEdit={startEditing}
      />

      <LensScopeBar
        lensId={id}
        scope={view.scope}
        showing={view.period}
        onPeriod={(chosen) => {
          setChanged(null);
          setPeriod(chosen);
        }}
        onSaved={() => {
          setChanged("Saved what this lens is for.");
          setPeriod(null);
          setNonce((n) => n + 1);
        }}
      />

      {rendered.loading && (
        <p className="flex items-center gap-1.5 text-xs text-text-muted">
          <Loader2 className="size-3 animate-spin" aria-hidden />
          Recalculating every panel for this period.
        </p>
      )}

      <LensEditBar
        editing={editing}
        dirty={
          !!order &&
          JSON.stringify(order.map((p) => p.metric_id || p.analysis_id)) !==
            JSON.stringify(
              view.panels.map((p) => p.metric_id || p.analysis_id),
            )
        }
        busy={saving}
        onSave={commit}
        onCancel={stopEditing}
        onAddMetric={() => setAddingMetric(true)}
      />

      {editing && addingMetric && (
        <FormulaBuilder
          period={view.period ?? ""}
          lensId={id}
          onLocked={(made) => void attach(made.metric_id)}
          onCancel={() => setAddingMetric(false)}
        />
      )}

      {editing && addingMetric && (
        <MetricBuilder
          lensName={lens.name}
          domain={view.scope.domains[0] ?? ""}
          portfolio={view.scope.portfolio}
          chosen={cards.map((p) => p.metric_id).filter(Boolean)}
          onLocked={(made) => void attach(made.metric_id)}
          onDone={() => setAddingMetric(false)}
        />
      )}

      {editing && !addingMetric ? (
        <EditBoard
          panels={cards}
          dragging={dragging}
          onDragStart={setDragging}
          onDropOn={(position) => {
            if (dragging !== null) move(dragging, position);
            setDragging(null);
          }}
          onRemove={(position) =>
            setOrder((current) =>
              (current ?? cards).filter((_, i) => i !== position),
            )
          }
          onMove={(position, step) => move(position, position + step)}
        />
      ) : arranging ? (
        <LayoutEditor
          lensId={id}
          rendered={view}
          onSaved={() => {
            setArranging(false);
            setChanged("Saved the new arrangement as a version of its own.");
            setNonce((n) => n + 1);
          }}
          onCancel={() => setArranging(false)}
        />
      ) : charting ? (
        <ChartBuilder
          lensId={id}
          rendered={view}
          onSaved={() => {
            setCharting(false);
            setChanged("Added the chart as a version of its own.");
            setNonce((n) => n + 1);
          }}
          onCancel={() => setCharting(false)}
        />
      ) : addingMetric ? null : (
        <>
          {/* §31. What CHANGED goes above what the Lens SHOWS, because a
              reader arriving at a dashboard they saw last quarter is asking
              the first question and the tiles answer the second. */}
          <LensChangesPanel
            lensId={id}
            period={view.period}
            version={lens.version}
            onRefreshed={() => setNonce((n) => n + 1)}
          />
          <LensInterpretationPanel
            lensId={id}
            period={view.period}
            version={lens.version}
          />
          <LensBody
            rendered={view}
            lens={lens}
            lensId={id}
            showHistoryFor={historyFor}
            onShowHistory={setHistoryFor}
          />
        </>
      )}

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
            placeholder="Add obligor concentration · exposure by region · remove the stress panel"
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <Button size="sm" onClick={ask} disabled={busy || !request.trim()}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Sparkles aria-hidden />}
            Apply
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setCharting(false);
              setArranging((a) => !a);
            }}
          >
            <LayoutGrid aria-hidden />
            {arranging ? "Stop arranging" : "Arrange"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setArranging(false);
              setCharting((c) => !c);
            }}
          >
            <ChartColumn aria-hidden />
            {charting ? "Stop building" : "Build a chart"}
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
  lensId,
  showHistoryFor,
  onShowHistory,
}: {
  rendered: RenderedLens;
  lens: Lens;
  lensId: number;
  showHistoryFor: string | null;
  onShowHistory: (metricId: string | null) => void;
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
        const charts = panels.filter((panel) => panel.kind === "chart");
        const analyses = panels.filter(
          (panel) => panel.kind !== "metric" && panel.kind !== "chart",
        );
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
                  <div
                    key={`${panel.metric_id}-${position}`}
                    className="space-y-1"
                  >
                    <MetricTile panel={panel} />
                    {panel.metric_id && (
                      <>
                        {/* §32. A tile's own two histories, on the tile,
                            because "has this been moving?" is asked while
                            looking at the figure rather than on another
                            screen. */}
                        <button
                          type="button"
                          className="text-[10px] text-text-muted hover:text-text-secondary"
                          data-testid={`show-history-${panel.metric_id}`}
                          onClick={() =>
                            onShowHistory(
                              showHistoryFor === panel.metric_id
                                ? null
                                : panel.metric_id,
                            )
                          }
                        >
                          {showHistoryFor === panel.metric_id
                            ? "Hide history"
                            : "History"}
                        </button>
                        {showHistoryFor === panel.metric_id && (
                          <Card className="p-3">
                            <MetricHistoryPanel
                              lensId={lensId}
                              metricId={panel.metric_id}
                              metricName={
                                panel.title || panel.metric?.name || ""
                              }
                            />
                          </Card>
                        )}
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
            {charts.length > 0 && (
              <div className="grid gap-3 sm:grid-cols-2">
                {charts.map((panel, position) => (
                  <ChartTile
                    key={`chart-${panel.metric_id}-${position}`}
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
 * The lens as an editable board.
 *
 * The real cards, wiggling, each with a handle and a remove control. One flat
 * grid rather than the lens's bands: a reorder that crosses a band boundary
 * has no correct band to land in, and pretending otherwise would put a tile
 * somewhere nobody chose. The bands come back when the lens is next changed
 * conversationally, which is where band membership is actually decided.
 */
function EditBoard({
  panels,
  dragging,
  onDragStart,
  onDropOn,
  onRemove,
  onMove,
}: {
  panels: RenderedPanel[];
  dragging: number | null;
  onDragStart: (index: number) => void;
  onDropOn: (index: number) => void;
  onRemove: (index: number) => void;
  onMove: (index: number, step: -1 | 1) => void;
}) {
  if (panels.length === 0) {
    return (
      <Card className="border-warning/40 p-4 text-xs text-warning">
        Every card has been removed. A lens needs at least one, so this will not
        save until you add something back.
      </Card>
    );
  }
  return (
    <div className="lens-board grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
         data-testid="edit-board">
      {panels.map((panel, index) => (
        <EditableCard
          key={`${panel.kind}-${panel.metric_id}-${panel.analysis_id}-${index}`}
          panel={panel}
          index={index}
          dragging={dragging === index}
          onDragStart={() => onDragStart(index)}
          onDragOver={(event) => event.preventDefault()}
          onDrop={() => onDropOn(index)}
          onRemove={() => onRemove(index)}
          onMove={(step) => onMove(index, step)}
          first={index === 0}
          last={index === panels.length - 1}
        >
          {panel.kind === "chart" ? (
            <ChartTile panel={panel} />
          ) : panel.kind === "metric" ? (
            <MetricTile panel={panel} />
          ) : (
            <Card className="p-4">
              <p className="text-xs font-medium text-text-secondary">
                {panel.title || panel.analysis_id}
              </p>
              <p className="mt-1 text-[11px] text-text-muted">Analysis panel</p>
            </Card>
          )}
        </EditableCard>
      ))}
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

function Header({
  lens,
  rendered,
  editing,
  onEdit,
}: {
  lens: Lens;
  rendered: RenderedLens;
  editing: boolean;
  onEdit: () => void;
}) {
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
        {/*
          §12. The pencil, next to the name, because "change this thing" is
          about the thing and the name is what identifies it. Hidden while
          editing rather than toggling: the edit bar below owns leaving the
          mode, and two controls for one state is how somebody ends up unable
          to tell which one they are in.
        */}
        {!editing && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onEdit}
            aria-label={`Edit ${lens.name}`}
            data-testid="edit-lens"
          >
            <Pencil aria-hidden />
            Edit
          </Button>
        )}
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
