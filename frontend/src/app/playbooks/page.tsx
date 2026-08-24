"use client";

import Link from "next/link";
import * as React from "react";
import {
  Check,
  ChevronDown,
  Loader2,
  Pause,
  Play,
  Plus,
  Trash2,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  type AnalysisSummary,
  type Playbook,
  type PlaybookCondition,
  type PlaybookEvaluation,
  type PlaybookRun,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { withReturnTo } from "@/lib/return-to";
import { cn } from "@/lib/utils";

/**
 * Playbooks.
 *
 * A playbook is a standing instruction the platform carries out: run these
 * certified analyses over this scope, test these thresholds, and if one is
 * crossed, do this.
 *
 * It replaced Blueprints, and the difference is the whole point. A Blueprint was
 * a template of a document — something you filled in. A Playbook RUNS. The work
 * a credit team actually repeats every quarter is not writing the same document;
 * it is asking the same questions of new data and noticing when an answer has
 * changed.
 *
 * A run that finds nothing says so. It never reaches for something to report.
 */
export default function PlaybooksPage() {
  const [refresh, setRefresh] = React.useState(0);
  const library = useAsync(() => api.playbooks(), [refresh]);
  const analyses = useAsync(() => api.analyses(), []);
  const [creating, setCreating] = React.useState(false);

  return (
    <div className="space-y-7">
      <PageHeader
        title="Playbooks"
        description="A standing instruction: run these certified analyses over this scope, test these thresholds, and act when one is crossed. Every figure a playbook reports carries a Trace, exactly as it would if you had asked for it by hand."
        status="partial"
        phase="Manual and on-publication triggers run; scheduling is not yet wired to a scheduler"
        actions={
          <Button size="sm" onClick={() => setCreating((c) => !c)}>
            <Plus aria-hidden />
            New playbook
          </Button>
        }
      />

      {creating && library.data && (
        <NewPlaybook
          analyses={analyses.data?.analyses ?? []}
          operators={library.data.operators}
          dimensions={library.data.scope_dimensions}
          triggers={library.data.triggers}
          onCreated={() => {
            setCreating(false);
            setRefresh((n) => n + 1);
          }}
          onCancel={() => setCreating(false)}
        />
      )}

      {library.loading && <Skeleton className="h-52 w-full" />}
      {library.error && (
        <Card className="border-negative/40 p-4 text-sm text-negative">
          {library.error}
        </Card>
      )}

      {library.data &&
        (library.data.playbooks.length > 0 ? (
          <div className="space-y-4">
            {library.data.playbooks.map((playbook) => (
              <PlaybookCard
                key={playbook.id}
                playbook={playbook}
                onChange={() => setRefresh((n) => n + 1)}
              />
            ))}
          </div>
        ) : (
          <EmptyState
            icon={Play}
            title="No playbooks yet"
            description="Define one when a question is worth asking of every new quarter. It runs the analyses, tests the thresholds you set, and tells you only when one is crossed."
            action={
              <Button size="sm" onClick={() => setCreating(true)}>
                New playbook
              </Button>
            }
          />
        ))}
    </div>
  );
}

/* ------------------------------------------------------------------- card */

function PlaybookCard({
  playbook,
  onChange,
}: {
  playbook: Playbook;
  onChange: () => void;
}) {
  const [open, setOpen] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [run, setRun] = React.useState<PlaybookRun | null>(playbook.last_run);
  const [error, setError] = React.useState<string | null>(null);

  async function execute() {
    setBusy(true);
    setError(null);
    try {
      setRun(await api.runPlaybook(playbook.id));
      setOpen(true);
      onChange();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function toggle() {
    await api.setPlaybookStatus(
      playbook.id,
      playbook.status === "active" ? "paused" : "active",
    );
    onChange();
  }

  async function remove() {
    await api.deletePlaybook(playbook.id);
    onChange();
  }

  return (
    <Card>
      <div className="flex flex-wrap items-start gap-3 p-5">
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="min-w-0 flex-1 text-left"
        >
          <span className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-text-primary">
              {playbook.name}
            </span>
            <Badge
              variant={
                playbook.status === "active"
                  ? "accent"
                  : playbook.status === "paused"
                    ? "warning"
                    : "outline"
              }
            >
              {playbook.status}
            </Badge>
            <Badge variant="outline">{playbook.trigger_label}</Badge>
          </span>
          {playbook.description && (
            <span className="mt-1 block text-xs leading-relaxed text-text-muted">
              {playbook.description}
            </span>
          )}
          <span className="mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[11px] text-text-muted">
            <span>
              {playbook.analyses.length}{" "}
              {playbook.analyses.length === 1 ? "analysis" : "analyses"}
            </span>
            <span>
              {playbook.conditions.length}{" "}
              {playbook.conditions.length === 1 ? "condition" : "conditions"}
            </span>
            {Object.keys(playbook.scope).length > 0 && (
              <span>
                scoped to{" "}
                {Object.entries(playbook.scope)
                  .map(([k, v]) => `${k} ${String(v)}`)
                  .join(", ")}
              </span>
            )}
            <span>
              {playbook.run_count} {playbook.run_count === 1 ? "run" : "runs"}
            </span>
          </span>
        </button>

        <div className="flex shrink-0 items-center gap-1">
          <Button size="sm" onClick={execute} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
            Run now
          </Button>
          <Button variant="ghost" size="sm" onClick={toggle}>
            {playbook.status === "active" ? <Pause aria-hidden /> : <Check aria-hidden />}
            {playbook.status === "active" ? "Pause" : "Activate"}
          </Button>
          <Button variant="ghost" size="sm" onClick={remove} title="Delete">
            <Trash2 aria-hidden />
            <span className="sr-only">Delete</span>
          </Button>
          <ChevronDown
            className={cn(
              "size-4 text-text-muted transition-transform",
              open && "rotate-180",
            )}
            aria-hidden
          />
        </div>
      </div>

      {error && (
        <p className="border-t border-border px-5 py-3 text-xs text-negative">{error}</p>
      )}

      {open && (
        <div className="space-y-5 border-t border-border bg-surface-sunken px-5 py-4">
          <Definition playbook={playbook} />
          {run ? <RunReport run={run} /> : (
            <p className="text-xs text-text-muted">
              This playbook has not run yet.
            </p>
          )}
        </div>
      )}
    </Card>
  );
}

function Definition({ playbook }: { playbook: Playbook }) {
  return (
    <div className="grid gap-5 md:grid-cols-2">
      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Analyses it runs
        </p>
        <ul className="space-y-1">
          {playbook.analyses.map((step) => (
            <li key={step.analysis_id} className="text-xs">
              <Link
                href={`/engine-builder/${step.analysis_id}`}
                className="text-text-secondary hover:text-accent"
              >
                {step.analysis_id}
              </Link>
            </li>
          ))}
        </ul>
      </div>

      <div>
        <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
          Conditions it tests
        </p>
        {playbook.conditions.length > 0 ? (
          <ul className="space-y-1">
            {playbook.conditions.map((condition) => (
              <li key={condition.metric} className="text-xs text-text-secondary">
                {condition.label || condition.metric} {condition.operator}{" "}
                {condition.threshold}
                {condition.unit}
                <Badge variant="outline" className="ml-2">
                  {condition.severity}
                </Badge>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-text-muted">
            None. The results are there to be read rather than judged.
          </p>
        )}
      </div>
    </div>
  );
}

/* -------------------------------------------------------------- run report */

function RunReport({ run }: { run: PlaybookRun }) {
  return (
    <div className="space-y-3">
      <p className="mb-1 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        Last run
      </p>
      <p className="max-w-3xl text-sm leading-relaxed text-text-primary">
        {run.summary}
      </p>

      {run.evaluations.length > 0 && (
        <ul className="space-y-1.5">
          {run.evaluations.map((evaluation) => (
            <Finding key={evaluation.metric} evaluation={evaluation} />
          ))}
        </ul>
      )}

      {run.results.length > 0 && (
        <p className="flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-text-muted">
          {run.results.map((result) =>
            result.analysis_run_id ? (
              <Link
                key={result.analysis_id}
                href={`/trace/${result.analysis_run_id}`}
                className="hover:text-accent"
              >
                {result.analysis_id} · Trace
              </Link>
            ) : (
              <span key={result.analysis_id}>{result.analysis_id}</span>
            ),
          )}
        </p>
      )}

      {run.investigation_id && (
        <p className="text-xs">
          <Link
            href={withReturnTo(
              `/investigations/${run.investigation_id}`,
              "/playbooks",
              "Playbooks",
            )}
            className="text-accent hover:underline"
          >
            An investigation was opened on what this found
          </Link>
        </p>
      )}

      {run.error && <p className="text-xs text-negative">{run.error}</p>}
    </div>
  );
}

function Finding({ evaluation }: { evaluation: PlaybookEvaluation }) {
  const tone = !evaluation.testable
    ? "text-text-muted"
    : evaluation.met
      ? evaluation.severity === "critical"
        ? "text-negative"
        : "text-warning"
      : "text-text-secondary";

  return (
    <li className={cn("flex items-start gap-2 text-xs leading-relaxed", tone)}>
      {evaluation.met ? (
        <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
      ) : (
        <Check className="mt-0.5 size-3 shrink-0 opacity-50" aria-hidden />
      )}
      {evaluation.sentence}
    </li>
  );
}

/* --------------------------------------------------------------- authoring */

function NewPlaybook({
  analyses,
  operators,
  dimensions,
  triggers,
  onCreated,
  onCancel,
}: {
  analyses: AnalysisSummary[];
  operators: Record<string, string>;
  dimensions: string[];
  triggers: Record<string, string>;
  onCreated: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [trigger, setTrigger] = React.useState("manual");
  const [chosen, setChosen] = React.useState<string[]>([]);
  const [scopeDimension, setScopeDimension] = React.useState("");
  const [scopeValue, setScopeValue] = React.useState("");
  const [conditions, setConditions] = React.useState<PlaybookCondition[]>([]);
  const [createInvestigation, setCreateInvestigation] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  function addCondition() {
    setConditions((current) => [
      ...current,
      { metric: "", label: "", operator: ">", threshold: 0, unit: "", severity: "warning" },
    ]);
  }

  function setCondition(index: number, patch: Partial<PlaybookCondition>) {
    setConditions((current) =>
      current.map((c, i) => (i === index ? { ...c, ...patch } : c)),
    );
  }

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.createPlaybook({
        name,
        description,
        trigger,
        scope:
          scopeDimension && scopeValue ? { [scopeDimension]: scopeValue } : {},
        analyses: chosen.map((id) => ({ analysis_id: id })),
        conditions: conditions.filter((c) => c.metric.trim()),
        actions: { create_investigation: createInvestigation, notify: [] },
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-5 p-5">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor="pb-name" className="text-xs font-medium text-text-secondary">
            Name
          </label>
          <Input
            id="pb-name"
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Quarterly deterioration review"
            className="mt-1"
          />
        </div>
        <div>
          <label htmlFor="pb-trigger" className="text-xs font-medium text-text-secondary">
            When should it run?
          </label>
          <select
            id="pb-trigger"
            value={trigger}
            onChange={(e) => setTrigger(e.target.value)}
            className="mt-1 h-9 w-full rounded-md border border-border bg-surface px-3 text-sm text-text-primary focus:border-accent focus:outline-none"
          >
            {Object.entries(triggers).map(([id, label]) => (
              <option key={id} value={id}>
                {label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div>
        <label htmlFor="pb-desc" className="text-xs font-medium text-text-secondary">
          What is it for?
        </label>
        <Input
          id="pb-desc"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Check whether Stage 2 or NPL has moved past appetite."
          className="mt-1"
        />
      </div>

      <div>
        <p className="mb-2 flex items-center gap-1.5 text-xs font-medium text-text-secondary">
          Analyses to run
          <InfoPopover title="Why only these">
            <p>
              A playbook can only run analyses the Engine Registry knows about.
              It cannot invent one, write a query, or compute a metric of its
              own.
            </p>
          </InfoPopover>
        </p>
        <div className="flex flex-wrap gap-1.5">
          {analyses.map((analysis) => (
            <button
              key={analysis.id}
              type="button"
              onClick={() =>
                setChosen((current) =>
                  current.includes(analysis.id)
                    ? current.filter((id) => id !== analysis.id)
                    : [...current, analysis.id],
                )
              }
              className={cn(
                "rounded-full border px-3 py-1 text-xs transition-colors",
                chosen.includes(analysis.id)
                  ? "border-accent bg-accent-muted text-accent"
                  : "border-border bg-surface text-text-secondary hover:border-accent",
              )}
            >
              {analysis.name}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor="pb-dim" className="text-xs font-medium text-text-secondary">
            Scope (optional)
          </label>
          <div className="mt-1 flex gap-2">
            <select
              id="pb-dim"
              value={scopeDimension}
              onChange={(e) => setScopeDimension(e.target.value)}
              className="h-9 rounded-md border border-border bg-surface px-3 text-sm text-text-primary focus:border-accent focus:outline-none"
            >
              <option value="">Whole book</option>
              {dimensions.map((dimension) => (
                <option key={dimension} value={dimension}>
                  {dimension}
                </option>
              ))}
            </select>
            <Input
              value={scopeValue}
              onChange={(e) => setScopeValue(e.target.value)}
              placeholder="Contracting"
              disabled={!scopeDimension}
            />
          </div>
        </div>
        <div className="flex items-end">
          <label className="flex items-center gap-2 text-xs text-text-secondary">
            <input
              type="checkbox"
              checked={createInvestigation}
              onChange={(e) => setCreateInvestigation(e.target.checked)}
              className="size-3.5 accent-[var(--accent)]"
            />
            Open an investigation when a condition is met
          </label>
        </div>
      </div>

      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
            Conditions
            <InfoPopover title="How a condition is tested">
              <p>
                The metric is looked up by name among the figures the analyses
                returned, and compared with your threshold. Nothing is converted
                or inferred.
              </p>
              <p>
                If no analysis produced a metric by that name, the run says the
                condition could not be tested — which is a different thing from
                the condition being false.
              </p>
            </InfoPopover>
          </p>
          <Button variant="ghost" size="sm" onClick={addCondition}>
            <Plus aria-hidden />
            Add
          </Button>
        </div>

        {conditions.map((condition, index) => (
          <div key={index} className="mb-2 flex flex-wrap items-center gap-2">
            <Input
              value={condition.metric}
              onChange={(e) => setCondition(index, { metric: e.target.value })}
              placeholder="stage2_pct"
              className="w-44"
            />
            <select
              value={condition.operator}
              onChange={(e) => setCondition(index, { operator: e.target.value })}
              aria-label="Comparison"
              className="h-9 rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            >
              {Object.entries(operators).map(([op, label]) => (
                <option key={op} value={op}>
                  {label}
                </option>
              ))}
            </select>
            <Input
              type="number"
              value={condition.threshold}
              onChange={(e) =>
                setCondition(index, { threshold: Number(e.target.value) })
              }
              className="w-24 tabular"
            />
            <Input
              value={condition.unit}
              onChange={(e) => setCondition(index, { unit: e.target.value })}
              placeholder="%"
              className="w-16"
            />
            <select
              value={condition.severity}
              onChange={(e) => setCondition(index, { severity: e.target.value })}
              aria-label="Severity"
              className="h-9 rounded-md border border-border bg-surface px-2 text-sm text-text-primary focus:border-accent focus:outline-none"
            >
              <option value="info">info</option>
              <option value="warning">warning</option>
              <option value="critical">critical</option>
            </select>
          </div>
        ))}
      </div>

      {error && <p className="text-xs text-negative">{error}</p>}

      <div className="flex items-center gap-2">
        <Button
          size="sm"
          onClick={create}
          disabled={busy || !name.trim() || chosen.length === 0}
        >
          Create playbook
        </Button>
        <Button variant="ghost" size="sm" onClick={onCancel}>
          Cancel
        </Button>
      </div>
    </Card>
  );
}
