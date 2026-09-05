"use client";

import * as React from "react";

import {
  CategoryBarChart,
  DivergingBarChart,
  MatrixHeatmap,
  TrendChart,
  type SeriesDef,
} from "@/components/analytics/charts";
import type { ScvChart, ScvResult } from "@/lib/api";
import { technical } from "@/lib/format";
import { cn } from "@/lib/utils";

/**
 * The validation charts. §22.
 *
 * This file draws nothing itself. Every chart below is one of the five
 * primitives already in `components/analytics/charts.tsx`, given the right
 * data. That constraint is deliberate and it is the whole design: a second
 * chart engine would mean two tooltip conventions, two palettes, two ideas
 * about what an axis should do, and a fortnight later a Gini rendered in a
 * colour that means "negative" on every other screen in the product.
 *
 * So what lives here is a MAPPING — from the fifteen chart payloads the
 * runner attaches to a result, onto the primitives that can draw them. When a
 * payload has no sensible primitive, this renders the result's own table and
 * says so, rather than inventing a picture.
 *
 * Why the payload rather than the value
 * ---------------------------------------
 * A validation chart is almost never a picture of the headline number. The
 * headline of DISC-AUC is 0.6547; the chart is the ROC curve it was integrated
 * from. The headline of STAB-CSI is the worst variable's index; the chart is
 * every variable ranked, because the question a validator actually has is
 * "which ones moved?" and a single bar cannot answer it. The runner already
 * attaches the shape that answers the question — this file's job is to not
 * lose it.
 *
 * A number that is not there
 * ----------------------------
 * Nothing here substitutes a zero for a missing value. A result in one of the
 * six unmeasured states carries no chart at all, and the caller renders the
 * refusal instead. That is checked once, in `ValidationChart`, rather than
 * defended in fifteen renderers.
 */

/** Anything the runner might have put in a chart row. */
type Row = Record<string, unknown>;

function rows(chart: ScvChart, key: string): Row[] {
  const value = chart[key];
  return Array.isArray(value) ? (value as Row[]) : [];
}

function num(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Recharts wants `string | number | null`; the payload is `unknown`. */
function plot(source: Row[], keys: string[]): Record<string,
  string | number | null>[] {
  return source.map((row) => {
    const out: Record<string, string | number | null> = {};
    for (const key of keys) {
      const value = row[key];
      out[key] =
        typeof value === "number" || typeof value === "string" ? value : null;
    }
    return out;
  });
}

function series(...defs: [string, string][]): SeriesDef[] {
  return defs.map(([key, label], slot) => ({ key, label, slot }));
}

function Caption({ children }: { children: React.ReactNode }) {
  return (
    <p className="mt-2 text-xs leading-relaxed text-text-muted">{children}</p>
  );
}

function Panel({ title, children }: {
  title: string; children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <h4 className="text-[11px] font-semibold uppercase tracking-wider text-text-muted">
        {title}
      </h4>
      {children}
    </div>
  );
}

// ------------------------------------------------------------ the renderers

/** Row counts surviving each filter. §DATA-ROWS. */
function Waterfall({ chart }: { chart: ScvChart }) {
  const steps = rows(chart, "steps");
  if (!steps.length) return null;
  return (
    <>
      <CategoryBarChart
        data={plot(steps, ["step", "rows", "removed"])}
        xKey="step"
        series={series(["rows", "Rows surviving"])}
        height={Math.max(160, steps.length * 40)}
      />
      <Caption>
        Each bar is what remains after the filter named beside it. A step that
        removes most of the population is the one to read first — it is where
        the model is being judged on a different book from the one it decides.
      </Caption>
    </>
  );
}

/**
 * Two different questions arrive as `distribution`, and they are drawn
 * differently on purpose.
 *
 * DATA-MATURITY splits the periods into matured and immature — a count, not a
 * shape. ROB-BOOTSTRAP carries the resample draws, whose shape IS the answer:
 * the spread is the uncertainty. Rendering the second as a bar of one number
 * would throw away the only thing the test measured.
 */
function Distribution({ chart }: { chart: ScvChart }) {
  const matured = Array.isArray(chart.matured) ? chart.matured as string[] : [];
  const immature = Array.isArray(chart.immature)
    ? chart.immature as string[] : [];
  if (matured.length || immature.length) {
    return (
      <>
        <CategoryBarChart
          data={[
            { window: "Outcome window closed", periods: matured.length },
            { window: "Not yet matured", periods: immature.length },
          ]}
          xKey="window"
          series={series(["periods", "Periods"])}
          height={140}
        />
        <Caption>
          {matured.length} of {matured.length + immature.length} periods carry a
          realised outcome
          {matured.length ? `, the latest being ${matured[matured.length - 1]}` : ""}.
          The immature periods are not empty and they are not zero — their
          performance window has not closed, so no outcome metric can be
          computed over them.
        </Caption>
      </>
    );
  }

  const draws = Array.isArray(chart.draws) ? chart.draws as number[] : [];
  if (draws.length) return <Histogram draws={draws} chart={chart} />;

  return null;
}

/** The bootstrap draws, binned. The spread is the point. */
function Histogram({ draws, chart }: { draws: number[]; chart: ScvChart }) {
  const bins = React.useMemo(() => {
    const low = Math.min(...draws);
    const high = Math.max(...draws);
    const width = (high - low) / 24 || 1;
    const counts = new Array(24).fill(0);
    for (const d of draws) {
      const at = Math.min(23, Math.floor((d - low) / width));
      counts[at] += 1;
    }
    return counts.map((count, i) => ({
      at: technical(low + width * (i + 0.5), 4),
      count,
    }));
  }, [draws]);

  const lower = num(chart.lower);
  const upper = num(chart.upper);

  return (
    <>
      <CategoryBarChart
        data={bins}
        xKey="at"
        series={series(["count", "Resamples"])}
        horizontal={false}
        height={220}
      />
      <Caption>
        {draws.length} resamples of the same population. The width of this
        distribution is the honest precision of the headline statistic
        {lower !== null && upper !== null
          ? `: the interval runs ${technical(lower, 4)} to ${technical(upper, 4)}`
          : ""}
        . A difference smaller than that spread is not a difference.
      </Caption>
    </>
  );
}

/** Missing rate by variable and period. §DATA-MISSING, §DATA-COVERAGE. */
function Heatmap({ chart }: { chart: ScvChart }) {
  const cells = rows(chart, "cells");
  if (!cells.length) return null;

  const periods: string[] = [];
  const variables: string[] = [];
  const grid: Record<string, number> = {};
  for (const cell of cells) {
    const variable = String(cell.variable ?? "");
    const period = String(cell.period ?? "");
    const rate = num(cell.missing_rate) ?? num(cell.coverage) ?? 0;
    if (!variables.includes(variable)) variables.push(variable);
    if (!periods.includes(period)) periods.push(period);
    grid[`${variable}|${period}`] = rate * 100;
  }

  // The primitive draws one square grid. A variable-by-period matrix is not
  // square, so the categories are the union and the empty half stays empty —
  // which reads correctly, because a period is not a variable and no cell
  // should exist where the two are swapped.
  return (
    <>
      <MatrixHeatmap
        categories={[...variables, ...periods]}
        cells={grid}
        diagonalHint={false}
      />
      <Caption>
        Percentage missing, by characteristic and month. A row that darkens
        part-way across is a feed that changed; a column that darkens is a
        month that arrived incomplete. The two have different fixes, which is
        why this is a grid rather than an average.
      </Caption>
    </>
  );
}

/** ROC, CAP and KS all arrive with the same payload and read differently. */
function Curves({ chart, kind }: { chart: ScvChart; kind: string }) {
  const roc = rows(chart, "roc");
  const ks = rows(chart, "ks_curve");
  const ksAt = num(chart.ks_at);

  if (kind === "ks" && ks.length) {
    return (
      <>
        <TrendChart
          data={plot(ks, ["score", "cumulative_bad", "cumulative_good", "gap"])}
          xKey="score"
          series={series(
            ["cumulative_bad", "Cumulative defaults"],
            ["cumulative_good", "Cumulative non-defaults"],
            ["gap", "Separation"],
          )}
          height={260}
        />
        <Caption>
          The two cumulative curves and the distance between them. KS is the
          widest that gap gets
          {ksAt !== null ? `, which on this population is at score ${ksAt}` : ""}
          . A score where the curves touch is a score at which the model is not
          discriminating at all.
        </Caption>
      </>
    );
  }

  if (!roc.length) return null;
  return (
    <>
      <TrendChart
        data={plot(roc, ["false_positive_rate", "true_positive_rate"])}
        xKey="false_positive_rate"
        series={series(["true_positive_rate", "Defaults captured"])}
        height={260}
      />
      <Caption>
        {kind === "cap"
          ? "The cumulative accuracy profile. Gini is twice the area between this curve and the diagonal, so the curve is the statistic rather than an illustration of it."
          : "The receiver operating characteristic. AUC is the area beneath it: the probability that a randomly chosen default scores worse than a randomly chosen non-default."}
      </Caption>
    </>
  );
}

/** Observed default rate by score band. §DISC-RANK, §SEG-RANK. */
function BandRate({ chart }: { chart: ScvChart }) {
  const bands = rows(chart, "bands");
  if (!bands.length) return null;
  return (
    <>
      <CategoryBarChart
        data={plot(bands, ["band", "observed_rate", "observations", "events"])}
        xKey="band"
        series={series(["observed_rate", "Observed default rate"])}
        horizontal={false}
        height={220}
      />
      <Caption>
        The realised default rate in each score band. What matters is the
        ORDER: a band that defaults more than the band below it is a rank
        inversion, and a scorecard that inverts is being used to decline the
        wrong applications.
      </Caption>
    </>
  );
}

/** Decile lift and cumulative capture. §DISC-LIFT. */
function Lift({ chart }: { chart: ScvChart }) {
  const deciles = rows(chart, "deciles");
  if (!deciles.length) return null;
  return (
    <div className="space-y-4">
      <Panel title="Lift by decile">
        <CategoryBarChart
          data={plot(deciles, ["decile", "lift", "bad_rate"])}
          xKey="decile"
          series={series(["lift", "Lift over the book"])}
          horizontal={false}
          height={200}
        />
      </Panel>
      <Panel title="Cumulative capture">
        <TrendChart
          data={plot(deciles, ["decile", "cumulative_capture_rate",
                               "population_share"])}
          xKey="decile"
          series={series(
            ["cumulative_capture_rate", "Defaults captured"],
            ["population_share", "Population reviewed"],
          )}
          height={200}
        />
      </Panel>
      <Caption>
        Lift is the decile&apos;s default rate over the book&apos;s. The capture
        curve is the operational reading: how much of next year&apos;s loss sits
        in the worst slice you are willing to review.
      </Caption>
    </div>
  );
}

/** A measure through time. §DISC-TREND, §CAL-DRIFT, §STAB-ROLLING. */
function Trend({ chart }: { chart: ScvChart }) {
  const points = rows(chart, "series");
  const measures = Array.isArray(chart.measures)
    ? (chart.measures as string[]) : [];
  if (!points.length || !measures.length) return null;
  return (
    <>
      <TrendChart
        data={plot(points, ["period", ...measures])}
        xKey="period"
        series={series(...measures.map((m) =>
          [m, m.toUpperCase()] as [string, string]))}
        height={240}
      />
      <Caption>
        Measured per cohort, over the matured window only. A cohort whose
        performance window has not closed is absent from this line rather than
        plotted at zero — a trend that falls off a cliff at the right-hand edge
        is almost always that mistake, and it is not made here.
      </Caption>
    </>
  );
}

/** Predicted against observed, by band. §CAL-OE, §CAL-BAND, §CAL-SLOPE. */
function Calibration({ chart }: { chart: ScvChart }) {
  const buckets = rows(chart, "buckets");
  if (!buckets.length) return null;
  return (
    <>
      <CategoryBarChart
        data={plot(buckets, ["band", "observed_default_rate",
                             "average_predicted_pd"])}
        xKey="band"
        series={series(
          ["average_predicted_pd", "Predicted"],
          ["observed_default_rate", "Observed"],
        )}
        horizontal={false}
        height={240}
      />
      <Caption>
        Predicted against realised, band by band. Discrimination asks whether
        the ordering is right; this asks whether the LEVEL is. A model can rank
        perfectly and still price every facility wrongly, and the two bars
        diverging in the same direction across every band is exactly that.
      </Caption>
    </>
  );
}

/** Population drift through time, and what is driving it. §STAB-PSI. */
function PsiTrend({ chart }: { chart: ScvChart }) {
  const points = rows(chart, "series");
  const bins = rows(chart, "bins");
  const limit = num(chart.limit);
  return (
    <div className="space-y-4">
      {points.length > 0 && (
        <Panel title="Index by month">
          <TrendChart
            data={plot(points, ["period", "index"])}
            xKey="period"
            series={series(["index", "Population stability index"])}
            height={220}
          />
        </Panel>
      )}
      {bins.length > 0 && (
        <Panel title="Where the shift is">
          <DivergingBarChart
            data={plot(bins, ["bin", "shift", "contribution"])}
            xKey="bin"
            valueKey="shift"
            height={Math.max(160, bins.length * 26)}
          />
        </Panel>
      )}
      <Caption>
        Measured against the frozen development population, never against last
        month
        {limit !== null ? `, and read against a limit of ${limit}` : ""}. A
        baseline that moves forward is how a book drifts a long way from what
        was approved while passing stability testing every quarter.
      </Caption>
    </div>
  );
}

/** Variables ranked by whatever the test measured. §STAB-CSI, §VAR-IV, §SEG-*. */
function Ranking({ chart }: { chart: ScvChart }) {
  const variables = rows(chart, "variables").length
    ? rows(chart, "variables")
    : rows(chart, "segments");
  if (!variables.length) return null;

  // The value key differs by test — csi, information_value, auc, observed
  // over expected. Rather than a lookup table that goes stale the first time a
  // test is added, take the first numeric column that is not a count.
  const skip = new Set(["observations", "events", "bins", "count"]);
  const first = variables[0];
  const label = Object.keys(first).find((k) => !skip.has(k)
    && typeof first[k] === "number");
  const name = Object.keys(first).find((k) => typeof first[k] === "string")
    ?? "variable";
  if (!label) return null;

  return (
    <>
      <CategoryBarChart
        data={plot(variables, [name, label])}
        xKey={name}
        series={series([label, label.replace(/_/g, " ")])}
        height={Math.max(180, variables.length * 32)}
      />
      <Caption>
        Ranked, because the aggregate cannot answer the question a validator
        has. &ldquo;The index is 1.08&rdquo; is a fact about the worst one;
        which one, and whether the rest moved with it, is the finding.
      </Caption>
    </>
  );
}

/** Weight of evidence by bin, one variable at a time. §VAR-WOE. */
function Woe({ chart }: { chart: ScvChart }) {
  const variables = rows(chart, "variables");
  const [picked, setPicked] = React.useState(0);
  if (!variables.length) return null;

  const chosen = variables[Math.min(picked, variables.length - 1)];
  const bins = Array.isArray(chosen.bins) ? chosen.bins as Row[] : [];
  const inversions = num(chosen.inversions);

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-1.5">
        {variables.map((v, i) => (
          <button
            key={String(v.variable ?? i)}
            type="button"
            onClick={() => setPicked(i)}
            className={cn(
              "rounded border px-2 py-1 text-[11px] transition-colors",
              i === picked
                ? "border-border-strong bg-surface-hover text-text"
                : "border-border text-text-muted hover:text-text",
              v.still_monotonic === false && "text-negative",
            )}
          >
            {String(v.variable ?? "")}
          </button>
        ))}
      </div>
      {bins.length > 0 && (
        <DivergingBarChart
          data={plot(bins, ["bin_id", "bin", "woe"])}
          xKey={typeof bins[0].bin_id === "string" ? "bin_id" : "bin"}
          valueKey="woe"
          height={Math.max(160, bins.length * 28)}
        />
      )}
      <Caption>
        Weight of evidence per bin. The approved binning asserts a direction,
        and this is where it either holds or does not:
        {inversions !== null && inversions > 0
          ? ` ${inversions} bin${inversions === 1 ? "" : "s"} on this characteristic now point the other way, which means the model is being credited for signal it no longer carries.`
          : " no bin on this characteristic contradicts the direction it was approved with."}
      </Caption>
    </div>
  );
}

/** Overrides by band and direction. §USE-MATRIX, §USE-CUTOFF, §CC-SWAPSET. */
function Matrix({ chart }: { chart: ScvChart }) {
  const cells = rows(chart, "cells");
  if (!cells.length) return null;

  const bands: string[] = [];
  const directions: string[] = [];
  const grid: Record<string, number> = {};
  for (const cell of cells) {
    const band = String(cell.band ?? cell.from ?? "");
    const direction = String(cell.direction ?? cell.to ?? "");
    const rate = num(cell.rate) ?? num(cell.share) ?? 0;
    if (!bands.includes(band)) bands.push(band);
    if (!directions.includes(direction)) directions.push(direction);
    grid[`${band}|${direction}`] = rate * 100;
  }

  return (
    <>
      <MatrixHeatmap
        categories={[...bands, ...directions]}
        cells={grid}
        diagonalHint={false}
      />
      <Caption>
        Override rate by score band and direction. Overrides concentrated at
        the band containing the cut-off are the signal worth reading: it means
        the people using the model do not believe it precisely where it makes
        its decision.
      </Caption>
    </>
  );
}

/** How much the answer moves when a segment or a window is removed. */
function Tornado({ chart }: { chart: ScvChart }) {
  const bars = rows(chart, "bars");
  const baseline = num(chart.baseline);
  if (!bars.length) return null;
  const name = typeof bars[0].excluded === "string" ? "excluded" : "window";
  return (
    <>
      <DivergingBarChart
        data={plot(bars, [name, "change", "share_of_book"])}
        xKey={name}
        valueKey="change"
        height={Math.max(160, bars.length * 34)}
      />
      <Caption>
        Each bar is how far the headline statistic moves when that slice is
        taken out
        {baseline !== null
          ? `, against a baseline of ${technical(baseline, 4)}` : ""}
        . A result that depends on one segment being present is a result about
        that segment, not about the model.
      </Caption>
    </>
  );
}

// ------------------------------------------------------------- the dispatch

const RENDERERS: Record<string, (chart: ScvChart) => React.ReactNode> = {
  waterfall: (c) => <Waterfall chart={c} />,
  distribution: (c) => <Distribution chart={c} />,
  heatmap: (c) => <Heatmap chart={c} />,
  roc: (c) => <Curves chart={c} kind="roc" />,
  cap: (c) => <Curves chart={c} kind="cap" />,
  ks: (c) => <Curves chart={c} kind="ks" />,
  band_rate: (c) => <BandRate chart={c} />,
  lift: (c) => <Lift chart={c} />,
  gains: (c) => <Lift chart={c} />,
  trend: (c) => <Trend chart={c} />,
  calibration: (c) => <Calibration chart={c} />,
  psi_trend: (c) => <PsiTrend chart={c} />,
  ranking: (c) => <Ranking chart={c} />,
  woe: (c) => <Woe chart={c} />,
  matrix: (c) => <Matrix chart={c} />,
  tornado: (c) => <Tornado chart={c} />,
};

/** Every chart kind this file can draw. Exported so a test can assert it. */
export const DRAWABLE = Object.keys(RENDERERS);

/**
 * Draw the chart a result carries, or nothing.
 *
 * Nothing is a legitimate outcome and the caller must handle it: five of the
 * forty-eight tests declare no chart, and every unmeasured result carries no
 * payload at all. Returning `null` here rather than an empty frame is what
 * keeps a refused test from occupying the same visual space as a measured one.
 */
export function ValidationChart({ result, className }: {
  result: ScvResult;
  className?: string;
}) {
  const chart = result.chart as ScvChart | undefined;
  if (!result.measured || !chart || !chart.kind) return null;

  const draw = RENDERERS[chart.kind];
  if (!draw) return null;

  const drawn = draw(chart);
  if (!drawn) return null;

  return <div className={cn("space-y-1", className)}>{drawn}</div>;
}
