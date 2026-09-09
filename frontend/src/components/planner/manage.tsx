"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { api, type PlannerProjectDetail, type UserRecord } from "@/lib/api";

/**
 * Administering a project from the screen it lives on.
 *
 * Until this existed, everything except a quick update, a raised risk and an
 * added milestone was API-and-workbook only: a project manager could see that
 * a task had the wrong owner and had no way to change it without a
 * spreadsheet. That is not a governance control, it is a missing form.
 *
 * Three rules run through all of it:
 *
 * **Disclosed, not displayed.** Every form is behind a button. A project page
 * that greets its reader with eight empty forms above the plan has its
 * priorities backwards.
 *
 * **The version goes with the change.** Every edit sends the version it read,
 * so two people editing the same task produces a 409 somebody can see rather
 * than a silent overwrite.
 *
 * **The backend still decides.** Nothing here is a permission check. The
 * forms are hidden from a contributor because a form that only ever produces
 * a 403 is worse than no form, but the refusal that matters is the one on the
 * server.
 */

function Disclosure({
  label,
  children,
}: {
  label: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  if (!open) {
    return (
      <div className="border-b border-border px-4 py-2">
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          {label}
        </Button>
      </div>
    );
  }
  return (
    <div className="border-b border-border bg-surface-sunken px-4 py-3">
      {children(() => setOpen(false))}
    </div>
  );
}

function Problem({ text }: { text: string | null }) {
  if (!text) return null;
  const stale = text.includes("changed by somebody else");
  return (
    <p className={`mt-2 text-sm ${stale ? "text-warning" : "text-negative"}`}>
      {text}
    </p>
  );
}

/** A save button that reports its own failure, so no caller has to. */
function useSave(after: () => void) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  async function run(work: () => Promise<unknown>, close?: () => void) {
    setBusy(true);
    setError(null);
    try {
      await work();
      close?.();
      after();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }
  return { busy, error, run };
}

function People({ people }: { people: UserRecord[] }) {
  return (
    <>
      <option value="">Nobody</option>
      {people.map((p) => (
        <option key={p.id} value={p.id}>{p.display_name || p.username}</option>
      ))}
    </>
  );
}

// ========================================================= the project


export function EditProject({
  detail,
  people,
  onSaved,
}: {
  detail: PlannerProjectDetail;
  people: UserRecord[];
  onSaved: () => void;
}) {
  const p = detail.project;
  const [name, setName] = React.useState(p.name);
  const [objective, setObjective] = React.useState(p.objective ?? "");
  const [status, setStatus] = React.useState(p.status);
  const [priority, setPriority] = React.useState(p.priority);
  const [manager, setManager] = React.useState(String(p.manager?.id ?? ""));
  const [sponsor, setSponsor] = React.useState(String(p.sponsor?.id ?? ""));
  const [start, setStart] = React.useState(p.start_date ?? "");
  const [target, setTarget] = React.useState(p.target_end_date ?? "");
  const [cadence, setCadence] = React.useState(p.reporting_cadence);
  const [stale, setStale] = React.useState(String(p.stale_after_days ?? 7));
  const save = useSave(onSaved);

  return (
    <Disclosure label="Edit the project">
      {(close) => (
        <div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div className="sm:col-span-2">
              <Label>Objective</Label>
              <Textarea rows={2} value={objective}
                        onChange={(e) => setObjective(e.target.value)} />
            </div>
            <div>
              <Label>Status</Label>
              <Select value={status} onChange={(e) => setStatus(e.target.value)}>
                {["DRAFT", "PLANNING", "ACTIVE", "ON_HOLD", "COMPLETED",
                  "CANCELLED"].map((s) => (
                  <option key={s} value={s}>
                    {s.replace(/_/g, " ").toLowerCase()}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Priority</Label>
              <Select value={priority}
                      onChange={(e) => setPriority(e.target.value)}>
                {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((s) => (
                  <option key={s} value={s}>{s.toLowerCase()}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Project manager</Label>
              <Select value={manager}
                      onChange={(e) => setManager(e.target.value)}>
                <People people={people} />
              </Select>
            </div>
            <div>
              <Label>Sponsor</Label>
              <Select value={sponsor}
                      onChange={(e) => setSponsor(e.target.value)}>
                <People people={people} />
              </Select>
            </div>
            <div>
              <Label>Start date</Label>
              <Input type="date" value={start}
                     onChange={(e) => setStart(e.target.value)} />
            </div>
            <div>
              <Label>Target completion</Label>
              <Input type="date" value={target}
                     onChange={(e) => setTarget(e.target.value)} />
            </div>
            <div>
              <Label>Reporting cadence</Label>
              <Select value={cadence}
                      onChange={(e) => setCadence(e.target.value)}>
                {["DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY",
                  "QUARTERLY"].map((c) => (
                  <option key={c} value={c}>{c.toLowerCase()}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Chase after (days)</Label>
              <Input type="number" min={1} max={90} value={stale}
                     onChange={(e) => setStale(e.target.value)} />
            </div>
          </div>
          <Problem text={save.error} />
          <div className="mt-3 flex gap-2">
            <Button size="sm" disabled={save.busy} onClick={() => save.run(
              () => api.planner.updateProject(p.id, {
                name, objective, status, priority,
                manager_id: manager ? Number(manager) : null,
                sponsor_id: sponsor ? Number(sponsor) : null,
                start_date: start || null,
                target_end_date: target || null,
                reporting_cadence: cadence,
                stale_after_days: Number(stale) || 7,
                expected_version: p.version,
              }), close)}>
              {save.busy ? "Saving…" : "Save"}
            </Button>
            <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
          </div>
        </div>
      )}
    </Disclosure>
  );
}

// ============================================================== people


export function ManagePeople({
  detail,
  people,
  onSaved,
}: {
  detail: PlannerProjectDetail;
  people: UserRecord[];
  onSaved: () => void;
}) {
  const save = useSave(onSaved);
  const [user, setUser] = React.useState("");
  const [role, setRole] = React.useState("CONTRIBUTOR");
  const [access, setAccess] = React.useState("CONTRIBUTOR");

  return (
    <>
      <Disclosure label="Add somebody">
        {(close) => (
          <div>
            <div className="grid gap-3 sm:grid-cols-3">
              <div>
                <Label>Person</Label>
                <Select value={user} onChange={(e) => setUser(e.target.value)}>
                  <People people={people} />
                </Select>
              </div>
              <div>
                <Label>What they do</Label>
                <Select value={role} onChange={(e) => setRole(e.target.value)}>
                  {["SPONSOR", "MANAGER", "WORKSTREAM_LEAD", "CONTRIBUTOR",
                    "REVIEWER", "OBSERVER"].map((r) => (
                    <option key={r} value={r}>
                      {r.replace(/_/g, " ").toLowerCase()}
                    </option>
                  ))}
                </Select>
              </div>
              <div>
                <Label>What they may change</Label>
                <Select value={access}
                        onChange={(e) => setAccess(e.target.value)}>
                  {["VIEWER", "CONTRIBUTOR", "EDITOR", "OWNER"].map((a) => (
                    <option key={a} value={a}>{a.toLowerCase()}</option>
                  ))}
                </Select>
              </div>
            </div>
            <Problem text={save.error} />
            <div className="mt-3 flex gap-2">
              <Button size="sm" disabled={!user || save.busy}
                      onClick={() => save.run(
                        () => api.planner.addParticipant(detail.project.id, {
                          user_id: Number(user), project_role: role, access,
                        }), close)}>
                Add
              </Button>
              <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
            </div>
          </div>
        )}
      </Disclosure>

      <ul className="divide-y divide-border">
        {detail.participants.map((row) => (
          <ParticipantRow key={row.user?.id ?? row.project_role}
                          projectId={detail.project.id} row={row}
                          onSaved={onSaved} />
        ))}
      </ul>
    </>
  );
}

function ParticipantRow({
  projectId,
  row,
  onSaved,
}: {
  projectId: number;
  row: PlannerProjectDetail["participants"][number];
  onSaved: () => void;
}) {
  const save = useSave(onSaved);
  const [editing, setEditing] = React.useState(false);
  const [role, setRole] = React.useState(row.project_role);
  const [access, setAccess] = React.useState(row.access);
  const [notify, setNotify] = React.useState(row.notifications_enabled);
  const userId = row.user?.id;

  return (
    <li className="px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-0 flex-1">
          <span className="text-sm text-text-primary">
            {row.user?.name ?? "Unknown"}
          </span>
          <p className="text-xs text-text-muted">
            {row.project_role.replace(/_/g, " ").toLowerCase()} ·{" "}
            {row.access.toLowerCase()} access
            {!row.notifications_enabled && " · reminders off"}
          </p>
        </div>
        {userId && (
          <>
            <Button size="sm" variant="ghost"
                    onClick={() => setEditing((v) => !v)}>
              {editing ? "Close" : "Change"}
            </Button>
            <Button size="sm" variant="ghost"
                    onClick={() => save.run(
                      () => api.planner.removeParticipant(projectId, userId))}>
              Remove
            </Button>
          </>
        )}
      </div>

      {editing && userId && (
        <div className="mt-2 rounded-md border border-border bg-surface-sunken px-3 py-2">
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <Label>What they do</Label>
              <Select value={role} onChange={(e) => setRole(e.target.value)}>
                {["SPONSOR", "MANAGER", "WORKSTREAM_LEAD", "CONTRIBUTOR",
                  "REVIEWER", "OBSERVER"].map((r) => (
                  <option key={r} value={r}>
                    {r.replace(/_/g, " ").toLowerCase()}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <Label>What they may change</Label>
              <Select value={access} onChange={(e) => setAccess(e.target.value)}>
                {["VIEWER", "CONTRIBUTOR", "EDITOR", "OWNER"].map((a) => (
                  <option key={a} value={a}>{a.toLowerCase()}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Reminders</Label>
              <Select value={notify ? "on" : "off"}
                      onChange={(e) => setNotify(e.target.value === "on")}>
                <option value="on">Send them reminders</option>
                <option value="off">Do not</option>
              </Select>
            </div>
          </div>
          <Problem text={save.error} />
          <div className="mt-2">
            <Button size="sm" disabled={save.busy} onClick={() => save.run(
              () => api.planner.addParticipant(projectId, {
                user_id: userId, project_role: role, access,
                notifications_enabled: notify,
              }), () => setEditing(false))}>
              Save
            </Button>
          </div>
        </div>
      )}
    </li>
  );
}

// ========================================================= workstreams


export function AddWorkstream({
  projectId,
  people,
  onSaved,
}: {
  projectId: number;
  people: UserRecord[];
  onSaved: () => void;
}) {
  const save = useSave(onSaved);
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [lead, setLead] = React.useState("");
  const [start, setStart] = React.useState("");
  const [end, setEnd] = React.useState("");

  return (
    <Disclosure label="Add a workstream">
      {(close) => (
        <div>
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <Label>Code</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value)}
                     placeholder="WS-DATA" maxLength={40} />
            </div>
            <div>
              <Label>Name</Label>
              <Input value={name} onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <Label>Lead</Label>
              <Select value={lead} onChange={(e) => setLead(e.target.value)}>
                <People people={people} />
              </Select>
            </div>
            <div />
            <div>
              <Label>Starts</Label>
              <Input type="date" value={start}
                     onChange={(e) => setStart(e.target.value)} />
            </div>
            <div>
              <Label>Ends</Label>
              <Input type="date" value={end}
                     onChange={(e) => setEnd(e.target.value)} />
            </div>
          </div>
          <Problem text={save.error} />
          <div className="mt-3 flex gap-2">
            <Button size="sm" disabled={!code || !name || save.busy}
                    onClick={() => save.run(
                      () => api.planner.createWorkstream(projectId, {
                        code, name,
                        lead_id: lead ? Number(lead) : null,
                        start_date: start || null,
                        target_end_date: end || null,
                      }), close)}>
              Add
            </Button>
            <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
          </div>
        </div>
      )}
    </Disclosure>
  );
}

// =============================================================== tasks


export function AddTask({
  detail,
  people,
  onSaved,
}: {
  detail: PlannerProjectDetail;
  people: UserRecord[];
  onSaved: () => void;
}) {
  const save = useSave(onSaved);
  const [code, setCode] = React.useState("");
  const [title, setTitle] = React.useState("");
  const [workstream, setWorkstream] = React.useState("");
  const [parent, setParent] = React.useState("");
  const [owner, setOwner] = React.useState("");
  const [reviewer, setReviewer] = React.useState("");
  const [priority, setPriority] = React.useState("MEDIUM");
  const [start, setStart] = React.useState("");
  const [due, setDue] = React.useState("");
  const [effort, setEffort] = React.useState("");
  const [weight, setWeight] = React.useState("1");
  const [critical, setCritical] = React.useState(false);
  const [description, setDescription] = React.useState("");

  return (
    <Disclosure label="Add a task">
      {(close) => (
        <div>
          <div className="grid gap-3 sm:grid-cols-3">
            <div>
              <Label>Code</Label>
              <Input value={code} onChange={(e) => setCode(e.target.value)}
                     placeholder="T-104" maxLength={40} />
            </div>
            <div className="sm:col-span-2">
              <Label>Title</Label>
              <Input value={title} onChange={(e) => setTitle(e.target.value)} />
            </div>
            <div>
              <Label>Workstream</Label>
              <Select value={workstream}
                      onChange={(e) => setWorkstream(e.target.value)}>
                <option value="">None</option>
                {detail.workstreams.map((ws) => (
                  <option key={ws.id} value={ws.id}>{ws.code} {ws.name}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Parent task</Label>
              <Select value={parent} onChange={(e) => setParent(e.target.value)}>
                <option value="">None — this is a top-level task</option>
                {detail.tasks.map((t) => (
                  <option key={t.id} value={t.id}>{t.code} {t.title}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Priority</Label>
              <Select value={priority}
                      onChange={(e) => setPriority(e.target.value)}>
                {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((s) => (
                  <option key={s} value={s}>{s.toLowerCase()}</option>
                ))}
              </Select>
            </div>
            <div>
              <Label>Owner</Label>
              <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
                <People people={people} />
              </Select>
            </div>
            <div>
              <Label>Reviewer</Label>
              <Select value={reviewer}
                      onChange={(e) => setReviewer(e.target.value)}>
                <People people={people} />
              </Select>
            </div>
            <div>
              <Label>Weight</Label>
              <Input type="number" min={0} step={0.5} value={weight}
                     onChange={(e) => setWeight(e.target.value)} />
            </div>
            <div>
              <Label>Starts</Label>
              <Input type="date" value={start}
                     onChange={(e) => setStart(e.target.value)} />
            </div>
            <div>
              <Label>Due</Label>
              <Input type="date" value={due}
                     onChange={(e) => setDue(e.target.value)} />
            </div>
            <div>
              <Label>Effort (days)</Label>
              <Input type="number" min={1} value={effort}
                     onChange={(e) => setEffort(e.target.value)} />
            </div>
            <div className="sm:col-span-3">
              <Label>Description</Label>
              <Textarea rows={2} value={description}
                        onChange={(e) => setDescription(e.target.value)} />
            </div>
            <label className="flex items-center gap-2 text-sm text-text-secondary">
              <input type="checkbox" checked={critical}
                     onChange={(e) => setCritical(e.target.checked)} />
              Mark critical
            </label>
          </div>
          <p className="mt-2 text-xs text-text-muted">
            Marking a task critical is your judgement. The calculated critical
            path is worked out separately, on the Timeline tab, and the two are
            shown side by side.
          </p>
          <Problem text={save.error} />
          <div className="mt-3 flex gap-2">
            <Button size="sm" disabled={!code || !title || save.busy}
                    onClick={() => save.run(
                      () => api.planner.createTask(detail.project.id, {
                        code, title, description,
                        workstream_id: workstream ? Number(workstream) : null,
                        parent_id: parent ? Number(parent) : null,
                        owner_id: owner ? Number(owner) : null,
                        reviewer_id: reviewer ? Number(reviewer) : null,
                        priority,
                        start_date: start || null,
                        due_date: due || null,
                        effort_days: effort ? Number(effort) : null,
                        weight: Number(weight) || 1,
                        critical,
                      }), close)}>
              Add
            </Button>
            <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
          </div>
        </div>
      )}
    </Disclosure>
  );
}

/**
 * The editor's half of a task: the fields the quick-update drawer refuses.
 *
 * Owner, dates, weight and the critical marker are commitments rather than
 * reports, which is why a contributor cannot change them from the drawer.
 * Somebody has to be able to, and this is where.
 */
export function EditTask({
  detail,
  task,
  people,
  onSaved,
  onClose,
}: {
  detail: PlannerProjectDetail;
  task: PlannerProjectDetail["tasks"][number];
  people: UserRecord[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const save = useSave(onSaved);
  const [title, setTitle] = React.useState(task.title);
  const [owner, setOwner] = React.useState(String(task.owner?.id ?? ""));
  const [reviewer, setReviewer] = React.useState(String(task.reviewer?.id ?? ""));
  const [workstream, setWorkstream] = React.useState(
    String(task.workstream_id ?? ""));
  const [priority, setPriority] = React.useState(task.priority);
  const [start, setStart] = React.useState(task.start_date ?? "");
  const [due, setDue] = React.useState(task.due_date ?? "");
  const [weight, setWeight] = React.useState(String(task.weight ?? 1));
  const [critical, setCritical] = React.useState(Boolean(task.critical));
  const [why, setWhy] = React.useState("");

  return (
    <div className="rounded-md border border-border bg-surface-sunken px-3 py-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="sm:col-span-3">
          <Label>Title</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <Label>Owner</Label>
          <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <People people={people} />
          </Select>
        </div>
        <div>
          <Label>Reviewer</Label>
          <Select value={reviewer} onChange={(e) => setReviewer(e.target.value)}>
            <People people={people} />
          </Select>
        </div>
        <div>
          <Label>Workstream</Label>
          <Select value={workstream}
                  onChange={(e) => setWorkstream(e.target.value)}>
            <option value="">None</option>
            {detail.workstreams.map((ws) => (
              <option key={ws.id} value={ws.id}>{ws.code}</option>
            ))}
          </Select>
        </div>
        <div>
          <Label>Priority</Label>
          <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
            {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((s) => (
              <option key={s} value={s}>{s.toLowerCase()}</option>
            ))}
          </Select>
        </div>
        <div>
          <Label>Starts</Label>
          <Input type="date" value={start}
                 onChange={(e) => setStart(e.target.value)} />
        </div>
        <div>
          <Label>Due</Label>
          <Input type="date" value={due}
                 onChange={(e) => setDue(e.target.value)} />
        </div>
        <div>
          <Label>Weight</Label>
          <Input type="number" min={0} step={0.5} value={weight}
                 onChange={(e) => setWeight(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-text-secondary">
          <input type="checkbox" checked={critical}
                 onChange={(e) => setCritical(e.target.checked)} />
          Marked critical
        </label>
        <div className="sm:col-span-3">
          <Label>Why (goes on the record)</Label>
          <Input value={why} onChange={(e) => setWhy(e.target.value)}
                 placeholder="Moved to the 12th after the data freeze slipped." />
        </div>
      </div>
      <Problem text={save.error} />
      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={save.busy} onClick={() => save.run(
          () => api.planner.updateTask(task.id, {
            title,
            owner_id: owner ? Number(owner) : null,
            reviewer_id: reviewer ? Number(reviewer) : null,
            workstream_id: workstream ? Number(workstream) : null,
            priority,
            start_date: start || null,
            due_date: due || null,
            weight: Number(weight) || 1,
            critical,
            narrative: why,
            expected_version: task.version,
          }), onClose)}>
          {save.busy ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
        <Button size="sm" variant="ghost" className="ml-auto text-negative"
                disabled={save.busy}
                onClick={() => save.run(
                  () => api.planner.deleteTask(task.id), onClose)}>
          Delete
        </Button>
      </div>
    </div>
  );
}

// ======================================================== dependencies


export function ManageDependencies({
  detail,
  onSaved,
}: {
  detail: PlannerProjectDetail;
  onSaved: () => void;
}) {
  const save = useSave(onSaved);
  const [pred, setPred] = React.useState("");
  const [succ, setSucc] = React.useState("");
  const [kind, setKind] = React.useState("FS");
  const [lag, setLag] = React.useState("0");

  const options = [
    ...detail.tasks.map((t) => ({
      value: `TASK:${t.id}`, label: `${t.code} ${t.title}` })),
    ...detail.milestones.map((m) => ({
      value: `MILESTONE:${m.id}`, label: `${m.code} ${m.name}` })),
  ];

  function split(value: string) {
    const [type, id] = value.split(":");
    return { type, id: Number(id) };
  }

  return (
    <>
      <Disclosure label="Link two things">
        {(close) => (
          <div>
            <div className="grid gap-3 sm:grid-cols-2">
              <div>
                <Label>This has to happen first</Label>
                <Select value={pred} onChange={(e) => setPred(e.target.value)}>
                  <option value="">Choose one</option>
                  {options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </Select>
              </div>
              <div>
                <Label>Before this</Label>
                <Select value={succ} onChange={(e) => setSucc(e.target.value)}>
                  <option value="">Choose one</option>
                  {options.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </Select>
              </div>
              <div>
                <Label>Kind</Label>
                <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                  <option value="FS">Finish then start</option>
                  <option value="SS">Start together</option>
                  <option value="FF">Finish together</option>
                  <option value="SF">Start then finish</option>
                </Select>
              </div>
              <div>
                <Label>Lag (days)</Label>
                <Input type="number" value={lag}
                       onChange={(e) => setLag(e.target.value)} />
              </div>
            </div>
            <Problem text={save.error} />
            <div className="mt-3 flex gap-2">
              <Button size="sm" disabled={!pred || !succ || save.busy}
                      onClick={() => save.run(() => {
                        const a = split(pred);
                        const b = split(succ);
                        return api.planner.createDependency(detail.project.id, {
                          predecessor_type: a.type, predecessor_id: a.id,
                          successor_type: b.type, successor_id: b.id,
                          dependency_type: kind, lag_days: Number(lag) || 0,
                        });
                      }, close)}>
                Link
              </Button>
              <Button size="sm" variant="ghost" onClick={close}>Cancel</Button>
            </div>
          </div>
        )}
      </Disclosure>

      <ul className="divide-y divide-border">
        {detail.dependencies.map((d) => (
          <li key={d.id} className="flex items-center gap-3 px-4 py-2 text-sm">
            <span className="font-mono text-xs text-text-muted">
              {d.predecessor_code}
            </span>
            <span className="text-text-muted">→</span>
            <span className="font-mono text-xs text-text-muted">
              {d.successor_code}
            </span>
            <Badge variant="outline">{d.dependency_type}</Badge>
            {d.lag_days !== 0 && (
              <span className="text-xs text-text-muted">
                {d.lag_days > 0 ? "+" : ""}{d.lag_days} d
              </span>
            )}
            <Button size="sm" variant="ghost" className="ml-auto"
                    disabled={save.busy}
                    onClick={() => save.run(
                      () => api.planner.deleteDependency(d.id))}>
              Unlink
            </Button>
          </li>
        ))}
      </ul>
      <Problem text={save.error} />
    </>
  );
}

// ========================================================== milestones


export function EditMilestone({
  milestone,
  people,
  onSaved,
  onClose,
}: {
  milestone: PlannerProjectDetail["milestones"][number];
  people: UserRecord[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const save = useSave(onSaved);
  const [name, setName] = React.useState(milestone.name);
  const [owner, setOwner] = React.useState(String(milestone.owner?.id ?? ""));
  const [target, setTarget] = React.useState(milestone.target_date ?? "");
  const [actual, setActual] = React.useState(milestone.actual_date ?? "");
  const [status, setStatus] = React.useState(milestone.status);
  const [critical, setCritical] = React.useState(Boolean(milestone.critical));
  const [why, setWhy] = React.useState("");

  return (
    <div className="rounded-md border border-border bg-surface-sunken px-3 py-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label>Name</Label>
          <Input value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <Label>Owner</Label>
          <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <People people={people} />
          </Select>
        </div>
        <div>
          <Label>Status</Label>
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["PENDING", "AT_RISK", "ACHIEVED", "MISSED", "CANCELLED"].map((s) => (
              <option key={s} value={s}>
                {s.replace(/_/g, " ").toLowerCase()}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label>Target date</Label>
          <Input type="date" value={target}
                 onChange={(e) => setTarget(e.target.value)} />
        </div>
        <div>
          <Label>Achieved on</Label>
          <Input type="date" value={actual}
                 onChange={(e) => setActual(e.target.value)} />
        </div>
        <label className="flex items-center gap-2 text-sm text-text-secondary">
          <input type="checkbox" checked={critical}
                 onChange={(e) => setCritical(e.target.checked)} />
          Marked critical
        </label>
        <div className="sm:col-span-2">
          <Label>Why (goes on the record)</Label>
          <Input value={why} onChange={(e) => setWhy(e.target.value)} />
        </div>
      </div>
      <Problem text={save.error} />
      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={save.busy} onClick={() => save.run(
          () => api.planner.updateMilestone(milestone.id, {
            name,
            owner_id: owner ? Number(owner) : null,
            target_date: target || null,
            actual_date: actual || null,
            status, critical, narrative: why,
            expected_version: milestone.version,
          }), onClose)}>
          {save.busy ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}

// ================================================================ RAID


export function EditRaid({
  item,
  people,
  onSaved,
  onClose,
}: {
  item: PlannerProjectDetail["raid"][number];
  people: UserRecord[];
  onSaved: () => void;
  onClose: () => void;
}) {
  const save = useSave(onSaved);
  const [title, setTitle] = React.useState(item.title);
  const [owner, setOwner] = React.useState(String(item.owner?.id ?? ""));
  const [severity, setSeverity] = React.useState(item.severity);
  const [status, setStatus] = React.useState(item.status);
  const [target, setTarget] = React.useState(item.target_date ?? "");
  const [mitigation, setMitigation] = React.useState(item.mitigation ?? "");
  const [resolution, setResolution] = React.useState(item.resolution ?? "");

  return (
    <div className="rounded-md border border-border bg-surface-sunken px-3 py-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <Label>Title</Label>
          <Input value={title} onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div>
          <Label>Owner</Label>
          <Select value={owner} onChange={(e) => setOwner(e.target.value)}>
            <People people={people} />
          </Select>
        </div>
        <div>
          <Label>Severity</Label>
          <Select value={severity}
                  onChange={(e) => setSeverity(e.target.value)}>
            {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((s) => (
              <option key={s} value={s}>{s.toLowerCase()}</option>
            ))}
          </Select>
        </div>
        <div>
          <Label>Status</Label>
          <Select value={status} onChange={(e) => setStatus(e.target.value)}>
            {["OPEN", "MITIGATING", "MONITORING", "CLOSED",
              "ACCEPTED"].map((s) => (
              <option key={s} value={s}>{s.toLowerCase()}</option>
            ))}
          </Select>
        </div>
        <div>
          <Label>Target date</Label>
          <Input type="date" value={target}
                 onChange={(e) => setTarget(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <Label>Mitigation</Label>
          <Textarea rows={2} value={mitigation}
                    onChange={(e) => setMitigation(e.target.value)} />
        </div>
        <div className="sm:col-span-2">
          <Label>Resolution</Label>
          <Textarea rows={2} value={resolution}
                    onChange={(e) => setResolution(e.target.value)} />
        </div>
      </div>
      <Problem text={save.error} />
      <div className="mt-3 flex gap-2">
        <Button size="sm" disabled={save.busy} onClick={() => save.run(
          () => api.planner.updateRaid(item.id, {
            title,
            owner_id: owner ? Number(owner) : null,
            severity, status,
            target_date: target || null,
            mitigation, resolution,
            expected_version: item.version,
          }), onClose)}>
          {save.busy ? "Saving…" : "Save"}
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>Cancel</Button>
      </div>
    </div>
  );
}
