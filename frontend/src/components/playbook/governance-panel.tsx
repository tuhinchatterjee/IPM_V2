"use client";

import Link from "next/link";
import * as React from "react";

import {
  Empty,
  Problem,
  SectionCard,
  formatDay,
  formatWhen,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import type { PlaybookAction, PlaybookDecision, PlaybookPack } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * What the committee is being asked to decide, and what follows from it.
 *
 * The rule this screen exists to hold: THE PLANNER IS THE EXECUTION SOURCE OF
 * TRUTH. A committee action links to a Planner task and reads its live state
 * every time somebody looks. It does not keep its own copy of the percentage,
 * because two systems each holding a progress field is two systems that will
 * eventually disagree — and the one read out in a meeting is the one on the
 * pack.
 */
export function GovernancePanel({
  pack,
  onChanged,
}: {
  pack: PlaybookPack;
  onChanged: () => void;
}) {
  const decisions = useAsync(
    () => api.playbook.decisions({ pack_id: pack.id }),
    [pack.id, pack.version],
  );
  const actions = useAsync(
    () => api.playbook.actions({ pack_id: pack.id }),
    [pack.id, pack.version],
  );

  return (
    <div className="space-y-4">
      <Unavailable state={decisions} what="the decisions on this pack" />
      <SectionCard
        title="Decisions the committee is asked to make"
        description="An assistant may draft the paper that asks the question. Only a person with approver access records the answer."
      >
        {decisions.loading ? (
          <Empty>Loading…</Empty>
        ) : (decisions.data?.decisions.length ?? 0) === 0 ? (
          <Empty>
            This pack asks the committee for no decisions.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {(decisions.data?.decisions ?? []).map((decision) => (
              <DecisionRow
                key={decision.id}
                decision={decision}
                pack={pack}
                onChanged={() => {
                  decisions.reload();
                  onChanged();
                }}
              />
            ))}
          </ul>
        )}
      </SectionCard>

      <Unavailable state={actions} what="the action log" />
      <SectionCard
        title="Actions"
        description="Governance records here; the work itself lives in the Project Planner and its progress is read from there."
      >
        {actions.loading ? (
          <Empty>Loading…</Empty>
        ) : (actions.data?.actions.length ?? 0) === 0 ? (
          <Empty>Nothing has been actioned off this pack.</Empty>
        ) : (
          <ul className="divide-y divide-border">
            {(actions.data?.actions ?? []).map((action) => (
              <ActionRow
                key={action.id}
                action={action}
                pack={pack}
                onChanged={() => {
                  actions.reload();
                  onChanged();
                }}
              />
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

const OUTCOMES = [
  { value: "APPROVED", label: "Approved" },
  { value: "CONDITIONALLY_APPROVED", label: "Approved with conditions" },
  { value: "REJECTED", label: "Rejected" },
  { value: "WITHDRAWN", label: "Withdrawn" },
];

function DecisionRow({
  decision,
  pack,
  onChanged,
}: {
  decision: PlaybookDecision;
  pack: PlaybookPack;
  onChanged: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [text, setText] = React.useState("");
  const [conditions, setConditions] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  const canDecide = ["APPROVER", "OWNER"].includes(pack.access);

  async function record(outcome: string) {
    setBusy(true);
    setError(null);
    try {
      await api.playbook.decide(decision.id, {
        outcome,
        decision_text: text,
        conditions,
      });
      setOpen(false);
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <li className="px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-muted">
              {decision.reference}
            </code>
            <span className="text-sm font-medium text-text-primary">
              {decision.title}
            </span>
            <Badge variant={decision.decided ? "positive" : "warning"}>
              {decision.status_label}
            </Badge>
            {decision.source === "AI" && !decision.decided && (
              <Badge variant="outline" title="Drafted by the assistant. The committee still decides.">
                drafted
              </Badge>
            )}
          </div>
          {decision.question && (
            <p className="mt-1 text-sm text-text-secondary">
              {decision.question}
            </p>
          )}
          {decision.recommendation && (
            <p className="mt-1 text-xs text-text-muted">
              <span className="font-medium">Recommendation: </span>
              {decision.recommendation}
            </p>
          )}
          {decision.decided && (
            <p className="mt-2 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
              {decision.decision_text || decision.status_label}
              {decision.conditions && (
                <>
                  <br />
                  <span className="font-medium">Conditions: </span>
                  {decision.conditions}
                </>
              )}
              <span className="ml-1 text-text-muted">
                ({formatWhen(decision.decided_at)})
              </span>
            </p>
          )}
        </div>

        {!decision.decided && (
          <Button
            size="sm"
            variant="outline"
            disabled={!canDecide}
            title={
              canDecide
                ? undefined
                : "Recording what a committee decided needs approver access."
            }
            onClick={() => setOpen((was) => !was)}
          >
            {open ? "Cancel" : "Record the decision"}
          </Button>
        )}
      </div>

      {error != null && (
        <div className="mt-2">
          <Problem error={error} />
        </div>
      )}

      {open && (
        <div className="mt-3 space-y-2 rounded-md border border-border bg-surface-sunken p-3">
          <Input
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="What the committee actually decided, in its own words."
          />
          <Input
            value={conditions}
            onChange={(e) => setConditions(e.target.value)}
            placeholder="Conditions, if any."
          />
          <div className="flex flex-wrap gap-2">
            {OUTCOMES.map((outcome) => (
              <Button
                key={outcome.value}
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => record(outcome.value)}
              >
                {outcome.label}
              </Button>
            ))}
          </div>
        </div>
      )}
    </li>
  );
}

function ActionRow({
  action,
  pack,
  onChanged,
}: {
  action: PlaybookAction;
  pack: PlaybookPack;
  onChanged: () => void;
}) {
  const [evidence, setEvidence] = React.useState("");
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      setOpen(false);
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const progress = action.planner;

  return (
    <li className="px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-muted">
              {action.reference}
            </code>
            <Badge variant={action.closed ? "positive" : "default"}>
              {action.status_label}
            </Badge>
            {action.overdue && <Badge variant="negative">overdue</Badge>}
          </div>
          <p className="mt-1 text-sm text-text-secondary">
            {action.description}
          </p>
          <p className="mt-0.5 text-xs text-text-muted">
            Due {formatDay(action.due_date)} · {action.priority.toLowerCase()}{" "}
            priority
          </p>

          {/* Read from the Planner on every request, never copied here. */}
          {progress.linked ? (
            <p className="mt-1.5 text-xs text-text-secondary">
              In the Planner:{" "}
              {progress.project_id ? (
                <Link
                  href={`/delivery/${progress.project_id}`}
                  className="text-accent hover:underline"
                >
                  {progress.task_code || `task ${progress.task_id}`}
                </Link>
              ) : (
                progress.task_code
              )}
              {progress.status && ` · ${progress.status.toLowerCase()}`}
              {typeof progress.percent_complete === "number" &&
                ` · ${progress.percent_complete}% complete`}
            </p>
          ) : progress.was_linked ? (
            <p className="mt-1.5 text-xs text-warning">{progress.note}</p>
          ) : (
            <p className="mt-1.5 text-xs text-text-muted">
              Not sent to the Planner. The work has no owner with a date until
              it is.
            </p>
          )}

          {action.closure_evidence && (
            <p className="mt-2 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
              <span className="font-medium">Closed on: </span>
              {action.closure_evidence}
            </p>
          )}
        </div>

        {!action.closed && pack.editable && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setOpen((was) => !was)}
          >
            {open ? "Cancel" : "Close"}
          </Button>
        )}
      </div>

      {error != null && (
        <div className="mt-2">
          <Problem error={error} />
        </div>
      )}

      {open && (
        <div className="mt-3 space-y-2 rounded-md border border-border bg-surface-sunken p-3">
          <p className="text-[11px] text-text-muted">
            Closing an action asserts the work was done. The evidence is what
            somebody reads when they ask what was done, so it is required.
          </p>
          <Input
            value={evidence}
            onChange={(e) => setEvidence(e.target.value)}
            placeholder="What was done, and where the evidence is."
          />
          <Button
            size="sm"
            disabled={busy || !evidence.trim()}
            onClick={() =>
              run(() => api.playbook.closeAction(action.id, evidence))
            }
          >
            Close the action
          </Button>
        </div>
      )}
    </li>
  );
}
