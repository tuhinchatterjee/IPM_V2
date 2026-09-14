"use client";

/**
 * One model version, in full: what it is, how it was built, and how it did.
 *
 * The performance blocks are cut by the state a facility was in when it was
 * scored, because a model measured on facilities that were already ninety
 * days down is measuring its own inputs. The hard-trigger cohort therefore
 * reports operational capture and says, in the same box, why no rank
 * statistic is shown for it.
 */

import Link from "next/link";
import * as React from "react";
import { ArrowLeft, Download, GitCompare } from "lucide-react";
import { useParams } from "next/navigation";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api, type EwsModelComparison, type EwsModelVersion,
  type EwsPerformanceCohort, type EwsPerformanceCut,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";

import { Spark } from "../../spark";

function show(value: unknown, places = 4): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(places) : String(value);
}

function pct(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%` : String(value);
}

export default function EwsModelVersionPage() {
  const params = useParams<{ version: string }>();
  const version = String(params?.version ?? "");
  const load = React.useCallback(
    () => api.ewsModelVersion(version), [version]);
  const { data, loading, error } = useAsync<EwsModelVersion>(load, [load]);
  const compareLoad = React.useCallback(
    () => api.ewsModelCompare(version), [version]);
  const { data: comparison, error: compareError } =
    useAsync<EwsModelComparison>(compareLoad, [compareLoad]);

  if (loading && !data) return <Skeleton className="h-96 w-full" />;
  if (error) {
    return <EmptyState title="This version could not be read"
                       description={String(error)} />;
  }
  if (!data?.available) {
    return <EmptyState title="No such model version" description={version} />;
  }

  const performance = data.performance;
  return (
    <div className="space-y-6" data-testid="ews-model-version-page">
      <PageHeader
        eyebrow="Govern"
        title={`Early Warning Score — model version ${data.model_version}`}
        description={data.change_summary}
        status="live"
        phase="Governed model on synthetic demonstration data"
        actions={
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" asChild>
              <a href={api.ewsModelReportUrl(data.model_version)}
                 data-testid="ews-version-report">
                <Download aria-hidden /> Development report (.docx)
              </a>
            </Button>
            <Button variant="outline" size="sm" asChild>
              <Link href="/early-warning/model-log"
                    data-testid="ews-version-back">
                <ArrowLeft aria-hidden /> Model log
              </Link>
            </Button>
          </div>
        }
      />

      <Card className="p-4" data-testid="ews-version-identity">
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant={data.status === "active" ? "default" : "outline"}>
            {data.status}
          </Badge>
          <span className="font-mono text-xs text-text-muted">
            {data.version_id}
          </span>
          <span className="text-[11px] text-text-muted">
            config {data.config_hash} · data {data.data_manifest_hash}
          </span>
        </div>
        <dl className="mt-3 grid gap-3 text-[12px] sm:grid-cols-2 lg:grid-cols-4">
          {[
            ["Effective", `${data.effective_from} → ${data.effective_to || "current"}`],
            ["Development sample", data.development_sample],
            ["Validation sample", data.validation_sample],
            ["Rulebook", data.rulebook_version],
            ["Taxonomy", data.taxonomy_version],
            ["Score scale", data.score_scale],
            ["Warning cutoff", String(data.warning_threshold)],
            ["Owner", data.created_by],
          ].map(([label, value]) => (
            <div key={label}>
              <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                {label}
              </dt>
              <dd className="text-text-primary">{value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-3 text-[12px] leading-relaxed text-text-secondary">
          <span className="font-medium text-text-primary">Why this version: </span>
          {data.change_rationale}
        </p>
        <p className="mt-1.5 text-[12px] leading-relaxed text-text-secondary">
          <span className="font-medium text-text-primary">Bureau treatment: </span>
          {data.bureau_treatment}
        </p>
        {data.notes?.map((note) => (
          <p key={note} className="mt-1.5 text-[11px] italic text-text-muted">
            {note}
          </p>
        ))}
      </Card>

      {performance?.available ? (
        <>
          <Card className="p-4" data-testid="ews-version-target">
            <p className="text-sm font-semibold text-text-primary">
              Measured against
            </p>
            <p className="mt-1 text-[12px] text-text-secondary">
              {performance.target_definition}
            </p>
            <p className="mt-1 text-[11px] text-text-muted">
              {performance.observations.toLocaleString()} scored
              facility-months over {performance.scored_months.length} months,{" "}
              {performance.events.toLocaleString()} outcomes.
            </p>
            <p className="mt-1.5 text-[12px] text-text-secondary"
               data-testid="ews-version-calibration">
              {performance.calibration}
            </p>
          </Card>

          {performance.cohorts.map((cohort) => (
            <CohortBlock key={cohort.key} cohort={cohort} />
          ))}

          <div className="grid gap-3 lg:grid-cols-2">
            <CutTable title="By product" rows={performance.by_product}
                      testId="ews-version-by-product" />
            <CutTable title="By classification"
                      rows={performance.by_classification}
                      testId="ews-version-by-classification" />
          </div>
          <CutTable title="By sub-product" rows={performance.by_sub_product}
                    testId="ews-version-by-sub-product" />

          <StabilityBlock stability={performance.stability} />
          <LeadTimeBlock lead={performance.lead_time} />

          <Card className="p-4" data-testid="ews-version-severity-rates">
            <p className="text-sm font-semibold text-text-primary">
              Outcome rate by severity band
            </p>
            <table className="mt-2 w-full text-[12px]">
              <thead>
                <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  <th className="px-2 py-1 text-left">Band</th>
                  <th className="px-2 py-1 text-right">Observations</th>
                  <th className="px-2 py-1 text-right">Outcomes</th>
                  <th className="px-2 py-1 text-right">Rate</th>
                </tr>
              </thead>
              <tbody>
                {performance.severity_event_rates.map((row) => (
                  <tr key={row.band} className="border-t border-border/60">
                    <td className="px-2 py-1 text-text-primary">{row.band}</td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {row.observations.toLocaleString()}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {row.events.toLocaleString()}
                    </td>
                    <td className="px-2 py-1 text-right tabular-nums">
                      {pct(row.event_rate)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      ) : (
        <Card className="p-4 text-sm text-text-secondary">
          Performance was not measured: {performance?.because ?? "no panel"}.
        </Card>
      )}

      {!comparison?.available && compareError ? (
        <Card className="p-4 text-[12px] text-text-secondary"
              data-testid="ews-version-no-comparison">
          {/* The first version in the registry has nothing before it. Said in
              a sentence, rather than leaving the reader to wonder whether the
              comparison failed to load. */}
          No comparison: {String(compareError).replace(/^Error:\s*/, "")}
        </Card>
      ) : null}

      {comparison?.available ? (
        <Card className="p-4" data-testid="ews-version-comparison">
          <div className="flex flex-wrap items-center gap-2">
            <GitCompare className="size-4 text-accent" aria-hidden />
            <p className="text-sm font-semibold text-text-primary">
              {comparison.left} compared with {comparison.right}
            </p>
          </div>
          <table className="mt-2 w-full text-[12px]">
            <thead>
              <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                <th className="px-2 py-1 text-left">What</th>
                <th className="px-2 py-1 text-left">{comparison.left}</th>
                <th className="px-2 py-1 text-left">{comparison.right}</th>
              </tr>
            </thead>
            <tbody>
              {comparison.configuration.map((row) => (
                <tr key={row.what} className="border-t border-border/60">
                  <td className="px-2 py-1 font-medium text-text-primary">
                    {row.what}
                  </td>
                  <td className="px-2 py-1 text-text-secondary">{row.left}</td>
                  <td className="px-2 py-1 text-text-secondary">{row.right}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="mt-3 text-[12px] text-text-secondary">
            At {String(comparison.population_impact.month)}
            {comparison.population_impact.month_is
              ? ` — ${String(comparison.population_impact.month_is)}` : ""},{" "}
            {Number(comparison.population_impact.severity_changed).toLocaleString()}{" "}
            of{" "}
            {Number(comparison.population_impact.observations).toLocaleString()}{" "}
            scored facilities
            ({String(comparison.population_impact.severity_changed_pct)}%) change
            severity band between the versions, covering{" "}
            {String(comparison.population_impact.exposure_severity_changed_pct)}%
            of exposure.{" "}
            {Number(comparison.population_impact.score_moved_up).toLocaleString()}{" "}
            scores rise and{" "}
            {Number(comparison.population_impact.score_moved_down).toLocaleString()}{" "}
            fall.
          </p>
        </Card>
      ) : null}
    </div>
  );
}

function CohortBlock({ cohort }: { cohort: EwsPerformanceCohort }) {
  const threshold = cohort.threshold ?? {};
  return (
    <Card className="p-4" data-testid={`ews-cohort-${cohort.key}`}>
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold text-text-primary">
          {cohort.name}
        </p>
        <span className="text-[11px] text-text-muted">
          {cohort.observations.toLocaleString()} observations ·{" "}
          {cohort.events.toLocaleString()} outcomes
        </span>
      </div>
      <p className="mt-1 text-[12px] text-text-secondary">{cohort.meaning}</p>
      {cohort.caveat ? (
        <p className="mt-1 text-[11px] italic text-text-muted"
           data-testid={`ews-cohort-caveat-${cohort.key}`}>
          {cohort.caveat}
        </p>
      ) : null}

      {!cohort.available ? (
        <p className="mt-2 text-[12px] text-text-muted">
          Not measured: {cohort.because}
        </p>
      ) : cohort.discrimination_reported === false ? (
        <div className="mt-2" data-testid={`ews-cohort-capture-${cohort.key}`}>
          <p className="text-[12px] text-text-secondary">
            {cohort.why_no_discrimination}
          </p>
          <dl className="mt-2 grid gap-3 text-[12px] sm:grid-cols-4">
            {[
              ["Flagged", Number(cohort.capture?.flagged ?? 0).toLocaleString()],
              ["Capture rate", pct(cohort.capture?.capture_rate)],
              ["Scored CRITICAL",
               Number(cohort.capture?.at_critical ?? 0).toLocaleString()],
              ["CRITICAL share", pct(cohort.capture?.at_critical_rate)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  {label}
                </dt>
                <dd className="tabular-nums text-text-primary">{value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : (
        <>
          <dl className="mt-3 grid gap-3 text-[12px] sm:grid-cols-3 lg:grid-cols-6">
            {[
              ["Outcome rate", pct(cohort.event_rate)],
              ["AUC", show(cohort.auc)],
              ["Gini", show(cohort.gini)],
              ["KS", show(cohort.ks)],
              ["PR-AUC", show(cohort.pr_auc)],
              ["Alert rate", pct(threshold.alert_rate)],
              ["Precision", pct(threshold.precision)],
              ["Recall", pct(threshold.recall)],
              ["F1", show(threshold.f1)],
              ["Balanced accuracy", show(threshold.balanced_accuracy)],
              ["False positive rate", pct(threshold.false_positive_rate)],
              ["False negative rate", pct(threshold.false_negative_rate)],
            ].map(([label, value]) => (
              <div key={label}>
                <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  {label}
                </dt>
                <dd className="tabular-nums text-text-primary">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-3 grid gap-4 lg:grid-cols-3">
            {cohort.roc?.length ? (
              <Curve label="ROC" diagonal
                     xLabel="False positive rate"
                     yLabel="True positive rate"
                     summary={cohort.auc === null || cohort.auc === undefined
                       ? undefined : `AUC ${show(cohort.auc)}`}
                     x={cohort.roc.map((p) => p.fpr)}
                     y={cohort.roc.map((p) => p.tpr)}
                     testId={`ews-roc-${cohort.key}`} />
            ) : null}
            {cohort.gains?.length ? (
              <Curve label="Gains" diagonal
                     xLabel="Share of the book, worst first"
                     yLabel="Share of outcomes caught"
                     x={cohort.gains.map((p) => p.share)}
                     y={cohort.gains.map((p) => p.captured)}
                     testId={`ews-gains-${cohort.key}`} />
            ) : null}
            {cohort.pr?.length ? (
              <Curve label="Precision-recall"
                     xLabel="Recall" yLabel="Precision"
                     baseline={cohort.base_rate}
                     baselineLabel={cohort.base_rate === null
                                    || cohort.base_rate === undefined
                       ? undefined
                       : `dashed line is the base rate, `
                         + `${pct(cohort.base_rate)}: a curve sitting on it `
                         + `is no better than picking at random`}
                     summary={cohort.pr_auc === null
                              || cohort.pr_auc === undefined
                       ? undefined : `PR-AUC ${show(cohort.pr_auc)}`}
                     x={cohort.pr.map((p) => p.recall)}
                     y={cohort.pr.map((p) => p.precision)}
                     testId={`ews-pr-${cohort.key}`} />
            ) : null}
          </div>

          {cohort.lift?.length ? (
            <table className="mt-3 w-full text-[11px]"
                   data-testid={`ews-lift-${cohort.key}`}>
              <thead>
                <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
                  <th className="px-1 py-1 text-left">Decile</th>
                  {cohort.lift.map((row) => (
                    <th key={row.decile} className="px-1 py-1 text-right">
                      {row.decile}
                      {row.within_one_score ? (
                        <span className="ml-0.5 font-normal normal-case
                                         text-text-muted"
                              title="This decile sits inside a single score, so it is a slice of a tie rather than a rank.">
                          tied
                        </span>
                      ) : null}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-border/60">
                  <td className="px-1 py-1 text-text-secondary">Outcome rate</td>
                  {cohort.lift.map((row) => (
                    <td key={row.decile}
                        className="px-1 py-1 text-right tabular-nums">
                      {pct(row.event_rate)}
                    </td>
                  ))}
                </tr>
                <tr className="border-t border-border/60">
                  <td className="px-1 py-1 text-text-secondary">Lift</td>
                  {cohort.lift.map((row) => (
                    <td key={row.decile}
                        className="px-1 py-1 text-right tabular-nums">
                      {show(row.lift, 2)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          ) : null}
          {cohort.lift_note ? (
            <p className="mt-1.5 text-[10px] italic leading-relaxed text-text-muted"
               data-testid={`ews-lift-note-${cohort.key}`}>
              {cohort.lift_note}
            </p>
          ) : null}
        </>
      )}
    </Card>
  );
}

/** A curve, drawn against both of its axes.
 *
 * These are not time series and must not be drawn as one. An ROC curve read
 * off equally-spaced points is a different curve from the one that was
 * measured: the whole content of ROC is how fast the true positive rate rises
 * against the false positive rate, and spacing the x axis evenly throws that
 * away. A sparkline also reports a latest value and a movement, which a curve
 * does not have — "ROC 100 +100" is the true positive rate reaching one at
 * the end of the sweep, which is true of every ROC curve ever drawn and tells
 * a reader nothing.
 *
 * So: both axes to scale, zero to one on each, the no-skill diagonal where it
 * means something, and the number that summarises the curve named underneath
 * rather than invented from the last point.
 */
function Curve({ label, x, y, testId, summary, diagonal = false,
                 baseline, baselineLabel, xLabel, yLabel }: {
  label: string; x: number[]; y: number[]; testId: string;
  summary?: string; diagonal?: boolean;
  /** A horizontal no-skill reference, in the y axis' own units. */
  baseline?: number | null; baselineLabel?: string;
  xLabel: string; yLabel: string;
}) {
  const W = 150, H = 92, PAD = 5;
  const points = y
    .map((value, index) => ({ x: x[index] ?? 0, y: value }))
    .filter((p) => Number.isFinite(p.x) && Number.isFinite(p.y));
  if (points.length < 2) return null;

  // Both axes run the full zero to one, so two cohorts' curves can be laid
  // beside each other and compared by eye.
  const px = (v: number) => PAD + Math.min(Math.max(v, 0), 1) * (W - PAD * 2);
  const py = (v: number) => H - PAD - Math.min(Math.max(v, 0), 1) * (H - PAD * 2);
  const path = points
    .map((p, i) => `${i ? "L" : "M"}${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`)
    .join(" ");

  return (
    <div data-testid={testId}>
      <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
        {label}
      </p>
      <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`}
           className="mt-1 w-full max-w-[190px]" role="img"
           aria-label={`${label}: ${yLabel} against ${xLabel}`
                       + (summary ? `, ${summary}` : "")}>
        <rect x={PAD} y={PAD} width={W - PAD * 2} height={H - PAD * 2}
              fill="none" stroke="var(--ipm-border)" strokeWidth={0.75} />
        {diagonal ? (
          <line x1={px(0)} y1={py(0)} x2={px(1)} y2={py(1)}
                stroke="var(--ipm-border-strong)" strokeWidth={0.75}
                strokeDasharray="2 2" />
        ) : null}
        {typeof baseline === "number" && Number.isFinite(baseline) ? (
          <line x1={px(0)} y1={py(baseline)} x2={px(1)} y2={py(baseline)}
                stroke="var(--ipm-border-strong)" strokeWidth={0.75}
                strokeDasharray="2 2" />
        ) : null}
        <path d={path} fill="none" stroke="var(--ipm-accent)"
              strokeWidth={1.5} strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <div className="flex justify-between text-[9px] text-text-muted">
        <span>{xLabel} 0</span>
        <span>1</span>
      </div>
      <p className="text-[9px] text-text-muted">
        {yLabel} on the vertical{summary ? ` · ${summary}` : ""}
        {baselineLabel ? ` · ${baselineLabel}` : ""}
      </p>
    </div>
  );
}

function CutTable({ title, rows, testId }: {
  title: string; rows: EwsPerformanceCut[]; testId: string;
}) {
  return (
    <Card className="p-4" data-testid={testId}>
      <p className="text-sm font-semibold text-text-primary">{title}</p>
      <table className="mt-2 w-full text-[12px]">
        <thead>
          <tr className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
            <th className="px-2 py-1 text-left">Cut</th>
            <th className="px-2 py-1 text-right">Observations</th>
            <th className="px-2 py-1 text-right">Rate</th>
            <th className="px-2 py-1 text-right">Gini</th>
            <th className="px-2 py-1 text-right">KS</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-t border-border/60">
              <td className="px-2 py-1 text-text-primary">{row.label}</td>
              <td className="px-2 py-1 text-right tabular-nums">
                {row.observations.toLocaleString()}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {pct(row.event_rate)}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {row.available ? show(row.gini) : "—"}
              </td>
              <td className="px-2 py-1 text-right tabular-nums">
                {row.available ? show(row.ks) : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </Card>
  );
}

function StabilityBlock({ stability }: { stability: Record<string, unknown> }) {
  if (!stability?.available) return null;
  const series = (stability.series ?? []) as {
    month: string; psi_vs_first: number | null; alert_rate: number;
    mean_score: number }[];
  return (
    <Card className="p-4" data-testid="ews-version-stability">
      <p className="text-sm font-semibold text-text-primary">Stability</p>
      <p className="mt-1 text-[12px] text-text-secondary">
        PSI against {String(stability.baseline_month)}:{" "}
        <span className="tabular-nums">{String(stability.psi_latest)}</span>,
        read as {String(stability.reading)}. {String(stability.bands)}
      </p>
      <div className="mt-3 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
            PSI over time
          </p>
          <Spark label="PSI" testId="ews-psi-series" height={60}
                 points={series.map((row) => ({
                   month: row.month, value: row.psi_vs_first ?? 0 }))} />
        </div>
        <div>
          <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
            Alert rate over time
          </p>
          <Spark label="Alert rate %" testId="ews-alert-series" height={60}
                 points={series.map((row) => ({
                   month: row.month, value: row.alert_rate * 100 }))} />
        </div>
      </div>
    </Card>
  );
}

function LeadTimeBlock({ lead }: { lead: Record<string, unknown> }) {
  if (!lead?.available) return null;
  const spread = (lead.distribution ?? []) as {
    months_early: number; facilities: number }[];
  return (
    <Card className="p-4" data-testid="ews-version-lead-time">
      <p className="text-sm font-semibold text-text-primary">Lead time</p>
      <dl className="mt-2 grid gap-3 text-[12px] sm:grid-cols-3 lg:grid-cols-5">
        {[
          ["Deteriorated", Number(lead.facilities_that_deteriorated ?? 0).toLocaleString()],
          ["Warned in time", Number(lead.warned_before_or_with ?? 0).toLocaleString()],
          ["Never warned", Number(lead.never_warned_in_time ?? 0).toLocaleString()],
          ["Median months", String(lead.median_months ?? "—")],
          ["≥1 month early", `${String(lead.at_least_1_month_early_pct ?? "—")}%`],
        ].map(([label, value]) => (
          <div key={label}>
            <dt className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
              {label}
            </dt>
            <dd className="tabular-nums text-text-primary">{value}</dd>
          </div>
        ))}
      </dl>
      {spread.length ? (
        <div className="mt-3 max-w-md" data-testid="ews-lead-time-distribution">
          <p className="text-[9px] uppercase tracking-[0.08em] text-text-muted">
            Facilities by months of warning
          </p>
          {/* Bars, not a line. This is how many facilities got each amount of
              warning — a distribution across buckets, with no order in time
              and so no movement to report. Drawn as a trend it reads as one. */}
          <div className="mt-1 flex items-end gap-1" style={{ height: 56 }}>
            {spread.map((row) => {
              const tallest = Math.max(
                ...spread.map((one) => one.facilities), 1);
              return (
                <div key={row.months_early}
                     className="flex min-w-0 flex-1 flex-col items-center gap-0.5">
                  <span className="text-[8px] tabular-nums text-text-muted">
                    {row.facilities.toLocaleString()}
                  </span>
                  <div className="w-full rounded-sm bg-accent/70"
                       style={{ height: `${Math.max(
                         (row.facilities / tallest) * 34, 1)}px` }} />
                  <span className="text-[8px] tabular-nums text-text-muted">
                    {row.months_early}m
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ) : null}
    </Card>
  );
}
