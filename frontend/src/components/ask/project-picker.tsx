"use client";

import * as React from "react";
import { Check, FolderInput, Plus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { api, type ProjectRow, type Thread } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Put this conversation in a project — or start one around it.
 *
 * A project owns investigations, so this is the one control that changes what
 * an investigation belongs to. It is shared between the investigation header
 * and the per-answer Project action, because both mean the same thing: the
 * conversation this answer is part of should live somewhere.
 *
 * Creating goes through `projectFromThread` rather than "create a project, then
 * move into it". The backend carries the conversation's settled context — the
 * periods already agreed — into the new project's standing context, so a
 * project started from a conversation begins where that conversation got to.
 */

export function ProjectMenu({
  thread,
  projects,
  open,
  onOpenChange,
  onChanged,
  label,
  className,
}: {
  thread: Thread;
  projects: ProjectRow[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged: (thread: Thread) => void;
  /** Overrides the button text. Defaults to the current project's name. */
  label?: string;
  className?: string;
}) {
  const [naming, setNaming] = React.useState(false);
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const current = projects.find((p) => p.id === thread.project_id) ?? null;

  function close() {
    onOpenChange(false);
    setNaming(false);
    setName("");
    setError(null);
  }

  async function run(work: () => Promise<Thread>) {
    setBusy(true);
    setError(null);
    try {
      onChanged(await work());
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  const move = (projectId: number | null) =>
    run(() => api.moveThread(thread.id, projectId));

  const create = () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    return run(async () => {
      const body = await api.projectFromThread(thread.id, { name: trimmed });
      return body.investigation;
    });
  };

  return (
    <div className={cn("relative", className)}>
      <Button
        variant="ghost"
        size="sm"
        onClick={() => (open ? close() : onOpenChange(true))}
        aria-expanded={open}
      >
        <FolderInput aria-hidden />
        {label ?? (current ? current.name : "Add to project")}
      </Button>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-1 w-72 rounded-lg border border-border bg-surface py-1 shadow-lg">
          <p className="meta px-3 pb-1 pt-1.5 text-text-muted">Projects</p>

          <div className="max-h-64 overflow-y-auto">
            {projects.map((p) => (
              <button
                key={p.id}
                type="button"
                disabled={busy}
                onClick={() => move(p.id)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-primary hover:bg-surface-hover disabled:opacity-50"
              >
                {p.id === thread.project_id ? (
                  <Check className="size-3.5 shrink-0 text-accent" aria-hidden />
                ) : (
                  <span className="size-3.5 shrink-0" />
                )}
                <span className="truncate">{p.name}</span>
              </button>
            ))}
            {projects.length === 0 && (
              <p className="px-3 py-2 text-xs text-text-muted">
                No projects yet — name one below.
              </p>
            )}
          </div>

          {thread.project_id !== null && (
            <button
              type="button"
              disabled={busy}
              onClick={() => move(null)}
              className="w-full border-t border-border px-3 py-2 text-left text-sm text-text-muted hover:bg-surface-hover disabled:opacity-50"
            >
              Remove from project
            </button>
          )}

          <div className="border-t border-border">
            {naming ? (
              <div className="flex items-center gap-1.5 px-2 py-2">
                <input
                  autoFocus
                  value={name}
                  disabled={busy}
                  placeholder="New project name"
                  onChange={(e) => setName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void create();
                    if (e.key === "Escape") setNaming(false);
                  }}
                  className="min-w-0 flex-1 rounded-md border border-border bg-canvas px-2 py-1.5 text-sm text-text-primary focus:border-accent focus:outline-none"
                  aria-label="New project name"
                />
                <Button size="sm" onClick={() => void create()} disabled={busy}>
                  Create
                </Button>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => setNaming(true)}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm text-text-primary hover:bg-surface-hover"
              >
                <Plus className="size-3.5 shrink-0 text-accent" aria-hidden />
                New project…
              </button>
            )}
          </div>

          {error && <p className="px-3 pb-2 text-xs text-negative">{error}</p>}
        </div>
      )}
    </div>
  );
}
