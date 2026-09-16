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

import { useRouter } from "next/navigation";
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
  // Opening a guided card creates a SELECTION and a THREAD and navigates to
  // it. The cohort a card describes becomes the same immutable membership
  // record an Early Warning export writes, so the thread that opens is the
  // same thread with the same engine, results and workbook behind it.
  const [opening, setOpening] = React.useState("");
  const router = useRouter();
  const openThread = React.useCallback(async (key: string) => {
    const card = JOURNEYS.find((one) => one.key === key);
    if (!card || opening) return;
    setOpening(key);
    try {
      const thread = await api.whatifThreadOpen({
        title: card.title, opened_from: "guided_card", ...card.cohort });
      router.push(`/what-if/threads/${thread.thread_id}`);
    } catch (failed) {
      setError(String(failed));
      setOpening("");
    }
  }, [opening, router]);

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

/**
 * The guided scenarios, as retail actually cuts.
 *
 * The corporate What-If offers six journeys and they are the right SHAPE —
 * pick the kind of change, see what that kind looks like, press one. Three of
 * the six are corporate objects, though, and a retail reader does not have
 * them. There is no rating to move, and the concentration that matters is not
 * a sector.
 *
 * So: rating movement becomes the two things a retail book actually migrates
 * on — days past due, and the behavioural score band. Sector stress becomes
 * product and sub-product stress, on the same taxonomy the Early Warning
 * Score uses, because a reader who has just been looking at Platinum Card
 * should be able to stress Platinum Card. PD and LGD stop being separate
 * journeys and become one Risk Parameter Adjustment, because nobody thinks
 * "I would like to change a loss given default" — they think "I want the
 * parameters worse". Stage migration, macro and borrower stress carry over
 * unchanged, because those are the same question in either book.
 *
 * Every prompt below is a complete sentence the governed parser resolves.
 * None is a keyword this file translates.
 */
const JOURNEYS: {
  key: string; title: string; blurb: string; prompts: string[];
  /**
   * The cohort this card opens a thread over.
   *
   * §8.2: clicking a card must create a thread and show its baseline, not
   * swap the prompt chips on the home page. So a card names the SELECTION it
   * is about — the same kind of immutable membership record an Early Warning
   * export writes — and the thread that opens is the same thread.
   */
  cohort: Record<string, string>;
}[] = [
  {
    key: "dpd",
    cohort: { dpd_bucket: "1-29" },
    title: "DPD Bucket Movement",
    blurb: "Move exposure or accounts between delinquency buckets. The "
         + "facilities that move are the worst in the bucket they leave, and "
         + "they land on what this book shows for the bucket they enter.",
    prompts: [
      "Move 20% of 1-29 DPD exposure to 30-59",
      "Move 15% of 30-59 DPD exposure to 60-89",
      "Move 10% of 60-89 DPD accounts to 90+",
      "Move 20% of 30-59 DPD exposure to 90+ for personal finance",
    ],
  },
  {
    key: "behavioural",
    cohort: { behavioural_band: "B" },
    title: "Behavioural Score Movement",
    blurb: "Worsen or improve score bands. A band change reaches PD through "
         + "the versioned score-to-PD mapping, the way any score change does.",
    prompts: [
      "Move 20% of behavioural score band B to C band",
      "Move 10% of behavioural score band A exposure to B band",
      "Reduce behavioural score by 30 points for non-salaried credit card customers",
      "Reduce behavioural score by 25 points for personal finance",
    ],
  },
  {
    key: "stage",
    cohort: { stage: "1" },
    title: "Stage Migration",
    blurb: "Move a share of one IFRS 9 stage into another. Stage decides "
         + "twelve months against lifetime, and nothing else is inferred.",
    prompts: [
      "Move 15% of Stage 1 exposure to Stage 2",
      "Move 10% of Stage 2 accounts to Stage 3",
      "Cure 20% of Stage 2 back to Stage 1",
      "Re-evaluate staging under worsened delinquency",
    ],
  },
  {
    key: "parameters",
    cohort: {},
    title: "Risk Parameter Adjustment",
    blurb: "PD, LGD, CCF, collateral and recovery in one place — the "
         + "parameters of the IFRS 9 identity, moved directly.",
    prompts: [
      "Increase PIT 12-month PD by 20%",
      "Add 2 percentage points to PD",
      "Increase LGD by 5 percentage points",
      "Increase CCF by 10 percentage points",
      "Reduce collateral value by 15%",
      "Add six months to the recovery delay",
    ],
  },
  {
    key: "product",
    cohort: { product: "CREDIT_CARD" },
    title: "Product & Sub-product Stress",
    blurb: "The same products and sub-products the Early Warning Score uses, "
         + "so a cohort you were just reading about is a cohort you can "
         + "stress by name.",
    prompts: [
      "Increase PIT 12-month PD by 20% for credit card",
      "Increase PIT 12-month PD by 15% for platinum card",
      "Add 5 percentage points to LGD on home finance",
      "Reduce verified income by 10% for non-salaried personal finance",
      "Increase PD by 25% for salaried auto finance",
    ],
  },
  {
    key: "macro",
    cohort: {},
    title: "Macroeconomic Stress",
    blurb: "The scenario weights, and the borrower-level proxies a retail "
         + "book carries for a downturn.",
    prompts: [
      "Change scenario weights to base 50%, upturn 10%, downturn 40%",
      "Reduce verified income by 15%",
      "Increase household expense burden by 10%",
      "Reduce collateral value by 20% and add six months to recovery",
    ],
  },
  {
    key: "borrower",
    cohort: { cohort: "forward_risk" },
    title: "Borrower Stress",
    blurb: "One customer, or a cohort exported from Early Warning Score. "
         + "Open the cohort from its card and the thread arrives with the "
         + "exact customers already selected.",
    prompts: [
      "Stress only the customers who are already bad",
      "Stress only the forward-risk customers",
      "Stress high and critical Early Warning customers only",
      "Apply the shock to customers with behavioural score band D and below",
    ],
  },
];

function Journeys({ onChoose, onOpen, opening }: {
  onChoose: (said: string) => void;
  onOpen: (key: string) => void;
  opening: string;
}) {
  const [open, setOpen] = React.useState<string>("");
  return (
    <Card data-testid="retail-whatif-journeys">
      <CardHeader>
        <CardTitle className="text-[18px]">Guided scenarios</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {JOURNEYS.map((one) => (
            <button
              key={one.key}
              type="button"
              onClick={() => setOpen(open === one.key ? "" : one.key)}
              className={
                "rounded-lg border p-3 text-left transition-colors "
                + (open === one.key
                  ? "border-accent bg-accent-muted/30"
                  : "border-border hover:bg-surface-muted")
              }
              data-testid={`retail-whatif-journey-${one.key}`}
            >
              <p className="text-[13px] font-semibold text-text-primary">
                {one.title}
              </p>
              <p className="mt-0.5 text-[11px] leading-relaxed text-text-secondary">
                {one.blurb}
              </p>
            </button>
          ))}
        </div>

        {open ? (
          <div className="mt-3 rounded-lg border border-border p-3"
               data-testid={`retail-whatif-prompts-${open}`}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
                {JOURNEYS.find((one) => one.key === open)?.title} — press one,
                or type your own
              </p>
              {/*
                * §8.2: the card OPENS a thread. Pressing a prompt below runs
                * it in the thread this creates, over the cohort the card is
                * about, with its baseline profile already drawn — rather than
                * executing a scenario inline under the cards, which is what
                * the standalone page used to do.
                */}
              <Button
                size="sm"
                disabled={Boolean(opening)}
                onClick={() => onOpen(open)}
                data-testid={`retail-whatif-open-${open}`}
              >
                {opening === open ? "Opening…" : "Open this as a thread"}
              </Button>
            </div>
            <div className="mt-2 flex flex-wrap gap-1.5">
              {(JOURNEYS.find((one) => one.key === open)?.prompts ?? []).map(
                (prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => onChoose(prompt)}
                    className="rounded-full border border-border px-2.5 py-1
                               text-[11px] text-text-secondary
                               transition-colors hover:bg-surface-muted"
                    data-testid="retail-whatif-journey-prompt"
                  >
                    {prompt}
                  </button>
                ),
              )}
            </div>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}

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

          <Journeys
            onChoose={(said) => void send(said)}
            onOpen={(key) => void openThread(key)}
            opening={opening}
          />

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

          {/*
            * The parameter catalogue used to be here, listing `pd_relative`,
            * `lgd_relative`, `ccf_absolute`, `income_pct`, `dpd_migration`
            * and `score_band_migration` to whoever opened the page. §2.1
            * names it as a defect: those are implementation identifiers, and
            * the reader's journey is not where they belong. The technical
            * dictionary lives on the model pages, which is where somebody
            * looking for it will look.
            */}
          <Card>
            <CardContent className="flex flex-wrap items-center gap-3 pt-4
                                    text-[12px] text-text-secondary">
              <span>
                Methodology {data.methodology_version} · staging modes{" "}
                {data.staging_modes.join(", ")}
              </span>
              {/* The RETAIL methodology pages. These used to point at
                  /what-if/models/delta and /what-if/models/ml, which are
                  corporate routes: in a retail installation both retire
                  themselves, so the two cards on the retail What-If screen
                  led to "this screen is not part of this installation". */}
              <Button variant="outline" size="sm" asChild>
                <a href="/what-if/methods/delta"
                   data-testid="retail-whatif-open-delta">
                  Delta method
                </a>
              </Button>
              <Button variant="outline" size="sm" asChild>
                <a href="/what-if/methods/xgboost"
                   data-testid="retail-whatif-open-xgboost">
                  XGBoost challenger
                </a>
              </Button>
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
                  onChoose(option.label, {
                    shocks: option.shocks,
                    // An option may BE a reweighting rather than a shock.
                    // Sending only `shocks` dropped the weights and ran the
                    // neutral scenario the clarification existed to prevent.
                    scenario_weights: option.scenario_weights ?? null,
                  })
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
