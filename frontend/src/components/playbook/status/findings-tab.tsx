"use client";

import * as React from "react";
import { MessageSquare, Paperclip, UserPlus } from "lucide-react";

import { Field, Locator, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import type { PbFinding } from "@/lib/api";
import {
  actorLabel,
  findingStatus,
  orderFindings,
  severity,
  shortDateTime,
} from "@/lib/intelligence";

/**
 * Findings. §13.
 *
 * The governance boundary is enforced here as well as in the service, not
 * because the UI is trusted to enforce it — it is not, and the service
 * refuses regardless — but because a button that looks available and then
 * fails is worse than no button. **Claude may draft an answer. Only a person
 * may accept, close or defer**, and the card says so where it matters.
 *
 * A blocking High finding that nobody has answered stops the pack being
 * ready for approval. That is computed by the backend; this shows it.
 */

const SEVERITIES = ["high", "medium", "low", "information"] as const;
const STATUSES = ["open", "answered", "accepted", "closed", "deferred"] as const;

export function FindingsTab({
  findings,
  busy,
  error,
  onAsk,
  onAnswer,
  onMove,
  onAssign,
  onAttachEvidence,
  onSetBlocking,
}: {
  findings: { total: number; open: number; blocking: number;
    by_severity: Record<string, number>; items: PbFinding[] };
  busy: number;
  error: string;
  onAsk: (findingId: number) => void;
  onAnswer: (finding: PbFinding) => void;
  onMove: (finding: PbFinding, status: string) => void;
  onAssign: (finding: PbFinding) => void;
  onAttachEvidence: (finding: PbFinding) => void;
  onSetBlocking: (finding: PbFinding, blocking: boolean) => void;
}) {
  const [severityFilter, setSeverityFilter] = React.useState("");
  const [statusFilter, setStatusFilter] = React.useState("");
  const [blockingOnly, setBlockingOnly] = React.useState(false);

  const shown = orderFindings(
    findings.items.filter(
      (f) =>
        (!severityFilter || f.severity === severityFilter) &&
        (!statusFilter || f.status === statusFilter) &&
        (!blockingOnly || f.blocking),
    ),
  );

  return (
    <div className="space-y-4" data-testid="playbook-findings-tab">
      <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface p-3">
        <p className="text-sm text-text-secondary">
          <span className="font-semibold text-text-primary">
            {findings.open}
          </span>{" "}
          open of {findings.total}
          {findings.blocking > 0 && (
            <>
              {" · "}
              <span className="font-semibold text-negative">
                {findings.blocking} blocking approval
              </span>
            </>
          )}
        </p>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <Select
            label="Severity"
            value={severityFilter}
            onChange={setSeverityFilter}
            options={SEVERITIES.map((s) => ({ value: s,
              label: severity(s).label }))}
            testId="playbook-filter-severity"
          />
          <Select
            label="Status"
            value={statusFilter}
            onChange={setStatusFilter}
            options={STATUSES.map((s) => ({ value: s,
              label: findingStatus(s).label }))}
            testId="playbook-filter-status"
          />
          <label className="flex items-center gap-1.5 text-[11px] text-text-secondary">
            <input
              type="checkbox"
              checked={blockingOnly}
              onChange={(e) => setBlockingOnly(e.target.checked)}
              data-testid="playbook-filter-blocking"
              className="size-3.5 accent-[var(--ipm-accent)]"
            />
            Blocking only
          </label>
        </div>
      </div>

      {error && (
        <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative"
          data-testid="playbook-findings-error">
          {error}
        </p>
      )}

      {shown.length === 0 ? (
        <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
          {findings.total === 0
            ? "No findings have been raised against this document."
            : "No finding matches these filters."}
        </p>
      ) : (
        <ul className="space-y-3">
          {shown.map((finding) => (
            <FindingCard
              key={finding.id}
              finding={finding}
              busy={busy === finding.id}
              onAsk={() => onAsk(finding.id)}
              onAnswer={() => onAnswer(finding)}
              onMove={(status) => onMove(finding, status)}
              onAssign={() => onAssign(finding)}
              onAttachEvidence={() => onAttachEvidence(finding)}
              onSetBlocking={(blocking) => onSetBlocking(finding, blocking)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingCard({
  finding,
  busy,
  onAsk,
  onAnswer,
  onMove,
  onAssign,
  onAttachEvidence,
  onSetBlocking,
}: {
  finding: PbFinding;
  busy: boolean;
  onAsk: () => void;
  onAnswer: () => void;
  onMove: (status: string) => void;
  onAssign: () => void;
  onAttachEvidence: () => void;
  onSetBlocking: (blocking: boolean) => void;
}) {
  const sev = severity(finding.severity);
  const status = findingStatus(finding.status);

  return (
    <li className="rounded-lg border border-border bg-surface"
      data-testid="playbook-finding-card">
      <div className="flex flex-wrap items-start gap-2 border-b border-border px-4 py-2.5">
        <StatusChip tone={sev.tone}>{sev.label}</StatusChip>
        <StatusChip tone={status.tone}>{status.label}</StatusChip>
        {finding.blocking && (
          <StatusChip tone="red">Blocks approval</StatusChip>
        )}
        <div className="min-w-0 basis-full">
          <h3 className="text-sm font-semibold text-text-primary">
            {finding.reference && (
              <span className="mr-2 text-text-muted">{finding.reference}</span>
            )}
            {finding.title}
          </h3>
        </div>
      </div>

      <div className="space-y-3 px-4 py-3">
        {finding.rationale && (
          <p className="text-sm leading-relaxed text-text-secondary">
            {finding.rationale}
          </p>
        )}

        <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
          {finding.previous_value && (
            <Field label="Previous">
              <span className="tabular-nums">{finding.previous_value}</span>
            </Field>
          )}
          {finding.current_value && (
            <Field label="Current">
              <span className="tabular-nums">{finding.current_value}</span>
            </Field>
          )}
          {finding.delta && (
            <Field label="Change">
              <span className="tabular-nums">{finding.delta}</span>
            </Field>
          )}
          {finding.threshold && (
            <Field label="Trigger">
              <span className="tabular-nums">{finding.threshold}</span>
            </Field>
          )}
          <Field label="Origin">
            {/* §27: where a finding came from is always visible. An AI
                suggestion and a threshold rule carry different weight. */}
            <span className="text-xs">{finding.origin_label}</span>
          </Field>
          <Field label="Owner">
            <span className="text-xs">
              {finding.owner || (
                <span className="text-text-muted">nobody yet</span>
              )}
            </span>
          </Field>
        </div>

        {finding.metric_id && (
          <p className="text-[11px] text-text-muted">
            Metric <Locator value={finding.metric_id} />
          </p>
        )}

        {finding.answer && (
          <div className="rounded-md border border-border bg-surface-sunken p-3">
            <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
              Answer
            </p>
            <p className="mt-1 text-sm leading-relaxed text-text-primary">
              {finding.answer}
            </p>
            <p className="mt-1.5 text-[11px] text-text-muted">
              {finding.answered_by
                ? `Answered by ${actorLabel(finding.answered_by)}`
                : "Drafted — nobody has stood behind this yet"}
              {finding.answered_at && ` · ${shortDateTime(finding.answered_at)}`}
            </p>
          </div>
        )}

        {finding.resolution && (
          <p className="text-[11px] text-text-muted">
            {findingStatus(finding.status).label} by{" "}
            {actorLabel(finding.resolved_by) || "—"}
            {finding.resolved_at && ` · ${shortDateTime(finding.resolved_at)}`}
            {" · "}
            {finding.resolution}
          </p>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 border-t border-border px-4 py-2.5">
        <SmallButton onClick={onAnswer} disabled={busy}
          testId="playbook-finding-answer">
          Answer
        </SmallButton>
        <SmallButton onClick={onAsk} icon={MessageSquare} disabled={busy}
          testId="playbook-finding-ask">
          Ask Claude
        </SmallButton>
        <SmallButton onClick={onAttachEvidence} icon={Paperclip} disabled={busy}
          testId="playbook-finding-evidence">
          Attach evidence
        </SmallButton>
        <SmallButton onClick={onAssign} icon={UserPlus} disabled={busy}
          testId="playbook-finding-assign">
          Assign owner
        </SmallButton>
        <span className="mx-1 w-px self-stretch bg-border" aria-hidden />
        {/* Accepting, closing and deferring are a person's acts. The service
            refuses an unnamed caller; these are the same three acts, offered
            to somebody who is signed in. */}
        <SmallButton onClick={() => onMove("accepted")} disabled={busy}
          testId="playbook-finding-accept">
          Accept
        </SmallButton>
        <SmallButton onClick={() => onMove("closed")} disabled={busy}
          testId="playbook-finding-close">
          Close
        </SmallButton>
        <SmallButton onClick={() => onMove("deferred")} disabled={busy}
          testId="playbook-finding-defer">
          Defer
        </SmallButton>
        <SmallButton
          onClick={() => onSetBlocking(!finding.blocking)}
          disabled={busy}
          testId="playbook-finding-blocking"
        >
          {finding.blocking ? "Stop blocking" : "Make blocking"}
        </SmallButton>
      </div>
    </li>
  );
}

export function Select({
  label,
  value,
  onChange,
  options,
  testId,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  testId?: string;
}) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        data-testid={testId}
        className="rounded border border-border bg-surface px-1.5 py-1 text-[11px] text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}
