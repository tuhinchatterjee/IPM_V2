"use client";

import * as React from "react";

import { Field, Locator, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import type { PbMetric, PbMetrics } from "@/lib/api";
import { freshness, orderMetrics } from "@/lib/intelligence";

/**
 * The metric inventory and its review queue. §16.
 *
 * The standing product rule governs this whole screen:
 *
 * > Never silently confirm an uploaded field purely from text similarity.
 *
 * So a suggestion is shown immediately, labelled as a suggestion, with the
 * label that was detected, the value, the sheet and cell it came from and the
 * governed metric it *resembles* — and it stays out of THEN/NOW, out of
 * freshness, and out of anything that counts as a governed link until a
 * person confirms it.
 *
 * "Confirm all high-confidence" is offered. "Confirm all" is not: confirming
 * every suggestion regardless of confidence is the automatic confirmation the
 * rule forbids, wearing a button.
 */
export function MetricsTab({
  metrics,
  busy,
  error,
  onConfirm,
  onChange,
  onIgnore,
  onConfirmHighConfidence,
  onConfirmSelected,
  onAsk,
}: {
  metrics: PbMetrics;
  busy: number;
  error: string;
  onConfirm: (metric: PbMetric) => void;
  onChange: (metric: PbMetric) => void;
  onIgnore: (metric: PbMetric) => void;
  onConfirmHighConfidence: () => void;
  onConfirmSelected: (ids: number[]) => void;
  onAsk: (metric: PbMetric) => void;
}) {
  const [selected, setSelected] = React.useState<number[]>([]);
  const queue = metrics.suggested_review ?? [];
  const inventory = orderMetrics(metrics.inventory ?? []);

  const toggle = (id: number) =>
    setSelected((s) => (s.includes(id) ? s.filter((x) => x !== id)
      : [...s, id]));

  return (
    <div className="space-y-5" data-testid="playbook-metrics-tab">
      <section className="rounded-lg border border-border bg-surface p-4">
        <div className="flex flex-wrap items-baseline gap-x-6 gap-y-2">
          <Count label="Detected" value={metrics.detected} />
          <Count label="Confirmed" value={metrics.confirmed} tone="green" />
          <Count label="Suggested" value={metrics.suggested} tone="amber" />
          <Count label="Unlinked" value={metrics.unlinked} />
          <div className="ml-auto text-right">
            <p className="text-[10px] uppercase tracking-wide text-text-muted">
              Linkage coverage
            </p>
            <p className="text-lg font-semibold tabular-nums text-text-primary">
              {metrics.coverage_pct}%
            </p>
          </div>
        </div>
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          Coverage counts confirmed links only. A suggestion nobody has
          confirmed lowers this figure on purpose — it is not being treated as
          linked data.
        </p>
      </section>

      {error && (
        <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative"
          data-testid="playbook-metrics-error">
          {error}
        </p>
      )}

      {queue.length > 0 && (
        <section className="space-y-3" data-testid="playbook-metric-review">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-text-primary">
              {metrics.review_prompt ||
                `Review ${queue.length} suggested link${
                  queue.length === 1 ? "" : "s"
                }`}
            </h2>
            <div className="ml-auto flex flex-wrap gap-1.5">
              <SmallButton
                onClick={onConfirmHighConfidence}
                disabled={busy !== 0}
                testId="playbook-confirm-high-confidence"
              >
                Confirm all high-confidence
              </SmallButton>
              <SmallButton
                onClick={() => {
                  onConfirmSelected(selected);
                  setSelected([]);
                }}
                disabled={busy !== 0 || selected.length === 0}
                testId="playbook-confirm-selected"
              >
                Confirm selected ({selected.length})
              </SmallButton>
            </div>
          </div>

          <ul className="space-y-3">
            {queue.map((metric) => (
              <SuggestionCard
                key={metric.id}
                metric={metric}
                checked={selected.includes(metric.id)}
                busy={busy === metric.id}
                onToggle={() => toggle(metric.id)}
                onConfirm={() => onConfirm(metric)}
                onChange={() => onChange(metric)}
                onIgnore={() => onIgnore(metric)}
              />
            ))}
          </ul>
        </section>
      )}

      <section>
        <h2 className="mb-2 text-sm font-semibold text-text-primary">
          Metric inventory
        </h2>
        {inventory.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
            No metrics have been detected in this document.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[48rem] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-surface-sunken text-left">
                  <Th>Metric</Th>
                  <Th className="text-right">Value</Th>
                  <Th>Link</Th>
                  <Th>Freshness</Th>
                  <Th>Source</Th>
                  <Th />
                </tr>
              </thead>
              <tbody>
                {inventory.map((metric) => (
                  <tr key={metric.id}
                    className="border-b border-border last:border-b-0"
                    data-testid="playbook-metric-row">
                    <td className="px-3 py-2">
                      <p className="font-medium text-text-primary">
                        {metric.label}
                      </p>
                      {metric.metric_id && (
                        <p className="text-[10px] text-text-muted">
                          {metric.metric_id}
                        </p>
                      )}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-text-primary">
                      {metric.display_value || metric.value_in_document || "—"}
                    </td>
                    <td className="px-3 py-2">
                      <StatusChip
                        tone={metric.governed ? "green" : "amber"}
                        title={metric.method_label}
                      >
                        {metric.governed ? "Governed" : metric.method_label ||
                          "Not confirmed"}
                      </StatusChip>
                    </td>
                    <td className="px-3 py-2">
                      {/* Freshness is a governed signal; an unconfirmed
                          suggestion never triggers it. */}
                      {metric.governed ? (
                        <StatusChip tone={freshness(metric.freshness).tone}>
                          {freshness(metric.freshness).label}
                        </StatusChip>
                      ) : (
                        <span className="text-[11px] text-text-muted">—</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      <Locator value={metric.source_locator} />
                    </td>
                    <td className="px-3 py-2 text-right">
                      <SmallButton onClick={() => onAsk(metric)}>
                        Ask Claude about this
                      </SmallButton>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Count({ label, value, tone }: { label: string; value: number;
  tone?: "green" | "amber" }) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-wide text-text-muted">
        {label}
      </p>
      <p
        className={
          "text-lg font-semibold tabular-nums " +
          (tone === "green"
            ? "text-positive"
            : tone === "amber"
              ? "text-warning"
              : "text-text-primary")
        }
      >
        {value}
      </p>
    </div>
  );
}

function Th({ children, className = "" }: { children?: React.ReactNode;
  className?: string }) {
  return (
    <th className={
      "px-3 py-2 text-[10px] font-semibold uppercase tracking-wide text-text-muted " +
      className}>
      {children}
    </th>
  );
}

function SuggestionCard({
  metric,
  checked,
  busy,
  onToggle,
  onConfirm,
  onChange,
  onIgnore,
}: {
  metric: PbMetric;
  checked: boolean;
  busy: boolean;
  onToggle: () => void;
  onConfirm: () => void;
  onChange: () => void;
  onIgnore: () => void;
}) {
  return (
    <li className="rounded-lg border border-warning/40 bg-surface p-4"
      data-testid="playbook-suggestion-card">
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={checked}
          onChange={onToggle}
          aria-label={`Select ${metric.label}`}
          data-testid="playbook-suggestion-select"
          className="mt-1 size-4 accent-[var(--ipm-accent)]"
        />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-text-primary">
              {metric.document_label || metric.label}
            </h3>
            <StatusChip tone="amber">
              {metric.method_label || "Suggested — confirmation required"}
            </StatusChip>
          </div>

          <div className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="Value in document">
              <span className="tabular-nums">
                {metric.display_value || metric.value_in_document || "—"}
              </span>
            </Field>
            {metric.reporting_period && (
              <Field label="Period">{metric.reporting_period}</Field>
            )}
            <Field label="Suggested metric">
              <code className="text-xs">{metric.metric_id || "none"}</code>
            </Field>
            <Field label="Confidence">
              {metric.confidence
                ? metric.confidence[0].toUpperCase() +
                  metric.confidence.slice(1)
                : "not stated"}
            </Field>
          </div>

          {metric.source_locator && (
            <p className="mt-2 text-[11px] text-text-muted">
              Source <Locator value={metric.source_locator} />
            </p>
          )}

          <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
            Not being used as a governed link. It does not appear in Then/Now,
            does not trigger a refresh and does not satisfy a required metric
            until it is confirmed.
          </p>

          <div className="mt-3 flex flex-wrap gap-1.5">
            <SmallButton onClick={onConfirm} disabled={busy}
              testId="playbook-suggestion-confirm">
              Confirm
            </SmallButton>
            <SmallButton onClick={onChange} disabled={busy}
              testId="playbook-suggestion-change">
              Change mapping
            </SmallButton>
            <SmallButton onClick={onIgnore} disabled={busy}
              testId="playbook-suggestion-ignore">
              Ignore
            </SmallButton>
          </div>
        </div>
      </div>
    </li>
  );
}
