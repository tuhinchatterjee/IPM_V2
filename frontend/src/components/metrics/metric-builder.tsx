"use client";

import * as React from "react";
import { Loader2, Plus, Trash2 } from "lucide-react";

import { coerce, formatMetric } from "@/components/metrics/present";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, type MetricPanel } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Building a metric, without writing anything that later becomes SQL.
 *
 * Every choice on this form comes from `/metrics/vocabulary`: the datasets the
 * governed library already reads, the fields those datasets actually hold, and
 * the aggregations and comparisons the formula language defines. A definition
 * naming a column that does not exist cannot be assembled here — and the
 * server refuses it again on submission, because a picker is a convenience and
 * never a control.
 *
 * The preview runs the formula without storing it, so somebody sees the number
 * and the working before committing to a definition, and sees the refusal with
 * its reason before they have named something that cannot calculate.
 *
 * What is saved arrives as a DRAFT. It reaches "Calculates" only by
 * calculating, and "User verified" only when somebody's own number agreed and
 * they accepted it. Nothing on this form can confer either.
 */

interface Clause {
  field: string;
  op: string;
  value: string;
}

interface TermDraft {
  id: string;
  label: string;
  aggregate: string;
  field: string;
  where: Clause[];
}

const RATIO_KINDS = new Set(["ratio", "percentage", "rate"]);

function emptyTerm(id: string): TermDraft {
  return { id, label: "", aggregate: "sum", field: "", where: [] };
}

export function MetricBuilder({
  onSaved,
  onCancel,
}: {
  onSaved?: (metric: MetricPanel) => void;
  onCancel?: () => void;
}) {
  const vocabulary = useAsync(() => api.metricVocabulary(), []);

  const [name, setName] = React.useState("");
  const [definition, setDefinition] = React.useState("");
  const [dataset, setDataset] = React.useState("");
  const [kind, setKind] = React.useState("percentage");
  const [unit, setUnit] = React.useState("percent");
  const [domain, setDomain] = React.useState("");
  const [scale, setScale] = React.useState("100");
  const [period, setPeriod] = React.useState("");
  const [top, setTop] = React.useState<TermDraft[]>([emptyTerm("top")]);
  const [bottom, setBottom] = React.useState<TermDraft[]>([emptyTerm("bottom")]);

  const [busy, setBusy] = React.useState<"" | "preview" | "save">("");
  const [error, setError] = React.useState<string | null>(null);
  const [preview, setPreview] = React.useState<{
    available: boolean;
    value: number | null;
    unavailable: string;
    period: string;
    formula: string;
  } | null>(null);

  const needsDenominator = RATIO_KINDS.has(kind);
  const fields =
    vocabulary.data?.datasets.find((d) => d.name === dataset)?.fields ?? [];

  function formula(): Record<string, unknown> {
    const side = (terms: TermDraft[]) => ({
      terms: terms
        .filter((t) => t.aggregate === "count" || t.field)
        .map((t) => ({
          id: t.id,
          label: t.label || t.field || t.aggregate,
          dataset,
          aggregate: t.aggregate,
          field: t.field,
          where: t.where
            .filter((c) => c.field && c.op)
            .map((c) => ({ field: c.field, op: c.op, value: coerce(c.value) })),
        })),
    });
    const built: Record<string, unknown> = {
      kind,
      numerator: side(top),
      scale: Number(scale) || 1,
    };
    if (needsDenominator) built.denominator = side(bottom);
    return built;
  }

  async function runPreview() {
    setBusy("preview");
    setError(null);
    try {
      setPreview(
        await api.previewMetric({ name, formula: formula(), unit }, period.trim()),
      );
    } catch (e) {
      setPreview(null);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  async function save() {
    setBusy("save");
    setError(null);
    try {
      const saved = await api.createMetric({
        name,
        definition,
        formula: formula(),
        unit,
        domain,
      });
      onSaved?.(saved);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy("");
    }
  }

  if (vocabulary.loading && !vocabulary.data) {
    return <Card className="p-4 text-sm text-text-muted">Loading…</Card>;
  }
  if (!vocabulary.data) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">
        {vocabulary.error ?? "The metric vocabulary could not be read."}
      </Card>
    );
  }
  const vocab = vocabulary.data;
  const ready = Boolean(name.trim() && dataset);

  return (
    <Card className="space-y-5 p-5">
      <div>
        <h2 className="text-base font-semibold tracking-tight text-text-primary">
          Build a metric
        </h2>
        <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-muted">
          Every field here comes from the governed catalogue, so a metric
          naming something that does not exist cannot be assembled. What you
          save arrives as a draft and stays one until it has been checked
          against a number you already trusted.
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name">
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Stretched Arrears Share"
            className={INPUT}
          />
        </Field>
        <Field label="Domain">
          <select
            value={domain}
            onChange={(e) => setDomain(e.target.value)}
            className={INPUT}
          >
            <option value="">—</option>
            {vocab.domains.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field label="What it measures">
        <input
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
          placeholder="Balance 30+ DPD as a share of the retail book."
          className={INPUT}
        />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Field label="Dataset">
          <select
            value={dataset}
            onChange={(e) => {
              setDataset(e.target.value);
              setTop([emptyTerm("top")]);
              setBottom([emptyTerm("bottom")]);
              setPreview(null);
            }}
            className={INPUT}
          >
            <option value="">Choose…</option>
            {vocab.datasets.map((d) => (
              <option key={d.name} value={d.name}>
                {d.business_name || d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Kind">
          <select
            value={kind}
            onChange={(e) => setKind(e.target.value)}
            className={INPUT}
          >
            {vocab.kinds
              .filter((k) => k !== "function")
              .map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
          </select>
        </Field>
        <Field label="Unit">
          <select
            value={unit}
            onChange={(e) => setUnit(e.target.value)}
            className={INPUT}
          >
            {vocab.units.map((u) => (
              <option key={u} value={u}>
                {u}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Scale">
          <input
            value={scale}
            onChange={(e) => setScale(e.target.value)}
            inputMode="numeric"
            className={INPUT}
          />
        </Field>
      </div>

      {dataset && (
        <>
          <Side
            title={needsDenominator ? "Numerator" : "What it measures"}
            terms={top}
            onChange={setTop}
            fields={fields}
            vocab={vocab}
          />
          {needsDenominator && (
            <Side
              title="Denominator"
              subtitle="What the numerator is a share of. A ratio with an empty bottom is not a ratio."
              terms={bottom}
              onChange={setBottom}
              fields={fields}
              vocab={vocab}
            />
          )}
        </>
      )}

      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-4">
        <Field label="Period">
          <input
            value={period}
            onChange={(e) => setPeriod(e.target.value)}
            placeholder="Latest"
            className={`${INPUT} w-36`}
          />
        </Field>
        <Button
          variant="ghost"
          size="sm"
          onClick={runPreview}
          disabled={!ready || busy !== ""}
        >
          {busy === "preview" && <Loader2 className="animate-spin" aria-hidden />}
          Preview
        </Button>
        <Button size="sm" onClick={save} disabled={!ready || busy !== ""}>
          {busy === "save" && <Loader2 className="animate-spin" aria-hidden />}
          Save as a draft
        </Button>
        {onCancel && (
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        )}
        <Badge variant="warning">Draft until verified</Badge>
      </div>

      {error && (
        <p className="whitespace-pre-line text-xs text-negative">{error}</p>
      )}

      {preview && (
        <div className="rounded-md border border-border p-4">
          {preview.available ? (
            <p className="text-[22px] font-semibold leading-none tabular text-text-primary">
              {formatMetric(preview.value, unit, 2)}
            </p>
          ) : (
            <>
              <p className="text-[22px] font-semibold leading-none text-text-muted">
                —
              </p>
              <p className="mt-1.5 text-xs leading-relaxed text-text-muted">
                {preview.unavailable}
              </p>
            </>
          )}
          <p className="mt-1.5 font-mono text-[11px] text-text-muted">
            {preview.formula}
          </p>
          {preview.period && (
            // Which period the figure is for. Left off, a share of the book
            // reads as "now" whichever period it actually came from.
            <p className="mt-0.5 text-xs text-text-muted">{preview.period}</p>
          )}
        </div>
      )}
    </Card>
  );
}

const INPUT =
  "h-8 w-full rounded-md border border-border bg-surface px-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none";

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
        {label}
      </span>
      <span className="mt-1 block">{children}</span>
    </label>
  );
}

function Side({
  title,
  subtitle,
  terms,
  onChange,
  fields,
  vocab,
}: {
  title: string;
  subtitle?: string;
  terms: TermDraft[];
  onChange: (terms: TermDraft[]) => void;
  fields: { name: string; business_name: string }[];
  vocab: { aggregations: Record<string, string>; comparisons: Record<string, string> };
}) {
  function update(index: number, patch: Partial<TermDraft>) {
    onChange(terms.map((t, i) => (i === index ? { ...t, ...patch } : t)));
  }

  return (
    <section className="rounded-md border border-border p-3">
      <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
        {title}
      </p>
      {subtitle && (
        <p className="mt-0.5 text-[11px] leading-relaxed text-text-muted">
          {subtitle}
        </p>
      )}

      <div className="mt-2 space-y-3">
        {terms.map((term, index) => (
          <div key={term.id} className="space-y-2">
            <div className="grid gap-2 sm:grid-cols-3">
              <select
                value={term.aggregate}
                onChange={(e) => update(index, { aggregate: e.target.value })}
                className={INPUT}
                aria-label="Aggregation"
              >
                {Object.entries(vocab.aggregations).map(([key, label]) => (
                  <option key={key} value={key}>
                    {label}
                  </option>
                ))}
              </select>
              <select
                value={term.field}
                onChange={(e) => update(index, { field: e.target.value })}
                className={INPUT}
                aria-label="Field"
              >
                <option value="">
                  {term.aggregate === "count" ? "(every row)" : "Choose a field…"}
                </option>
                {fields.map((f) => (
                  <option key={f.name} value={f.name}>
                    {f.business_name || f.name}
                  </option>
                ))}
              </select>
              <input
                value={term.label}
                onChange={(e) => update(index, { label: e.target.value })}
                placeholder="What to call this part"
                className={INPUT}
                aria-label="Label"
              />
            </div>

            {term.where.map((clause, position) => (
              <div key={position} className="grid gap-2 sm:grid-cols-4">
                <select
                  value={clause.field}
                  onChange={(e) =>
                    update(index, {
                      where: term.where.map((c, i) =>
                        i === position ? { ...c, field: e.target.value } : c,
                      ),
                    })
                  }
                  className={INPUT}
                  aria-label="Filter field"
                >
                  <option value="">Only where…</option>
                  {fields.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.business_name || f.name}
                    </option>
                  ))}
                </select>
                <select
                  value={clause.op}
                  onChange={(e) =>
                    update(index, {
                      where: term.where.map((c, i) =>
                        i === position ? { ...c, op: e.target.value } : c,
                      ),
                    })
                  }
                  className={INPUT}
                  aria-label="Comparison"
                >
                  {Object.entries(vocab.comparisons).map(([key, label]) => (
                    <option key={key} value={key}>
                      {label}
                    </option>
                  ))}
                </select>
                <input
                  value={clause.value}
                  onChange={(e) =>
                    update(index, {
                      where: term.where.map((c, i) =>
                        i === position ? { ...c, value: e.target.value } : c,
                      ),
                    })
                  }
                  placeholder="value"
                  className={INPUT}
                  aria-label="Value"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() =>
                    update(index, {
                      where: term.where.filter((_, i) => i !== position),
                    })
                  }
                >
                  <Trash2 aria-hidden />
                  Remove
                </Button>
              </div>
            ))}

            <Button
              variant="ghost"
              size="sm"
              onClick={() =>
                update(index, {
                  where: [...term.where, { field: "", op: "=", value: "" }],
                })
              }
            >
              <Plus aria-hidden />
              Only where
            </Button>
          </div>
        ))}
      </div>
    </section>
  );
}
