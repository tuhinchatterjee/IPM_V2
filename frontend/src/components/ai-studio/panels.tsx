"use client";

import * as React from "react";

import { Explain, Panel, Rules, Validation, Dot } from "@/components/ai-studio/shared";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  StudioCapabilityHealth,
  StudioJudgment,
  StudioObjects,
  StudioPermissions,
  StudioReadiness,
  StudioSections,
  StudioShapeLabResult,
  StudioVisualGrammar,
} from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The Studio's tab panels. §103-§116.
 *
 * Each one fetches its own data and each one is lazily imported by the page,
 * so opening Overview does not download the blueprint library or the fifteen
 * contradiction diagnostics.
 *
 * None of these compute anything. Every number on screen was computed by the
 * thing the panel is about, which is what stops the Studio drifting from the
 * product it describes.
 */

function useLoad<T>(load: () => Promise<T>) {
  const [state, setState] = React.useState<{
    data: T | null;
    error: string;
  }>({ data: null, error: "" });

  React.useEffect(() => {
    let live = true;
    load()
      .then((data) => live && setState({ data, error: "" }))
      .catch((e: unknown) =>
        live &&
        setState({
          data: null,
          error: e instanceof Error ? e.message : "Could not load this tab.",
        }),
      );
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return state;
}

function Loading() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-24 w-full" />
      <Skeleton className="h-24 w-full" />
    </div>
  );
}

function Failed({ message }: { message: string }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-text-secondary">{message}</p>
    </Card>
  );
}

// ---------------------------------------------------------------- §103, §104

export function Overview() {
  const readiness = useLoad<StudioReadiness>(() => api.studioReadiness());
  const health = useLoad<StudioCapabilityHealth>(() =>
    api.studioCapabilities(),
  );

  if (readiness.error) return <Failed message={readiness.error} />;
  if (!readiness.data || !health.data) return <Loading />;

  const ready = readiness.data;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-medium text-text-primary">
            Client-demo readiness
          </h3>
          <span className="text-xs font-medium text-text-primary">
            {ready.state.replaceAll("_", " ")}
          </span>
        </div>
        <p className="text-sm leading-relaxed text-text-secondary">
          {ready.means}
        </p>
        {ready.reasons.length ? (
          <ul className="space-y-1 text-xs text-text-secondary">
            {ready.reasons.map((reason) => (
              <li key={reason}>· {reason}</li>
            ))}
          </ul>
        ) : null}
        {ready.to_improve.length ? (
          <div>
            <p className="text-xs font-medium text-text-primary">
              What would move it up
            </p>
            <ul className="mt-1 space-y-1 text-xs text-text-secondary">
              {ready.to_improve.map((step) => (
                <li key={step}>· {step}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </Card>

      <Panel title="Capability health" count={health.data.capabilities.length}>
        <p className="text-xs text-text-tertiary">
          There is no overall score. Averaging eighteen dimensions of which one
          is a grounding defect produces a comfortable number and hides the only
          row that matters.
        </p>
        <ul className="mt-2 divide-y divide-border">
          {health.data.capabilities.map((row) => (
            <li key={row.capability} className="py-2.5">
              <div className="flex items-start gap-2">
                <Dot
                  ok={
                    row.status === "NOT_EVALUATED"
                      ? null
                      : row.status === "HEALTHY"
                  }
                />
                <div className="min-w-0">
                  <p className="text-xs font-medium text-text-primary">
                    {row.capability.replaceAll("_", " ")}
                    {row.critical ? (
                      <span className="ml-2 text-status-warning">critical</span>
                    ) : null}
                  </p>
                  <p className="text-xs leading-relaxed text-text-secondary">
                    {row.means}
                  </p>
                  <p className="text-xs text-text-tertiary">{row.sentence}</p>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §105

export function Knowledge() {
  const { data, error } = useLoad<StudioSections>(() => api.studioKnowledge());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      {data.sections.map((section) => (
        <Panel
          key={section.id}
          title={section.name}
          count={section.count}
          editIn={section.edit_in}
          explanation={section.explanation}
        >
          {section.rows.length ? (
            <ul className="max-h-64 space-y-1 overflow-y-auto text-xs text-text-secondary">
              {section.rows.slice(0, 60).map((row, index) => (
                <li key={index}>
                  {Object.entries(row)
                    .filter(([, v]) => v !== "" && v != null)
                    .map(([k, v]) => `${k}: ${String(v)}`)
                    .join(" · ")}
                </li>
              ))}
            </ul>
          ) : null}
        </Panel>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------- §107

export function Blueprints() {
  const { data, error } = useLoad<StudioObjects>(() => api.studioBlueprints());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-3">
      <p className="text-xs text-text-tertiary">
        {data.count} blueprints. Each one says what it investigates, what may
        not be omitted, and what may be — with a recorded reason.
      </p>
      {data.objects.map((object) => (
        <Card key={object.object_id} className="space-y-3 p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium text-text-primary">
              {object.name}
            </h3>
            <span className="text-xs text-text-tertiary">
              {String(object.family ?? "")}
            </span>
          </div>
          <Explain explanation={object.explanation} />
          <Validation validation={object.validation} />
          <Objectives
            label="Mandatory objectives"
            rows={
              (object.mandatory_objectives as {
                id: string;
                statement: string;
              }[]) ?? []
            }
          />
          <Objectives
            label="May be omitted, with a reason"
            rows={
              (object.optional_objectives as {
                id: string;
                statement: string;
              }[]) ?? []
            }
          />
        </Card>
      ))}
    </div>
  );
}

function Objectives({
  label,
  rows,
}: {
  label: string;
  rows: { id: string; statement: string }[];
}) {
  if (!rows.length) return null;
  return (
    <div>
      <p className="text-xs font-medium text-text-primary">{label}</p>
      <ul className="mt-1 space-y-0.5 text-xs text-text-secondary">
        {rows.map((row) => (
          <li key={row.id}>· {row.statement}</li>
        ))}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------- §108

export function Judgment() {
  const { data, error } = useLoad<StudioJudgment>(() => api.studioJudgment());
  const [sub, setSub] = React.useState<string>("");
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  const active = sub || data.subtabs[0];
  const policy = data.policies[active];

  return (
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label="Analytical judgment policies"
        className="flex flex-wrap gap-1 border-b border-border pb-2"
      >
        {data.subtabs.map((one) => (
          <button
            key={one}
            type="button"
            role="tab"
            onClick={() => setSub(one)}
            aria-selected={one === active}
            className={cn(
              "rounded px-2.5 py-1 text-xs",
              one === active
                ? "bg-surface-raised font-medium text-text-primary"
                : "text-text-secondary hover:text-text-primary",
            )}
          >
            {one.replaceAll("_", " ").toLowerCase()}
          </button>
        ))}
      </div>
      {policy ? (
        <Panel
          title={`${policy.name} · v${policy.version}`}
          explanation={policy.explanation}
        >
          <p className="text-xs text-text-tertiary">
            The rules themselves, not a description of them. A reviewer cannot
            challenge &ldquo;assessed against a weighted model&rdquo;; they can
            challenge a weight.
          </p>
          <div className="mt-2">
            <Rules rules={policy.rules} />
          </div>
        </Panel>
      ) : null}
    </div>
  );
}

// ---------------------------------------------------------------------- §109

export function VisualGrammar() {
  const { data, error } = useLoad<StudioVisualGrammar>(() =>
    api.studioVisualGrammar(),
  );
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="What each field means" explanation={data.explanation}>
        <ul className="mt-2 divide-y divide-border">
          {data.roles.map((role) => (
            <li key={role.id} className="py-2">
              <p className="text-xs font-medium text-text-primary">
                {role.id}
                {role.never_drawn ? (
                  <span className="ml-2 text-status-warning">never drawn</span>
                ) : null}
              </p>
              <p className="text-xs leading-relaxed text-text-secondary">
                {role.means}
              </p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Result shape to chart" count={data.mapping.length}>
        <ul className="divide-y divide-border">
          {data.mapping.map((row) => (
            <li key={row.shape} className="py-2">
              <p className="text-xs font-medium text-text-primary">
                {row.shape.replaceAll("_", " ")} → {row.default_label}
              </p>
              <p className="text-xs text-text-secondary">{row.means}</p>
              {row.alternatives.length ? (
                <p className="text-xs text-text-tertiary">
                  also acceptable: {row.alternatives.join(", ")}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="What the critic refuses" count={data.critic.length}>
        <ul className="divide-y divide-border">
          {data.critic.map((check) => (
            <li key={check.id} className="flex items-start gap-2 py-2">
              <Dot ok={!check.fatal} />
              <div>
                <p className="text-xs text-text-primary">{check.asks}</p>
                {check.fatal ? (
                  <p className="text-xs text-text-tertiary">
                    A failure here is a chart that asserts something untrue, not
                    one that reads badly.
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-text-tertiary">
          {data.accessibility} Display precision is at most{" "}
          {data.precision_contract.max_decimals} decimals.
        </p>
      </Panel>

      <ShapeLab shapes={data.mapping.map((m) => m.shape)} />
    </div>
  );
}

/** §109's Result Shape Lab. Takes a shape, never rows. */
function ShapeLab({ shapes }: { shapes: string[] }) {
  const [shape, setShape] = React.useState(shapes[0] ?? "");
  const [categories, setCategories] = React.useState(8);
  const [result, setResult] = React.useState<StudioShapeLabResult | null>(null);
  const [busy, setBusy] = React.useState(false);

  const run = async () => {
    setBusy(true);
    try {
      setResult(
        await api.studioShapeLab({
          shape,
          roles: { category: "CATEGORY", value: "MEASURE" },
          categories,
          measures: 1,
          cardinality: categories,
          periods: 8,
        }),
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <Panel title="Result shape lab">
      <p className="text-xs text-text-tertiary">
        A sanitised result SHAPE in, the whole decision out — every candidate,
        its score and why it was refused. No portfolio data is needed or
        accepted.
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-3">
        <label className="text-xs text-text-secondary">
          Shape
          <select
            value={shape}
            onChange={(e) => setShape(e.target.value)}
            className="ml-2 rounded border border-border bg-surface px-2 py-1 text-xs text-text-primary"
          >
            {shapes.map((one) => (
              <option key={one} value={one}>
                {one.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-text-secondary">
          Categories
          <input
            type="number"
            min={1}
            value={categories}
            onChange={(e) => setCategories(Number(e.target.value) || 1)}
            className="ml-2 w-20 rounded border border-border bg-surface px-2 py-1 text-xs text-text-primary"
          />
        </label>
        <button
          type="button"
          onClick={run}
          disabled={busy}
          className="rounded bg-surface-raised px-3 py-1 text-xs font-medium text-text-primary disabled:opacity-50"
        >
          {busy ? "Working…" : "Preview"}
        </button>
      </div>

      {result ? (
        <div className="mt-3 space-y-2">
          <p className="text-xs font-medium text-text-primary">
            {result.reason ?? result.message}
          </p>
          {result.candidates?.length ? (
            <ul className="divide-y divide-border">
              {result.candidates.map((candidate) => (
                <li key={candidate.chart} className="flex items-start gap-2 py-1.5">
                  <Dot ok={candidate.accepted} />
                  <div>
                    <p className="text-xs text-text-primary">
                      {candidate.label} · {candidate.total.toFixed(2)}
                    </p>
                    {candidate.rejections.map((why) => (
                      <p key={why} className="text-xs text-text-secondary">
                        {why}
                      </p>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </Panel>
  );
}

// ---------------------------------------------------------------- §119, §120

export function Settings() {
  const permissions = useLoad<StudioPermissions>(() =>
    api.studioPermissions(),
  );
  const holdout = useLoad(() => api.studioHoldout());

  if (permissions.error) return <Failed message={permissions.error} />;
  if (!permissions.data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="Who may do what" count={permissions.data.permissions.length}>
        <p className="text-xs text-text-tertiary">
          Enforced in the backend. A tab hidden in the interface is a tab
          reachable with curl.
        </p>
        <ul className="mt-2 divide-y divide-border">
          {permissions.data.permissions.map((one) => (
            <li key={one.id} className="py-2">
              <p className="text-xs font-medium text-text-primary">{one.id}</p>
              <p className="text-xs text-text-secondary">{one.means}</p>
              <p className="text-xs text-text-tertiary">
                {one.roles.join(", ")}
              </p>
            </li>
          ))}
        </ul>
        {permissions.data.separated_duties.map((pair) => (
          <p key={pair.author} className="mt-2 text-xs text-text-tertiary">
            {pair.author} and {pair.review} are held apart: a person who writes
            a case and approves their own has produced a case with an approval
            record and no review.
          </p>
        ))}
      </Panel>

      {holdout.data ? (
        <Panel title="Sealed holdout">
          <p className="text-xs text-text-secondary">{holdout.data.note}</p>
          <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
            {holdout.data.shown.map((field) => (
              <div key={field}>
                <dt className="text-text-tertiary">
                  {field.replaceAll("_", " ")}
                </dt>
                <dd className="text-text-primary">
                  {String(
                    (holdout.data as unknown as Record<string, unknown>)[
                      field
                    ] ?? "—",
                  )}
                </dd>
              </div>
            ))}
          </dl>
        </Panel>
      ) : null}
    </div>
  );
}

/** Tabs whose content lands with a later part of the brief. */
export function ComingWithLaterWork({
  title,
  what,
}: {
  title: string;
  what: string;
}) {
  return (
    <Card className="space-y-2 p-5">
      <h3 className="text-sm font-medium text-text-primary">{title}</h3>
      <p className="text-sm leading-relaxed text-text-secondary">{what}</p>
      <p className="text-xs text-text-tertiary">
        Shown as an empty tab rather than hidden, so the Studio&rsquo;s shape is
        the same for everybody and a reader can see what is coming rather than
        discovering it later.
      </p>
    </Card>
  );
}

// ---------------------------------------------------------------------- §106

export function TeachingCases() {
  const { data, error } = useLoad(() => api.studioTeachingCases());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="Who has actually reviewed this library" explanation={data.explanation}>
        <p className="text-sm leading-relaxed text-text-primary">
          {String(data.governance.sentence ?? "")}
        </p>
        <p className="mt-1 text-xs text-text-tertiary">{data.never_shown}</p>
      </Panel>
      <Panel title="Filters the case list supports">
        <p className="text-xs text-text-secondary">
          {data.filters.join(" · ")}
        </p>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §110

export function Routing() {
  const { data, error } = useLoad(() => api.studioRoutingTab());
  const [question, setQuestion] = React.useState("");
  const [simulation, setSimulation] = React.useState<{
    called_a_provider: boolean;
    note: string;
  } | null>(null);

  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="Model roles" count={data.roles.length} explanation={data.explanation}>
        <ul className="divide-y divide-border">
          {data.roles.map((role) => (
            <li key={role.name} className="py-2">
              <p className="text-xs font-medium text-text-primary">
                {role.name.replaceAll("_", " ")}
                {role.active ? null : (
                  <span className="ml-2 text-text-tertiary">inactive</span>
                )}
              </p>
              <p className="text-xs text-text-secondary">{role.purpose}</p>
              <p className="text-xs text-text-tertiary">
                {role.configured_model || "provider default"}
                {role.effort ? ` · ${role.effort}` : ""}
                {role.inherited ? " · inherited" : ""}
              </p>
            </li>
          ))}
        </ul>
      </Panel>

      <Panel title="Why a question goes where it goes">
        <dl className="space-y-2">
          {Object.entries(data.why).map(([id, why]) => (
            <div key={id}>
              <dt className="text-xs font-medium text-text-primary">{id}</dt>
              <dd className="text-xs leading-relaxed text-text-secondary">
                {why}
              </dd>
            </div>
          ))}
        </dl>
        <p className="mt-2 text-xs text-text-tertiary">
          {data.fallback_policy.note}
        </p>
      </Panel>

      <Panel title="Route simulator">
        <p className="text-xs text-text-tertiary">
          Predicts the route from the same signals the runtime uses. Nothing is
          sent anywhere and nothing is spent, so try as many phrasings as you
          like.
        </p>
        <div className="mt-2 flex flex-wrap items-end gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="A sanitised question"
            className="min-w-64 flex-1 rounded border border-border bg-surface px-2 py-1 text-xs text-text-primary"
          />
          <button
            type="button"
            disabled={!question.trim()}
            onClick={async () =>
              setSimulation(await api.studioRouteSimulator(question))
            }
            className="rounded bg-surface-raised px-3 py-1 text-xs font-medium text-text-primary disabled:opacity-50"
          >
            Predict
          </button>
        </div>
        {simulation ? (
          <p className="mt-2 text-xs text-text-secondary">{simulation.note}</p>
        ) : null}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §112

export function Evaluations() {
  const { data, error } = useLoad(() => api.studioEvaluations());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="Seven suites, kept apart" explanation={data.explanation}>
        <ul className="mt-1 space-y-0.5 text-xs text-text-secondary">
          {data.subtabs.map((one) => (
            <li key={one}>· {one.replaceAll("_", " ").toLowerCase()}</li>
          ))}
        </ul>
      </Panel>
      <Panel title="What a number here is allowed to claim">
        <Rules rules={data.reporting_rules} />
      </Panel>
      <Panel title="Cost">
        <p className="text-xs text-text-secondary">{data.cost_control.note}</p>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §114

export function Failures() {
  const { data, error } = useLoad(() => api.studioFailures());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="The active-learning queue" explanation={data.explanation}>
        <p className="text-sm leading-relaxed text-text-secondary">
          {data.note}
        </p>
      </Panel>
      <Panel title="Failure categories" count={data.categories.length}>
        <ul className="divide-y divide-border">
          {data.categories.map((one) => (
            <li key={one.id} className="flex items-start gap-2 py-2">
              <Dot ok={!one.critical} />
              <div>
                <p className="text-xs font-medium text-text-primary">
                  {one.label}
                  <span className="ml-2 text-text-tertiary">{one.stage}</span>
                </p>
                <p className="text-xs leading-relaxed text-text-secondary">
                  {one.looks_like}
                </p>
              </div>
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §115

export function Releases() {
  const { data, error } = useLoad(() => api.studioReleasesTab());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="The release in force" explanation={data.explanation}>
        <p className="text-sm text-text-primary">
          {String(data.gate.state ?? "unknown")}
        </p>
        <p className="text-xs leading-relaxed text-text-secondary">
          {String(data.gate.reason ?? "")}
        </p>
        {data.missing_files.length ? (
          <p className="mt-1 text-xs text-status-warning">
            Missing from the release: {data.missing_files.join(", ")}
          </p>
        ) : null}
      </Panel>
      <Panel title="Actions">
        <ul className="space-y-1">
          {data.actions.map((one) => (
            <li key={one.id} className="text-xs">
              <span className="font-medium text-text-primary">{one.label}</span>
              <span className="text-text-tertiary"> · {one.needs}</span>
              {one.note ? (
                <span className="text-text-secondary"> — {one.note}</span>
              ) : null}
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-text-tertiary">{data.never}</p>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §116

export function LiveHealth() {
  const { data, error } = useLoad(() => api.studioLiveHealth());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel title="Provider">
        <p className="text-sm text-text-primary">
          {String(data.provider.state ?? "unknown")}
        </p>
        <p className="text-xs text-text-tertiary">
          CONNECTED means a real response came back, not that a key is present.
        </p>
      </Panel>
      <Panel title="Safe local commands">
        <ul className="space-y-3">
          {data.commands.map((one) => (
            <li key={one.what}>
              <p className="text-xs font-medium text-text-primary">
                {one.what}
              </p>
              <pre className="mt-1 overflow-x-auto rounded bg-surface-raised p-2 text-xs text-text-secondary">
                {one.windows}
                {"\n"}
                {one.unix}
              </pre>
            </li>
          ))}
        </ul>
        <p className="mt-2 text-xs text-text-tertiary">
          Never shown here: {data.never_shown.join(", ")}.
        </p>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------- §111

export function Prompts() {
  const { data, error } = useLoad(() => api.studioPrompts());
  if (error) return <Failed message={error} />;
  if (!data) return <Loading />;

  return (
    <div className="space-y-4">
      <Panel
        title="What may reach a model"
        explanation={data.explanation}
      >
        <Rules rules={(data.pack_policy ?? {}) as Record<string, unknown>} />
      </Panel>
      <Panel title="Prompt caching">
        <Rules rules={(data.caching ?? {}) as Record<string, unknown>} />
      </Panel>
      <Panel title="Promotion">
        <Rules rules={(data.promotion ?? {}) as Record<string, unknown>} />
      </Panel>
    </div>
  );
}
