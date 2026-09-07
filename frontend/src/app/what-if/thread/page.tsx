"use client";

/**
 * A What-If thread.
 *
 * The philosophy the product asked for, in order: show the book, ask what to
 * change, gather what is missing, restate what was understood, ask which ECL
 * methodology, calculate, explain, and leave the composer open so the next
 * shock lands on top of this one.
 *
 * The scenario STATE lives here, in the browser, as a structure. That is what
 * makes "change the PD increase from 20% to 15%" possible: the step is edited
 * in place and the whole thing recomputed, rather than the conversation being
 * re-read and re-interpreted.
 *
 * The composer is never replaced by the buttons beside it. Every finite choice
 * gets chips AND the box stays; a person who wants to say something no chip
 * covers must always be able to.
 */

import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { BackLink } from "@/components/layout/back-link";
import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs } from "@/components/ui/tabs";
import {
  BeforeAfterChart,
  DriverAttribution,
  Composer,
  EclHeadline,
  Figure,
  MethodologyGate,
  MigrationMatrix,
  PeriodPicker,
  InvestigationAnswer,
  ProfileTable,
  ResultContext,
  WhatIfError,
  ResultInterpretation,
  RiskParameterPanel,
  ScenarioSteps,
  StagingCriteria,
  count,
  money,
  pct,
  signed,
} from "@/components/whatif/parts";
import type {
  WhatIfBorrowerList,
  WhatIfGate,
  WhatIfInvestigation,
  WhatIfMacro,
  WhatIfMigration,
  WhatIfParameterProfile,
  WhatIfRatingProfile,
  WhatIfRunResult,
  WhatIfSectorProfile,
  WhatIfStageProfile,
  WhatIfStaging,
  WhatIfStagingKind,
  WhatIfStagingRuleIn,
  WhatIfState,
} from "@/lib/api";
import { api } from "@/lib/api";

type Turn =
  | { kind: "said"; text: string }
  | { kind: "replied"; text: string; tone?: "note" | "warn" }
  | { kind: "result"; result: WhatIfRunResult }
  | { kind: "answer"; answer: WhatIfInvestigation };

const JOURNEY_TITLES: Record<string, string> = {
  rating: "Rating Movement",
  parameters: "IFRS 9 Risk Parameter Adjustment",
  stage: "Stage Migration",
  macro: "Macroeconomic Shock",
  sector: "Sector Stress",
  borrower: "Borrower Stress",
};

const JOURNEY_PROMPTS: Record<string, string[]> = {
  rating: [
    "Downgrade everyone one notch.",
    "Downgrade only Stage 1 borrowers two notches.",
    "Downgrade BBB borrowers two notches.",
  ],
  parameters: [
    "Increase Stage 1 PD by 20%.",
    "Add 100 bps to BBB Stage 1 PD.",
    "Increase LGD by five percentage points.",
    "Increase CCF by 20%.",
  ],
  stage: [
    "Move half the Stage 1 borrowers to Stage 2.",
    "Move 10% of Stage 2 to Stage 3.",
    "Cure 20% of Stage 2 back to Stage 1.",
  ],
  macro: [
    "Increase unemployment by one percentage point.",
    "Oil price down 20%.",
    "Policy rates up 200 bps.",
  ],
  sector: [
    "Reduce construction collateral by 20%.",
    "Increase PD in Real Estate by 30%.",
  ],
  borrower: ["Downgrade this borrower two notches."],
};

function emptyState(period: string, title: string): WhatIfState {
  return { period, title, steps: [] };
}

export default function WhatIfThreadPage() {
  const params = useSearchParams();
  const router = useRouter();
  const journey = params.get("journey") ?? "";
  const initialQuestion = params.get("q") ?? "";
  const savedId = params.get("saved");

  const [state, setState] = React.useState<WhatIfState>(() => emptyState("", ""));
  const [history, setHistory] = React.useState<WhatIfState[]>([]);
  const [turns, setTurns] = React.useState<Turn[]>([]);
  const [gate, setGate] = React.useState<WhatIfGate | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [text, setText] = React.useState("");
  //: The error OBJECT, not its sentence. A screen that keeps only the message
  //: cannot tell a refusal from an outage, and every failure reads the same.
  const [error, setError] = React.useState<unknown>(null);
  //: What "Try again" would repeat. The ARGUMENTS, not a closure over the
  //: function: a ref holding a closure captures whichever `runWith` existed
  //: when it was written, and a retry that calls a stale one runs a scenario
  //: the thread has moved on from.
  const retryArgs = React.useRef<
    { state: WhatIfState; methodology: string; instruction: string } | null>(null);
  const [stagingOpen, setStagingOpen] = React.useState(false);
  const [staging, setStaging] = React.useState<WhatIfStaging | null>(null);
  // The reported-book rule set is held separately and never edited: it is what
  // staged the accounts, and the screen shows it so the override is legible.
  const [reportedStaging, setReportedStaging] = React.useState<WhatIfStaging | null>(null);
  const [stagingKinds, setStagingKinds] = React.useState<WhatIfStagingKind[]>([]);
  const [stagingCombinations, setStagingCombinations] = React.useState<string[]>([]);
  //: The keys the DEFAULT What-If rule set carries. A rule not in here was
  //: added by this thread, and is removed by omission rather than by a request.
  const [stagingDefaultKeys, setStagingDefaultKeys] = React.useState<string[]>([]);
  const [periods, setPeriods] = React.useState<string[]>([]);
  const [migrationView, setMigrationView] = React.useState("count");
  //: The id the last result is held under on the server. A follow-up question
  //: is answered from THAT result rather than from a second run of the same
  //: scenario, which is what makes "why?" a question about the number on the
  //: screen instead of about a new one.
  const [runId, setRunId] = React.useState("");
  const [saveName, setSaveName] = React.useState("");
  const bootstrapped = React.useRef(false);

  // opening views, per journey
  const [ratingProfile, setRatingProfile] = React.useState<WhatIfRatingProfile | null>(null);
  const [stageProfile, setStageProfile] = React.useState<WhatIfStageProfile | null>(null);
  const [sectorProfile, setSectorProfile] = React.useState<WhatIfSectorProfile | null>(null);
  const [macro, setMacro] = React.useState<WhatIfMacro | null>(null);
  const [borrowers, setBorrowers] = React.useState<WhatIfBorrowerList | null>(null);
  const [migration, setMigration] = React.useState<WhatIfMigration | null>(null);
  const [parameterBody, setParameterBody] = React.useState<WhatIfParameterProfile | null>(null);
  const [parameter, setParameter] = React.useState("pd");

  const say = React.useCallback((turn: Turn) => setTurns((t) => [...t, turn]), []);

  /* ------------------------------------------------------------ bootstrap */

  React.useEffect(() => {
    if (bootstrapped.current) return;
    bootstrapped.current = true;
    let cancelled = false;
    (async () => {
      setBusy(true);
      try {
        const [periodBody, stagingBody] = await Promise.all([
          api.whatIfPeriods(),
          api.whatIfStaging(),
        ]);
        if (cancelled) return;
        setPeriods(periodBody.periods);
        setStaging(stagingBody.whatif ?? stagingBody);
        setReportedStaging(stagingBody.reported ?? null);
        setStagingKinds(stagingBody.kind_catalogue ?? []);
        setStagingCombinations(stagingBody.combinations ?? []);
        setStagingDefaultKeys(
          (stagingBody.whatif ?? stagingBody).rules.map((r) => r.key));
        const period = periodBody.latest ?? "";

        if (savedId) {
          const opened = await api.whatIfOpenSaved(Number(savedId));
          if (cancelled) return;
          setState(opened.state);
          say({
            kind: "replied",
            text: `Reopened "${opened.card.name}" — ${opened.card.scenario}. It ran on ${opened.card.period} using the ${opened.card.ecl_methodology}. Run it again, or add another shock.`,
          });
        } else {
          setState(emptyState(period, JOURNEY_TITLES[journey] ?? ""));
        }
      } catch (e) {
        if (!cancelled) setError(e);
      } finally {
        if (!cancelled) setBusy(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [journey, savedId, say]);

  /* ------------------------------------- the opening analysis of a journey */

  const period = state.period;

  React.useEffect(() => {
    if (!period || savedId) return;
    let cancelled = false;
    (async () => {
      try {
        if (journey === "rating") {
          const [profile, moves] = await Promise.all([
            api.whatIfRatingProfile(period),
            api.whatIfRatingMigration(period).catch(() => null),
          ]);
          if (cancelled) return;
          setRatingProfile(profile);
          setMigration(moves);
        } else if (journey === "stage") {
          const [profile, moves] = await Promise.all([
            api.whatIfStageProfile(period),
            api.whatIfStageMigration(period).catch(() => null),
          ]);
          if (cancelled) return;
          setStageProfile(profile);
          setMigration(moves);
        } else if (journey === "sector") {
          setSectorProfile(await api.whatIfSectorProfile(period));
        } else if (journey === "macro") {
          setMacro(await api.whatIfMacroProfile(period));
        } else if (journey === "borrower") {
          setBorrowers(await api.whatIfBorrowers(period, 10));
        } else if (journey === "parameters") {
          setParameterBody(await api.whatIfParameterProfile(parameter, period));
        }
      } catch (e) {
        if (!cancelled) setError(e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [journey, period, parameter, savedId]);

  /* -------------------------------------------------------------- talking */

  const runWith = React.useCallback(
    async (next: WhatIfState, methodology = "", instruction = "") => {
      setBusy(true);
      setError(null);
      // Only offered where retrying could plausibly help — a refusal will be
      // refused the same way, and inviting a retry on one wastes the reader's
      // time.
      retryArgs.current = { state: next, methodology, instruction };
      try {
        const result = await api.whatIfExecute({
          state: next,
          methodology,
          instruction,
          limit: 200,
        });
        if (result.needs_methodology && result.gate) {
          setGate(result.gate);
          setState(result.state);
          return;
        }
        setGate(null);
        setState(result.state);
        setRunId(result.run_id ?? "");
        say({ kind: "result", result });
      } catch (e) {
        setError(e);
      } finally {
        setBusy(false);
      }
    },
    [say],
  );

  const retry = React.useCallback(() => {
    const again = retryArgs.current;
    if (!again) return;
    setError(null);
    void runWith(again.state, again.methodology, again.instruction);
  }, [runWith]);

  const send = React.useCallback(
    async (raw?: string) => {
      const said = (raw ?? text).trim();
      if (!said) return;
      setText("");
      say({ kind: "said", text: said });
      setBusy(true);
      setError(null);
      try {
        const read = await api.whatIfInterpret(said, state);

        // A question about the result is answered from the result. The
        // scenario is not touched, no methodology gate appears, and nothing
        // is recomputed — asking why a number moved cannot move it.
        if (read.changes_state === false) {
          const answered = await api.whatIfInvestigate(said, runId, state);
          if (!answered.answered) {
            say({ kind: "replied", text: answered.message ?? "", tone: "note" });
            return;
          }
          say({ kind: "answer", answer: answered });
          return;
        }

        if (!read.understood) {
          setState(read.state);
          say({ kind: "replied", text: read.message ?? "", tone: "note" });
          return;
        }
        setHistory((h) => [...h, state]);
        setState(read.state);
        say({ kind: "replied", text: read.restatement ?? "" });
        // What the instruction was understood to mean, filter by filter,
        // BEFORE a figure appears. A population that narrowed and a population
        // that did not look identical in a sentence and are not.
        if (read.filters?.length) {
          say({
            kind: "replied",
            text: `What I understood — ${read.filters.join("; ")}.`,
            tone: "note",
          });
        }
        for (const note of read.notes) say({ kind: "replied", text: note, tone: "note" });
        await runWith(read.state, "", said);
      } catch (e) {
        setError(e);
      } finally {
        setBusy(false);
      }
    },
    [text, state, say, runWith, runId],
  );

  // A question typed on the landing page arrives as ?q= and is asked once the
  // period is known. Sent from inside the async body rather than the effect
  // body, because the effect itself must not be what changes state.
  const askedInitial = React.useRef(false);
  React.useEffect(() => {
    if (!initialQuestion || !state.period || askedInitial.current) return;
    askedInitial.current = true;
    let cancelled = false;
    void (async () => {
      if (cancelled) return;
      await send(initialQuestion);
    })();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialQuestion, state.period]);

  /* ------------------------------------------------------------ operating */

  const removeStep = (id: string) => {
    setHistory((h) => [...h, state]);
    setState({ ...state, steps: state.steps.filter((s) => s.step_id !== id) });
    say({ kind: "replied", text: "Removed that step. Run again to see the new result." });
  };
  const undo = () => {
    const previous = history[history.length - 1];
    if (!previous) return;
    setHistory((h) => h.slice(0, -1));
    setState(previous);
    say({ kind: "replied", text: "Undone." });
  };
  const reset = () => {
    setHistory((h) => [...h, state]);
    setState({ ...state, steps: [] });
    say({ kind: "replied", text: "Reset to the reported position." });
  };

  /**
   * Every staging edit goes through here.
   *
   * The thread holds the WHOLE rule set as a list of edits against the default
   * one, and posts it to /whatif/staging for validation before it is allowed
   * near a result. That way a rule the engine cannot apply is refused on the
   * screen that composed it, not three clicks later inside a run — and the
   * thread's override is exactly what the next execute will use.
   */
  const applyStaging = async (
    rules: WhatIfStagingRuleIn[],
    combination?: string,
    told?: string,
  ) => {
    try {
      const preview = await api.whatIfStagingPreview({
        rules,
        combination: combination ?? staging?.combination,
      });
      setStaging(preview.whatif ?? preview);
      setReportedStaging(preview.reported ?? reportedStaging);
      setState({ ...state, staging: { rules, combination: preview.combination } });
      say({
        kind: "replied",
        text: told ?? `Staging criteria updated (${preview.version}). Run again to apply them.`,
        tone: "note",
      });
    } catch (e) {
      setError(e);
    }
  };

  /** The current rule set as the edit list the API speaks. */
  const stagingEdits = (): WhatIfStagingRuleIn[] =>
    (staging?.rules ?? []).map((r) => ({
      key: r.key,
      kind: r.kind,
      name: r.name,
      threshold: r.threshold,
      floor: r.floor,
      enabled: r.enabled,
    }));

  const changeStaging = (key: string, changes: WhatIfStagingRuleIn) =>
    applyStaging(
      stagingEdits().map((r) => (r.key === key ? { ...r, ...changes, key } : r)),
    );

  const addStagingRule = (rule: WhatIfStagingRuleIn) =>
    applyStaging([...stagingEdits(), rule], undefined,
      `Added "${rule.name}" to this What-If's staging criteria. Run again to apply it.`);

  /**
   * Removing a rule is two different requests depending on where it came from.
   *
   * The edit list is replayed against the DEFAULT rule set, so a rule this
   * thread added is removed by simply not asking for it again. A rule that is
   * in the default set has to be removed explicitly — and asking to remove a
   * rule the default set never had is an error, not a no-op, which is why the
   * thread remembers which keys the default carried.
   */
  const removeStagingRule = (key: string) => {
    const kept = stagingEdits().filter((r) => r.key !== key);
    const edits = stagingDefaultKeys.includes(key)
      ? [...kept, { key, remove: true }]
      : kept;
    return applyStaging(edits, undefined,
      "Rule removed from this What-If's staging criteria.");
  };

  const combineStaging = (how: string) =>
    applyStaging(stagingEdits(), how,
      how === "ALL"
        ? "A borrower now needs EVERY enabled rule to fire before it moves to Stage 2."
        : "A borrower now moves to Stage 2 if ANY enabled rule fires.");

  const resetStaging = async () => {
    try {
      const fresh = await api.whatIfStaging();
      setStaging(fresh.whatif ?? fresh);
      setReportedStaging(fresh.reported ?? null);
      setStagingKinds(fresh.kind_catalogue ?? []);
      setState({ ...state, staging: null });
      say({
        kind: "replied",
        text: "Staging criteria back to the What-If default.",
        tone: "note",
      });
    } catch (e) {
      setError(e);
    }
  };

  const save = async () => {
    setBusy(true);
    try {
      const body = await api.whatIfSave({
        state,
        methodology: state.methodology ?? "",
        name: saveName || state.title || "What-If",
      });
      say({ kind: "replied", text: `Saved as "${body.saved.name}".` });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };

  const last = [...turns].reverse().find((t) => t.kind === "result") as
    | { kind: "result"; result: WhatIfRunResult }
    | undefined;

  const suggestions = JOURNEY_PROMPTS[journey] ?? [
    "Increase Stage 1 PD by 20%.",
    "Downgrade everyone one notch.",
    "Increase LGD by five percentage points.",
  ];

  return (
    <div className="space-y-5">
      {/* Back is a control, not a browser affordance. A thread is opened from
          the What-If index, from a saved scenario and from a link somebody
          pasted, and in every one of those a person who wants out of it was
          reaching for a button that was not there. */}
      <BackLink href="/what-if" label="What-If Analysis" />

      <PageHeader
        eyebrow="What-If Analysis"
        title={JOURNEY_TITLES[journey] ?? "What-If"}
        description="Corporate IFRS 9, borrower by borrower. Every result names the period, the population, the staging criteria and the ECL methodology that produced it."
        actions={
          <Button variant="ghost" size="sm" onClick={() => router.push("/what-if")}>
            All What-Ifs
          </Button>
        }
      />

      {/* Four different situations with four different next actions, said
          apart rather than flattened into one red bar. */}
      <WhatIfError
        error={error}
        onRetry={retry}
        onDismiss={() => setError(null)}
      />

      <div className="flex flex-wrap items-end gap-4">
        {periods.length ? (
          <div className="w-52">
            <PeriodPicker
              periods={periods}
              value={state.period}
              onChange={(v) => setState({ ...state, period: v })}
            />
          </div>
        ) : null}
        {state.methodology ? (
          <Badge variant="accent" data-testid="active-methodology">
            {state.methodology === "ml" ? "ML Model — XGBoost" : "Delta Model"}
            {state.model_version ? ` v${state.model_version}` : ""}
          </Badge>
        ) : null}
      </div>

      {staging ? (
        <StagingCriteria
          staging={staging}
          reported={reportedStaging}
          kinds={stagingKinds}
          combinations={stagingCombinations}
          open={stagingOpen}
          onToggle={() => setStagingOpen((v) => !v)}
          onChange={changeStaging}
          onAdd={addStagingRule}
          onRemove={removeStagingRule}
          onCombination={combineStaging}
          onReset={resetStaging}
        />
      ) : null}

      {/* ------------------------------------------- the opening analysis */}

      {ratingProfile ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">
              Rating profile — {ratingProfile.period}
            </CardTitle>
            <p className="mt-0.5 text-[11px] text-text-muted">
              {ratingProfile.grades.length} governed grades plus a Total.{" "}
              {ratingProfile.grain}
            </p>
          </CardHeader>
          <CardContent>
            <ProfileTable
              rows={ratingProfile.rows}
              total={ratingProfile.total}
              first="Rating"
              currency={ratingProfile.currency}
            />
          </CardContent>
        </Card>
      ) : null}

      {stageProfile ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">Stage profile — {stageProfile.period}</CardTitle>
          </CardHeader>
          <CardContent>
            <ProfileTable
              rows={stageProfile.rows}
              total={stageProfile.total}
              first="Stage"
              currency={stageProfile.currency}
            />
          </CardContent>
        </Card>
      ) : null}

      {sectorProfile ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">
              Sector profile — {sectorProfile.period}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <ProfileTable
              rows={sectorProfile.rows}
              total={sectorProfile.total}
              first="Sector"
              currency={sectorProfile.currency}
              extra={[
                {
                  key: "collateral_coverage_pct",
                  label: "Collateral cover",
                  format: (v) => pct(v as number),
                },
                {
                  key: "avg_haircut_pct",
                  label: "Haircut",
                  format: (v) => (v === null ? "—" : pct(v as number)),
                },
              ]}
            />
          </CardContent>
        </Card>
      ) : null}

      {macro ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">
              Macroeconomic variables — v{macro.version}
            </CardTitle>
            <p className="mt-0.5 text-[11px] text-text-muted">{macro.basis}</p>
          </CardHeader>
          <CardContent className="space-y-3">
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {macro.variables.map((variable) => (
                <div
                  key={variable.key}
                  data-macro={variable.key}
                  className="rounded-md border border-border bg-surface p-3"
                >
                  <div className="text-[12px] font-medium text-text-primary">
                    {variable.name}
                  </div>
                  <div className="mt-1 text-[11px] text-text-muted">
                    {variable.has_observed_level
                      ? `Latest ${variable.observed_level} ${variable.unit}`
                      : "No observed level in this installation"}
                  </div>
                  <div className="mt-2 flex gap-3 text-[11px]">
                    <span className="text-text-secondary">
                      PD ×{variable.pd_multiplier}
                    </span>
                    <span className="text-text-secondary">
                      LGD +{variable.lgd_change_pp}pp
                    </span>
                  </div>
                  <div className="mt-0.5 text-[10px] text-text-muted">
                    {variable.adverse_label}
                  </div>
                </div>
              ))}
            </div>
            <p className="text-[11px] text-warning">{macro.limitation}</p>
          </CardContent>
        </Card>
      ) : null}

      {borrowers ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">
              Top Stage 2 borrowers by ECL — {borrowers.period}
            </CardTitle>
            <p className="mt-0.5 text-[11px] text-text-muted">{borrowers.grain}</p>
          </CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead>
                <tr className="text-left text-text-muted">
                  <th className="py-1">Customer</th>
                  <th>Name</th>
                  <th>Sector</th>
                  <th>Rating</th>
                  <th className="text-right">Exposure</th>
                  <th className="text-right">12m PD</th>
                  <th className="text-right">Lifetime PD</th>
                  <th className="text-right">LGD</th>
                  <th className="text-right">ECL</th>
                </tr>
              </thead>
              <tbody>
                {borrowers.rows.map((row) => (
                  <tr key={row.borrower_id} data-borrower={row.borrower_id} className="border-t border-border">
                    <td className="py-1 font-mono text-[11px]">{row.borrower_id}</td>
                    <td>{row.name}</td>
                    <td>{row.sector}</td>
                    <td>{row.rating}</td>
                    <td className="text-right tabular-nums">{money(row.exposure)}</td>
                    <td className="text-right tabular-nums">{pct(row.pd_12m, 3)}</td>
                    <td className="text-right tabular-nums">{pct(row.pd_lifetime, 3)}</td>
                    <td className="text-right tabular-nums">{pct(row.lgd)}</td>
                    <td className="text-right tabular-nums">{money(row.ecl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      ) : null}

      {parameterBody ? (
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle className="text-[14px]">
              {String(parameterBody.parameter ?? "").toUpperCase()} —{" "}
              {String(parameterBody.period ?? "")}
            </CardTitle>
            <Tabs
              active={parameter}
              onChange={setParameter}
              tabs={[
                { id: "pd", label: "PD" },
                { id: "lgd", label: "LGD" },
                { id: "ccf", label: "CCF" },
              ]}
            />
          </CardHeader>
          <CardContent>
            <RiskParameterPanel
              profile={parameterBody}
              currency={parameterBody.currency ?? "SAR"}
            />
          </CardContent>
        </Card>
      ) : null}

      {migration ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-[14px]">
              {migration.kind === "rating" ? "Rating" : "Stage"} migration —{" "}
              {migration.opening_period} → {migration.closing_period}
            </CardTitle>
          </CardHeader>
          <CardContent>
            <MigrationMatrix
              migration={migration}
              view={migrationView}
              onView={setMigrationView}
              currency={migration.currency}
            />
          </CardContent>
        </Card>
      ) : null}

      {/* -------------------------------------------------- the conversation */}

      <Card>
        <CardHeader>
          <CardTitle className="text-[14px]">Scenario</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <ScenarioSteps
            steps={state.steps}
            onRemove={removeStep}
            onReset={reset}
            onUndo={undo}
            canUndo={history.length > 0}
          />

          {turns.length ? (
            <ol className="space-y-3 border-t border-border pt-4">
              {turns.map((turn, index) => {
                if (turn.kind === "said") {
                  return (
                    <li key={index} className="flex justify-end">
                      <span className="max-w-[80%] rounded-md bg-accent-muted px-3 py-2 text-[12px] text-text-primary">
                        {turn.text}
                      </span>
                    </li>
                  );
                }
                if (turn.kind === "replied") {
                  return (
                    <li
                      key={index}
                      className={
                        turn.tone === "note"
                          ? "text-[12px] text-text-muted"
                          : "text-[12px] text-text-secondary"
                      }
                    >
                      {turn.text}
                    </li>
                  );
                }
                if (turn.kind === "answer") {
                  return (
                    <li key={index} data-testid="whatif-answer">
                      <InvestigationAnswer
                        answer={turn.answer}
                        currency={turn.answer.context?.currency ?? "SAR"}
                      />
                    </li>
                  );
                }
                const result = turn.result;
                const context = result.context;
                if (!context) return null;
                return (
                  <li key={index} className="space-y-3" data-testid="whatif-result">
                    <ResultContext context={context} />
                    <EclHeadline context={context} currency={context.currency} />
                    {result.confirmation ? (
                      <p className="text-[12px] text-text-secondary">{result.confirmation}</p>
                    ) : null}
                    {result.interpretation ? (
                      <ResultInterpretation
                        interpretation={result.interpretation}
                        onAsk={(question) => void send(question)}
                      />
                    ) : null}
                    {result.factors ? (
                      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
                        <Figure label="PD effect" value={signed((result.factors.pd_factor - 1) * 100)} />
                        <Figure label="Stage effect" value={signed((result.factors.stage_factor - 1) * 100)} />
                        <Figure label="LGD effect" value={signed((result.factors.lgd_factor - 1) * 100)} />
                        <Figure label="EAD effect" value={signed((result.factors.ead_factor - 1) * 100)} />
                        <Figure
                          label="Combined"
                          value={signed((result.factors.combined_factor - 1) * 100)}
                          tone="whatif"
                        />
                      </div>
                    ) : null}
                    {result.stage_movement ? (
                      <div className="grid grid-cols-3 gap-3">
                        <Figure label="Stage moves" value={count(result.stage_movement.moved)} />
                        <Figure
                          label="Deteriorated"
                          value={count(result.stage_movement.deteriorated)}
                          tone="negative"
                        />
                        <Figure
                          label="Cured"
                          value={count(result.stage_movement.cured)}
                          tone="positive"
                        />
                      </div>
                    ) : null}
                    {result.attribution ? (
                      <DriverAttribution
                        attribution={result.attribution}
                        currency={context.currency}
                      />
                    ) : null}
                    {result.stage_movement?.stages?.length ? (
                      <div className="grid gap-4 lg:grid-cols-2">
                        <BeforeAfterChart
                          title="Exposure by Stage"
                          measure="exposure"
                          currency={context.currency}
                          rows={result.stage_movement.stages.map((s) => ({
                            label: `Stage ${s.stage}`,
                            before: s.exposure_before,
                            after: s.exposure_after,
                          }))}
                        />
                        <BeforeAfterChart
                          title="ECL by Stage"
                          currency={context.currency}
                          rows={result.stage_movement.stages.map((s) => ({
                            label: `Stage ${s.stage}`,
                            before: s.ecl_before,
                            after: s.ecl_after,
                          }))}
                        />
                      </div>
                    ) : null}
                    {result.rating_movement?.rows?.length ? (
                      <div className="grid gap-4 lg:grid-cols-2">
                        <BeforeAfterChart
                          title="Exposure by rating"
                          measure="exposure"
                          currency={context.currency}
                          rows={result.rating_movement.rows.map((r) => ({
                            label: r.grade,
                            before: r.exposure_before,
                            after: r.exposure_after,
                          }))}
                        />
                        <BeforeAfterChart
                          title="ECL by rating"
                          currency={context.currency}
                          rows={result.rating_movement.rows.map((r) => ({
                            label: r.grade,
                            before: r.ecl_before,
                            after: r.ecl_after,
                          }))}
                        />
                      </div>
                    ) : null}
                    {result.steps?.length ? (
                      <details className="rounded-md border border-border bg-surface-sunken p-3">
                        <summary className="cursor-pointer text-[12px] font-medium">
                          How this was calculated
                        </summary>
                        <ol className="mt-2 space-y-1.5">
                          {result.steps.map((step, i) => (
                            <li key={i} className="text-[11px] text-text-secondary">
                              <span className="font-medium text-text-primary">
                                {step.step}
                              </span>{" "}
                              — {step.detail}
                            </li>
                          ))}
                        </ol>
                      </details>
                    ) : null}
                    {result.ml?.out_of_distribution?.length ? (
                      <div className="rounded-md border border-warning/40 bg-warning-muted px-3 py-2 text-[11px]">
                        {result.ml.out_of_distribution.map((o) => (
                          <p key={o.feature}>{o.message}</p>
                        ))}
                      </div>
                    ) : null}
                    {result.warnings?.length ? (
                      <ul className="space-y-1">
                        {result.warnings.map((w, i) => (
                          <li key={i} className="text-[11px] text-warning">
                            {w}
                          </li>
                        ))}
                      </ul>
                    ) : null}
                    {/* Notes are about the INSTALLATION, not this result. An
                        absent optional column costs exactly the capability it
                        names; putting that in the same amber list as "this
                        shock could not be applied" taught people to skip both,
                        so it is folded away and it is grey. */}
                    {result.notes?.length ? (
                      <details data-testid="whatif-notes">
                        <summary className="cursor-pointer text-[11px] text-text-muted">
                          Data availability ({result.notes.length})
                        </summary>
                        <ul className="mt-1 space-y-1">
                          {result.notes.map((n, i) => (
                            <li key={i} className="text-[11px] text-text-muted">
                              {n}
                            </li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                    {result.borrowers?.rows.length ? (
                      <details className="rounded-md border border-border p-3">
                        <summary className="cursor-pointer text-[12px] font-medium">
                          Borrowers ({count(result.borrowers.shown)} of{" "}
                          {count(result.borrowers.total)})
                        </summary>
                        <div className="mt-2 max-h-80 overflow-auto">
                          <table className="w-full text-[11px]">
                            <thead>
                              <tr className="text-left text-text-muted">
                                {result.borrowers.columns.slice(0, 10).map((c) => (
                                  <th key={c} className="py-1 pr-2">
                                    {c}
                                  </th>
                                ))}
                              </tr>
                            </thead>
                            <tbody>
                              {result.borrowers.rows.slice(0, 50).map((row, i) => (
                                <tr key={i} className="border-t border-border">
                                  {result.borrowers!.columns.slice(0, 10).map((c) => (
                                    <td key={c} className="py-1 pr-2 tabular-nums">
                                      {typeof row[c] === "number"
                                        ? (row[c] as number).toLocaleString(undefined, {
                                            maximumFractionDigits: 2,
                                          })
                                        : String(row[c] ?? "")}
                                    </td>
                                  ))}
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </details>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          ) : null}

          {gate ? (
            <MethodologyGate
              gate={gate}
              busy={busy}
              onChoose={(method) => void runWith(state, method)}
            />
          ) : null}

          <Composer
            value={text}
            onChange={setText}
            onSubmit={() => void send()}
            busy={busy}
            suggestions={suggestions}
            placeholder="Add another shock, change one, or ask about the book."
          />

          {last ? (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              <input
                value={saveName}
                onChange={(e) => setSaveName(e.target.value)}
                placeholder="Name this What-If"
                aria-label="Name this What-If"
                className="rounded-md border border-border bg-surface px-2 py-1 text-[12px]"
              />
              <Button size="sm" onClick={() => void save()} disabled={busy}>
                Save What-If
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void runWith(state, state.methodology === "ml" ? "delta" : "ml")}
                disabled={busy}
              >
                Change ECL methodology
              </Button>
              <span className="text-[11px] text-text-muted">
                Baseline {money(last.result.context?.baseline_ecl)} → What-If{" "}
                {money(last.result.context?.whatif_ecl)} ({signed(last.result.context?.percentage_change)})
              </span>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
