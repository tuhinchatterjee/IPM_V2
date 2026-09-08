"use client";

import * as React from "react";
import {
  ArrowDownRight,
  ArrowUpRight,
  History,
  Info,
  Loader2,
  RotateCw,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type ChangeClaim,
  type LensChanges,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * "CreditProbe View — what changed". §31.
 *
 * Distinct from the CreditProbe View above the tiles, which reads what the
 * Lens SHOWS. This reads what CHANGED since the previous comparable refresh,
 * and the two answer different questions for different readers: a committee
 * asks the first once and the second every quarter.
 *
 * What this panel refuses to do
 * -----------------------------
 * **It never presents a definition or filter change as movement.** Where the
 * classification says the population or the calculation changed, that is the
 * first thing on screen, above any figure — because a reader who sees "Stage 2
 * up 1.3 points" and only later learns the formula changed has already drawn
 * the conclusion.
 *
 * **It shows the basis of every claim.** §28's ladder is on the chip beside
 * each sentence: a correlation is labelled a correlation, and a claim that
 * was downgraded from "confirmed driver" for want of a mechanism says so.
 *
 * **It says when nothing happened.** A quiet quarter renders as one sentence
 * and the three facts behind it, not as a paragraph looking for something to
 * report.
 */
export function LensChangesPanel({
  lensId,
  period,
  version,
  onRefreshed,
}: {
  lensId: number;
  period: string | null;
  version: number;
  onRefreshed?: () => void;
}) {
  const [nonce, setNonce] = React.useState(0);
  const [refreshing, setRefreshing] = React.useState(false);
  const changes = useAsync(
    () => api.lensChanges(lensId, period ?? undefined),
    [lensId, period, version, nonce],
    { keepPrevious: true },
  );

  async function refreshNow() {
    if (refreshing) return;
    setRefreshing(true);
    try {
      await api.refreshLens(lensId, {
        period: period ?? undefined,
        trigger: "manual",
      });
      setNonce((n) => n + 1);
      onRefreshed?.();
    } finally {
      setRefreshing(false);
    }
  }

  if (changes.loading && !changes.data) {
    return <Skeleton className="h-28 w-full" />;
  }

  const data = changes.data;
  if (!data) {
    return (
      <p className="text-[11px] text-text-muted" data-testid="lens-changes-error">
        {changes.error ?? "CreditProbe could not read this Lens's history."}
      </p>
    );
  }

  if (!data.remembered) {
    return (
      <p
        className="text-[11px] text-text-muted"
        data-testid="lens-changes-unavailable"
      >
        {data.note}
      </p>
    );
  }

  const reading = data.changes;

  return (
    <Card
      className="border-accent/30 bg-accent/5 p-5"
      data-testid="lens-changes"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-[0.12em] text-accent">
          <Sparkles className="size-3.5" aria-hidden />
          CreditProbe View — what changed
        </h2>
        <Button
          size="sm"
          variant="ghost"
          onClick={refreshNow}
          disabled={refreshing}
          data-testid="refresh-lens"
        >
          {refreshing ? (
            <Loader2 className="mr-1 size-3 animate-spin" aria-hidden />
          ) : (
            <RotateCw className="mr-1 size-3" aria-hidden />
          )}
          Refresh
        </Button>
      </header>

      <RefreshHeader data={data} />

      {/* The classification, ABOVE the figures. A reader who sees a movement
          first has already drawn a conclusion by the time they learn the
          definition changed. */}
      {data.classification_labels.length > 0 && (
        <ul className="mt-3 space-y-1" data-testid="refresh-classification">
          {data.classification_labels.map((label, i) => (
            <li key={label} className="flex items-start gap-1.5 text-[11px]">
              <Info
                className="mt-0.5 size-3 shrink-0 text-text-muted"
                aria-hidden
              />
              <span>
                <span className="font-medium text-text-primary">{label}.</span>{" "}
                <span className="text-text-secondary">
                  {data.classification_meaning[i]}
                </span>
              </span>
            </li>
          ))}
        </ul>
      )}

      {reading?.definition_caveat && (
        <p
          className="mt-3 rounded border border-warning/40 bg-warning/5 p-2 text-[11px] text-warning"
          data-testid="change-caveat"
        >
          {reading.definition_caveat}
        </p>
      )}

      {reading?.headline && (
        <p
          className="mt-3 text-sm font-medium text-text-primary"
          data-testid="change-headline"
        >
          {reading.headline}
        </p>
      )}

      {reading?.unavailable && (
        <p className="mt-2 text-[11px] text-text-muted" data-testid="change-note">
          {reading.unavailable}
        </p>
      )}

      {reading && <Sections reading={reading} />}

      {data.why_no_comparison && (
        <p
          className="mt-3 text-[11px] text-text-muted"
          data-testid="no-comparison"
        >
          {data.why_no_comparison}
        </p>
      )}
    </Card>
  );
}

/** §31's header: purpose, period, last refreshed, compared with, changes. */
function RefreshHeader({ data }: { data: LensChanges }) {
  return (
    <dl
      className="mt-3 grid gap-x-6 gap-y-1 text-[11px] sm:grid-cols-2"
      data-testid="refresh-header"
    >
      <Pair label="Reporting period" value={data.reporting_period || "—"}
            testId="header-reporting-period" />
      <Pair
        label="Last refreshed"
        value={friendly(data.last_refreshed)}
        testId="header-last-refreshed"
      />
      <Pair
        label="Compared with"
        value={
          data.compared_with
            ? `${friendly(data.compared_with.refreshed_at)}` +
              (data.compared_with.reporting_period
                ? ` · ${data.compared_with.reporting_period}`
                : "") +
              (data.compared_with.exact ? "" : " (not an exact match)")
            : "nothing yet — this is the baseline"
        }
        testId="header-compared-with"
      />
      <div className="flex gap-2">
        <dt className="shrink-0 text-text-muted">Data changes detected</dt>
        <dd className="flex flex-wrap gap-1" data-testid="header-data-changes">
          <Badge
            variant={data.data_changes.cockpit ? "warning" : "outline"}
            data-testid="data-change-cockpit"
          >
            Cockpit {data.data_changes.cockpit ? "changed" : "unchanged"}
          </Badge>
          <Badge
            variant={data.data_changes.ews ? "warning" : "outline"}
            data-testid="data-change-ews"
          >
            Early Warning {data.data_changes.ews ? "changed" : "unchanged"}
          </Badge>
        </dd>
      </div>
      {data.compared_with?.relaxed?.length ? (
        <div className="flex gap-2 sm:col-span-2">
          <dt className="shrink-0 text-text-muted">Comparison note</dt>
          <dd className="text-warning" data-testid="comparison-relaxed">
            {data.compared_with.relaxed.join(" ")}
          </dd>
        </div>
      ) : null}
    </dl>
  );
}

const SECTION_LABELS: Record<string, string> = {
  MATERIAL_CHANGES: "What moved",
  PERSISTENT_TRENDS: "Persistent trends",
  NEW_DETERIORATION: "New deterioration",
  IMPROVEMENTS: "Improvements",
  REVERSALS: "Reversals",
  CROSS_METRIC_CORROBORATION: "Corroboration across metrics",
  SUPPORTED_DRIVERS: "Supported drivers",
  UNCERTAINTIES: "Uncertainties",
  AREAS_REQUIRING_ATTENTION: "Needs attention",
};

function Sections({
  reading,
}: {
  reading: NonNullable<LensChanges["changes"]>;
}) {
  const sections = Object.entries(reading.sections ?? {}).filter(
    ([, claims]) => claims.length > 0,
  );
  if (sections.length === 0) return null;
  return (
    <div className="mt-3 space-y-3" data-testid="change-sections">
      {sections.map(([name, claims]) => (
        <section key={name}>
          <h3 className="text-[10px] uppercase tracking-wide text-text-muted">
            {SECTION_LABELS[name] ?? name}
          </h3>
          <ul className="mt-1 space-y-1.5">
            {claims.map((claim, i) => (
              <Claim key={i} claim={claim} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}

function Claim({ claim }: { claim: ChangeClaim }) {
  return (
    <li className="text-xs text-text-secondary" data-testid="change-claim">
      <span>{claim.text}</span>
      <span className="ml-1.5 inline-flex flex-wrap items-center gap-1 align-middle">
        <span
          className="rounded border border-border px-1 py-px text-[9px] uppercase tracking-wide text-text-muted"
          data-testid="claim-basis"
          title={
            claim.downgraded_from
              ? `CreditProbe downgraded this from ${claim.downgraded_from}: ` +
                "the data shows two things moving together, not a mechanism."
              : undefined
          }
        >
          {claim.basis_label}
          {claim.downgraded_from ? " ↓" : ""}
        </span>
        {claim.metrics.map((name) => (
          <span
            key={name}
            className="rounded border border-border px-1.5 py-px text-[10px] text-text-muted"
          >
            {name}
          </span>
        ))}
      </span>
    </li>
  );
}

/**
 * §32. One metric's two histories, labelled apart.
 *
 * They are different questions — "what did this say each time the Lens ran"
 * and "what did this say for each business period" — and a screen that showed
 * one under the other's heading would be read with complete confidence and be
 * wrong.
 */
export function MetricHistoryPanel({
  lensId,
  metricId,
  metricName,
}: {
  lensId: number;
  metricId: string;
  metricName?: string;
}) {
  const history = useAsync(
    () => api.lensMetricHistory(lensId, metricId),
    [lensId, metricId],
  );

  if (history.loading && !history.data) {
    return <Skeleton className="h-20 w-full" />;
  }
  const data = history.data;
  if (!data || !data.remembered) {
    return (
      <p className="text-[11px] text-text-muted" data-testid="history-unavailable">
        This deployment does not record Lens history, so there is nothing to
        show yet.
      </p>
    );
  }
  if (
    data.refresh_history.length === 0 &&
    data.reporting_period_history.length === 0
  ) {
    return (
      <p className="text-[11px] text-text-muted" data-testid="history-empty">
        No history yet. It builds up from the next refresh.
      </p>
    );
  }

  return (
    <div className="space-y-3" data-testid="metric-history">
      <h4 className="flex items-center gap-1.5 text-xs font-semibold text-text-primary">
        <History className="size-3.5" aria-hidden />
        {metricName || metricId}
      </h4>
      <HistoryList
        title="Refresh history"
        note={data.labels.refresh_history}
        testId="refresh-history"
        points={data.refresh_history.map((p) => ({
          key: `${p.refresh_id}`,
          label: friendly(p.refreshed_at),
          value: p.value,
          unit: p.unit,
          decimals: p.decimals,
        }))}
      />
      <HistoryList
        title="Reporting period history"
        note={data.labels.reporting_period_history}
        testId="reporting-period-history"
        points={data.reporting_period_history.map((p) => ({
          key: p.reporting_period,
          label: p.reporting_period,
          value: p.value,
          unit: p.unit,
          decimals: p.decimals,
        }))}
      />
      {data.definition_changed_during && (
        <p className="text-[11px] text-warning" data-testid="history-definition-note">
          {data.definition_note}
        </p>
      )}
    </div>
  );
}

function HistoryList({
  title,
  note,
  testId,
  points,
}: {
  title: string;
  note: string;
  testId: string;
  points: {
    key: string;
    label: string;
    value: number | null;
    unit: string;
    decimals: number;
  }[];
}) {
  if (points.length === 0) return null;
  const previous = points.length > 1 ? points[points.length - 2].value : null;
  const latest = points[points.length - 1].value;
  return (
    <section data-testid={testId}>
      <h5 className="text-[10px] uppercase tracking-wide text-text-muted">
        {title}
        {latest !== null && previous !== null && latest !== previous && (
          <span className="ml-1.5 inline-flex items-center text-[10px] normal-case text-text-secondary">
            {latest > previous ? (
              <ArrowUpRight className="size-3 text-warning" aria-hidden />
            ) : (
              <ArrowDownRight className="size-3 text-positive" aria-hidden />
            )}
          </span>
        )}
      </h5>
      <p className="text-[10px] text-text-muted">{note}</p>
      <ul className="mt-1 space-y-0.5">
        {points.map((point) => (
          <li
            key={point.key}
            className="flex justify-between gap-4 text-[11px]"
          >
            <span className="text-text-muted">{point.label}</span>
            <span className="font-mono text-text-primary">
              {format(point.value, point.unit, point.decimals)}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Pair({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-text-muted">{label}</dt>
      <dd className="text-text-secondary" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

function friendly(iso: string): string {
  if (!iso) return "—";
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return iso;
  return at.toLocaleString(undefined, {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function format(
  value: number | null,
  unit: string,
  decimals: number,
): string {
  if (value === null || value === undefined) return "—";
  const shown = value.toLocaleString(undefined, {
    minimumFractionDigits: unit === "count" ? 0 : decimals,
    maximumFractionDigits: unit === "count" ? 0 : decimals,
  });
  return unit === "percent" ? `${shown}%` : shown;
}
