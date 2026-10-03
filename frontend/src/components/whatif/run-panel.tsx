"use client";

/**
 * Running a scenario: SCENARIO first, METHOD second, never assumed.
 *
 * 1. If this What-If session already executed a scenario, the reader chooses
 *    the baseline: the original reported book, or layered on a run.
 * 2. The preview says what will be stressed; confirming it does NOT run it.
 * 3. Method selection: Delta, ML emulator, User-defined or Compare, each
 *    with its availability and reason. An unavailable method is shown and
 *    refused, never swapped for another.
 * 4. Run -> the persisted Scenario Result with its dual-scope decomposition.
 */

import * as React from "react";
import { Loader2 } from "lucide-react";

import { ResultView } from "@/components/whatif/result-view";
import { count, sar } from "@/lib/viz/format";
import type { Cohort } from "@/lib/workspace/objects";
import { readObject } from "@/lib/workspace/objects";
import {
  STATE_TEXT,
  chooseBaseline,
  chooseMethod,
  confirmRun,
  executeRun,
  readRun,
  rerunWithAnotherMethod,
  startRun,
  whatIfSession,
  type BaselineChoice,
  type MethodId,
  type ResultBody,
  type Run,
  type ScenarioResult,
  type UserAssumption,
} from "@/lib/workspace/runs";
import type { ScenarioObject } from "@/lib/workspace/scenarios";
import { METHOD_LABEL } from "@/lib/workspace/method-labels";

const METHODS: { id: MethodId | "compare"; label: string; blurb: string }[] = [
  { id: "delta", label: METHOD_LABEL.delta, blurb: "Scales booked ECL by the moved parameters, row by row; exact attribution by driver." },
  { id: "ml", label: METHOD_LABEL.ml, blurb: "The validated emulator predicts ECL under the moved inputs; shown only when every gate passes." },
  { id: "user_defined", label: METHOD_LABEL.user_defined, blurb: "You state the ECL impact; it is allocated and reconciled exactly." },
  { id: "compare", label: "Compare methods", blurb: "Every chosen available method on the same confirmed scenario, cohort and baseline." },
];

const FORMS: { id: UserAssumption["form"]; label: string }[] = [
  { id: "relative", label: "ECL moves by % of baseline" },
  { id: "absolute", label: "ECL moves by an amount (SAR m)" },
  { id: "target_amount", label: "ECL becomes (SAR m)" },
  { id: "target_rate", label: "Coverage becomes (% of EAD)" },
];

function errorText(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}

export function RunPanel({
  scenario,
  cohort,
  entry = "whatif",
  initialRunId = "",
  onRun,
}: {
  scenario: ScenarioObject;
  cohort: Cohort | null;
  entry?: "whatif" | "library" | "cockpit" | "messages";
  initialRunId?: string;
  onRun?: (run: Run | null) => void;
}) {
  const [run, setRun] = React.useState<Run | null>(null);
  const [result, setResult] = React.useState<ScenarioResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [choice, setChoice] = React.useState<Set<string>>(new Set());
  const [form, setForm] = React.useState<UserAssumption["form"]>("relative");
  const [value, setValue] = React.useState("");
  const [statedAs, setStatedAs] = React.useState("");
  const [baseline, setBaseline] = React.useState("");

  const update = React.useCallback(
    (next: Run | null) => {
      setRun(next);
      onRun?.(next);
    },
    [onRun],
  );

  React.useEffect(() => {
    if (!initialRunId) return;
    let live = true;
    readRun(initialRunId)
      .then(async (r) => {
        if (!live) return;
        update(r);
        if (r.body.result_id) setResult((await readObject<ResultBody>(r.body.result_id)) as ScenarioResult);
      })
      .catch((e: unknown) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [initialRunId, update]);

  // One governed mutation at a time: a double-click fires twice before
  // `busy` disables the control; the ref closes that window.
  const inFlight = React.useRef(false);
  async function act(fn: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }

  const start = () =>
    act(async () => {
      setResult(null);
      update(
        await startRun({
          scenario_id: scenario.object_id,
          scenario_version: scenario.version,
          cohort_id: cohort?.object_id,
          cohort_version: cohort?.version,
          session_id: whatIfSession(),
          entry,
        }),
      );
    });

  const pickBaseline = () =>
    act(async () => {
      if (!run || !baseline) return;
      const opt = run.body.question?.options.find((o) => (o.parent_run_id ?? o.mode) === baseline);
      if (!opt) return;
      const chosen: BaselineChoice = opt.mode === "PRIOR_SCENARIO" ? { mode: opt.mode, parent_run_id: opt.parent_run_id } : { mode: opt.mode };
      update(await chooseBaseline(run.object_id, chosen));
    });

  const confirm = () =>
    act(async () => {
      if (run) update(await confirmRun(run.object_id, run.body.contract.digest));
    });

  const assumption = (): UserAssumption | null =>
    value.trim() ? { form, value: value.trim(), stated_as: statedAs.trim() || undefined } : null;

  const runIt = () =>
    act(async () => {
      if (!run) return;
      const methods = [...choice];
      const next = await chooseMethod(run.object_id, methods, choice.has("user_defined") || choice.has("compare") ? assumption() : null);
      update(next);
      if (next.status !== "READY_TO_EXECUTE") return;
      const done = await executeRun(next.object_id);
      update(done.run);
      setResult(done.result);
    });

  const rerun = () =>
    act(async () => {
      if (!run) return;
      setResult(null);
      setChoice(new Set());
      update(await rerunWithAnotherMethod(run.object_id));
    });

  function toggle(id: string) {
    setChoice((prev) => {
      const next = new Set(prev);
      if (id === "compare") return next.has("compare") ? new Set() : new Set(["compare"]);
      next.delete("compare");
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  const state = run?.status as Run["body"]["state"] | undefined;
  const avail = run?.body.availability;
  const needsInput = choice.has("user_defined") || (choice.has("compare") && avail?.user_defined.status !== "BLOCKED");
  const overlay = scenario.body.components.find((c) => c.kind === "overlay");

  return (
    <section className="space-y-3 rounded-xl border border-border bg-surface-raised p-4" data-testid="whatif-run" data-state={state ?? "NONE"} data-run-id={run?.object_id ?? ""}>
      <header className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold">Run this scenario</h3>
        {state && (
          <span className="rounded-full border border-border px-2 py-0.5 text-xs" data-testid="whatif-run-state">
            {STATE_TEXT[state]}
          </span>
        )}
        {busy && <Loader2 className="h-4 w-4 animate-spin" aria-label="working" />}
        {(!run || state === "EXECUTED") && (
          <button type="button" disabled={busy} onClick={() => void start()} className="ml-auto rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast disabled:opacity-40" data-testid="whatif-run-start">
            {run ? "Start another run" : "Start run"}
          </button>
        )}
      </header>
      {!run && <p className="text-xs text-text-muted">Starting a run previews it first. Nothing is calculated until you confirm the scenario AND choose a method.</p>}
      {error && (
        <p role="alert" className="text-sm text-negative" data-testid="whatif-run-error">
          {error}
        </p>
      )}

      {run && state === "WAITING_BASELINE_CHOICE" && run.body.question && (
        <fieldset className="space-y-2 rounded-lg border border-warning p-3 text-sm" data-testid="whatif-baseline-question">
          <legend className="px-1 font-semibold">{run.body.question.text}</legend>
          {run.body.question.options.map((o) => {
            const key = o.parent_run_id ?? o.mode;
            return (
              <label key={key} className="flex items-start gap-2">
                <input type="radio" name="baseline" value={key} checked={baseline === key} onChange={() => setBaseline(key)} data-testid="whatif-baseline-option" data-mode={o.mode} data-parent={o.parent_run_id ?? ""} />
                <span>
                  <span className="font-medium">{o.label}</span>
                  <span className="block text-xs text-text-muted">{o.detail}</span>
                </span>
              </label>
            );
          })}
          <button type="button" disabled={!baseline || busy} onClick={() => void pickBaseline()} className="rounded-md bg-accent px-3 py-1.5 text-sm text-accent-contrast disabled:opacity-40" data-testid="whatif-baseline-choose">
            Use this baseline
          </button>
        </fieldset>
      )}

      {run && run.body.preview && state !== "WAITING_BASELINE_CHOICE" && (
        <div className="grid gap-2 text-xs md:grid-cols-2" data-testid="whatif-run-preview">
          <div className="rounded-lg border border-border p-2">
            <div className="font-semibold">Population</div>
            <div data-testid="whatif-run-population" data-entities={run.body.preview.entities} data-owners={run.body.preview.owners} data-hash={run.body.cohort.membership_hash}>
              {run.body.preview.population}
            </div>
            <div className="tabular">
              {count(run.body.preview.entities)} exposures · {count(run.body.preview.owners)} owners · EAD {sar(Number(run.body.preview.baseline_ead))} · ECL {sar(Number(run.body.preview.baseline_ecl))}
            </div>
            <div data-testid="whatif-run-baseline" data-mode={run.body.baseline.mode}>
              Baseline: {run.body.baseline.mode === "PRIOR_SCENARIO" ? `layered on run ${run.body.baseline.parent_run_id} (${run.body.chain.map((c) => c.name).join(" → ")})` : `original reported baseline ${run.body.preview.period}`}
            </div>
            <div>
              Stages {run.body.preview.stage_policy} · overlay {run.body.preview.overlay_policy}
            </div>
          </div>
          <div className="rounded-lg border border-border p-2">
            <div className="font-semibold">Rules sent to the engine ({run.body.preview.shocks.length})</div>
            <ul className="max-h-32 overflow-auto" data-testid="whatif-run-shocks">
              {run.body.preview.shocks.map((s, i) => (
                <li key={i}>
                  {s.origin}: {s.field} {s.operation} {s.value} · {count(s.reach)} rows
                </li>
              ))}
              {!run.body.preview.shocks.length && <li className="text-text-muted">No component has a governed engine translation; only User-defined can run.</li>}
            </ul>
            {run.body.preview.compositions > 0 && <div>{run.body.preview.compositions} declared compound overlap(s)</div>}
          </div>
          {run.body.preview.notes.length > 0 && (
            <ul className="rounded-lg border border-warning p-2 md:col-span-2" data-testid="whatif-run-notes">
              {run.body.preview.notes.map((n, i) => (
                <li key={i} className={n.includes("SIGN_REVIEW") ? "font-semibold text-negative" : ""}>
                  {n}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      {run && state === "SCENARIO_PREVIEW" && (
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" disabled={busy} onClick={() => void confirm()} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast disabled:opacity-40" data-testid="whatif-run-confirm">
            Confirm scenario
          </button>
          <span className="text-xs text-text-muted">Confirming does NOT run it — you choose the method next.</span>
        </div>
      )}

      {run && avail && state && ["METHOD_SELECTION", "METHOD_INPUT_REQUIRED", "METHOD_UNAVAILABLE", "READY_TO_EXECUTE"].includes(state) && (
        <div className="space-y-2" data-testid="whatif-method-selection">
          <p className="text-sm font-semibold" data-testid="whatif-method-headline">
            Scenario confirmed — NOT executed. Choose how to translate it into ECL.
          </p>
          {run.body.gate_message && state !== "METHOD_SELECTION" && (
            <p className={`text-xs ${state === "METHOD_UNAVAILABLE" ? "text-negative" : "text-warning"}`} data-testid="whatif-method-gate">
              {run.body.gate_message}
            </p>
          )}
          <div className="grid gap-2 md:grid-cols-4">
            {METHODS.map((m) => {
              const a = avail[m.id];
              const blocked = ["UNAVAILABLE", "BLOCKED", "NOT_APPLICABLE", "NOT_ENOUGH_METHODS"].includes(a.status);
              return (
                <label
                  key={m.id}
                  className={`flex flex-col gap-1 rounded-lg border p-2 text-xs ${choice.has(m.id) ? "border-accent bg-accent/5" : "border-border"} ${blocked ? "opacity-70" : ""}`}
                  data-testid={`whatif-method-${m.id}`}
                  data-status={a.status}
                >
                  <span className="flex items-center gap-2">
                    <input type="checkbox" checked={choice.has(m.id)} onChange={() => toggle(m.id)} data-testid={`whatif-method-pick-${m.id}`} />
                    <span className="font-semibold">{m.label}</span>
                    <span className={`ml-auto rounded px-1 ${blocked ? "bg-negative/10 text-negative" : a.status === "READY" || a.status === "AVAILABLE" ? "bg-positive/10 text-positive" : "bg-warning/10"}`}>
                      {a.status}
                    </span>
                  </span>
                  <span className="text-text-muted">{m.blurb}</span>
                  {a.reason && (
                    <span className={blocked ? "text-negative" : ""} data-testid={`whatif-method-reason-${m.id}`}>
                      {a.reason}
                    </span>
                  )}
                </label>
              );
            })}
          </div>
          {needsInput && (
            <div className="grid gap-2 rounded-lg border border-border p-2 text-xs md:grid-cols-4" data-testid="whatif-ud-input">
              <select value={form} onChange={(e) => setForm(e.target.value as UserAssumption["form"])} className="rounded border border-border bg-surface px-2 py-1" data-testid="whatif-ud-form">
                {FORMS.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.label}
                  </option>
                ))}
              </select>
              <input value={value} onChange={(e) => setValue(e.target.value)} inputMode="decimal" placeholder="value, e.g. 15" className="rounded border border-border bg-surface px-2 py-1" data-testid="whatif-ud-value" />
              <input value={statedAs} onChange={(e) => setStatedAs(e.target.value)} placeholder="in your words (kept for audit)" className="rounded border border-border bg-surface px-2 py-1 md:col-span-2" data-testid="whatif-ud-stated" />
              {overlay && (
                <p className="text-text-muted md:col-span-4">
                  This scenario states an overlay ({overlay.label}). Enter it here if it is the impact you want; nothing is filled in for you.
                </p>
              )}
            </div>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <button type="button" disabled={busy || choice.size === 0} onClick={() => void runIt()} className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast disabled:opacity-40" data-testid="whatif-run-execute">
              Run with {choice.size ? [...choice].map((c) => METHODS.find((m) => m.id === c)?.label).join(" + ") : "…"}
            </button>
            <span className="text-xs text-text-muted">No method is preselected. Nothing runs until you choose one.</span>
          </div>
        </div>
      )}

      {result && (
        <ResultView
          result={result}
          actions={
            <button type="button" disabled={busy} onClick={() => void rerun()} className="rounded-md border border-border px-2 py-1 text-xs" data-testid="whatif-run-rerun">
              Same scenario, another method
            </button>
          }
        />
      )}
    </section>
  );
}
