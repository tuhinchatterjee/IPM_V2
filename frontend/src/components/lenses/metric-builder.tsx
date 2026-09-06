"use client";

import * as React from "react";
import {
  ArrowLeft,
  Check,
  Loader2,
  Lock,
  Pencil,
  Plus,
  Sparkles,
  TriangleAlert,
} from "lucide-react";

import { MetricLibrary } from "@/components/lenses/metric-library";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type FormulaTerm,
  type MetricExplained,
  type MetricPreview,
  type MetricProposal,
} from "@/lib/api";

/**
 * Adding one metric to a lens, whichever way somebody wants to.
 *
 * §4 and §16. One component, used from the creation flow and from an existing
 * lens's edit mode, because "add a metric" is one act and two implementations
 * of it would drift — the version reached from an existing lens is exactly the
 * version reached while building a new one, including the preview and the lock.
 *
 * The flow, and why it is in this order:
 *
 *   choose  — an existing governed metric, or a new one described in words.
 *   define  — for a new one: the name, the algebra, the plain-English steps
 *             and the real SQL, all four regenerated on every edit so none can
 *             go stale (§6, §7).
 *   preview — run it against the real book and show every step (§8).
 *   lock    — only after the preview. A metric nobody has seen a number for is
 *             a metric nobody has checked (§9).
 *   then    — add another, or go back to the lens (§10).
 *
 * Nothing is stored before the lock. Everything up to it is a definition being
 * worked on, and the routes it calls take the definition in the body — which
 * is what lets the three readings stay reconciled while somebody is still
 * typing.
 */

export type BuilderStage = "choose" | "define" | "preview" | "locked";

export interface BuiltMetric {
  metric_id: string;
  name: string;
}

export function MetricBuilder({
  onLocked,
  onDone,
  chosen = [],
  domain = "",
  portfolio = "",
  lensName = "",
}: {
  /** Called when a metric is locked and ready to go on the lens. */
  onLocked: (metric: BuiltMetric) => void;
  /** "Go back to the lens" — §10. */
  onDone: () => void;
  chosen?: string[];
  domain?: string;
  portfolio?: string;
  lensName?: string;
}) {
  const [stage, setStage] = React.useState<BuilderStage>("choose");
  const [mode, setMode] = React.useState<"existing" | "new">("existing");

  const [said, setSaid] = React.useState("");
  const [proposal, setProposal] = React.useState<MetricProposal | null>(null);
  const [draft, setDraft] = React.useState<Draft | null>(null);
  const [explained, setExplained] = React.useState<MetricExplained | null>(null);
  const [preview, setPreview] = React.useState<MetricPreview | null>(null);
  const [locked, setLocked] = React.useState<BuiltMetric | null>(null);

  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  function reset() {
    setStage("choose");
    setMode("existing");
    setSaid("");
    setProposal(null);
    setDraft(null);
    setExplained(null);
    setPreview(null);
    setLocked(null);
    setError("");
  }

  async function describe() {
    if (!said.trim() || busy) return;
    setBusy(true);
    setError("");
    try {
      const body = await api.proposeMetric(said.trim(), domain);
      setProposal(body);
      setDraft({
        name: body.name,
        definition: "",
        unit: "number",
        decimals: 2,
        domain: body.domain || domain,
        portfolio,
        formula: body.formula as unknown as Record<string, unknown>,
      });
      setStage("define");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function runPreview(using: Draft) {
    setBusy(true);
    setError("");
    try {
      const body = await api.previewDraft({ ...using });
      setPreview(body);
      setStage("preview");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  async function lock() {
    if (!draft || busy) return;
    setBusy(true);
    setError("");
    try {
      // Stored only now, and stored as a metric like any other so it is
      // searchable, reusable and governed from the moment it exists.
      //
      // Shared, because putting a metric on a lens IS publishing it. A
      // private metric on a shared lens is a tile nobody else can resolve,
      // and the refusal they would get — "not a metric in the catalogue" —
      // describes the permission as an absence. The screen says so below
      // rather than deciding it silently.
      const stored = await api.createMetric({
        name: draft.name,
        definition: draft.definition,
        formula: draft.formula,
        unit: draft.unit,
        domain: draft.domain,
        portfolio: draft.portfolio,
        shared: true,
      });
      const made = { metric_id: stored.metric_id, name: stored.name };
      setLocked(made);
      setStage("locked");
      onLocked(made);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5" data-testid="metric-builder">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-sm font-semibold tracking-tight text-text-primary">
          {stage === "locked" ? "Metric locked" : "Add a metric"}
          {lensName && stage !== "locked" && (
            <span className="ml-1.5 font-normal text-text-muted">
              to {lensName}
            </span>
          )}
        </h2>
        <Button variant="ghost" size="sm" onClick={onDone}>
          <ArrowLeft aria-hidden />
          {lensName ? `Back to ${lensName}` : "Back to the lens"}
        </Button>
      </div>

      {/* ---------------------------------------------------------- choose */}

      {stage === "choose" && (
        <div className="mt-4 space-y-4">
          <div
            className="flex flex-wrap gap-2"
            role="radiogroup"
            aria-label="How to add this metric"
          >
            <Choice
              on={mode === "existing"}
              onClick={() => setMode("existing")}
              title="Use an existing metric"
              detail="Governed, already defined, already checked."
            />
            <Choice
              on={mode === "new"}
              onClick={() => setMode("new")}
              title="Define a new metric"
              detail="Describe it in words; CreditProbe drafts the definition."
            />
          </div>

          {mode === "existing" ? (
            <MetricLibrary
              chosen={chosen}
              domain={domain}
              portfolio={portfolio}
              onPick={(metricId, name) => {
                const picked = { metric_id: metricId, name };
                setLocked(picked);
                setStage("locked");
                onLocked(picked);
              }}
            />
          ) : (
            <div>
              <label
                htmlFor="describe-metric"
                className="text-[11px] font-medium text-text-secondary"
              >
                What should this metric measure?
              </label>
              <div className="mt-1 flex flex-wrap gap-2">
                <input
                  id="describe-metric"
                  value={said}
                  onChange={(e) => setSaid(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") void describe();
                  }}
                  placeholder="the share of exposure to borrowers on the watchlist"
                  aria-label="What this metric should measure"
                  className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
                />
                <Button size="sm" onClick={describe} disabled={busy || !said.trim()}>
                  {busy ? (
                    <Loader2 className="animate-spin" aria-hidden />
                  ) : (
                    <Sparkles aria-hidden />
                  )}
                  Draft it
                </Button>
              </div>
              <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
                Every field, aggregation and filter CreditProbe drafts is
                matched against the governed catalogue first. It will tell you
                what it assumed and what it could not work out, rather than
                filling the gap with something plausible.
              </p>
            </div>
          )}
        </div>
      )}

      {/* ---------------------------------------------------------- define */}

      {stage === "define" && draft && (
        <DefineMetric
          draft={draft}
          proposal={proposal}
          explained={explained}
          onExplained={setExplained}
          onChange={setDraft}
          busy={busy}
          onPreview={() => void runPreview(draft)}
          onBack={reset}
        />
      )}

      {/* --------------------------------------------------------- preview */}

      {stage === "preview" && preview && draft && (
        <div className="mt-4 space-y-4">
          <PreviewPanel preview={preview} />
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
            <Button
              onClick={lock}
              disabled={busy || preview.value === null}
              data-testid="lock-metric"
            >
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Lock aria-hidden />}
              Lock metric
            </Button>
            <Button variant="ghost" onClick={() => setStage("define")}>
              <Pencil aria-hidden />
              Edit again
            </Button>
            <p className="text-[11px] text-text-muted">
              Locking stores it in the metric library, shared, so anyone who
              can open this lens can read the tile and anyone building another
              lens can reuse the definition.
            </p>
            {preview.value === null && (
              <p className="text-[11px] text-warning">
                This produced no figure, so there is nothing to lock. Change the
                definition or try another period.
              </p>
            )}
          </div>
        </div>
      )}

      {/* ---------------------------------------------------------- locked */}

      {stage === "locked" && locked && (
        <div className="mt-4 space-y-3" data-testid="metric-locked">
          <p className="flex items-center gap-1.5 text-sm text-positive">
            <Check className="size-4" aria-hidden />
            {locked.name} is on the lens.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button variant="outline" onClick={reset} data-testid="add-another-metric">
              <Plus aria-hidden />
              Add another metric
            </Button>
            <Button onClick={onDone} data-testid="back-to-lens">
              <ArrowLeft aria-hidden />
              {lensName ? `Go back to ${lensName}` : "Go back to the lens"}
            </Button>
          </div>
        </div>
      )}

      {error && (
        <p className="mt-3 flex items-start gap-1.5 text-xs text-negative">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </Card>
  );
}

function Choice({
  on,
  onClick,
  title,
  detail,
}: {
  on: boolean;
  onClick: () => void;
  title: string;
  detail: string;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={on}
      onClick={onClick}
      className={`flex-1 rounded-md border px-3 py-2.5 text-left transition-colors ${
        on
          ? "border-accent bg-accent/10"
          : "border-border hover:bg-surface-hover"
      }`}
    >
      <span className="block text-xs font-medium text-text-primary">{title}</span>
      <span className="mt-0.5 block text-[11px] leading-relaxed text-text-muted">
        {detail}
      </span>
    </button>
  );
}

export interface Draft {
  name: string;
  definition: string;
  unit: string;
  decimals: number;
  domain: string;
  portfolio: string;
  formula: Record<string, unknown>;
}

/**
 * The definition, read four ways at once (§6), and editable (§7).
 *
 * The four move together because none of them is stored: every keystroke that
 * changes the definition re-asks the server, and the server derives the
 * algebra, the English and the SQL from the one tree. There is no stored prose
 * to be right when it was written and wrong afterwards.
 *
 * The parameters are printed under the SQL deliberately. A threshold is a
 * BOUND parameter, so moving it from 0 to 5 changes what is bound and not the
 * query text — a screen showing the SQL alone would look frozen to somebody
 * who had just edited the number they came to edit.
 */
function DefineMetric({
  draft,
  proposal,
  explained,
  onExplained,
  onChange,
  busy,
  onPreview,
  onBack,
}: {
  draft: Draft;
  proposal: MetricProposal | null;
  explained: MetricExplained | null;
  onExplained: (body: MetricExplained | null) => void;
  onChange: (draft: Draft) => void;
  busy: boolean;
  onPreview: () => void;
  onBack: () => void;
}) {
  const [error, setError] = React.useState("");
  const signature = JSON.stringify({
    formula: draft.formula,
    unit: draft.unit,
    name: draft.name,
  });

  React.useEffect(() => {
    let live = true;
    const timer = setTimeout(async () => {
      try {
        const body = await api.explainDraft({ ...draft });
        if (live) {
          onExplained(body);
          setError("");
        }
      } catch (e) {
        if (live) {
          onExplained(null);
          setError(e instanceof Error ? e.message : String(e));
        }
      }
    }, 220);
    return () => {
      live = false;
      clearTimeout(timer);
    };
    // `signature` rather than `draft`: a new object identity on every render
    // would re-ask the server for a definition that has not changed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const terms = readTerms(draft.formula);

  return (
    <div className="mt-4 space-y-4" data-testid="metric-definition">
      {proposal && (proposal.assumptions.length > 0 ||
        proposal.unresolved.length > 0) && (
        <div className="rounded-md border border-border bg-surface-muted/40 p-3">
          <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
            What CreditProbe assumed
          </p>
          <ul className="mt-1 space-y-0.5">
            {proposal.assumptions.map((a) => (
              <li key={a} className="text-[11px] leading-relaxed text-text-secondary">
                {a}
              </li>
            ))}
            {proposal.unresolved.map((u) => (
              <li key={u} className="text-[11px] leading-relaxed text-warning">
                Still to decide: {u}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="text-[11px] font-medium text-text-secondary">Name</span>
          <input
            value={draft.name}
            aria-label="Metric name"
            onChange={(e) => onChange({ ...draft, name: e.target.value })}
            className="mt-1 h-8 w-full rounded-md border border-border bg-surface px-2.5 text-xs text-text-primary focus:border-accent focus:outline-none"
          />
        </label>
        <label className="block">
          <span className="text-[11px] font-medium text-text-secondary">Unit</span>
          <select
            value={draft.unit}
            aria-label="Metric unit"
            onChange={(e) => onChange({ ...draft, unit: e.target.value })}
            className="mt-1 h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text-primary focus:border-accent focus:outline-none"
          >
            {["number", "percent", "currency", "ratio", "count", "score",
              "days", "index"].map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </label>
      </div>

      <label className="block">
        <span className="text-[11px] font-medium text-text-secondary">
          Business definition
        </span>
        <textarea
          value={draft.definition}
          rows={2}
          aria-label="Business definition"
          placeholder="What this measures, in the words somebody reading it would use."
          onChange={(e) => onChange({ ...draft, definition: e.target.value })}
          className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs leading-relaxed text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
      </label>

      <TermEditor
        terms={terms}
        formula={draft.formula}
        onChange={(formula) => onChange({ ...draft, formula })}
      />

      <Representations explained={explained} error={error} />

      <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
        <Button onClick={onPreview} disabled={busy} data-testid="preview-metric">
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : null}
          Preview on real data
        </Button>
        <Button variant="ghost" onClick={onBack}>
          Start over
        </Button>
      </div>
    </div>
  );
}

/** §6: the algebra, the execution logic and the query, side by side. */
function Representations({
  explained,
  error,
}: {
  explained: MetricExplained | null;
  error: string;
}) {
  if (error)
    return (
      <p className="text-xs text-negative" data-testid="definition-error">
        {error}
      </p>
    );
  if (!explained)
    return (
      <p className="flex items-center gap-1.5 text-[11px] text-text-muted">
        <Loader2 className="size-3 animate-spin" aria-hidden />
        Working out what that means
      </p>
    );

  return (
    <div className="space-y-3 rounded-md border border-border p-3">
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
          Formula
        </p>
        <p
          className="mt-0.5 break-words font-mono text-[11px] text-text-primary"
          data-testid="formula-line"
        >
          {explained.formula_detail || explained.formula}
        </p>
      </div>
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
          How it is executed
        </p>
        <ol
          className="mt-0.5 list-inside list-decimal space-y-0.5"
          data-testid="plain-english"
        >
          {explained.plain_english.map((step, index) => (
            <li key={index} className="text-[11px] leading-relaxed text-text-secondary">
              {step}
            </li>
          ))}
        </ol>
      </div>
      <div>
        <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
          Query
        </p>
        {explained.sql ? (
          <>
            <pre
              className="mt-0.5 max-h-52 overflow-auto rounded bg-surface-muted p-2 font-mono text-[10px] leading-relaxed text-text-secondary"
              data-testid="sql-line"
            >
              {explained.sql}
            </pre>
            {explained.sql_params.length > 0 && (
              <p className="mt-1 text-[10px] text-text-muted" data-testid="sql-params">
                Bound values: {explained.sql_params.join(", ")}. Values are
                bound to the query rather than written into it, which is why a
                filter value can never become SQL.
              </p>
            )}
          </>
        ) : (
          <p className="mt-0.5 text-[11px] text-warning">
            {explained.sql_unavailable ||
              "This definition does not compile yet."}
          </p>
        )}
      </div>
    </div>
  );
}

function readTerms(formula: Record<string, unknown>): {
  side: "numerator" | "denominator";
  index: number;
  term: FormulaTerm;
}[] {
  const out: {
    side: "numerator" | "denominator";
    index: number;
    term: FormulaTerm;
  }[] = [];
  for (const side of ["numerator", "denominator"] as const) {
    const block = formula[side] as { terms?: FormulaTerm[] } | null | undefined;
    (block?.terms ?? []).forEach((term, index) =>
      out.push({ side, index, term }),
    );
  }
  return out;
}

/**
 * Editing the terms themselves.
 *
 * Deliberately narrow: a filter's value and a term's aggregation are the two
 * things somebody actually changes after CreditProbe drafts a definition, and
 * both are safe to change because both are validated server-side against the
 * catalogue before anything runs. Adding a field picker here would be a second
 * metric builder; the full one already exists and this is the quick path.
 */
function TermEditor({
  terms,
  formula,
  onChange,
}: {
  terms: ReturnType<typeof readTerms>;
  formula: Record<string, unknown>;
  onChange: (formula: Record<string, unknown>) => void;
}) {
  function edit(
    side: "numerator" | "denominator",
    index: number,
    change: Partial<FormulaTerm>,
  ) {
    const next = JSON.parse(JSON.stringify(formula)) as Record<string, unknown>;
    const block = next[side] as { terms: FormulaTerm[] };
    block.terms[index] = { ...block.terms[index], ...change };
    onChange(next);
  }

  if (terms.length === 0) return null;

  return (
    <div className="space-y-2">
      <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
        Terms
      </p>
      {terms.map(({ side, index, term }) => (
        <div
          key={`${side}-${index}`}
          className="rounded-md border border-border p-2.5"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline">
              {side === "numerator" ? "Numerator" : "Denominator"}
            </Badge>
            <span className="font-mono text-[11px] text-text-secondary">
              {term.describes}
            </span>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-2">
            <label className="text-[10px] text-text-muted">
              Aggregation
              <select
                value={term.aggregate}
                aria-label={`Aggregation for ${side} term ${index + 1}`}
                onChange={(e) =>
                  edit(side, index, { aggregate: e.target.value })
                }
                className="ml-1.5 h-7 rounded-md border border-border bg-surface px-1.5 text-xs text-text-primary focus:border-accent focus:outline-none"
              >
                {["sum", "count", "count_distinct", "avg", "min", "max",
                  "median"].map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </label>
            {(term.where ?? []).map((condition, position) => (
              <label
                key={`${condition.field}-${position}`}
                className="text-[10px] text-text-muted"
              >
                {condition.field} {condition.op}
                <input
                  value={String(condition.value ?? "")}
                  aria-label={`Value for ${condition.field}`}
                  onChange={(e) => {
                    const raw = e.target.value;
                    const parsed =
                      raw !== "" && !Number.isNaN(Number(raw))
                        ? Number(raw)
                        : raw;
                    const where = (term.where ?? []).map((c, i) =>
                      i === position ? { ...c, value: parsed } : c,
                    );
                    edit(side, index, { where });
                  }}
                  className="ml-1.5 h-7 w-24 rounded-md border border-border bg-surface px-1.5 text-xs text-text-primary focus:border-accent focus:outline-none"
                />
              </label>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

/** §8: what it produces on the real book, step by step. */
export function PreviewPanel({ preview }: { preview: MetricPreview }) {
  return (
    <div className="space-y-3" data-testid="metric-preview">
      <div className="flex flex-wrap items-center gap-1.5">
        <Badge variant="outline">{preview.domain || "Ungrouped"}</Badge>
        <Badge variant="outline">{preview.dataset}</Badge>
        {preview.period && <Badge variant="accent">{preview.period}</Badge>}
        <span className="text-[11px] text-text-muted">
          {preview.periods.length} period
          {preview.periods.length === 1 ? "" : "s"} available
        </span>
      </div>
      {preview.grain && (
        <p className="text-[11px] text-text-muted">{preview.grain}</p>
      )}

      {preview.unavailable ? (
        <p className="flex items-start gap-1.5 text-xs text-warning">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {preview.unavailable}
        </p>
      ) : (
        <>
          <Step label="Fields read">
            {preview.fields.length > 0
              ? preview.fields
                  .map((f) => `${f.business_name} (${f.name})`)
                  .join(", ")
              : "None — this counts rows rather than reading a field."}
          </Step>
          {preview.scope.length > 0 && (
            <Step label="Applied to every term">{preview.scope.join("; ")}</Step>
          )}
          <Terms label="Numerator" terms={preview.numerator}
                 total={preview.numerator_value} />
          {preview.denominator.length > 0 && (
            <Terms label="Denominator" terms={preview.denominator}
                   total={preview.denominator_value} />
          )}
          <Step label="Aggregation">{preview.aggregations.join(", ")}</Step>
          <div className="rounded-md border border-accent/40 bg-accent/5 p-3">
            <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
              Final calculation
            </p>
            <p className="mt-0.5 font-mono text-[11px] text-text-primary">
              {preview.final}
            </p>
            <p
              className="mt-1 text-[22px] font-semibold leading-none tabular tracking-tight text-text-primary"
              data-testid="preview-value"
            >
              {preview.formatted}
            </p>
            <p className="mt-1 text-[11px] text-text-muted">
              over {preview.rows_considered.toLocaleString()} rows
            </p>
          </div>
        </>
      )}
    </div>
  );
}

function Step({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
        {label}
      </p>
      <p className="mt-0.5 text-[11px] leading-relaxed text-text-secondary">
        {children}
      </p>
    </div>
  );
}

function Terms({
  label,
  terms,
  total,
}: {
  label: string;
  terms: MetricPreview["numerator"];
  total: number | null;
}) {
  return (
    <div>
      <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-text-muted">
        {label}
      </p>
      <ul className="mt-0.5 space-y-1">
        {terms.map((term) => (
          <li
            key={term.id}
            className="flex flex-wrap items-baseline justify-between gap-2 rounded border border-border px-2 py-1"
          >
            <span className="min-w-0">
              <span className="text-[11px] text-text-primary">{term.label}</span>
              <span className="ml-1.5 font-mono text-[10px] text-text-muted">
                {term.describes}
              </span>
            </span>
            <span className="font-mono text-[11px] tabular text-text-primary">
              {term.value === null ? "—" : term.value.toLocaleString()}
            </span>
          </li>
        ))}
      </ul>
      {terms.length > 1 && total !== null && (
        <p className="mt-0.5 text-right font-mono text-[11px] text-text-secondary">
          = {total.toLocaleString()}
        </p>
      )}
    </div>
  );
}
