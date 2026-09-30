"use client";

/**
 * The portfolio explorer: Plotly views of the latest-period book that share
 * ONE filter state with the grid beneath them. Click a bar to filter (click
 * again to clear); box/lasso-select several bars to filter to them; the grid,
 * the selection and every other chart follow. Aggregates come from the server
 * (`/grid/group`) -- the portfolio is never shipped to the browser.
 */

import * as React from "react";
import { Loader2 } from "lucide-react";

import { ChartCard } from "@/components/viz/chart-card";
import { heatmap, reconcile, stageSankey, type Cell } from "@/lib/viz/advanced";
import { categoryBars, stageMix } from "@/lib/viz/figures";
import { gridGroup, gridGroup2 } from "@/lib/workspace/guided";
import type { DomainId, Filter } from "@/lib/workspace/objects";
import { EXPLORER_DIMENSIONS, EXPLORER_MATRICES, cellFilter, selectedValues, setFilterValues, toggleFilterValue } from "@/lib/workspace/whatif";

type Group = { value: string | number | null; n: number; ead_sar_mn: number; ecl_sar_mn: number };

export function PortfolioExplorer({
  domain,
  filters,
  onFilters,
  context,
}: {
  domain: DomainId;
  filters: Filter[];
  onFilters: (next: Filter[]) => void;
  context: { releaseId: string; fingerprint: string; period: string };
}) {
  const dims = EXPLORER_DIMENSIONS[domain];
  const [dimension, setDimension] = React.useState(dims[0].key);
  const [measure, setMeasure] = React.useState<"ead_sar_mn" | "ecl_sar_mn">("ecl_sar_mn");
  const dim = dims.some((d) => d.key === dimension) ? dimension : dims[0].key;
  // The dimension chart ignores its OWN filter so every category stays
  // visible and toggleable; the selected ones are highlighted instead.
  const others = React.useMemo(() => filters.filter((f) => f.column !== dim), [filters, dim]);
  const key = JSON.stringify({ domain, dim, others, filters });
  const [loaded, setLoaded] = React.useState<{ key: string; groups: Group[]; stages: Group[]; error: string }>({
    key: "",
    groups: [],
    stages: [],
    error: "",
  });

  React.useEffect(() => {
    let live = true;
    Promise.all([gridGroup(domain, dim, others), gridGroup(domain, "stage", filters)])
      .then(([g, s]) => live && setLoaded({ key, groups: g.groups, stages: s.groups, error: "" }))
      .catch((e: unknown) => live && setLoaded({ key, groups: [], stages: [], error: e instanceof Error ? e.message : String(e) }));
    return () => {
      live = false;
    };
  }, [domain, dim, others, filters, key]);

  const ready = loaded.key === key;
  const selected = selectedValues(filters, dim);
  const groups = [...loaded.groups].sort((a, b) => (b[measure] ?? 0) - (a[measure] ?? 0));
  const bars = categoryBars(groups, measure, { dimension: dims.find((d) => d.key === dim)?.label ?? dim, selected });
  const stageFig = stageMix(loaded.stages.map((s) => ({ stage: Number(s.value), n: s.n, ead: s.ead_sar_mn ?? 0, ecl: s.ecl_sar_mn ?? 0 })));
  const label = dims.find((d) => d.key === dim)?.label ?? dim;

  return (
    <section className="space-y-2" data-testid="whatif-explorer" data-dimension={dim}>
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <h2 className="font-semibold">Portfolio explorer</h2>
        <select value={dim} onChange={(e) => setDimension(e.target.value)} className="rounded border border-border bg-surface px-2 py-1 text-xs" data-testid="whatif-explorer-dimension" aria-label="Break down by">
          {dims.map((d) => (
            <option key={d.key} value={d.key}>
              By {d.label.toLowerCase()}
            </option>
          ))}
        </select>
        <select value={measure} onChange={(e) => setMeasure(e.target.value as typeof measure)} className="rounded border border-border bg-surface px-2 py-1 text-xs" aria-label="Measure">
          <option value="ecl_sar_mn">Booked ECL</option>
          <option value="ead_sar_mn">EAD</option>
        </select>
        <span className="text-xs text-text-muted">Click a bar to filter; drag a box or lasso to select several. The grid follows.</span>
        {!ready && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
      </div>
      {loaded.error && loaded.key === key && <p className="text-xs text-negative">{loaded.error}</p>}
      <div className="grid gap-3 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ChartCard
            title={`${measure === "ecl_sar_mn" ? "Booked ECL" : "EAD"} by ${label.toLowerCase()}`}
            subtitle={`${context.period} · ${selected.length ? `${selected.length} selected` : "all categories"}`}
            data={bars.data}
            layout={{ ...bars.layout, dragmode: "select", clickmode: "event+select", margin: { l: 60, r: 10, t: 10, b: 90 } }}
            height={300}
            selectable
            testId="whatif-chart-dimension"
            context={{ releaseId: context.releaseId, fingerprint: context.fingerprint, period: context.period, filters: { applied: others } }}
            onPointClick={(p) => {
              const value = Array.isArray(p.customdata) ? String(p.customdata[0]) : String(p.x ?? "");
              onFilters(toggleFilterValue(filters, dim, dim === "stage" ? Number(value) : value));
            }}
            onSelected={(points) => {
              const values = points.map((p) => (Array.isArray(p.customdata) ? String(p.customdata[0]) : String(p.x ?? "")));
              onFilters(setFilterValues(filters, dim, Array.from(new Set(values))));
            }}
            table={{
              columns: [
                { key: "value", label: label },
                { key: "n", label: "Exposures", align: "right" },
                { key: "ead_sar_mn", label: "EAD (SAR m, raw)", align: "right" },
                { key: "ecl_sar_mn", label: "Booked ECL (SAR m, raw)", align: "right" },
              ],
              rows: groups as unknown as Record<string, unknown>[],
            }}
          />
        </div>
        <ChartCard
          title="Filtered population by stage"
          subtitle="EAD; click a stage to filter"
          data={stageFig.data}
          layout={{ ...stageFig.layout, height: 210, margin: { l: 40, r: 10, t: 6, b: 90 }, legend: { orientation: "h", y: -0.7 } }}
          height={210}
          testId="whatif-chart-stage"
          context={{ releaseId: context.releaseId, fingerprint: context.fingerprint, period: context.period, filters: { applied: filters } }}
          onPointClick={(p) => {
            const name = String(p.data?.name ?? "");
            const stage = Number(name.replace(/\D/g, ""));
            if (stage) onFilters(toggleFilterValue(filters, "stage", stage));
          }}
          table={{
            columns: [
              { key: "value", label: "Stage" },
              { key: "n", label: "Exposures", align: "right" },
              { key: "ead_sar_mn", label: "EAD (SAR m, raw)", align: "right" },
              { key: "ecl_sar_mn", label: "Booked ECL (SAR m, raw)", align: "right" },
            ],
            rows: loaded.stages as unknown as Record<string, unknown>[],
          }}
        />
      </div>
      <ExplorerMatrices domain={domain} filters={filters} onFilters={onFilters} context={context} />
    </section>
  );
}

type Matrix = { cells: Cell[]; total: { n: number; ead_sar_mn: number | null }; truncated: boolean };

/**
 * The two-dimension views: a heatmap (sector × rating / product × score band)
 * and the prior → current stage flow. Each ignores its OWN columns' filters
 * so the whole matrix stays visible; a cell or link click narrows the shared
 * filter state to it, and the keyboard does the same from the data table.
 */
function ExplorerMatrices({
  domain,
  filters,
  onFilters,
  context,
}: {
  domain: DomainId;
  filters: Filter[];
  onFilters: (next: Filter[]) => void;
  context: { releaseId: string; fingerprint: string; period: string };
}) {
  const m = EXPLORER_MATRICES[domain];
  const [measure, setMeasure] = React.useState<"ead_sar_mn" | "ecl_sar_mn">("ead_sar_mn");
  const heatOthers = React.useMemo(() => filters.filter((f) => f.column !== m.x && f.column !== m.y), [filters, m.x, m.y]);
  const flowOthers = React.useMemo(() => filters.filter((f) => f.column !== "prior_stage" && f.column !== "stage"), [filters]);
  const key = JSON.stringify({ domain, heatOthers, flowOthers });
  const [loaded, setLoaded] = React.useState<{ key: string; heat: Matrix | null; flow: Matrix | null; error: string }>({
    key: "",
    heat: null,
    flow: null,
    error: "",
  });

  React.useEffect(() => {
    let live = true;
    Promise.all([gridGroup2(domain, m.x, m.y, heatOthers), gridGroup2(domain, "prior_stage", "stage", flowOthers)])
      .then(([heat, flow]) => live && setLoaded({ key, heat, flow, error: "" }))
      .catch((e: unknown) => live && setLoaded({ key, heat: null, flow: null, error: e instanceof Error ? e.message : String(e) }));
    return () => {
      live = false;
    };
  }, [domain, m.x, m.y, heatOthers, flowOthers, key]);

  const { heat, flow } = loaded;
  const heatFig = React.useMemo(() => heatmap(heat?.cells ?? [], measure, { x: m.xLabel, y: m.yLabel }), [heat, measure, m.xLabel, m.yLabel]);
  const flowFig = React.useMemo(() => stageSankey(flow?.cells ?? [], "ead_sar_mn"), [flow]);
  const flowCheck = flow ? reconcile(flow.cells, flow.total) : null;
  const heatCheck = heat ? reconcile(heat.cells, heat.total) : null;
  const pickHeat = (x: unknown, y: unknown) =>
    onFilters(cellFilter(filters, [
      { column: m.x, value: x as string },
      { column: m.y, value: y as string },
    ]));
  const pickFlow = (prior: unknown, current: unknown) =>
    onFilters(cellFilter(filters, [
      { column: "prior_stage", value: prior as string },
      { column: "stage", value: current as string },
    ]));
  const cellColumns = (xLabel: string, yLabel: string) => [
    { key: "x", label: xLabel },
    { key: "y", label: yLabel },
    { key: "n", label: "Exposures", align: "right" as const },
    { key: "ead_sar_mn", label: "EAD (SAR m, raw)", align: "right" as const },
    { key: "ecl_sar_mn", label: "Booked ECL (SAR m, raw)", align: "right" as const },
  ];

  return (
    <div className="grid gap-3 lg:grid-cols-2" data-testid="whatif-matrices">
      {loaded.error && <p className="text-xs text-negative lg:col-span-2">{loaded.error}</p>}
      <ChartCard
        title={`${measure === "ecl_sar_mn" ? "Booked ECL" : "EAD"} by ${m.xLabel.toLowerCase()} × ${m.yLabel.toLowerCase()}`}
        subtitle={`${context.period} · click a cell (or press Enter on a row of its data) to filter to it; again to clear`}
        data={heatFig.data}
        layout={heatFig.layout}
        height={340}
        testId="whatif-chart-heatmap"
        actions={
          <select value={measure} onChange={(e) => setMeasure(e.target.value as typeof measure)} className="rounded border border-border bg-surface px-2 py-1 text-xs" aria-label="Heatmap measure">
            <option value="ead_sar_mn">EAD</option>
            <option value="ecl_sar_mn">Booked ECL</option>
          </select>
        }
        context={{ releaseId: context.releaseId, fingerprint: context.fingerprint, period: context.period, filters: { applied: heatOthers } }}
        onPointClick={(p) => pickHeat(p.x, p.y)}
        table={{
          columns: cellColumns(m.xLabel, m.yLabel),
          rows: (heat?.cells ?? []) as unknown as Record<string, unknown>[],
          onRowActivate: (row) => pickHeat(row.x ?? "(none)", row.y ?? "(none)"),
          activateLabel: `Filter to ${m.xLabel.toLowerCase()} and ${m.yLabel.toLowerCase()}`,
        }}
        footer={
          heatCheck && (
            <p className="mt-1 text-[11px] text-text-muted" data-testid="whatif-heatmap-reconcile" data-ok={String(heatCheck.ok)}>
              {heat?.cells.length} cells · {heatCheck.n.toLocaleString()} exposures {heatCheck.ok ? "reconcile to" : "DO NOT reconcile to"} the filtered book
              {heat?.truncated ? " (truncated: narrow the filter)" : ""}.
            </p>
          )
        }
      />
      <ChartCard
        title="Stage migration, prior → current quarter"
        subtitle="EAD; click a flow (or press Enter on a row of its data) to filter to it"
        data={flowFig.data}
        layout={flowFig.layout}
        height={340}
        testId="whatif-chart-sankey"
        context={{ releaseId: context.releaseId, fingerprint: context.fingerprint, period: context.period, filters: { applied: flowOthers } }}
        onPointClick={(p) => {
          const c = p.customdata;
          if (Array.isArray(c) && c.length >= 2) pickFlow(c[0], c[1]);
        }}
        table={{
          columns: cellColumns("Prior stage", "Current stage"),
          rows: (flow?.cells ?? []) as unknown as Record<string, unknown>[],
          onRowActivate: (row) => pickFlow(row.x ?? "(none)", row.y),
          activateLabel: "Filter to the migration",
        }}
        footer={
          flowCheck && (
            <p className="mt-1 text-[11px] text-text-muted" data-testid="whatif-sankey-reconcile" data-ok={String(flowCheck.ok)}>
              Flows sum to {flowCheck.n.toLocaleString()} exposures, EAD {flowCheck.ead.toFixed(1)} SAR m:{" "}
              {flowCheck.ok ? "reconciles to" : "DOES NOT reconcile to"} the filtered book.
            </p>
          )
        }
      />
    </div>
  );
}
