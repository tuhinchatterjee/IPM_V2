"use client";

/**
 * The disclosure views for one settled (or running) comparison.
 *
 * Everything rendered here is model or evaluator output and is treated as
 * untrusted TEXT: React escapes it, nothing is injected as HTML, no link
 * from model content is made clickable. Every status carries a text label;
 * tone is an extra cue, never the only one.
 */

import * as React from "react";

import type { Call, Check, ChildEval, Claim, Evaluation, Metric } from "./client";
import {
  STAGES,
  STAGE_NAMES,
  blindLabel,
  formatMetric,
  formatRate,
  isMetric,
  metricHelp,
  shortId,
  statusLabel,
  statusTone,
} from "./format";

const TONE: Record<string, string> = {
  positive: "text-positive",
  negative: "text-negative",
  warning: "text-warning",
  muted: "text-text-muted",
};

export function Status({ value }: { value: string | null | undefined }) {
  const tone = statusTone(value);
  const glyph =
    tone === "positive" ? "✓" : tone === "negative" ? "✕" : tone === "warning" ? "!" : "·";
  return (
    <span className={`whitespace-nowrap font-medium ${TONE[tone]}`}>
      <span aria-hidden="true">{glyph} </span>
      {statusLabel(value)}
    </span>
  );
}

function MetricCell({ m }: { m: Metric | string | number | undefined }) {
  if (!isMetric(m)) return <span className="text-text-muted">unknown</span>;
  const help = metricHelp(m);
  return (
    <span title={help} tabIndex={0} aria-label={`${formatMetric(m)}. ${help}`}
      className="cursor-help underline decoration-dotted underline-offset-2">
      {formatMetric(m)}
    </span>
  );
}

function name(child: ChildEval, blind: boolean, index: number): string {
  if (blind) return blindLabel(index);
  return child.display_name + (child.fixture ? " [FIXTURE]" : "");
}

// ---- overview -------------------------------------------------------------

export function Overview({
  ev,
  blind,
  onSelect,
}: {
  ev: Evaluation;
  blind: boolean;
  onSelect: (childId: string) => void;
}) {
  const cols: [string, string][] = [
    ["service_ms", "End-to-end service"],
    ["queue_delay_ms", "Queue wait"],
    ["provider_call_ms", "Model-call time"],
    ["creditprobe_ms", "CreditProbe time"],
    ["input_tokens", "Input tokens"],
    ["output_tokens", "Output tokens"],
    ["cost_usd", "Cost"],
  ];
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs" aria-label="Overview, one row per model">
        <thead>
          <tr className="border-b border-border-strong text-left text-text-secondary">
            <th scope="col" className="p-2">Model</th>
            <th scope="col" className="p-2">Execution</th>
            <th scope="col" className="p-2">Identity</th>
            {cols.map(([k, label]) => (
              <th key={k} scope="col" className="p-2">{label}</th>
            ))}
            <th scope="col" className="p-2">Repairs</th>
            <th scope="col" className="p-2">Claims assessed</th>
            <th scope="col" className="p-2">First divergence</th>
          </tr>
        </thead>
        <tbody>
          {ev.children.map((c, i) => (
            <tr key={c.child_run_id} className="border-b border-border align-top">
              <th scope="row" className="p-2 text-left font-medium text-text-primary">
                <button type="button" className="text-left underline-offset-2 hover:underline"
                  onClick={() => onSelect(c.child_run_id)}>
                  {name(c, blind, i)}
                </button>
                {c.profile_id === ev.comparator.profile_id && (
                  <span className="ml-1 text-text-muted">(comparator)</span>
                )}
              </th>
              <td className="p-2">
                <Status value={c.execution_state} />
                {c.reason && <div className="text-text-muted">{c.reason}</div>}
              </td>
              <td className="p-2 text-text-secondary">
                {blind ? "hidden" : `${c.requested_model} · ${c.identity?.status ?? "UNAVAILABLE"}`}
              </td>
              {cols.map(([k]) => (
                <td key={k} className="p-2 text-text-secondary">
                  <MetricCell m={c.metrics?.[k] as Metric | undefined} />
                </td>
              ))}
              <td className="p-2 text-text-secondary">
                {c.repair.opportunities
                  ? `${c.repair.valid_repairs}/${c.repair.opportunities} valid`
                  : "no opportunity (not observed)"}
              </td>
              <td className="p-2 text-text-secondary">
                {formatRate(c.claim_rates?.assessment_coverage as { numerator: number; denominator: number })}
              </td>
              <td className="p-2 text-text-secondary">
                {c.first_divergence
                  ? `${c.first_divergence.stage}: ${c.first_divergence.summary} (${c.first_divergence.confidence})`
                  : "none observed"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---- four-stage matrix ----------------------------------------------------

export function StageMatrix({
  ev,
  blind,
  onOpen,
}: {
  ev: Evaluation;
  blind: boolean;
  onOpen: (childId: string, stage: string) => void;
}) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-xs" aria-label="Four-stage matrix">
        <thead>
          <tr className="border-b border-border-strong text-left text-text-secondary">
            <th scope="col" className="p-2">Stage</th>
            {ev.children.map((c, i) => (
              <th key={c.child_run_id} scope="col" className="p-2">{name(c, blind, i)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {STAGES.map((s) => (
            <tr key={s} className="border-b border-border align-top">
              <th scope="row" className="p-2 text-left text-text-primary">
                {s} · {STAGE_NAMES[s]}
              </th>
              {ev.children.map((c) => {
                const st = c.stages?.[s];
                return (
                  <td key={c.child_run_id} className="p-2">
                    <button type="button" className="text-left"
                      onClick={() => onOpen(c.child_run_id, s)}
                      aria-label={`${s} for ${c.display_name}: ${statusLabel(st?.status)}. Open evidence.`}>
                      <Status value={st?.status} />
                      <div className="text-text-muted">
                        {st?.checks?.length ?? 0} check(s) · {st?.calls?.length ?? 0} call(s)
                        {st?.shared_calls?.length ? ` · ${st.shared_calls.length} shared` : ""}
                        {` · confidence ${st?.evidence_confidence?.toLowerCase() ?? "low"}`}
                      </div>
                    </button>
                  </td>
                );
              })}
            </tr>
          ))}
          <tr className="align-top">
            <th scope="row" className="p-2 text-left text-text-primary">
              CreditProbe execution &amp; validation
            </th>
            {ev.children.map((c) => (
              <td key={c.child_run_id} className="p-2 text-text-secondary">
                <MetricCell m={c.metrics?.creditprobe_ms as Metric | undefined} />
                <div className="text-text-muted">{c.app_lane?.length ?? 0} application event(s)</div>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
      <p className="mt-2 text-xs text-text-muted">
        Stages are reporting groups over the real calls, not four API calls. A call serving two
        stages is shown once as a shared span; its time and tokens are never divided.
      </p>
    </div>
  );
}

// ---- answer comparison -----------------------------------------------------

export function AnswerCard({ child, label }: { child: ChildEval; label: string }) {
  const a = child.answer;
  return (
    <article className="min-w-0 flex-1 rounded-md border border-border bg-surface p-3"
      aria-label={`Answer from ${label}`}>
      <header className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
        <h4 className="text-sm font-semibold text-text-primary">{label}</h4>
        <Status value={child.execution_state} />
      </header>
      {child.fixture && (
        <p className="mb-2 text-xs text-warning">
          FIXTURE — a scripted demonstration through the real engine, not a model.
        </p>
      )}
      {!a && (
        <p className="text-xs text-text-muted">
          No answer. {child.reason || child.error_code || child.execution_state}
        </p>
      )}
      {a?.clarification_question && (
        <p className="mb-2 text-sm text-text-primary">
          <span className="font-medium">Asked the user:</span> {a.clarification_question}
        </p>
      )}
      {a?.narrative && (
        <p className="whitespace-pre-wrap text-sm text-text-primary">{a.narrative}</p>
      )}
      {(a?.tables ?? []).slice(0, 2).map((t, ti) => (
        <div key={ti} className="mt-2 overflow-x-auto">
          <div className="text-xs font-medium text-text-secondary">{t.title}</div>
          <table className="w-full border-collapse text-xs">
            <thead>
              <tr>
                {(t.columns ?? []).map((c) => (
                  <th key={c} scope="col" className="border-b border-border p-1 text-left text-text-secondary">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(t.rows ?? []).slice(0, 15).map((r, ri) => (
                <tr key={ri}>
                  {(t.columns ?? []).map((c) => (
                    <td key={c} className="border-b border-border p-1 text-text-primary">
                      {String(r.display?.[c] ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {(a?.limitations ?? []).length > 0 && (
        <ul className="mt-2 list-disc pl-4 text-xs text-text-secondary">
          {a!.limitations!.map((l, i) => <li key={i}>{l}</li>)}
        </ul>
      )}
      {child.failures.length > 0 && (
        <p className="mt-2 text-xs text-negative">
          {child.failures.length} diagnosed issue(s): {child.failures.map((f) => f.primary_category).join(", ")}
        </p>
      )}
    </article>
  );
}

// ---- drill-down -------------------------------------------------------------

function CallRow({ c }: { c: Call }) {
  return (
    <tr className="border-b border-border align-top">
      <td className="p-1 font-mono">{shortId(c.call_id)}</td>
      <td className="p-1">{c.seq}</td>
      <td className="p-1">{c.stage_tags.join("+")}</td>
      <td className="p-1">{c.purpose}</td>
      <td className="p-1" title={`tool names from: ${c.tool_names_source || "n/a"}`}>
        {c.tool_names.join(", ") ||
          (c.evidence_status === "EVIDENCE_INCOMPLETE" ? "(not recoverable — evidence incomplete)" : "(none)")}
        {c.tool_names_source === "frozen_call_report" && (
          <span className="text-text-muted"> · from frozen record</span>
        )}
        {c.tool_names_disagree && c.tool_names_disagree.length > 0 && (
          <span className="text-warning"> · sources disagree: {c.tool_names_disagree.join(", ")}</span>
        )}
      </td>
      <td className="p-1">{c.stop_reason}</td>
      <td className="p-1">{c.duration_ms == null ? "unknown" : `${c.duration_ms.toFixed(1)} ms`}</td>
      <td className="p-1" title={c.token_source}>
        {c.input_tokens ?? "unknown"} / {c.output_tokens ?? "unknown"} ({c.token_status.toLowerCase()})
      </td>
      <td className="p-1 text-negative">{c.errors_returned.join("; ") || c.protocol_flag}</td>
    </tr>
  );
}

function CheckRow({ c }: { c: Check }) {
  return (
    <li className="rounded border border-border p-2" id={`check-${c.check_id}`}>
      <div className="flex flex-wrap gap-2">
        <span className="font-mono">{c.check_id}</span>
        <Status value={c.outcome} />
        <span className="text-text-muted">{c.kind} · {c.severity} · {c.status}</span>
      </div>
      <div className="mt-1">Expected: {JSON.stringify(c.expected)}</div>
      <div>Actual: {JSON.stringify(c.actual)}</div>
      {c.tolerance ? <div>Tolerance: {JSON.stringify(c.tolerance)}</div> : null}
      <div className="text-text-muted">Truth source: {c.truth_source}</div>
      {c.evidence_ref && <div className="text-text-muted">Evidence: {JSON.stringify(c.evidence_ref)}</div>}
      {c.note && <div className="text-text-muted">{c.note}</div>}
      {c.review && <div className="text-accent">Reviewed: {c.review.decision} — {c.review.reason}</div>}
    </li>
  );
}

export function ClaimList({
  child,
  onReview,
}: {
  child: ChildEval;
  onReview: (target: string, decision: string) => void;
}) {
  const rates = child.claim_rates as Record<string, { numerator: number; denominator: number }>;
  return (
    <div>
      <p className="mb-2 text-xs text-text-secondary">
        Contradicted {formatRate(rates.contradicted_rate)} · Unsupported{" "}
        {formatRate(rates.unsupported_rate)} · Assessed/extracted{" "}
        {formatRate(rates.assessment_coverage)} · Required outputs{" "}
        {formatRate(rates.required_output_coverage)}
      </p>
      <ul className="space-y-2 text-xs">
        {child.claims.length === 0 && <li className="text-text-muted">No claims extracted.</li>}
        {child.claims.map((c: Claim) => (
          <li key={c.claim_id} className="rounded border border-border p-2">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono">{c.claim_id}</span>
              <Status value={c.verification_status} />
              <span className="text-text-muted">
                {c.claim_type} · extraction {c.extraction_confidence_class.toLowerCase()} ·{" "}
                {c.reviewer_status.toLowerCase()}
                {c.evidence_status === "EVIDENCE_INCOMPLETE" ? " · evidence incomplete (not assessed)" : ""}
              </span>
            </div>
            {c.frozen_validation && (
              <div className="text-text-secondary">
                Frozen Finalizer: {c.frozen_validation.status} — {c.frozen_validation.message}
              </div>
            )}
            <blockquote className="mt-1 text-text-primary">{c.extracted_text || "(structured claim)"}</blockquote>
            <div className="text-text-muted">{c.explanation}</div>
            {c.review && (
              <div className="text-accent">
                Reviewer: {c.review.decision} (automatic was {c.review.automatic_status}) — {c.review.reason}
              </div>
            )}
            <div className="mt-1 flex gap-2">
              <button type="button" className="rounded border border-border px-2 py-0.5"
                onClick={() => onReview(`${child.child_run_id}:${c.claim_id}`, "CONFIRM")}>
                Confirm
              </button>
              <button type="button" className="rounded border border-border px-2 py-0.5"
                onClick={() => onReview(`${child.child_run_id}:${c.claim_id}`, "OVERTURN_TO_SUPPORTED")}>
                Mark supported
              </button>
              <button type="button" className="rounded border border-border px-2 py-0.5"
                onClick={() => onReview(`${child.child_run_id}:${c.claim_id}`, "OVERTURN_TO_UNSUPPORTED")}>
                Mark unsupported
              </button>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function Evidence({
  child,
  stage,
  ev,
  onReview,
}: {
  child: ChildEval;
  stage: string | null;
  ev: Evaluation;
  onReview: (target: string, decision: string) => void;
}) {
  const calls = stage ? child.calls.filter((c) => c.stage_tags.includes(stage)) : child.calls;
  const checks = stage
    ? child.checks.filter((c) => c.stage.includes(stage))
    : child.checks;
  const match = child.opus_match;
  return (
    <section aria-label={`Evidence for ${child.display_name}`} className="space-y-4 text-xs">
      <h3 className="text-sm font-semibold text-text-primary">
        {child.display_name}
        {stage ? ` · ${stage} ${STAGE_NAMES[stage]}` : " · all evidence"}
      </h3>
      {stage && child.stages?.[stage]?.note && (
        <p className="text-text-secondary">{child.stages[stage].note}</p>
      )}
      <div>
        <h4 className="font-medium text-text-secondary">Calls ({calls.length})</h4>
        <div className="overflow-x-auto">
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-text-secondary">
                {["call", "#", "stages", "purpose", "tools", "stop", "time", "tokens in/out", "errors"].map((h) => (
                  <th key={h} scope="col" className="p-1">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>{calls.map((c) => <CallRow key={c.call_id} c={c} />)}</tbody>
          </table>
        </div>
      </div>
      <div>
        <h4 className="font-medium text-text-secondary">Checks ({checks.length})</h4>
        <ul className="space-y-2">
          {checks.length === 0 && <li className="text-text-muted">No check covers this. That is not a pass.</li>}
          {checks.map((c) => <CheckRow key={c.check_id} c={c} />)}
        </ul>
      </div>
      {(!stage || stage === "S3") && (
        <div>
          <h4 className="font-medium text-text-secondary">Repair chain</h4>
          <p>
            <Status value={child.repair.status} /> · opportunities {child.repair.opportunities} ·
            attempts {child.repair.attempts} · valid {child.repair.valid_repairs} · business-correct{" "}
            {child.repair.business_correct_recoveries ?? "unknown"}
          </p>
          {child.repair.note && <p className="text-text-muted">{child.repair.note}</p>}
          {child.repair.chains.map((r) => (
            <div key={r.call_id} className="mt-1 rounded border border-border p-2">
              <div>{r.error_code}: {r.feedback}</div>
              <div className="text-text-muted">Next: {r.revalidation}</div>
              {r.diff?.unified && (
                <pre className="mt-1 overflow-x-auto whitespace-pre bg-surface-sunken p-2 font-mono">{r.diff.unified}</pre>
              )}
            </div>
          ))}
        </div>
      )}
      {(!stage || stage === "S4") && (
        <div>
          <h4 className="font-medium text-text-secondary">Claim ledger</h4>
          <ClaimList child={child} onReview={onReview} />
        </div>
      )}
      <div>
        <h4 className="font-medium text-text-secondary">
          {ev.comparator.is_opus ? "Opus Match" : "Comparator Match"} vs verified correctness
        </h4>
        <p className="text-text-muted">{ev.comparator.note}. Status: {ev.comparator.status}.</p>
        {!match && <p className="text-text-muted">This is the comparator.</p>}
        {match && (
          <table className="w-full border-collapse">
            <thead>
              <tr className="text-left text-text-secondary">
                <th scope="col" className="p-1">Stage</th>
                <th scope="col" className="p-1">Agreement</th>
                <th scope="col" className="p-1">Verified</th>
                <th scope="col" className="p-1">Checks (weight)</th>
              </tr>
            </thead>
            <tbody>
              {STAGES.map((s) => (
                <tr key={s} className="border-b border-border align-top">
                  <th scope="row" className="p-1 text-left">{s}</th>
                  <td className="p-1">{match[s]?.display ?? "N/A"} {match[s]?.reason ? `(${match[s].reason})` : ""}</td>
                  <td className="p-1"><Status value={child.stages?.[s]?.status} /></td>
                  <td className="p-1">
                    {(match[s]?.checks ?? []).map((k) => (
                      <div key={k.check_id}>
                        {k.check_id} ({k.weight}): {k.agree === null ? "not assessed" : k.agree ? "agree" : "differ"} — {k.description}
                      </div>
                    ))}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div>
        <h4 className="font-medium text-text-secondary">Diagnosis</h4>
        {child.failures.length === 0 && <p className="text-text-muted">No failure diagnosed from the available checks.</p>}
        {child.failures.map((f, i) => (
          <div key={i} className="mt-1 rounded border border-border p-2">
            <div className="font-medium text-text-primary">{f.primary_category} · {f.severity}</div>
            <div>Symptom: {f.symptom}</div>
            <div>Failed requirement: {f.failed_requirement}</div>
            <div>Likely owner: {f.likely_owner} ({f.origin_confidence})</div>
            <div>Affected stages: {f.affected_stages.join(", ") || "none"}; inherited: {f.inherited_effects.join("; ") || "none"}</div>
            <div>Next diagnostic: {f.next_diagnostic}</div>
            <div>Intervention: {f.intervention_category}; approval: {f.approval_needed}</div>
          </div>
        ))}
      </div>
      <div>
        <h4 className="font-medium text-text-secondary">CreditProbe lane</h4>
        <ul>
          {child.app_lane.map((a, i) => (
            <li key={i}>
              {a.kind} · {a.status} · {a.duration_ms.toFixed(0)} ms · {a.message}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
