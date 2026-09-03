"use client";

import * as React from "react";

import { Empty, SectionCard } from "@/components/planner/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select } from "@/components/ui/input";
import { api, type PlannerProjectDetail, type PlannerScheduleNode,
         type PlannerSlip } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * When everything happens, and what determines the end date.
 *
 * Two things on one tab because they are two views of one fact. The bars show
 * the plan as it is laid out; the schedule beneath them shows what the
 * dependency network actually implies. A project manager reads the first and
 * then asks the second.
 *
 * Drawn in CSS rather than with a charting library. A Gantt is a row of
 * absolutely positioned divs over a shared date axis; pulling in a
 * hundred-kilobyte dependency to draw rectangles would be a maintenance cost
 * with no user in it. What it does not do is drag-to-reschedule — moving a
 * date by dragging is a change to a commitment, and this product asks people
 * to make those deliberately.
 *
 * Every bar is also a table row, always, not as a fallback. A bar chart that
 * a screen reader cannot read is a bar chart half the bank cannot read.
 */

const DAY = 86_400_000;

type Span = {
  key: string;
  code: string;
  name: string;
  kind: "workstream" | "task" | "milestone";
  start: Date | null;
  end: Date | null;
  percent: number;
  status: string;
  overdue: boolean;
  complete: boolean;
  critical: boolean;
  owner: string;
};

function parse(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(`${value}T00:00:00Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

function spansOf(detail: PlannerProjectDetail, today: number): Span[] {
  const out: Span[] = [];

  for (const ws of detail.workstreams) {
    out.push({
      key: `ws-${ws.id}`, code: ws.code, name: ws.name, kind: "workstream",
      start: parse(ws.start_date), end: parse(ws.target_end_date),
      percent: ws.percent_complete, status: ws.status ?? "",
      overdue: false, complete: false, critical: false,
      owner: ws.lead?.name ?? "",
    });
  }
  for (const task of detail.tasks) {
    const end = parse(task.due_date);
    const done = ["COMPLETED", "CANCELLED"].includes(task.status);
    out.push({
      key: `t-${task.id}`, code: task.code, name: task.title, kind: "task",
      start: parse(task.start_date), end,
      percent: task.percent_complete, status: task.status,
      overdue: !done && end !== null && end.getTime() < today,
      complete: done, critical: Boolean(task.critical),
      owner: task.owner?.name ?? "",
    });
  }
  for (const stone of detail.milestones) {
    const end = parse(stone.target_date);
    const done = ["ACHIEVED", "CANCELLED"].includes(stone.status);
    out.push({
      key: `m-${stone.id}`, code: stone.code, name: stone.name,
      kind: "milestone", start: end, end,
      percent: done ? 100 : 0, status: stone.status,
      overdue: !done && end !== null && end.getTime() < today,
      complete: done, critical: Boolean(stone.critical),
      owner: stone.owner?.name ?? "",
    });
  }
  return out;
}

export function Timeline({
  projectId,
  detail,
  mayEdit,
}: {
  projectId: number;
  detail: PlannerProjectDetail;
  mayEdit: boolean;
}) {
  const schedule = useAsync(() => api.planner.schedule(projectId), [projectId]);
  // Read once, at mount. A "today" that moved mid-render would put the marker
  // and the overdue flags at two different instants, and a marker that crept
  // across the chart while somebody read it would be worse than one that is a
  // few hours old.
  const [today] = React.useState(() => Date.now());
  const spans = React.useMemo(() => spansOf(detail, today), [detail, today]);
  const dated = spans.filter((s) => s.end !== null);

  const bounds = React.useMemo(() => {
    const stamps: number[] = [];
    for (const span of dated) {
      if (span.start) stamps.push(span.start.getTime());
      if (span.end) stamps.push(span.end.getTime());
    }
    const project = parse(detail.project.start_date);
    const target = parse(detail.project.target_end_date);
    if (project) stamps.push(project.getTime());
    if (target) stamps.push(target.getTime());
    if (stamps.length === 0) return null;
    const from = Math.min(...stamps);
    const to = Math.max(...stamps);
    // A single-day project would divide by zero and a two-day one would draw
    // bars wider than the page. One week is the narrowest useful axis.
    const span = Math.max(to - from, 7 * DAY);
    return { from, to: from + span, span };
  }, [dated, detail.project.start_date, detail.project.target_end_date]);

  return (
    <>
      <SectionCard
        title="Timeline"
        action={
          <span className="text-xs text-text-muted">
            {bounds
              ? `${new Date(bounds.from).toISOString().slice(0, 10)} — ` +
                `${new Date(bounds.to).toISOString().slice(0, 10)}`
              : ""}
          </span>
        }
      >
        {!bounds ? (
          <Empty>
            Nothing on this project carries a date yet, so there is no timeline
            to draw. Give the tasks start and due dates.
          </Empty>
        ) : (
          <div className="overflow-x-auto px-4 py-3">
            <div className="min-w-[640px]">
              <Axis bounds={bounds} today={today} />
              <ul>
                {dated.map((span) => (
                  <Bar key={span.key} span={span} bounds={bounds} />
                ))}
              </ul>
            </div>
          </div>
        )}
      </SectionCard>

      <SectionCard title="Everything with a date">
        {dated.length === 0 ? (
          <Empty>Nothing has a date yet.</Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
                  <th className="px-4 py-2">Code</th>
                  <th className="px-4 py-2">What</th>
                  <th className="px-4 py-2">Owner</th>
                  <th className="px-4 py-2">Starts</th>
                  <th className="px-4 py-2">Due</th>
                  <th className="px-4 py-2 text-right">Done</th>
                  <th className="px-4 py-2">State</th>
                </tr>
              </thead>
              <tbody>
                {dated.map((span) => (
                  <tr key={span.key} className="border-b border-border last:border-0">
                    <td className="px-4 py-2 font-mono text-xs text-text-muted">
                      {span.code}
                    </td>
                    <td className="px-4 py-2 text-text-primary">
                      {span.name}
                      {span.kind === "milestone" && (
                        <Badge variant="outline" className="ml-2">milestone</Badge>
                      )}
                    </td>
                    <td className="px-4 py-2 text-text-secondary">
                      {span.owner || "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-text-secondary">
                      {span.start ? span.start.toISOString().slice(0, 10) : "—"}
                    </td>
                    <td className="px-4 py-2 text-xs text-text-secondary">
                      {span.end ? span.end.toISOString().slice(0, 10) : "—"}
                    </td>
                    <td className="px-4 py-2 text-right text-xs text-text-secondary">
                      {span.percent}%
                    </td>
                    <td className="px-4 py-2 text-xs">
                      {span.complete ? (
                        <span className="text-positive">done</span>
                      ) : span.overdue ? (
                        <span className="text-negative">overdue</span>
                      ) : (
                        <span className="text-text-muted">
                          {span.status.replace(/_/g, " ").toLowerCase()}
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <CriticalPath projectId={projectId} schedule={schedule} mayEdit={mayEdit} />
    </>
  );
}

function Axis({
  bounds,
  today,
}: {
  bounds: { from: number; to: number; span: number };
  today: number;
}) {
  const ticks: { at: number; label: string }[] = [];
  const first = new Date(bounds.from);
  const cursor = new Date(Date.UTC(first.getUTCFullYear(), first.getUTCMonth(), 1));
  while (cursor.getTime() <= bounds.to) {
    if (cursor.getTime() >= bounds.from) {
      ticks.push({
        at: ((cursor.getTime() - bounds.from) / bounds.span) * 100,
        label: cursor.toLocaleDateString(undefined, { month: "short" }),
      });
    }
    cursor.setUTCMonth(cursor.getUTCMonth() + 1);
  }
  const nowAt = today >= bounds.from && today <= bounds.to
    ? ((today - bounds.from) / bounds.span) * 100
    : null;

  return (
    <div className="relative mb-2 h-5 border-b border-border">
      {ticks.map((tick) => (
        <span key={tick.at}
              className="absolute top-0 text-[10px] uppercase tracking-wide text-text-muted"
              style={{ left: `${tick.at}%` }}>
          {tick.label}
        </span>
      ))}
      {nowAt !== null && (
        <span className="absolute bottom-0 top-0 w-px bg-accent"
              style={{ left: `${nowAt}%` }}
              aria-hidden />
      )}
    </div>
  );
}

function Bar({
  span,
  bounds,
}: {
  span: Span;
  bounds: { from: number; to: number; span: number };
}) {
  const end = span.end!.getTime();
  const start = span.start ? span.start.getTime() : end;
  const left = ((Math.max(start, bounds.from) - bounds.from) / bounds.span) * 100;
  const width = Math.max(
    ((Math.min(end, bounds.to) - Math.max(start, bounds.from)) / bounds.span) * 100,
    0.6);

  const tone = span.complete
    ? "bg-positive/50"
    : span.overdue
      ? "bg-negative/60"
      : span.kind === "workstream"
        ? "bg-accent/25"
        : "bg-accent/50";

  return (
    <li className="relative flex h-6 items-center">
      <span className="w-32 shrink-0 truncate pr-2 font-mono text-[11px] text-text-muted">
        {span.code}
      </span>
      <span className="relative h-3 flex-1 rounded bg-surface-sunken">
        {span.kind === "milestone" ? (
          <span
            className={`absolute top-1/2 h-2.5 w-2.5 -translate-y-1/2 rotate-45 ${
              span.complete ? "bg-positive" : span.overdue ? "bg-negative" : "bg-accent"}`}
            style={{ left: `${left}%` }}
            title={`${span.code} ${span.name}`}
          />
        ) : (
          <span className={`absolute top-0 h-3 rounded ${tone}`}
                style={{ left: `${left}%`, width: `${width}%` }}
                title={`${span.code} ${span.name} — ${span.percent}%`} />
        )}
      </span>
      <span className="w-10 shrink-0 pl-2 text-right text-[11px] text-text-muted">
        {span.kind === "milestone" ? "" : `${span.percent}%`}
      </span>
    </li>
  );
}

/**
 * The calculated schedule, and the honest refusal when there is not one.
 *
 * The two "critical" concepts are shown as separate columns and the rows where
 * they disagree are called out, because that disagreement is the useful thing
 * on this panel: a task somebody marked critical that has three weeks of float
 * is a task the plan and the team disagree about.
 */
function CriticalPath({
  projectId,
  schedule,
  mayEdit,
}: {
  projectId: number;
  schedule: ReturnType<typeof useAsync<import("@/lib/api").PlannerSchedule>>;
  mayEdit: boolean;
}) {
  const [code, setCode] = React.useState("");
  const [days, setDays] = React.useState("2");
  const [slip, setSlip] = React.useState<PlannerSlip | null>(null);
  const [asking, setAsking] = React.useState(false);

  if (schedule.loading) {
    return (
      <SectionCard title="Critical path">
        <p className="px-4 py-3 text-sm text-text-muted">Calculating…</p>
      </SectionCard>
    );
  }
  const found = schedule.data;
  if (!found) {
    return (
      <SectionCard title="Critical path">
        <Empty>{schedule.error ?? "The schedule could not be read."}</Empty>
      </SectionCard>
    );
  }

  if (!found.computed) {
    return (
      <SectionCard title="Critical path">
        <div className="px-4 py-3">
          <p className="text-sm font-medium text-text-primary">
            The critical path cannot be calculated.
          </p>
          {found.cannot_because.map((why, i) => (
            <p key={i} className="mt-2 text-sm text-text-secondary">{why}</p>
          ))}
        </div>
      </SectionCard>
    );
  }

  async function ask() {
    if (!code) return;
    setAsking(true);
    try {
      setSlip(await api.planner.slip(projectId, code, Number(days) || 1));
    } finally {
      setAsking(false);
    }
  }

  const path = new Set(found.critical_path);
  const nodes = found.nodes;

  return (
    <SectionCard
      title="Critical path"
      action={
        <span className="text-xs text-text-muted">
          finishes {found.project_finish ?? "—"} · calendar days
        </span>
      }
    >
      <div className="border-b border-border px-4 py-2 text-xs text-text-secondary">
        <span className="font-medium text-text-primary">
          {found.critical_path.join(" → ")}
        </span>
        {found.marked_not_calculated.length > 0 && (
          <p className="mt-1">
            Marked critical but carrying float:{" "}
            {found.marked_not_calculated.join(", ")}.
          </p>
        )}
        {found.calculated_not_marked.length > 0 && (
          <p className="mt-1">
            On the path but not marked critical:{" "}
            {found.calculated_not_marked.join(", ")}.
          </p>
        )}
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
              <th className="px-4 py-2">Code</th>
              <th className="px-4 py-2">Earliest</th>
              <th className="px-4 py-2">Latest</th>
              <th className="px-4 py-2 text-right">Float</th>
              <th className="px-4 py-2">Calculated</th>
              <th className="px-4 py-2">Marked</th>
            </tr>
          </thead>
          <tbody>
            {nodes.map((node: PlannerScheduleNode) => (
              <tr key={`${node.kind}-${node.id}`}
                  className={`border-b border-border last:border-0 ${
                    path.has(node.code) ? "bg-surface-sunken" : ""}`}>
                <td className="px-4 py-2 font-mono text-xs text-text-muted">
                  {node.code}
                </td>
                <td className="px-4 py-2 text-xs text-text-secondary">
                  {node.early_start} → {node.early_finish}
                </td>
                <td className="px-4 py-2 text-xs text-text-secondary">
                  {node.late_start} → {node.late_finish}
                </td>
                <td className="px-4 py-2 text-right text-xs">
                  {node.total_float_days} d
                </td>
                <td className="px-4 py-2 text-xs">
                  {node.calculated_critical ? (
                    <Badge variant="warning">on the path</Badge>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
                <td className="px-4 py-2 text-xs">
                  {node.marked_critical ? (
                    <Badge variant={node.disagrees ? "negative" : "default"}>
                      marked
                    </Badge>
                  ) : (
                    <span className="text-text-muted">—</span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {mayEdit && (
        <div className="border-t border-border px-4 py-3">
          <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
            If this slips
          </p>
          <div className="mt-2 flex flex-wrap items-end gap-3">
            <div className="w-48">
              <Label>Task</Label>
              <Select value={code} onChange={(e) => setCode(e.target.value)}>
                <option value="">Choose one</option>
                {nodes.map((n: PlannerScheduleNode) => (
                  <option key={n.code} value={n.code}>{n.code}</option>
                ))}
              </Select>
            </div>
            <div className="w-24">
              <Label>Days</Label>
              <Input type="number" min={1} max={365} value={days}
                     onChange={(e) => setDays(e.target.value)} />
            </div>
            <Button size="sm" variant="outline" disabled={!code || asking}
                    onClick={ask}>
              {asking ? "Working it out…" : "Work it out"}
            </Button>
          </div>

          {slip && slip.computed && (
            <div className="mt-3 rounded-md border border-border px-3 py-2 text-sm">
              {slip.absorbed ? (
                <p className="text-text-secondary">
                  Nothing moves. {slip.code} has enough float to absorb{" "}
                  {slip.days} {slip.days === 1 ? "day" : "days"}.
                </p>
              ) : (
                <>
                  <p className="text-text-primary">
                    The project finishes {slip.finish_moves_by}{" "}
                    {slip.finish_moves_by === 1 ? "day" : "days"} later —{" "}
                    {slip.project_finish_before} becomes{" "}
                    {slip.project_finish_after}.
                  </p>
                  <ul className="mt-2 space-y-1">
                    {(slip.moved ?? []).map((m) => (
                      <li key={m.code} className="text-xs text-text-secondary">
                        <span className="font-mono">{m.code}</span> {m.name} —{" "}
                        {m.was} becomes {m.now} ({m.days > 0 ? "+" : ""}
                        {m.days} d)
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
          {slip && !slip.computed && (
            <p className="mt-3 text-sm text-text-secondary">
              {(slip.cannot_because ?? []).join(" ")}
            </p>
          )}
        </div>
      )}
    </SectionCard>
  );
}
