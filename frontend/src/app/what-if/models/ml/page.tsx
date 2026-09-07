"use client";

/**
 * ML Model — XGBoost. The configuration, the evidence, and the retraining.
 *
 * This page ships with a trained model rather than an invitation to train one.
 * A configuration screen whose only content is "train your first model" tells
 * a reviewer nothing about whether the methodology is any good.
 *
 * The limitations are shown at the TOP, not buried at the bottom. On this book
 * the reported ECL is close to a closed form, so R-squared is very high for
 * mechanical reasons — and a reader who takes 0.998 at face value has been
 * misled by the screen rather than by the model.
 */

import * as React from "react";

import { CategoryBarChart, ScatterPlot } from "@/components/analytics/charts";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import { Unavailable } from "@/components/ui/unavailable";
import { Composer, Figure, count, pct } from "@/components/whatif/parts";
import type { WhatIfExample, WhatIfMlExplain, WhatIfTrainResult } from "@/lib/api";
import { ApiError, api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/** The Client X example the product asks for, at the values it specifies. */
const CLIENT_X: Record<string, unknown> = {
  borrower: "Client X",
  stage: 1,
  ead: 100_000_000,
  drawn_exposure: 100_000_000,
  undrawn_commitment: 0,
  pd_12m: 2.5,
  pd_lifetime: 8.0,
  pd_at_origination_pct: 1.2,
  lgd: 35,
  ccf: 0.5,
  collateral_market_value: 40_000_000,
  collateral_coverage_pct: 40,
  secured_exposure: 40_000_000,
  internal_rating_numeric: 8,
  current_dpd: 0,
  sector: "Contracting",
  segment: "Corporate",
  final_ecl: 1_800_000,
};

function metric(body: Record<string, number | null> | undefined, key: string, digits = 5) {
  const value = body?.[key];
  return value === null || value === undefined ? "—" : Number(value).toFixed(digits);
}

export default function MlModelPage() {
  const model = useAsync(() => api.whatIfMlModel(), []);
  const [tab, setTab] = React.useState("card");
  const [explain, setExplain] = React.useState<WhatIfMlExplain | null>(null);
  const [example, setExample] = React.useState<WhatIfExample | null>(null);
  const [trained, setTrained] = React.useState<WhatIfTrainResult | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [instruction, setInstruction] = React.useState("");
  const data = model.data;
  const card = data?.active ?? null;

  React.useEffect(() => {
    if (!card || explain) return;
    let cancelled = false;
    (async () => {
      try {
        const body = await api.whatIfMlExplain(card.version);
        if (!cancelled) setExplain(body);
      } catch (e) {
        if (!cancelled) setError(e instanceof ApiError ? e.message : String(e));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [card, explain]);

  const runExample = async () => {
    setBusy(true);
    setError("");
    try {
      setExample(await api.whatIfMlExample(CLIENT_X));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const retrain = async () => {
    setBusy(true);
    setError("");
    try {
      const body = await api.whatIfMlTrain({
        instruction,
        reason: instruction || "Retrained from the ML configuration page",
      });
      setTrained(body);
      model.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const activate = async (version: string) => {
    setBusy(true);
    try {
      await api.whatIfMlActivate(version, "Activated from the ML configuration page");
      setTrained(null);
      setExplain(null);
      model.reload();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="What-If Analysis"
        title="ML Model — XGBoost"
        description="A nonlinear response learned from historical Corporate IFRS 9 outcomes, anchored so the official baseline ECL remains the truth."
      />
      <Unavailable state={model} what="the ML model configuration" />

      {error ? (
        <div className="rounded-md border border-negative/40 bg-negative-muted px-3 py-2 text-[12px]">
          {error}
        </div>
      ) : null}

      {data && !data.has_active ? (
        <Card>
          <CardContent className="py-6 text-[13px] text-text-secondary">
            No model has been trained yet. Train one below; until then, What-If runs on
            the Delta Model.
          </CardContent>
        </Card>
      ) : null}

      {card ? (
        <>
          <Card className="border-warning/40">
            <CardHeader>
              <CardTitle className="text-[14px]">Read these first</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-2">
                {card.limitations.map((limitation) => (
                  <li key={limitation} className="text-[12px] text-text-secondary">
                    • {limitation}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>

          <div className="flex flex-wrap items-center gap-3">
            <Badge variant="positive" data-testid="active-model">
              Active v{card.version}
            </Badge>
            <span className="text-[12px] text-text-muted">
              Built {card.built_at} · {card.artifact_format} ·{" "}
              {(card.artifact_bytes / 1024).toFixed(0)} KB · sha256{" "}
              {card.artifact_sha256.slice(0, 12)}…
            </span>
          </div>

          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: "card", label: "Model card" },
              { id: "explain", label: "Explainability" },
              { id: "example", label: "Worked example" },
              { id: "retrain", label: "Retrain" },
            ]}
          />

          {tab === "card" ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">Validation</CardTitle>
                </CardHeader>
                <CardContent className="space-y-4">
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <Figure label="R² (validation)" value={metric(card.validation, "r2")} />
                    <Figure label="MAE" value={metric(card.validation, "mae", 6)} />
                    <Figure label="RMSE" value={metric(card.validation, "rmse", 6)} />
                    <Figure
                      label="WAPE"
                      value={pct(card.validation.wape as number, 2)}
                    />
                  </div>
                  <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                    <Figure
                      label="R² (out-of-time)"
                      value={metric(card.out_of_time, "r2")}
                      tone="whatif"
                    />
                    <Figure label="OOT MAE" value={metric(card.out_of_time, "mae", 6)} />
                    <Figure label="OOT RMSE" value={metric(card.out_of_time, "rmse", 6)} />
                    <Figure
                      label="OOT WAPE"
                      value={pct(card.out_of_time.wape as number, 2)}
                      tone="whatif"
                    />
                  </div>
                  <p className="text-[11px] text-text-muted">
                    Accuracy is a classification word and is deliberately not shown. This
                    model predicts a rate.
                  </p>
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">How it was built</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2 text-[12px] text-text-secondary">
                  <div>
                    <span className="text-text-muted">Algorithm: </span>
                    {card.algorithm}
                  </div>
                  <div>
                    <span className="text-text-muted">Target: </span>
                    {card.target_definition}
                  </div>
                  <div>
                    <span className="text-text-muted">Features: </span>
                    {card.feature_count} structural features, no client identifiers
                  </div>
                  <div>
                    <span className="text-text-muted">Training: </span>
                    {card.split.train.join(", ")} ({count(card.rows.train)} rows)
                  </div>
                  <div>
                    <span className="text-text-muted">Validation: </span>
                    {card.split.validation.join(", ")} ({count(card.rows.validation)} rows)
                  </div>
                  <div>
                    <span className="text-text-muted">Out-of-time (locked): </span>
                    {card.split.out_of_time.join(", ")} ({count(card.rows.out_of_time)} rows)
                  </div>
                  <div>
                    <span className="text-text-muted">Split: </span>
                    {card.split.by} — {card.split.why}
                  </div>
                  <div>
                    <span className="text-text-muted">Seed: </span>
                    {card.seed}
                  </div>
                </CardContent>
              </Card>

              {card.slices?.stage?.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-[14px]">Error by Stage</CardTitle>
                  </CardHeader>
                  <CardContent className="overflow-x-auto">
                    <table className="w-full text-[12px]">
                      <thead>
                        <tr className="text-left text-text-muted">
                          <th className="py-1">Slice</th>
                          <th className="text-right">Rows</th>
                          <th className="text-right">R²</th>
                          <th className="text-right">WAPE</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(["stage", "out_of_time_stage", "pd_band", "lgd_band",
                           "period"] as const).flatMap(
                          (key) =>
                            (card.slices[key] ?? []).map((row) => (
                              <tr key={`${key}-${row.label}`} className="border-t border-border">
                                <td className="py-1">
                                  <span className="text-text-muted">{key}</span> {row.label}
                                </td>
                                <td className="text-right tabular-nums">{count(row.count)}</td>
                                <td className="text-right tabular-nums">
                                  {row.r2 === null ? "—" : row.r2.toFixed(4)}
                                </td>
                                <td className="text-right tabular-nums">
                                  {row.wape === null ? "—" : `${row.wape.toFixed(2)}%`}
                                </td>
                              </tr>
                            )),
                        )}
                      </tbody>
                    </table>
                  </CardContent>
                </Card>
              ) : null}

              {card.stage_study?.available ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-[14px]">
                      Stage-aware: one model, or one per Stage?
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-3" data-testid="stage-study">
                    <p className="text-[12px] text-text-secondary">
                      <strong>{card.stage_study.chosen}</strong> Both designs were
                      fitted and scored out of time on this training run, so this is
                      what the numbers chose rather than what was preferred.
                    </p>
                    {(card.stage_study.because ?? []).map((line) => (
                      <p key={line} className="text-[12px] text-text-secondary">
                        {line}
                      </p>
                    ))}
                    {card.stage_study.boundary?.available ? (
                      <div className="grid grid-cols-3 gap-3" data-testid="stage-boundary">
                        <Figure
                          label="Governed Stage 1 → 2 step"
                          value={`${card.stage_study.boundary.governed_step.toFixed(2)}x`}
                        />
                        <Figure
                          label="This model"
                          value={`${card.stage_study.boundary.champion_step.toFixed(2)}x`}
                          tone="whatif"
                        />
                        <Figure
                          label="Separate models"
                          value={
                            card.stage_study.boundary.challenger_step === undefined
                              ? "—"
                              : `${card.stage_study.boundary.challenger_step.toFixed(2)}x`
                          }
                        />
                      </div>
                    ) : null}
                    <div className="overflow-x-auto">
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr className="text-left text-text-muted">
                            <th className="py-1">Stage</th>
                            <th className="text-right">OOT rows</th>
                            <th className="text-right">Share of ECL</th>
                            <th className="text-right">This model R²</th>
                            <th className="text-right">Separate model R²</th>
                          </tr>
                        </thead>
                        <tbody>
                          {["1", "2", "3"].map((stage) => {
                            const mine = card.stage_study!.champion_by_stage?.[stage];
                            const theirs = card.stage_study!.challenger_by_stage?.[stage];
                            if (!mine) return null;
                            const totalEcl = ["1", "2", "3"].reduce(
                              (sum, k) =>
                                sum + (card.stage_study!.champion_by_stage?.[k]?.ecl ?? 0),
                              0,
                            );
                            return (
                              <tr key={stage} className="border-t border-border">
                                <td className="py-1">Stage {stage}</td>
                                <td className="text-right tabular-nums">{count(mine.rows)}</td>
                                <td className="text-right tabular-nums">
                                  {totalEcl ? pct((mine.ecl / totalEcl) * 100, 1) : "—"}
                                </td>
                                <td className="text-right tabular-nums">
                                  {mine.champion?.r2 === undefined
                                    ? "—"
                                    : mine.champion.r2.toFixed(4)}
                                </td>
                                <td className="text-right tabular-nums">
                                  {theirs?.fitted && theirs.r2 !== undefined
                                    ? theirs.r2.toFixed(4)
                                    : theirs?.why ?? "—"}
                                </td>
                              </tr>
                            );
                          })}
                        </tbody>
                      </table>
                    </div>
                  </CardContent>
                </Card>
              ) : null}
            </div>
          ) : null}

          {tab === "explain" && explain ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">Top predictors of the ECL rate</CardTitle>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    {explain.shap?.method} on {count(explain.shap?.rows_sampled ?? 0)} rows.{" "}
                    {explain.shap?.note}
                  </p>
                </CardHeader>
                <CardContent>
                  <CategoryBarChart
                    data={(explain.shap?.features ?? []).slice(0, 12).map((f) => ({
                      label: f.feature,
                      value: f.share_pct,
                    }))}
                    xKey="label"
                    series={[{ key: "value", label: "Share of |SHAP| (%)", slot: 0 }]}
                    height={320}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">XGBoost gain importance</CardTitle>
                </CardHeader>
                <CardContent>
                  <CategoryBarChart
                    data={explain.importance.slice(0, 12).map((f) => ({
                      label: f.feature,
                      value: f.share_pct,
                    }))}
                    xKey="label"
                    series={[{ key: "value", label: "Share of gain (%)", slot: 1 }]}
                    height={320}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">Actual against predicted</CardTitle>
                </CardHeader>
                <CardContent>
                  <ScatterPlot
                    data={explain.actual_vs_predicted.map((b) => ({
                      x: b.mean_predicted,
                      y: b.mean_actual,
                      label: `bucket ${b.bucket}`,
                    }))}
                    xKey="x"
                    yKey="y"
                    height={300}
                  />
                </CardContent>
              </Card>

              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">Sensitivity</CardTitle>
                  <p className="mt-0.5 text-[11px] text-text-muted">
                    What the model itself says happens when one feature is scaled.
                  </p>
                </CardHeader>
                <CardContent className="space-y-3">
                  {Object.entries(explain.sensitivity).map(([name, body]) => (
                    <div key={name} data-sensitivity={name}>
                      <div className="text-[12px] font-medium text-text-primary">{name}</div>
                      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-text-secondary">
                        {body.points.map((p) => (
                          <span key={p.multiplier} className="tabular-nums">
                            ×{p.multiplier} →{" "}
                            {p.relative_to_base === null
                              ? "—"
                              : `${p.relative_to_base.toFixed(3)}×`}
                          </span>
                        ))}
                      </div>
                      <p className="mt-0.5 text-[10px] text-text-muted">{body.note}</p>
                    </div>
                  ))}
                </CardContent>
              </Card>

              {explain.stage_interaction?.stages?.length ? (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-[14px]">
                      Stage interaction — the same shock, inside each Stage
                    </CardTitle>
                    <p className="mt-0.5 text-[11px] text-text-muted">
                      A single model is only stage-aware if the Stage changes how it
                      reads everything else. This shocks {explain.stage_interaction.feature}{" "}
                      within each Stage, so nothing here is a migration effect.
                    </p>
                  </CardHeader>
                  <CardContent className="space-y-3" data-testid="stage-interaction">
                    {explain.stage_interaction.stages.map((entry) => (
                      <div key={entry.stage} data-stage-response={entry.stage}>
                        <div className="text-[12px] font-medium text-text-primary">
                          Stage {entry.stage}{" "}
                          <span className="text-[11px] text-text-muted">
                            ({count(entry.rows)} rows)
                          </span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-text-secondary">
                          {entry.points.map((p) => (
                            <span key={p.multiplier} className="tabular-nums">
                              ×{p.multiplier} →{" "}
                              {p.relative_to_base === null
                                ? "—"
                                : `${p.relative_to_base.toFixed(3)}×`}
                            </span>
                          ))}
                        </div>
                      </div>
                    ))}
                    {explain.stage_interaction.finding ? (
                      <p className="text-[12px] text-text-secondary">
                        {explain.stage_interaction.finding}
                      </p>
                    ) : null}
                    <p className="text-[10px] text-text-muted">
                      {explain.stage_interaction.note}
                    </p>
                  </CardContent>
                </Card>
              ) : null}
            </div>
          ) : null}

          {tab === "example" ? (
            <Card>
              <CardHeader>
                <CardTitle className="text-[14px]">Client X</CardTitle>
                <p className="mt-0.5 text-[11px] text-text-muted">
                  Stage 1 · SAR 100m exposure · 12m PD 2.50% · lifetime PD 8.00% · LGD 35% ·
                  CCF 50% · collateral SAR 40m · official ECL SAR 1.80m. The shock is 12m PD
                  +20%, taking it to 3.00%.
                </p>
              </CardHeader>
              <CardContent className="space-y-4">
                <Button onClick={() => void runExample()} disabled={busy} size="sm">
                  {busy ? "Scoring…" : "Score Client X with the active model"}
                </Button>
                {example ? (
                  <div className="space-y-4" data-testid="client-x-result">
                    <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                      <Figure
                        label="Baseline model rate"
                        value={example.predicted_rate.toFixed(6)}
                      />
                      <Figure label="Official baseline ECL" value="SAR 1.80m" tone="baseline" />
                      <Figure label="Model version" value={example.model_version} />
                      <Figure
                        label="Base value"
                        value={example.explanation.base_value.toFixed(6)}
                      />
                    </div>
                    <div>
                      <div className="text-[12px] font-medium text-text-primary">
                        Why the model said that
                      </div>
                      <table className="mt-1 w-full text-[11px]">
                        <thead>
                          <tr className="text-left text-text-muted">
                            <th className="py-1">Feature</th>
                            <th className="text-right">Value</th>
                            <th className="text-right">SHAP</th>
                          </tr>
                        </thead>
                        <tbody>
                          {example.explanation.contributions.slice(0, 10).map((c) => (
                            <tr key={c.feature} className="border-t border-border">
                              <td className="py-1">{c.feature}</td>
                              <td className="text-right tabular-nums">{c.value}</td>
                              <td
                                className={`text-right tabular-nums ${
                                  c.shap >= 0 ? "text-negative" : "text-positive"
                                }`}
                              >
                                {c.shap.toFixed(6)}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                      <p className="mt-2 text-[11px] text-text-muted">
                        {example.explanation.note}
                      </p>
                    </div>
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {tab === "retrain" ? (
            <div className="space-y-4">
              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">{data?.retrain_prompt}</CardTitle>
                </CardHeader>
                <CardContent className="space-y-3">
                  <Composer
                    value={instruction}
                    onChange={setInstruction}
                    onSubmit={() => void retrain()}
                    busy={busy}
                    placeholder="Describe the training periods — or just press Retrain."
                    suggestions={[
                      "Keep everything through Q4 2025 and keep Q1 and Q2 2026 as out-of-time.",
                      "Remove the earliest four quarters.",
                    ]}
                  />
                  <div className="flex gap-2">
                    <Button onClick={() => void retrain()} disabled={busy} size="sm">
                      {busy ? "Training…" : "Retrain"}
                    </Button>
                    <Button variant="outline" size="sm" onClick={() => setInstruction("")}>
                      Not now
                    </Button>
                  </div>
                  <p className="text-[11px] text-text-muted">
                    A retrained model arrives as a CANDIDATE. The active model keeps
                    answering until you activate the new one, and every previous version
                    is kept.
                  </p>
                </CardContent>
              </Card>

              {trained ? (
                <Card data-testid="candidate">
                  <CardHeader>
                    <CardTitle className="text-[14px]">
                      Candidate v{trained.candidate.version}
                    </CardTitle>
                    <p className="mt-0.5 text-[11px] text-text-muted">{trained.message}</p>
                  </CardHeader>
                  <CardContent className="space-y-3">
                    {trained.comparison ? (
                      <table className="w-full text-[12px]">
                        <thead>
                          <tr className="text-left text-text-muted">
                            <th className="py-1">Metric</th>
                            <th className="text-right">Active</th>
                            <th className="text-right">Candidate</th>
                          </tr>
                        </thead>
                        <tbody>
                          {trained.comparison.rows.map((row) => (
                            <tr key={row.metric} className="border-t border-border">
                              <td className="py-1">{row.metric}</td>
                              <td className="text-right tabular-nums">
                                {row.left === null ? "—" : row.left}
                              </td>
                              <td
                                className={`text-right tabular-nums ${
                                  row.right_better === true
                                    ? "text-positive"
                                    : row.right_better === false
                                      ? "text-negative"
                                      : ""
                                }`}
                              >
                                {row.right === null ? "—" : row.right}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    ) : null}
                    <p className="text-[11px] text-text-muted">
                      {trained.comparison?.note}
                    </p>
                    <Button
                      size="sm"
                      onClick={() => void activate(trained.candidate.version)}
                      disabled={busy}
                    >
                      Activate model
                    </Button>
                  </CardContent>
                </Card>
              ) : null}

              <Card>
                <CardHeader>
                  <CardTitle className="text-[14px]">Versions</CardTitle>
                </CardHeader>
                <CardContent className="overflow-x-auto">
                  <table className="w-full text-[12px]">
                    <thead>
                      <tr className="text-left text-text-muted">
                        <th className="py-1">Version</th>
                        <th>State</th>
                        <th>Built</th>
                        <th>Predecessor</th>
                        <th className="text-right">Validation R²</th>
                        <th className="text-right">OOT R²</th>
                        <th />
                      </tr>
                    </thead>
                    <tbody>
                      {(data?.versions ?? []).map((version) => (
                        <tr key={version.version} className="border-t border-border">
                          <td className="py-1 font-medium">{version.version}</td>
                          <td>
                            <Badge
                              variant={version.state === "ACTIVE" ? "positive" : "outline"}
                            >
                              {version.state}
                            </Badge>
                          </td>
                          <td>{version.built_at}</td>
                          <td>{version.predecessor || "—"}</td>
                          <td className="text-right tabular-nums">
                            {metric(version.validation, "r2")}
                          </td>
                          <td className="text-right tabular-nums">
                            {metric(version.out_of_time, "r2")}
                          </td>
                          <td className="text-right">
                            {version.state !== "ACTIVE" ? (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => void activate(version.version)}
                                disabled={busy}
                              >
                                Activate
                              </Button>
                            ) : null}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>
            </div>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
