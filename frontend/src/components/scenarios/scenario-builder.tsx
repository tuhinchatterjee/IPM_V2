"use client";

/**
 * Create a Scenario Definition WITHOUT executing it (SC-01). Every component
 * is typed; the preview resolves it against the book the server serves and
 * says what each component would translate to, or why it cannot. Saving makes
 * a DRAFT or SAVED object; running it is a separate, explicit step.
 */

import * as React from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Eye, Loader2, Plus, Save, Trash2 } from "lucide-react";

import { DomainSwitchPlain } from "@/components/guided/domain-toggle";
import { PreviewPanel } from "@/components/scenarios/preview-panel";
import { readGridSchema, type GridColumn } from "@/lib/workspace/guided";
import { readObject, type CohortBody, type DomainId } from "@/lib/workspace/objects";
import { blankComponent, kindsFor } from "@/lib/workspace/scenario-figures";
import {
  createScenario,
  previewDefinition,
  type Component,
  type Definition,
  type Filter,
  type Preview,
  type Scope,
} from "@/lib/workspace/scenarios";

const PARAMETER_FIELDS: Record<DomainId, string[]> = {
  corporate: ["pd_pit_12m", "pd_lifetime", "lgd_pct", "ead_sar_mn", "ccf", "drawn_sar_mn", "undrawn_sar_mn"],
  retail: ["pd_pit_12m", "pd_lifetime", "lgd_pct", "ead_sar_mn", "balance_sar_mn"],
};
const OPERATIONS = ["relative_pct", "absolute_pp", "basis_points", "multiply", "set_to"];
const MACRO_OPS = ["percentage_points", "basis_points", "relative_percent", "index_points"];
const FILTER_OPS = ["in", "eq", "neq", "gt", "gte", "lt", "lte", "contains"];

export function ScenarioBuilder() {
  const router = useRouter();
  const params = useSearchParams();
  const [domain, setDomain] = React.useState<DomainId>((params.get("domain") as DomainId) || "corporate");
  const [name, setName] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [thesis, setThesis] = React.useState("");
  const [severity, setSeverity] = React.useState("moderate");
  const [stagePolicy, setStagePolicy] = React.useState("frozen");
  const [scopeMode, setScopeMode] = React.useState<"whole_book" | "filters" | "cohort">("whole_book");
  const [filters, setFilters] = React.useState<Filter[]>([{ column: domain === "corporate" ? "sector" : "product", op: "in", values: [] }]);
  const [cohortScope, setCohortScope] = React.useState<Scope | null>(null);
  const [components, setComponents] = React.useState<Component[]>([blankComponent("parameter", domain)]);
  const [columns, setColumns] = React.useState<GridColumn[]>([]);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);

  React.useEffect(() => {
    readGridSchema(domain)
      .then((s) => setColumns(s.columns))
      .catch(() => setColumns([]));
  }, [domain]);

  // Arriving with ?cohort= binds the definition to that governed cohort.
  const cohortId = params.get("cohort") ?? "";
  React.useEffect(() => {
    if (!cohortId) return;
    readObject<CohortBody>(cohortId)
      .then((c) => {
        setDomain(c.body.domain_id);
        setScopeMode("cohort");
        setCohortScope({
          type: "cohort",
          cohort_id: c.object_id,
          label: `Cohort: ${c.body.name}`,
          filters: c.body.filters as unknown as Filter[],
          membership_hash: c.body.membership_hash,
        });
      })
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [cohortId]);

  function changeDomain(d: DomainId) {
    setDomain(d);
    setPreview(null);
    setComponents([blankComponent("parameter", d)]);
    setFilters([{ column: d === "corporate" ? "sector" : "product", op: "in", values: [] }]);
    if (scopeMode === "cohort") setScopeMode("whole_book");
  }

  function scope(): Scope {
    if (scopeMode === "cohort" && cohortScope) return cohortScope;
    if (scopeMode === "filters") return { type: "filters", filters: filters.filter((f) => f.column) };
    return { type: "whole_book" };
  }

  function definition(): Partial<Definition> {
    return {
      name: name.trim() || "Untitled scenario",
      domain_id: domain,
      description,
      risk_thesis: thesis,
      severity: severity as Definition["severity"],
      stage_policy: stagePolicy,
      scope: scope(),
      components,
      composition_policy: { resolutions: {} },
      tags: ["user"],
      assumptions: [],
      limitations: [],
    };
  }

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4" data-testid="scenario-builder">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text-primary">New scenario</h1>
        <DomainSwitchPlain value={domain} onChange={changeDomain} />
        <span className="text-xs text-text-muted">Saved as a definition. Nothing is calculated here.</span>
      </header>

      <div className="grid gap-3 md:grid-cols-2">
        <Field label="Name">
          <input value={name} onChange={(e) => setName(e.target.value)} className="w-full rounded border border-border bg-surface px-2 py-1 text-sm" data-testid="builder-name" />
        </Field>
        <div className="grid grid-cols-2 gap-2">
          <Field label="Severity">
            <select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-full rounded border border-border bg-surface px-2 py-1 text-sm">
              {["upside", "mild", "moderate", "severe"].map((s) => (
                <option key={s}>{s}</option>
              ))}
            </select>
          </Field>
          <Field label="Stage policy">
            <select value={stagePolicy} onChange={(e) => setStagePolicy(e.target.value)} className="w-full rounded border border-border bg-surface px-2 py-1 text-sm" data-testid="builder-stage-policy">
              <option value="frozen">Hold stages</option>
              <option value="retest_sicr">Re-test SICR</option>
              <option value="cure_retest">Cure re-test (upside)</option>
            </select>
          </Field>
        </div>
        <Field label="Description">
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} rows={2} className="w-full rounded border border-border bg-surface px-2 py-1 text-sm" />
        </Field>
        <Field label="Risk thesis">
          <textarea value={thesis} onChange={(e) => setThesis(e.target.value)} rows={2} className="w-full rounded border border-border bg-surface px-2 py-1 text-sm" />
        </Field>
      </div>

      <section className="space-y-2 rounded-lg border border-border bg-surface p-3" data-testid="builder-scope">
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="font-semibold">Scope</span>
          {(["whole_book", "filters", "cohort"] as const).map((m) => (
            <label key={m} className="flex items-center gap-1">
              <input type="radio" checked={scopeMode === m} disabled={m === "cohort" && !cohortScope} onChange={() => setScopeMode(m)} data-testid={`builder-scope-${m}`} />
              {m === "whole_book" ? "Whole book" : m === "filters" ? "Filtered segment" : cohortScope ? cohortScope.label : "Saved cohort (open from What-If)"}
            </label>
          ))}
        </div>
        {scopeMode === "filters" && (
          <div className="space-y-1">
            {filters.map((f, i) => (
              <div key={i} className="flex flex-wrap items-center gap-2 text-xs" data-testid="builder-filter">
                <select
                  value={f.column}
                  onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, column: e.target.value } : x)))}
                  className="rounded border border-border bg-surface px-1 py-0.5"
                  data-testid="builder-filter-column"
                >
                  {columns.map((c) => (
                    <option key={c.key} value={c.key}>
                      {c.label}
                    </option>
                  ))}
                </select>
                <select value={f.op} onChange={(e) => setFilters(filters.map((x, j) => (j === i ? { ...x, op: e.target.value } : x)))} className="rounded border border-border bg-surface px-1 py-0.5">
                  {FILTER_OPS.map((o) => (
                    <option key={o}>{o}</option>
                  ))}
                </select>
                <input
                  value={f.op === "in" ? (f.values ?? []).join(", ") : String(f.value ?? "")}
                  onChange={(e) =>
                    setFilters(
                      filters.map((x, j) =>
                        j === i
                          ? f.op === "in"
                            ? { column: x.column, op: x.op, values: e.target.value.split(",").map((v) => v.trim()).filter(Boolean) }
                            : { column: x.column, op: x.op, value: e.target.value }
                          : x,
                      ),
                    )
                  }
                  placeholder={f.op === "in" ? "Value, value, …" : "Value"}
                  className="min-w-[16rem] flex-1 rounded border border-border bg-surface px-2 py-0.5"
                  data-testid="builder-filter-value"
                />
                <button type="button" onClick={() => setFilters(filters.filter((_, j) => j !== i))} aria-label="Remove filter">
                  <Trash2 className="h-3 w-3" />
                </button>
              </div>
            ))}
            <button type="button" onClick={() => setFilters([...filters, { column: "stage", op: "in", values: [] }])} className="text-xs text-accent">
              + filter (all filters must hold)
            </button>
          </div>
        )}
      </section>

      <section className="space-y-2 rounded-lg border border-border bg-surface p-3" data-testid="builder-components">
        <div className="flex items-center gap-2 text-sm">
          <span className="font-semibold">Components</span>
          <span className="text-xs text-text-muted">Relative percent, percentage points and basis points are different operations.</span>
        </div>
        {components.map((c, i) => (
          <ComponentRow
            key={i}
            index={i}
            domain={domain}
            value={c}
            onChange={(next) => setComponents(components.map((x, j) => (j === i ? next : x)))}
            onRemove={() => setComponents(components.filter((_, j) => j !== i))}
          />
        ))}
        <div className="flex flex-wrap gap-1 text-xs">
          {kindsFor(domain).map((k) => (
            <button key={k} type="button" onClick={() => setComponents([...components, blankComponent(k, domain)])} className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5" data-testid={`builder-add-${k}`}>
              <Plus className="h-3 w-3" /> {k}
            </button>
          ))}
        </div>
      </section>

      <div className="flex flex-wrap gap-2">
        <button type="button" disabled={busy} onClick={() => run(async () => setPreview(await previewDefinition(definition())))} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="builder-preview">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Eye className="h-4 w-4" />} Preview (no calculation)
        </button>
        {(["DRAFT", "SAVED"] as const).map((status) => (
          <button
            key={status}
            type="button"
            disabled={busy || !name.trim()}
            onClick={() =>
              run(async () => {
                const obj = await createScenario(definition(), status);
                router.push(`/scenarios/${obj.object_id}`);
              })
            }
            className={status === "SAVED" ? "inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast disabled:opacity-40" : "inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-40"}
            data-testid={`builder-save-${status.toLowerCase()}`}
          >
            <Save className="h-4 w-4" /> {status === "SAVED" ? "Save" : "Save draft"}
          </button>
        ))}
      </div>
      {error && <p role="alert" className="text-sm text-negative" data-testid="builder-error">{error}</p>}
      {preview && <PreviewPanel preview={preview} testId="builder-preview-panel" />}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block text-xs text-text-muted">
      {label}
      <div className="mt-0.5 text-text-primary">{children}</div>
    </label>
  );
}

function ComponentRow({
  index,
  domain,
  value,
  onChange,
  onRemove,
}: {
  index: number;
  domain: DomainId;
  value: Component;
  onChange: (c: Component) => void;
  onRemove: () => void;
}) {
  const c = value;
  const set = (patch: Partial<Component>) => onChange({ ...c, ...patch });
  const input = "rounded border border-border bg-surface px-1 py-0.5";
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="builder-component" data-kind={c.kind}>
      <span className="font-mono text-text-muted">c{index + 1}</span>
      <span className="font-semibold">{c.kind}</span>
      {c.kind === "parameter" && (
        <>
          <select value={c.field} onChange={(e) => set({ field: e.target.value })} className={input} data-testid="builder-component-field">
            {PARAMETER_FIELDS[domain].map((f) => (
              <option key={f}>{f}</option>
            ))}
          </select>
          <select value={c.operation} onChange={(e) => set({ operation: e.target.value })} className={input} data-testid="builder-component-operation">
            {OPERATIONS.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </>
      )}
      {c.kind === "macro" && (
        <>
          <input value={c.factor_id} onChange={(e) => set({ factor_id: e.target.value.toUpperCase() })} className={`${input} w-20`} aria-label="Factor id" data-testid="builder-component-factor" />
          <select value={c.operation} onChange={(e) => set({ operation: e.target.value })} className={input}>
            {MACRO_OPS.map((o) => (
              <option key={o}>{o}</option>
            ))}
          </select>
        </>
      )}
      {c.kind === "score" && (
        <>
          <select value={c.score_type} onChange={(e) => set({ score_type: e.target.value })} className={input}>
            <option>BEHAVIOURAL</option>
            <option>APPLICATION</option>
          </select>
          <select value={c.operation} onChange={(e) => set({ operation: e.target.value })} className={input}>
            <option>points</option>
            <option>bands</option>
          </select>
        </>
      )}
      {c.kind === "collateral" && (
        <select value={c.asset} onChange={(e) => set({ asset: e.target.value })} className={input}>
          <option value="commercial_property">commercial property</option>
          <option value="residential_property">residential property</option>
          <option value="vehicle">vehicle</option>
        </select>
      )}
      {(c.kind === "rating" || c.kind === "delinquency" || c.kind === "utilisation" || c.kind === "overlay") && <span className="text-text-muted">{c.operation}</span>}
      <input value={c.value} onChange={(e) => set({ value: e.target.value })} className={`${input} w-20`} aria-label="Value" data-testid="builder-component-value" />
      <button type="button" onClick={onRemove} aria-label="Remove component">
        <Trash2 className="h-3 w-3" />
      </button>
    </div>
  );
}
