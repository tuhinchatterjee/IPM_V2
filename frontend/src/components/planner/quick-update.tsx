"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { ApiError, api, type PlannerTaskRow } from "@/lib/api";

/**
 * The quick update — where a person says how a task is going.
 *
 * This is the single most-used control in the product, so it is deliberately
 * small: status, a percentage, a sentence, and whether it is blocked. Owner
 * and dates are NOT here, because moving the date you are measured against is
 * not an update on progress — it is a change to a commitment, it needs editor
 * access, and the backend refuses it from a contributor anyway. Putting the
 * field on this form would only produce a 403 the person cannot act on.
 *
 * `expected_version` is sent with every save. Two people updating the same
 * task from two screens is not hypothetical, and without it the second save
 * silently discards the first. With it, the second person is told.
 */
const STATUSES = [
  "NOT_STARTED",
  "IN_PROGRESS",
  "BLOCKED",
  "IN_REVIEW",
  "COMPLETED",
  "CANCELLED",
];

export function QuickUpdate({
  task,
  onClose,
  onSaved,
}: {
  task: PlannerTaskRow;
  onClose: () => void;
  onSaved: (updated: PlannerTaskRow) => void;
}) {
  const [status, setStatus] = React.useState(task.status);
  const [percent, setPercent] = React.useState(String(task.percent_complete));
  const [narrative, setNarrative] = React.useState("");
  const [blocked, setBlocked] = React.useState(task.blocked);
  const [reason, setReason] = React.useState(task.blocker_reason ?? "");
  const [next, setNext] = React.useState(task.next_step ?? "");
  const [saving, setSaving] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [stale, setStale] = React.useState(false);

  async function save() {
    setSaving(true);
    setError(null);
    setStale(false);
    try {
      const result = await api.planner.updateTask(task.id, {
        status,
        percent_complete: Number(percent),
        narrative,
        blocked,
        blocker_reason: reason,
        next_step: next,
        expected_version: task.version,
      });
      onSaved(result.task);
    } catch (e) {
      if (e instanceof ApiError) {
        // 409 is not a failure of the person's input — somebody else got
        // there first. It reads differently and it needs a different action,
        // so it says so rather than showing the same red box as a bad value.
        setStale(e.status === 409);
        setError(e.message);
      } else {
        setError("That could not be saved.");
      }
    } finally {
      setSaving(false);
    }
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/30 p-0 sm:items-center sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-label={`Update ${task.code}`}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="max-h-full w-full max-w-lg overflow-y-auto rounded-t-lg border border-border bg-surface shadow-lg sm:rounded-lg">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-3">
          <div className="min-w-0">
            <p className="font-mono text-[11px] text-text-muted">
              {task.code} · {task.project_code}
            </p>
            <h2 className="truncate text-sm font-semibold text-text-primary">
              {task.title}
            </h2>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Close
          </Button>
        </header>

        <div className="flex flex-col gap-4 px-5 py-4">
          {task.due_date && (
            <p className="text-xs text-text-muted">
              Due {task.due_date}
              {task.days_overdue
                ? ` — ${task.days_overdue} days overdue`
                : ""}
              . To change the date, ask the project manager: reporting progress
              and moving a commitment are different things.
            </p>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label htmlFor="qu-status">Status</Label>
              <Select
                id="qu-status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ").toLowerCase()}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label htmlFor="qu-percent">Percent complete</Label>
              <Input
                id="qu-percent"
                type="number"
                min={0}
                max={100}
                value={percent}
                onChange={(e) => setPercent(e.target.value)}
              />
            </div>
          </div>

          <div>
            <Label htmlFor="qu-narrative">What has happened</Label>
            <Textarea
              id="qu-narrative"
              rows={3}
              value={narrative}
              placeholder="Extract written, sampling next. Expect to finish Friday."
              onChange={(e) => setNarrative(e.target.value)}
            />
            <p className="mt-1 text-[11px] text-text-muted">
              This goes on the project&rsquo;s record with your name on it. It
              is what &ldquo;what changed since Friday?&rdquo; reads.
            </p>
          </div>

          <div>
            <label className="flex items-center gap-2 text-sm text-text-primary">
              <input
                type="checkbox"
                checked={blocked}
                onChange={(e) => setBlocked(e.target.checked)}
              />
              This is blocked
            </label>
            {blocked && (
              <div className="mt-2">
                <Label htmlFor="qu-reason">Blocked by</Label>
                <Input
                  id="qu-reason"
                  value={reason}
                  placeholder="Waiting on the updated valuation policy."
                  onChange={(e) => setReason(e.target.value)}
                />
                <p className="mt-1 text-[11px] text-text-muted">
                  Required. &ldquo;Blocked&rdquo; with nothing after it tells
                  the project manager nothing they can act on.
                </p>
              </div>
            )}
          </div>

          <div>
            <Label htmlFor="qu-next">Next step</Label>
            <Input
              id="qu-next"
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </div>

          {error && (
            <div
              className={
                stale
                  ? "rounded-md border border-warning bg-warning-muted px-3 py-2 text-sm text-warning"
                  : "rounded-md border border-negative bg-negative-muted px-3 py-2 text-sm text-negative"
              }
            >
              {error}
              {stale && (
                <Button
                  variant="link"
                  size="sm"
                  className="ml-2"
                  onClick={() => window.location.reload()}
                >
                  Reload
                </Button>
              )}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-between gap-3 border-t border-border px-5 py-3">
          <Badge variant="outline">version {task.version}</Badge>
          <div className="flex gap-2">
            <Button variant="outline" size="sm" onClick={onClose}>
              Cancel
            </Button>
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save update"}
            </Button>
          </div>
        </footer>
      </div>
    </div>
  );
}
