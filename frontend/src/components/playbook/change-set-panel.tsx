"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api, type PbChangeItem, type PbChangeSet } from "@/lib/api";
import {
  decisionSummary,
  dependencyWarnings,
  isOpen,
  withDependencies,
} from "@/lib/playbook";

const STATUS: Record<string, { label: string; variant: "positive" | "default" | "outline" }> = {
  approved: { label: "Approved", variant: "positive" },
  applied: { label: "Applied", variant: "positive" },
  rejected: { label: "Held", variant: "default" },
  superseded: { label: "Superseded", variant: "default" },
  proposed: { label: "Awaiting a decision", variant: "outline" },
};

/**
 * A numbered proposal, and the decision about it.
 *
 * Two things this deliberately does not do. It does not renumber: change 4 is
 * change 4 after a reload, because "hold 4" is an instruction somebody may give
 * an hour later. And it does not resolve a dependency quietly — ticking a
 * change that rests on another ticks that one too and says so, rather than
 * accepting an approval it will silently widen.
 *
 * Chat remains the other way to say the same thing. This panel is not the only
 * route to a partial approval; it is the one that is visible.
 */
export function ChangeSetPanel({
  workspaceId,
  changeSet,
  onDecided,
}: {
  workspaceId: number;
  changeSet: PbChangeSet;
  onDecided: (instruction: string) => void;
}) {
  const open = isOpen(changeSet);
  const [selected, setSelected] = React.useState<string[]>(() =>
    changeSet.items.filter((i) => i.status === "approved").map((i) => i.stable_id),
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const toggle = (item: PbChangeItem) => {
    setSelected((current) =>
      current.includes(item.stable_id)
        ? current.filter(
            (id) =>
              id !== item.stable_id &&
              // Dropping a change drops what could not stand without it.
              !(
                changeSet.items
                  .find((i) => i.stable_id === id)
                  ?.depends_on ?? []
              ).includes(item.stable_id),
          )
        : withDependencies(changeSet.items, [...current, item.stable_id]),
    );
  };

  const warnings = dependencyWarnings(changeSet.items, selected);

  const decide = async () => {
    setBusy(true);
    setError("");
    try {
      const result = await api.decidePlaybookChanges(workspaceId, changeSet.id, {
        approve: selected,
      });
      onDecided(result.instruction);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      className="rounded-lg border border-border bg-surface p-4"
      aria-label="Proposed changes"
      data-testid="playbook-change-set"
    >
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-sm font-semibold text-text-primary">
          Proposed changes
        </h2>
        <span className="text-xs text-text-muted">
          {open
            ? `${selected.length} of ${changeSet.items.length} selected`
            : decisionSummary(
                changeSet.items,
                changeSet.items
                  .filter((i) => i.status === "approved" || i.status === "applied")
                  .map((i) => i.stable_id),
              )}
        </span>
      </div>

      <ol className="space-y-2">
        {changeSet.items.map((item) => {
          const status = STATUS[item.status] ?? STATUS.proposed;
          const checked = selected.includes(item.stable_id);
          return (
            <li key={item.stable_id}>
              <label
                className={`flex gap-3 rounded-md border p-3 ${
                  open
                    ? "cursor-pointer border-border hover:bg-surface-hover"
                    : "border-border"
                }`}
              >
                {open && (
                  <input
                    type="checkbox"
                    className="mt-0.5 size-4 shrink-0 accent-[var(--ipm-accent)]"
                    checked={checked}
                    onChange={() => toggle(item)}
                    aria-label={`Change ${item.number}: ${item.target_section}`}
                  />
                )}
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-text-primary">
                      {item.number}. {item.target_section}
                    </span>
                    {!open && (
                      <Badge variant={status.variant}>{status.label}</Badge>
                    )}
                  </div>
                  <p className="mt-1 text-xs text-text-muted">{item.rationale}</p>
                  {item.depends_on.length > 0 && (
                    <p className="mt-1 text-[11px] text-text-muted">
                      Rests on:{" "}
                      {item.depends_on
                        .map((id) => {
                          const dep = changeSet.items.find(
                            (i) => i.stable_id === id,
                          );
                          return dep ? `change ${dep.number}` : id;
                        })
                        .join(", ")}
                    </p>
                  )}
                </div>
              </label>
            </li>
          );
        })}
      </ol>

      {warnings.length > 0 && (
        <p className="mt-3 rounded-md border border-warning/40 bg-surface-warning p-2 text-xs text-text-primary">
          {warnings
            .map(
              (w) =>
                `Change ${w.number} rests on ${w.requires
                  .map((n) => `change ${n}`)
                  .join(", ")}, which ${
                  w.requires.length === 1 ? "is" : "are"
                } not selected.`,
            )
            .join(" ")}
        </p>
      )}

      {open && (
        <>
          <p className="mt-3 text-xs text-text-secondary">
            {decisionSummary(changeSet.items, selected)}
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <Button
              size="sm"
              onClick={decide}
              disabled={busy || warnings.length > 0}
              data-testid="playbook-apply-selected"
            >
              {busy ? "Recording…" : "Apply selected"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                setSelected(changeSet.items.map((i) => i.stable_id))
              }
              disabled={busy}
            >
              Select all
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => setSelected([])}
              disabled={busy}
            >
              Clear
            </Button>
          </div>
          <p className="mt-2 text-[11px] text-text-muted">
            Recording a decision does not rewrite the document. Send the
            instruction to make the changes.
          </p>
        </>
      )}
      {error && <p className="mt-2 text-xs text-negative">{error}</p>}
    </section>
  );
}
