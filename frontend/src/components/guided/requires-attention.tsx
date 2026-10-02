"use client";

/**
 * Requires your attention: the guided entry to the Cockpit.
 *
 * Ranked, evidence-backed issue cards for the active book, computed on the
 * server from governed metrics (no model call). Each card states the issue,
 * its severity and materiality, the movement between two published periods,
 * who is affected, a trend drawn in Plotly, the largest measured contributor
 * and a short interpretation that separates fact from inference -- then
 * offers the next steps as chips. The Ask box above stays the way to ask
 * anything else.
 */

import * as React from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, ArrowRight, FlaskConical, Loader2, Save, Search, Table2, TrendingUp } from "lucide-react";

import { PlotlyChart } from "@/components/viz/plotly-chart";
import { sparkline } from "@/lib/viz/figures";
import { count, sar } from "@/lib/viz/format";
import { SEVERITY_COLORS, SEMANTIC } from "@/lib/viz/palette";
import {
  investigateIssue,
  readIssues,
  recordStep,
  saveIssueCohort,
  type Issue,
  type IssueFeed,
} from "@/lib/workspace/guided";
import type { DomainId } from "@/lib/workspace/objects";
import { cn } from "@/lib/utils";
import { useSingleFlight } from "@/lib/workspace/single-flight";
import { withBack } from "@/lib/workspace/nav";

const SEEN_KEY = "creditprobe.guided.seen";

function seenIds(): Set<string> {
  try {
    return new Set(JSON.parse(window.localStorage.getItem(SEEN_KEY) ?? "[]") as string[]);
  } catch {
    return new Set();
  }
}

function markSeen(ids: string[]) {
  try {
    const all = Array.from(new Set([...seenIds(), ...ids])).slice(-500);
    window.localStorage.setItem(SEEN_KEY, JSON.stringify(all));
  } catch {
    /* per-viewer convenience only */
  }
}

export function SeverityPill({ severity }: { severity: string }) {
  return (
    <span
      className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wide"
      style={{ color: SEVERITY_COLORS[severity], border: `1px solid ${SEVERITY_COLORS[severity]}` }}
      data-severity={severity}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: SEVERITY_COLORS[severity] }} />
      {severity}
    </span>
  );
}

function IssueCard({
  issue,
  isNew,
  onInvestigate,
  busy,
}: {
  issue: Issue;
  isNew: boolean;
  onInvestigate: (issue: Issue, question?: string, suggestionId?: string, kind?: string) => void;
  busy: boolean;
}) {
  const router = useRouter();
  const [saved, setSaved] = React.useState("");
  // The issue population is frozen once per card: Save and What-If reuse it,
  // and a double-click never freezes it twice.
  const flight = useSingleFlight();
  const frozen = React.useRef<Awaited<ReturnType<typeof saveIssueCohort>> | null>(null);
  async function freeze() {
    if (!frozen.current) frozen.current = await saveIssueCohort(issue.issue_id);
    return frozen.current;
  }
  const m = issue.materiality;
  const fig = React.useMemo(
    () => sparkline(issue.evidence.series, issue.metric_unit, SEVERITY_COLORS[issue.severity] ?? SEMANTIC.pd),
    [issue],
  );
  const top = issue.drivers[0];
  const chips = issue.next_best_questions.primary.slice(0, 3);
  return (
    <article
      className="flex flex-col rounded-xl border border-border bg-surface p-4 shadow-[0_1px_2px_rgb(0_0_0/0.04)]"
      data-testid="issue-card"
      data-issue-id={issue.issue_id}
      data-rule={issue.detection_rule.id}
    >
      <header className="flex items-start gap-2">
        <SeverityPill severity={issue.severity} />
        {isNew && (
          <span className="rounded-full bg-accent-muted px-2 py-0.5 text-[11px] font-semibold text-accent" data-testid="issue-new">
            new
          </span>
        )}
        <span className="ml-auto text-[11px] text-text-muted">
          {issue.evidence.prior_period} → {issue.evidence.period}
        </span>
      </header>
      <h3 className="mt-2 text-sm font-semibold leading-snug text-text-primary" data-testid="issue-title">
        <button
          type="button"
          onClick={() => router.push(`/issues/${issue.issue_id}`)}
          className="text-left hover:underline"
          title="Open the evidence and the affected population"
        >
          {issue.title}
        </button>
      </h3>
      <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
        <div>
          <div className="text-text-muted">{issue.metric_name}</div>
          <div className="font-semibold tabular text-text-primary" data-testid="issue-current">
            {m.level_display}
          </div>
        </div>
        <div>
          <div className="text-text-muted">Movement</div>
          <div className="font-semibold tabular" style={{ color: (m.movement_abs ?? 0) >= 0 ? SEMANTIC.increase : SEMANTIC.decrease }}>
            {m.movement_abs === null ? "level" : m.movement_display}
          </div>
        </div>
        <div>
          <div className="text-text-muted">Affected</div>
          <div className="font-semibold tabular text-text-primary" data-testid="issue-affected">
            {count(m.affected_entities)} {issue.entity_plural}
          </div>
        </div>
        <div>
          <div className="text-text-muted">EAD</div>
          <div className="tabular">{sar(m.affected_ead)}</div>
        </div>
        <div>
          <div className="text-text-muted">ECL</div>
          <div className="tabular">{sar(m.affected_ecl)}</div>
        </div>
        <div>
          <div className="text-text-muted">Stage 2 EAD</div>
          <div className="tabular">{sar(m.stage2_ead)}</div>
        </div>
      </div>
      <div className="mt-2" data-testid="issue-sparkline">
        <PlotlyChart
          data={fig.data}
          layout={fig.layout}
          height={64}
          chrome="minimal"
          ariaLabel={`${issue.metric_name} trend, ${issue.evidence.series[0]?.period} to ${issue.evidence.period}`}
        />
      </div>
      {top && (
        <p className="mt-1 text-xs text-text-secondary">
          <TrendingUp className="mr-1 inline h-3 w-3" />
          Largest contributor:{" "}
          <button
            type="button"
            onClick={() => router.push(`/issues/${issue.issue_id}?driver=${encodeURIComponent(String(top.label))}`)}
            className="font-medium text-accent hover:underline"
            data-testid="issue-driver"
            title="Open the population behind this contributor"
          >
            {top.label}
          </button>{" "}
          ({top.display})
        </p>
      )}
      <p className="mt-1 line-clamp-3 text-xs text-text-muted" data-testid="issue-interpretation">
        {issue.interpretation}
      </p>
      <div className="mt-3 flex flex-wrap gap-1.5">
        <button
          type="button"
          disabled={busy}
          onClick={() => onInvestigate(issue)}
          className="inline-flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-accent-contrast disabled:opacity-60"
          data-testid="issue-investigate"
        >
          <Search className="h-3 w-3" /> Investigate why
        </button>
        <button
          type="button"
          onClick={() => router.push(`/issues/${issue.issue_id}`)}
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
          data-testid="issue-open"
        >
          <Table2 className="h-3 w-3" /> Evidence &amp; {issue.owner_plural}
        </button>
        <button
          type="button"
          disabled={flight.busy}
          onClick={() =>
            flight
              .run(freeze)
              .then((c) => c && setSaved(`Saved ${count(c.body.counts.entities)} as ${c.object_id}`))
              .catch((e: unknown) => setSaved(e instanceof Error ? e.message : String(e)))
          }
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
          data-testid="issue-save-cohort"
        >
          <Save className="h-3 w-3" /> Save cohort
        </button>
        <button
          type="button"
          disabled={busy || flight.busy}
          onClick={() =>
            flight
              .run(freeze)
              .then((c) => c && router.push(withBack(`/what-if?cohort=${encodeURIComponent(c.object_id)}&from=issue`)))
              .catch((e: unknown) => setSaved(e instanceof Error ? e.message : String(e)))
          }
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs"
          data-testid="issue-whatif"
          title="Freeze this exact population and open it in What-If"
        >
          <FlaskConical className="h-3 w-3" /> What-If
        </button>
      </div>
      {saved && (
        <p className="mt-1 text-[11px] text-positive" data-testid="issue-cohort-saved">
          {saved}
        </p>
      )}
      <div className="mt-3 border-t border-border pt-2">
        <p className="mb-1 text-[11px] font-medium uppercase tracking-wide text-text-muted">Ask next</p>
        <ul className="space-y-1">
          {chips.map((s) => (
            <li key={s.suggestion_id}>
              <button
                type="button"
                disabled={busy}
                onClick={() => onInvestigate(issue, s.exact_request, s.suggestion_id, s.type)}
                title={s.rationale}
                className="group flex w-full items-start gap-1 text-left text-xs text-accent hover:underline disabled:opacity-60"
                data-testid="issue-nbq"
                data-suggestion-id={s.suggestion_id}
              >
                <ArrowRight className="mt-0.5 h-3 w-3 shrink-0" />
                <span>{s.text}</span>
              </button>
            </li>
          ))}
        </ul>
      </div>
    </article>
  );
}

export function RequiresAttention({ domain }: { domain: DomainId }) {
  const router = useRouter();
  const [loaded, setLoaded] = React.useState<{ domain: DomainId; feed: IssueFeed | null; error: string }>({
    domain,
    feed: null,
    error: "",
  });
  // What is on screen belongs to the book it was read for; a switch shows
  // "loading" rather than the other book's issues.
  const feed = loaded.domain === domain ? loaded.feed : null;
  const error = loaded.domain === domain ? loaded.error : "";
  const [busy, setBusy] = React.useState(false);
  const [showAll, setShowAll] = React.useState(false);
  const [seen, setSeen] = React.useState<Set<string>>(new Set());

  React.useEffect(() => {
    readIssues(domain)
      .then((f) => {
        setSeen(seenIds());
        setLoaded({ domain, feed: f, error: "" });
        markSeen(f.issues.map((i) => i.issue_id));
      })
      .catch((e: unknown) => setLoaded({ domain, feed: null, error: e instanceof Error ? e.message : String(e) }));
  }, [domain]);

  async function investigate(issue: Issue, question?: string, suggestionId?: string, kind?: string) {
    setBusy(true);
    try {
      const opened = await investigateIssue(issue.issue_id);
      const ask = question ?? "";
      if (ask) {
        await recordStep(opened.investigation_id, { suggestion_id: suggestionId, kind, question: ask }).catch(() => undefined);
      }
      router.push(withBack(`/cockpit/thread/${opened.thread_id}${ask ? `?ask=${encodeURIComponent(ask)}` : ""}`));
    } catch (e) {
      setLoaded((prev) => ({ ...prev, domain, error: e instanceof Error ? e.message : String(e) }));
      setBusy(false);
    }
  }

  if (error) {
    return (
      <section className="rounded-lg border border-border p-4 text-sm text-negative" data-testid="requires-attention-error">
        <AlertTriangle className="mr-1 inline h-4 w-4" /> Requires Attention could not be computed: {error}
      </section>
    );
  }
  if (!feed) {
    return (
      <section className="rounded-lg border border-border p-4" data-testid="requires-attention-loading">
        <p className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Measuring what changed in this book…
        </p>
        <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-56 animate-pulse rounded-xl bg-surface-sunken" />
          ))}
        </div>
      </section>
    );
  }
  const fresh = feed.issues.filter((i) => !seen.has(i.issue_id)).length;
  const shown = showAll ? feed.issues : feed.issues.slice(0, 6);
  return (
    <section data-testid="requires-attention" data-count={feed.issues.length} aria-label="Requires your attention">
      <header className="mb-3 flex flex-wrap items-baseline gap-2">
        <h2 className="text-base font-semibold text-text-primary">Requires your attention</h2>
        <span className="text-sm text-text-secondary" data-testid="requires-attention-summary">
          {feed.issues.length} item{feed.issues.length === 1 ? "" : "s"} require attention
          {fresh ? `; ${fresh} new` : ""} · {feed.prior_period} → {feed.period}
        </span>
        <span className="ml-auto text-[11px] text-text-muted">
          {feed.release_id} · rules {feed.ruleset} · {feed.server_ms} ms · no model call
        </span>
      </header>
      {feed.issues.length === 0 ? (
        <p className="rounded-lg border border-border p-4 text-sm text-text-muted" data-testid="requires-attention-none">
          No detector found a material change between {feed.prior_period} and {feed.period}. {feed.detectors.length}{" "}
          rules ran; each is listed in the trace.
        </p>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {shown.map((issue) => (
            <IssueCard key={issue.issue_id} issue={issue} isNew={!seen.has(issue.issue_id)} onInvestigate={investigate} busy={busy} />
          ))}
        </div>
      )}
      {feed.issues.length > 6 && (
        <button type="button" onClick={() => setShowAll((v) => !v)} className="mt-2 text-sm text-accent underline" data-testid="requires-attention-more">
          {showAll ? "Show fewer" : `Show all ${feed.issues.length}`}
        </button>
      )}
      {busy && (
        <p className="mt-2 flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Opening an investigation with the evidence already bound…
        </p>
      )}
      <p className="mt-2 text-[11px] text-text-muted">
        Drivers are measured contributions — associations in the published data, not established causes. Figures are
        synthetic demonstration data.
      </p>
    </section>
  );
}

export { cn };
