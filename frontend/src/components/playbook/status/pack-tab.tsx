"use client";

import * as React from "react";
import { FileText, MessageSquare, PencilLine } from "lucide-react";

import { Field, Locator, StatusChip } from "@/components/playbook/status/chips";
import type { PbDashboard, PbMetric, PbSectionRow } from "@/lib/api";
import {
  componentViews,
  orderSections,
  sectionStatus,
  statistics,
} from "@/lib/intelligence";

/**
 * The Pack / Overview tab. §12.
 *
 * The purpose is stated in the specification and is worth repeating here
 * because it decides every layout choice below: **a senior user should
 * understand the document without opening Word or PDF.** So this is the
 * report read section by section, with the metrics that sit in each section
 * beside it, its review state, and what can be done about it.
 */
export function PackTab({
  dashboard,
  onAsk,
  onUpdateSection,
  onOpenSection,
}: {
  dashboard: PbDashboard;
  onAsk: (kind: string, target: string) => void;
  onUpdateSection: (sectionKey: string) => void;
  onOpenSection: (sectionKey: string) => void;
}) {
  const sections = orderSections(dashboard.sections);
  const metricsBySection = new Map<string, PbMetric[]>();
  for (const metric of dashboard.metrics.inventory) {
    if (!metric.section_key) continue;
    const list = metricsBySection.get(metric.section_key) ?? [];
    list.push(metric);
    metricsBySection.set(metric.section_key, list);
  }
  const findingsBySection = new Map<string, number>();
  for (const finding of dashboard.findings.items) {
    if (!finding.section_key) continue;
    findingsBySection.set(
      finding.section_key,
      (findingsBySection.get(finding.section_key) ?? 0) + 1,
    );
  }

  return (
    <div className="space-y-5" data-testid="playbook-pack-tab">
      <CompletionSummary dashboard={dashboard} />

      {sections.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
          No document has been generated in this Playbook yet. The conversation
          is where one gets written.
        </p>
      ) : (
        <ul className="space-y-3">
          {sections.map((section) => (
            <SectionCard
              key={section.section_key}
              section={section}
              metrics={metricsBySection.get(section.section_key) ?? []}
              findings={findingsBySection.get(section.section_key) ?? 0}
              onAsk={onAsk}
              onUpdate={() => onUpdateSection(section.section_key)}
              onOpen={() => onOpenSection(section.section_key)}
            />
          ))}
        </ul>
      )}

      <DocumentStatistics dashboard={dashboard} />
    </div>
  );
}

function CompletionSummary({ dashboard }: { dashboard: PbDashboard }) {
  const parts = componentViews(
    dashboard.readiness.completion_components,
    dashboard.committee_report,
  );
  if (parts.length === 0) return null;
  return (
    <section className="rounded-lg border border-border bg-surface p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
          Completion
        </h2>
        <p className="text-sm text-text-secondary">
          <span className="text-lg font-semibold tabular-nums text-text-primary">
            {dashboard.readiness.completion_pct}%
          </span>{" "}
          of the expected document exists
        </p>
      </div>
      {/* Completion and readiness are different questions and are never
          combined. §9. */}
      <p className="mt-1 text-[11px] text-text-muted">
        How much of the expected document exists. Whether it is ready to go
        anywhere is a separate question, answered in the readiness panel.
      </p>
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {parts.map((part) => (
          <li key={part.name}
            className="flex items-center justify-between gap-2 rounded border border-border bg-surface-sunken px-2 py-1.5">
            <span className="min-w-0 truncate text-[11px] text-text-secondary">
              {part.name}
            </span>
            <StatusChip tone={part.tone}>{part.display}</StatusChip>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SectionCard({
  section,
  metrics,
  findings,
  onAsk,
  onUpdate,
  onOpen,
}: {
  section: PbSectionRow;
  metrics: PbMetric[];
  findings: number;
  onAsk: (kind: string, target: string) => void;
  onUpdate: () => void;
  onOpen: () => void;
}) {
  const status = sectionStatus(section.status);
  const pages =
    section.page_from && section.page_to
      ? `${section.page_from}–${section.page_to}`
      : section.page_from
        ? String(section.page_from)
        : "";

  return (
    <li className="rounded-lg border border-border bg-surface"
      data-testid="playbook-section-card">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <h3 className="truncate text-sm font-semibold text-text-primary">
            {section.heading}
          </h3>
          <p className="mt-0.5 flex flex-wrap gap-x-3 text-[11px] text-text-muted">
            {pages && <span>Page {pages}</span>}
            <span>{section.word_count.toLocaleString()} words</span>
            <span>Changed in version {section.last_changed_version}</span>
            {section.reviewer && <span>Reviewer {section.reviewer}</span>}
          </p>
        </div>
        <StatusChip tone={status.tone}>{status.label}</StatusChip>
      </div>

      {section.stale_reason && (
        <p className="border-b border-border bg-surface-warning px-4 py-1.5 text-[11px] text-text-primary">
          {section.stale_reason}
        </p>
      )}

      {metrics.length > 0 && (
        <ul className="grid gap-x-6 gap-y-2 px-4 py-3 sm:grid-cols-2 lg:grid-cols-3">
          {metrics.map((metric) => (
            <li key={metric.id}>
              <Field label={metric.label}>
                <span className="tabular-nums">
                  {metric.display_value || metric.value_in_document || "—"}
                </span>
                {!metric.governed && (
                  <span className="ml-2 text-[10px] text-warning">
                    suggested
                  </span>
                )}
              </Field>
              <Locator value={metric.source_locator} />
            </li>
          ))}
        </ul>
      )}

      <div className="flex flex-wrap items-center gap-2 px-4 pb-3 pt-1">
        {findings > 0 && (
          <span className="text-[11px] text-warning">
            {findings} finding{findings === 1 ? "" : "s"} against this section
          </span>
        )}
        <div className="ml-auto flex flex-wrap gap-1.5">
          <SmallButton onClick={onOpen} icon={FileText}>
            Open section
          </SmallButton>
          <SmallButton
            onClick={() => onAsk("section", section.section_key)}
            icon={MessageSquare}
          >
            Ask Claude
          </SmallButton>
          <SmallButton onClick={onUpdate} icon={PencilLine}>
            Update this section
          </SmallButton>
        </div>
      </div>
    </li>
  );
}

export function SmallButton({
  onClick,
  icon: Icon,
  children,
  disabled,
  testId,
}: {
  onClick: () => void;
  icon?: typeof FileText;
  children: React.ReactNode;
  disabled?: boolean;
  testId?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="inline-flex items-center gap-1 rounded border border-border bg-surface px-2 py-1 text-[11px] font-medium text-text-secondary hover:bg-surface-hover disabled:opacity-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
    >
      {Icon && <Icon className="size-3" aria-hidden />}
      {children}
    </button>
  );
}

function DocumentStatistics({ dashboard }: { dashboard: PbDashboard }) {
  const rows = statistics(dashboard);
  return (
    <section className="rounded-lg border border-border bg-surface p-4"
      data-testid="playbook-statistics">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-text-muted">
        Document statistics
      </h2>
      <dl className="mt-3 grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3 lg:grid-cols-4">
        {rows.map((row) => (
          <div key={row.label} className="min-w-0">
            <dt className="text-[10px] uppercase tracking-wide text-text-muted">
              {row.label}
            </dt>
            <dd className="text-sm tabular-nums text-text-primary">
              {row.value}
            </dd>
            {row.note && (
              <dd className="text-[10px] leading-snug text-text-muted">
                {row.note}
              </dd>
            )}
          </div>
        ))}
      </dl>
    </section>
  );
}
