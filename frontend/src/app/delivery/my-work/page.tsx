"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { QuickUpdate } from "@/components/planner/quick-update";
import { SectionCard, Stat, TaskLine } from "@/components/planner/parts";
import type { PlannerTaskRow } from "@/lib/api";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * My work — one person's own commitments, across every project.
 *
 * Not a filtered portfolio. The portfolio answers "what is happening"; this
 * answers "what do I have to do today", which is a different question with a
 * different reader and a different order.
 *
 * The buckets come from the backend and each task appears in exactly one of
 * them. That is deliberate: a task that is overdue AND blocked appearing
 * twice makes a list of nine items look like a list of eleven, and the first
 * thing somebody does with a list they distrust is stop reading it.
 */
const BUCKETS: { key: string; title: string; note: string }[] = [
  { key: "overdue", title: "Overdue", note: "Past the date you agreed." },
  { key: "today", title: "Due today", note: "" },
  { key: "week", title: "Due this week", note: "" },
  { key: "blocked", title: "Blocked", note: "Waiting on somebody else." },
  {
    key: "needs_update",
    title: "Needs an update",
    note: "Coming up, and nobody has said how it is going.",
  },
  { key: "later", title: "Later", note: "" },
];

export default function MyWorkPage() {
  const work = useAsync(() => api.planner.myWork(30), []);
  const [open, setOpen] = React.useState<PlannerTaskRow | null>(null);

  const counts = work.data?.counts ?? {};
  const buckets = work.data?.buckets ?? {};
  const nothing =
    work.data && Object.values(buckets).every((list) => list.length === 0);

  return (
    <div className="mx-auto w-full max-w-4xl px-6 py-6">
      <PageHeader
        title="My work"
        description="Every task you own across every delivery project, in the order it needs you."
        eyebrow="Project Planner"
        actions={
          <Link href="/delivery" className="text-sm text-accent hover:underline">
            All projects
          </Link>
        }
      />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Overdue" value={counts.overdue ?? 0}
              tone={counts.overdue ? "negative" : undefined} />
        <Stat label="Due today" value={counts.today ?? 0}
              tone={counts.today ? "warning" : undefined} />
        <Stat label="This week" value={counts.week ?? 0} />
        <Stat label="Blocked" value={counts.blocked ?? 0}
              tone={counts.blocked ? "warning" : undefined} />
      </div>

      {work.loading && (
        <p className="mt-6 text-sm text-text-muted">Reading your work…</p>
      )}
      {work.error && <p className="mt-6 text-sm text-negative">{work.error}</p>}
      {nothing && (
        <p className="mt-6 rounded-lg border border-border bg-surface px-4 py-6 text-sm text-text-muted">
          Nothing is assigned to you on any delivery project. If that seems
          wrong, ask the project manager to add you as a task owner.
        </p>
      )}

      <div className="mt-6 flex flex-col gap-4">
        {BUCKETS.map(({ key, title, note }) => {
          const list = buckets[key] ?? [];
          if (list.length === 0) return null;
          return (
            <SectionCard
              key={key}
              title={`${title} (${list.length})`}
              action={
                note ? (
                  <span className="text-xs text-text-muted">{note}</span>
                ) : null
              }
            >
              {list.map((task) => (
                <TaskLine key={task.id} task={task} showProject
                          onOpen={setOpen} />
              ))}
            </SectionCard>
          );
        })}
      </div>

      {open && (
        <QuickUpdate
          task={open}
          onClose={() => setOpen(null)}
          onSaved={() => {
            setOpen(null);
            work.reload();
          }}
        />
      )}
    </div>
  );
}
