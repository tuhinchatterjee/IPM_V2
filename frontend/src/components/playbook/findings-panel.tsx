"use client";

import * as React from "react";

import {
  Empty,
  Problem,
  SectionCard,
  Severity,
  formatWhen,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import type { PlaybookFinding, PlaybookPack } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * What the pack raised, and what has been done about it.
 *
 * Findings come from declared materiality rules against governed figures —
 * never from a model deciding something looks important — so every one here
 * shows the rule that fired and the numbers it fired on. That is what makes a
 * finding challengeable rather than an assertion.
 *
 * Dismissal is the one answer that takes something off the committee's list,
 * so it is the one answer that demands a written reason. The reason box is on
 * the screen rather than behind a confirmation dialog, because a dialog
 * teaches people to click through it.
 */
export function FindingsPanel({ pack }: { pack: PlaybookPack }) {
  const findings = useAsync(
    () => api.playbook.findings({ pack_id: pack.id }), [pack.id, pack.version]);
  const rows = findings.data?.findings ?? [];
  const open = rows.filter((f) => !f.answered);

  return (
    <div className="space-y-4">
      <Unavailable state={findings} what="the findings on this pack" />
      <SectionCard
        title="Findings"
        description={
          rows.length === 0
            ? undefined
            : `${open.length} of ${rows.length} still to answer. A serious one left unanswered blocks approval.`
        }
      >
        {findings.loading ? (
          <Empty>Loading…</Empty>
        ) : rows.length === 0 ? (
          <Empty>
            Nothing material has been raised on this pack. Findings appear when
            a declared threshold in the committee&rsquo;s template is crossed
            by a governed figure.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {rows.map((finding) => (
              <FindingRow
                key={finding.id}
                finding={finding}
                editable={pack.editable}
                access={pack.access}
                onChanged={findings.reload}
              />
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

const ANSWERS: { value: string; label: string; hint: string }[] = [
  { value: "ACKNOWLEDGED", label: "Acknowledge",
    hint: "Somebody has seen it and owns it." },
  { value: "EXPLAINED", label: "Explain",
    hint: "There is a management response on the record." },
  { value: "ACTIONED", label: "Actioned",
    hint: "An action was raised, and the action is the answer." },
  { value: "RESOLVED", label: "Resolved",
    hint: "The underlying condition has gone away." },
];

function FindingRow({
  finding,
  editable,
  access,
  onChanged,
}: {
  finding: PlaybookFinding;
  editable: boolean;
  access: string;
  onChanged: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [response, setResponse] = React.useState("");
  const [reason, setReason] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  const canDismiss = ["REVIEWER", "EDITOR", "APPROVER", "OWNER"].includes(
    access);

  async function answer(status: string) {
    setBusy(true);
    setError(null);
    try {
      await api.playbook.respondToFinding(finding.id, {
        status,
        response,
        reason,
        owner_id: null,
      });
      setOpen(false);
      setResponse("");
      setReason("");
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  async function reopen() {
    setBusy(true);
    setError(null);
    try {
      await api.playbook.reopenFinding(
        finding.id,
        reason || "Reopened from the pack for another look.",
      );
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
            <Severity severity={finding.severity} />
            <span className="text-sm font-medium text-text-primary">
              {finding.title}
            </span>
            <Badge variant={finding.answered ? "positive" : "default"}>
              {finding.status.toLowerCase()}
            </Badge>
          </div>

          {finding.description && (
            <p className="mt-1 text-sm text-text-secondary">
              {finding.description}
            </p>
          )}

          {/* The working. Without it, a finding is somebody's opinion. */}
          {finding.factual_basis && (
            <p className="mt-1.5 text-xs text-text-muted">
              {finding.factual_basis}
            </p>
          )}
          {finding.rule_key && (
            <p className="mt-0.5 text-[11px] text-text-muted">
              Raised by the <code className="font-mono">{finding.rule_key}</code>{" "}
              rule
              {finding.figure &&
                ` · ${finding.figure.metric_id} at ${finding.figure.display_value} for ${finding.figure.period}`}
            </p>
          )}

          {finding.response && (
            <p className="mt-2 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
              <span className="font-medium">Response: </span>
              {finding.response}
            </p>
          )}
          {finding.dismissed_reason && (
            <p className="mt-2 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
              <span className="font-medium">Dismissed: </span>
              {finding.dismissed_reason}
              <span className="ml-1 text-text-muted">
                ({formatWhen(finding.dismissed_at)})
              </span>
            </p>
          )}
        </div>

        {editable && (
          <div className="flex shrink-0 gap-2">
            {finding.answered ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy || !canDismiss}
                title={
                  canDismiss
                    ? "Put it back on the list."
                    : "Reopening a finding needs reviewer access."
                }
                onClick={reopen}
              >
                Reopen
              </Button>
            ) : (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setOpen((was) => !was)}
              >
                {open ? "Cancel" : "Answer"}
              </Button>
            )}
          </div>
        )}
      </div>

      {error != null && (
        <div className="mt-2">
          <Problem error={error} />
        </div>
      )}

      {open && editable && (
        <div className="mt-3 space-y-3 rounded-md border border-border bg-surface-sunken p-3">
          <div>
            <label
              className="text-xs font-medium text-text-secondary"
              htmlFor={`response-${finding.id}`}
            >
              Management response
            </label>
            <Input
              id={`response-${finding.id}`}
              value={response}
              onChange={(e) => setResponse(e.target.value)}
              placeholder="What is being done about this, and by whom."
              className="mt-1"
            />
          </div>
          <div className="flex flex-wrap gap-2">
            {ANSWERS.map((option) => (
              <Button
                key={option.value}
                size="sm"
                variant="outline"
                disabled={busy}
                title={option.hint}
                onClick={() => answer(option.value)}
              >
                {option.label}
              </Button>
            ))}
          </div>

          <div className="border-t border-border pt-3">
            <label
              className="text-xs font-medium text-text-secondary"
              htmlFor={`reason-${finding.id}`}
            >
              Dismiss instead — and say why
            </label>
            <p className="mt-0.5 text-[11px] text-text-muted">
              Dismissing takes this off the committee&rsquo;s list. A reader six
              months from now has to be able to see the reason, so it is
              required, and it is recorded against your name.
            </p>
            <Input
              id={`reason-${finding.id}`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Why this is not material."
              className="mt-1.5"
            />
            <Button
              size="sm"
              variant="destructive"
              className="mt-2"
              disabled={busy || !reason.trim() || !canDismiss}
              title={
                canDismiss
                  ? undefined
                  : "Dismissing a finding needs reviewer access."
              }
              onClick={() => answer("DISMISSED")}
            >
              Dismiss
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}
