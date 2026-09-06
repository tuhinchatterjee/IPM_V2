"use client";

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";
import {
  ArrowRight,
  Check,
  Loader2,
  Plus,
  Sparkles,
  Trash2,
  TriangleAlert,
} from "lucide-react";

import { BackLink } from "@/components/layout/back-link";
import { PageHeader } from "@/components/layout/page-header";
import { LensScopeForm } from "@/components/lenses/lens-scope";
import { MetricBuilder, type BuiltMetric } from "@/components/lenses/metric-builder";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, type ChartIntent, type LensIntent, type LensScope } from "@/lib/api";

/**
 * Creating a lens by describing it.
 *
 * §1–§11. The shape of this page is the argument: a person is asked one thing
 * at a time, and every answer CreditProbe forms is shown before it is acted on.
 *
 *   1. Say what you want to watch, in ordinary language.
 *   2. Confirm which governed data domains that means — as options to tick,
 *      with what each matched on, plus a box for one it missed.
 *   3. Name it, and settle what it is for.
 *   4. Fill it: existing metrics from the library, or new ones defined,
 *      previewed against real data and locked.
 *
 * The interpretation is deterministic — the catalogue reads the sentence, not
 * a model — so a reading that is wrong is visibly wrong here rather than
 * mysteriously absent from the lens later.
 */
export default function NewLensPage() {
  return (
    <React.Suspense fallback={<Loader2 className="size-4 animate-spin" aria-hidden />}>
      <Builder />
    </React.Suspense>
  );
}

interface Picked {
  metric_id: string;
  name: string;
}

function Builder() {
  const router = useRouter();
  const params = useSearchParams();
  const carried = params.get("say") ?? "";

  const [said, setSaid] = React.useState(carried);
  const [intent, setIntent] = React.useState<LensIntent | null>(null);
  /** The sentence that was actually read, which is what this lens is for. */
  const [sentence, setSentence] = React.useState("");
  const [domains, setDomains] = React.useState<string[]>([]);
  const [extra, setExtra] = React.useState("");

  const [name, setName] = React.useState("");
  const [named, setNamed] = React.useState("");
  const [scope, setScope] = React.useState<LensScope | null>(null);
  const [description, setDescription] = React.useState("");

  const [picked, setPicked] = React.useState<Picked[]>([]);
  const [charts, setCharts] = React.useState<ChartIntent[]>([]);
  const [adding, setAdding] = React.useState(false);

  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");

  const read = React.useCallback(async (text: string) => {
    if (!text.trim()) return;
    setBusy(true);
    setError("");
    try {
      const body = await api.interpretLens(text.trim());
      setIntent(body);
      setSentence(text.trim());
      setDomains(body.domains.filter((d) => d.chosen).map((d) => d.name));
      setName((current) => current || suggestName(body));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  // The sentence carried in from the library is read once, out of the render
  // path. A `useEffect` that calls setState synchronously cascades renders and
  // React now warns about it; the work here is a fetch, so it belongs after
  // paint rather than during it.
  const started = React.useRef(false);
  React.useEffect(() => {
    if (!carried || started.current) return;
    started.current = true;
    const timer = setTimeout(() => void read(carried), 0);
    return () => clearTimeout(timer);
  }, [carried, read]);

  async function create() {
    // The same condition the button is disabled by. They were different —
    // the button enabled itself for a chart-only lens and this returned
    // without doing anything, so the click looked like it had worked and
    // nothing happened. A guard that disagrees with its own control is worse
    // than no guard.
    if (!named || picked.length + charts.length === 0 || busy) return;
    setBusy(true);
    setError("");
    try {
      const lens = await api.createLens({
        name: named,
        description,
        audience: effectiveScope.audience,
        scope: effectiveScope,
        panels: [
          ...picked.map((m) => ({
            kind: "metric" as const,
            metric_id: m.metric_id,
            visual: "kpi",
          })),
          ...charts.map((c) => ({
            kind: "chart" as const,
            metric_id: c.metric_id,
            visual: c.visual,
            params: { dimension: c.dimension, aggregate: "metric",
                      sort: c.over_time ? "label" : "value",
                      direction: c.over_time ? "asc" : "desc", limit: 20,
                      compare: "" },
          })),
        ],
      });
      router.push(`/lenses/${lens.id}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  }

  const chosenDomain = domains[0] ?? "";

  /**
   * What this lens says it is for, before anybody edits it.
   *
   * The sentence somebody typed IS the purpose — it is the answer to "what
   * should this lens watch" in their own words — so a lens created without
   * opening the definition panel still carries one. It used to save an empty
   * purpose, which made the definition panel on the lens read as though
   * nobody had ever said what it was for.
   */
  const effectiveScope: LensScope = scope
    ? { ...scope, domains }
    : {
        purpose: sentence,
        audience: "",
        portfolio: intent?.portfolios[0] ?? "",
        domains,
        default_period: "",
        comparison_period: "",
        visibility: "shared",
      };

  return (
    <div className="space-y-6">
      <BackLink href="/lenses" label="Lenses" />
      <PageHeader
        title="Create a lens"
        description="Describe what you want to watch. CreditProbe shows what it recognised before it builds anything, and every metric it offers is one that calculates against this deployment's governed data."
      />

      {/* -------------------------------------------------- 1. the sentence */}

      <Card className="p-5">
        <Step n={1} title="What do you want this lens to watch?"
              done={!!intent} />
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={said}
            autoFocus
            aria-label="What this lens should watch"
            data-testid="lens-sentence"
            placeholder="Watchlist exposure and covenant breaches across the corporate book"
            onChange={(e) => setSaid(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void read(said);
            }}
            className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
          <Button size="sm" onClick={() => void read(said)}
                  disabled={busy || !said.trim()} data-testid="read-sentence">
            {busy ? <Loader2 className="animate-spin" aria-hidden />
                  : <Sparkles aria-hidden />}
            Read it
          </Button>
        </div>
        {intent && (
          <p className="mt-2 text-xs leading-relaxed text-text-secondary"
             data-testid="understood">
            {intent.understood}
          </p>
        )}
        {intent && intent.unavailable.length > 0 && (
          <div className="mt-2 rounded-md border border-warning/40 bg-warning/5 p-2.5"
               data-testid="lens-refusals">
            {intent.unavailable.map((entry) => (
              <p key={entry.metric_id}
                 className="text-[11px] leading-relaxed text-text-secondary">
                <span className="font-medium">{entry.name}</span> is not
                available in this deployment. {entry.because}
              </p>
            ))}
          </div>
        )}
      </Card>

      {/* --------------------------------------------------- 2. the domains */}

      {intent && (
        <Card className="p-5">
          <Step n={2} title="Which governed data does that mean?"
                done={domains.length > 0} />
          <p className="mt-1 text-[11px] leading-relaxed text-text-muted">
            Tick the ones you meant. More than one is normal — a lens often
            reads two books — and anything CreditProbe got wrong is wrong here
            rather than missing from the lens later.
          </p>
          <div className="mt-3 flex flex-wrap gap-1.5" data-testid="domain-options">
            {intent.domains.map((option) => {
              const on = domains.includes(option.name);
              return (
                <button
                  key={option.name}
                  type="button"
                  aria-pressed={on}
                  data-testid="domain-option"
                  onClick={() =>
                    setDomains((current) =>
                      on
                        ? current.filter((d) => d !== option.name)
                        : [...current, option.name],
                    )
                  }
                  className={`rounded-full border px-3 py-1.5 text-left text-[11px] transition-colors ${
                    on
                      ? "border-accent bg-accent/10 text-accent"
                      : "border-border text-text-secondary hover:bg-surface-hover"
                  }`}
                >
                  {option.name}
                  <span className="ml-1 opacity-60">{option.metrics}</span>
                </button>
              );
            })}
            {intent.domains.length === 0 && (
              <p className="text-[11px] text-text-muted">
                Nothing recognised. Name a domain below, or say it another way.
              </p>
            )}
          </div>
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              value={extra}
              aria-label="A data domain CreditProbe did not offer"
              data-testid="domain-freetext"
              placeholder="Or type one it missed"
              onChange={(e) => setExtra(e.target.value)}
              className="h-8 min-w-0 flex-1 rounded-md border border-border bg-surface px-2.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            <Button
              size="sm"
              variant="outline"
              disabled={!extra.trim()}
              onClick={() => {
                setDomains((c) =>
                  c.includes(extra.trim()) ? c : [...c, extra.trim()],
                );
                setExtra("");
              }}
            >
              <Plus aria-hidden />
              Add
            </Button>
          </div>
        </Card>
      )}

      {/* ------------------------------------------------------ 3. the name */}

      {intent && (
        <Card className="p-5">
          <Step n={3} title="What is it called, and what is it for?"
                done={!!named} />
          <div className="mt-3 flex flex-wrap gap-2">
            <input
              value={name}
              aria-label="What this lens is called"
              data-testid="lens-name"
              placeholder="Corporate Watchlist Monitor"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && name.trim()) setNamed(name.trim());
              }}
              className="h-9 min-w-0 flex-1 rounded-md border border-border bg-surface px-3 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
            <Button size="sm" disabled={!name.trim()}
                    onClick={() => setNamed(name.trim())}
                    data-testid="confirm-name">
              <Check aria-hidden />
              Use this name
            </Button>
          </div>
          {named && (
            <LensScopeForm
              lensId={null}
              periods={null}
              scope={effectiveScope}
              onSaved={(saved) => setScope({ ...saved, domains })}
            />
          )}
        </Card>
      )}

      {/* -------------------------------------------------- 4. the metrics */}

      {named && (
        <Card className="p-5">
          <Step n={4} title="What should it show?" done={picked.length > 0} />

          {(picked.length > 0 || charts.length > 0) && (
            <ul className="mt-3 divide-y divide-border overflow-hidden rounded-md border border-border"
                data-testid="lens-contents">
              {picked.map((m) => (
                <li key={m.metric_id}
                    className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="min-w-0 truncate text-sm text-text-primary">
                    {m.name}
                  </span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Badge variant="outline">Figure</Badge>
                    <Button variant="ghost" size="sm"
                            aria-label={`Remove ${m.name}`}
                            onClick={() =>
                              setPicked((c) =>
                                c.filter((x) => x.metric_id !== m.metric_id))
                            }>
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                </li>
              ))}
              {charts.map((c, index) => (
                <li key={`${c.metric_id}-${c.dimension}`}
                    className="flex items-center justify-between gap-3 px-3 py-2">
                  <span className="min-w-0 truncate text-sm text-text-primary">
                    {c.metric_name} by {c.dimension_label}
                  </span>
                  <div className="flex shrink-0 items-center gap-1.5">
                    <Badge variant="outline">{c.visual}</Badge>
                    <Button variant="ghost" size="sm"
                            aria-label={`Remove the ${c.dimension_label} chart`}
                            onClick={() =>
                              setCharts((cs) => cs.filter((_, i) => i !== index))
                            }>
                      <Trash2 aria-hidden />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          {/* §11: the chart the sentence asked for, offered rather than assumed. */}
          {intent && intent.charts.length > 0 && (
            <div className="mt-4">
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
                Charts your description asked for
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {intent.charts
                  .filter((c) =>
                    !charts.some(
                      (x) => x.metric_id === c.metric_id &&
                             x.dimension === c.dimension))
                  .map((c) => (
                    <button
                      key={`${c.metric_id}-${c.dimension}`}
                      type="button"
                      data-testid="suggested-chart"
                      onClick={() => setCharts((cs) => [...cs, c])}
                      className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[11px] text-text-secondary transition-colors hover:bg-surface-hover"
                    >
                      <Plus className="size-3" aria-hidden />
                      {c.metric_name} by {c.dimension_label} ({c.visual})
                    </button>
                  ))}
              </div>
            </div>
          )}

          {intent && intent.metrics.length > 0 && !adding && (
            <div className="mt-4">
              <p className="text-[10px] font-medium uppercase tracking-[0.14em] text-text-muted">
                Metrics your description matched
              </p>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {intent.metrics
                  .filter((m) => !picked.some((p) => p.metric_id === m.metric_id))
                  .map((m) => (
                    <button
                      key={m.metric_id}
                      type="button"
                      data-testid="suggested-metric"
                      onClick={() =>
                        setPicked((c) => [
                          ...c,
                          { metric_id: m.metric_id, name: m.name },
                        ])
                      }
                      className="inline-flex items-center gap-1 rounded-full border border-border px-2.5 py-1 text-[11px] text-text-secondary transition-colors hover:bg-surface-hover"
                    >
                      <Plus className="size-3" aria-hidden />
                      {m.name}
                    </button>
                  ))}
              </div>
            </div>
          )}

          <div className="mt-4">
            {adding ? (
              <MetricBuilder
                lensName={named}
                domain={chosenDomain}
                portfolio={scope?.portfolio ?? ""}
                chosen={picked.map((m) => m.metric_id)}
                onLocked={(made: BuiltMetric) =>
                  setPicked((c) =>
                    c.some((x) => x.metric_id === made.metric_id)
                      ? c
                      : [...c, made],
                  )
                }
                onDone={() => setAdding(false)}
              />
            ) : (
              <Button variant="outline" onClick={() => setAdding(true)}
                      data-testid="open-metric-builder">
                <Plus aria-hidden />
                Add a metric
              </Button>
            )}
          </div>

          <label className="mt-4 block">
            <span className="text-[11px] font-medium text-text-secondary">
              Description
            </span>
            <input
              value={description}
              aria-label="Lens description"
              placeholder="One line, for the library card."
              onChange={(e) => setDescription(e.target.value)}
              className="mt-1 h-8 w-full rounded-md border border-border bg-surface px-2.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
            />
          </label>
        </Card>
      )}

      {named && (
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={create}
                  disabled={busy || picked.length + charts.length === 0}
                  data-testid="create-lens">
            {busy ? <Loader2 className="animate-spin" aria-hidden />
                  : <ArrowRight aria-hidden />}
            Create the lens
          </Button>
          <p className="text-[11px] text-text-muted">
            {picked.length + charts.length === 0
              ? "Add at least one metric. A lens with nothing on it cannot be saved."
              : `${picked.length} figure${picked.length === 1 ? "" : "s"} and ${charts.length} chart${charts.length === 1 ? "" : "s"}.`}
          </p>
        </div>
      )}

      {error && (
        <p className="flex items-start gap-1.5 text-xs text-negative">
          <TriangleAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
          {error}
        </p>
      )}
    </div>
  );
}

/** A name from what CreditProbe understood, so the field is not empty. */
function suggestName(intent: LensIntent): string {
  const domain = intent.domains.find((d) => d.chosen)?.name ?? "";
  if (intent.metrics.length > 0 && domain) {
    return `${domain} watch`;
  }
  return domain ? `${domain} lens` : "";
}

function Step({ n, title, done }: { n: number; title: string; done: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span
        aria-hidden
        className={`inline-flex size-5 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold ${
          done ? "bg-accent text-white" : "border border-border text-text-muted"
        }`}
      >
        {done ? <Check className="size-3" /> : n}
      </span>
      <h2 className="text-sm font-semibold tracking-tight text-text-primary">
        {title}
      </h2>
    </div>
  );
}
