"use client";

/**
 * What-If Analysis, on the retail book.
 *
 * One screen, and the composer is the way in. A person types a change in
 * words — "increase PD by 20% for personal finance" — and gets the baseline,
 * the scenario, the movement between them, what moved it, and the assumptions
 * and limits that go with it.
 *
 * Three promises, kept here and in the engine behind it:
 *
 * **A unit is never guessed.** "Increase PD by 2" is answered with a question,
 * because two percent of the PD and two percentage points added to it are
 * different scenarios. Both readings are offered as buttons that run exactly
 * what they say.
 *
 * **An instruction is never dropped.** A sentence asking for something this
 * engine does not implement is refused with the list of what it does — never
 * run as the half that was understood.
 *
 * **A saved scenario is what it was.** Reopening one shows the run it stored,
 * on the snapshot it read, never a recomputation against a newer month.
 */

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { save as saveBlob } from "@/components/exports/download";
import { Unavailable } from "@/components/ui/unavailable";
import { Composer, count, money } from "@/components/whatif/parts";
import type {
  RetailWhatIfCard,
  RetailWhatIfComparison,
  RetailWhatIfTurn,
} from "@/lib/api";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

type Turn =
  | { kind: "said"; text: string }
  | { kind: "replied"; text: string }
  | { kind: "turn"; body: RetailWhatIfTurn };

/** A fraction from the engine (0.1298) shown the way a person reads it. */
function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const pct = value * 100;
  return `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
}

function sar(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `SAR ${value.toLocaleString("en-US", { maximumFractionDigits: 0 })}`;
}

export function RetailWhatIf() {
  const landing = useAsync(() => api.retailWhatIfLanding(), []);
  const [month, setMonth] = React.useState("");
  const [text, setText] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [error, setError] = React.useState<string | null>(null);
  const [saveName, setSaveName] = React.useState("");
  const [saved, setSaved] = React.useState<RetailWhatIfCard[]>([]);
  const [reopened, setReopened] = React.useState<RetailWhatIfCard | null>(null);
  const [picked, setPicked] = React.useState<number[]>([]);
  const [comparison, setComparison] =
    React.useState<RetailWhatIfComparison | null>(null);

  React.useEffect(() => {
    if (landing.data && !month) setMonth(landing.data.latest_month ?? "");
    if (landing.data) setSaved(landing.data.saved ?? []);
  }, [landing.data, month]);

  // The scenario the conversation is holding, so "apply the same shock only to
  // salary-transfer customers" narrows THIS scenario rather than starting a
  // new one from the sentence alone.
  const carried = React.useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const turn = turns[i];
      if (turn.kind === "turn" && turn.body.kind === "result" && turn.body.scenario) {
        return {
          filters: turn.body.scenario.filters,
          shocks: turn.body.scenario.shocks,
          month: turn.body.snapshot_month ?? month,
        };
      }
    }
    return {};
  }, [turns, month]);

  const last = React.useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i -= 1) {
      const turn = turns[i];
      if (turn.kind === "turn" && turn.body.kind === "result") return turn.body;
    }
    return null;
  }, [turns]);

  // Held in a ref as well as in state: `send` is a callback the composer keeps,
  // and closing over `last` would send whatever run was on the table when the
  // callback was made rather than the one on it now.
  const lastRef = React.useRef<RetailWhatIfTurn | null>(null);

  const send = React.useCallback(
    async (question: string, chosen?: Record<string, unknown>) => {
      const said = question.trim();
      if (!said || busy) return;
      setBusy(true);
      setError(null);
      setReopened(null);
      setTurns((t) => [...t, { kind: "said", text: said }]);
      setText("");
      try {
        const body = await api.retailWhatIfAsk({
          question: said,
          month: month || null,
          carried,
          chosen: chosen ?? null,
          // The run on the table, so "what changed, and why?" is answered
          // about THAT run rather than read as a scenario with no shocks.
          last_run: (lastRef.current as unknown as Record<string, unknown>) ?? null,
        });
        setTurns((t) => [...t, { kind: "turn", body }]);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        // The question is not lost: it goes back in the composer so a retry is
        // one key rather than retyping a paragraph.
        setText(said);
      } finally {
        setBusy(false);
      }
    },
    [busy, carried, month],
  );

  const save = React.useCallback(async () => {
    if (!last) return;
    setBusy(true);
    setError(null);
    try {
      const body = await api.retailWhatIfSave({
        name: saveName || (last.question ?? "What-If"),
        question: last.question ?? "",
        month: last.snapshot_month ?? month,
        run: last as unknown as Record<string, unknown>,
      });
      setSaved((rows) => [body.saved, ...rows]);
      setSaveName("");
      setTurns((t) => [
        ...t,
        { kind: "replied", text: `Saved as “${body.saved.name}”.` },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, [last, month, saveName]);

  const reopen = React.useCallback(async (id: number) => {
    setBusy(true);
    setError(null);
    try {
      const body = await api.retailWhatIfReopen(id);
      setReopened(body.saved);
      setTurns((t) => [
        ...t,
        { kind: "said", text: `Explain the saved What-If “${body.saved.name}”.` },
        { kind: "turn", body: body.run },
      ]);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  React.useEffect(() => {
    lastRef.current = last;
  }, [last]);

  const exportRun = React.useCallback(
    async (id: number, fmt: "csv" | "json") => {
      setError(null);
      try {
        const file = await api.retailWhatIfExport(id, fmt);
        saveBlob(file.blob, file.filename);
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
      }
    },
    [],
  );

  const remove = React.useCallback(async (id: number) => {
    setError(null);
    try {
      await api.retailWhatIfDelete(id);
      setSaved((rows) => rows.filter((r) => r.id !== id));
      setPicked((ids) => ids.filter((x) => x !== id));
      setComparison(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const compare = React.useCallback(async (ids: number[]) => {
    setError(null);
    try {
      setComparison(await api.retailWhatIfCompare(ids[0], ids[1]));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  const data = landing.data;

  return (
    <div className="space-y-5" data-testid="retail-whatif">
      <PageHeader
        eyebrow="What-If Analysis"
        title="What-If"
        description={
          "Saudi retail IFRS 9, facility by facility. Every result names the "
          + "month, the population, the shocks, the staging mode and the "
          + "methodology version that produced it."
        }
      />

      <Unavailable state={landing} what="What-If Analysis" />

      {data ? (
        <>
          <Card>
            <CardHeader className="flex-row items-center justify-between gap-3">
              <CardTitle className="text-[18px]">Describe a change</CardTitle>
              <label className="flex items-center gap-2 text-[12px] text-text-secondary">
                Month
                <select
                  value={month}
                  onChange={(e) => setMonth(e.target.value)}
                  aria-label="Reporting month"
                  data-testid="retail-whatif-month"
                  className="rounded-md border border-border bg-surface px-2 py-1 text-[12px]"
                >
                  {data.months.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                </select>
              </label>
            </CardHeader>
            <CardContent className="space-y-3">
              <Composer
                value={text}
                onChange={setText}
                onSubmit={() => void send(text)}
                busy={busy}
                placeholder="Describe a change to the retail book — or ask about it."
                suggestions={data.starters}
              />
              <p className="text-[11px] text-text-muted">{data.disclosure}</p>
            </CardContent>
          </Card>

          {error ? (
            <Card className="border-negative/40 p-4 text-sm text-negative"
                  data-testid="retail-whatif-error">
              {error}
            </Card>
          ) : null}

          <div className="space-y-4" data-testid="retail-whatif-thread">
            {turns.map((turn, index) => (
              <TurnView key={index} turn={turn} onChoose={send} />
            ))}
          </div>

          {last ? (
            <Card>
              <CardContent className="flex flex-wrap items-center gap-2 pt-4">
                <input
                  value={saveName}
                  onChange={(e) => setSaveName(e.target.value)}
                  placeholder="Name this What-If"
                  aria-label="Name this What-If"
                  data-testid="retail-whatif-name"
                  className="rounded-md border border-border bg-surface px-2 py-1 text-[12px]"
                />
                <Button size="sm" onClick={() => void save()} disabled={busy}
                        data-testid="retail-whatif-save">
                  Save What-If
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setTurns([]);
                    setReopened(null);
                    setError(null);
                  }}
                  data-testid="retail-whatif-clear"
                >
                  Clear conversation
                </Button>
                <span className="text-[11px] text-text-muted">
                  Baseline {sar(last.baseline?.ecl_final_sar)} → What-If{" "}
                  {sar(last.scenario_result?.ecl_final_sar)} (
                  {percent(last.delta?.ecl_final_pct)})
                </span>
              </CardContent>
            </Card>
          ) : null}

          <Card>
            <CardHeader>
              <CardTitle className="text-[14px]">Saved What-Ifs</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {reopened ? (
                <p className="text-[12px] text-text-secondary">
                  Showing “{reopened.name}” as it ran at {reopened.month}, on
                  dataset {reopened.dataset_version}. Reopening never recomputes
                  it.
                </p>
              ) : null}
              {saved.length === 0 ? (
                <p className="text-[12px] text-text-muted">
                  {data.persistence}
                </p>
              ) : (
                <ul className="space-y-2" data-testid="retail-whatif-saved">
                  {saved.map((card) => (
                    <li
                      key={card.id}
                      className="flex flex-wrap items-center gap-3 rounded-md border border-border bg-surface p-3"
                      data-saved-id={card.id}
                    >
                      <span className="text-[13px] font-medium text-text-primary">
                        {card.name}
                      </span>
                      <Badge variant="default">{card.month}</Badge>
                      <span className="text-[12px] text-text-secondary">
                        {sar(card.baseline_ecl)} → {sar(card.whatif_ecl)} (
                        {percent(card.delta_pct)})
                      </span>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => void reopen(card.id)}
                        data-testid={`retail-whatif-reopen-${card.id}`}
                      >
                        Reopen
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void exportRun(card.id, "csv")}
                        data-testid={`retail-whatif-csv-${card.id}`}
                      >
                        CSV
                      </Button>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void exportRun(card.id, "json")}
                        data-testid={`retail-whatif-json-${card.id}`}
                      >
                        JSON
                      </Button>
                      <label className="flex items-center gap-1 text-[11px] text-text-secondary">
                        <input
                          type="checkbox"
                          checked={picked.includes(card.id)}
                          aria-label={`Compare ${card.name}`}
                          data-testid={`retail-whatif-pick-${card.id}`}
                          onChange={(e) =>
                            setPicked((ids) =>
                              e.target.checked
                                ? [...ids, card.id].slice(-2)
                                : ids.filter((x) => x !== card.id),
                            )
                          }
                        />
                        Compare
                      </label>
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => void remove(card.id)}
                        data-testid={`retail-whatif-delete-${card.id}`}
                      >
                        Delete
                      </Button>
                    </li>
                  ))}
                </ul>
              )}

              {picked.length === 2 ? (
                <Button
                  size="sm"
                  onClick={() => void compare(picked)}
                  data-testid="retail-whatif-compare"
                >
                  Compare the two selected
                </Button>
              ) : null}

              {comparison ? (
                <div className="rounded-md border border-border p-3 text-[12px]"
                     data-testid="retail-whatif-comparison">
                  <p className="font-medium text-text-primary">
                    {comparison.left.name} against {comparison.right.name}
                  </p>
                  <p className="text-text-secondary">{comparison.note}</p>
                  {comparison.differences.map((line) => (
                    <p key={line} className="text-warning">
                      {line}
                    </p>
                  ))}
                  <p className="text-text-secondary">
                    {sar(comparison.left.whatif_ecl)} against{" "}
                    {sar(comparison.right.whatif_ecl)}
                    {comparison.comparable && comparison.ecl_gap_sar !== null
                      ? ` — a difference of ${sar(comparison.ecl_gap_sar)}`
                      : ""}
                  </p>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[14px]">
                What this engine implements
              </CardTitle>
            </CardHeader>
            <CardContent>
              <dl className="grid gap-2 text-[12px] sm:grid-cols-2">
                {Object.entries(data.supported).map(([name, description]) => (
                  <div key={name}>
                    <dt className="font-medium text-text-primary">{name}</dt>
                    <dd className="text-text-secondary">{description}</dd>
                  </div>
                ))}
              </dl>
              <p className="mt-3 text-[11px] text-text-muted">
                Methodology {data.methodology_version}. Staging modes:{" "}
                {data.staging_modes.join(", ")}.
              </p>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}

function TurnView({
  turn,
  onChoose,
}: {
  turn: Turn;
  onChoose: (question: string, chosen?: Record<string, unknown>) => void;
}) {
  if (turn.kind === "said") {
    return (
      <p className="text-[13px] font-medium text-text-primary" data-turn="said">
        {turn.text}
      </p>
    );
  }
  if (turn.kind === "replied") {
    return (
      <p className="text-[13px] text-text-secondary" data-turn="replied">
        {turn.text}
      </p>
    );
  }

  const body = turn.body;

  if (body.kind === "clarification") {
    return (
      <Card data-turn="clarification">
        <CardContent className="space-y-3 pt-4">
          <p className="text-[13px] text-text-primary">{body.question}</p>
          <div className="flex flex-wrap gap-2">
            {(body.options ?? []).map((option) => (
              <Button
                key={option.id}
                size="sm"
                variant="outline"
                data-option={option.id}
                onClick={() =>
                  onChoose(option.label, { shocks: option.shocks })
                }
              >
                {option.label}
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (body.kind === "explanation") {
    return (
      <Card data-turn="explanation">
        <CardContent className="space-y-2 pt-4">
          {(body.lines ?? []).map((line) => (
            <p key={line} className="text-[13px] text-text-primary">
              {line}
            </p>
          ))}
          {body.message ? (
            <p className="text-[13px] text-text-primary">{body.message}</p>
          ) : null}
          {(body.assumptions ?? []).length || (body.limitations ?? []).length ? (
            <details>
              <summary className="cursor-pointer text-[12px] text-text-secondary">
                The assumptions this run carried
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-[12px] text-text-secondary">
                {(body.assumptions ?? []).map((line) => (
                  <li key={line}>{line}</li>
                ))}
                {(body.limitations ?? []).map((line) => (
                  <li key={line}>{line}</li>
                ))}
                {body.run_id ? <li>Run {body.run_id}</li> : null}
              </ul>
            </details>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  if (body.kind === "cutoff") {
    const rate = (defaults?: number, known?: number) =>
      known && known > 0 && defaults !== undefined
        ? `${((defaults / known) * 100).toFixed(2)}%`
        : "—";
    return (
      <Card data-turn="cutoff" data-testid="retail-whatif-cutoff">
        <CardContent className="space-y-4 pt-4">
          <p className="text-[12px] text-text-secondary">
            {body.read_as && body.read_as.length
              ? `Read as: ${body.read_as.join("; ")}.`
              : "An application-score cutoff replay."}
          </p>
          {/* Said before the figures, not after them. This is a count over the
              accounts that WERE booked — not a revaluation of the book, and not
              a statement about anyone who was declined. */}
          <p className="text-[12px] text-text-primary">
            A retrospective replay over booked originations only
            {body.products && body.products.length
              ? ` (${body.products.join(", ")})`
              : ""}
            . No expected credit loss is recomputed here.
          </p>
          <div className="grid gap-3 sm:grid-cols-4">
            <Figure
              label="Booked originations"
              value={count(body.booked_facilities)}
            />
            <Figure
              label="Would be excluded"
              value={`${count(body.would_be_excluded)}${
                body.would_be_excluded_pct !== null
                && body.would_be_excluded_pct !== undefined
                  ? ` (${(body.would_be_excluded_pct * 100).toFixed(1)}%)`
                  : ""
              }`}
            />
            <Figure
              label="Excluded exposure"
              value={sar(body.excluded_exposure_sar)}
            />
            <Figure
              label="Cutoff"
              value={Object.entries(body.new_cutoff ?? {})
                .map(([code, level]) => `${code} ${level}`)
                .join(", ") || "—"}
            />
          </div>

          {body.outcomes_available ? (
            <table className="w-full text-[12px]"
                   data-testid="retail-whatif-cutoff-outcomes">
              <thead>
                <tr className="text-left text-text-muted">
                  <th className="py-1">Group</th>
                  <th className="py-1 text-right">Closed outcome window</th>
                  <th className="py-1 text-right">Observed defaults</th>
                  <th className="py-1 text-right">Default rate</th>
                </tr>
              </thead>
              <tbody>
                <tr className="border-t border-border">
                  <td className="py-1">Would have been excluded</td>
                  <td className="py-1 text-right">
                    {count(body.excluded_with_known_outcome)}
                  </td>
                  <td className="py-1 text-right">
                    {count(body.excluded_observed_defaults)}
                  </td>
                  <td className="py-1 text-right">
                    {rate(body.excluded_observed_defaults,
                          body.excluded_with_known_outcome)}
                  </td>
                </tr>
                <tr className="border-t border-border">
                  <td className="py-1">Retained</td>
                  <td className="py-1 text-right">
                    {count(body.retained_with_known_outcome)}
                  </td>
                  <td className="py-1 text-right">
                    {count(body.retained_observed_defaults)}
                  </td>
                  <td className="py-1 text-right">
                    {rate(body.retained_observed_defaults,
                          body.retained_with_known_outcome)}
                  </td>
                </tr>
              </tbody>
            </table>
          ) : (
            // Not a table of zeros. An unknown outcome and a clean book look
            // identical once both are printed as 0.
            <p className="text-[12px] text-warning"
               data-testid="retail-whatif-cutoff-no-outcomes">
              What the excluded accounts went on to do is NOT KNOWN at{" "}
              {body.snapshot_month}: no facility in this population has a closed outcome
              window yet. That is not zero defaults. Ask again at an earlier
              reporting month.
            </p>
          )}

          {body.limitations && body.limitations.length ? (
            <details>
              <summary className="cursor-pointer text-[12px] text-text-secondary">
                What this replay cannot tell you
              </summary>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-[12px] text-text-secondary">
                {body.limitations.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </details>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  if (body.kind === "refusal" || body.kind === "invalid") {
    return (
      <Card className="border-warning/40" data-turn={body.kind}>
        <CardContent className="space-y-2 pt-4">
          <p className="text-[13px] text-text-primary">{body.message}</p>
          {body.supported ? (
            <p className="text-[12px] text-text-secondary">
              Supported: {Object.keys(body.supported).join(", ")}.
            </p>
          ) : null}
        </CardContent>
      </Card>
    );
  }

  const baseline = body.baseline;
  const scenario = body.scenario_result;
  const delta = body.delta;

  return (
    <Card data-turn="result" data-run-id={body.scenario?.run_id}>
      <CardContent className="space-y-4 pt-4">
        <p className="text-[12px] text-text-secondary">
          {body.read_as && body.read_as.length
            ? `Read as: ${body.read_as.join("; ")}.`
            : "An unchanged scenario over the whole retail book."}
        </p>

        {body.population_empty ? (
          <p className="text-[13px] text-text-primary">
            No facility matches that population at {body.snapshot_month}. This is an
            empty result, not a zero: there is nothing to shock.
          </p>
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-4">
              <Figure label="Baseline ECL" value={sar(baseline?.ecl_final_sar)} />
              <Figure label="What-If ECL" value={sar(scenario?.ecl_final_sar)} />
              <Figure
                label="Change"
                value={`${sar(delta?.ecl_final_sar)} (${percent(delta?.ecl_final_pct)})`}
              />
              <Figure
                label="Population"
                value={`${count(baseline?.facilities)} facilities · ${count(
                  baseline?.customers,
                )} customers`}
              />
            </div>

            {body.parity ? (
              <p
                className="text-[12px] text-text-secondary"
                data-testid="retail-whatif-parity"
              >
                {body.parity.within_tolerance
                  ? `Unchanged: the rebuild reproduces the published ECL to `
                    + `SAR ${Math.abs(body.parity.total_residual_sar).toFixed(2)} `
                    + `on ${sar(body.parity.published_ecl_final_sar)} `
                    + `(${(body.parity.relative_residual * 100).toExponential(1)}%), `
                    + `no facility differing by more than `
                    + `SAR ${body.parity.max_facility_residual_sar.toFixed(3)} `
                    + `— inside the declared tolerance of SAR `
                    + `${body.parity.tolerance.per_facility_sar} per facility.`
                  : `The neutral rebuild is OUTSIDE the declared tolerance: `
                    + `${body.parity.facilities_outside_tolerance} facilities `
                    + `differ by more than SAR `
                    + `${body.parity.tolerance.per_facility_sar}. This is a `
                    + `defect in the engine, not a rounding difference.`}
              </p>
            ) : null}

            {body.drivers && body.drivers.length ? (
              <table className="w-full text-[12px]" data-testid="retail-whatif-drivers">
                <thead>
                  <tr className="text-left text-text-muted">
                    <th className="py-1">Product</th>
                    <th className="py-1 text-right">Baseline</th>
                    <th className="py-1 text-right">What-If</th>
                    <th className="py-1 text-right">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {body.drivers.map((row) => (
                    <tr key={row.product_code} className="border-t border-border">
                      <td className="py-1">{row.product_code}</td>
                      <td className="py-1 text-right">{money(row.baseline)}</td>
                      <td className="py-1 text-right">{money(row.scenario)}</td>
                      <td className="py-1 text-right">{money(row.delta_sar)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : null}
          </>
        )}

        {body.assumptions && body.assumptions.length ? (
          <details>
            <summary className="cursor-pointer text-[12px] text-text-secondary">
              Assumptions and evidence
            </summary>
            <ul className="mt-2 list-disc space-y-1 pl-5 text-[12px] text-text-secondary">
              {body.assumptions.map((line) => (
                <li key={line}>{line}</li>
              ))}
              {(body.limitations ?? []).map((line) => (
                <li key={line}>{line}</li>
              ))}
              <li>
                Run {body.scenario?.run_id} · dataset {body.dataset_version} ·
                methodology {body.scenario?.methodology_version} · staging{" "}
                {body.scenario?.staging_mode}
              </li>
            </ul>
          </details>
        ) : null}

        {body.unsupported && body.unsupported.length ? (
          <p className="text-[12px] text-warning">
            Not applied, because this engine does not implement it:{" "}
            {body.unsupported.join("; ")}.
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface p-3">
      <div className="text-[11px] uppercase tracking-wide text-text-muted">
        {label}
      </div>
      <div className="text-[15px] font-medium text-text-primary">{value}</div>
    </div>
  );
}
