"use client";

import * as React from "react";
import { Loader2, TriangleAlert } from "lucide-react";

import { Bars } from "@/components/metrics/chart-tile";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type ChartSeries,
  type ChartVocabulary,
  type LensPanel,
  type MetricHit,
  type RenderedLens,
} from "@/lib/api";

/**
 * Building a chart, and putting it on a lens.
 *
 * Six steps, in the order somebody actually thinks in: which number, broken
 * out by what, over which period, narrowed how, ordered how, drawn how. The
 * preview at the bottom is produced by the same route the lens tile uses, so
 * what is approved here is what the lens draws.
 *
 * Every picker is filled from the governed catalogue rather than from a list
 * in this file. That is not only a convenience: the chart types offered depend
 * on the dimension chosen, because whether a line means anything depends on
 * whether the axis has an order, and the refusals are shown rather than
 * hidden — a person who cannot see why "line" is missing will assume the
 * product is broken. The server checks all of it again on submission.
 */
export function ChartBuilder({
  lensId,
  rendered,
  onSaved,
  onCancel,
}: {
  lensId: number;
  rendered: RenderedLens;
  onSaved: () => void;
  onCancel: () => void;
}) {
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<MetricHit[]>([]);
  const [searching, setSearching] = React.useState(false);

  const [metricId, setMetricId] = React.useState("");
  const [options, setOptions] = React.useState<ChartVocabulary | null>(null);

  const [title, setTitle] = React.useState("");
  const [dimension, setDimension] = React.useState("");
  const [period, setPeriod] = React.useState("");
  const [filterField, setFilterField] = React.useState("");
  const [filterValue, setFilterValue] = React.useState("");
  const [aggregate, setAggregate] = React.useState("metric");
  const [sort, setSort] = React.useState("value");
  const [direction, setDirection] = React.useState("desc");
  const [limit, setLimit] = React.useState(10);
  const [compare, setCompare] = React.useState("");
  const [chartType, setChartType] = React.useState("");

  const [preview, setPreview] = React.useState<ChartSeries | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function search() {
    if (!query.trim()) return;
    setSearching(true);
    setError(null);
    try {
      const found = await api.searchMetrics(query.trim(), 12);
      setHits(found.results);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSearching(false);
    }
  }

  // Reloaded whenever the dimension changes, because that is what decides
  // which chart types are honest. A stale list here would offer a line
  // between products, which the server would then refuse — leaving the
  // person to guess why the button did nothing.
  React.useEffect(() => {
    if (!metricId) return;
    let live = true;
    api
      .chartOptions(metricId, dimension)
      .then((vocabulary) => {
        if (!live) return;
        setOptions(vocabulary);
        setChartType((current) =>
          vocabulary.chart_types.includes(current)
            ? current
            : (vocabulary.chart_types[0] ?? ""),
        );
      })
      .catch((e) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [metricId, dimension]);

  const chosen = options?.dimensions.find((d) => d.name === dimension) ?? null;

  function payload() {
    return {
      metric_id: metricId,
      dimension,
      period,
      filters:
        filterField && filterValue ? { [filterField]: filterValue } : {},
      aggregate,
      sort,
      direction,
      limit,
      compare,
    };
  }

  async function draw() {
    setBusy(true);
    setError(null);
    setPreview(null);
    try {
      setPreview(await api.drawChart(payload()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  /**
   * Add the chart to the lens.
   *
   * Through `setLensLayout` with the tiles that are already there plus this
   * one, so it goes through the same validation and writes the same kind of
   * revision as any other change. There is no route into a lens that skips it.
   */
  async function add() {
    setBusy(true);
    setError(null);
    try {
      const existing: LensPanel[] = rendered.panels.map((panel) => ({
        kind: panel.kind,
        analysis_id: panel.analysis_id,
        metric_id: panel.metric_id,
        title: panel.title,
        visual: panel.visual,
        params: panel.params,
        filters: panel.filters,
        period: panel.period,
        note: panel.note,
      }));
      const settings = payload();
      await api.setLensLayout(lensId, {
        tiles: [
          ...existing,
          {
            kind: "chart",
            analysis_id: "",
            metric_id: metricId,
            title,
            visual: chartType,
            params: {
              dimension,
              aggregate,
              sort,
              direction,
              limit,
              compare,
            },
            filters: settings.filters,
            period,
            note: "",
          },
        ],
        sections: rendered.sections ?? undefined,
        change_summary: `Added a chart of ${
          options?.metric.name ?? metricId
        } by ${chosen?.business_name ?? dimension}.`,
      });
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-5 p-5" data-testid="chart-builder">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-text-primary">
          Build a chart
        </h2>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-muted">
          A governed metric, broken out across one dimension. The bars are the
          metric&rsquo;s own formula computed for each group, so they reconcile
          with the figure on its tile.
        </p>
      </div>

      {/* 1 ---------------------------------------------------- the metric */}
      <Field step={1} label="Which number">
        <div className="flex gap-2">
          <input
            aria-label="Search the metric catalogue"
            className="w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
            placeholder="default rate, exposure, utilisation…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && search()}
          />
          <Button size="sm" variant="outline" onClick={search} disabled={searching}>
            {searching ? <Loader2 className="size-3.5 animate-spin" /> : "Search"}
          </Button>
        </div>
        {hits.length > 0 && (
          <ul className="mt-2 max-h-44 space-y-1 overflow-auto">
            {hits.map((hit) => (
              <li key={hit.metric_id}>
                <button
                  type="button"
                  onClick={() => {
                    setMetricId(hit.metric_id);
                    setDimension("");
                    setPreview(null);
                    setTitle("");
                  }}
                  className={`w-full rounded px-2 py-1.5 text-left text-xs ${
                    metricId === hit.metric_id
                      ? "bg-accent/10 text-text-primary"
                      : "hover:bg-surface-muted"
                  }`}
                >
                  <span className="font-medium">{hit.name}</span>
                  <span className="ml-2 text-text-muted">{hit.domain}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        {options && (
          <p className="mt-2 text-xs text-text-secondary">
            {options.metric.name}
            <span className="ml-2 text-text-muted">
              {options.metric.definition}
            </span>
          </p>
        )}
      </Field>

      {options && (
        <>
          {/* 2 --------------------------------------------- the dimension */}
          <Field step={2} label="Broken out by">
            {options.dimensions.length === 0 ? (
              <p className="text-xs text-text-muted">
                This metric&rsquo;s dataset has no dimension that can be shown
                on an axis.
              </p>
            ) : (
              <select
                aria-label="Dimension"
                className="w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                value={dimension}
                onChange={(e) => {
                  setDimension(e.target.value);
                  setPreview(null);
                }}
              >
                <option value="">Choose a dimension…</option>
                {options.dimensions.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.business_name}
                    {d.over_time ? " (over time)" : ""}
                  </option>
                ))}
              </select>
            )}
            {chosen?.definition && (
              <p className="mt-1 text-[11px] text-text-muted">
                {chosen.definition}
              </p>
            )}
          </Field>

          {/* 3 ------------------------------------------------ the period */}
          <Field step={3} label="Over which period">
            <select
              aria-label="Period"
              className="w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
              value={period}
              disabled={Boolean(chosen?.over_time)}
              onChange={(e) => {
                setPeriod(e.target.value);
                setPreview(null);
              }}
            >
              <option value="">The metric&rsquo;s own default period</option>
              {options.periods.map((p) => (
                <option key={p} value={p}>
                  {p}
                </option>
              ))}
            </select>
            {chosen?.over_time && (
              <p className="mt-1 text-[11px] text-text-muted">
                This chart&rsquo;s dimension IS the period, so it draws every
                period the dataset holds and a single period does not apply.
              </p>
            )}
          </Field>

          {/* 4 ----------------------------------------------- the filters */}
          <Field step={4} label="Narrowed to (optional)">
            <div className="flex gap-2">
              <select
                aria-label="Filter field"
                className="w-1/2 rounded border border-border bg-surface px-2 py-1.5 text-xs"
                value={filterField}
                onChange={(e) => {
                  setFilterField(e.target.value);
                  setFilterValue("");
                  setPreview(null);
                }}
              >
                <option value="">No filter</option>
                {options.dimensions.map((d) => (
                  <option key={d.name} value={d.name}>
                    {d.business_name}
                  </option>
                ))}
              </select>
              {(() => {
                const field = options.dimensions.find(
                  (d) => d.name === filterField,
                );
                const allowed = field?.allowed_values ?? [];
                if (allowed.length > 0) {
                  return (
                    <select
                      aria-label="Filter value"
                      className="w-1/2 rounded border border-border bg-surface px-2 py-1.5 text-xs"
                      value={filterValue}
                      onChange={(e) => {
                        setFilterValue(e.target.value);
                        setPreview(null);
                      }}
                    >
                      <option value="">Any value</option>
                      {allowed.map((value) => (
                        <option key={value} value={value}>
                          {value}
                        </option>
                      ))}
                    </select>
                  );
                }
                return (
                  <input
                    aria-label="Filter value"
                    className="w-1/2 rounded border border-border bg-surface px-2 py-1.5 text-xs"
                    placeholder="value"
                    disabled={!filterField}
                    value={filterValue}
                    onChange={(e) => {
                      setFilterValue(e.target.value);
                      setPreview(null);
                    }}
                  />
                );
              })()}
            </div>
          </Field>

          {/* 5 ---------------------------- aggregation, ordering, compare */}
          <Field step={5} label="Rolled up, ordered and compared">
            <div className="grid gap-2 sm:grid-cols-2">
              <label className="text-[11px] text-text-muted">
                Aggregation
                <select
                  aria-label="Aggregation"
                  className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                  value={aggregate}
                  onChange={(e) => {
                    setAggregate(e.target.value);
                    setPreview(null);
                  }}
                >
                  {options.aggregations
                    .filter((a) => a.available)
                    .map((a) => (
                      <option key={a.name} value={a.name}>
                        {a.label}
                      </option>
                    ))}
                </select>
              </label>
              <label className="text-[11px] text-text-muted">
                How many groups
                <input
                  aria-label="How many groups"
                  type="number"
                  min={1}
                  max={options.max_groups}
                  className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                  value={limit}
                  onChange={(e) => {
                    setLimit(Number(e.target.value) || 1);
                    setPreview(null);
                  }}
                />
              </label>
              <label className="text-[11px] text-text-muted">
                Sorted
                <select
                  aria-label="Sorted"
                  className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                  value={sort}
                  onChange={(e) => {
                    setSort(e.target.value);
                    setPreview(null);
                  }}
                >
                  {Object.entries(options.sorts).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-text-muted">
                Direction
                <select
                  aria-label="Direction"
                  className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                  value={direction}
                  onChange={(e) => {
                    setDirection(e.target.value);
                    setPreview(null);
                  }}
                >
                  {Object.entries(options.directions).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="text-[11px] text-text-muted sm:col-span-2">
                Compared with
                <select
                  aria-label="Compared with"
                  className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                  value={compare}
                  disabled={Boolean(chosen?.over_time)}
                  onChange={(e) => {
                    setCompare(e.target.value);
                    setPreview(null);
                  }}
                >
                  {Object.entries(options.comparisons).map(([value, label]) => (
                    <option key={value || "none"} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {options.aggregations
              .filter((a) => !a.available)
              .map((a) => (
                <p key={a.name} className="mt-1.5 text-[11px] text-text-muted">
                  <span className="font-medium">{a.label}</span> is not offered:{" "}
                  {a.unavailable_because}
                </p>
              ))}
          </Field>

          {/* 6 ------------------------------------ chart type, and title */}
          <Field step={6} label="Drawn as">
            {options.chart_types.length === 0 ? (
              <p className="text-xs text-text-muted">
                No chart type is honest for this combination. The reasons are
                below; choose another dimension.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {options.chart_types.map((type) => (
                  <button
                    key={type}
                    type="button"
                    aria-pressed={chartType === type}
                    onClick={() => {
                      setChartType(type);
                      setPreview(null);
                    }}
                    className={`rounded border px-2.5 py-1 text-xs capitalize ${
                      chartType === type
                        ? "border-accent bg-accent/10 text-text-primary"
                        : "border-border text-text-secondary hover:bg-surface-muted"
                    }`}
                  >
                    {type}
                  </button>
                ))}
              </div>
            )}
            {options.chart_types_refused.length > 0 && (
              <ul
                className="mt-2 space-y-1"
                data-testid="chart-types-refused"
              >
                {options.chart_types_refused.map((refused) => (
                  <li
                    key={refused.name}
                    className="text-[11px] leading-relaxed text-text-muted"
                  >
                    <span className="font-medium capitalize">
                      {refused.name}
                    </span>{" "}
                    is not offered: {refused.because}
                  </li>
                ))}
              </ul>
            )}
            <label className="mt-3 block text-[11px] text-text-muted">
              Title
              <input
                aria-label="Title"
                className="mt-1 w-full rounded border border-border bg-surface px-2 py-1.5 text-xs"
                placeholder={
                  chosen
                    ? `${options.metric.name} by ${chosen.business_name}`
                    : "Leave empty for the default"
                }
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </label>
          </Field>
        </>
      )}

      {error && (
        <p className="flex items-start gap-1.5 text-xs text-negative">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          <span>{error}</span>
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-border/60 pt-4">
        <Button
          size="sm"
          variant="outline"
          onClick={draw}
          disabled={busy || !metricId || !dimension || !chartType}
        >
          {busy ? <Loader2 className="size-3.5 animate-spin" /> : "Preview"}
        </Button>
        <Button
          size="sm"
          onClick={add}
          disabled={busy || !preview || !chartType}
        >
          Add to this lens
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        {!preview && metricId && dimension && (
          <span className="text-[11px] text-text-muted">
            Preview it before adding: a chart nobody has looked at is a chart
            nobody has checked.
          </span>
        )}
      </div>

      {preview && (
        <Card className="p-4" data-testid="chart-preview">
          <div className="flex items-start justify-between gap-2">
            <div>
              <p className="text-xs font-medium text-text-secondary">
                {title || `${preview.series_label} by ${preview.dimension_label}`}
              </p>
              <p className="mt-0.5 text-[10px] text-text-muted">
                {preview.period}
                {preview.comparison ? ` vs ${preview.comparison.period}` : ""}
                {" · "}
                {preview.points.length} of {preview.groups_found} groups
              </p>
            </div>
            <Badge variant="outline" className="capitalize">
              {chartType}
            </Badge>
          </div>
          {preview.unavailable ? (
            <p className="mt-3 text-xs text-text-muted">{preview.unavailable}</p>
          ) : (
            <Bars
              points={preview.points}
              comparison={preview.comparison}
              unit={preview.unit}
              decimals={preview.decimals}
            />
          )}
          {preview.notes.length > 0 && (
            <ul className="mt-3 space-y-1 border-t border-border/60 pt-2">
              {preview.notes.map((note) => (
                <li key={note} className="text-[10px] text-text-muted">
                  {note}
                </li>
              ))}
            </ul>
          )}
          <details className="mt-3">
            <summary className="cursor-pointer text-[10px] text-text-muted">
              The query that produced these numbers · run {preview.run_id}
            </summary>
            <pre className="mt-1.5 max-h-56 overflow-auto rounded bg-surface-muted p-2 font-mono text-[10px] leading-relaxed text-text-secondary">
              {preview.sql}
            </pre>
          </details>
        </Card>
      )}
    </Card>
  );
}

function Field({
  step,
  label,
  children,
}: {
  step: number;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <p className="mb-1.5 text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
        {step}. {label}
      </p>
      {children}
    </section>
  );
}
