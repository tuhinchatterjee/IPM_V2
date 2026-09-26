"use client";

/**
 * Lab-only "Model comparison" section, shown ABOVE the unchanged Cockpit.
 *
 * Type the question once, pick a saved preset, press Compare models. The
 * server freezes a comparison spec, runs each selected model's own full
 * investigation through the frozen engine, evaluates the stored evidence and
 * prepares the pack. This component only drives that API and shows what it
 * returns; it never builds an answer and never re-sends a question on
 * refresh (the comparison id is remembered, the events are re-read).
 */

import * as React from "react";

import {
  type Comparison,
  type Preflight,
  type Preset,
  type Profile,
  addReview,
  answerClarification,
  cancelComparison,
  createComparison,
  exportUrl,
  listComparisons,
  preflight as runPreflight,
  readComparison,
  readProfiles,
} from "./client";
import { SETTLED, blindLabel } from "./format";
import { AnswerCard, Evidence, Overview, StageMatrix, Status } from "./results";

const REMEMBER = "model-lab:last-comparison";

function remember(id: string | null) {
  try {
    if (id) window.sessionStorage.setItem(REMEMBER, id);
    else window.sessionStorage.removeItem(REMEMBER);
  } catch {
    /* storage unavailable; reopening falls back to Saved comparisons */
  }
}

function recall(): string | null {
  try {
    return window.sessionStorage.getItem(REMEMBER);
  } catch {
    return null;
  }
}

function errorText(e: unknown): string {
  const d = (e as { detail?: unknown })?.detail;
  if (d && typeof d === "object" && "message" in (d as object))
    return String((d as { message: unknown }).message);
  if (typeof d === "string") return d;
  return e instanceof Error ? e.message : String(e);
}

export function ModelComparisonLab() {
  const [open, setOpen] = React.useState(true);
  const [profiles, setProfiles] = React.useState<Profile[]>([]);
  const [presets, setPresets] = React.useState<Preset[]>([]);
  const [presetId, setPresetId] = React.useState("");
  const [selected, setSelected] = React.useState<string[]>([]);
  const [comparator, setComparator] = React.useState("");
  const [question, setQuestion] = React.useState("");
  const [pre, setPre] = React.useState<Preflight | null>(null);
  const [cmp, setCmp] = React.useState<Comparison | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [blind, setBlind] = React.useState(false);
  const [focus, setFocus] = React.useState<{ child: string; stage: string | null } | null>(null);
  const [pinned, setPinned] = React.useState<string[]>([]);
  const [history, setHistory] = React.useState<
    { comparison_id: string; state: string; question: string }[]
  >([]);
  const [clarText, setClarText] = React.useState("");
  const [clarTo, setClarTo] = React.useState<string[]>([]);

  const preset = presets.find((p) => p.preset_id === presetId);

  React.useEffect(() => {
    readProfiles()
      .then((r) => {
        setProfiles(r.profiles);
        setPresets(r.presets);
        const first = r.presets.find((p) => p.preset_id === "fixture-demo") ?? r.presets[0];
        if (first) {
          setPresetId(first.preset_id);
          setSelected(first.profiles);
          setComparator(first.comparator);
        }
      })
      .catch((e) => setError(`Model registry unavailable: ${errorText(e)}`));
    listComparisons().then((r) => setHistory(r.comparisons)).catch(() => {});
    const last = recall();
    if (last) readComparison(last).then(setCmp).catch(() => remember(null));
  }, []);

  // Poll a live comparison; stop when settled AND evaluated/exported.
  React.useEffect(() => {
    if (!cmp) return;
    const done = SETTLED.has(cmp.state) && cmp.evaluation && cmp.export;
    const waiting = cmp.children.some((c) => c.state === "WAITING_USER");
    if (done && !waiting) return;
    const t = window.setTimeout(() => {
      readComparison(cmp.comparison_id).then(setCmp).catch(() => {});
    }, done ? 4000 : 1000);
    return () => window.clearTimeout(t);
  }, [cmp]);

  function choosePreset(id: string) {
    setPresetId(id);
    const p = presets.find((x) => x.preset_id === id);
    if (p) {
      setSelected(p.profiles);
      setComparator(p.comparator);
    }
    setPre(null);
  }

  function input() {
    return {
      question: question.trim(),
      profile_ids: selected,
      comparator_id: comparator,
      preset_id: presetId,
      deployment: preset?.deployment ?? "mac_sequential",
      trial_count: preset?.trial_count ?? 1,
      group_spend_cap_usd: preset?.group_spend_cap_usd ?? 0,
      group_wall_clock_s: preset?.group_wall_clock_s ?? 1800,
      ...(preset?.execution_mode ? { execution_mode: preset.execution_mode } : {}),
      ...(preset?.reference_comparison_id
        ? { reference_comparison_id: preset.reference_comparison_id }
        : {}),
    };
  }

  async function onCompare() {
    setError("");
    setBusy(true);
    try {
      const p = await runPreflight(input());
      setPre(p);
      if (!p.ok) {
        setError(p.errors.join(" · "));
        return;
      }
      // One key per click: a double-click or a retried request returns the
      // same comparison instead of starting a second one.
      const key = `cmp-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
      const c = await createComparison(input(), key);
      setCmp(c);
      remember(c.comparison_id);
      setFocus(null);
      setPinned([]);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  async function onReview(target: string, decision: string) {
    if (!cmp) return;
    const reason = window.prompt(`Reason for "${decision}" on ${target}`);
    if (!reason) return;
    try {
      await addReview(cmp.comparison_id, target, decision, reason);
      setCmp(await readComparison(cmp.comparison_id));
    } catch (e) {
      setError(errorText(e));
    }
  }

  const ev = cmp?.evaluation ?? null;
  const children = ev?.children ?? [];
  const comparatorChild = children.find((c) => c.profile_id === ev?.comparator.profile_id);
  const candidates = children.filter((c) => c !== comparatorChild);
  const shown = (pinned.length ? candidates.filter((c) => pinned.includes(c.child_run_id))
    : candidates.filter((c) => c.answer || c.execution_state !== "BLOCKED")).slice(0, 2);
  const waiting = (cmp?.children ?? []).filter((c) => c.state === "WAITING_USER");
  const focusChild = focus ? children.find((c) => c.child_run_id === focus.child) : null;

  return (
    <section className="mb-6 rounded-lg border border-border-strong bg-surface" aria-labelledby="model-lab-title">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border p-3">
        <h2 id="model-lab-title" className="text-base font-semibold text-text-primary">
          Model comparison <span className="text-xs font-normal text-warning">EXPERIMENTAL · lab only</span>
        </h2>
        <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}
          className="rounded border border-border px-2 py-1 text-xs text-text-secondary">
          {open ? "Collapse" : "Expand"}
        </button>
      </header>
      {open && (
        <div className="space-y-4 p-3">
          <div className="flex flex-wrap items-end gap-3 text-xs">
            <label className="flex flex-col gap-1 text-text-secondary">
              Preset
              <select value={presetId} onChange={(e) => choosePreset(e.target.value)}
                className="rounded border border-border bg-surface-sunken p-1 text-text-primary">
                {presets.map((p) => (
                  <option key={p.preset_id} value={p.preset_id}>{p.name}</option>
                ))}
              </select>
            </label>
            <span className="text-text-muted">
              Mode: full investigation · Deployment: {preset?.deployment ?? "—"} · Repeats:{" "}
              {preset?.trial_count ?? 1} · Group cap ${preset?.group_spend_cap_usd ?? 0}
            </span>
          </div>
          {preset?.note && <p className="text-xs text-text-muted">{preset.note}</p>}

          <fieldset className="text-xs">
            <legend className="mb-1 text-text-secondary">Models (readiness is proven, not declared)</legend>
            <div className="flex flex-wrap gap-2">
              {profiles.map((p) => {
                const on = selected.includes(p.profile_id);
                return (
                  <label key={p.profile_id}
                    className={`flex items-center gap-1 rounded border px-2 py-1 ${on ? "border-accent" : "border-border"}`}
                    title={`${p.readiness.status}: ${p.readiness.reasons.join("; ")}${p.readiness.recovery ? ` — ${p.readiness.recovery}` : ""}`}>
                    <input type="checkbox" checked={on}
                      onChange={() => setSelected(on ? selected.filter((x) => x !== p.profile_id)
                        : [...selected, p.profile_id])} />
                    <span className="text-text-primary">{p.display_name}</span>
                    <span className="text-text-muted">· <Status value={p.readiness.status} /></span>
                    {p.profile_id === comparator && <span className="text-accent">(comparator)</span>}
                  </label>
                );
              })}
            </div>
          </fieldset>

          <label className="block text-xs text-text-secondary">
            Question (typed once for every model)
            <textarea value={question} onChange={(e) => setQuestion(e.target.value)} rows={2}
              data-testid="model-lab-question"
              className="mt-1 w-full rounded border border-border bg-surface-sunken p-2 text-sm text-text-primary"
              placeholder="e.g. What is Stage 2 exposure by sector for the latest quarter?" />
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="button" onClick={onCompare} disabled={busy || !question.trim() || !selected.length}
              data-testid="model-lab-compare"
              className="rounded bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast disabled:opacity-50">
              {busy ? "Checking…" : "Compare models"}
            </button>
            <button type="button" disabled={!cmp || SETTLED.has(cmp.state)}
              onClick={() => cmp && cancelComparison(cmp.comparison_id).then(setCmp)}
              className="rounded border border-border px-3 py-1.5 text-sm text-text-secondary disabled:opacity-50">
              Cancel remaining
            </button>
            <details className="text-sm">
              <summary className="cursor-pointer rounded border border-border px-3 py-1.5 text-text-secondary">
                Saved comparisons ({history.length})
              </summary>
              <ul className="mt-1 max-h-48 overflow-y-auto text-xs">
                {history.map((h) => (
                  <li key={h.comparison_id}>
                    <button type="button" className="text-left underline-offset-2 hover:underline"
                      onClick={() => readComparison(h.comparison_id).then((c) => { setCmp(c); remember(c.comparison_id); })}>
                      {h.state} · {h.question.slice(0, 80)}
                    </button>
                  </li>
                ))}
              </ul>
            </details>
          </div>
          {error && <p role="alert" className="text-sm text-negative">{error}</p>}

          {pre && (
            <div className="text-xs" aria-label="Preflight">
              <h3 className="font-medium text-text-secondary">
                Preflight (no inference, no spend) — comparator {pre.comparator.status}
              </h3>
              <ul className="mt-1 grid gap-1 md:grid-cols-2">
                {pre.profiles.map((r) => (
                  <li key={r.profile_id} className="rounded border border-border p-1">
                    <span className="text-text-primary">{r.display_name}</span> ·{" "}
                    <Status value={r.eligible ? "READY_E2E" : r.status} /> · {r.price.status} ·{" "}
                    <span className="text-text-muted">{r.reasons[0]}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {cmp && (
            <div className="space-y-4" data-testid="model-lab-result">
              <div className="flex flex-wrap items-center gap-3 text-sm">
                <span className="text-text-secondary">Comparison {cmp.comparison_id}</span>
                <Status value={cmp.state} />
                {!SETTLED.has(cmp.state) && (
                  <span className="text-xs text-warning">running — results are provisional</span>
                )}
                {ev && (
                  <span className="text-xs text-text-muted">
                    Comparator: {ev.comparator.profile_id} ({ev.comparator.status})
                    {ev.comparator.is_fixture ? " — a FIXTURE, not Opus" : ""} · evaluation r
                    {cmp.evaluation_revision} · {ev.comparison_class.join(", ")}
                  </span>
                )}
                <label className="text-xs text-text-secondary">
                  <input type="checkbox" checked={blind} onChange={() => setBlind(!blind)} /> Blind labels
                </label>
                {cmp.export?.state === "READY" && (
                  <a href={exportUrl(cmp.comparison_id)} data-testid="model-lab-download"
                    className="rounded border border-accent px-2 py-1 text-xs text-accent">
                    Download comparison pack (r{cmp.export.revision})
                  </a>
                )}
              </div>

              <ul className="flex flex-wrap gap-2 text-xs" aria-label="Live progress">
                {cmp.children.map((c) => (
                  <li key={c.child_run_id} className="rounded border border-border px-2 py-1">
                    {c.display_name}: <Status value={c.state} />
                    {c.reason ? <span className="text-text-muted"> — {c.reason}</span> : null}
                  </li>
                ))}
              </ul>

              {waiting.length > 0 && (
                <div className="rounded border border-warning bg-warning-muted p-2 text-xs">
                  <h3 className="font-medium text-text-primary">Waiting for your clarification</h3>
                  {cmp.evaluation?.children.filter((c) => c.execution_state === "WAITING_USER").map((c) => (
                    <label key={c.child_run_id} className="block">
                      <input type="checkbox" checked={clarTo.includes(c.child_run_id)}
                        onChange={() => setClarTo(clarTo.includes(c.child_run_id)
                          ? clarTo.filter((x) => x !== c.child_run_id) : [...clarTo, c.child_run_id])} />{" "}
                      {c.display_name} asked: “{c.answer?.clarification_question}”
                    </label>
                  ))}
                  <p className="text-text-muted">
                    Your answer goes ONLY to the ticked investigations. Other models are not paused.
                  </p>
                  <div className="mt-1 flex gap-2">
                    <input value={clarText} onChange={(e) => setClarText(e.target.value)}
                      className="flex-1 rounded border border-border bg-surface p-1 text-text-primary"
                      aria-label="Clarification answer" />
                    <button type="button" disabled={!clarText.trim() || !clarTo.length}
                      className="rounded bg-accent px-2 py-1 text-accent-contrast disabled:opacity-50"
                      onClick={() => answerClarification(cmp.comparison_id, clarText, clarTo)
                        .then((c) => { setCmp(c); setClarText(""); setClarTo([]); })
                        .catch((e) => setError(errorText(e)))}>
                      Send
                    </button>
                  </div>
                </div>
              )}

              {ev && (
                <>
                  <section>
                    <h3 className="mb-1 text-sm font-semibold text-text-primary">Overview</h3>
                    <Overview ev={ev} blind={blind}
                      onSelect={(id) => setFocus({ child: id, stage: null })} />
                    <p className="mt-1 text-xs text-text-muted">
                      {String(ev.summary.note)}. Comparison elapsed:{" "}
                      {ev.comparison_elapsed_ms.value == null ? "unknown"
                        : `${Math.round(Number(ev.comparison_elapsed_ms.value))} ms (includes queueing)`}.
                    </p>
                  </section>
                  <section>
                    <h3 className="mb-1 text-sm font-semibold text-text-primary">Answers</h3>
                    <div className="mb-1 flex flex-wrap gap-2 text-xs">
                      {candidates.map((c, i) => (
                        <label key={c.child_run_id}>
                          <input type="checkbox" checked={pinned.includes(c.child_run_id)}
                            onChange={() => setPinned(pinned.includes(c.child_run_id)
                              ? pinned.filter((x) => x !== c.child_run_id)
                              : [...pinned, c.child_run_id].slice(-2))} />{" "}
                          {blind ? blindLabel(i + 1) : c.display_name}
                        </label>
                      ))}
                    </div>
                    <div className="flex flex-col gap-3 lg:flex-row">
                      {comparatorChild && (
                        <AnswerCard child={comparatorChild}
                          label={`${blind ? blindLabel(0) : comparatorChild.display_name} — comparator`} />
                      )}
                      {shown.map((c) => (
                        <AnswerCard key={c.child_run_id} child={c}
                          label={blind ? blindLabel(candidates.indexOf(c) + 1) : c.display_name} />
                      ))}
                    </div>
                  </section>
                  <section>
                    <h3 className="mb-1 text-sm font-semibold text-text-primary">Four stages</h3>
                    <StageMatrix ev={ev} blind={blind}
                      onOpen={(child, stage) => setFocus({ child, stage })} />
                  </section>
                  {focusChild && (
                    <div className="rounded border border-border-strong bg-surface-sunken p-3">
                      <button type="button" className="float-right text-xs text-text-secondary"
                        onClick={() => setFocus(null)}>Close</button>
                      <Evidence child={focusChild} stage={focus?.stage ?? null} ev={ev} onReview={onReview} />
                    </div>
                  )}
                </>
              )}
            </div>
          )}
        </div>
      )}
    </section>
  );
}
