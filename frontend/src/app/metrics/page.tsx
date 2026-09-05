"use client";

import * as React from "react";
import { BookOpen, Loader2, Plus } from "lucide-react";

import { MetricBuilder } from "@/components/metrics/metric-builder";
import { MetricInfo } from "@/components/metrics/metric-panel";
import { MetricPicker } from "@/components/metrics/metric-picker";
import { formatMetric } from "@/components/metrics/present";
import { VerificationWorkspace } from "@/components/metrics/verification";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type MetricPanel,
  type MetricUnavailable,
  type MetricValue,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * The Metric Catalogue.
 *
 * One place that says what CreditProbe means by each number. Before this, a
 * dashboard's formulas lived in the component that drew them, so a figure on
 * a screen and the same figure in an answer were two implementations of one
 * definition and the only way to know whether they agreed was to read both.
 *
 * The search comes first and the catalogue second, deliberately: §8.3 asks
 * that a picker does not open with everything. Somebody who wants the whole
 * list can have it, but they have to say so.
 */
export default function MetricCataloguePage() {
  const [selected, setSelected] = React.useState<string | null>(null);
  const [browsing, setBrowsing] = React.useState(false);
  const [building, setBuilding] = React.useState(false);

  return (
    <div className="space-y-6">
      <header>
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-text-muted">
          Metrics
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
            Metric Catalogue
          </h1>
          <InfoPopover title="What this is">
            <p>
              Every number CreditProbe can put on a screen, with the definition
              behind it: the formula, the numerator, the denominator, the
              fields it reads, what it excludes and what it is not.
            </p>
            <p>
              Governed metrics are part of what the platform means and are
              defined in code. A metric somebody built is marked as such, and
              stays marked until it has been checked against a number that was
              already trusted.
            </p>
          </InfoPopover>
        </div>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-text-secondary">
          Search by what you call it. &ldquo;NPL rate&rdquo;, &ldquo;bad
          rate&rdquo; and &ldquo;default rate&rdquo; are one number, and the
          catalogue answers to all three.
        </p>
      </header>

      <Card className="p-4">
        <MetricPicker onPick={(hit) => setSelected(hit.metric_id)} autoFocus />
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setBrowsing((b) => !b)}
          >
            <BookOpen aria-hidden />
            {browsing ? "Hide the whole catalogue" : "Show the whole catalogue"}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setBuilding((b) => !b)}
          >
            <Plus aria-hidden />
            {building ? "Close the builder" : "Build a metric"}
          </Button>
        </div>
      </Card>

      {building && (
        <MetricBuilder
          onSaved={(metric) => {
            setBuilding(false);
            setSelected(metric.metric_id);
          }}
          onCancel={() => setBuilding(false)}
        />
      )}

      {selected && (
        <MetricDetail
          metricId={selected}
          onClose={() => setSelected(null)}
          key={selected}
        />
      )}

      {browsing && <Catalogue onPick={setSelected} />}
    </div>
  );
}

function Catalogue({ onPick }: { onPick: (metricId: string) => void }) {
  const catalogue = useAsync(() => api.metricCatalogue(), []);

  if (catalogue.loading && !catalogue.data) {
    return <Skeleton className="h-64 w-full" />;
  }
  if (catalogue.error && !catalogue.data) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {catalogue.error}
      </Card>
    );
  }
  if (!catalogue.data) return null;

  return (
    <div className="space-y-5">
      {catalogue.data.domains.map((group) => (
        <section key={group.domain}>
          <h2 className="text-sm font-semibold tracking-tight text-text-primary">
            {group.domain}
            <span className="ml-2 text-xs font-normal text-text-muted">
              {group.metrics.length}
            </span>
          </h2>
          <Card className="mt-2 divide-y divide-border">
            {group.metrics.map((metric) => (
              <button
                key={metric.metric_id}
                type="button"
                onClick={() => onPick(metric.metric_id)}
                className="block w-full px-4 py-2.5 text-left hover:bg-surface-muted"
              >
                <span className="flex flex-wrap items-baseline gap-2">
                  <span className="text-sm text-text-primary">
                    {metric.name}
                  </span>
                  {!metric.governed && (
                    <Badge variant="warning">{metric.origin_label}</Badge>
                  )}
                  {!metric.trustworthy && (
                    <Badge variant="warning">{metric.status_label}</Badge>
                  )}
                </span>
                <span className="mt-0.5 block text-xs leading-relaxed text-text-muted">
                  {metric.definition}
                </span>
              </button>
            ))}
          </Card>
        </section>
      ))}

      <Unavailable entries={catalogue.data.unavailable} />
    </div>
  );
}

/**
 * The metrics CreditProbe knows about and cannot calculate here.
 *
 * Listed rather than omitted. Somebody who came looking for a roll rate has
 * come to the right place and deserves the reason, not silence.
 */
function Unavailable({ entries }: { entries: MetricUnavailable[] }) {
  if (entries.length === 0) return null;
  return (
    <section>
      <h2 className="text-sm font-semibold tracking-tight text-text-primary">
        Not available in this deployment
      </h2>
      <Card className="mt-2 divide-y divide-border">
        {entries.map((entry) => (
          <div key={entry.metric_id} className="px-4 py-2.5">
            <p className="text-sm text-text-secondary">
              {entry.name}
              <span className="ml-2 text-xs text-text-muted">
                {entry.domain}
              </span>
            </p>
            <p className="mt-0.5 text-xs leading-relaxed text-text-muted">
              {entry.because}
            </p>
            {entry.needs.length > 0 && (
              <p className="mt-0.5 text-[11px] text-text-muted">
                Would need: {entry.needs.join("; ")}
              </p>
            )}
          </div>
        ))}
      </Card>
    </section>
  );
}

/**
 * One metric: what it means, what it is worth now, and the workspace for
 * checking that against a number somebody already trusted.
 */
function MetricDetail({
  metricId,
  onClose,
}: {
  metricId: string;
  onClose: () => void;
}) {
  const [period, setPeriod] = React.useState("");
  const [computed, setComputed] = React.useState<MetricValue | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const panel = useAsync<MetricPanel>(() => api.metric(metricId), [metricId]);

  async function compute() {
    setBusy(true);
    setError(null);
    try {
      setComputed(await api.metricValue(metricId, period.trim()));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (panel.loading && !panel.data) return <Skeleton className="h-64 w-full" />;
  if (panel.error && !panel.data) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {panel.error}
      </Card>
    );
  }
  if (!panel.data) return null;
  const metric = panel.data;

  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold tracking-tight text-text-primary">
              {metric.name}
            </h2>
            <Badge variant={metric.governed ? "outline" : "warning"}>
              {metric.origin_label}
            </Badge>
            <Badge variant={metric.trustworthy ? "outline" : "warning"}>
              {metric.status_label}
            </Badge>
          </div>
          <p className="mt-1 max-w-2xl text-sm leading-relaxed text-text-secondary">
            {metric.definition}
          </p>
        </div>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>

      <div className="mt-4 flex flex-wrap items-end gap-2">
        <label className="text-xs text-text-muted">
          Period
          <input
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="Latest"
            className="ml-2 h-8 w-40 rounded-md border border-border bg-surface px-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
        </label>
        <Button size="sm" onClick={compute} disabled={busy}>
          {busy && <Loader2 className="animate-spin" aria-hidden />}
          Calculate
        </Button>
      </div>

      {error && <p className="mt-2 text-xs text-negative">{error}</p>}

      {computed && (
        <div className="mt-4 rounded-md border border-border p-4">
          {computed.available ? (
            <>
              <p className="text-[26px] font-semibold leading-none tabular tracking-tight text-text-primary">
                {formatMetric(
                  computed.value,
                  computed.unit,
                  computed.decimals,
                )}
              </p>
              <p className="mt-1.5 font-mono text-[11px] text-text-muted">
                {computed.calculation.final}
              </p>
              {computed.period && (
                <p className="mt-0.5 text-xs text-text-muted">
                  {computed.period}
                </p>
              )}
            </>
          ) : (
            <>
              <p className="text-[26px] font-semibold leading-none text-text-muted">
                —
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
                {computed.unavailable}
              </p>
            </>
          )}
        </div>
      )}

      <div className="mt-5 border-t border-border pt-4">
        <MetricInfo metric={metric} calculation={computed?.calculation} />
      </div>

      <div className="mt-5 border-t border-border pt-4">
        <VerificationWorkspace
          metricId={metricId}
          computed={computed}
          period={period.trim()}
          onVerified={() => void panel.reload?.()}
        />
      </div>
    </Card>
  );
}
