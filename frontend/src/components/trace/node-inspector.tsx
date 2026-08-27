"use client";

import * as React from "react";
import { ArrowDown, ArrowUp, Check, Copy, X } from "lucide-react";

import { ResultTable } from "@/components/analytics/primitives";
import { Badge } from "@/components/ui/badge";
import type { TraceGraph, TraceNode } from "@/lib/api";
import { humanise } from "@/lib/format";
import { cn } from "@/lib/utils";

import { nodeSubtitle, nodeTitle, presentationFor } from "./node-presentation";

/**
 * The node inspector.
 *
 * Everything on this panel was stamped by the execution itself: which dataset,
 * which governed fields and their business definitions, which filters, how many
 * rows survived, which function at which version, how long it took, and the
 * content hash that decides whether a modification has to re-run it.
 *
 * Nothing here is a description written afterwards, which is the whole point of
 * the Trace and is stated on the panel so a reader knows what they are looking
 * at.
 */

/** Rendered by the mathematical-query block rather than the generic dump. */
const MATHS_KEYS = new Set([
  "sql",
  "parameters",
  "operations",
  "formulas",
  "plain_english",
  "kernels",
]);

/** Rendered by the fingerprint block rather than the generic config dump. */
const FINGERPRINT_KEYS = new Set([
  "run",
  "plan",
  "data",
  "relationships",
  "parameters",
  "datasets",
  "relationships_used",
  "parameters_used",
]);

const HIDDEN_CONFIG_KEYS = new Set([
  "_step",
  "_step_title",
  // Rendered by the dedicated blocks below rather than in the generic dump.
  "stage",
  "stage_label",
  "direct_answer",
  "interpretation",
  "interpretation_points",
  "summary",
  "rule",
  "variables",
]);

/**
 * What a reader is looking for when they open a step.
 *
 * Six questions, and they are asked one at a time. A single scrolling column
 * containing all of them is complete and unusable: the auditor checking a
 * hash, the analyst reading a formula and the reviewer tracing what a change
 * would break are three people who each need one sixth of it.
 */
export type InspectorTab =
  | "summary"
  | "inputs"
  | "outputs"
  | "formula"
  | "validation"
  | "impact";

export function NodeInspector({
  node,
  graph,
  onClose,
  onSelect,
}: {
  node: TraceNode | null;
  graph: TraceGraph;
  onClose: () => void;
  onSelect: (id: string) => void;
}) {
  const [tab, setTab] = React.useState<InspectorTab>("summary");

  // Selecting a different step keeps the tab where the reader left it — which
  // is what somebody comparing the same tab across two steps wants — and falls
  // back to the summary where the new step has nothing behind that tab. Derived
  // at render rather than reset in an effect, so there is no frame in which the
  // panel shows a tab that is not there.

  if (!node) {
    return (
      <div className="flex h-full flex-col justify-center gap-2 px-5 py-8">
        <p className="text-sm font-medium text-text-primary">Nothing selected</p>
        <p className="text-xs leading-relaxed text-text-muted">
          Choose a step on the map. Its dataset, governed variables, filters, row counts,
          function version and recorded output appear here — everything stamped while the
          analysis ran.
        </p>
      </div>
    );
  }

  const presentation = presentationFor(node.type);
  const Icon = presentation.icon;
  const parents = graph.edges.filter((e) => e.target === node.id).map((e) => e.source);
  const children = graph.edges.filter((e) => e.source === node.id).map((e) => e.target);
  const labelOf = (id: string) => graph.nodes.find((n) => n.id === id)?.label ?? id;

  // The execution stamps each governed field with its business name, unit and
  // definition. Older traces carry only a definitions map, so both are read.
  const variables = (node.config?.variables ?? []) as {
    field: string;
    business_name?: string;
    unit?: string;
    data_type?: string;
    definition?: string;
  }[];
  const definitions = (node.config?.definitions ?? null) as Record<string, string> | null;
  const stage = (node.config?.stage ?? "") as string;
  const stageLabel = (node.config?.stage_label ?? "") as string;
  const directAnswer = (node.config?.direct_answer ?? "") as string;
  const points = (node.config?.interpretation_points ?? []) as string[];
  const rule = (node.config?.rule ?? "") as string;
  const isDemo = node.config?.is_demo === true;
  // The fingerprint node has its own block below: four hashes and what each
  // one covers reads as a statement about the run, not as a config dump.
  const isFingerprint = node.type === "FINGERPRINT";
  const isMaths = node.type === "MATHEMATICAL_QUERY";
  // What the inspector can show for THIS node. A tab with nothing behind it is
  // a tab that teaches a reader the panel is mostly empty, so tabs appear only
  // where there is something to read.
  const config = Object.fromEntries(
    Object.entries(node.config ?? {}).filter(
      ([k]) =>
        !HIDDEN_CONFIG_KEYS.has(k) &&
        k !== "definitions" &&
        !(isFingerprint && FINGERPRINT_KEYS.has(k)) &&
        !(isMaths && MATHS_KEYS.has(k)),
    ),
  );

  const hasInputs = variables.length > 0 || node.fields_used.length > 0;
  const hasFormula = isMaths || Object.keys(config).length > 0;
  const hasOutputs =
    (node.output_summary && Object.keys(node.output_summary).length > 0) ||
    (node.output_preview?.length ?? 0) > 0;
  const hasValidation =
    isFingerprint || node.warnings.length > 0 || Boolean(node.error);
  const hasImpact = parents.length > 0 || children.length > 0;

  const tabs: { id: InspectorTab; label: string; enabled: boolean }[] = [
    { id: "summary", label: "Summary", enabled: true },
    { id: "inputs", label: "Inputs", enabled: hasInputs },
    { id: "outputs", label: "Outputs", enabled: hasOutputs },
    { id: "formula", label: isMaths ? "Formula / SQL" : "Configuration", enabled: hasFormula },
    { id: "validation", label: "Validation", enabled: hasValidation },
    { id: "impact", label: "Impact", enabled: hasImpact },
  ];
  const shown = tabs.find((t) => t.id === tab && t.enabled) ? tab : "summary";

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start justify-between gap-3 border-b border-border px-5 pb-2 pt-3.5">
        <div className="min-w-0">
          <span className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
            <Icon
              className="size-3"
              style={{
                color: presentation.governed
                  ? "var(--ipm-trace-governed)"
                  : "var(--ipm-trace-interpretive)",
              }}
              aria-hidden
            />
            {presentation.label}
            <Badge variant={presentation.governed ? "accent" : "outline"} className="ml-1">
              {presentation.governed ? "Governed" : "Interpretive"}
            </Badge>
          </span>
          {/* What this step IS, not what kind of step it is. "DERIVED_VARIABLE"
              told a reader nothing they could not see from its position; "Stage
              2 EAD share" tells them what the analysis did, and the label was
              stamped on the node all along. */}
          <p className="mt-1.5 text-sm font-medium leading-snug text-text-primary">
            {nodeTitle(node)}
          </p>
          {nodeSubtitle(node) && (
            <p className="mt-0.5 font-mono text-[11px] leading-relaxed text-text-secondary">
              {nodeSubtitle(node)}
            </p>
          )}
          <p className="mt-1 text-xs leading-relaxed text-text-muted">{presentation.blurb}</p>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="shrink-0 rounded p-1 text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
          title="Close"
        >
          <X className="size-3.5" aria-hidden />
        </button>
      </div>

      <div
        role="tablist"
        aria-label="What to look at on this step"
        className="flex flex-wrap gap-0.5 border-b border-border px-4 pb-2"
      >
        {tabs
          .filter((entry) => entry.enabled)
          .map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              aria-selected={shown === entry.id}
              onClick={() => setTab(entry.id)}
              className={cn(
                "rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
                shown === entry.id
                  ? "bg-surface-raised text-text-primary"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              {entry.label}
            </button>
          ))}
      </div>

      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-5 py-4">
        {shown === "summary" && isDemo && (
          <p className="rounded-md border border-warning/30 bg-warning-muted px-3 py-2 text-xs leading-relaxed text-warning">
            This is CreditProbe&rsquo;s demonstration data. It is not your bank&rsquo;s book.
            Onboard client data in Data Builder to replace it.
          </p>
        )}

        {shown === "summary" && stage && (
          <div className="space-y-3">
            <p className="text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
              {stageLabel || "Interpretation"}
            </p>
            {directAnswer && (
              <div>
                <Badge variant="accent">Calculated</Badge>
                <p className="mt-1.5 text-xs leading-relaxed text-text-primary">
                  {directAnswer}
                </p>
              </div>
            )}
            {points.length > 0 && (
              <div>
                <Badge variant="outline">CreditProbe&rsquo;s reading</Badge>
                <ul className="mt-1.5 space-y-1.5">
                  {points.map((point) => (
                    <li key={point} className="text-xs leading-relaxed text-text-secondary">
                      {point}
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {rule && (
              <p className="border-l-2 border-border pl-3 text-[11px] leading-relaxed text-text-muted">
                {rule}
              </p>
            )}
          </div>
        )}

        {shown === "summary" && (
        <dl className="divide-y divide-border">
          <Row label="Status" value={node.status} />
          {node.dataset && <Row label="Dataset" value={node.dataset} mono />}
          {node.function_id && (
            <Row label="Function" value={`${node.function_id} v${node.function_version}`} mono />
          )}
          {node.rows_in !== null && <Row label="Rows in" value={node.rows_in.toLocaleString()} />}
          {node.rows_out !== null && (
            <Row label="Rows out" value={node.rows_out.toLocaleString()} />
          )}
          {node.duration_ms !== null && <Row label="Duration" value={`${node.duration_ms}ms`} />}
          {node.content_hash && <Row label="Content hash" value={node.content_hash} mono />}
        </dl>
        )}

        {shown === "inputs" && (variables.length > 0 ? (
          <Section title={`Governed variables (${variables.length})`}>
            <ul className="space-y-2">
              {variables.map((variable) => (
                <li key={variable.field} className="text-xs leading-relaxed">
                  <span className="text-text-primary">
                    {variable.business_name || variable.field}
                  </span>
                  {variable.unit ? (
                    <span className="ml-1.5 text-text-muted">({variable.unit})</span>
                  ) : null}
                  <code className="ml-1.5 rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
                    {variable.field}
                  </code>
                  {variable.definition ? (
                    <p className="mt-0.5 text-text-muted">{variable.definition}</p>
                  ) : null}
                </li>
              ))}
            </ul>
          </Section>
        ) : node.fields_used.length > 0 ? (
          <Section title={`Governed variables (${node.fields_used.length})`}>
            <ul className="space-y-1.5">
              {node.fields_used.map((field) => (
                <li key={field} className="text-xs">
                  <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[10px] text-text-secondary">
                    {field}
                  </code>
                  {definitions?.[field] && (
                    <span className="ml-2 text-text-muted">{definitions[field]}</span>
                  )}
                </li>
              ))}
            </ul>
          </Section>
        ) : null)}

        {shown === "formula" && isMaths && (
          <MathematicalQueryBlock config={node.config ?? {}} />
        )}

        {shown === "validation" && isFingerprint && (
          <FingerprintBlock config={node.config ?? {}} />
        )}

        {shown === "formula" && Object.keys(config).length > 0 && (
          <Section title="What this step was configured to do">
            <dl className="divide-y divide-border">
              {Object.entries(config).map(([key, value]) => (
                <ConfigRow key={key} label={humanise(key)} value={value} />
              ))}
            </dl>
          </Section>
        )}

        {shown === "outputs" && node.output_summary &&
          Object.keys(node.output_summary).length > 0 && (
          <Section title="Recorded output">
            <dl className="divide-y divide-border">
              {Object.entries(node.output_summary)
                .slice(0, 12)
                .map(([key, value]) => (
                  <Row key={key} label={humanise(key)} value={String(value)} />
                ))}
            </dl>
          </Section>
        )}

        {shown === "outputs" && node.output_preview && node.output_preview.length > 0 && (
          <Section title="Output preview">
            <div className="overflow-x-auto rounded-md border border-border">
              <ResultTable rows={node.output_preview} maxRows={5} />
            </div>
          </Section>
        )}

        {shown === "impact" && (parents.length > 0 || children.length > 0) && (
          <Section title="What this step depends on, and what depends on it">
            <div className="space-y-2">
              {parents.length > 0 && (
                <Lineage
                  icon={ArrowUp}
                  title="Feeds into this step"
                  ids={parents}
                  labelOf={labelOf}
                  onSelect={onSelect}
                />
              )}
              {children.length > 0 && (
                <Lineage
                  icon={ArrowDown}
                  title="This step feeds"
                  ids={children}
                  labelOf={labelOf}
                  onSelect={onSelect}
                />
              )}
            </div>
          </Section>
        )}

        {(shown === "summary" || shown === "validation") && node.warnings.length > 0 && (
          <div className="rounded-md border border-warning/30 bg-warning-muted p-3">
            {node.warnings.map((warning) => (
              <p key={warning} className="text-xs text-warning">
                {warning}
              </p>
            ))}
          </div>
        )}

        {(shown === "summary" || shown === "validation") && node.error && (
          <div className="rounded-md border border-negative/30 bg-negative-muted p-3 text-xs text-negative">
            {node.error}
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.11em] text-text-muted">
        {title}
      </p>
      {children}
    </div>
  );
}

/**
 * The mathematical query.
 *
 * Everything a reviewer needs to check the arithmetic, in one place they can
 * open from the map: what the query does in English, the formula behind every
 * derived column, the analytical plan, and the SQL that actually ran with its
 * parameters shown separately. Sending somebody to another screen for the SQL
 * is how "fully auditable" stops being true in practice.
 */
function MathematicalQueryBlock({ config }: { config: Record<string, unknown> }) {
  const sql = String(config.sql ?? "");
  const parameters = (config.parameters ?? []) as unknown[];
  const operations = (config.operations ?? []) as {
    id: string;
    op: string;
    label?: string;
  }[];
  const formulas = (config.formulas ?? []) as {
    name: string;
    column: string;
    formula: string;
    means: string;
  }[];
  const plainEnglish = String(config.plain_english ?? "");
  const [copied, setCopied] = React.useState(false);

  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      // A clipboard the browser refuses is not worth an error state: the SQL
      // is on screen and selectable.
      setCopied(false);
    }
  }

  return (
    <>
      {plainEnglish && (
        <Section title="What this query does">
          <p className="text-xs leading-relaxed text-text-secondary">{plainEnglish}</p>
        </Section>
      )}

      {formulas.length > 0 && (
        <Section title={`Formulas (${formulas.length})`}>
          <ul className="space-y-2.5">
            {formulas.map((f) => (
              <li key={f.column}>
                <p className="text-xs font-medium text-text-primary">{f.name}</p>
                <p className="mt-0.5 font-mono text-[11px] leading-relaxed text-accent">
                  {f.formula}
                </p>
                <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
                  {f.means}
                </p>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {operations.length > 0 && (
        <Section title={`Analytical plan (${operations.length} steps)`}>
          <ol className="space-y-1">
            {operations.map((o, index) => (
              <li key={o.id} className="flex gap-2 text-[11px] leading-relaxed">
                <span className="tabular w-4 shrink-0 text-text-muted">{index + 1}</span>
                <span className="w-32 shrink-0 font-mono text-[10px] text-accent">
                  {o.op}
                </span>
                <span className="text-text-secondary">{o.label || o.id}</span>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {sql && (
        <section>
          <div className="mb-1.5 flex items-center gap-2">
            <h3 className="meta text-text-muted">SQL</h3>
            <button
              type="button"
              onClick={copy}
              className="ml-auto flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted transition-colors hover:border-accent hover:text-accent"
            >
              {copied ? (
                <Check className="size-2.5" aria-hidden />
              ) : (
                <Copy className="size-2.5" aria-hidden />
              )}
              {copied ? "Copied" : "Copy query"}
            </button>
          </div>
          <pre className="max-h-80 overflow-auto rounded-md border border-border bg-surface-sunken p-2.5 font-mono text-[10px] leading-relaxed text-text-secondary">
            <code>{highlightSql(sql)}</code>
          </pre>
          <p className="mt-1.5 text-[11px] leading-relaxed text-text-muted">
            {parameters.length} bound parameter
            {parameters.length === 1 ? "" : "s"}:{" "}
            <span className="font-mono text-text-secondary">
              {JSON.stringify(parameters)}
            </span>
            . Every value is a placeholder in the statement and a parameter beside
            it — nothing was concatenated into the SQL.
          </p>
        </section>
      )}
    </>
  );
}

/**
 * SQL, with its keywords picked out.
 *
 * A regex rather than a parser, and deliberately so: it highlights keywords,
 * strings and the CTE names that give a compiled query its structure, and it
 * cannot mangle the text because every branch re-emits exactly what it matched.
 */
const SQL_KEYWORDS =
  /\b(WITH|SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|JOIN|LEFT|RIGHT|INNER|OUTER|FULL|ON|AS|AND|OR|NOT|IN|IS|NULL|CASE|WHEN|THEN|ELSE|END|OVER|PARTITION BY|ROW_NUMBER|SUM|AVG|MIN|MAX|COUNT|CAST|COALESCE|NULLIF|DISTINCT|UNION|ALL|ASC|DESC|BETWEEN)\b/g;

function highlightSql(sql: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let key = 0;
  for (const line of sql.split("\n")) {
    const parts: React.ReactNode[] = [];
    let cursor = 0;
    // Strings first, so a keyword inside a literal is not painted.
    const tokens = [...line.matchAll(/'[^']*'|\?/g)];
    const pushKeywords = (text: string) => {
      let last = 0;
      for (const match of text.matchAll(SQL_KEYWORDS)) {
        if (match.index === undefined) continue;
        if (match.index > last) parts.push(text.slice(last, match.index));
        parts.push(
          <span key={`k${key++}`} className="font-semibold text-accent">
            {match[0]}
          </span>,
        );
        last = match.index + match[0].length;
      }
      if (last < text.length) parts.push(text.slice(last));
    };
    for (const token of tokens) {
      if (token.index === undefined) continue;
      pushKeywords(line.slice(cursor, token.index));
      parts.push(
        <span key={`s${key++}`} className="text-positive">
          {token[0]}
        </span>,
      );
      cursor = token.index + token[0].length;
    }
    pushKeywords(line.slice(cursor));
    out.push(
      <React.Fragment key={`l${key++}`}>
        {parts}
        {"\n"}
      </React.Fragment>,
    );
  }
  return out;
}

/**
 * What identifies this run.
 *
 * Four hashes rather than one, because a reviewer comparing two runs needs to
 * tell "someone changed the analysis" from "someone restated the data" from "a
 * steward re-declared a join" — and one hash collapses all three into "these
 * are different". The datasets and relationships behind the hashes are listed
 * underneath, because a hash nobody can explain is a hash nobody will trust.
 */
function FingerprintBlock({ config }: { config: Record<string, unknown> }) {
  const datasets = (config.datasets ?? []) as {
    dataset: string;
    version: string;
    origin: string;
    periods: string[];
  }[];
  const used = (config.relationships_used ?? []) as {
    relationship_id: number;
    version: number;
    cardinality: string;
  }[];

  const parts: { key: string; label: string; covers: string }[] = [
    { key: "plan", label: "Plan", covers: "the steps, their inputs and their parameters" },
    { key: "data", label: "Data", covers: "every dataset read, at the version it was read at" },
    {
      key: "relationships",
      label: "Relationships",
      covers: "every governed join walked, at the version that was active",
    },
    { key: "parameters", label: "Parameters", covers: "the periods and values bound into it" },
  ];

  return (
    <Section title="What identifies this run">
      <p className="mb-2 flex flex-wrap items-baseline gap-2 text-xs">
        <span className="text-text-muted">Run</span>
        <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-primary">
          {String(config.run ?? "")}
        </code>
      </p>
      <dl className="divide-y divide-border">
        {parts.map((part) => (
          <div key={part.key} className="py-1.5">
            <div className="flex items-baseline justify-between gap-3">
              <dt className="text-xs text-text-primary">{part.label}</dt>
              <dd>
                <code className="font-mono text-[10px] text-text-secondary">
                  {String(config[part.key] ?? "")}
                </code>
              </dd>
            </div>
            <p className="text-[11px] leading-snug text-text-muted">{part.covers}</p>
          </div>
        ))}
      </dl>

      {datasets.length > 0 && (
        <ul className="mt-2.5 space-y-1">
          {datasets.map((entry) => (
            <li key={entry.dataset} className="text-[11px] leading-relaxed text-text-secondary">
              <code className="font-mono text-[10px] text-text-primary">{entry.dataset}</code>
              <span className="ml-1.5 text-text-muted">
                v{entry.version}
                {entry.periods.length > 0 && ` · ${entry.periods.join(", ")}`}
              </span>
            </li>
          ))}
        </ul>
      )}

      {used.length > 0 && (
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          {used.length} governed {used.length === 1 ? "relationship" : "relationships"} walked, at{" "}
          {used.map((r) => `#${r.relationship_id} v${r.version}`).join(", ")}.
        </p>
      )}
    </Section>
  );
}

/**
 * One configuration entry.
 *
 * Configuration is structured data — a list of validation rules, a map of
 * parameters — and printing it as raw JSON would make the panel look like a
 * developer console rather than an inspection of the analysis. Each shape gets
 * the presentation that reads best.
 */
function ConfigRow({ label, value }: { label: string; value: unknown }) {
  if (Array.isArray(value)) {
    if (value.length === 0) return null;
    const objects = value.filter(
      (v): v is Record<string, unknown> => typeof v === "object" && v !== null,
    );
    if (objects.length === value.length) {
      return (
        <div className="py-2">
          <p className="text-xs text-text-muted">
            {label} <span className="tabular">({value.length})</span>
          </p>
          <ul className="mt-1 space-y-1">
            {objects.slice(0, 8).map((item, i) => (
              <li key={i} className="text-xs leading-relaxed text-text-secondary">
                <span className="text-text-primary">
                  {String(item.name ?? item.label ?? item.analysis_id ?? `Item ${i + 1}`)}
                </span>
                {item.description ? ` — ${String(item.description)}` : ""}
              </li>
            ))}
          </ul>
        </div>
      );
    }
    return <Row label={label} value={value.map(String).join(", ")} wrap />;
  }

  if (typeof value === "object" && value !== null) {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <Row label={label} value="none" />;
    return (
      <div className="py-2">
        <p className="text-xs text-text-muted">{label}</p>
        <dl className="mt-1 space-y-0.5">
          {entries.slice(0, 12).map(([k, v]) => (
            <div key={k} className="flex items-start justify-between gap-3">
              <dt className="text-[11px] text-text-muted">{humanise(k)}</dt>
              <dd className="text-right text-[11px] text-text-secondary">
                {typeof v === "object" && v !== null ? JSON.stringify(v) : String(v)}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    );
  }

  return <Row label={label} value={String(value)} wrap />;
}

function Row({
  label,
  value,
  mono,
  wrap,
}: {
  label: string;
  value: string;
  mono?: boolean;
  wrap?: boolean;
}) {
  return (
    <div className="grid grid-cols-[minmax(90px,40%)_1fr] items-start gap-3 py-1.5">
      <dt className="text-xs text-text-muted">{label}</dt>
      <dd
        className={cn(
          "text-right text-xs text-text-secondary",
          mono && "font-mono",
          wrap ? "break-words text-left" : "truncate",
        )}
        title={value}
      >
        {value}
      </dd>
    </div>
  );
}

function Lineage({
  icon: Icon,
  title,
  ids,
  labelOf,
  onSelect,
}: {
  icon: typeof ArrowUp;
  title: string;
  ids: string[];
  labelOf: (id: string) => string;
  onSelect: (id: string) => void;
}) {
  return (
    <div>
      <p className="mb-1 flex items-center gap-1 text-[11px] text-text-muted">
        <Icon className="size-3" aria-hidden />
        {title}
      </p>
      <div className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => onSelect(id)}
            className="max-w-full truncate rounded border border-border bg-surface-sunken px-1.5 py-0.5 text-[11px] text-text-secondary transition-colors hover:border-accent hover:text-accent"
          >
            {labelOf(id)}
          </button>
        ))}
      </div>
    </div>
  );
}
