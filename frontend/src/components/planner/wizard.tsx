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
  type DraftPreview,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Setting a project up, one decision at a time.
 *
 * The page this replaces put every panel of the plan on the screen at once
 * and left the person to work out which of them mattered first. UAT found
 * exactly that: an enormous unstructured page. So the same plan is now asked
 * for in eight steps, in the order somebody actually decides — what the
 * project is, who is answerable, how hard the agent chases, the milestones,
 * the work under them, what waits for what, the whole thing read back, and
 * then one deliberate Publish.
 *
 * Two rules hold throughout.
 *
 * **The server is the plan.** Every control calls `api.planner.plan.apply`
 * with a named command, and the step re-reads the draft afterwards. There is
 * no client-side copy to reconcile, so Save Draft is not a separate save — by
 * the time you press it there is nothing unsaved except the box you are
 * typing in, which the step saves on its way forward.
 *
 * **Next validates.** Moving forward saves the step and then reads the
 * server's own completeness notes for that step. A wizard that let you walk
 * past a missing sponsor and told you about it on step eight would be the
 * same unstructured page with extra clicks.
 */

type Row = Record<string, unknown>;

const text = (row: Row, key: string) => String(row[key] ?? "");
const num = (row: Row, key: string): number | null => {
  const found = row[key];
  return found === null || found === undefined || found === "" ? null
    : Number(found);
};

/** The eight steps, and which completeness scopes belong to each. */
export const STEPS = [
  { key: "OVERVIEW", n: 1, title: "Overview",
    detail: "What this project is and what it has to achieve.",
    scopes: ["overview"] },
  { key: "GOVERNANCE", n: 2, title: "People & governance",
    detail: "Who sponsors it, who runs it, and who hears about a delay.",
    scopes: ["governance"] },
  { key: "AGENTIC", n: 3, title: "Agentic AI policy",
    detail: "When the agent chases somebody, and who it escalates to.",
    scopes: ["agentic"] },
  { key: "MILESTONES", n: 4, title: "Major milestones",
    detail: "The dates somebody is answerable for.",
    scopes: ["milestones", "milestone"] },
  { key: "TASKS", n: 5, title: "Tasks",
    detail: "The work under each milestone, with an owner and a due date.",
    scopes: ["task"] },
  { key: "DEPENDENCIES", n: 6, title: "Dependencies",
    detail: "What has to finish before something else can start.",
    scopes: ["link"] },
  { key: "REVIEW", n: 7, title: "Preview",
    detail: "The whole plan, read back before anything is created.",
    scopes: [] },
  { key: "PUBLISH", n: 8, title: "Publish",
    detail: "Create the project. All of it, or none of it.",
    scopes: [] },
] as const;

export type StepKey = (typeof STEPS)[number]["key"];

/** The server stores seven steps; Publish is the eighth screen of Review. */
const SERVER_STEP: Record<StepKey, string> = {
  OVERVIEW: "OVERVIEW", GOVERNANCE: "GOVERNANCE", AGENTIC: "AGENTIC",
  MILESTONES: "MILESTONES", TASKS: "TASKS", DEPENDENCIES: "DEPENDENCIES",
  REVIEW: "REVIEW", PUBLISH: "REVIEW",
};

function stepIndex(key: string): number {
  const found = STEPS.findIndex((step) => step.key === key);
  return found < 0 ? 0 : found;
}

export function ProjectWizard({
  detail,
  people,
  onChanged,
  onPublished,
  onSaved,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  onChanged: () => void;
  onPublished: (projectId: number) => void;
  onSaved: () => void;
}) {
  // Names to print come from the plan itself; the `people` prop is only the
  // handful offered before anybody searches.
  const named = React.useMemo(
    () => {
      const rows = [...(detail.people ?? [])];
      for (const person of people) {
        if (!rows.some((row) => row.user_id === person.user_id)) {
          rows.push(person);
        }
      }
      return rows;
    },
    [detail.people, people]);
  const [at, setAt] = React.useState(() => stepIndex(detail.step));
  const [error, setError] = React.useState("");
  const [blockers, setBlockers] = React.useState<DraftNote[]>([]);
  const [busy, setBusy] = React.useState(false);
  const step = STEPS[at];

  const apply = React.useCallback(
    async (command: string, payload: Row = {}) => {
      setBusy(true);
      setError("");
      try {
        await api.planner.plan.apply(detail.key, command, payload,
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

  /**
   * A step's own gate: save what is on screen, then read the server's
   * blockers for the scopes this step is responsible for.
   *
   * Each step registers its saver here rather than the wizard reaching into
   * the step's state, so the step that knows what a valid Overview is is the
   * one that decides whether Overview is valid.
   */
  const saver = React.useRef<null | (() => Promise<boolean>)>(null);
  const register = React.useCallback(
    (fn: null | (() => Promise<boolean>)) => { saver.current = fn; }, []);

  const goto = React.useCallback(async (next: number) => {
    setError("");
    setBlockers([]);
    if (next > at) {
      if (saver.current && !(await saver.current())) return;
      const fresh = await api.planner.plan.draft(detail.key);
      const scopes = STEPS[at].scopes as readonly string[];
      const stopping = fresh.completeness.blockers.filter(
        (note) => scopes.includes(note.scope));
      if (stopping.length > 0) {
        setBlockers(stopping);
        onChanged();
        return;
      }
    }
    const target = STEPS[Math.max(0, Math.min(STEPS.length - 1, next))];
    await api.planner.plan.apply(detail.key, "set_step",
                                 { step: SERVER_STEP[target.key] });
    setAt(stepIndex(target.key));
    onChanged();
  }, [at, detail.key, onChanged]);

  const saveDraft = React.useCallback(async () => {
    setError("");
    if (saver.current && !(await saver.current())) return;
    await api.planner.plan.apply(detail.key, "set_step",
                                 { step: SERVER_STEP[step.key] });
    onSaved();
  }, [detail.key, onSaved, step.key]);

  return (
    <div className="space-y-4">
      <StepRail at={at} onJump={(index) => void goto(index)} />

      <section className="overflow-hidden rounded-lg border border-border bg-surface">
        <header className="border-b border-border px-4 py-3">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">
            Step {step.n} of {STEPS.length}
          </p>
          <h2 className="text-base font-semibold text-text-primary">
            {step.title}
          </h2>
          <p className="mt-0.5 text-xs text-text-secondary">{step.detail}</p>
        </header>

        {error && (
          <p role="alert"
             className="border-b border-border bg-negative/10 px-4 py-2 text-sm text-negative">
            {error}
          </p>
        )}
        {blockers.length > 0 && (
          <div role="alert" className="border-b border-border bg-negative/5 px-4 py-3">
            <p className="text-[11px] uppercase tracking-wide text-negative">
              This step is not finished
            </p>
            <ul className="mt-1.5 space-y-1">
              {blockers.map((note, index) => (
                <li key={index} className="text-sm text-text-primary">
                  {note.code && (
                    <span className="mr-2 font-mono text-xs text-text-muted">
                      {note.code}
                    </span>
                  )}
                  {note.message}
                  {note.fix && (
                    <span className="ml-1 text-text-muted">{note.fix}</span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="px-4 py-4">
          {step.key === "OVERVIEW" && (
            <OverviewStep key={`o${detail.version}`} detail={detail}
                          apply={apply} register={register} />
          )}
          {step.key === "GOVERNANCE" && (
            <GovernanceStep key={`g${detail.version}`} detail={detail}
                            people={named} apply={apply}
                            register={register} />
          )}
          {step.key === "AGENTIC" && (
            <AgenticStep detail={detail} apply={apply} busy={busy}
                         register={register} />
          )}
          {step.key === "MILESTONES" && (
            <MilestonesStep detail={detail} people={named} apply={apply}
                            busy={busy} register={register} />
          )}
          {step.key === "TASKS" && (
            <TasksStep detail={detail} people={named} apply={apply}
                       busy={busy} register={register} />
          )}
          {step.key === "DEPENDENCIES" && (
            <DependenciesStep detail={detail} apply={apply} busy={busy}
                              register={register} />
          )}
          {step.key === "REVIEW" && (
            <PreviewStep detail={detail} people={named} register={register} />
          )}
          {step.key === "PUBLISH" && (
            <PublishStep detail={detail} onPublished={onPublished}
                         register={register} />
          )}
        </div>

        <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          <Button variant="outline" size="sm" disabled={busy || at === 0}
                  onClick={() => void goto(at - 1)}>
            Back
          </Button>
          {at < STEPS.length - 1 && (
            <Button size="sm" disabled={busy} onClick={() => void goto(at + 1)}>
              Next
            </Button>
          )}
          <Button variant="ghost" size="sm" disabled={busy}
                  onClick={() => void saveDraft()}>
            Save draft
          </Button>
          <span className="ml-auto text-xs text-text-muted">
            Saved {detail.version} {detail.version === 1 ? "time" : "times"} ·
            nothing exists until you publish.
          </span>
        </footer>
      </section>
    </div>
  );
}

/** Where you are, and how to get back to a step you have already passed. */
function StepRail({ at, onJump }: { at: number; onJump: (n: number) => void }) {
  return (
    <ol className="flex flex-wrap gap-1.5" aria-label="Project setup steps">
      {STEPS.map((step, index) => {
        const state = index === at ? "current"
          : index < at ? "done" : "todo";
        return (
          <li key={step.key}>
            <button
              type="button"
              aria-current={state === "current" ? "step" : undefined}
              disabled={state === "todo"}
              onClick={() => onJump(index)}
              className={cn(
                "rounded-md border px-2.5 py-1.5 text-xs transition",
                state === "current" && "border-accent bg-accent-muted text-text-primary",
                state === "done" && "border-border bg-surface text-text-secondary hover:border-accent",
                state === "todo" && "border-border bg-surface text-text-muted",
              )}
            >
              <span className="font-mono">{step.n}</span>
              <span className="ml-1.5">{step.title}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

// ------------------------------------------------------------------- shell

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
      {hint && (
        <span className="mt-0.5 block text-xs text-text-muted">{hint}</span>
      )}
    </label>
  );
}

/**
 * Naming a colleague, on an installation with more people than a list.
 *
 * A plain select over the directory works until the directory is a bank's:
 * then the person you want is the six hundredth name alphabetically, the
 * list does not contain them, and the form cannot be completed at all. So
 * this searches. The people already on the plan are offered without typing,
 * because most of the time the next name is one of the last few.
 */
function PersonSelect({
  value,
  people,
  onChange,
  label,
}: {
  value: number | null;
  /** Everybody already named on this plan, offered before any search. */
  people: CopilotPerson[];
  onChange: (id: number | null) => void;
  label?: string;
}) {
  const [search, setSearch] = React.useState("");
  const [query, setQuery] = React.useState("");

  React.useEffect(() => {
    const timer = setTimeout(() => setQuery(search.trim()), 250);
    return () => clearTimeout(timer);
  }, [search]);

  const found = useAsync(
    () => api.planner.plan.people(query, 50), [query]);

  // The chosen person always stays in the list, whatever the search says:
  // a select that dropped its own value while somebody typed would silently
  // unassign them.
  const chosen = [...people, ...(found.data?.people ?? [])]
    .find((person) => person.user_id === value);
  const options: CopilotPerson[] = [];
  for (const person of [...(chosen ? [chosen] : []), ...people,
                        ...(found.data?.people ?? [])]) {
    if (!options.some((row) => row.user_id === person.user_id)) {
      options.push(person);
    }
  }

  return (
    <>
      <Input
        value={search}
        aria-label={label ? `Find ${label}` : "Find a person"}
        placeholder="Type a name to search"
        className="mt-1 h-8 text-xs"
        onChange={(event) => setSearch(event.target.value)}
      />
      <select
        value={value ?? ""}
        aria-label={label}
        onChange={(event) =>
          onChange(event.target.value ? Number(event.target.value) : null)}
        className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary"
      >
        <option value="">Nobody yet</option>
        {options.map((person) => (
          <option key={person.user_id} value={person.user_id}>
            {person.name} ({person.username})
          </option>
        ))}
      </select>
    </>
  );
}

function nameOf(people: CopilotPerson[], id: number | null): string {
  if (!id) return "";
  return people.find((person) => person.user_id === id)?.name ?? "";
}

type Apply = (command: string, payload?: Row) => Promise<boolean>;
type Register = (fn: null | (() => Promise<boolean>)) => void;

/**
 * Give the wizard this step's saver, and take it back when the step leaves.
 *
 * A ref rather than state, and an effect rather than a render-time call,
 * because the wizard reads it when Next is pressed and never during render.
 */
function useSaver(register: Register, fn: () => Promise<boolean>) {
  const latest = React.useRef(fn);
  React.useEffect(() => { latest.current = fn; });
  React.useEffect(() => {
    register(() => latest.current());
    return () => register(null);
  }, [register]);
}

// -------------------------------------------------------------- 1 overview

function OverviewStep({
  detail,
  apply,
  register,
}: {
  detail: DraftDetail;
  apply: Apply;
  register: Register;
}) {
  const [form, setForm] = React.useState(detail.plan.overview);
  const [taken, setTaken] = React.useState("");

  useSaver(register, async () => {
    setTaken("");
    if (!form.name.trim()) return false;
    const wanted = form.code.trim();
    if (wanted) {
      // §7. The duplicate is caught here rather than at publish, because
      // finding out on step eight that the code is taken means redoing the
      // one field a person cannot easily change afterwards.
      try {
        const check = await api.planner.plan.codeAvailable(wanted);
        if (!check.available) {
          setTaken(`Code ${wanted} is already used by ${check.used_by}. ` +
                   "Codes are unique across the platform.");
          return false;
        }
      } catch {
        // A failed check must not block a plan; publish checks it again.
      }
    }
    return apply("set_overview", { ...form });
  });

  return (
    <div className="space-y-3">
      {taken && (
        <p role="alert" className="rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {taken}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Project name">
          <Input value={form.name}
                 placeholder="LGD Model Redevelopment"
                 onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </Field>
        <Field label="Project code"
               hint="How people refer to it in exports, messages and reports.">
          <Input value={form.code}
                 placeholder="LGDMR-2026"
                 onChange={(e) => setForm({ ...form, code: e.target.value })} />
        </Field>
        <Field label="Description">
          <Input value={form.description}
                 onChange={(e) =>
                   setForm({ ...form, description: e.target.value })} />
        </Field>
        <Field label="Objective"
               hint="What has to be true for this to be finished?">
          <Input value={form.objective}
                 onChange={(e) =>
                   setForm({ ...form, objective: e.target.value })} />
        </Field>
      </div>
    </div>
  );
}

// ------------------------------------------------------------ 2 governance

function GovernanceStep({
  detail,
  people,
  apply,
  register,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  apply: Apply;
  register: Register;
}) {
  const [form, setForm] = React.useState(detail.plan.governance);
  const [local, setLocal] = React.useState("");

  useSaver(register, async () => {
    setLocal("");
    if (form.start_date && form.target_end_date
        && form.target_end_date < form.start_date) {
      setLocal(`Target completion (${form.target_end_date}) is before the ` +
               `start date (${form.start_date}).`);
      return false;
    }
    return apply("set_governance", { ...form });
  });

  return (
    <div className="space-y-3">
      {local && (
        <p role="alert" className="rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {local}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Sponsor" hint="Accountable for the project existing.">
          <PersonSelect label="Sponsor" value={form.sponsor_id} people={people}
                        onChange={(id) => setForm({ ...form, sponsor_id: id })} />
        </Field>
        <Field label="Project manager" hint="Runs it day to day.">
          <PersonSelect label="Project manager" value={form.manager_id}
                        people={people}
                        onChange={(id) => setForm({ ...form, manager_id: id })} />
        </Field>
        <Field label="Owner" hint="Often the manager. Say so explicitly.">
          <PersonSelect label="Owner" value={form.owner_id} people={people}
                        onChange={(id) => setForm({ ...form, owner_id: id })} />
        </Field>
        <Field label="Escalation contact"
               hint="The last stop when a milestone's own contact has not resolved something.">
          <PersonSelect label="Escalation contact" value={form.escalation_id}
                        people={people}
                        onChange={(id) =>
                          setForm({ ...form, escalation_id: id })} />
        </Field>
        <Field label="Start date">
          <Input type="date" value={form.start_date ?? ""}
                 onChange={(e) =>
                   setForm({ ...form, start_date: e.target.value })} />
        </Field>
        <Field label="Target completion">
          <Input type="date" value={form.target_end_date ?? ""}
                 onChange={(e) =>
                   setForm({ ...form, target_end_date: e.target.value })} />
        </Field>
        <Field label="Priority">
          <select value={form.priority} aria-label="Priority"
                  onChange={(e) =>
                    setForm({ ...form, priority: e.target.value })}
                  className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary">
            {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((level) => (
              <option key={level} value={level}>{level}</option>
            ))}
          </select>
        </Field>
        <Field label="Reporting cadence">
          <select value={form.reporting_cadence} aria-label="Reporting cadence"
                  onChange={(e) =>
                    setForm({ ...form, reporting_cadence: e.target.value })}
                  className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary">
            {["DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY"].map((cadence) => (
              <option key={cadence} value={cadence}>{cadence}</option>
            ))}
          </select>
        </Field>
      </div>
      <p className="text-xs text-text-muted">
        Everybody named here is seated on the project when it is published, so
        the person the agent chases can open what they are being chased about.
      </p>
    </div>
  );
}

// --------------------------------------------------------------- 3 agentic

function AgenticStep({
  detail,
  apply,
  busy,
  register,
}: {
  detail: DraftDetail;
  apply: Apply;
  busy: boolean;
  register: Register;
}) {
  const chosen = detail.plan.agentic?.mode ?? "STANDARD";
  useSaver(register, async () => true);

  return (
    <div className="space-y-3">
      <p className="text-sm text-text-secondary">
        The agent watches dates deterministically — it does not decide what is
        late, it applies these rules. This choice decides how soon it chases
        and how far it escalates.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {detail.agentic_choices.map((choice) => (
          <button
            key={choice.mode}
            type="button"
            disabled={busy}
            aria-pressed={choice.mode === chosen}
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
    </div>
  );
}

// ------------------------------------------------------------ 4 milestones

function MilestonesStep({
  detail,
  people,
  apply,
  busy,
  register,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  apply: Apply;
  busy: boolean;
  register: Register;
}) {
  const [form, setForm] = React.useState<Row>({ name: "" });
  const [editing, setEditing] = React.useState("");
  useSaver(register, async () => true);

  const milestones = detail.plan.milestones ?? [];

  return (
    <div className="space-y-4">
      <ol className="space-y-2">
        {milestones.map((milestone, index) => {
          const code = text(milestone, "code");
          const escalation = nameOf(people, num(milestone, "escalation_id"))
            || nameOf(people, detail.plan.governance.escalation_id);
          const inherited = !num(milestone, "escalation_id");
          return (
            <li key={code}
                className="rounded-md border border-border bg-surface-raised px-3 py-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm font-medium text-text-primary">
                    <span className="mr-2 font-mono text-xs text-text-muted">
                      {code}
                    </span>
                    {text(milestone, "name")}
                  </p>
                  <p className="mt-0.5 text-xs text-text-muted">
                    {text(milestone, "start_date") || "no start"} →{" "}
                    {text(milestone, "target_date") || "no target date"} ·
                    owner {nameOf(people, num(milestone, "owner_id"))
                      || "not named"}
                  </p>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    Escalation: {escalation || "nobody yet"}
                    {escalation && inherited
                      ? " — inherited from the project" : ""}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost" disabled={busy || index === 0}
                          onClick={() =>
                            void apply("move_milestone",
                                       { code, direction: "up" })}>
                    Move up
                  </Button>
                  <Button size="sm" variant="ghost"
                          disabled={busy || index === milestones.length - 1}
                          onClick={() =>
                            void apply("move_milestone",
                                       { code, direction: "down" })}>
                    Move down
                  </Button>
                  <Button size="sm" variant="ghost"
                          onClick={() =>
                            setEditing(editing === code ? "" : code)}>
                    {editing === code ? "Close" : "Edit"}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy}
                          onClick={() =>
                            void apply("remove_milestone", { code })}>
                    Remove
                  </Button>
                </div>
              </div>
              {editing === code && (
                <MilestoneEditor key={`${code}-${detail.version}`}
                                 milestone={milestone} people={people}
                                 apply={apply} busy={busy} />
              )}
            </li>
          );
        })}
        {milestones.length === 0 && (
          <li className="rounded-md border border-dashed border-border px-3 py-4 text-sm text-text-muted">
            No milestones yet. A project with no milestone has nothing to be
            judged against.
          </li>
        )}
      </ol>

      <div className="rounded-md border border-border px-3 py-3">
        <p className="text-[11px] uppercase tracking-wide text-text-muted">
          Add a milestone
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-4">
          <Field label="Milestone name">
            <Input value={text(form, "name")} placeholder="Data foundation"
                   onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </Field>
          <Field label="Milestone owner">
            <PersonSelect label="Milestone owner" value={num(form, "owner_id")}
                          people={people}
                          onChange={(id) => setForm({ ...form, owner_id: id })} />
          </Field>
          <Field label="Milestone start">
            <Input type="date" value={text(form, "start_date")}
                   onChange={(e) =>
                     setForm({ ...form, start_date: e.target.value })} />
          </Field>
          <Field label="Milestone target date">
            <Input type="date" value={text(form, "target_date")}
                   onChange={(e) =>
                     setForm({ ...form, target_date: e.target.value })} />
          </Field>
        </div>
        <Button size="sm" className="mt-3"
                disabled={busy || !text(form, "name").trim()}
                onClick={async () => {
                  if (await apply("add_milestone", { ...form })) {
                    setForm({ name: "" });
                  }
                }}>
          Add milestone
        </Button>
      </div>
    </div>
  );
}

function MilestoneEditor({
  milestone,
  people,
  apply,
  busy,
}: {
  milestone: Row;
  people: CopilotPerson[];
  apply: Apply;
  busy: boolean;
}) {
  const [form, setForm] = React.useState(milestone);
  const code = text(milestone, "code");
  return (
    <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
      <Field label="Name">
        <Input value={text(form, "name")}
               onChange={(e) => setForm({ ...form, name: e.target.value })} />
      </Field>
      <Field label="Owner">
        <PersonSelect label="Owner" value={num(form, "owner_id")} people={people}
                      onChange={(id) => setForm({ ...form, owner_id: id })} />
      </Field>
      <Field label="Starts">
        <Input type="date" value={text(form, "start_date")}
               onChange={(e) =>
                 setForm({ ...form, start_date: e.target.value })} />
      </Field>
      <Field label="Target date">
        <Input type="date" value={text(form, "target_date")}
               onChange={(e) =>
                 setForm({ ...form, target_date: e.target.value })} />
      </Field>
      <Field label="Critical date"
             hint="After this it cannot recover. Not the target date.">
        <Input type="date" value={text(form, "critical_date")}
               onChange={(e) =>
                 setForm({ ...form, critical_date: e.target.value })} />
      </Field>
      <Field label="Escalation contact"
             hint="Leave empty to inherit the project's.">
        <PersonSelect label="Escalation contact"
                      value={num(form, "escalation_id")} people={people}
                      onChange={(id) =>
                        setForm({ ...form, escalation_id: id })} />
      </Field>
      <div className="sm:col-span-2">
        <Button size="sm" disabled={busy}
                onClick={() => void apply("update_milestone", { ...form, code })}>
          Save milestone
        </Button>
      </div>
    </div>
  );
}

// ----------------------------------------------------------------- 5 tasks

function TasksStep({
  detail,
  people,
  apply,
  busy,
  register,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  apply: Apply;
  busy: boolean;
  register: Register;
}) {
  useSaver(register, async () => true);
  const milestones = detail.plan.milestones ?? [];
  const tasks = detail.plan.tasks ?? [];

  if (milestones.length === 0) {
    return (
      <p className="text-sm text-text-muted">
        Add a milestone first — every task belongs to one.
      </p>
    );
  }

  return (
    <div className="space-y-4">
      {milestones.map((milestone) => {
        const code = text(milestone, "code");
        return (
          <MilestoneTasks
            key={`${code}-${detail.version}`}
            milestone={milestone}
            tasks={tasks.filter(
              (task) => text(task, "milestone_code") === code)}
            people={people}
            plan={detail.plan}
            apply={apply}
            busy={busy}
          />
        );
      })}
    </div>
  );
}

function MilestoneTasks({
  milestone,
  tasks,
  people,
  plan,
  apply,
  busy,
}: {
  milestone: Row;
  tasks: Row[];
  people: CopilotPerson[];
  plan: DraftDetail["plan"];
  apply: Apply;
  busy: boolean;
}) {
  const code = text(milestone, "code");
  const [form, setForm] = React.useState<Row>({ title: "" });
  const [editing, setEditing] = React.useState("");

  const escalationFor = (task: Row) => {
    const own = num(task, "escalation_id");
    if (own) return { name: nameOf(people, own), from: "" };
    const parent = num(milestone, "escalation_id");
    if (parent) {
      return {
        name: nameOf(people, parent),
        from: `inherited from milestone ${text(milestone, "name") || code}`,
      };
    }
    return {
      name: nameOf(people, plan.governance.escalation_id),
      from: "inherited from the project",
    };
  };

  return (
    <section className="rounded-md border border-border">
      <header className="border-b border-border px-3 py-2">
        <p className="text-sm font-medium text-text-primary">
          <span className="mr-2 font-mono text-xs text-text-muted">{code}</span>
          {text(milestone, "name")}
        </p>
        <p className="mt-0.5 text-xs text-text-muted">
          due {text(milestone, "target_date") || "no target date"} ·{" "}
          {tasks.length} {tasks.length === 1 ? "task" : "tasks"}
        </p>
      </header>

      <ul className="divide-y divide-border">
        {tasks.map((task) => {
          const taskCode = text(task, "code");
          const escalation = escalationFor(task);
          return (
            <li key={taskCode} className="px-3 py-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <div className="min-w-0">
                  <p className="text-sm text-text-primary">
                    <span className="mr-2 font-mono text-xs text-text-muted">
                      {taskCode}
                    </span>
                    {text(task, "title")}
                  </p>
                  <p className="mt-0.5 text-xs text-text-muted">
                    owner {nameOf(people, num(task, "owner_id")) || "not named"}
                    {" · due "}{text(task, "due_date") || "no due date"}
                  </p>
                  <p className="mt-0.5 text-xs text-text-secondary">
                    Escalation: {escalation.name || "nobody yet"}
                    {escalation.name && escalation.from
                      ? ` — ${escalation.from}` : ""}
                  </p>
                </div>
                <div className="flex shrink-0 gap-1">
                  <Button size="sm" variant="ghost"
                          onClick={() =>
                            setEditing(editing === taskCode ? "" : taskCode)}>
                    {editing === taskCode ? "Close" : "Edit"}
                  </Button>
                  <Button size="sm" variant="ghost" disabled={busy}
                          onClick={() =>
                            void apply("remove_task", { code: taskCode })}>
                    Remove
                  </Button>
                </div>
              </div>
              {editing === taskCode && (
                <TaskEditor task={task} people={people} apply={apply}
                            busy={busy} />
              )}
            </li>
          );
        })}
        {tasks.length === 0 && (
          <li className="px-3 py-2.5 text-xs text-text-muted">
            No tasks under this milestone yet.
          </li>
        )}
      </ul>

      <div className="border-t border-border px-3 py-3">
        <div className="grid gap-3 sm:grid-cols-5">
          <Field label="Task title">
            <Input value={text(form, "title")}
                   placeholder="Extract recovery history"
                   onChange={(e) =>
                     setForm({ ...form, title: e.target.value })} />
          </Field>
          <Field label="Task description">
            <Input value={text(form, "description")}
                   onChange={(e) =>
                     setForm({ ...form, description: e.target.value })} />
          </Field>
          <Field label="Task owner">
            <PersonSelect label="Task owner" value={num(form, "owner_id")}
                          people={people}
                          onChange={(id) => setForm({ ...form, owner_id: id })} />
          </Field>
          <Field label="Task start">
            <Input type="date" value={text(form, "start_date")}
                   onChange={(e) =>
                     setForm({ ...form, start_date: e.target.value })} />
          </Field>
          <Field label="Task due date">
            <Input type="date" value={text(form, "due_date")}
                   onChange={(e) =>
                     setForm({ ...form, due_date: e.target.value })} />
          </Field>
        </div>
        <Button size="sm" className="mt-3"
                disabled={busy || !text(form, "title").trim()}
                onClick={async () => {
                  const added = await apply("add_task",
                                            { ...form, milestone_code: code });
                  if (added) setForm({ title: "" });
                }}>
          Add task
        </Button>
      </div>
    </section>
  );
}

function TaskEditor({
  task,
  people,
  apply,
  busy,
}: {
  task: Row;
  people: CopilotPerson[];
  apply: Apply;
  busy: boolean;
}) {
  const [form, setForm] = React.useState(task);
  const code = text(task, "code");
  return (
    <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-3">
      <Field label="Title">
        <Input value={text(form, "title")}
               onChange={(e) => setForm({ ...form, title: e.target.value })} />
      </Field>
      <Field label="Description"
             hint="The owner reads this when the agent reminds them.">
        <Input value={text(form, "description")}
               onChange={(e) =>
                 setForm({ ...form, description: e.target.value })} />
      </Field>
      <Field label="Owner">
        <PersonSelect label="Owner" value={num(form, "owner_id")} people={people}
                      onChange={(id) => setForm({ ...form, owner_id: id })} />
      </Field>
      <Field label="Starts">
        <Input type="date" value={text(form, "start_date")}
               onChange={(e) =>
                 setForm({ ...form, start_date: e.target.value })} />
      </Field>
      <Field label="Due">
        <Input type="date" value={text(form, "due_date")}
               onChange={(e) =>
                 setForm({ ...form, due_date: e.target.value })} />
      </Field>
      <Field label="Escalation contact"
             hint="Leave empty to inherit the milestone's.">
        <PersonSelect label="Escalation contact"
                      value={num(form, "escalation_id")} people={people}
                      onChange={(id) =>
                        setForm({ ...form, escalation_id: id })} />
      </Field>
      <div className="sm:col-span-3">
        <Button size="sm" disabled={busy}
                onClick={() => void apply("update_task", { ...form, code })}>
          Save task
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------- 6 dependencies

/**
 * §11. A dependency states its impact, then the person decides.
 *
 * Three answers, and the middle one is the point: keeping the dates and
 * flagging the conflict is a legitimate decision that has to survive into the
 * published project, so it is written onto the link rather than shown once
 * and forgotten. Nothing here ever moves a date that was not asked for.
 */
function DependenciesStep({
  detail,
  apply,
  busy,
  register,
}: {
  detail: DraftDetail;
  apply: Apply;
  busy: boolean;
  register: Register;
}) {
  const [before, setBefore] = React.useState("");
  const [after, setAfter] = React.useState("");
  const [preview, setPreview] = React.useState<DraftLinkPreview | null>(null);
  const [error, setError] = React.useState("");
  useSaver(register, async () => true);

  const label = (code: string) =>
    detail.catalogue.find((row) => row.code === code)?.name ?? code;

  const settle = async (adjust: boolean) => {
    if (!preview) return;
    const done = await apply("add_link", {
      predecessor: preview.predecessor,
      successor: preview.successor,
      adjust,
    });
    if (done) {
      setPreview(null);
      setBefore("");
      setAfter("");
    }
  };

  const adjustment = preview && "days" in preview.adjustment
    ? preview.adjustment : null;

  return (
    <div className="space-y-4">
      <ul className="divide-y divide-border rounded-md border border-border">
        {detail.plan.links.map((link) => (
          <li key={`${link.predecessor}-${link.successor}`}
              className="flex items-start justify-between gap-3 px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-sm text-text-primary">
                {label(link.successor)} waits for {label(link.predecessor)}
              </p>
              {link.notes && (
                <p className="mt-0.5 text-xs text-warning">{link.notes}</p>
              )}
            </div>
            <Button size="sm" variant="ghost" disabled={busy}
                    onClick={() =>
                      void apply("remove_link", {
                        predecessor: link.predecessor,
                        successor: link.successor,
                      })}>
              Unlink
            </Button>
          </li>
        ))}
        {detail.plan.links.length === 0 && (
          <li className="px-3 py-3 text-sm text-text-muted">
            Nothing waits for anything yet. That is a valid plan; it just means
            everything can run at once.
          </li>
        )}
      </ul>

      <div className="rounded-md border border-border px-3 py-3">
        <p className="text-[11px] uppercase tracking-wide text-text-muted">
          Add a dependency
        </p>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <Field label="This has to finish first">
            <CatalogueSelect label="This has to finish first" value={before}
                             rows={detail.catalogue} onChange={setBefore} />
          </Field>
          <Field label="Before this can start">
            <CatalogueSelect label="Before this can start" value={after}
                             rows={detail.catalogue} onChange={setAfter} />
          </Field>
        </div>

        {error && (
          <p role="alert" className="mt-2 text-sm text-negative">{error}</p>
        )}

        {!preview ? (
          <Button size="sm" variant="outline" className="mt-3"
                  disabled={busy || !before || !after}
                  onClick={async () => {
                    setError("");
                    try {
                      setPreview(
                        await api.planner.plan.linkPreview(detail.key, {
                          predecessor: before, successor: after,
                        }));
                    } catch (failure) {
                      setError(failure instanceof ApiError
                        ? failure.message
                        : "I could not work out what that link would do.");
                    }
                  }}>
            Show the impact
          </Button>
        ) : (
          <div className="mt-3 rounded-md border border-border bg-surface-raised px-3 py-3">
            <p className="text-sm text-text-primary">{preview.sentence}</p>
            {preview.conflict && (
              <p className="mt-1 text-sm text-warning">{preview.conflict}</p>
            )}
            {adjustment && (
              <>
                <p className="mt-1 text-sm text-text-secondary">
                  {adjustment.sentence}
                </p>
                <ul className="mt-1.5 space-y-0.5">
                  {adjustment.items.map((shift) => (
                    <li key={shift.code} className="text-xs text-text-muted">
                      <span className="mr-2 font-mono">{shift.code}</span>
                      {shift.label}:{" "}
                      {shift.due_date || shift.target_date || "—"} →{" "}
                      {shift.new_due_date || shift.new_target_date || "—"}
                    </li>
                  ))}
                </ul>
              </>
            )}
            <div className="mt-3 flex flex-wrap gap-2">
              {adjustment && (
                <Button size="sm" disabled={busy}
                        onClick={() => void settle(true)}>
                  Adjust dates
                </Button>
              )}
              <Button size="sm" variant={adjustment ? "outline" : "default"}
                      disabled={busy} onClick={() => void settle(false)}>
                {preview.conflict
                  ? "Keep dates and flag conflict"
                  : "Create the dependency"}
              </Button>
              <Button size="sm" variant="ghost" disabled={busy}
                      onClick={() => setPreview(null)}>
                Cancel
              </Button>
            </div>
          </div>
        )}
      </div>
      <p className="text-xs text-text-muted">
        A link that would make a loop is refused, and so is a link that already
        exists or one that points at itself.
      </p>
    </div>
  );
}

function CatalogueSelect({
  value,
  rows,
  onChange,
  label,
}: {
  value: string;
  rows: DraftCatalogueRow[];
  onChange: (code: string) => void;
  label: string;
}) {
  return (
    <select
      value={value}
      aria-label={label}
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

// --------------------------------------------------------------- 7 preview

/**
 * §12 and §13. The whole plan read back, and what it still needs.
 *
 * Fetched from the server rather than assembled here, from the same function
 * publish uses, so the preview and the publication cannot drift. The
 * completeness list is split the way §13 asks: what stops a publish, and what
 * a careful person would fix anyway.
 */
function PreviewStep({
  detail,
  people,
  register,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  register: Register;
}) {
  const [preview, setPreview] = React.useState<DraftPreview | null>(null);
  const [error, setError] = React.useState("");
  useSaver(register, async () => true);

  React.useEffect(() => {
    let live = true;
    api.planner.plan.preview(detail.key)
      .then((found) => { if (live) setPreview(found); })
      .catch((failure) => {
        if (live) {
          setError(failure instanceof ApiError
            ? failure.message : "I could not build the preview.");
        }
      });
    return () => { live = false; };
  }, [detail.key, detail.version]);

  if (error) return <p role="alert" className="text-sm text-negative">{error}</p>;
  if (!preview) return <p className="text-sm text-text-muted">Reading the plan…</p>;

  const said = (source: string, from: string) =>
    source === "own" ? ""
      : source === "milestone" ? ` — inherited from milestone ${from}`
        : source === "project" ? " — inherited from the project" : "";

  return (
    <div className="space-y-4">
      <div>
        <p className="text-base font-semibold text-text-primary">
          {preview.overview.name}
          <span className="ml-2 font-mono text-xs text-text-muted">
            {preview.overview.code}
          </span>
        </p>
        <p className="mt-0.5 text-sm text-text-secondary">
          {preview.overview.description || "No description."}
        </p>
        <p className="mt-0.5 text-xs text-text-muted">
          {preview.governance.start_date ?? "no start"} →{" "}
          {preview.governance.target_end_date ?? "no target completion"} ·{" "}
          sponsor {nameOf(people, preview.governance.sponsor_id) || "not named"}
          {" · manager "}
          {nameOf(people, preview.governance.manager_id) || "not named"}
          {" · escalates to "}
          {nameOf(people, preview.governance.escalation_id) || "nobody"}
        </p>
        <p className="mt-1 text-sm text-text-secondary">
          {preview.agentic.sentence}
        </p>
        <p className="mt-1 text-xs text-text-muted">
          {preview.totals.milestones} milestones, {preview.totals.tasks} tasks,{" "}
          {preview.totals.links} dependencies, {preview.totals.people} people.
        </p>
      </div>

      <Timeline schedule={preview.schedule} />

      <ol className="space-y-2">
        {preview.milestones.map((milestone) => (
          <li key={String(milestone.code)}
              className="rounded-md border border-border bg-surface-raised px-3 py-2.5">
            <p className="text-sm font-medium text-text-primary">
              <span className="mr-2 font-mono text-xs text-text-muted">
                {String(milestone.code)}
              </span>
              {String(milestone.name)}
              <span className="ml-2 text-xs font-normal text-text-muted">
                {String(milestone.target_date ?? "no target date")}
              </span>
            </p>
            <p className="mt-0.5 text-xs text-text-secondary">
              Escalation: {nameOf(people, milestone.escalation.user_id)
                || "nobody"}
              {said(milestone.escalation.source, milestone.escalation.from_code)}
            </p>
            <ul className="mt-1.5 space-y-1">
              {milestone.tasks.map((task) => (
                <li key={String(task.code)} className="text-xs">
                  <span className="mr-2 font-mono text-text-muted">
                    {String(task.code)}
                  </span>
                  <span className="text-text-primary">
                    {String(task.title)}
                  </span>
                  <span className="text-text-muted">
                    {" · "}{nameOf(people, task.owner_id as number | null)
                      || "no owner"}
                    {" · due "}{String(task.due_date ?? "—")}
                  </span>
                  <span className="ml-1 text-text-secondary">
                    · escalation {nameOf(people, task.escalation.user_id)
                      || "nobody"}
                    {said(task.escalation.source, task.escalation.from_code)}
                  </span>
                </li>
              ))}
              {milestone.tasks.length === 0 && (
                <li className="text-xs text-text-muted">No tasks.</li>
              )}
            </ul>
          </li>
        ))}
      </ol>

      {preview.links.length > 0 && (
        <div className="rounded-md border border-border px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-text-muted">
            Dependencies
          </p>
          <ul className="mt-1 space-y-1">
            {preview.links.map((link) => (
              <li key={`${link.predecessor}-${link.successor}`}
                  className="text-xs text-text-secondary">
                {link.sentence}
                {link.notes && (
                  <span className="ml-1 text-warning">{link.notes}</span>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}

      <CompletenessPanel notes={preview.completeness.blockers}
                         warnings={preview.completeness.warnings} />
    </div>
  );
}

function Timeline({ schedule }: { schedule: DraftPreview["schedule"] }) {
  if (!schedule?.computed) {
    return (
      <div className="rounded-md border border-border px-3 py-2.5">
        <p className="text-[11px] uppercase tracking-wide text-text-muted">
          Timeline
        </p>
        <ul className="mt-1 space-y-0.5">
          {(schedule?.cannot_because ?? ["There is not enough in the plan yet."])
            .map((why, index) => (
              <li key={index} className="text-xs text-text-muted">{why}</li>
            ))}
        </ul>
      </div>
    );
  }
  const critical = new Set(schedule.critical_path);
  return (
    <div className="rounded-md border border-border px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">
        Timeline and critical path
      </p>
      <p className="mt-1 text-sm text-text-secondary">
        {schedule.project_start} → {schedule.project_finish} ·{" "}
        {schedule.critical_path.length} of {schedule.nodes.length} items are on
        the critical path.
      </p>
      <ul className="mt-1.5 space-y-0.5">
        {schedule.nodes.map((node) => (
          <li key={`${node.kind}-${node.code}`} className="text-xs">
            <span className="mr-2 font-mono text-text-muted">{node.code}</span>
            <span className={critical.has(node.code)
              ? "text-text-primary" : "text-text-secondary"}>
              {node.name}
            </span>
            <span className="ml-1 text-text-muted">
              {node.early_start} → {node.early_finish}
              {critical.has(node.code)
                ? " · critical path"
                : ` · ${node.total_float_days} days of float`}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** §13. Two lists, never one, and never the same colour. */
function CompletenessPanel({
  notes,
  warnings,
}: {
  notes: DraftNote[];
  warnings: DraftNote[];
}) {
  return (
    <div className="space-y-3">
      <div className="rounded-md border border-border px-3 py-2.5">
        <p className="text-[11px] uppercase tracking-wide text-negative">
          Required before publish
        </p>
        {notes.length === 0 ? (
          <p className="mt-1 text-sm text-positive">
            Nothing outstanding. This plan can be published.
          </p>
        ) : (
          <NoteList notes={notes} />
        )}
      </div>
      <div className="rounded-md border border-border px-3 py-2.5">
        <p className="text-[11px] uppercase tracking-wide text-warning">
          Recommended improvements
        </p>
        {warnings.length === 0 ? (
          <p className="mt-1 text-sm text-text-muted">
            Nothing a careful reader would change.
          </p>
        ) : (
          <NoteList notes={warnings} />
        )}
      </div>
    </div>
  );
}

function NoteList({ notes }: { notes: DraftNote[] }) {
  return (
    <ul className="mt-1.5 space-y-1">
      {notes.map((note, index) => (
        <li key={`${note.scope}-${note.code}-${index}`} className="text-sm">
          {note.code && (
            <span className="mr-2 font-mono text-xs text-text-muted">
              {note.code}
            </span>
          )}
          <span className="text-text-primary">{note.message}</span>
          {note.fix && <span className="ml-1 text-text-muted">{note.fix}</span>}
        </li>
      ))}
    </ul>
  );
}

// --------------------------------------------------------------- 8 publish

function PublishStep({
  detail,
  onPublished,
  register,
}: {
  detail: DraftDetail;
  onPublished: (projectId: number) => void;
  register: Register;
}) {
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  useSaver(register, async () => true);

  if (detail.status === "PUBLISHED") {
    return (
      <p className="text-sm text-text-secondary">
        This plan is already project {detail.code}. Changes go through the
        project itself from here.
      </p>
    );
  }

  const { publishable, blockers } = detail.completeness;

  return (
    <div className="space-y-3">
      {error && (
        <p role="alert" className="rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {error}
        </p>
      )}
      <p className="text-sm text-text-secondary">
        Publishing creates the project, its milestones, its tasks, its
        dependencies and everybody&apos;s access in one transaction. If any
        part of it fails, none of it is created.
      </p>
      {!publishable && (
        <div className="rounded-md border border-negative/40 bg-negative/5 px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-negative">
            {blockers.length} {blockers.length === 1 ? "thing has" : "things have"}{" "}
            to be settled first
          </p>
          <NoteList notes={blockers} />
        </div>
      )}
      <Button
        disabled={busy || !publishable}
        onClick={async () => {
          setBusy(true);
          setError("");
          try {
            const made = await api.planner.plan.publish(detail.key, true);
            onPublished(made.project_id);
          } catch (failure) {
            setError(failure instanceof ApiError
              ? failure.message : "The project was not created.");
            setBusy(false);
          }
        }}
      >
        Publish project
      </Button>
    </div>
  );
}
