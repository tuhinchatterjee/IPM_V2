"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { ImportNewProject } from "@/components/planner/import-panel";
import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Starting a project, without a spreadsheet and without an API call.
 *
 * Two ways in, because they are genuinely different situations. Somebody
 * beginning a piece of work types the eleven fields below. Somebody whose
 * plan already exists in a workbook — which is most people, most of the time —
 * uploads it and sees what it would create before it creates anything.
 *
 * The form asks for what a project needs to be chased on and nothing else.
 * Every field here ends up in a rule: the dates decide what is late, the
 * cadence and the reminder policy decide when somebody hears about it, and
 * the manager is who hears when it turns red. A field that fed no rule would
 * be a field nobody fills in truthfully.
 */

const CADENCES = ["DAILY", "WEEKLY", "FORTNIGHTLY", "MONTHLY", "QUARTERLY"];
const PRIORITIES = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const STATUSES = ["DRAFT", "PLANNING", "ACTIVE", "ON_HOLD"];

/** The reminder policy, as choices rather than as a comma-separated list. */
const REMINDER_POLICIES: { id: string; label: string; days: number[] }[] = [
  { id: "standard", label: "A week, three days, the day before, and the day",
    days: [7, 3, 1, 0] },
  { id: "close", label: "Three days, the day before, and the day",
    days: [3, 1, 0] },
  { id: "light", label: "The day before and the day", days: [1, 0] },
  { id: "day", label: "On the day only", days: [0] },
];

export default function NewDeliveryProjectPage() {
  const router = useRouter();
  const directory = useAsync(() => api.users(), []);
  const people = (directory.data?.users ?? []).filter((p) => p.is_active);

  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [objective, setObjective] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [sponsor, setSponsor] = React.useState("");
  const [manager, setManager] = React.useState("");
  const [priority, setPriority] = React.useState("MEDIUM");
  const [status, setStatus] = React.useState("ACTIVE");
  const [start, setStart] = React.useState("");
  const [target, setTarget] = React.useState("");
  const [cadence, setCadence] = React.useState("WEEKLY");
  const [policy, setPolicy] = React.useState("standard");
  const [stale, setStale] = React.useState("7");

  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const ready = code.trim().length > 0 && name.trim().length > 0;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const chosen = REMINDER_POLICIES.find((p) => p.id === policy);
      const made = await api.planner.createProject({
        code: code.trim(),
        name: name.trim(),
        objective: objective.trim(),
        description: description.trim(),
        sponsor_id: sponsor ? Number(sponsor) : null,
        manager_id: manager ? Number(manager) : null,
        priority,
        status,
        start_date: start || null,
        target_end_date: target || null,
        reporting_cadence: cadence,
        reminder_days: chosen?.days ?? [7, 3, 1, 0],
        stale_after_days: Number(stale) || 7,
      });
      router.push(`/delivery/${made.project.id}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-3xl px-6 py-6">
      <PageHeader
        title="New project"
        eyebrow="Project Planner"
        description="What the team is delivering, and what it will be chased on."
        actions={
          <Link href="/delivery" className="text-sm text-accent hover:underline">
            All projects
          </Link>
        }
      />

      <div className="mt-4 rounded-lg border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium text-text-primary">
            The project
          </h2>
        </div>
        <div className="grid gap-4 px-4 py-4 sm:grid-cols-2">
          <Field label="Project code" hint="Short, and it becomes a filename.">
            <Input value={code} onChange={(e) => setCode(e.target.value)}
                   placeholder="RET-IFRS9-2026" maxLength={40} />
          </Field>
          <Field label="Project name">
            <Input value={name} onChange={(e) => setName(e.target.value)}
                   placeholder="Retail IFRS 9 — monthly ECL production" />
          </Field>
          <Field label="Objective" hint="What done looks like." wide>
            <Textarea value={objective} rows={2}
                      onChange={(e) => setObjective(e.target.value)} />
          </Field>
          <Field label="Description" wide>
            <Textarea value={description} rows={2}
                      onChange={(e) => setDescription(e.target.value)} />
          </Field>

          <Field label="Sponsor" hint="Who is accountable for the outcome.">
            <Select value={sponsor} onChange={(e) => setSponsor(e.target.value)}>
              <option value="">Not set</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name || p.username}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Project manager"
                 hint="Who hears when the project turns red.">
            <Select value={manager} onChange={(e) => setManager(e.target.value)}>
              <option value="">Not set</option>
              {people.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.display_name || p.username}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Priority">
            <Select value={priority} onChange={(e) => setPriority(e.target.value)}>
              {PRIORITIES.map((p) => (
                <option key={p} value={p}>{p.toLowerCase()}</option>
              ))}
            </Select>
          </Field>
          <Field label="Status">
            <Select value={status} onChange={(e) => setStatus(e.target.value)}>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {s.replace(/_/g, " ").toLowerCase()}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="Start date">
            <Input type="date" value={start}
                   onChange={(e) => setStart(e.target.value)} />
          </Field>
          <Field label="Target completion">
            <Input type="date" value={target}
                   onChange={(e) => setTarget(e.target.value)} />
          </Field>

          <Field label="Reporting cadence">
            <Select value={cadence} onChange={(e) => setCadence(e.target.value)}>
              {CADENCES.map((c) => (
                <option key={c} value={c}>{c.toLowerCase()}</option>
              ))}
            </Select>
          </Field>
          <Field label="Reminder policy"
                 hint="How far ahead of a due date an owner is reminded.">
            <Select value={policy} onChange={(e) => setPolicy(e.target.value)}>
              {REMINDER_POLICIES.map((p) => (
                <option key={p.id} value={p.id}>{p.label}</option>
              ))}
            </Select>
          </Field>
          <Field label="Chase after (days)"
                 hint="How long a task may go unmentioned before its owner is asked.">
            <Input type="number" min={1} max={90} value={stale}
                   onChange={(e) => setStale(e.target.value)} />
          </Field>
        </div>

        {error && (
          <p className="border-t border-border px-4 py-3 text-sm text-negative">
            {error}
          </p>
        )}

        <div className="flex items-center gap-3 border-t border-border px-4 py-3">
          <Button onClick={create} disabled={!ready || busy}>
            {busy ? "Creating…" : "Create project"}
          </Button>
          <span className="text-xs text-text-muted">
            You become its owner, so you can add the rest of the team next.
          </span>
        </div>
      </div>

      <div className="mt-6 rounded-lg border border-border bg-surface">
        <div className="border-b border-border px-4 py-3">
          <h2 className="text-sm font-medium text-text-primary">
            Or start from a workbook
          </h2>
          <p className="mt-1 text-xs text-text-muted">
            If the plan already exists in a spreadsheet, upload it. You will see
            everything it would create before anything is created.
          </p>
        </div>
        <ImportNewProject
          onCreated={(projectId: number) =>
            router.push(`/delivery/${projectId}`)} />
        <div className="border-t border-border px-4 py-2">
          <a href={api.planner.templateUrl()}
             className="text-xs text-accent hover:underline">
            Download the template
          </a>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  hint,
  wide,
  children,
}: {
  label: string;
  hint?: string;
  wide?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className={wide ? "sm:col-span-2" : undefined}>
      <Label>{label}</Label>
      {children}
      {hint && <p className="mt-1 text-xs text-text-muted">{hint}</p>}
    </div>
  );
}
