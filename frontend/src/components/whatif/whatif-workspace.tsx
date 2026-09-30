"use client";

/**
 * What-If Analysis (P5): see the data, define the population, load or build a
 * scenario, and hand it to the ONE scenario engine the Cockpit uses.
 *
 * Top to bottom: book + period + method availability; the conversational Ask
 * box (an ordinary Cockpit run that carries the active selection by
 * reference); the active cohort / scenario / baseline / method strip; the
 * portfolio explorer and the latest-period grid sharing one filter state; the
 * selection summary and its actions; and the applied scenario.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Download, Eraser, FlaskConical, Library, Loader2, MessageSquare, Save, Search, Send, X } from "lucide-react";

import { CockpitV4Thread } from "@/components/cockpit-v4/thread-view";
import { rememberRun, startRun } from "@/components/cockpit-v4/client";
import { DomainSwitchPlain } from "@/components/guided/domain-toggle";
import { Badge } from "@/components/ui/badge";
import { DataGrid, type GridSelection } from "@/components/workspace/data-grid";
import { PortfolioExplorer } from "@/components/whatif/portfolio-explorer";
import { ScenarioApplication } from "@/components/whatif/scenario-application";
import { count, pct, sar } from "@/lib/viz/format";
import { downloadGridCsv } from "@/lib/workspace/guided";
import { listCohorts, readObject, workspaceCohortExportUrl, type Cohort, type DomainId, type Filter } from "@/lib/workspace/objects";
import { readRun, type Run } from "@/lib/workspace/runs";
import { listScenarios, readScenario, type ScenarioCard, type ScenarioObject } from "@/lib/workspace/scenarios";
import {
  adoptThreadCohort,
  askContext,
  investigateCohort,
  readThreadCohort,
  readWhatIfContext,
  saveSelection,
  shareObject,
  summariseSelection,
  type SelectionSummary,
  type WhatIfContext,
  type WorkspaceSelection,
} from "@/lib/workspace/whatif";

function toSelection(sel: GridSelection): WorkspaceSelection | null {
  if (sel.mode === "rows" && sel.ids.length) return { mode: "rows", ids: sel.ids };
  if (sel.mode === "filtered") return sel.filters.length ? { mode: "filtered", filters: sel.filters } : { mode: "all" };
  return null;
}

export function WhatIfWorkspace() {
  const router = useRouter();
  const params = useSearchParams();
  const [domain, setDomain] = React.useState<DomainId>((params.get("domain") as DomainId) || "corporate");
  const [ctx, setCtx] = React.useState<{ domain: DomainId; value: WhatIfContext | null }>({ domain, value: null });
  const [filters, setFilters] = React.useState<Filter[]>([]);
  const [gridSel, setGridSel] = React.useState<GridSelection>({ mode: "none", ids: [], filters: [], count: 0 });
  const [summary, setSummary] = React.useState<{ key: string; value: SelectionSummary | null }>({ key: "", value: null });
  const [resetKey, setResetKey] = React.useState(0);
  const [cohort, setCohort] = React.useState<Cohort | null>(null);
  const [scenario, setScenario] = React.useState<ScenarioObject | null>(null);
  const [threadId, setThreadId] = React.useState("");
  const [threadKey, setThreadKey] = React.useState(0);
  const [question, setQuestion] = React.useState(params.get("suggest") ?? "");
  const [asking, setAsking] = React.useState(false);
  const [note, setNote] = React.useState("");
  const [error, setError] = React.useState("");
  const [panel, setPanel] = React.useState<"" | "save" | "share" | "cohorts" | "scenarios">("");
  const [applyKey, setApplyKey] = React.useState(0);
  const [activeRun, setActiveRun] = React.useState<Run | null>(null);
  const [entry] = React.useState<"whatif" | "library" | "cockpit" | "messages">(() => {
    const from = params.get("from");
    return from === "library" || from === "cockpit" || from === "messages" ? from : "whatif";
  });
  const [initialRunId, setInitialRunId] = React.useState(params.get("run") ?? "");
  const handledParams = React.useRef(false);

  const context = ctx.domain === domain ? ctx.value : null;
  React.useEffect(() => {
    readWhatIfContext(domain)
      .then((value) => setCtx({ domain, value }))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
  }, [domain]);

  // Deep links: ?cohort=, ?scenario= (Scenario Library, Early Warning, an
  // investigation's What-If suggestion) load the SAME governed objects.
  React.useEffect(() => {
    if (handledParams.current) return;
    handledParams.current = true;
    const cohortId = params.get("cohort");
    const scenarioId = params.get("scenario");
    const runId = params.get("run");
    if (runId) {
      // Reopening a run shows it exactly where it stopped: a confirmed run
      // without a method reopens at METHOD SELECTION and never executes.
      readRun(runId)
        .then(async (r) => {
          const sc = await readObject<ScenarioObject["body"]>(r.body.scenario_id, r.body.scenario_version);
          setDomain(r.body.domain_id as DomainId);
          if (r.body.cohort.object.cohort_id) {
            setCohort((await readObject<Cohort["body"]>(r.body.cohort.object.cohort_id, r.body.cohort.object.version ?? undefined)) as Cohort);
          }
          setScenario(sc as ScenarioObject);
        })
        .catch((e: unknown) => {
          setInitialRunId("");
          setError(e instanceof Error ? e.message : String(e));
        });
    }
    if (cohortId) {
      readObject<Cohort["body"]>(cohortId)
        .then((c) => {
          setDomain(c.domain_id as DomainId);
          setCohort(c as Cohort);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }
    if (scenarioId) {
      readScenario(scenarioId)
        .then((d) => {
          setDomain(d.scenario.domain_id);
          setScenario(d.scenario);
        })
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }
  }, [params]);

  const selection = toSelection(gridSel);
  const selKey = JSON.stringify({ domain, selection });
  React.useEffect(() => {
    if (!selection) return;
    const t = setTimeout(() => {
      summariseSelection(domain, selection)
        .then((value) => setSummary({ key: selKey, value }))
        .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)));
    }, 150);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selKey]);
  const selSummary = selection && summary.key === selKey ? summary.value : null;

  function changeDomain(d: DomainId) {
    if (d === domain) return;
    setDomain(d);
    setFilters([]);
    setGridSel({ mode: "none", ids: [], filters: [], count: 0 });
    if (cohort && cohort.domain_id !== d) setCohort(null);
    if (scenario && scenario.domain_id !== d) setScenario(null);
    setThreadId("");
  }

  function clearSelection() {
    setResetKey((k) => k + 1);
    setGridSel({ mode: "none", ids: [], filters: [], count: 0 });
    setCohort(null);
    setApplyKey((k) => k + 1);
    setNote("Selection cleared; no cohort is active.");
  }

  async function run<T>(fn: () => Promise<T>): Promise<T | undefined> {
    setError("");
    try {
      return await fn();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return undefined;
    }
  }

  /** The active governed cohort, saving the live selection first if needed. */
  async function ensureCohort(name?: string): Promise<Cohort | null> {
    if (selection) {
      const made = await saveSelection(domain, selection, name || `What-If selection · ${new Date().toISOString().slice(0, 16).replace("T", " ")}`);
      setCohort(made);
      setResetKey((k) => k + 1);
      setGridSel({ mode: "none", ids: [], filters: [], count: 0 });
      return made;
    }
    return cohort;
  }

  async function ask() {
    const q = question.trim();
    if (!q || asking) return;
    setAsking(true);
    await run(async () => {
      const active = await ensureCohort();
      const filtersForRun = await askContext(active?.object_id ?? "", scenario?.object_id ?? "");
      const started = await startRun({ question: q, domain, threadId: threadId || undefined, filters: filtersForRun });
      rememberRun({ runId: started.run_id, threadId: started.thread_id, cursor: 0, question: q });
      setThreadId(started.thread_id);
      setThreadKey((k) => k + 1);
      setQuestion("");
    });
    setAsking(false);
  }

  return (
    <div className="space-y-4" data-testid="whatif-workspace" data-domain={domain}>
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-semibold text-text-primary">What-If Analysis</h1>
        <DomainSwitchPlain value={domain} onChange={changeDomain} />
        {context && (
          <span className="text-xs text-text-muted" data-testid="whatif-book">
            Latest {context.period_kind} {context.period} · {context.release_id} · {context.fingerprint.slice(0, 12)} · {count(context.book.entities)} {context.grain_plural}
          </span>
        )}
        {context && (
          <span className="ml-auto flex flex-wrap gap-1" data-testid="whatif-method-badges">
            {(["delta", "ml", "user_defined"] as const).map((m) => (
              <Badge
                key={m}
                variant={context.methods[m].status === "AVAILABLE" ? "positive" : context.methods[m].status === "UNAVAILABLE" ? "negative" : "warning"}
                title={context.methods[m].reason || context.methods[m].label}
                data-testid={`whatif-method-${m}`}
                data-status={context.methods[m].status}
              >
                {m === "ml" ? "ML" : m === "delta" ? "Delta" : "User-defined"}: {context.methods[m].status.toLowerCase().replace(/_/g, " ")}
              </Badge>
            ))}
          </span>
        )}
      </header>
      {context && context.methods.ml.status === "UNAVAILABLE" && (
        <p className="text-xs text-negative" data-testid="whatif-ml-unavailable">
          ML emulator unavailable for this book — {context.methods.ml.reason}
        </p>
      )}

      <section className="rounded-xl border border-border bg-surface p-3" data-testid="whatif-ask-box">
        <label className="text-xs font-semibold text-text-secondary" htmlFor="whatif-question">
          Ask or describe a scenario — it applies to the active selection unless you say otherwise
        </label>
        <div className="mt-1 flex gap-2">
          <textarea
            id="whatif-question"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void ask();
              }
            }}
            rows={2}
            placeholder={cohort || selection ? "e.g. Increase PD by 20% and LGD by 10% for this selection" : "e.g. Which sectors carry the most ECL?"}
            className="flex-1 rounded-md border border-border bg-surface-sunken px-2 py-1 text-sm"
            data-testid="whatif-ask-input"
          />
          <button type="button" disabled={asking || !question.trim()} onClick={() => void ask()} className="inline-flex items-center gap-1 self-start rounded-md bg-accent px-3 py-2 text-sm font-medium text-accent-contrast disabled:opacity-40" data-testid="whatif-ask">
            {asking ? <Loader2 className="h-4 w-4 animate-spin" /> : <MessageSquare className="h-4 w-4" />} Ask
          </button>
        </div>
      </section>

      <ActiveStrip
        cohort={cohort}
        scenario={scenario}
        run={activeRun}
        period={context?.period ?? ""}
        onClearCohort={() => {
          setCohort(null);
          setApplyKey((k) => k + 1);
        }}
        onClearScenario={() => {
          setScenario(null);
          setApplyKey((k) => k + 1);
        }}
        onLoadCohort={() => setPanel(panel === "cohorts" ? "" : "cohorts")}
        onLoadScenario={() => setPanel(panel === "scenarios" ? "" : "scenarios")}
      />
      {panel === "cohorts" && (
        <LoadCohort
          domain={domain}
          onPick={(c) => {
            setCohort(c);
            setPanel("");
            setApplyKey((k) => k + 1);
          }}
        />
      )}
      {panel === "scenarios" && (
        <LoadScenario
          domain={domain}
          onPick={async (id) => {
            const d = await run(() => readScenario(id));
            if (d) setScenario(d.scenario);
            setPanel("");
            setApplyKey((k) => k + 1);
          }}
        />
      )}

      {threadId && (
        <section className="rounded-xl border border-accent p-3" data-testid="whatif-conversation" data-thread-id={threadId}>
          <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
            <span className="font-semibold">Conversation</span>
            <Link href={`/cockpit/thread/${threadId}`} className="text-accent underline" data-testid="whatif-open-thread">
              Open full conversation
            </Link>
            <button
              type="button"
              className="rounded border border-border px-2 py-0.5"
              data-testid="whatif-adopt-cohort"
              onClick={() =>
                run(async () => {
                  const found = await readThreadCohort(threadId);
                  if (!found.has_cohort) {
                    setNote(found.message ?? "No cohort yet.");
                    return;
                  }
                  const adopted = await adoptThreadCohort(threadId);
                  setCohort(adopted);
                  setApplyKey((k) => k + 1);
                  setNote(`Adopted the conversation's cohort ${adopted.object_id}: ${count(adopted.body.counts.entities)} exposures, membership ${adopted.body.membership_hash.slice(0, 12)}.`);
                })
              }
            >
              Use this conversation&apos;s cohort
            </button>
            <button type="button" className="ml-auto" aria-label="Close conversation" onClick={() => setThreadId("")}>
              <X className="h-3 w-3" />
            </button>
          </div>
          <div className="max-h-[70vh] overflow-auto">
            <CockpitV4Thread key={threadKey} threadId={threadId} onHome={() => setThreadId("")} />
          </div>
        </section>
      )}

      {context && (
        <PortfolioExplorer
          domain={domain}
          filters={filters}
          onFilters={setFilters}
          context={{ releaseId: context.release_id, fingerprint: context.fingerprint, period: context.period }}
        />
      )}

      <section className="sticky top-0 z-10 rounded-xl border border-border bg-surface-raised p-3 text-sm shadow-sm" data-testid="whatif-selection" data-mode={selection?.mode ?? "none"}>
        <div className="flex flex-wrap items-center gap-3">
          <span className="font-semibold">Active selection</span>
          {!selection && <span className="text-text-muted">Nothing selected. Tick rows, or use &ldquo;Select all filtered&rdquo; in the grid.</span>}
          {selection && !selSummary && <Loader2 className="h-4 w-4 animate-spin text-text-muted" />}
          {selSummary && (
            <span className="flex flex-wrap gap-3 tabular" data-testid="whatif-selection-summary" data-entities={selSummary.entities}>
              <span>
                {count(selSummary.entities)} {selSummary.grain_plural}
              </span>
              <span>
                {count(selSummary.owners)} {selSummary.owner_plural}
              </span>
              <span>EAD {sar(selSummary.ead)}</span>
              <span>Booked ECL {sar(selSummary.ecl)}</span>
              {selSummary.share_of_book_ecl != null && <span className="text-text-muted">{pct(selSummary.share_of_book_ecl)} of book ECL</span>}
              <span className="text-text-muted">
                Stage {selSummary.stage_mix.map((s) => `${s.stage}: ${count(s.n)}`).join(" · ")}
              </span>
              <span className="text-text-muted">{selSummary.period}</span>
            </span>
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-2" data-testid="whatif-actions">
          <Action testId="whatif-save-cohort" disabled={!selection} icon={<Save className="h-4 w-4" />} onClick={() => setPanel(panel === "save" ? "" : "save")}>
            Save cohort
          </Action>
          <Action
            testId="whatif-investigate"
            disabled={!selection && !cohort}
            icon={<Search className="h-4 w-4" />}
            onClick={() =>
              run(async () => {
                const active = await ensureCohort();
                if (!active) return;
                const out = await investigateCohort(active.object_id);
                router.push(`/cockpit/thread/${out.thread_id}`);
              })
            }
          >
            Investigate in Cockpit
          </Action>
          <Action
            testId="whatif-apply"
            disabled={(!selection && !cohort) || !scenario}
            icon={<FlaskConical className="h-4 w-4" />}
            onClick={() =>
              run(async () => {
                await ensureCohort();
                setApplyKey((k) => k + 1);
                setNote("");
              })
            }
            title={!scenario ? "Load a scenario first" : ""}
          >
            Apply scenario
          </Action>
          <Action testId="whatif-share" disabled={!selection && !cohort} icon={<Send className="h-4 w-4" />} onClick={() => setPanel(panel === "share" ? "" : "share")}>
            Share
          </Action>
          <Action testId="whatif-clear" disabled={!selection && !cohort} icon={<Eraser className="h-4 w-4" />} onClick={clearSelection}>
            Clear selection
          </Action>
          <Action testId="whatif-export" icon={<Download className="h-4 w-4" />} onClick={() => run(() => downloadGridCsv(domain, filters))}>
            Export filtered data
          </Action>
          {cohort && (
            <a href={workspaceCohortExportUrl(cohort.object_id)} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="whatif-export-cohort">
              <Download className="h-4 w-4" /> Export cohort
            </a>
          )}
          <Link href={`/scenarios?domain=${domain}`} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid="whatif-library">
            <Library className="h-4 w-4" /> Scenario Library
          </Link>
        </div>
        {panel === "save" && selection && (
          <InlineInput
            testId="whatif-save-form"
            label="Cohort name"
            submit="Freeze as governed cohort"
            onSubmit={(name) =>
              run(async () => {
                const made = await ensureCohort(name);
                setPanel("");
                if (made) setNote(`Saved ${count(made.body.counts.entities)} exposures as ${made.object_id} (membership ${made.body.membership_hash.slice(0, 12)}).`);
              })
            }
          />
        )}
        {panel === "share" && (
          <InlineInput
            testId="whatif-share-form"
            label="Share the cohort with (user ids, comma-separated)"
            submit="Share reference"
            onSubmit={(to) =>
              run(async () => {
                const active = await ensureCohort();
                if (!active) return;
                await shareObject(active.object_id, to.split(",").map((x) => x.trim()).filter(Boolean));
                setPanel("");
                setNote(`Shared ${active.object_id} v${active.version} — the reference, never the rows.`);
              })
            }
          />
        )}
        {note && (
          <p className="mt-2 text-xs text-positive" data-testid="whatif-note">
            {note}
          </p>
        )}
        {error && (
          <p role="alert" className="mt-2 text-xs text-negative" data-testid="whatif-error">
            {error}
          </p>
        )}
      </section>

      <DataGrid
        domain={domain}
        initialFilters={filters}
        onFiltersChange={(f) => {
          if (JSON.stringify(f) !== JSON.stringify(filters)) setFilters(f);
        }}
        selectable
        onSelection={(s: GridSelection) => setGridSel(s)}
        selectionResetKey={resetKey}
        testId="whatif-grid"
      />

      {scenario && (
        <ScenarioApplication
          key={`${applyKey}-${cohort?.object_id ?? "scope"}-${scenario.object_id}-${scenario.version}`}
          cohort={cohort}
          scenario={scenario}
          entry={entry}
          initialRunId={initialRunId}
          onRun={setActiveRun}
        />
      )}
    </div>
  );
}

function ActiveStrip({
  cohort,
  scenario,
  run,
  period,
  onClearCohort,
  onClearScenario,
  onLoadCohort,
  onLoadScenario,
}: {
  cohort: Cohort | null;
  scenario: ScenarioObject | null;
  run: Run | null;
  period: string;
  onClearCohort: () => void;
  onClearScenario: () => void;
  onLoadCohort: () => void;
  onLoadScenario: () => void;
}) {
  return (
    <section className="grid gap-2 rounded-xl border border-border bg-surface p-3 text-xs md:grid-cols-4" data-testid="whatif-strip">
      <div data-testid="whatif-strip-cohort" data-cohort-id={cohort?.object_id ?? ""}>
        <div className="text-text-muted">Cohort</div>
        {cohort ? (
          <div>
            <span className="font-semibold">{cohort.body.name}</span> · {count(cohort.body.counts.entities)} exposures · {cohort.object_id} v{cohort.version}
            <div className="font-mono text-[10px] text-text-muted">membership {cohort.body.membership_hash.slice(0, 16)}</div>
            <button type="button" onClick={onClearCohort} className="text-accent underline">
              clear
            </button>
          </div>
        ) : (
          <div className="text-text-muted">None — select rows or load a saved cohort</div>
        )}
        <button type="button" onClick={onLoadCohort} className="mt-1 text-accent underline" data-testid="whatif-load-cohort">
          Load saved cohort
        </button>
      </div>
      <div data-testid="whatif-strip-scenario" data-scenario-id={scenario?.object_id ?? ""}>
        <div className="text-text-muted">Scenario</div>
        {scenario ? (
          <div>
            <span className="font-semibold">{scenario.body.name}</span> · v{scenario.version}
            <div className="text-text-muted">{scenario.body.components.map((c) => c.label).join(" · ")}</div>
            <button type="button" onClick={onClearScenario} className="text-accent underline">
              clear
            </button>
          </div>
        ) : (
          <div className="text-text-muted">None — load one from the library or describe one above</div>
        )}
        <button type="button" onClick={onLoadScenario} className="mt-1 text-accent underline" data-testid="whatif-load-scenario">
          Load scenario
        </button>
      </div>
      <div data-testid="whatif-strip-baseline" data-mode={run?.body.baseline?.mode ?? ""}>
        <div className="text-text-muted">Baseline</div>
        {run?.body.baseline?.mode === "PRIOR_SCENARIO" ? (
          <div>Layered on {run.body.chain.map((c) => c.name).join(" → ")}</div>
        ) : run?.status === "WAITING_BASELINE_CHOICE" ? (
          <div className="text-warning">Waiting for your choice</div>
        ) : (
          <div>Original reported baseline {period}</div>
        )}
      </div>
      <div data-testid="whatif-strip-method" data-methods={(run?.body.methods_ran.length ? run.body.methods_ran : run?.body.methods_chosen ?? []).join(",")}>
        <div className="text-text-muted">Method</div>
        {run?.body.methods_ran.length ? (
          <div>Ran: {run.body.methods_ran.join(", ")}</div>
        ) : run?.body.methods_chosen.length ? (
          <div>Chosen: {run.body.methods_chosen.join(", ")}</div>
        ) : (
          <div>Not selected — chosen after the scenario is confirmed</div>
        )}
        {run && <div className="text-text-muted">run {run.object_id} · {run.status}</div>}
      </div>
    </section>
  );
}

function LoadCohort({ domain, onPick }: { domain: DomainId; onPick: (c: Cohort) => void }) {
  const [rows, setRows] = React.useState<{ object_id: string; version: number; title: string; counts: { entities: number } }[] | null>(null);
  React.useEffect(() => {
    listCohorts(domain)
      .then((r) => setRows(r.cohorts as unknown as { object_id: string; version: number; title: string; counts: { entities: number } }[]))
      .catch(() => setRows([]));
  }, [domain]);
  if (!rows) return <p className="text-xs text-text-muted">Loading saved cohorts…</p>;
  if (!rows.length) return <p className="rounded border border-border p-2 text-xs" data-testid="whatif-cohorts-empty">No saved {domain} cohorts yet — save a selection first.</p>;
  return (
    <ul className="max-h-56 space-y-1 overflow-auto rounded-lg border border-border bg-surface-sunken p-2 text-xs" data-testid="whatif-cohort-list">
      {rows.map((c) => (
        <li key={c.object_id} className="flex items-center gap-2">
          <span className="flex-1">
            {c.title} · {count(c.counts.entities)} · {c.object_id} v{c.version}
          </span>
          <button type="button" className="rounded border border-border px-2 py-0.5" data-testid="whatif-cohort-pick" onClick={() => readObject<Cohort["body"]>(c.object_id).then((o) => onPick(o as Cohort))}>
            Load
          </button>
        </li>
      ))}
    </ul>
  );
}

function LoadScenario({ domain, onPick }: { domain: DomainId; onPick: (id: string) => void }) {
  const [rows, setRows] = React.useState<ScenarioCard[] | null>(null);
  const [q, setQ] = React.useState("");
  React.useEffect(() => {
    listScenarios({ domain })
      .then((r) => setRows(r.scenarios))
      .catch(() => setRows([]));
  }, [domain]);
  if (!rows) return <p className="text-xs text-text-muted">Loading the Scenario Library…</p>;
  const shown = rows.filter((r) => !q || `${r.template_id} ${r.name} ${r.scope_label}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div className="rounded-lg border border-border bg-surface-sunken p-2 text-xs" data-testid="whatif-scenario-list">
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter scenarios…" className="mb-1 w-full rounded border border-border bg-surface px-2 py-1" data-testid="whatif-scenario-filter" />
      <ul className="max-h-56 space-y-1 overflow-auto">
        {shown.map((c) => (
          <li key={c.object_id} className="flex items-center gap-2">
            <span className="flex-1">
              <span className="font-mono text-text-muted">{c.template_id}</span> {c.name} · {c.components.map((x) => x.label).join(" · ")}
            </span>
            <button type="button" className="rounded border border-border px-2 py-0.5" data-testid="whatif-scenario-pick" data-template-id={c.template_id} onClick={() => onPick(c.object_id)}>
              Load
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

function Action({
  children,
  onClick,
  icon,
  disabled,
  testId,
  title,
}: {
  children: React.ReactNode;
  onClick: () => void;
  icon: React.ReactNode;
  disabled?: boolean;
  testId: string;
  title?: string;
}) {
  return (
    <button type="button" disabled={disabled} onClick={onClick} title={title} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm disabled:opacity-40" data-testid={testId}>
      {icon} {children}
    </button>
  );
}

function InlineInput({ label, submit, onSubmit, testId }: { label: string; submit: string; onSubmit: (v: string) => void; testId: string }) {
  const [value, setValue] = React.useState("");
  return (
    <form
      className="mt-2 flex flex-wrap items-center gap-2 text-xs"
      data-testid={testId}
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSubmit(value.trim());
      }}
    >
      <label className="text-text-muted">{label}</label>
      <input value={value} onChange={(e) => setValue(e.target.value)} className="min-w-[16rem] flex-1 rounded border border-border bg-surface px-2 py-1" data-testid={`${testId}-input`} />
      <button type="submit" className="rounded-md bg-accent px-3 py-1 font-medium text-accent-contrast" data-testid={`${testId}-submit`}>
        {submit}
      </button>
    </form>
  );
}
