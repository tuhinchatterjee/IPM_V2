"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { readablePeriodRule } from "@/components/metrics/present";
import type { MetricCalculation, MetricPanel } from "@/lib/api";

/**
 * Everything §6 asks a number to be able to explain about itself.
 *
 * The content comes from the backend, assembled in one place, so the panel on
 * a lens tile, the panel beside a chart and the answer to "how is this
 * calculated?" say the same thing. Nothing here is composed from the tile's
 * own knowledge of the metric, because two descriptions of one definition is
 * the problem the Metric Catalogue exists to solve.
 *
 * The order is deliberate. What it measures, then how it is calculated, then
 * what was actually computed, then where the numbers came from, and only then
 * the governance. A reader who came to check one figure should reach their
 * answer before they reach the version number.
 */
export function MetricInfo({
  metric,
  calculation,
}: {
  metric: MetricPanel;
  calculation?: MetricCalculation;
}) {
  return (
    <div className="space-y-3 text-xs leading-relaxed">
      <Section label="What it measures">
        <p className="text-text-secondary">{metric.definition}</p>
      </Section>

      <Section label="How it is calculated">
        <p className="font-mono text-[11px] text-text-primary">
          {metric.formula}
        </p>
        {metric.numerator && (
          <Row label="Numerator" value={metric.numerator} />
        )}
        {metric.denominator && (
          <Row label="Denominator" value={metric.denominator} />
        )}
        {metric.transformation && (
          <p className="mt-1 text-text-muted">{metric.transformation}</p>
        )}
      </Section>

      {calculation && calculation.value !== null && (
        <Section label="This figure">
          <p className="font-mono text-[11px] text-text-primary">
            {calculation.final}
          </p>
          {calculation.period && (
            <Row label="Period" value={calculation.period} />
          )}
          {calculation.rows_considered > 0 && (
            <Row
              label="Rows"
              value={calculation.rows_considered.toLocaleString()}
            />
          )}
          {calculation.warnings
            .filter((w) => w.trim())
            .map((warning) => (
              <p key={warning} className="mt-1 text-text-muted">
                {warning}
              </p>
            ))}
        </Section>
      )}

      <Section label="Where it comes from">
        {metric.datasets.map((dataset) => (
          <Row key={dataset} label="Dataset" value={dataset} />
        ))}
        {metric.source_fields.length > 0 && (
          <ul className="mt-1 space-y-0.5">
            {metric.source_fields.map((field) => (
              <li key={field.name} className="text-text-muted">
                <span className="font-mono text-[11px] text-text-secondary">
                  {field.name}
                </span>
                {field.business_name ? ` · ${field.business_name}` : ""}
                {field.definition ? ` — ${field.definition}` : ""}
              </li>
            ))}
          </ul>
        )}
        {metric.filters.map((filter) => (
          <Row key={filter} label="Filter" value={filter} />
        ))}
        <Row label="Period rule" value={readablePeriodRule(metric.period_rule)} />
        {metric.exclusions && (
          <Row label="Excluded" value={metric.exclusions} />
        )}
      </Section>

      {metric.not_this && (
        // Often the most useful line here: the assumption a reasonable person
        // would otherwise make, said out loud.
        <Section label="What it is not">
          <p className="text-warning">{metric.not_this}</p>
        </Section>
      )}

      <Section label="Governance">
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge variant={metric.governed ? "outline" : "warning"}>
            {metric.origin_label}
          </Badge>
          <Badge variant={metric.trustworthy ? "outline" : "warning"}>
            {metric.status_label}
          </Badge>
          <span className="text-text-muted">version {metric.version}</span>
        </div>
        <Row label="Owner" value={metric.owner} />
        {metric.verified_at && (
          <Row
            label="Verified"
            value={
              metric.last_verified_note
                ? `${metric.verified_at.slice(0, 10)} — ${metric.last_verified_note}`
                : metric.verified_at.slice(0, 10)
            }
          />
        )}
        {metric.aliases.length > 0 && (
          <Row label="Also called" value={metric.aliases.join(", ")} />
        )}
      </Section>
    </div>
  );
}

function Section({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
        {label}
      </p>
      <div className="mt-1">{children}</div>
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <p className="text-text-secondary">
      <span className="text-text-muted">{label}: </span>
      {value}
    </p>
  );
}
