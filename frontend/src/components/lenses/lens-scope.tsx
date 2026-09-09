"use client";

import * as React from "react";
import { CalendarRange, Loader2, Pencil } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type LensPeriods,
  type LensScope,
  type LensVocabulary,
} from "@/lib/api";

/**
 * What a lens is for, and which period it is showing.
 *
 * Two things live here because a reader asks them together. "What am I
 * looking at" and "as at when" are the first two questions anybody has about
 * a dashboard, and answering the first in a header while burying the second
 * in a menu is how people read last quarter's numbers as this quarter's.
 *
 * The period picker offers what the lens's own datasets hold rows for, from
 * `GET /lenses/{id}/periods`. Not every period in the lake: a picker offering
 * a quarter the staging dataset has never seen draws a screen of dashes and
 * teaches the reader that the picker is broken.
 */
export function LensScopeBar({
  lensId,
  scope,
  showing,
  onPeriod,
  onSaved,
}: {
  lensId: number;
  scope: LensScope;
  /** The period the render actually used, which may be each metric's own. */
  showing: string | null;
  onPeriod: (period: string) => void;
  onSaved: (scope: LensScope) => void;
}) {
  const [periods, setPeriods] = React.useState<LensPeriods | null>(null);
  const [editing, setEditing] = React.useState(false);

  React.useEffect(() => {
    let live = true;
    void api
      .lensPeriods(lensId)
      .then((body) => {
        if (live) setPeriods(body);
      })
      .catch(() => {
        // A picker that cannot be built is a picker that is not shown. The
        // lens still renders on its own defaults, which is what it did
        // before there was a picker at all.
        if (live) setPeriods(null);
      });
    return () => {
      live = false;
    };
  }, [lensId]);

  const chosen = showing ?? scope.default_period ?? "";

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
            What this lens is for
          </p>
          <p className="mt-1 max-w-2xl text-xs leading-relaxed text-text-secondary">
            {scope.purpose || (
              <span className="text-text-muted">
                Nobody has said yet. Anyone who opens this lens has to work it
                out from the tiles.
              </span>
            )}
          </p>
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {scope.audience && (
              <Badge variant="outline">{scope.audience}</Badge>
            )}
            {scope.portfolio && (
              <Badge variant="outline">{scope.portfolio}</Badge>
            )}
            {scope.domains.map((domain) => (
              <Badge key={domain} variant="info">
                {domain}
              </Badge>
            ))}
            {scope.visibility === "private" && (
              <Badge variant="warning">Only me</Badge>
            )}
          </div>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2">
          {periods && periods.periods.length > 0 && (
            <label className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <CalendarRange className="size-3.5" aria-hidden />
              <span className="sr-only sm:not-sr-only">Showing</span>
              <select
                value={chosen}
                aria-label="Which period this lens shows"
                onChange={(e) => onPeriod(e.target.value)}
                className="h-8 rounded-md border border-border bg-surface px-2 text-xs text-text-primary focus:border-accent focus:outline-none"
              >
                {/*
                  An explicit "latest" is not offered as a value of its own.
                  It would be a second thing the period box can mean, and a
                  reader who picked it could not tell from the box which
                  period they were being shown.
                */}
                {periods.periods
                  .slice()
                  .reverse()
                  .map((period) => (
                    <option key={period} value={period}>
                      {period}
                    </option>
                  ))}
              </select>
            </label>
          )}
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setEditing((e) => !e)}
          >
            <Pencil aria-hidden />
            {editing ? "Close" : "Edit"}
          </Button>
        </div>
      </div>

      {periods?.note && (
        <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
          {periods.note}
        </p>
      )}

      {editing && (
        <LensScopeForm
          lensId={lensId}
          scope={scope}
          periods={periods}
          onSaved={(saved) => {
            setEditing(false);
            onSaved(saved);
          }}
        />
      )}
    </Card>
  );
}

/**
 * The lens definition panel §8 asks for: short, and about the lens rather
 * than about its tiles.
 *
 * The choices come from `GET /lenses/vocabulary` rather than from a list in
 * this file, so a domain the reader may not read never appears as an option
 * and the form cannot drift from the validator about what a visibility is.
 */
export function LensScopeForm({
  lensId,
  scope,
  periods,
  onSaved,
}: {
  lensId: number | null;
  scope: LensScope;
  periods: LensPeriods | null;
  onSaved: (scope: LensScope) => void;
}) {
  const [draft, setDraft] = React.useState<LensScope>(scope);
  const [vocabulary, setVocabulary] = React.useState<LensVocabulary | null>(
    null,
  );
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  React.useEffect(() => {
    let live = true;
    void api
      .lensVocabulary()
      .then((body) => {
        if (live) setVocabulary(body);
      })
      .catch(() => {
        if (live) setVocabulary(null);
      });
    return () => {
      live = false;
    };
  }, []);

  function set<K extends keyof LensScope>(key: K, value: LensScope[K]) {
    setDraft((current) => ({ ...current, [key]: value }));
  }

  async function save() {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      if (lensId === null) {
        onSaved(draft);
        return;
      }
      const lens = await api.setLensScope(lensId, draft);
      onSaved(lens.scope);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-4 space-y-3 border-t border-border pt-4">
      <Field label="Business purpose" hint="Why somebody would open it.">
        <textarea
          value={draft.purpose}
          onChange={(e) => set("purpose", e.target.value)}
          rows={2}
          placeholder="The monthly read a head of retail risk is asked for."
          className="w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs leading-relaxed text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
      </Field>

      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Audience" hint="Who it is written for.">
          <input
            value={draft.audience}
            onChange={(e) => set("audience", e.target.value)}
            list="lens-audiences"
            placeholder="Head of Retail Credit Risk"
            className="h-8 w-full rounded-md border border-border bg-surface px-2.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <datalist id="lens-audiences">
            {(vocabulary?.audiences ?? []).map((audience) => (
              <option key={audience} value={audience} />
            ))}
          </datalist>
        </Field>

        <Field label="Portfolio" hint="The book it reads.">
          <select
            value={draft.portfolio}
            onChange={(e) => set("portfolio", e.target.value)}
            className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text-primary focus:border-accent focus:outline-none"
          >
            <option value="">Not scoped to one</option>
            {(vocabulary?.portfolios ?? []).map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <Field
        label="Data domains"
        hint="What it is allowed to draw on. Leave empty for no restriction."
      >
        <div className="flex flex-wrap gap-1.5">
          {(vocabulary?.domains ?? []).map((domain) => {
            const on = draft.domains.includes(domain.name);
            return (
              <button
                key={domain.name}
                type="button"
                aria-pressed={on}
                onClick={() =>
                  set(
                    "domains",
                    on
                      ? draft.domains.filter((d) => d !== domain.name)
                      : [...draft.domains, domain.name],
                  )
                }
                className={`rounded-full border px-2.5 py-1 text-[11px] transition-colors ${
                  on
                    ? "border-accent bg-accent/10 text-accent"
                    : "border-border text-text-muted hover:bg-surface-hover"
                }`}
              >
                {domain.name}
                <span className="ml-1 opacity-60">{domain.metrics}</span>
              </button>
            );
          })}
        </div>
      </Field>

      <div className="grid gap-3 sm:grid-cols-3">
        <Field label="Opens on" hint="Empty means each metric's own latest.">
          <select
            value={draft.default_period}
            onChange={(e) => set("default_period", e.target.value)}
            className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text-primary focus:border-accent focus:outline-none"
          >
            <option value="">Latest each metric has</option>
            {(periods?.periods ?? [])
              .slice()
              .reverse()
              .map((period) => (
                <option key={period} value={period}>
                  {period}
                </option>
              ))}
          </select>
        </Field>

        <Field label="Compares against" hint="Charts that ask for it use this.">
          <select
            value={draft.comparison_period}
            onChange={(e) => set("comparison_period", e.target.value)}
            className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text-primary focus:border-accent focus:outline-none"
          >
            {(vocabulary?.comparisons ?? [{ name: "", label: "No comparison" }]).map(
              (comparison) => (
                <option key={comparison.name} value={comparison.name}>
                  {comparison.label}
                </option>
              ),
            )}
          </select>
        </Field>

        <Field label="Visibility" hint="Who can open it.">
          <select
            value={draft.visibility}
            onChange={(e) => set("visibility", e.target.value)}
            className="h-8 w-full rounded-md border border-border bg-surface px-2 text-xs text-text-primary focus:border-accent focus:outline-none"
          >
            {(vocabulary?.visibilities ?? [
              { name: "shared", label: "Anyone who can reach the workspace" },
            ]).map((visibility) => (
              <option key={visibility.name} value={visibility.name}>
                {visibility.label}
              </option>
            ))}
          </select>
        </Field>
      </div>

      <p className="text-[11px] leading-relaxed text-text-muted">
        Visibility is what this lens says about itself. It is not a permission
        on the data underneath: a shared lens still shows each reader only the
        metrics their datasets allow.
      </p>

      {error && <p className="text-xs text-negative">{error}</p>}

      <Button size="sm" onClick={save} disabled={busy}>
        {busy && <Loader2 className="animate-spin" aria-hidden />}
        {lensId === null ? "Use this" : "Save"}
      </Button>
    </div>
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
      <span className="text-[11px] font-medium text-text-secondary">
        {label}
      </span>
      {hint && (
        <span className="ml-1.5 text-[11px] text-text-muted">{hint}</span>
      )}
      <div className="mt-1">{children}</div>
    </label>
  );
}
