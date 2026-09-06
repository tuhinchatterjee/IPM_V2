"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  api,
  ApiError,
  type CopilotPerson,
  type DraftCatalogueRow,
  type DraftDetail,
  type DraftLinkPreview,
  type DraftNote,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The plan, as panels.
 *
 * Every control here calls `api.planner.copilot.apply` with a named command —
 * the same call the conversation makes. There is no "save the form" endpoint
 * and no client-side plan model that later has to be reconciled with the
 * server's: the draft on the server is the plan, and this is a view of it.
 * That is §39 as a piece of code rather than as an intention.
 *
 * The panels are ordered the way somebody actually decides: what the project
 * is, who is answerable, how hard the agent should chase, then the work. The
 * agentic question is not last and not optional, because a plan published
 * without an answer to it gets a default nobody chose.
 */

type Row = Record<string, unknown>;

const text = (row: Row, key: string) => String(row[key] ?? "");
const num = (row: Row, key: string): number | null => {
  const found = row[key];
  return found === null || found === undefined || found === "" ? null
    : Number(found);
};

export function DraftBuilder({
  detail,
  people,
  onChanged,
  onPublished,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  onChanged: () => void;
  onPublished: (projectId: number) => void;
}) {
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  const apply = React.useCallback(
    async (command: string, payload: Row = {}) => {
      setBusy(true);
      setError("");
      try {
        await api.planner.copilot.apply(detail.key, command, payload,
                                        detail.version);
        onChanged();
        return true;
      } catch (failure) {
        setError(
          failure instanceof ApiError
            ? failure.message
            : "That change did not go through.",
        );
        return false;
      } finally {
        setBusy(false);
      }
    },
    [detail.key, detail.version, onChanged],
  );

  const plan = detail.plan;
  const milestones = plan.milestones ?? [];
  const tasks = plan.tasks ?? [];

  return (
    <div className="space-y-4">
      {error && (
        <p
          role="alert"
          className="rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative"
        >
          {error}
        </p>
      )}

      <Overview key={`o${detail.version}`} detail={detail} apply={apply}
               busy={busy} />
      <Governance key={`g${detail.version}`} detail={detail} people={people}
                  apply={apply} busy={busy} />
      <Agentic detail={detail} apply={apply} busy={busy} />

      <Panel
        title="Milestones"
        note="A milestone is a date somebody is answerable for. Tasks live under it."
      >
        <div className="divide-y divide-border">
          {milestones.length === 0 && (
            <p className="px-4 py-4 text-sm text-text-muted">
              Nothing yet. Add the first milestone, or tell the Copilot what
              the stages are.
            </p>
          )}
          {milestones.map((milestone) => (
            <MilestoneBlock
              key={`${text(milestone, "code")}-${detail.version}`}
              milestone={milestone}
              tasks={tasks.filter(
                (task) => text(task, "milestone_code") ===
                  text(milestone, "code"))}
              people={people}
              catalogue={detail.catalogue}
              draftKey={detail.key}
              apply={apply}
              busy={busy}
            />
          ))}
        </div>
        <AddMilestone people={people} apply={apply} busy={busy} />
      </Panel>

      <Links detail={detail} apply={apply} busy={busy} />
      <Completeness detail={detail} />
      <PublishPanel detail={detail} onPublished={onPublished} />
    </div>
  );
}

// ------------------------------------------------------------------- shell

function Panel({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-lg border border-border bg-surface">
      <header className="border-b border-border px-4 py-2.5">
        <h2 className="text-sm font-semibold text-text-primary">{title}</h2>
        {note && <p className="mt-0.5 text-xs text-text-muted">{note}</p>}
      </header>
      {children}
    </section>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[11px] uppercase tracking-wide text-text-muted">
        {label}
      </span>
      {children}
      {hint && <span className="mt-0.5 block text-xs text-text-muted">{hint}</span>}
    </label>
  );
}

function PersonSelect({
  value,
  people,
  onChange,
  allowNobody = true,
}: {
  value: number | null;
  people: CopilotPerson[];
  onChange: (id: number | null) => void;
  allowNobody?: boolean;
}) {
  return (
    <select
      value={value ?? ""}
      onChange={(event) =>
        onChange(event.target.value ? Number(event.target.value) : null)}
      className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary"
    >
      {allowNobody && <option value="">Nobody yet</option>}
      {people.map((person) => (
        <option key={person.user_id} value={person.user_id}>
          {person.name}
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------- overview

function Overview({
  detail,
  apply,
  busy,
}: {
  detail: DraftDetail;
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  // Seeded from the server once. The parent remounts this panel on the
  // draft's version, so a saved change comes back as the server stored it
  // rather than as an effect racing the render that produced it.
  const [form, setForm] = React.useState(detail.plan.overview);

  return (
    <Panel title="What this project is">
      <div className="grid gap-3 px-4 py-4 sm:grid-cols-2">
        <Field label="Name">
          <Input
            value={form.name}
            onChange={(event) =>
              setForm({ ...form, name: event.target.value })}
          />
        </Field>
        <Field label="Code" hint="How people will refer to it in exports and chat.">
          <Input
            value={form.code}
            onChange={(event) =>
              setForm({ ...form, code: event.target.value })}
          />
        </Field>
        <Field label="Overview">
          <Input
            value={form.description}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })}
          />
        </Field>
        <Field label="Objective" hint="What has to be true for this to be finished?">
          <Input
            value={form.objective}
            onChange={(event) =>
              setForm({ ...form, objective: event.target.value })}
          />
        </Field>
      </div>
      <div className="border-t border-border px-4 py-2.5">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => void apply("set_overview", { ...form })}
        >
          Save
        </Button>
      </div>
    </Panel>
  );
}

// -------------------------------------------------------------- governance

function Governance({
  detail,
  people,
  apply,
  busy,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  const [form, setForm] = React.useState(detail.plan.governance);

  return (
    <Panel
      title="Who is answerable"
      note="The escalation contact is the last stop when a task's own owner has not resolved something."
    >
      <div className="grid gap-3 px-4 py-4 sm:grid-cols-2">
        <Field label="Sponsor">
          <PersonSelect
            value={form.sponsor_id}
            people={people}
            onChange={(id) => setForm({ ...form, sponsor_id: id })}
          />
        </Field>
        <Field label="Manager">
          <PersonSelect
            value={form.manager_id}
            people={people}
            onChange={(id) => setForm({ ...form, manager_id: id })}
          />
        </Field>
        <Field label="Owner">
          <PersonSelect
            value={form.owner_id}
            people={people}
            onChange={(id) => setForm({ ...form, owner_id: id })}
          />
        </Field>
        <Field label="Escalation contact">
          <PersonSelect
            value={form.escalation_id}
            people={people}
            onChange={(id) => setForm({ ...form, escalation_id: id })}
          />
        </Field>
        <Field label="Starts">
          <Input
            type="date"
            value={form.start_date ?? ""}
            onChange={(event) =>
              setForm({ ...form, start_date: event.target.value })}
          />
        </Field>
        <Field label="Target completion">
          <Input
            type="date"
            value={form.target_end_date ?? ""}
            onChange={(event) =>
              setForm({ ...form, target_end_date: event.target.value })}
          />
        </Field>
        <Field label="Priority">
          <select
            value={form.priority}
            onChange={(event) =>
              setForm({ ...form, priority: event.target.value })}
            className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary"
          >
            {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((level) => (
              <option key={level} value={level}>{level}</option>
            ))}
          </select>
        </Field>
        <Field label="Reporting">
          <select
            value={form.reporting_cadence}
            onChange={(event) =>
              setForm({ ...form, reporting_cadence: event.target.value })}
            className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary"
          >
            {["DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"].map((cadence) => (
              <option key={cadence} value={cadence}>{cadence}</option>
            ))}
          </select>
        </Field>
      </div>
      <div className="border-t border-border px-4 py-2.5">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => void apply("set_governance", { ...form })}
        >
          Save
        </Button>
      </div>
    </Panel>
  );
}

// ----------------------------------------------------------------- agentic

/**
 * §11. The question every project gets asked and nobody may skip.
 *
 * Presented as four described choices rather than a settings form, because
 * "escalate_after_days: 2" is not a decision a project manager can make and
 * "chase the owner two days after a date passes, then their escalation
 * contact" is.
 */
function Agentic({
  detail,
  apply,
  busy,
}: {
  detail: DraftDetail;
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  const chosen = detail.plan.agentic?.mode ?? "STANDARD";
  return (
    <Panel
      title="How do you want the Agentic AI to work?"
      note="This decides when the agent chases somebody, and who hears about it next."
    >
      <div className="grid gap-3 px-4 py-4 sm:grid-cols-2">
        {detail.agentic_choices.map((choice) => (
          <button
            key={choice.mode}
            type="button"
            disabled={busy}
            onClick={() => void apply("set_agentic", { mode: choice.mode })}
            className={cn(
              "rounded-lg border px-3 py-3 text-left transition",
              choice.mode === chosen
                ? "border-accent bg-accent-muted"
                : "border-border bg-surface-raised hover:border-accent",
            )}
          >
            <p className="text-sm font-semibold text-text-primary">
              {choice.label}
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">{choice.note}</p>
            <p className="mt-1.5 text-xs text-text-muted">{choice.sentence}</p>
          </button>
        ))}
      </div>
    </Panel>
  );
}

// -------------------------------------------------------------- milestones

function MilestoneBlock({
  milestone,
  tasks,
  people,
  catalogue,
  draftKey,
  apply,
  busy,
}: {
  milestone: Row;
  tasks: Row[];
  people: CopilotPerson[];
  catalogue: DraftCatalogueRow[];
  draftKey: string;
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  const code = text(milestone, "code");
  const [open, setOpen] = React.useState(false);
  const [form, setForm] = React.useState(milestone);

  return (
    <div className="px-4 py-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-text-primary">
            <span className="mr-2 font-mono text-xs text-text-muted">{code}</span>
            {text(milestone, "name")}
          </p>
          <p className="mt-0.5 text-xs text-text-muted">
            {text(milestone, "start_date") || "no start"} →{" "}
            {text(milestone, "target_date") || "no target date"} ·{" "}
            {tasks.length} {tasks.length === 1 ? "task" : "tasks"}
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="ghost" onClick={() => setOpen(!open)}>
            {open ? "Close" : "Edit"}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => void apply("remove_milestone", { code })}
          >
            Remove
          </Button>
        </div>
      </div>

      {open && (
        <div className="mt-3 space-y-3 rounded-md border border-border bg-surface-raised p-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label="Name">
              <Input
                value={text(form, "name")}
                onChange={(event) =>
                  setForm({ ...form, name: event.target.value })}
              />
            </Field>
            <Field label="Owner">
              <PersonSelect
                value={num(form, "owner_id")}
                people={people}
                onChange={(id) => setForm({ ...form, owner_id: id })}
              />
            </Field>
            <Field label="Starts">
              <Input
                type="date"
                value={text(form, "start_date")}
                onChange={(event) =>
                  setForm({ ...form, start_date: event.target.value })}
              />
            </Field>
            <Field label="Target date">
              <Input
                type="date"
                value={text(form, "target_date")}
                onChange={(event) =>
                  setForm({ ...form, target_date: event.target.value })}
              />
            </Field>
            <Field
              label="Critical date"
              hint="After this it cannot recover. Not the same as the target date."
            >
              <Input
                type="date"
                value={text(form, "critical_date")}
                onChange={(event) =>
                  setForm({ ...form, critical_date: event.target.value })}
              />
            </Field>
            <Field
              label="Escalation contact"
              hint="Leave empty to inherit the project's."
            >
              <PersonSelect
                value={num(form, "escalation_id")}
                people={people}
                onChange={(id) => setForm({ ...form, escalation_id: id })}
              />
            </Field>
          </div>
          <Button
            size="sm"
            disabled={busy}
            onClick={() =>
              void apply("update_milestone", { ...form, code })}
          >
            Save milestone
          </Button>
        </div>
      )}

      <TaskTable
        milestoneCode={code}
        tasks={tasks}
        people={people}
        catalogue={catalogue}
        draftKey={draftKey}
        apply={apply}
        busy={busy}
      />
    </div>
  );
}

function AddMilestone({
  people,
  apply,
  busy,
}: {
  people: CopilotPerson[];
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  const [form, setForm] = React.useState<Row>({ name: "" });
  return (
    <div className="border-t border-border px-4 py-3">
      <div className="grid gap-3 sm:grid-cols-4">
        <Field label="New milestone">
          <Input
            value={text(form, "name")}
            placeholder="Data foundation"
            onChange={(event) => setForm({ ...form, name: event.target.value })}
          />
        </Field>
        <Field label="Owner">
          <PersonSelect
            value={num(form, "owner_id")}
            people={people}
            onChange={(id) => setForm({ ...form, owner_id: id })}
          />
        </Field>
        <Field label="Starts">
          <Input
            type="date"
            value={text(form, "start_date")}
            onChange={(event) =>
              setForm({ ...form, start_date: event.target.value })}
          />
        </Field>
        <Field label="Target date">
          <Input
            type="date"
            value={text(form, "target_date")}
            onChange={(event) =>
              setForm({ ...form, target_date: event.target.value })}
          />
        </Field>
      </div>
      <Button
        size="sm"
        className="mt-3"
        disabled={busy || !text(form, "name").trim()}
        onClick={async () => {
          if (await apply("add_milestone", { ...form })) setForm({ name: "" });
        }}
      >
        Add milestone
      </Button>
    </div>
  );
}

// ------------------------------------------------------------------- tasks

function TaskTable({
  milestoneCode,
  tasks,
  people,
  catalogue,
  draftKey,
  apply,
  busy,
}: {
  milestoneCode: string;
  tasks: Row[];
  people: CopilotPerson[];
  catalogue: DraftCatalogueRow[];
  draftKey: string;
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  const [form, setForm] = React.useState<Row>({ title: "" });
  const [linking, setLinking] = React.useState<DraftLinkPreview | null>(null);

  const offerPrevious = React.useCallback(
    async (code: string) => {
      const found = await api.planner.copilot.previousTask(draftKey, code);
      if (!found.code) return;
      setLinking(
        await api.planner.copilot.linkPreview(draftKey, {
          predecessor: found.code, successor: code,
        }),
      );
    },
    [draftKey],
  );

  return (
    <div className="mt-3 rounded-md border border-border">
      <table className="w-full text-sm">
        <tbody className="divide-y divide-border">
          {tasks.map((task) => (
            <tr key={text(task, "code")}>
              <td className="px-3 py-2 font-mono text-xs text-text-muted">
                {text(task, "code")}
              </td>
              <td className="px-3 py-2 text-text-primary">
                {text(task, "title")}
              </td>
              <td className="px-3 py-2 text-xs text-text-muted">
                {people.find((p) => p.user_id === num(task, "owner_id"))?.name
                  ?? "no owner"}
              </td>
              <td className="px-3 py-2 text-xs text-text-muted">
                {text(task, "due_date") || "no due date"}
              </td>
              <td className="px-3 py-2 text-right">
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => void offerPrevious(text(task, "code"))}
                >
                  Link to previous task
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={busy}
                  onClick={() =>
                    void apply("remove_task", { code: text(task, "code") })}
                >
                  Remove
                </Button>
              </td>
            </tr>
          ))}
          {tasks.length === 0 && (
            <tr>
              <td className="px-3 py-2 text-xs text-text-muted" colSpan={5}>
                No tasks under this milestone yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>

      {linking && (
        <LinkConfirm
          preview={linking}
          busy={busy}
          onCancel={() => setLinking(null)}
          onConfirm={async () => {
            await apply("add_link", {
              predecessor: linking.predecessor,
              successor: linking.successor,
            });
            setLinking(null);
          }}
        />
      )}

      <div className="grid gap-3 border-t border-border px-3 py-3 sm:grid-cols-5">
        <Field label="New task">
          <Input
            value={text(form, "title")}
            placeholder="Extract recovery history"
            onChange={(event) =>
              setForm({ ...form, title: event.target.value })}
          />
        </Field>
        <Field label="What it involves">
          <Input
            value={text(form, "description")}
            onChange={(event) =>
              setForm({ ...form, description: event.target.value })}
          />
        </Field>
        <Field label="Owner">
          <PersonSelect
            value={num(form, "owner_id")}
            people={people}
            onChange={(id) => setForm({ ...form, owner_id: id })}
          />
        </Field>
        <Field label="Starts">
          <Input
            type="date"
            value={text(form, "start_date")}
            onChange={(event) =>
              setForm({ ...form, start_date: event.target.value })}
          />
        </Field>
        <Field label="Due">
          <Input
            type="date"
            value={text(form, "due_date")}
            onChange={(event) =>
              setForm({ ...form, due_date: event.target.value })}
          />
        </Field>
      </div>
      <div className="border-t border-border px-3 py-2.5">
        <Button
          size="sm"
          disabled={busy || !text(form, "title").trim()}
          onClick={async () => {
            const added = await apply("add_task", {
              ...form, milestone_code: milestoneCode,
            });
            if (added) setForm({ title: "" });
          }}
        >
          Add task
        </Button>
        <span className="ml-3 text-xs text-text-muted">
          {catalogue.length} things in this plan can be linked to.
        </span>
      </div>
    </div>
  );
}

/**
 * §17. A dependency states itself before it exists.
 *
 * Including the date conflict, which is stated and NOT fixed: moving a date
 * somebody committed to is a decision, and a plan that silently rescheduled
 * it would be a plan nobody can trust the dates in.
 */
function LinkConfirm({
  preview,
  busy,
  onCancel,
  onConfirm,
}: {
  preview: DraftLinkPreview;
  busy: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  return (
    <div className="border-t border-border bg-surface-raised px-3 py-3">
      <p className="text-sm text-text-primary">{preview.sentence}</p>
      {preview.conflict && (
        <p className="mt-1 text-sm text-warning">{preview.conflict}</p>
      )}
      <div className="mt-2 flex gap-2">
        <Button size="sm" disabled={busy} onClick={onConfirm}>
          Make the link
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Leave it
        </Button>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------- links

function Links({
  detail,
  apply,
  busy,
}: {
  detail: DraftDetail;
  apply: (command: string, payload: Row) => Promise<boolean>;
  busy: boolean;
}) {
  const [before, setBefore] = React.useState("");
  const [after, setAfter] = React.useState("");
  const [preview, setPreview] = React.useState<DraftLinkPreview | null>(null);
  const [error, setError] = React.useState("");

  const label = (code: string) =>
    detail.catalogue.find((row) => row.code === code)?.name ?? code;

  return (
    <Panel
      title="What waits for what"
      note="Nothing is linked until you say so, and a link that would make a loop is refused."
    >
      <ul className="divide-y divide-border">
        {detail.plan.links.map((link) => (
          <li
            key={`${link.predecessor}-${link.successor}`}
            className="flex items-center justify-between gap-3 px-4 py-2 text-sm"
          >
            <span className="text-text-secondary">
              {label(link.successor)} waits for {label(link.predecessor)}
            </span>
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() =>
                void apply("remove_link", {
                  predecessor: link.predecessor,
                  successor: link.successor,
                })}
            >
              Unlink
            </Button>
          </li>
        ))}
        {detail.plan.links.length === 0 && (
          <li className="px-4 py-3 text-sm text-text-muted">
            Nothing waits for anything yet.
          </li>
        )}
      </ul>

      <div className="grid gap-3 border-t border-border px-4 py-3 sm:grid-cols-2">
        <Field label="This has to finish first">
          <CatalogueSelect
            value={before}
            rows={detail.catalogue}
            onChange={setBefore}
          />
        </Field>
        <Field label="Before this can start">
          <CatalogueSelect
            value={after}
            rows={detail.catalogue}
            onChange={setAfter}
          />
        </Field>
      </div>

      {error && <p className="px-4 pb-2 text-sm text-negative">{error}</p>}

      {preview ? (
        <LinkConfirm
          preview={preview}
          busy={busy}
          onCancel={() => setPreview(null)}
          onConfirm={async () => {
            await apply("add_link", {
              predecessor: preview.predecessor,
              successor: preview.successor,
            });
            setPreview(null);
            setBefore("");
            setAfter("");
          }}
        />
      ) : (
        <div className="border-t border-border px-4 py-2.5">
          <Button
            size="sm"
            variant="outline"
            disabled={busy || !before || !after}
            onClick={async () => {
              setError("");
              try {
                setPreview(
                  await api.planner.copilot.linkPreview(detail.key, {
                    predecessor: before, successor: after,
                  }),
                );
              } catch (failure) {
                setError(
                  failure instanceof ApiError
                    ? failure.message
                    : "I could not work out what that link would do.",
                );
              }
            }}
          >
            Show me what that would do
          </Button>
        </div>
      )}
    </Panel>
  );
}

function CatalogueSelect({
  value,
  rows,
  onChange,
}: {
  value: string;
  rows: DraftCatalogueRow[];
  onChange: (code: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary"
    >
      <option value="">Choose…</option>
      {rows.map((row) => (
        <option key={row.code} value={row.code}>
          {row.code} — {row.name}
        </option>
      ))}
    </select>
  );
}

// ------------------------------------------------------------ completeness

/**
 * §19. Blockers and warnings are not the same thing and never look the same.
 *
 * A blocker stops publication and says what would satisfy it. A warning is
 * something a careful person would fix, and a plan where every gap stopped
 * publication is a plan nobody ever finishes drafting.
 */
function Completeness({ detail }: { detail: DraftDetail }) {
  const { blockers, warnings, publishable } = detail.completeness;
  return (
    <Panel title="What this plan still needs">
      {publishable && warnings.length === 0 && (
        <p className="px-4 py-4 text-sm text-positive">
          Nothing outstanding. The plan is complete.
        </p>
      )}
      {blockers.length > 0 && (
        <NoteList
          heading="Has to be settled before publishing"
          notes={blockers}
          tone="negative"
        />
      )}
      {warnings.length > 0 && (
        <NoteList
          heading="Worth a look, but will not stop you"
          notes={warnings}
          tone="warning"
        />
      )}
    </Panel>
  );
}

function NoteList({
  heading,
  notes,
  tone,
}: {
  heading: string;
  notes: DraftNote[];
  tone: "negative" | "warning";
}) {
  return (
    <div className="border-b border-border px-4 py-3 last:border-b-0">
      <p
        className={cn(
          "text-[11px] uppercase tracking-wide",
          tone === "negative" ? "text-negative" : "text-warning",
        )}
      >
        {heading}
      </p>
      <ul className="mt-1.5 space-y-1.5">
        {notes.map((note, index) => (
          <li key={`${note.scope}-${note.code}-${index}`} className="text-sm">
            <span className="text-text-primary">
              {note.code && (
                <span className="mr-2 font-mono text-xs text-text-muted">
                  {note.code}
                </span>
              )}
              {note.message}
            </span>
            {note.fix && (
              <span className="ml-1 text-text-muted">{note.fix}</span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

// ----------------------------------------------------------------- publish

/**
 * §20 and §21. The whole plan, then a confirmation that is a person's act.
 *
 * The preview is fetched rather than assembled here: what it shows is exactly
 * what publish will create, from the same server-side function, so the two
 * cannot drift.
 */
function PublishPanel({
  detail,
  onPublished,
}: {
  detail: DraftDetail;
  onPublished: (projectId: number) => void;
}) {
  const [preview, setPreview] = React.useState<
    Awaited<ReturnType<typeof api.planner.copilot.preview>> | null
  >(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  if (detail.status === "PUBLISHED") {
    return (
      <Panel title="Published">
        <p className="px-4 py-4 text-sm text-text-secondary">
          This plan is now project {detail.code}. Changes go through the
          project itself from here.
        </p>
      </Panel>
    );
  }

  return (
    <Panel
      title="Publish"
      note="Everything below is created in one go, or nothing is."
    >
      {error && <p className="px-4 pt-3 text-sm text-negative">{error}</p>}

      {!preview ? (
        <div className="px-4 py-4">
          <Button
            disabled={busy}
            onClick={async () => {
              setBusy(true);
              setError("");
              try {
                setPreview(await api.planner.copilot.preview(detail.key));
              } catch (failure) {
                setError(
                  failure instanceof ApiError
                    ? failure.message
                    : "I could not build the preview.",
                );
              } finally {
                setBusy(false);
              }
            }}
          >
            Show me the whole plan
          </Button>
        </div>
      ) : (
        <div className="space-y-3 px-4 py-4">
          <p className="text-sm text-text-secondary">
            {preview.totals.milestones} milestones, {preview.totals.tasks}{" "}
            tasks, {preview.totals.links} dependencies, {preview.totals.people}{" "}
            people.
          </p>
          <p className="text-sm text-text-muted">{preview.agentic.sentence}</p>
          <ol className="space-y-2">
            {preview.milestones.map((milestone) => (
              <li
                key={String(milestone.code)}
                className="rounded-md border border-border bg-surface-raised px-3 py-2"
              >
                <p className="text-sm font-medium text-text-primary">
                  <span className="mr-2 font-mono text-xs text-text-muted">
                    {String(milestone.code)}
                  </span>
                  {String(milestone.name)}
                </p>
                <p className="mt-0.5 text-xs text-text-muted">
                  Escalates to{" "}
                  {milestone.escalation.source === "project"
                    ? "the project's contact"
                    : milestone.escalation.source === "milestone"
                      ? `the contact on ${milestone.escalation.from_code}`
                      : "its own contact"}
                </p>
                <ul className="mt-1.5 space-y-0.5">
                  {milestone.tasks.map((task) => (
                    <li key={String(task.code)} className="text-xs text-text-secondary">
                      <span className="mr-2 font-mono text-text-muted">
                        {String(task.code)}
                      </span>
                      {String(task.title)} · due {String(task.due_date ?? "—")}
                    </li>
                  ))}
                </ul>
              </li>
            ))}
          </ol>
          {preview.links.length > 0 && (
            <ul className="space-y-1">
              {preview.links.map((link) => (
                <li
                  key={`${link.predecessor}-${link.successor}`}
                  className="text-xs text-text-muted"
                >
                  {link.sentence}
                </li>
              ))}
            </ul>
          )}
          <div className="flex items-center gap-2 pt-1">
            <Button
              disabled={busy || !preview.completeness.publishable}
              onClick={async () => {
                setBusy(true);
                setError("");
                try {
                  const made = await api.planner.copilot.publish(
                    detail.key, true);
                  onPublished(made.project_id);
                } catch (failure) {
                  setError(
                    failure instanceof ApiError
                      ? failure.message
                      : "The project was not created.",
                  );
                } finally {
                  setBusy(false);
                }
              }}
            >
              Yes, create this project
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => setPreview(null)}
            >
              Not yet
            </Button>
          </div>
          {!preview.completeness.publishable && (
            <p className="text-xs text-text-muted">
              {preview.completeness.blockers.length} things still have to be
              settled first.
            </p>
          )}
        </div>
      )}
    </Panel>
  );
}
