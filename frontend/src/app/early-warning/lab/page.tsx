"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowLeft,
  Check,
  Loader2,
  Play,
  TriangleAlert,
} from "lucide-react";

import { useRole } from "@/components/system/role-switcher";
import { technical } from "@/lib/format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty";
import { InfoPopover } from "@/components/ui/info-popover";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import {
  api,
  type BacktestResult,
  type EarlyWarningModel,
  type ImpactAnalysis,
  type SignalSpecification,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

import { PrototypeNotice } from "../page";

/**
 * The Model Lab.
 *
 * Administrator only, and deliberately the narrowest permission in the product:
 * a data steward may publish data and an analyst may run any analysis, but
 * neither may decide what "high risk" means.
 *
 * Three things happen here and nothing else does.
 *
 *   FIT      estimate a specification on the early quarters and test it on the
 *            last three, which it has never seen
 *   REVIEW   read the weights against what a credit officer would expect, and
 *            the backtest against chance
 *   COMPARE  before adopting a version, see what it would actually do to the
 *            book — which facilities change band and how much exposure moves
 *
 * A fit is never silently adopted, and every stored version is a PROTOTYPE
 * whatever its numbers look like.
 */
export default function ModelLabPage() {
  const { role } = useRole();
  const overview = useAsync(() => api.earlyWarning(), []);
  const [refresh, setRefresh] = React.useState(0);
  const models = useAsync(
    () => api.earlyWarningModels(),
    [refresh],
    { enabled: role === "ADMIN" },
  );
  const [tab, setTab] = React.useState("models");

  if (role !== "ADMIN") {
    return (
      <div className="space-y-6">
        <Back />
        <EmptyState
          icon={TriangleAlert}
          title="The Model Lab needs the Administrator role"
          description="Fitting and activating a Forward Risk Signal model changes how the whole book is ranked, so it sits behind the narrowest permission in the product. You can read the signal itself from Early Warning."
          action={
            <Button size="sm" asChild>
              <Link href="/early-warning">Back to Early Warning</Link>
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="space-y-7">
      <Back />

      <header>
        <p className="text-[10px] font-medium uppercase tracking-[0.16em] text-text-muted">
          Early Warning
        </p>
        <div className="mt-1.5 flex flex-wrap items-center gap-2">
          <h1 className="text-[24px] font-semibold leading-tight tracking-tight text-text-primary">
            Model Lab
          </h1>
          <InfoPopover title="What the Model Lab does">
            <p>
              Fits a Forward Risk Signal specification on the early reporting
              quarters and tests it on the last three, which it has never seen.
            </p>
            <p>
              Refitting always creates a new version; it never edits one, so a
              score quoted last month stays reproducible. Only one version per
              transition is in use at a time.
            </p>
          </InfoPopover>
        </div>
      </header>

      {overview.data && <PrototypeNotice notice={overview.data.notice} />}

      <Tabs
        active={tab}
        onChange={setTab}
        tabs={[
          { id: "models", label: "Versions", count: models.data?.models.length },
          { id: "fit", label: "Fit a model" },
          { id: "compare", label: "Impact analysis" },
        ]}
      />

      {tab === "models" && (
        <Versions
          models={models.data?.models ?? []}
          loading={models.loading}
          error={models.error}
          onChange={() => setRefresh((n) => n + 1)}
        />
      )}

      {tab === "fit" && (
        <FitPanel
          targets={(overview.data?.targets ?? []).map((t) => ({
            id: t.id,
            label: t.label,
          }))}
          onFitted={() => setRefresh((n) => n + 1)}
        />
      )}

      {tab === "compare" && <ComparePanel models={models.data?.models ?? []} />}
    </div>
  );
}

function Back() {
  return (
    <Button variant="ghost" size="sm" asChild className="-ml-2">
      <Link href="/early-warning">
        <ArrowLeft aria-hidden />
        Early Warning
      </Link>
    </Button>
  );
}

/* ---------------------------------------------------------------- versions */

function Versions({
  models,
  loading,
  error,
  onChange,
}: {
  models: EarlyWarningModel[];
  loading: boolean;
  error: string | null;
  onChange: () => void;
}) {
  const [open, setOpen] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState<number | null>(null);

  async function activate(id: number) {
    setBusy(id);
    try {
      await api.activateEarlyWarningModel(id);
      onChange();
    } finally {
      setBusy(null);
    }
  }

  if (loading) return <Skeleton className="h-52 w-full" />;
  if (error) {
    return (
      <Card className="border-negative/40 p-4 text-sm text-negative">{error}</Card>
    );
  }
  if (models.length === 0) {
    return (
      <EmptyState
        title="No models fitted yet"
        description="Fit one on the next tab. It takes a few seconds and holds the last three quarters back to test on."
      />
    );
  }

  return (
    <Card className="divide-y divide-border">
      {models.map((model) => (
        <div key={model.id}>
          <div className="flex flex-wrap items-center gap-3 px-4 py-3">
            <button
              type="button"
              onClick={() => setOpen(open === model.id ? null : model.id)}
              className="min-w-0 flex-1 text-left"
            >
              <span className="flex flex-wrap items-center gap-2">
                <span className="truncate text-sm font-medium text-text-primary">
                  {model.name}
                </span>
                <Badge variant={model.is_active ? "accent" : "outline"}>
                  {model.is_active ? "In use" : `v${model.version}`}
                </Badge>
                <Badge variant="warning">{model.lifecycle_label}</Badge>
              </span>
              <span className="mt-0.5 block truncate text-[11px] text-text-muted">
                {model.target_label} · fitted on{" "}
                {model.specification.fitted_rows?.toLocaleString() ?? "—"} rows ·{" "}
                {model.specification.backtest?.auc != null
                  ? `AUC ${technical(model.specification.backtest.auc)}`
                  : "no backtest stored"}
              </span>
            </button>
            {!model.is_active && (
              <Button
                variant="outline"
                size="sm"
                disabled={busy === model.id}
                onClick={() => activate(model.id)}
              >
                {busy === model.id ? (
                  <Loader2 className="animate-spin" aria-hidden />
                ) : (
                  <Check aria-hidden />
                )}
                Put into use
              </Button>
            )}
          </div>

          {open === model.id && (
            <div className="space-y-6 border-t border-border bg-surface-sunken px-4 py-4">
              <p className="text-xs leading-relaxed text-warning">{model.notice}</p>
              <Weights specification={model.specification} />
              {model.specification.backtest && (
                <Backtest result={model.specification.backtest} />
              )}
            </div>
          )}
        </div>
      ))}
    </Card>
  );
}

/* ----------------------------------------------------------------- weights */

function Weights({ specification }: { specification: SignalSpecification }) {
  const ordered = [...(specification.weights ?? [])].sort(
    (a, b) => Math.abs(b.weight) - Math.abs(a.weight),
  );
  const largest = Math.max(...ordered.map((w) => Math.abs(w.weight)), 0.0001);
  const disagreeing = ordered.filter(
    (w) => !w.agrees_with_expectation && Math.abs(w.weight) > 0.05,
  );

  return (
    <div>
      <p className="mb-2 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        Weights
        <InfoPopover title="Reading the weights">
          <p>
            Each weight applies to its factor standardised against the fitting
            population, so they are directly comparable with one another.
          </p>
          <p>
            A weight whose sign disagrees with what a credit officer would expect
            is flagged. That is not automatically an error — correlated factors
            routinely swap signs — but it is the thing to look at first.
          </p>
        </InfoPopover>
      </p>

      {disagreeing.length > 0 && (
        <p className="mb-3 flex items-start gap-1.5 text-xs text-warning">
          <TriangleAlert className="mt-0.5 size-3 shrink-0" aria-hidden />
          {disagreeing.length}{" "}
          {disagreeing.length === 1 ? "factor disagrees" : "factors disagree"} with
          credit intuition: {disagreeing.map((w) => w.label).join(", ")}. Worth
          understanding before this version is put into use.
        </p>
      )}

      <div className="space-y-1">
        {ordered.map((weight) => (
          <div key={weight.factor_id} className="flex items-center gap-3 text-xs">
            <span className="w-44 shrink-0 truncate text-text-secondary">
              {weight.label}
            </span>
            <span className="hidden w-28 shrink-0 truncate text-[11px] text-text-muted sm:block">
              {weight.family_label}
            </span>
            <span className="relative h-3 min-w-0 flex-1">
              <span className="absolute inset-y-0 left-1/2 w-px bg-border" />
              <span
                className={cn(
                  "absolute inset-y-0.5 rounded-sm",
                  weight.agrees_with_expectation ? "bg-accent/50" : "bg-warning/60",
                )}
                style={
                  weight.weight >= 0
                    ? { left: "50%", width: `${(50 * Math.abs(weight.weight)) / largest}%` }
                    : { right: "50%", width: `${(50 * Math.abs(weight.weight)) / largest}%` }
                }
              />
            </span>
            <span className="w-16 shrink-0 text-right tabular font-medium text-text-primary">
              {weight.weight > 0 ? "+" : ""}
              {technical(weight.weight)}
            </span>
            {!weight.agrees_with_expectation && Math.abs(weight.weight) > 0.05 && (
              <TriangleAlert className="size-3 shrink-0 text-warning" aria-hidden />
            )}
          </div>
        ))}
      </div>

      <p className="mt-3 text-[11px] text-text-muted">
        Intercept {technical(specification.intercept)} · fitted on{" "}
        {specification.fitted_periods?.length ?? 0} quarters ·{" "}
        {specification.fitted_events?.toLocaleString()} transitions in{" "}
        {specification.fitted_rows?.toLocaleString()} rows (base rate{" "}
        {specification.base_rate_pct?.toFixed(2)}%)
      </p>
    </div>
  );
}

/* --------------------------------------------------------------- backtest */

function Backtest({ result }: { result: BacktestResult }) {
  return (
    <div className="space-y-4">
      <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
        Out-of-time backtest
      </p>

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="AUC" value={technical(result.auc)} hint="0.5 is chance" />
        <Stat label="KS" value={technical(result.ks)} hint="separation" />
        <Stat
          label="Worst decile capture"
          value={`${result.top_decile_capture_pct.toFixed(0)}%`}
          hint="of all transitions"
        />
        <Stat
          label="Tested on"
          value={result.facilities.toLocaleString()}
          hint={`${result.events} transitions`}
        />
      </div>

      <p className="max-w-3xl text-xs leading-relaxed text-text-secondary">
        {result.verdict}
      </p>

      {result.deciles.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] text-text-muted">
            Decile lift — the book split into ten equal groups, worst-scoring first
          </p>
          <div className="flex items-end gap-1">
            {result.deciles.map((decile) => {
              const height = Math.min(100, (decile.lift / 6) * 100);
              return (
                <div key={decile.decile} className="min-w-0 flex-1">
                  <div
                    className="rounded-t-sm bg-accent/60"
                    style={{ height: `${Math.max(2, height)}px` }}
                    title={`Decile ${decile.decile}: ${decile.rate_pct.toFixed(2)}% migrated, ${decile.lift.toFixed(2)}x the book rate`}
                  />
                  <p className="mt-1 truncate text-center text-[10px] tabular text-text-muted">
                    {decile.lift.toFixed(1)}x
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {result.calibration.length > 0 && (
        <div>
          <p className="mb-1.5 text-[11px] text-text-muted">
            Calibration — predicted against observed, by band
          </p>
          <div className="space-y-1">
            {result.calibration.map((band) => (
              <div key={band.band} className="flex items-center gap-3 text-xs">
                <span className="w-20 shrink-0 text-text-secondary">{band.band}</span>
                <span className="w-16 shrink-0 text-right tabular text-text-muted">
                  {band.facilities.toLocaleString()}
                </span>
                <span className="w-20 shrink-0 text-right tabular text-text-muted">
                  {band.predicted_pct.toFixed(1)}% predicted
                </span>
                <span className="w-20 shrink-0 text-right tabular text-text-primary">
                  {band.observed_pct.toFixed(1)}% observed
                </span>
                <span
                  className={cn(
                    "tabular",
                    Math.abs(band.gap_pp) > 3 ? "text-warning" : "text-text-muted",
                  )}
                >
                  {band.gap_pp > 0 ? "+" : ""}
                  {band.gap_pp.toFixed(1)}pp
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      <p className="text-[11px] text-text-muted">
        Fitted on {result.fitted_periods.join(", ")}. Tested on{" "}
        {result.tested_periods.join(", ")} — never seen during fitting.
      </p>
    </div>
  );
}

function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}) {
  return (
    <Card className="p-3">
      <p className="text-[11px] text-text-muted">{label}</p>
      <p className="mt-0.5 text-[18px] font-semibold tabular text-text-primary">
        {value}
      </p>
      {hint && <p className="text-[10px] text-text-muted">{hint}</p>}
    </Card>
  );
}

/* -------------------------------------------------------------------- fit */

function FitPanel({
  targets,
  onFitted,
}: {
  targets: { id: string; label: string }[];
  onFitted: () => void;
}) {
  const [targetId, setTargetId] = React.useState(targets[0]?.id ?? "");
  const [testQuarters, setTestQuarters] = React.useState(3);
  const [changeNote, setChangeNote] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [result, setResult] = React.useState<{
    specification: SignalSpecification;
    backtest: BacktestResult;
  } | null>(null);

  const selected = targetId || targets[0]?.id || "";

  async function fit() {
    if (!selected) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.fitEarlyWarning({
        targetId: selected,
        testQuarters,
        changeNote,
      });
      setResult({
        specification: response.specification,
        backtest: response.backtest,
      });
      onFitted();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <Card className="space-y-4 p-5">
        <div>
          <label
            htmlFor="fit-target"
            className="text-xs font-medium text-text-secondary"
          >
            Transition to fit
          </label>
          <select
            id="fit-target"
            value={selected}
            onChange={(e) => setTargetId(e.target.value)}
            className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
          >
            {targets.map((target) => (
              <option key={target.id} value={target.id}>
                {target.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label
            htmlFor="fit-holdout"
            className="text-xs font-medium text-text-secondary"
          >
            Quarters held back for testing
          </label>
          <input
            id="fit-holdout"
            type="number"
            min={1}
            max={6}
            value={testQuarters}
            onChange={(e) => setTestQuarters(Number(e.target.value))}
            className="mt-1 w-24 rounded-md border border-border bg-surface px-3 py-2 text-sm tabular text-text-primary focus:border-accent focus:outline-none"
          />
          <p className="mt-1 text-[11px] text-text-muted">
            The split is by time, never at random. A random split would let the
            model see the same borrower in both halves and count its persistence
            as skill.
          </p>
        </div>

        <div>
          <label
            htmlFor="fit-note"
            className="text-xs font-medium text-text-secondary"
          >
            Why are you refitting?
          </label>
          <input
            id="fit-note"
            value={changeNote}
            onChange={(e) => setChangeNote(e.target.value)}
            placeholder="Q2 2026 data published; refitting on the full history."
            className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
          />
        </div>

        <div className="flex items-center gap-3">
          <Button size="sm" onClick={fit} disabled={busy || !selected}>
            {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
            Fit and backtest
          </Button>
          <p className="text-[11px] text-text-muted">
            Stored as a new prototype version and put into use.
          </p>
        </div>

        {error && <p className="text-xs text-negative">{error}</p>}
      </Card>

      {result && (
        <Card className="space-y-6 p-5">
          <Weights specification={result.specification} />
          <Backtest result={result.backtest} />
        </Card>
      )}
    </div>
  );
}

/* ---------------------------------------------------------------- compare */

function ComparePanel({ models }: { models: EarlyWarningModel[] }) {
  const [fromId, setFromId] = React.useState<number | null>(null);
  const [toId, setToId] = React.useState<number | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [impact, setImpact] = React.useState<ImpactAnalysis | null>(null);

  async function compare() {
    if (fromId === null || toId === null) return;
    setBusy(true);
    setError(null);
    setImpact(null);
    try {
      setImpact(await api.compareEarlyWarningModels(fromId, toId));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  if (models.length < 2) {
    return (
      <EmptyState
        title="Two versions are needed to compare"
        description="Impact analysis runs both specifications over the same facilities in the same period and reports which ones change band. Fit a second version to use it."
      />
    );
  }

  return (
    <div className="space-y-6">
      <Card className="space-y-4 p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <ModelSelect
            id="compare-from"
            label="Currently"
            models={models}
            value={fromId}
            onChange={setFromId}
          />
          <ModelSelect
            id="compare-to"
            label="Would become"
            models={models}
            value={toId}
            onChange={setToId}
          />
        </div>
        <Button
          size="sm"
          onClick={compare}
          disabled={busy || fromId === null || toId === null || fromId === toId}
        >
          {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
          Show the impact
        </Button>
        <p className="text-[11px] text-text-muted">
          Consequences, not coefficients. &ldquo;The AUC improved by 0.02&rdquo;
          is not something a credit committee can act on; &ldquo;eleven
          facilities carrying 340 million move into High&rdquo; is.
        </p>
        {error && <p className="text-xs text-negative">{error}</p>}
      </Card>

      {impact && (
        <Card className="space-y-5 p-5">
          <p className="max-w-3xl text-sm leading-relaxed text-text-primary">
            {impact.summary}
          </p>

          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <Stat
              label="Into a worse band"
              value={impact.moved_to_worse_band.toLocaleString()}
              hint={`${impact.ead_to_worse_band.toLocaleString()} USD mn`}
            />
            <Stat
              label="Into a better band"
              value={impact.moved_to_better_band.toLocaleString()}
              hint={`${impact.ead_to_better_band.toLocaleString()} USD mn`}
            />
            <Stat label="Unchanged" value={impact.unchanged.toLocaleString()} />
            <Stat
              label="Compared"
              value={impact.facilities_compared.toLocaleString()}
              hint={impact.period}
            />
          </div>

          {impact.biggest_increases.length > 0 && (
            <div>
              <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
                Largest moves into a worse band
              </p>
              <div className="space-y-1">
                {impact.biggest_increases.slice(0, 8).map((move) => (
                  <div
                    key={move.account_id}
                    className="flex items-center gap-3 text-xs"
                  >
                    <span className="min-w-0 flex-1 truncate text-text-secondary">
                      {move.borrower_name}
                    </span>
                    <span className="hidden w-32 shrink-0 truncate text-text-muted sm:block">
                      {move.sector}
                    </span>
                    <span className="w-20 shrink-0 text-right tabular text-text-muted">
                      {move.ead.toFixed(1)}
                    </span>
                    <span className="w-40 shrink-0 text-right text-text-primary">
                      {move.from_band} → {move.to_band}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div>
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.12em] text-text-muted">
              What moved in the weights
            </p>
            <div className="space-y-1">
              {impact.weight_changes.slice(0, 8).map((change) => (
                <div key={change.factor_id} className="flex items-center gap-3 text-xs">
                  <span className="min-w-0 flex-1 truncate text-text-secondary">
                    {change.label}
                  </span>
                  <span className="w-16 shrink-0 text-right tabular text-text-muted">
                    {technical(change.before)}
                  </span>
                  <span className="w-16 shrink-0 text-right tabular text-text-muted">
                    {technical(change.after)}
                  </span>
                  <span
                    className={cn(
                      "w-16 shrink-0 text-right tabular font-medium",
                      Math.abs(change.change) > 0.1
                        ? "text-text-primary"
                        : "text-text-muted",
                    )}
                  >
                    {change.change > 0 ? "+" : ""}
                    {technical(change.change)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </div>
  );
}

function ModelSelect({
  id,
  label,
  models,
  value,
  onChange,
}: {
  id: string;
  label: string;
  models: EarlyWarningModel[];
  value: number | null;
  onChange: (id: number) => void;
}) {
  return (
    <div>
      <label htmlFor={id} className="text-xs font-medium text-text-secondary">
        {label}
      </label>
      <select
        id={id}
        value={value ?? ""}
        onChange={(e) => onChange(Number(e.target.value))}
        className="mt-1 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm text-text-primary focus:border-accent focus:outline-none"
      >
        <option value="">Choose a version…</option>
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.name}
            {model.is_active ? " (in use)" : ""}
          </option>
        ))}
      </select>
    </div>
  );
}
