"use client";

import * as React from "react";
import { MessageSquare, Share2 } from "lucide-react";

import { Field, StatusChip } from "@/components/playbook/status/chips";
import { SmallButton } from "@/components/playbook/status/pack-tab";
import type { PbAction, PbFinding, PbGovernedDecision } from "@/lib/api";
import {
  actionStatus,
  actorLabel,
  decisionStatus,
  isOverdue,
  orderActions,
  orderDecisions,
  shortDate,
  shortDateTime,
} from "@/lib/intelligence";

/**
 * Decisions and the actions that follow them. §14.
 *
 * Two rules shape this tab and both are in the specification.
 *
 * **A decision is recorded by a person.** Claude may draft the question, the
 * options and a recommendation; recording what the committee decided requires
 * a human actor, a time, an outcome and a rationale, and the service refuses
 * anything else. RECORD THE DECISION opens a form that collects exactly those.
 *
 * **Actions follow a decision that has been taken.** The button to create them
 * appears only on a decision that has been recorded, because actions
 * belonging to a decision nobody made are how a pack ends up describing work
 * that was never authorised.
 */
export function DecisionsTab({
  decisions,
  actions,
  findings,
  busy,
  error,
  onAsk,
  onMoveDecision,
  onRecord,
  onCreateActions,
  onMoveAction,
  onUpdateAction,
  onExportAction,
}: {
  decisions: { total: number; outstanding: number; decided: number;
    items: PbGovernedDecision[] };
  actions: { total: number; open: number; completed: number; overdue: number;
    items: PbAction[] };
  findings: PbFinding[];
  busy: number;
  error: string;
  onAsk: (decisionId: number) => void;
  onMoveDecision: (decision: PbGovernedDecision, status: string) => void;
  onRecord: (decision: PbGovernedDecision) => void;
  onCreateActions: (decision: PbGovernedDecision) => void;
  onMoveAction: (action: PbAction, status: string) => void;
  onUpdateAction: (action: PbAction) => void;
  onExportAction: (action: PbAction) => void;
}) {
  const ordered = orderDecisions(decisions.items);
  const byId = new Map(findings.map((f) => [f.id, f]));

  return (
    <div className="space-y-6" data-testid="playbook-decisions-tab">
      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-text-primary">
            Decisions the committee is asked to make
          </h2>
          <p className="text-[11px] text-text-muted">
            {decisions.outstanding} outstanding · {decisions.decided} recorded
          </p>
        </div>

        {error && (
          <p className="rounded-md border border-negative/40 bg-negative-muted p-3 text-sm text-negative"
            data-testid="playbook-decisions-error">
            {error}
          </p>
        )}

        {ordered.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
            Nothing is being put to the committee in this pack.
          </p>
        ) : (
          <ul className="space-y-3">
            {ordered.map((decision) => (
              <DecisionCard
                key={decision.id}
                decision={decision}
                related={(decision.related_finding_ids ?? [])
                  .map((id) => byId.get(id))
                  .filter((f): f is PbFinding => Boolean(f))}
                busy={busy === decision.id}
                onAsk={() => onAsk(decision.id)}
                onMove={(status) => onMoveDecision(decision, status)}
                onRecord={() => onRecord(decision)}
                onCreateActions={() => onCreateActions(decision)}
              />
            ))}
          </ul>
        )}
      </section>

      <section className="space-y-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-semibold text-text-primary">Actions</h2>
          <p className="text-[11px] text-text-muted">
            {actions.open} open
            {actions.overdue > 0 && (
              <span className="ml-1 font-semibold text-negative">
                · {actions.overdue} overdue
              </span>
            )}
          </p>
        </div>

        {actions.items.length === 0 ? (
          <p className="rounded-lg border border-border bg-surface p-4 text-sm text-text-muted">
            No actions have been raised.
          </p>
        ) : (
          <ul className="space-y-2">
            {orderActions(actions.items).map((action) => (
              <ActionRow
                key={action.id}
                action={action}
                busy={busy === action.id}
                onMove={(status) => onMoveAction(action, status)}
                onUpdate={() => onUpdateAction(action)}
                onExport={() => onExportAction(action)}
              />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function DecisionCard({
  decision,
  related,
  busy,
  onAsk,
  onMove,
  onRecord,
  onCreateActions,
}: {
  decision: PbGovernedDecision;
  related: PbFinding[];
  busy: boolean;
  onAsk: () => void;
  onMove: (status: string) => void;
  onRecord: () => void;
  onCreateActions: () => void;
}) {
  const status = decisionStatus(decision.status);
  const decided = decision.status === "decided";

  return (
    <li className="rounded-lg border border-border bg-surface"
      data-testid="playbook-decision-card">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b border-border px-4 py-2.5">
        <div className="min-w-0">
          <p className="text-[11px] font-medium uppercase tracking-wide text-text-muted">
            Decision {decision.reference}
          </p>
          <h3 className="mt-0.5 text-sm font-semibold text-text-primary">
            {decision.question}
          </h3>
        </div>
        <StatusChip tone={status.tone}>{status.label}</StatusChip>
      </div>

      <div className="space-y-3 px-4 py-3">
        {decision.recommendation && (
          <div>
            <p className="text-[10px] font-medium uppercase tracking-wide text-text-muted">
              Recommendation
            </p>
            <p className="mt-0.5 text-sm leading-relaxed text-text-secondary">
              {decision.recommendation}
            </p>
          </div>
        )}

        <div className="grid gap-x-6 gap-y-2 sm:grid-cols-2 lg:grid-cols-4">
          {decision.current_position && (
            <Field label="Current position">{decision.current_position}</Field>
          )}
          {decision.proposed_position && (
            <Field label="Proposed">{decision.proposed_position}</Field>
          )}
          {decision.reporting_period && (
            <Field label="Period">{decision.reporting_period}</Field>
          )}
          {decision.options?.length > 0 && (
            <Field label="Options">
              <span className="text-xs">
                {decision.options
                  .map((o) => o[0].toUpperCase() + o.slice(1))
                  .join(" · ")}
              </span>
            </Field>
          )}
        </div>

        {related.length > 0 && (
          <p className="text-[11px] text-text-muted">
            Related finding
            {related.length === 1 ? "" : "s"}:{" "}
            {related.map((f) => f.reference || f.title).join(", ")}
          </p>
        )}

        {decided && (
          <div className="rounded-md border border-positive/40 bg-positive-muted p-3">
            <p className="text-xs font-semibold text-positive">
              Decided: {decision.outcome.toUpperCase()}
            </p>
            {decision.rationale && (
              <p className="mt-1 text-sm leading-relaxed text-text-primary">
                {decision.rationale}
              </p>
            )}
            <p className="mt-1.5 text-[11px] text-text-muted">
              Recorded by {actorLabel(decision.decided_by)}
              {decision.decided_at &&
                ` · ${shortDateTime(decision.decided_at)}`}
              {decision.meeting && ` · ${decision.meeting}`}
            </p>
          </div>
        )}
      </div>

      <div className="flex flex-wrap gap-1.5 border-t border-border px-4 py-2.5">
        <SmallButton onClick={onAsk} icon={MessageSquare} disabled={busy}
          testId="playbook-decision-ask">
          Draft committee recommendation
        </SmallButton>
        {decision.status === "proposed" && (
          <SmallButton onClick={() => onMove("ready_for_decision")}
            disabled={busy} testId="playbook-decision-ready">
            Mark ready for decision
          </SmallButton>
        )}
        {!decided && decision.status !== "withdrawn" && (
          <SmallButton onClick={onRecord} disabled={busy}
            testId="playbook-decision-record">
            Record the decision
          </SmallButton>
        )}
        {!decided && decision.status === "ready_for_decision" && (
          <SmallButton onClick={() => onMove("deferred")} disabled={busy}
            testId="playbook-decision-defer">
            Defer
          </SmallButton>
        )}
        {/* Actions follow a decision that has been taken. Offering the button
            earlier would offer work nobody authorised. */}
        {decided && (
          <SmallButton onClick={onCreateActions} disabled={busy}
            testId="playbook-decision-actions">
            Add an action
          </SmallButton>
        )}
      </div>
    </li>
  );
}

function ActionRow({
  action,
  busy,
  onMove,
  onUpdate,
  onExport,
}: {
  action: PbAction;
  busy: boolean;
  onMove: (status: string) => void;
  onUpdate: () => void;
  onExport: () => void;
}) {
  const status = actionStatus(action.status);
  const overdue = isOverdue(action);

  return (
    <li className="rounded-lg border border-border bg-surface px-4 py-3"
      data-testid="playbook-action-row">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-text-primary">
            {action.reference && (
              <span className="mr-2 text-text-muted">{action.reference}</span>
            )}
            {action.title}
          </p>
          {action.description && (
            <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
              {action.description}
            </p>
          )}
        </div>
        <div className="flex items-center gap-1.5">
          {overdue && <StatusChip tone="red">Overdue</StatusChip>}
          <StatusChip tone={status.tone}>{status.label}</StatusChip>
        </div>
      </div>

      <div className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-[11px] text-text-muted">
        <span>Owner: {action.owner || "unassigned"}</span>
        <span>
          Due: {action.due_date ? shortDate(action.due_date) : "no date"}
        </span>
        {action.decision_id && <span>From decision</span>}
        {action.external_ref && (
          <span>
            {action.external_system || "external"} {action.external_ref}
            {action.external_status && ` · says ${action.external_status}`}
          </span>
        )}
        {action.completed_by && (
          <span>Completed by {actorLabel(action.completed_by)}</span>
        )}
      </div>

      {action.last_update && (
        <p className="mt-1.5 rounded bg-surface-sunken px-2 py-1 text-[11px] text-text-secondary">
          {action.last_update}
        </p>
      )}

      <div className="mt-2 flex flex-wrap gap-1.5">
        {action.status === "open" && (
          <SmallButton onClick={() => onMove("in_progress")} disabled={busy}
            testId="playbook-action-start">
            Start
          </SmallButton>
        )}
        {["open", "in_progress"].includes(action.status) && (
          <>
            <SmallButton onClick={() => onMove("blocked")} disabled={busy}
              testId="playbook-action-block">
              Blocked
            </SmallButton>
            <SmallButton onClick={() => onMove("completed")} disabled={busy}
              testId="playbook-action-complete">
              Complete
            </SmallButton>
          </>
        )}
        {action.status === "blocked" && (
          <SmallButton onClick={() => onMove("in_progress")} disabled={busy}
            testId="playbook-action-unblock">
            Unblock
          </SmallButton>
        )}
        <SmallButton onClick={onUpdate} disabled={busy}
          testId="playbook-action-update">
          Add an update
        </SmallButton>
        <SmallButton onClick={onExport} icon={Share2} disabled={busy}
          testId="playbook-action-export">
          Hand to a planner
        </SmallButton>
      </div>
    </li>
  );
}
