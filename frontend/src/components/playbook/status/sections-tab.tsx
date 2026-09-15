"use client";

import * as React from "react";
import { MessageSquare } from "lucide-react";

import { Field, Locator, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import { MarkdownView } from "@/components/playbook/markdown-view";
import type { PbDashboard, PbSectionDetail } from "@/lib/api";
import {
  actorLabel,
  describeHistoryEntry,
  orderSections,
  sectionStatus,
  severity,
  shortDateTime,
} from "@/lib/intelligence";
import { cn } from "@/lib/utils";

/**
 * The section workbench. §17.
 *
 * Three columns, and each answers a different question. LEFT: which section?
 * CENTRE: what does it say? RIGHT: what is the state of it — who is reviewing,
 * which metrics sit in it, what has been raised against it, what may be done
 * to it next.
 *
 * The status transitions offered come from `allowed`, which the backend
 * computes from the same transition table the service enforces. Offering a
 * move the service would refuse is how a UI teaches somebody that the buttons
 * lie.
 */
export function SectionsTab({
  dashboard,
  selected,
  detail,
  loading,
  busy,
  error,
  onSelect,
  onAsk,
  onUpdate,
  onTransition,
  onAssignReviewer,
}: {
  dashboard: PbDashboard;
  selected: string;
  detail: PbSectionDetail | null;
  loading: boolean;
  busy: boolean;
  error: string;
  onSelect: (key: string) => void;
  onAsk: (key: string) => void;
  onUpdate: (key: string) => void;
  onTransition: (key: string, status: string) => void;
  onAssignReviewer: (key: string) => void;
}) {
  const sections = orderSections(dashboard.sections);

  if (sections.length === 0) {
    return (
      <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted"
        data-testid="playbook-sections-tab">
        This Playbook has no document yet, so it has no sections.
      </p>
    );
  }

  return (
    <div
      className="grid gap-4 lg:grid-cols-[14rem_minmax(0,1fr)_16rem]"
      data-testid="playbook-sections-tab"
    >
      <nav aria-label="Sections"
        className="max-h-[32rem] overflow-y-auto rounded-lg border border-border bg-surface">
        <ul>
          {sections.map((section) => {
            const status = sectionStatus(section.status);
            const active = section.section_key === selected;
            return (
              <li key={section.section_key}>
                <button
                  type="button"
                  onClick={() => onSelect(section.section_key)}
                  aria-current={active ? "true" : undefined}
                  data-testid="playbook-section-nav-item"
                  className={cn(
                    "flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left text-xs last:border-b-0",
                    "hover:bg-surface-hover focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-accent",
                    active && "bg-accent-muted",
                  )}
                >
                  <span className="min-w-0 flex-1 truncate text-text-primary">
                    {section.heading}
                  </span>
                  <StatusChip tone={status.tone} title={status.label}>
                    <span className="sr-only">{status.label}</span>
                    <span aria-hidden>·</span>
                  </StatusChip>
                </button>
              </li>
            );
          })}
        </ul>
      </nav>

      <div className="min-w-0 rounded-lg border border-border bg-surface p-4">
        {loading ? (
          <p className="text-sm text-text-muted">Reading the section…</p>
        ) : !detail ? (
          <p className="text-sm text-text-muted">
            Choose a section to read it.
          </p>
        ) : (
          <>
            <h3 className="text-base font-semibold text-text-primary">
              {detail.heading}
            </h3>
            {detail.text ? (
              <div className="mt-3">
                <MarkdownView source={detail.text} />
              </div>
            ) : (
              <p className="mt-3 text-sm text-text-muted">
                The text of this section is not available from the stored
                version.
              </p>
            )}
          </>
        )}
      </div>

      <aside className="space-y-3">
        {error && (
          <p className="rounded-md border border-negative/40 bg-negative-muted p-2 text-[11px] text-negative"
            data-testid="playbook-section-error">
            {error}
          </p>
        )}
        {detail && (
          <SectionIntelligence
            detail={detail}
            busy={busy}
            onAsk={() => onAsk(detail.section_key)}
            onUpdate={() => onUpdate(detail.section_key)}
            onTransition={(status) => onTransition(detail.section_key, status)}
            onAssignReviewer={() => onAssignReviewer(detail.section_key)}
          />
        )}
      </aside>
    </div>
  );
}

function SectionIntelligence({
  detail,
  busy,
  onAsk,
  onUpdate,
  onTransition,
  onAssignReviewer,
}: {
  detail: PbSectionDetail;
  busy: boolean;
  onAsk: () => void;
  onUpdate: () => void;
  onTransition: (status: string) => void;
  onAssignReviewer: () => void;
}) {
  const status = sectionStatus(detail.status);
  const pages =
    detail.page_from && detail.page_to
      ? `${detail.page_from}–${detail.page_to}`
      : detail.page_from
        ? String(detail.page_from)
        : "not known";

  return (
    <div className="space-y-3" data-testid="playbook-section-intelligence">
      <div className="rounded-lg border border-border bg-surface p-3">
        <div className="flex items-center justify-between gap-2">
          <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
            Status
          </p>
          <StatusChip tone={status.tone}>{status.label}</StatusChip>
        </div>
        {detail.stale_reason && (
          <p className="mt-2 rounded bg-surface-warning px-2 py-1 text-[11px] text-text-primary">
            {detail.stale_reason}
          </p>
        )}
        <dl className="mt-3 space-y-2">
          <Field label="Page">{pages}</Field>
          <Field label="Words">
            <span className="tabular-nums">
              {detail.word_count.toLocaleString()}
            </span>
          </Field>
          <Field label="Reviewer">
            {detail.reviewer || (
              <span className="text-text-muted">nobody assigned</span>
            )}
          </Field>
          <Field label="Last changed">
            Version {detail.last_changed_version}
          </Field>
          <Field label="Evidence">
            {detail.sources.length} source
            {detail.sources.length === 1 ? "" : "s"}
          </Field>
        </dl>
      </div>

      {detail.metrics.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
            Metrics in this section
          </p>
          <ul className="mt-2 space-y-1.5">
            {detail.metrics.map((metric) => (
              <li key={metric.id} className="text-[11px]">
                <span className="text-text-secondary">{metric.label}</span>{" "}
                <span className="tabular-nums text-text-primary">
                  {metric.display_value}
                </span>
                {!metric.governed && (
                  <span className="ml-1 text-warning">· suggested</span>
                )}
                <Locator value={metric.source_locator} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {detail.findings.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
            Findings
          </p>
          <ul className="mt-2 space-y-1.5">
            {detail.findings.map((finding) => (
              <li key={finding.id} className="flex items-start gap-1.5">
                <StatusChip tone={severity(finding.severity).tone}>
                  {severity(finding.severity).label}
                </StatusChip>
                <span className="min-w-0 text-[11px] text-text-secondary">
                  {finding.title}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="rounded-lg border border-border bg-surface p-3">
        <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
          Do something about it
        </p>
        <div className="mt-2 flex flex-wrap gap-1.5">
          <SmallButton onClick={onAsk} icon={MessageSquare} disabled={busy}
            testId="playbook-section-ask">
            Ask Claude
          </SmallButton>
          <SmallButton onClick={onUpdate} disabled={busy}
            testId="playbook-section-update">
            Update this section
          </SmallButton>
          <SmallButton onClick={onAssignReviewer} disabled={busy}
            testId="playbook-section-reviewer">
            Assign reviewer
          </SmallButton>
          {/* Only the moves the service would actually allow. */}
          {(detail.allowed ?? []).map((next) => (
            <SmallButton
              key={next}
              onClick={() => onTransition(next)}
              disabled={busy}
              testId={`playbook-section-to-${next}`}
            >
              {sectionStatus(next).label}
            </SmallButton>
          ))}
        </div>
      </div>

      {detail.history.length > 0 && (
        <div className="rounded-lg border border-border bg-surface p-3">
          <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
            What happened to it
          </p>
          <ul className="mt-2 space-y-1.5">
            {[...detail.history].reverse().map((entry, i) => (
              <li key={i} className="text-[11px] leading-relaxed">
                {/* A section entry records the MOVE, not an act name. Reading
                    `act` off it is how this pane once took the page down, so
                    the rule lives in a tested function rather than here. */}
                <span className="text-text-primary">
                  {describeHistoryEntry(entry)}
                </span>
                {entry.actor && (
                  <span className="text-text-muted">
                    {" "}
                    by {actorLabel(entry.actor)}
                  </span>
                )}
                {entry.at && (
                  <span className="text-text-muted">
                    {" · "}
                    {shortDateTime(entry.at)}
                  </span>
                )}
                {entry.reason && (
                  <span className="block text-text-muted">{entry.reason}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
