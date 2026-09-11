"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  api,
  ApiError,
  type AgenticSetting,
  type CopilotPerson,
  type DraftCatalogueRow,
  type DraftDetail,
  type DraftLinkPreview,
  type DraftNote,
  type DraftPreview,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { anchorId, focusField, SetupAssistant, SetupProgress }
  from "./setup-assistant";

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
 * Three rules hold throughout.
 *
 * **There is one save.** Every field saves itself, shortly after you stop
 * typing, and one status line says whether it worked: Saved, Saving…, or
 * Save failed. There is no per-section Save button anywhere — a form with
 * five of them is a form where "did that save?" is a fair question — and the
 * single Save draft in the action bar is a way to leave, not a second way to
 * save.
 *
 * **The server is the plan.** A field's value is what the server holds,
 * overlaid with what you are typing into it right now and nothing else. So
 * the fields, the completeness notes and the progress bar are three views of
 * one document: they cannot drift, because there is nothing between them to
 * drift.
 *
 * **Next validates.** Moving forward flushes the pending save and then reads
 * the server's own completeness notes for that step. A wizard that let you
 * walk past a missing sponsor and told you about it on step eight would be
 * the same unstructured page with extra clicks.
 */

type Row = Record<string, unknown>;

const text = (row: Row, key: string) => String(row[key] ?? "");
const num = (row: Row, key: string): number | null => asNumber(row[key]);
const asNumber = (found: unknown): number | null =>
  found === null || found === undefined || found === "" ? null
    : Number(found);

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
  const [save, setSave] = React.useState<SaveState>("idle");
  const step = STEPS[at];

  const apply = React.useCallback(
    async (command: string, payload: Row = {}) => {
      setBusy(true);
      setError("");
      setSave("saving");
      try {
        await api.planner.plan.apply(detail.key, command, payload,
                                     detail.version);
        setSave("saved");
        onChanged();
        return true;
      } catch (failure) {
        setSave("failed");
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
   * A step's own gate: flush whatever it has pending, and say whether what
   * is on screen is valid.
   *
   * Each step registers this here rather than the wizard reaching into the
   * step's state, so the step that knows what a valid Overview is is the one
   * that decides whether Overview is valid. With autosave there is usually
   * nothing to flush — the field saved itself a second after it was typed —
   * but Next pressed inside the debounce window must not outrun the save.
   */
  const saver = React.useRef<null | (() => Promise<boolean>)>(null);
  const register = React.useCallback(
    (fn: null | (() => Promise<boolean>)) => { saver.current = fn; }, []);

  const jump = React.useCallback(async (next: number, gated: boolean) => {
    setError("");
    setBlockers([]);
    if (saver.current && !(await saver.current())) return false;
    if (gated && next > at) {
      const fresh = await api.planner.plan.draft(detail.key);
      const scopes = STEPS[at].scopes as readonly string[];
      const stopping = fresh.completeness.blockers.filter(
        (note) => scopes.includes(note.scope));
      if (stopping.length > 0) {
        setBlockers(stopping);
        onChanged();
        return false;
      }
    }
    const target = STEPS[Math.max(0, Math.min(STEPS.length - 1, next))];
    await api.planner.plan.apply(detail.key, "set_step",
                                 { step: SERVER_STEP[target.key] });
    setAt(stepIndex(target.key));
    onChanged();
    return true;
  }, [at, detail.key, onChanged]);

  /** Next: validated. */
  const goto = React.useCallback(
    (next: number) => jump(next, true), [jump]);

  /**
   * The assistant's answer to "where is that?": go to the step the note
   * belongs to and put the cursor on the field.
   *
   * Deliberately NOT gated. A person clicking "The project has no sponsor"
   * is being sent to fix it; stopping them on the way with the step's own
   * blockers would be refusing to take them to the thing they asked for.
   */
  const goTo = React.useCallback(async (stepKey: string, field: string) => {
    const wanted = stepKey ? stepIndex(stepKey) : at;
    if (wanted !== at) {
      if (!(await jump(wanted, false))) return;
    }
    focusField(field);
  }, [at, jump]);

  const saveDraft = React.useCallback(async () => {
    setError("");
    if (saver.current && !(await saver.current())) return;
    await api.planner.plan.apply(detail.key, "set_step",
                                 { step: SERVER_STEP[step.key] });
    onSaved();
  }, [detail.key, onSaved, step.key]);

  const last = at === STEPS.length - 1;

  return (
    <div className="space-y-4">
      <SetupProgress
        progress={detail.progress}
        at={SERVER_STEP[step.key] === "REVIEW" && step.key === "PUBLISH"
          ? "PUBLISH" : step.key}
        onJump={(stepKey) => void goTo(stepKey, "")}
      />

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
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
            <NoteList notes={blockers}
                      onGo={(stepKey, field) => void goTo(stepKey, field)} />
          </div>
        )}

        <div className="px-4 py-4">
          {step.key === "OVERVIEW" && (
            <OverviewStep key={`o${detail.key}`} detail={detail}
                          apply={apply} register={register} />
          )}
          {step.key === "GOVERNANCE" && (
            <GovernanceStep key={`g${detail.key}`} detail={detail}
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
            <PreviewStep detail={detail} people={named} register={register}
                         onGo={(stepKey, field) => void goTo(stepKey, field)} />
          )}
          {step.key === "PUBLISH" && (
            <PublishStep detail={detail} register={register}
                         onGo={(stepKey, field) => void goTo(stepKey, field)} />
          )}
        </div>

        {/*
          * One action bar, on every step, in one order. §14.
          *
          * Back, Save draft, Next — and on the last step Preview and Publish
          * in place of Next, because there is nowhere further forward to go.
          * Nothing else on this page saves anything, which is why "did that
          * save?" now has one answer, printed beside these buttons.
          */}
        <footer className="flex flex-wrap items-center gap-2 border-t border-border bg-surface-sunken px-4 py-3">
          <Button variant="outline" size="sm" disabled={busy || at === 0}
                  onClick={() => void goto(at - 1)}>
            Back
          </Button>
          <Button variant="ghost" size="sm" disabled={busy}
                  onClick={() => void saveDraft()}>
            Save draft
          </Button>
          {!last && (
            <Button size="sm" disabled={busy} onClick={() => void goto(at + 1)}>
              Next
            </Button>
          )}
          {last && (
            <>
              <Button variant="outline" size="sm" disabled={busy}
                      onClick={() => void goTo("REVIEW", "")}>
                Preview
              </Button>
              <PublishButton detail={detail} busy={busy}
                             onPublished={onPublished} onFailed={setError} />
            </>
          )}
          <SaveStatus state={save} />
        </footer>
      </section>

      <SetupAssistant guidance={detail.guidance}
                      onGo={(stepKey, field) => void goTo(stepKey, field)} />
      </div>
    </div>
  );
}

/** Saved · Saving… · Save failed. One line, one place, §2. */
function SaveStatus({ state }: { state: SaveState }) {
  if (state === "idle") {
    return (
      <span className="ml-auto text-xs text-text-muted">
        Every field saves itself. Nothing exists until you publish.
      </span>
    );
  }
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn(
        "ml-auto rounded-md px-2 py-1 text-xs",
        state === "saving" && "bg-surface text-text-secondary",
        state === "saved" && "bg-positive/10 text-positive",
        state === "failed" && "bg-negative/10 text-negative",
      )}
    >
      {state === "saving" ? "Saving…"
        : state === "saved" ? "Saved" : "Save failed"}
    </span>
  );
}

// ------------------------------------------------------------------- shell

/**
 * One labelled control, and the address a completeness note can send
 * somebody to.
 *
 * `anchor` is the plan path the field holds — `governance.sponsor_id`. The
 * assistant's notes carry the same string, so "The project has no sponsor"
 * is one click from the sponsor rather than a search through eight steps.
 */
function Field({
  label,
  hint,
  anchor,
  children,
}: {
  label: string;
  hint?: string;
  anchor?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block" id={anchor ? `${anchorId(anchor)}-row` : undefined}>
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
  anchor,
}: {
  value: number | null;
  /** Everybody already named on this plan, offered before any search. */
  people: CopilotPerson[];
  onChange: (id: number | null) => void;
  label?: string;
  /** The plan path this picker sets, so a note can send somebody here. */
  anchor?: string;
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
        id={anchor ? anchorId(anchor) : undefined}
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

/** What the one status line on the screen is currently saying. */
export type SaveState = "idle" | "saving" | "saved" | "failed";

/** How long after the last keystroke a field saves itself. */
const AUTOSAVE_MS = 700;

/**
 * One field, saved shortly after you stop typing.
 *
 * The value of a control is the server's value, overlaid with what is being
 * typed into it and nothing else. That overlay is cleared the moment the
 * server confirms what it was, so the form cannot end up holding a different
 * plan from the one the completeness panel is describing — which is exactly
 * what UAT saw, and exactly what a local copy of the whole section produces
 * when the server derives a field the copy does not know about.
 *
 * `flush` is what Back, Next and Save draft call: a save that is scheduled
 * but has not fired yet must not be outrun by the button that assumes it has.
 */
function useAutosave({
  apply,
  command,
  server,
  extra,
}: {
  apply: Apply;
  command: string;
  /** The section of the plan as the server currently holds it. */
  server: Row;
  /** Merged into every patch — the code of the row being edited. */
  extra?: Row;
}) {
  const [pending, setPending] = React.useState<Row>({});
  const queued = React.useRef<Row>({});
  const timer = React.useRef<ReturnType<typeof setTimeout> | null>(null);
  // The row being edited — `{code}` — which every patch has to carry. In a
  // ref rather than a dependency because `flush` is called from a timer, and
  // in an effect rather than during render because a ref written while
  // rendering is a ref React is allowed to throw away.
  const carry = React.useRef<Row>(extra ?? {});
  React.useEffect(() => { carry.current = extra ?? {}; });

  const flush = React.useCallback(async () => {
    if (timer.current) {
      clearTimeout(timer.current);
      timer.current = null;
    }
    const patch = queued.current;
    queued.current = {};
    if (Object.keys(patch).length === 0) return true;
    const ok = await apply(command, { ...carry.current, ...patch });
    if (!ok) {
      // Keep it pending: the field still shows what the person typed, and
      // the status line says the save failed. Losing their typing silently
      // would be the worse of the two failures.
      queued.current = { ...patch, ...queued.current };
      return false;
    }
    setPending((was) => {
      const next = { ...was };
      for (const key of Object.keys(patch)) {
        if (!(key in queued.current) && next[key] === patch[key]) {
          delete next[key];
        }
      }
      return next;
    });
    return true;
  }, [apply, command]);

  const set = React.useCallback((key: string, value: unknown) => {
    setPending((was) => ({ ...was, [key]: value }));
    queued.current = { ...queued.current, [key]: value };
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => { void flush(); }, AUTOSAVE_MS);
  }, [flush]);

  React.useEffect(() => () => {
    if (timer.current) clearTimeout(timer.current);
  }, []);

  const value = React.useCallback(
    (key: string): unknown => (key in pending ? pending[key] : server[key]),
    [pending, server]);

  return { value, set, flush };
}

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
  const form = useAutosave({ apply, command: "set_overview",
                             server: detail.plan.overview as Row });
  const [taken, setTaken] = React.useState("");

  useSaver(register, async () => {
    setTaken("");
    if (!(await form.flush())) return false;
    const wanted = String(form.value("code") ?? "").trim();
    if (!String(form.value("name") ?? "").trim()) return false;
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
    return true;
  });

  return (
    <div className="space-y-3">
      {taken && (
        <p role="alert" className="rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {taken}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Project name" anchor="overview.name">
          <Input id={anchorId("overview.name")}
                 value={String(form.value("name") ?? "")}
                 placeholder="LGD Model Redevelopment"
                 onChange={(e) => form.set("name", e.target.value)} />
        </Field>
        <Field label="Project code" anchor="overview.code"
               hint="How people refer to it in exports, messages and reports.">
          <Input id={anchorId("overview.code")}
                 value={String(form.value("code") ?? "")}
                 placeholder="LGDMR-2026"
                 onChange={(e) => form.set("code", e.target.value)} />
        </Field>
        <Field label="Description" anchor="overview.description">
          <Input id={anchorId("overview.description")}
                 value={String(form.value("description") ?? "")}
                 onChange={(e) => form.set("description", e.target.value)} />
        </Field>
        <Field label="Objective" anchor="overview.objective"
               hint="What has to be true for this to be finished?">
          <Input id={anchorId("overview.objective")}
                 value={String(form.value("objective") ?? "")}
                 onChange={(e) => form.set("objective", e.target.value)} />
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
  const form = useAutosave({ apply, command: "set_governance",
                             server: detail.plan.governance as Row });
  const [local, setLocal] = React.useState("");
  const start = String(form.value("start_date") ?? "");
  const end = String(form.value("target_end_date") ?? "");

  useSaver(register, async () => {
    setLocal("");
    if (start && end && end < start) {
      setLocal(`Target completion (${end}) is before the start date ` +
               `(${start}).`);
      return false;
    }
    return form.flush();
  });

  return (
    <div className="space-y-3">
      {local && (
        <p role="alert" className="rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {local}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Sponsor" anchor="governance.sponsor_id"
               hint="Accountable for the project existing.">
          <PersonSelect label="Sponsor" anchor="governance.sponsor_id"
                        value={asNumber(form.value("sponsor_id"))} people={people}
                        onChange={(id) => form.set("sponsor_id", id)} />
        </Field>
        <Field label="Project manager" anchor="governance.manager_id"
               hint="Runs it day to day.">
          <PersonSelect label="Project manager" anchor="governance.manager_id"
                        value={asNumber(form.value("manager_id"))} people={people}
                        onChange={(id) => form.set("manager_id", id)} />
        </Field>
        <Field label="Owner" anchor="governance.owner_id"
               hint="Often the manager. Say so explicitly.">
          <PersonSelect label="Owner" anchor="governance.owner_id"
                        value={asNumber(form.value("owner_id"))} people={people}
                        onChange={(id) => form.set("owner_id", id)} />
        </Field>
        <Field label="Escalation contact" anchor="governance.escalation_id"
               hint="The last stop when a milestone's own contact has not resolved something.">
          <PersonSelect label="Escalation contact"
                        anchor="governance.escalation_id"
                        value={asNumber(form.value("escalation_id"))} people={people}
                        onChange={(id) => form.set("escalation_id", id)} />
        </Field>
        <Field label="Start date" anchor="governance.start_date">
          <Input id={anchorId("governance.start_date")} type="date"
                 value={start}
                 onChange={(e) => form.set("start_date", e.target.value)} />
        </Field>
        <Field label="Target completion" anchor="governance.target_end_date">
          <Input id={anchorId("governance.target_end_date")} type="date"
                 value={end}
                 onChange={(e) =>
                   form.set("target_end_date", e.target.value)} />
        </Field>
        <Field label="Priority" anchor="governance.priority">
          <select value={String(form.value("priority") ?? "MEDIUM")}
                  aria-label="Priority"
                  id={anchorId("governance.priority")}
                  onChange={(e) => form.set("priority", e.target.value)}
                  className="mt-1 h-9 w-full rounded-md border border-border bg-surface-raised px-2 text-sm text-text-primary">
            {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((level) => (
              <option key={level} value={level}>{level}</option>
            ))}
          </select>
        </Field>
        <Field label="Reporting cadence" anchor="governance.reporting_cadence">
          <select value={String(form.value("reporting_cadence") ?? "WEEKLY")}
                  aria-label="Reporting cadence"
                  id={anchorId("governance.reporting_cadence")}
                  onChange={(e) =>
                    form.set("reporting_cadence", e.target.value)}
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
            id={choice.mode === "CUSTOM" ? anchorId("agentic.mode") : undefined}
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
      {chosen === "CUSTOM" && (
        <CustomPolicy detail={detail} apply={apply} busy={busy} />
      )}
    </div>
  );
}

/**
 * Custom, actually set. §11.
 *
 * Choosing Custom used to select a label and leave the thresholds on
 * Standard, which is the worst of the four answers: the screen says the
 * policy is yours and the agent behaves as though it is not. Every field
 * here is a real threshold the monitoring engine reads, rendered from the
 * server's own list of them with the server's own bounds — so a field cannot
 * appear that the policy does not have, and a number cannot be shown as
 * acceptable that the policy will refuse.
 *
 * Nothing is saved per field here either: the panel writes the whole custom
 * document through `set_agentic`, which is one command, and the sentence
 * underneath is the policy read back in the words it will behave in.
 */
function CustomPolicy({
  detail,
  apply,
  busy,
}: {
  detail: DraftDetail;
  apply: Apply;
  busy: boolean;
}) {
  const stored = (detail.plan.agentic?.policy ?? {}) as Row;
  const settings = detail.agentic_settings ?? [];
  const [error, setError] = React.useState("");
  const [saying, setSaying] = React.useState("");
  const [draft, setDraft] = React.useState<Row>(() => {
    const start: Row = {};
    for (const setting of settings) {
      start[setting.key] = setting.key in stored
        ? stored[setting.key] : setting.default;
    }
    return start;
  });

  const write = React.useCallback(async (next: Row) => {
    setError("");
    const ok = await apply("set_agentic", { mode: "CUSTOM", policy: next });
    if (!ok) {
      setError("Those thresholds were refused. The message above says why.");
      return;
    }
    setSaying("");
  }, [apply]);

  const change = (setting: AgenticSetting, raw: unknown) => {
    const next = { ...draft, [setting.key]: raw };
    setDraft(next);
    void write(next);
  };

  return (
    <section className="rounded-lg border border-accent/40 bg-surface px-4 py-3"
             aria-label="Custom agentic policy">
      <p className="text-[11px] uppercase tracking-wide text-text-muted">
        Your thresholds
      </p>
      {error && (
        <p role="alert"
           className="mt-1.5 rounded-md border border-negative/40 bg-negative/10 px-3 py-2 text-sm text-negative">
          {error}
        </p>
      )}
      <div className="mt-2 grid gap-3 sm:grid-cols-2">
        {settings.map((setting) => {
          const held = draft[setting.key];
          if (setting.kind === "flag") {
            return (
              <label key={setting.key}
                     className="flex items-start gap-2 rounded-md border border-border px-3 py-2">
                <input
                  type="checkbox"
                  className="mt-0.5"
                  checked={Boolean(held)}
                  aria-label={setting.label}
                  disabled={busy}
                  onChange={(e) => change(setting, e.target.checked)}
                />
                <span className="min-w-0">
                  <span className="block text-xs text-text-primary">
                    {setting.label}
                  </span>
                  {setting.help && (
                    <span className="mt-0.5 block text-[11px] text-text-muted">
                      {setting.help}
                    </span>
                  )}
                </span>
              </label>
            );
          }
          if (setting.kind === "days_list") {
            return (
              <Field key={setting.key} label={setting.label}
                     hint={setting.help}>
                <Input
                  value={Array.isArray(held) ? held.join(", ") : ""}
                  aria-label={setting.label}
                  placeholder="7, 3, 1, 0"
                  disabled={busy}
                  onChange={(e) => setSaying(e.target.value)}
                  onBlur={(e) => change(setting, e.target.value
                    .split(",")
                    .map((part) => part.trim())
                    .filter(Boolean)
                    .map(Number)
                    .filter((day) => Number.isFinite(day)))}
                />
              </Field>
            );
          }
          const never = setting.kind === "days_or_never";
          return (
            <Field key={setting.key} label={setting.label} hint={setting.help}>
              <div className="flex items-center gap-2">
                <Input
                  type="number"
                  className="mt-1"
                  aria-label={setting.label}
                  min={setting.minimum ?? undefined}
                  max={setting.maximum ?? undefined}
                  disabled={busy || (never && held === null)}
                  value={held === null || held === undefined
                    ? "" : String(held)}
                  onChange={(e) => change(setting, e.target.value === ""
                    ? null : Number(e.target.value))}
                />
                {never && (
                  <label className="mt-1 flex shrink-0 items-center gap-1 text-[11px] text-text-muted">
                    <input
                      type="checkbox"
                      checked={held === null}
                      aria-label={`${setting.label}: never`}
                      disabled={busy}
                      onChange={(e) => change(
                        setting, e.target.checked ? null : setting.default)}
                    />
                    Never
                  </label>
                )}
              </div>
            </Field>
          );
        })}
      </div>
      {saying && (
        <p className="mt-2 text-[11px] text-text-muted">
          Reminder days are saved when you leave the box.
        </p>
      )}
      <p className="mt-3 rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
        {detail.agentic_policy?.sentence}
      </p>
    </section>
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
                <MilestoneEditor key={code} milestone={milestone}
                                 people={people} apply={apply} />
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

/**
 * Editing one milestone, with no Save button of its own. §2.
 *
 * Each field saves itself, and the one status line in the action bar says
 * whether it worked. A milestone editor with its own Save was one of five
 * places on this page that claimed to save something, which is how a person
 * ends up not knowing whether any of them did.
 */
function MilestoneEditor({
  milestone,
  people,
  apply,
}: {
  milestone: Row;
  people: CopilotPerson[];
  apply: Apply;
}) {
  const code = text(milestone, "code");
  const form = useAutosave({ apply, command: "update_milestone",
                             server: milestone, extra: { code } });
  const at = (field: string) => `milestone.${code}.${field}`;
  return (
    <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-2">
      <Field label="Name" anchor={at("name")}>
        <Input id={anchorId(at("name"))}
               value={String(form.value("name") ?? "")}
               onChange={(e) => form.set("name", e.target.value)} />
      </Field>
      <Field label="Owner" anchor={at("owner_id")}>
        <PersonSelect label="Owner" anchor={at("owner_id")}
                      value={asNumber(form.value("owner_id"))} people={people}
                      onChange={(id) => form.set("owner_id", id)} />
      </Field>
      <Field label="Starts" anchor={at("start_date")}>
        <Input id={anchorId(at("start_date"))} type="date"
               value={String(form.value("start_date") ?? "")}
               onChange={(e) => form.set("start_date", e.target.value)} />
      </Field>
      <Field label="Target date" anchor={at("target_date")}>
        <Input id={anchorId(at("target_date"))} type="date"
               value={String(form.value("target_date") ?? "")}
               onChange={(e) => form.set("target_date", e.target.value)} />
      </Field>
      <Field label="Critical date" anchor={at("critical_date")}
             hint="After this it cannot recover. Not the target date.">
        <Input id={anchorId(at("critical_date"))} type="date"
               value={String(form.value("critical_date") ?? "")}
               onChange={(e) => form.set("critical_date", e.target.value)} />
      </Field>
      <Field label="Escalation contact" anchor={at("escalation_id")}
             hint="Leave empty to inherit the project's.">
        <PersonSelect label="Escalation contact" anchor={at("escalation_id")}
                      value={asNumber(form.value("escalation_id"))}
                      people={people}
                      onChange={(id) => form.set("escalation_id", id)} />
      </Field>
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
            key={code}
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
                <TaskEditor key={taskCode} task={task} people={people}
                            apply={apply} />
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

/** Editing one task. Like the milestone editor, it has no Save. §2. */
function TaskEditor({
  task,
  people,
  apply,
}: {
  task: Row;
  people: CopilotPerson[];
  apply: Apply;
}) {
  const code = text(task, "code");
  const form = useAutosave({ apply, command: "update_task",
                             server: task, extra: { code } });
  const at = (field: string) => `task.${code}.${field}`;
  return (
    <div className="mt-3 grid gap-3 border-t border-border pt-3 sm:grid-cols-3">
      <Field label="Title" anchor={at("title")}>
        <Input id={anchorId(at("title"))}
               value={String(form.value("title") ?? "")}
               onChange={(e) => form.set("title", e.target.value)} />
      </Field>
      <Field label="Description" anchor={at("description")}
             hint="The owner reads this when the agent reminds them.">
        <Input id={anchorId(at("description"))}
               value={String(form.value("description") ?? "")}
               onChange={(e) => form.set("description", e.target.value)} />
      </Field>
      <Field label="Owner" anchor={at("owner_id")}>
        <PersonSelect label="Owner" anchor={at("owner_id")}
                      value={asNumber(form.value("owner_id"))} people={people}
                      onChange={(id) => form.set("owner_id", id)} />
      </Field>
      <Field label="Starts" anchor={at("start_date")}>
        <Input id={anchorId(at("start_date"))} type="date"
               value={String(form.value("start_date") ?? "")}
               onChange={(e) => form.set("start_date", e.target.value)} />
      </Field>
      <Field label="Due" anchor={at("due_date")}>
        <Input id={anchorId(at("due_date"))} type="date"
               value={String(form.value("due_date") ?? "")}
               onChange={(e) => form.set("due_date", e.target.value)} />
      </Field>
      <Field label="Escalation contact" anchor={at("escalation_id")}
             hint="Leave empty to inherit the milestone's.">
        <PersonSelect label="Escalation contact" anchor={at("escalation_id")}
                      value={asNumber(form.value("escalation_id"))}
                      people={people}
                      onChange={(id) => form.set("escalation_id", id)} />
      </Field>
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
  onGo,
}: {
  detail: DraftDetail;
  people: CopilotPerson[];
  register: Register;
  onGo: (step: string, field: string) => void;
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

      <CompletenessPanel onGo={onGo} notes={preview.completeness.blockers}
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
  onGo,
}: {
  notes: DraftNote[];
  warnings: DraftNote[];
  onGo: (step: string, field: string) => void;
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
          <NoteList notes={notes} onGo={onGo} />
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
          <NoteList notes={warnings} onGo={onGo} />
        )}
      </div>
    </div>
  );
}

/** Every note is a way back to the field it is about. §9. */
function NoteList({
  notes,
  onGo,
}: {
  notes: DraftNote[];
  onGo: (step: string, field: string) => void;
}) {
  return (
    <ul className="mt-1.5 space-y-1">
      {notes.map((note, index) => (
        <li key={`${note.scope}-${note.code}-${index}`}>
          <button
            type="button"
            aria-label={`Fix: ${note.message}`}
            onClick={() => onGo(stepOfScope(note.scope), note.field)}
            className="w-full rounded-md border border-transparent px-1.5 py-1 text-left text-sm transition hover:border-accent"
          >
            {note.code && (
              <span className="mr-2 font-mono text-xs text-text-muted">
                {note.code}
              </span>
            )}
            <span className="text-text-primary">{note.message}</span>
            {note.fix && (
              <span className="ml-1 text-text-muted">{note.fix}</span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

// --------------------------------------------------------------- 8 publish

/**
 * What publishing does, and what is still in the way. §15.
 *
 * The button itself is in the action bar with Back, Save draft and Preview,
 * because §14 asks for one row of controls and a Publish that sits somewhere
 * else is a second one.
 */
function PublishStep({
  detail,
  register,
  onGo,
}: {
  detail: DraftDetail;
  register: Register;
  onGo: (step: string, field: string) => void;
}) {
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
      <p className="text-sm text-text-secondary">
        Publishing creates the project, its milestones, its tasks, its
        dependencies and everybody&apos;s access in one transaction. If any
        part of it fails, none of it is created.
      </p>
      <p className={cn(
        "rounded-md border px-3 py-2 text-sm",
        publishable
          ? "border-positive/40 bg-positive/5 text-positive"
          : "border-negative/40 bg-negative/5 text-negative",
      )}>
        {detail.progress.publish_message}
      </p>
      {!publishable && (
        <div className="rounded-md border border-border px-3 py-2.5">
          <p className="text-[11px] uppercase tracking-wide text-negative">
            {blockers.length === 1 ? "It is this" : "They are these"}
          </p>
          <ul className="mt-1.5 space-y-1">
            {blockers.map((note, index) => (
              <li key={index}>
                <button
                  type="button"
                  aria-label={`Fix: ${note.message}`}
                  onClick={() => onGo(stepOfScope(note.scope), note.field)}
                  className="w-full rounded-md border border-border px-2.5 py-1.5 text-left text-sm transition hover:border-accent"
                >
                  {note.code && (
                    <span className="mr-2 font-mono text-xs text-text-muted">
                      {note.code}
                    </span>
                  )}
                  <span className="text-text-primary">{note.message}</span>
                  {note.fix && (
                    <span className="ml-1 text-text-muted">{note.fix}</span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Which step of the form a completeness note belongs to. */
function stepOfScope(scope: string): string {
  if (scope === "overview") return "OVERVIEW";
  if (scope === "governance") return "GOVERNANCE";
  if (scope === "agentic") return "AGENTIC";
  if (scope === "milestones" || scope === "milestone") return "MILESTONES";
  if (scope === "task") return "TASKS";
  if (scope === "link") return "DEPENDENCIES";
  return "REVIEW";
}

/** The one Publish, in the action bar. */
function PublishButton({
  detail,
  busy,
  onPublished,
  onFailed,
}: {
  detail: DraftDetail;
  busy: boolean;
  onPublished: (projectId: number) => void;
  onFailed: (message: string) => void;
}) {
  const [going, setGoing] = React.useState(false);
  const publishable = detail.completeness.publishable
    && detail.status !== "PUBLISHED";
  return (
    <Button
      size="sm"
      disabled={busy || going || !publishable}
      title={detail.progress.publish_message}
      onClick={async () => {
        setGoing(true);
        onFailed("");
        try {
          const made = await api.planner.plan.publish(detail.key, true);
          onPublished(made.project_id);
        } catch (failure) {
          onFailed(failure instanceof ApiError
            ? failure.message : "The project was not created.");
          setGoing(false);
        }
      }}
    >
      Publish project
    </Button>
  );
}
