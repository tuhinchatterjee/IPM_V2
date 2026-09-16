"use client";

/**
 * The retail What-If challenger, with somewhere to read it. §10.2.
 *
 * What was here before
 * ---------------------
 * Nothing. The challenger ran on every scenario that asked for it and had no
 * page, no version anybody could quote and no artifact anybody could open.
 *
 * Where this is mounted, and where it is not
 * -------------------------------------------
 * `/what-if/methods/xgboost`, in the retail namespace. NOT
 * `/what-if/models/ml`, which is a corporate route reading the corporate
 * registry and is retired in a retail installation. It was briefly mounted
 * there, which turned a corporate route into a retail one and broke the
 * boundary `TestTheCorporateWhatIfRoutesDoNotServeTheirScreen` holds.
 *
 * Why the honesty note is at the top
 * -----------------------------------
 * The held-back R² is 0.98 and the training R² is 0.9998. Both are real and
 * neither means the model is good: recorded expected credit loss on this book
 * is close to a closed form of the parameters the challenger is fitted on, so
 * a gradient-boosted tree recovers it almost exactly. A reader who takes 0.98
 * at face value has been misled by the screen rather than by the model, so
 * the screen says it first rather than in a footnote.
 */

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { Tabs } from "@/components/ui/tabs";
import { api } from "@/lib/api";
import type {
  ChallengerExample,
  ChallengerModel,
  ChallengerParity,
} from "@/lib/api";

const TABS = [
  { id: "card", label: "Model card" },
  { id: "features", label: "Features" },
  { id: "performance", label: "Performance" },
  { id: "artifact", label: "Artifact" },
  { id: "example", label: "Worked example" },
  { id: "rebuild", label: "Rebuild" },
];

const SAR = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const FINE = new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 });

function Stat({ label, value, note }: {
  label: string; value: React.ReactNode; note?: string;
}) {
  return (
    <div>
      <p className="text-[10px] uppercase tracking-[0.14em] text-text-muted">
        {label}
      </p>
      <p className="mt-0.5 text-[15px] tabular-nums text-text">{value}</p>
      {note && <p className="mt-0.5 text-[10.5px] text-text-muted">{note}</p>}
    </div>
  );
}

export function RetailChallengerPage() {
  const [model, setModel] = React.useState<ChallengerModel | null>(null);
  const [failed, setFailed] = React.useState("");
  const [tab, setTab] = React.useState("card");
  const [parity, setParity] = React.useState<ChallengerParity | null>(null);
  const [example, setExample] = React.useState<ChallengerExample | null>(null);
  const [busy, setBusy] = React.useState("");
  const [said, setSaid] = React.useState("");

  const read = React.useCallback(() => {
    api.retailChallenger().then(setModel,
      (problem: Error) => setFailed(problem.message));
  }, []);
  React.useEffect(read, [read]);

  React.useEffect(() => {
    if (tab === "artifact" && !parity && model?.has_artifact) {
      setBusy("parity");
      api.retailChallengerParity().then(
        (got) => { setParity(got); setBusy(""); },
        (problem: Error) => { setFailed(problem.message); setBusy(""); });
    }
    if (tab === "example" && !example && model?.has_artifact) {
      setBusy("example");
      api.retailChallengerExample(8).then(
        (got) => { setExample(got); setBusy(""); },
        (problem: Error) => { setFailed(problem.message); setBusy(""); });
    }
  }, [tab, parity, example, model]);

  if (failed) {
    return (
      <Card className="border-negative/40 p-4 text-[12px] text-negative"
            data-testid="challenger-failed">
        {failed}
      </Card>
    );
  }
  if (!model) return <Skeleton className="h-64 w-full" />;

  const card = model.card;

  return (
    <div className="space-y-4" data-testid="challenger-page">
      {/* The limitation first, not in a footnote. */}
      <Card className="border-warning/40 bg-warning-muted/20 p-3.5">
        <p className="text-[12px] leading-relaxed text-text">
          <strong>Read the R² with care.</strong> Recorded expected credit loss
          on this book is close to a closed form of the parameters below, so a
          gradient-boosted tree recovers it almost exactly. A high score here
          says the challenger has learned the IFRS 9 identity, not that it has
          learned anything about credit. It is a second route to the same
          number, and the Delta method is the calculation of record.
        </p>
      </Card>

      <div className="flex flex-wrap items-center gap-2">
        <Badge variant={model.has_artifact ? "positive" : "warning"}
               data-testid="challenger-artifact-state">
          {model.has_artifact
            ? (model.stale ? "artifact stored, book has moved" : "artifact stored")
            : "no artifact yet"}
        </Badge>
        {card && (
          <span className="text-[11px] text-text-muted">
            {card.version} · {card.library} · fitted on the book at{" "}
            <code data-testid="challenger-month">{card.month}</code>
          </span>
        )}
      </div>
      {model.because && (
        <p className="text-[11.5px] text-text-muted">{model.because}</p>
      )}

      <Tabs active={tab} onChange={setTab} tabs={TABS} />

      {tab === "card" && (
        <Card>
          <CardHeader><CardTitle className="text-[14px]">What this model is</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <p className="text-[12px] leading-relaxed text-text">{model.what}</p>
            <p className="text-[12px] leading-relaxed text-text-muted">
              {model.authority}
            </p>
            {card && (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                <Stat label="Version" value={card.version} />
                <Stat label="Library" value={card.library.split(" —")[0]} />
                <Stat label="Target" value={card.target} />
                <Stat label="Month" value={card.month} />
                <Stat label="Fitted on" value={SAR.format(card.rows_fitted)}
                      note="facilities" />
                <Stat label="Held back" value={SAR.format(card.rows_held_back)}
                      note="never seen in training" />
                <Stat label="Fit time" value={`${FINE.format(card.seconds)} s`} />
                <Stat label="Built" value={card.built_at.replace("T", " ").replace("Z", "")} />
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {tab === "features" && card && (
        <Card>
          <CardHeader><CardTitle className="text-[14px]">
            What it was allowed to learn from
          </CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-[11.5px] leading-relaxed text-text-muted">
              The IFRS 9 inputs and nothing else. A model that reached for a
              customer identifier or a product label would fit the book&rsquo;s
              labels rather than its credit relationships, and would then be
              unable to say anything about a shock to a parameter.
            </p>
            <table className="w-full text-[12px]" data-testid="challenger-features">
              <thead>
                <tr className="border-b border-border text-left text-[10px] uppercase tracking-[0.12em] text-text-muted">
                  <th className="py-1.5">Parameter</th>
                  <th className="py-1.5 text-right">Share of the fit</th>
                </tr>
              </thead>
              <tbody>
                {card.importance.map((one) => (
                  <tr key={one.feature} className="border-b border-border/50">
                    <td className="py-1.5 text-text">{one.feature}</td>
                    <td className="py-1.5 text-right tabular-nums text-text">
                      {(one.share * 100).toFixed(1)}%
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {tab === "performance" && card && (
        <Card>
          <CardHeader><CardTitle className="text-[14px]">
            Measured on rows it never saw
          </CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="R² (held back)"
                    value={(card.metrics.r2 ?? 0).toFixed(4)} />
              <Stat label="WAPE (held back)"
                    value={`${((card.metrics.wape ?? 0) * 100).toFixed(2)}%`} />
              <Stat label="MAE (held back)"
                    value={`${FINE.format(card.metrics.mae ?? 0)} SAR`} />
              <Stat label="RMSE (held back)"
                    value={`${FINE.format(card.metrics.rmse ?? 0)} SAR`} />
            </div>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 opacity-70">
              <Stat label="R² (training)"
                    value={(card.training_metrics.r2 ?? 0).toFixed(4)} />
              <Stat label="WAPE (training)"
                    value={`${((card.training_metrics.wape ?? 0) * 100).toFixed(2)}%`} />
              <Stat label="MAE (training)"
                    value={`${FINE.format(card.training_metrics.mae ?? 0)} SAR`} />
              <Stat label="RMSE (training)"
                    value={`${FINE.format(card.training_metrics.rmse ?? 0)} SAR`} />
            </div>
            <p className="text-[11.5px] leading-relaxed text-text-muted">
              Both sets are shown because the gap between them is the thing
              worth looking at. WAPE rather than MAPE: expected credit loss is
              near zero on most facilities and exactly zero on some, so a
              per-row percentage divides by something arbitrarily small and
              reports a number in the thousands for a model that is fine.
            </p>
          </CardContent>
        </Card>
      )}

      {tab === "artifact" && (
        <Card>
          <CardHeader><CardTitle className="text-[14px]">
            The stored file, and whether it is the model
          </CardTitle></CardHeader>
          <CardContent className="space-y-4">
            {card && (
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                <Stat label="Fitted from book"
                      value={<code>{card.source_hash.slice(0, 16)}</code>} />
                <Stat label="Still the published book"
                      value={model.stale ? "no" : "yes"}
                      note={model.stale
                        ? "it will be refitted on the next scenario"
                        : "the artifact is current"} />
                <Stat label="Features stored" value={card.features.length} />
              </div>
            )}
            {busy === "parity" && <Skeleton className="h-20 w-full" />}
            {parity && (
              <div className="space-y-2" data-testid="challenger-parity">
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
                  <Stat label="Facilities scored both ways"
                        value={SAR.format(parity.rows)} />
                  <Stat label="Largest disagreement"
                        value={`${parity.largest_row_disagreement_sar} SAR`} />
                  <Stat label="Total disagreement"
                        value={`${parity.total_disagreement_sar} SAR`} />
                </div>
                <p className="text-[12px] leading-relaxed text-text">
                  {parity.says}
                </p>
                <p className="text-[11px] text-text-muted">
                  Save/load parity is run here, not asserted: the artifact is
                  fitted, saved, loaded back and scored against the same rows
                  through both. An artifact that scores differently from the
                  model that produced it is not that model.
                </p>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {tab === "example" && (
        <Card>
          <CardHeader><CardTitle className="text-[14px]">
            Real facilities, scored
          </CardTitle></CardHeader>
          <CardContent className="space-y-3">
            {busy === "example" && <Skeleton className="h-40 w-full" />}
            {example && (
              <>
                <p className="text-[11.5px] leading-relaxed text-text-muted">
                  {example.says}
                </p>
                <table className="w-full text-[12px]" data-testid="challenger-example">
                  <thead>
                    <tr className="border-b border-border text-left text-[10px] uppercase tracking-[0.12em] text-text-muted">
                      <th className="py-1.5">Facility</th>
                      <th className="py-1.5">Product</th>
                      <th className="py-1.5 text-right">Stage</th>
                      <th className="py-1.5 text-right">Recorded ECL</th>
                      <th className="py-1.5 text-right">Challenger</th>
                      <th className="py-1.5 text-right">Difference</th>
                    </tr>
                  </thead>
                  <tbody>
                    {example.rows.map((one) => (
                      <tr key={one.facility_id} className="border-b border-border/50">
                        <td className="py-1.5 text-text">{one.facility_id}</td>
                        <td className="py-1.5 text-text-muted">{one.product}</td>
                        <td className="py-1.5 text-right tabular-nums text-text-muted">
                          {one.stage ?? "—"}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-text">
                          {SAR.format(one.recorded_ecl_sar)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-text">
                          {SAR.format(one.challenger_ecl_sar)}
                        </td>
                        <td className="py-1.5 text-right tabular-nums text-text-muted">
                          {one.difference_sar > 0 ? "+" : ""}
                          {SAR.format(one.difference_sar)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </>
            )}
          </CardContent>
        </Card>
      )}

      {tab === "rebuild" && (
        <Card>
          <CardHeader><CardTitle className="text-[14px]">
            Refit on the published book
          </CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-[12px] leading-relaxed text-text-muted">
              A refit replaces the stored artifact. It is not needed while the
              book is unchanged &mdash; the challenger is stamped with the
              book it was fitted from and refits itself when that stamp stops
              matching.
            </p>
            <Button
              data-testid="challenger-rebuild"
              disabled={busy === "rebuild"}
              onClick={() => {
                setBusy("rebuild");
                setSaid("");
                api.retailChallengerRebuild().then(
                  (got) => {
                    setSaid(got.says);
                    setBusy("");
                    setParity(null);
                    setExample(null);
                    read();
                  },
                  (problem: Error) => { setFailed(problem.message); setBusy(""); });
              }}
            >
              {busy === "rebuild" ? "Refitting…" : "Refit the challenger"}
            </Button>
            {said && (
              <p className="text-[12px] text-text" data-testid="challenger-rebuilt">
                {said}
              </p>
            )}
          </CardContent>
        </Card>
      )}

      {model.disclosure && (
        <p className="text-[10.5px] text-text-muted">{model.disclosure}</p>
      )}
    </div>
  );
}
