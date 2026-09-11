"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { AgentActivity } from "@/components/planner/agent-activity";
import { ImportPanel } from "@/components/planner/import-panel";
import {
  AddTask,
  AddWorkstream,
  EditMilestone,
  EditProject,
  EditRaid,
  EditTask,
  ManageDependencies,
  ManagePeople,
} from "@/components/planner/manage";
import { UpdateRequests } from "@/components/planner/requests";
import { Timeline } from "@/components/planner/timeline";
import {
  Due,
  Empty,
  FindingList,
  HealthPill,
  Progress,
  SectionCard,
  StatementLine,
  TaskLine,
  when,
} from "@/components/planner/parts";
import { QuickUpdate } from "@/components/planner/quick-update";
import { AddMilestone, RaiseRaid } from "@/components/planner/raise-forms";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/input";
import {
  api,
  type PlannerFinding,
  type PlannerHealth,
  type PlannerMilestone,
  type PlannerProjectDetail,
  type PlannerRaidItem,
  type PlannerTaskRow,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { shortDate } from "@/lib/planner-format";
import { cn } from "@/lib/utils";

/**
 * One delivery project, in full.
 *
 * Everything here is populated from what was entered when the project was
 * created. There is no second copy and nothing to re-enter: publishing wrote
 * the plan into ordinary planner rows, and these tabs read those rows.
 *
 * The tab order is the order somebody asks: is it all right (Overview), what
 * is the work (Plan), when does it land (Timeline), what dates are we judged
 * on (Milestones), what could go wrong (RAID), who is on it (People), what
 * has been said (Updates), and what has the agent actually done (Agent
 * activity).
 *
 * §16. The Copilot tab is gone. It was a chat box that could answer some
 * questions about this project and refuse others, and it competed with every
 * tab beside it. The one part of it worth keeping — a grounded read of where
 * the project stands — is now a panel on Overview, where it is read rather
 * than talked to.
 */
const TABS = [
  { id: "overview", label: "Overview" },
  { id: "plan", label: "Plan" },
  { id: "timeline", label: "Timeline" },
  { id: "milestones", label: "Milestones" },
  { id: "raid", label: "RAID" },
  { id: "people", label: "People" },
  { id: "updates", label: "Updates" },
  { id: "agent", label: "Agent activity" },
];

export default function DeliveryProjectPage() {
  const params = useParams<{ id: string }>();
  const projectId = Number(params.id);
  const [tab, setTab] = React.useState("overview");
  const [open, setOpen] = React.useState<PlannerTaskRow | null>(null);
  /** Which row is being edited, by kind and id. One at a time, deliberately. */
  const [editing, setEditing] = React.useState<string | null>(null);
  const directory = useAsync(() => api.users(), []);
  const people = React.useMemo(
    () => (directory.data?.users ?? []).filter((p) => p.is_active),
    [directory.data]);

  const detail = useAsync(() => api.planner.project(projectId), [projectId]);
  const brief = useAsync(
    () => api.planner.brief(projectId),
    [projectId],
    { enabled: tab === "overview" },
  );
  const activity = useAsync(
    () => api.planner.activity(projectId, 100),
    [projectId],
    { enabled: tab === "updates" },
  );

  if (detail.loading) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 py-6 text-sm text-text-muted">
        Reading the project…
      </div>
    );
  }
  if (detail.error || !detail.data) {
    return (
      <div className="mx-auto w-full max-w-5xl px-6 py-6">
        <p className="rounded-lg border border-border bg-surface px-4 py-6 text-sm text-negative">
          {detail.error ??
            "That project could not be read. It may not exist, or you may not be on it."}
        </p>
        <Link href="/delivery" className="mt-3 inline-block text-sm text-accent">
          Back to the portfolio
        </Link>
      </div>
    );
  }

  const { project, access, findings, workstreams, tasks, milestones, raid,
          participants, dependencies } = detail.data;
  const mayEdit = ["EDITOR", "OWNER"].includes(access.access);
  const openTasks = tasks.filter(
    (t) => !["COMPLETED", "CANCELLED"].includes(t.status));

  // Health as it should be READ: what somebody set by hand if they set it,
  // and otherwise what the rules calculate. "UNKNOWN" is a storage state,
  // not an answer to "is this project all right?".
  const shownHealth = (project.health_overridden || project.health !== "UNKNOWN"
    ? project.health
    : (project.calculated_health || project.health)) as typeof project.health;
  const shownReason = project.health_overridden || project.health !== "UNKNOWN"
    ? project.health_reason
    : (project.calculated_health_reason || project.health_reason);

  return (
    <div className="mx-auto w-full max-w-5xl px-6 py-6">
      <PageHeader
        title={project.name}
        eyebrow={`Project Planner · ${project.code}`}
        description={project.objective || undefined}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button asChild variant="outline" size="sm">
              <a href={api.planner.exportUrl(projectId)}>Export plan</a>
            </Button>
            <Link href="/delivery" className="text-sm text-accent hover:underline">
              All projects
            </Link>
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 rounded-lg border border-border bg-surface px-4 py-3">
        <div className="flex items-center gap-2">
          {/*
            The stored health is UNKNOWN until the first sweep runs, and a
            project published five minutes ago showed a grey UNKNOWN pill
            beside its own sentence saying the calculation was GREEN. The
            calculated value is the honest answer when nobody has overridden
            it; the override case is called out underneath, as before.
          */}
          <HealthPill health={shownHealth}
                      reason={shownReason}
                      overridden={project.health_overridden} />
          <span className="text-sm text-text-secondary">{shownReason}</span>
        </div>
        <Progress percent={project.percent_complete} />
        <span className="text-xs text-text-muted">
          {project.status.replace(/_/g, " ").toLowerCase()}
        </span>
        {project.target_end_date && (
          <span className="text-xs text-text-muted">
            Target {shortDate(project.target_end_date)}
          </span>
        )}
        <span className="text-xs text-text-muted">
          {project.manager?.name ?? "No manager"}
        </span>
        <Badge variant="outline">{access.access.toLowerCase()} access</Badge>
      </div>

      {project.health_overridden && (
        <p className="mt-2 rounded-md border border-warning bg-warning-muted px-3 py-2 text-xs text-warning">
          Health is reported by hand as {project.health}
          {project.manual_health_by ? ` by ${project.manual_health_by.name}` : ""}
          . The calculation says {project.calculated_health}:{" "}
          {project.calculated_health_reason}
        </p>
      )}

      <Tabs tabs={TABS} active={tab} onChange={setTab} className="mt-6" />

      <div className="mt-4 flex flex-col gap-4">
        {tab === "overview" && (
          <>
            <ExecutiveSummary project={project} tasks={tasks}
                              milestones={milestones} raid={raid}
                              findings={findings} health={shownHealth} />

            <SectionCard title="What needs somebody">
              <FindingList findings={findings} />
            </SectionCard>

            <ProjectBrief brief={brief} />

            {/*
              §11. The policy the person approved when they created this
              project, read back to them in the same words. It was settled at
              creation and then invisible from the day after — so nobody
              could answer "why has the agent not chased this?" without
              reading the database.
            */}
            <SectionCard title="How the Agentic AI works on this project">
              <div className="px-4 py-3">
                <p className="text-sm font-medium text-text-primary">
                  {project.agentic.label}
                </p>
                <p className="mt-1 text-sm text-text-secondary">
                  {project.agentic.sentence}
                </p>
                <p className="mt-2 text-xs text-text-muted">
                  Escalates to{" "}
                  {project.escalation?.name ?? "nobody — it stops at the "
                    + "project manager"}
                  {project.owner?.name ? ` · owned by ${project.owner.name}` : ""}
                </p>
              </div>
            </SectionCard>
            {mayEdit && (
              <SectionCard title="Project settings">
                <EditProject detail={detail.data!} people={people}
                             onSaved={() => detail.reload()} />
                <p className="px-4 py-2 text-xs text-text-muted">
                  Dates, cadence and the chase window all feed rules: they
                  decide what counts as late and when somebody hears about it.
                </p>
              </SectionCard>
            )}
            <Chases projectId={projectId} mayChase={mayEdit} />
            <UpdateRequests projectId={projectId}
                            title="Who we have asked, and who has replied" />
            <SectionCard title="Workstreams">
              {workstreams.length === 0 ? (
                <Empty>No workstreams yet.</Empty>
              ) : (
                <ul className="divide-y divide-border">
                  {workstreams.map((ws) => (
                    <li key={ws.id}
                        className="flex items-center gap-3 px-4 py-2.5">
                      <div className="min-w-0 flex-1">
                        <span className="font-mono text-[11px] text-text-muted">
                          {ws.code}
                        </span>
                        <span className="ml-2 text-sm text-text-primary">
                          {ws.name}
                        </span>
                        <p className="text-xs text-text-muted">
                          {ws.lead?.name ?? "No lead"} · {ws.task_count}{" "}
                          {ws.task_count === 1 ? "task" : "tasks"}
                        </p>
                      </div>
                      <Progress percent={ws.percent_complete} />
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
            {project.business_context && (
              <SectionCard title="Why the bank is doing it">
                <p className="px-4 py-3 text-sm text-text-secondary">
                  {project.business_context}
                </p>
              </SectionCard>
            )}
          </>
        )}

        {tab === "plan" && (
          <>
            <SectionCard
              title={`Open tasks (${openTasks.length})`}
              action={
                <span className="text-xs text-text-muted">
                  {mayEdit
                    ? "Click a task to update it."
                    : "Click a task you own to update it."}
                </span>
              }
            >
              {mayEdit && (
                <>
                  <AddWorkstream projectId={projectId} people={people}
                                 onSaved={() => detail.reload()} />
                  <AddTask detail={detail.data!} people={people}
                           onSaved={() => detail.reload()} />
                </>
              )}
              {openTasks.length === 0 ? (
                <Empty>Every task on this project is closed.</Empty>
              ) : (
                openTasks.map((task) => (
                  <div key={task.id}>
                    <div className="flex items-center">
                      <div className="min-w-0 flex-1">
                        <TaskLine task={task} onOpen={setOpen} />
                      </div>
                      {mayEdit && (
                        <Button
                          size="sm" variant="ghost" className="mr-3 shrink-0"
                          onClick={() => setEditing(
                            editing === `task-${task.id}`
                              ? null : `task-${task.id}`)}>
                          {editing === `task-${task.id}` ? "Close" : "Edit"}
                        </Button>
                      )}
                    </div>
                    {editing === `task-${task.id}` && (
                      <div className="px-4 pb-3">
                        <EditTask detail={detail.data!} task={task}
                                  people={people}
                                  onSaved={() => detail.reload()}
                                  onClose={() => setEditing(null)} />
                      </div>
                    )}
                  </div>
                ))
              )}
            </SectionCard>
            <SectionCard title={`Dependencies (${dependencies.length})`}>
              {mayEdit ? (
                <ManageDependencies detail={detail.data!}
                                    onSaved={() => detail.reload()} />
              ) : dependencies.length === 0 ? (
                <Empty>Nothing is linked to anything yet.</Empty>
              ) : (
                <ul className="divide-y divide-border">
                  {dependencies.map((d) => (
                    <li key={d.id}
                        className="flex items-center gap-2 px-4 py-2 text-sm">
                      <span className="font-mono text-xs text-text-primary">
                        {d.predecessor_code}
                      </span>
                      <Badge variant="outline">{d.dependency_type}</Badge>
                      <span className="font-mono text-xs text-text-primary">
                        {d.successor_code}
                      </span>
                      {d.lag_days !== 0 && (
                        <span className="text-xs text-text-muted">
                          {d.lag_days > 0 ? "+" : ""}
                          {d.lag_days} days
                        </span>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
            {mayEdit && (
              <ImportPanel projectId={projectId}
                           onApplied={() => detail.reload()} />
            )}
          </>
        )}

        {tab === "timeline" && (
          <Timeline projectId={projectId} detail={detail.data!}
                    mayEdit={mayEdit} />
        )}

        {tab === "milestones" && (
          <SectionCard title={`Milestones (${milestones.length})`}>
            {mayEdit && (
              <AddMilestone projectId={projectId}
                            onAdded={() => detail.reload()} />
            )}
            {milestones.length === 0 ? (
              <Empty>No milestones set. Nothing is being judged by a date.</Empty>
            ) : (
              <ul className="divide-y divide-border">
                {milestones.map((m) => (
                  <li key={m.id} className="flex items-center gap-3 px-4 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[11px] text-text-muted">
                          {m.code}
                        </span>
                        <span className="text-sm text-text-primary">{m.name}</span>
                        {m.critical && <Badge variant="outline">critical</Badge>}
                      </div>
                      <p className="text-xs text-text-muted">
                        {m.owner?.name ?? "No owner"}
                      </p>
                    </div>
                    <Badge
                      variant={
                        m.status === "ACHIEVED"
                          ? "positive"
                          : m.status === "MISSED"
                            ? "negative"
                            : "default"
                      }
                    >
                      {m.status.toLowerCase()}
                    </Badge>
                    <span className="w-40 text-right text-xs">
                      <Due date={m.target_date} />
                    </span>
                    {mayEdit && (
                      <Button size="sm" variant="ghost"
                              onClick={() => setEditing(
                                editing === `ms-${m.id}` ? null : `ms-${m.id}`)}>
                        {editing === `ms-${m.id}` ? "Close" : "Edit"}
                      </Button>
                    )}
                    {editing === `ms-${m.id}` && (
                      <div className="basis-full pt-2">
                        <EditMilestone milestone={m} people={people}
                                       onSaved={() => detail.reload()}
                                       onClose={() => setEditing(null)} />
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        )}

        {tab === "raid" && (
          <SectionCard title={`Risks, assumptions, issues and decisions (${raid.length})`}>
            {/* CONTRIBUTOR, not EDITOR. Noticing a problem is not the same as
                having authority over the plan, and a product where only
                editors may raise risks is one where risks go unraised. */}
            {access.access !== "VIEWER" && (
              <RaiseRaid projectId={projectId}
                         onRaised={() => detail.reload()} />
            )}
            {raid.length === 0 ? (
              <Empty>Nothing has been raised on this project.</Empty>
            ) : (
              <ul className="divide-y divide-border">
                {raid.map((r) => (
                  <li key={r.id} className="px-4 py-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[11px] text-text-muted">
                        {r.code}
                      </span>
                      <Badge variant="outline">{r.type.toLowerCase()}</Badge>
                      <Badge
                        variant={
                          r.severity === "CRITICAL" || r.severity === "HIGH"
                            ? "negative"
                            : r.severity === "MEDIUM"
                              ? "warning"
                              : "default"
                        }
                      >
                        {r.severity.toLowerCase()}
                      </Badge>
                      <span className="text-sm text-text-primary">{r.title}</span>
                      <span className="ml-auto text-xs text-text-muted">
                        {r.status.toLowerCase()} · {r.owner?.name ?? "no owner"}
                      </span>
                      {mayEdit && (
                        <Button size="sm" variant="ghost"
                                onClick={() => setEditing(
                                  editing === `raid-${r.id}`
                                    ? null : `raid-${r.id}`)}>
                          {editing === `raid-${r.id}` ? "Close" : "Edit"}
                        </Button>
                      )}
                    </div>
                    {editing === `raid-${r.id}` && (
                      <div className="mt-2">
                        <EditRaid item={r} people={people}
                                  onSaved={() => detail.reload()}
                                  onClose={() => setEditing(null)} />
                      </div>
                    )}
                    {r.description && (
                      <p className="mt-1 text-sm text-text-secondary">
                        {r.description}
                      </p>
                    )}
                    {r.mitigation && (
                      <p className="mt-1 text-xs text-text-muted">
                        Action: {r.mitigation}
                      </p>
                    )}
                    {r.resolution && (
                      <p className="mt-1 text-xs text-positive">
                        Resolved: {r.resolution}
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        )}

        {tab === "people" && (
          <SectionCard title={`People (${participants.length})`}>
            {mayEdit ? (
              <ManagePeople detail={detail.data!} people={people}
                            onSaved={() => detail.reload()} />
            ) : (
              <ul className="divide-y divide-border">
                {participants.map((p) => (
                  <li key={p.id}
                      className="flex items-center gap-3 px-4 py-2.5 text-sm">
                    <span className="min-w-0 flex-1 truncate text-text-primary">
                      {p.user?.name ?? "Unknown"}
                      {p.user?.job_title && (
                        <span className="ml-2 text-xs text-text-muted">
                          {p.user.job_title}
                        </span>
                      )}
                    </span>
                    <Badge variant="outline">
                      {p.project_role.replace(/_/g, " ").toLowerCase()}
                    </Badge>
                    <Badge variant="default">{p.access.toLowerCase()}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </SectionCard>
        )}

        {tab === "updates" && (
          <>
            <PostUpdate projectId={projectId}
                        onPosted={() => activity.reload()} />
            <SectionCard title="What has been said">
              {activity.loading && <Empty>Reading the history…</Empty>}
              {activity.data && activity.data.items.length === 0 && (
                <Empty>Nothing has been recorded on this project yet.</Empty>
              )}
              {activity.data && (
                <ul className="divide-y divide-border">
                  {activity.data.items.map((row) => (
                    <li key={row.id} className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-2 text-xs text-text-muted">
                        <span className="text-text-secondary">
                          {row.author?.name ?? "CreditProbe"}
                        </span>
                        <span>{when(row.at)}</span>
                        {row.entity_code && (
                          <span className="font-mono">{row.entity_code}</span>
                        )}
                        <Badge variant="outline">{row.action}</Badge>
                        {row.source !== "UI" && (
                          <Badge variant="default">
                            {row.source.replace(/_/g, " ").toLowerCase()}
                          </Badge>
                        )}
                      </div>
                      {row.narrative && (
                        <p className="mt-1 text-sm text-text-primary">
                          {row.narrative}
                        </p>
                      )}
                      {(row.old_status || row.new_status) &&
                        row.old_status !== row.new_status && (
                          <p className="mt-0.5 text-xs text-text-muted">
                            {row.old_status || "—"} → {row.new_status || "—"}
                          </p>
                        )}
                      {row.old_percent !== null &&
                        row.new_percent !== null &&
                        row.old_percent !== row.new_percent && (
                          <p className="mt-0.5 text-xs text-text-muted">
                            {row.old_percent}% → {row.new_percent}%
                          </p>
                        )}
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          </>
        )}

        {tab === "agent" && (
          <AgentActivity projectId={projectId} mayRun={mayEdit} />
        )}
      </div>

      {open && (
        <QuickUpdate
          task={open}
          onClose={() => setOpen(null)}
          onSaved={() => {
            setOpen(null);
            detail.reload();
          }}
        />
      )}
    </div>
  );
}

/**
 * §22. What remained of the assistant: a read of where this stands.
 *
 * Grounded — every statement is computed from the plan and carries the rows
 * it came from — and read-only. It cannot be asked a question, so it can
 * never answer "I did not follow that", which is what made the chat box a
 * liability on a page somebody opened to find out whether the project is all
 * right.
 */
/**
 * What a sponsor needs in the first thirty seconds.
 *
 * Opening a project used to mean reading three paragraphs of narrative to
 * find out whether anything was late. The narrative is still underneath —
 * it explains WHY — but the facts a senior reader scans for are now a grid
 * at the top: is it healthy, how far along, who runs it, when is it due,
 * what is next, what is late, what is stuck, what is coming, and what has
 * been raised. Every number here is counted from the project's own rows;
 * nothing is asked of a model.
 */
function ExecutiveSummary({
  project,
  tasks,
  milestones,
  raid,
  findings,
  health,
}: {
  project: PlannerProjectDetail["project"];
  tasks: PlannerTaskRow[];
  milestones: PlannerMilestone[];
  raid: PlannerRaidItem[];
  findings: PlannerFinding[];
  health: PlannerHealth;
}) {
  const open = tasks.filter(
    (t) => !["COMPLETED", "CANCELLED"].includes(t.status));
  const overdue = open.filter((t) => (t.days_overdue ?? 0) > 0).length;
  const blocked = open.filter((t) => t.blocked || t.status === "BLOCKED").length;
  const dueSoon = open.filter(
    (t) => (t.days_overdue ?? 0) <= 0
      && (t.days_until_due ?? 99) <= 7).length;
  const onPath = findings.filter(
    (f) => f.rule === "dependency" || f.rule === "milestone").length;
  const raidOpen = raid.filter(
    (r) => !["CLOSED", "RESOLVED"].includes(String(r.status).toUpperCase())
      && ["HIGH", "CRITICAL"].includes(String(r.severity).toUpperCase())).length;

  const next = milestones
    .filter((m) => !["COMPLETE", "COMPLETED", "CANCELLED"]
      .includes(String(m.status).toUpperCase()) && m.target_date)
    .sort((a, b) => String(a.target_date).localeCompare(String(b.target_date)))[0];

  // The clock is read ONCE, when this panel first mounts, rather than on
  // every render: a component that asks what time it is while rendering
  // gives a different answer each time React happens to re-run it.
  const [now] = React.useState(() => Date.now());
  const daysToNext = next?.target_date
    ? Math.round((new Date(next.target_date).getTime() - now) / 86_400_000)
    : null;

  const cells: { label: string; value: React.ReactNode; tone?: string }[] = [
    { label: "Health", value: health, tone: health === "RED" ? "text-negative"
      : health === "AMBER" ? "text-warning"
        : health === "GREEN" ? "text-positive" : "text-text-muted" },
    { label: "Progress", value: `${Math.round(project.percent_complete)}%` },
    { label: "Status",
      value: project.status.replace(/_/g, " ").toLowerCase() },
    { label: "Project manager", value: project.manager?.name ?? "—" },
    { label: "Sponsor", value: project.sponsor?.name ?? "—" },
    { label: "Owner", value: project.owner?.name ?? "—" },
    { label: "Start", value: shortDate(project.start_date) },
    { label: "Target completion", value: shortDate(project.target_end_date) },
    { label: "Next milestone",
      value: next ? `${next.code} ${next.name}` : "None set" },
    { label: "Days to it",
      value: daysToNext === null ? "—"
        : daysToNext < 0 ? `${Math.abs(daysToNext)} late` : `${daysToNext}`,
      tone: daysToNext !== null && daysToNext < 0 ? "text-negative" : "" },
    { label: "Overdue tasks", value: overdue,
      tone: overdue ? "text-negative" : "text-text-muted" },
    { label: "Blocked tasks", value: blocked,
      tone: blocked ? "text-warning" : "text-text-muted" },
    { label: "Due within 7 days", value: dueSoon },
    { label: "Critical-path risks", value: onPath,
      tone: onPath ? "text-negative" : "text-text-muted" },
    { label: "Open high RAID", value: raidOpen,
      tone: raidOpen ? "text-warning" : "text-text-muted" },
    { label: "Last updated", value: when(project.updated_at) },
  ];

  return (
    <SectionCard title="Where this project is">
      <dl className="grid grid-cols-2 gap-x-4 gap-y-3 px-4 py-3 sm:grid-cols-4">
        {cells.map((cell) => (
          <div key={cell.label}>
            <dt className="text-[11px] uppercase tracking-wide text-text-muted">
              {cell.label}
            </dt>
            <dd className={cn("mt-0.5 text-sm font-medium",
                              cell.tone || "text-text-primary")}>
              {cell.value}
            </dd>
          </div>
        ))}
      </dl>
    </SectionCard>
  );
}

function ProjectBrief({
  brief,
}: {
  brief: ReturnType<typeof useAsync<Awaited<ReturnType<typeof api.planner.brief>>>>;
}) {
  return (
    <SectionCard
      title="Where this project stands"
      action={brief.data ? <Badge variant="outline">{brief.data.as_of}</Badge> : null}
    >
      {brief.loading && <Empty>Reading the project…</Empty>}
      {brief.error && (
        <p className="px-4 py-4 text-sm text-negative">{brief.error}</p>
      )}
      {brief.data && (
        <div className="px-4 py-3">
          <p className="text-sm font-medium text-text-primary">
            {brief.data.headline}
          </p>
          <ul className="mt-2 divide-y divide-border">
            {brief.data.statements.map((statement, index) => (
              <StatementLine key={index} statement={statement} />
            ))}
          </ul>
          {brief.data.open_questions.length > 0 && (
            <div className="mt-4 rounded-md border border-border bg-surface-sunken px-3 py-2">
              <p className="text-xs font-medium uppercase tracking-wide text-text-muted">
                Open questions
              </p>
              <ul className="mt-1 space-y-1">
                {brief.data.open_questions.map((question, index) => (
                  <li key={index} className="text-sm text-text-secondary">
                    {question}
                  </li>
                ))}
              </ul>
            </div>
          )}
          <p className="mt-3 border-t border-border pt-2 text-[11px] text-text-muted">
            {brief.data.grounding}
          </p>
        </div>
      )}
    </SectionCard>
  );
}


/**
 * Who to ask for an update, and the words to use.
 *
 * The deterministic rules decide who is on this list and why; the draft is
 * composed from those rules. Nothing is sent from here and nothing on the
 * project changes — the person doing the chasing owns the act of chasing,
 * which is exactly the line §4 draws.
 */
function Chases({
  projectId,
  mayChase,
}: {
  projectId: number;
  mayChase: boolean;
}) {
  const chases = useAsync(() => api.planner.chases(projectId), [projectId],
                          { enabled: mayChase });
  const [copied, setCopied] = React.useState<number | null>(null);
  if (!mayChase) return null;
  const drafts = chases.data?.drafts ?? [];
  if (chases.loading || drafts.length === 0) return null;

  return (
    <SectionCard
      title={`Who owes an update (${drafts.length})`}
      action={<span className="text-xs text-text-muted">Drafts. Nothing is sent.</span>}
    >
      <ul className="divide-y divide-border">
        {drafts.map((draft) => (
          <li key={draft.task_id} className="px-4 py-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[11px] text-text-muted">
                {draft.task_code}
              </span>
              <span className="text-sm text-text-primary">
                {"name" in (draft.to ?? {})
                  ? (draft.to as { name: string }).name
                  : "the owner"}
              </span>
              <Badge variant="outline">
                {draft.trigger.replace(/_/g, " ")}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                className="ml-auto"
                onClick={() => {
                  void navigator.clipboard?.writeText(draft.body);
                  setCopied(draft.task_id);
                }}
              >
                {copied === draft.task_id ? "Copied" : "Copy the message"}
              </Button>
            </div>
            <p className="mt-1 text-sm text-text-secondary">{draft.why}</p>
          </li>
        ))}
      </ul>
    </SectionCard>
  );
}


/** A note on the project, with nothing else changed. */
function PostUpdate({
  projectId,
  onPosted,
}: {
  projectId: number;
  onPosted: () => void;
}) {
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function post() {
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.planner.postUpdate(projectId, { narrative: text.trim() });
      setText("");
      onPosted();
    } catch (e) {
      setError(e instanceof Error ? e.message : "That could not be posted.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard title="Say something">
      <div className="px-4 py-3">
        <Textarea
          rows={2}
          value={text}
          placeholder="Weekly report: PD on track, LGD at risk on the valuation policy, no change to the end date."
          onChange={(e) => setText(e.target.value)}
        />
        {error && <p className="mt-1 text-sm text-negative">{error}</p>}
        <div className="mt-2 flex justify-end">
          <Button size="sm" onClick={post} disabled={busy || !text.trim()}>
            {busy ? "Posting…" : "Post update"}
          </Button>
        </div>
      </div>
    </SectionCard>
  );
}
