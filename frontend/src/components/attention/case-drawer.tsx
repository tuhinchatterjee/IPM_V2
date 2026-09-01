"use client";

import Link from "next/link";
import * as React from "react";
import {
  Check,
  Clock,
  FolderPlus,
  GitBranch,
  MessageSquare,
  Search,
  Send,
  UserPlus,
  X,
} from "lucide-react";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type RiskCase } from "@/lib/api";
import { technical } from "@/lib/format";
import { cn } from "@/lib/utils";

import {
  LEVEL_LABEL,
  SEVERITY_LABEL,
  SEVERITY_TONE,
  coverage,
  dueLabel,
  format,
} from "./severity";

/**
 * The Risk Case drawer. §47.
 *
 * §47's own section list, in its order:
 *
 *     BOTTOM LINE · WHY IT MATTERS · SIGNALS · TIMELINE · EVIDENCE ·
 *     ANALYSES · TRACE · OWNER & WORKFLOW · COMMENTS · NEXT ACTIONS
 *
 * "Avoid opening a generic chat unless the user chooses Investigate" — so this
 * is a reading surface with actions at the end, not a conversation. The chat
 * exists behind exactly one button.
 *
 * The severity arithmetic is on screen
 * ------------------------------------
 * §39 requires the formula to be transparent, and a number with no arithmetic
 * behind it is what the LLM is not allowed to produce. So the nine components,
 * their weights and their contributions are one click away on every case — a
 * reader can see that "high" came from exposure and magnitude rather than from
 * a sentence.
 */
export function CaseDrawer({
  caseId,
  onClose,
  onChanged,
  onInvestigate,
}: {
  caseId: number;
  onClose: () => void;
  onChanged?: () => void;
  onInvestigate?: (investigationId: number) => void;
}) {
  const [loaded, setLoaded] = React.useState<{
    caseId: number;
    found: RiskCase | null;
    error: string;
  } | null>(null);
  const [busy, setBusy] = React.useState("");
  const [note, setNote] = React.useState("");

  const refresh = React.useCallback(
    (found: RiskCase) => {
      setLoaded({ caseId, found, error: "" });
      onChanged?.();
    },
    [caseId, onChanged],
  );

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await api.riskCase(caseId);
        if (live) setLoaded({ caseId, found, error: "" });
      } catch (error) {
        if (live)
          setLoaded({
            caseId,
            found: null,
            error:
              error instanceof Error
                ? error.message
                : "That case could not be loaded.",
          });
      }
    })();
    return () => {
      live = false;
    };
  }, [caseId]);

  // Escape closes. A drawer that traps the reader is a modal, and this is not
  // asking them anything.
  React.useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const settled = loaded && loaded.caseId === caseId ? loaded : null;
  const found = settled?.found ?? null;

  const act = async (id: string, run: () => Promise<RiskCase>) => {
    setBusy(id);
    try {
      refresh(await run());
      setNote("");
    } catch (error) {
      setLoaded((now) =>
        now
          ? {
              ...now,
              error:
                error instanceof Error
                  ? error.message
                  : "That could not be done.",
            }
          : now,
      );
    } finally {
      setBusy("");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex justify-end"
      role="dialog"
      aria-modal="true"
      aria-label={found ? found.title : "Risk case"}
      data-testid="case-drawer"
    >
      <button
        type="button"
        className="absolute inset-0 bg-black/25"
        onClick={onClose}
        aria-label="Close"
        tabIndex={-1}
      />

      <aside className="relative flex h-full w-full max-w-xl flex-col overflow-y-auto border-l border-border bg-surface shadow-lg">
        <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-border bg-surface px-4 py-3">
          <div className="min-w-0 flex-1">
            {found && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span
                    className={cn(
                      "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
                      SEVERITY_TONE[found.severity] ?? "",
                    )}
                  >
                    {SEVERITY_LABEL[found.severity] ?? found.severity}
                  </span>
                  <span className="text-[11px] uppercase tracking-[0.09em] text-text-muted">
                    {LEVEL_LABEL[found.level] ?? found.level}
                  </span>
                  <span className="mono text-[11px] text-text-muted">
                    {found.case_key}
                  </span>
                </div>
                <h2 className="mt-1 text-base font-semibold leading-snug text-text-primary">
                  {found.title}
                </h2>
              </>
            )}
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X aria-hidden />
          </Button>
        </header>

        <div className="flex-1 space-y-5 px-4 py-4">
          {settled === null && <Skeleton className="h-64 w-full" />}
          {settled?.error && (
            <p className="text-sm text-negative">{settled.error}</p>
          )}

          {found && (
            <>
              <Section title="Bottom line">
                <p className="text-sm leading-relaxed text-text-primary">
                  {found.conclusion}
                </p>
                <Facts found={found} />
              </Section>

              <Section title="Why it matters">
                <p className="text-sm leading-relaxed text-text-secondary">
                  {found.why}
                </p>
                <Severity found={found} />
              </Section>

              {found.signals.length > 0 && (
                <Section title="Signals">
                  <ul className="space-y-1">
                    {found.signals.map((signal, index) => (
                      <li
                        key={index}
                        className="flex items-start gap-2 text-xs text-text-secondary"
                      >
                        <span
                          className="mt-1.5 size-1 shrink-0 rounded-full bg-text-muted"
                          aria-hidden
                        />
                        {signal}
                      </li>
                    ))}
                  </ul>
                </Section>
              )}

              <Section title="Evidence">
                <p className="text-xs text-text-secondary">
                  {coverage(found)}
                  {found.analyses.length > 0 && (
                    <>
                      {" · "}
                      {found.analyses.length} governed{" "}
                      {found.analyses.length === 1 ? "analysis" : "analyses"}
                    </>
                  )}
                </p>
                {found.analyses.length > 0 && (
                  <div className="mt-1.5 flex flex-wrap gap-1.5">
                    {found.analyses.map((runId) => (
                      <Link
                        key={runId}
                        href={`/trace/${runId}`}
                        className="inline-flex items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[11px] text-accent hover:bg-surface-hover"
                      >
                        <GitBranch className="size-3" aria-hidden />
                        Analysis {runId}
                      </Link>
                    ))}
                  </div>
                )}
                {found.agent_run_id && (
                  <p className="mt-1.5 text-[11px] text-text-muted">
                    Raised by agentic run{" "}
                    <span className="mono">{found.agent_run_id}</span>, from a
                    deterministic screen of the published book.
                  </p>
                )}
              </Section>

              <Section title="Timeline">
                <ol className="space-y-1.5">
                  {found.timeline.map((event) => (
                    <li key={event.id} className="flex items-start gap-2">
                      <span className="mono mt-0.5 shrink-0 text-[10px] text-text-muted">
                        {(event.at ?? "").slice(0, 16).replace("T", " ")}
                      </span>
                      <span className="min-w-0 flex-1 text-xs text-text-secondary">
                        {event.to_status && event.from_status ? (
                          <span className="text-text-primary">
                            {event.from_status} → {event.to_status}.{" "}
                          </span>
                        ) : null}
                        {event.body}
                        {event.actor_label && (
                          <span className="text-text-muted">
                            {" "}
                            — {event.actor_label}
                          </span>
                        )}
                      </span>
                    </li>
                  ))}
                </ol>
              </Section>

              <Section title="Owner and workflow">
                <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                  <Row label="Status" value={found.status_label} />
                  <Row
                    label="Owner"
                    value={found.owner_id ? `User ${found.owner_id}` : "Nobody yet"}
                  />
                  <Row label="Due" value={dueLabel(found) || "Not set"} />
                  <Row
                    label="Investigation"
                    value={
                      found.investigation_id
                        ? `#${found.investigation_id}`
                        : "None"
                    }
                  />
                  <Row
                    label="Project"
                    value={found.project_id ? `#${found.project_id}` : "None"}
                  />
                  <Row
                    label="Workflow"
                    value={
                      found.workflow_item_id
                        ? `#${found.workflow_item_id}`
                        : "Not sent"
                    }
                  />
                </dl>
              </Section>

              <Section title="Comments">
                <textarea
                  value={note}
                  onChange={(event) => setNote(event.target.value)}
                  rows={2}
                  placeholder="Add a note for whoever picks this up."
                  className="w-full rounded-md border border-border bg-surface-sunken px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/40"
                />
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-1"
                  disabled={!note.trim() || busy === "comment"}
                  onClick={() =>
                    void act("comment", () =>
                      api.commentOnRiskCase(caseId, note.trim()),
                    )
                  }
                >
                  <MessageSquare aria-hidden />
                  Comment
                </Button>
              </Section>

              <Section title="Next actions">
                <Actions
                  found={found}
                  busy={busy}
                  note={note}
                  act={act}
                  onInvestigate={onInvestigate}
                />
              </Section>
            </>
          )}
        </div>
      </aside>
    </div>
  );
}

/**
 * §47's NEXT ACTIONS, from the case's own state.
 *
 * The backend decides which actions apply — offering "Investigate" on a case
 * that already has one, or "Resolve" on a dismissed case, is offering
 * something that will not work — and this renders what it returned.
 */
function Actions({
  found,
  busy,
  note,
  act,
  onInvestigate,
}: {
  found: RiskCase;
  busy: string;
  note: string;
  act: (id: string, run: () => Promise<RiskCase>) => Promise<void>;
  onInvestigate?: (investigationId: number) => void;
}) {
  const [opening, setOpening] = React.useState(false);

  const investigate = async () => {
    setOpening(true);
    try {
      const found_ = await api.investigateRiskCase(found.id);
      onInvestigate?.(found_.investigation_id);
    } finally {
      setOpening(false);
    }
  };

  const has = (id: string) => found.next_actions.some((a) => a.id === id);

  return (
    <div className="flex flex-wrap gap-1.5">
      {(has("investigate") || has("open_investigation")) && (
        <Button
          size="sm"
          data-testid="case-investigate"
          onClick={() => void investigate()}
          disabled={opening}
        >
          <Search aria-hidden />
          {found.investigation_id ? "Open investigation" : "Investigate"}
        </Button>
      )}
      {has("add_to_project") && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy === "project"}
          onClick={() =>
            void act("project", async () => {
              await api.riskCaseToProject(found.id, null);
              return api.riskCase(found.id);
            })
          }
        >
          <FolderPlus aria-hidden />
          New project
        </Button>
      )}
      {has("assign") && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy === "assign"}
          onClick={() =>
            void act("assign", () =>
              api.assignRiskCase(found.id, null, "Triaged."),
            )
          }
        >
          <UserPlus aria-hidden />
          Triage
        </Button>
      )}
      {has("review") && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy === "review"}
          onClick={() =>
            void act("review", async () => {
              await api.sendRiskCaseForReview(found.id, {
                recipients: [],
                teams: [],
                message: note,
              });
              return api.riskCase(found.id);
            })
          }
        >
          <Send aria-hidden />
          Send for review
        </Button>
      )}
      {has("snooze") && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy === "snooze"}
          onClick={() =>
            void act("snooze", () => api.snoozeRiskCase(found.id, 7, note))
          }
        >
          <Clock aria-hidden />
          Snooze 7d
        </Button>
      )}
      {has("dismiss") && (
        <Button
          variant="ghost"
          size="sm"
          disabled={busy === "dismiss" || !note.trim()}
          title={
            note.trim()
              ? "Close this case with the reason above"
              : "A dismissal needs a reason — write one above"
          }
          onClick={() =>
            void act("dismiss", () =>
              api.dismissRiskCase(found.id, note.trim()),
            )
          }
        >
          <X aria-hidden />
          Dismiss
        </Button>
      )}
      {has("reopen") && (
        <Button
          variant="outline"
          size="sm"
          disabled={busy === "reopen"}
          onClick={() =>
            void act("reopen", () =>
              api.moveRiskCase(found.id, "TRIAGED", note || "Reopened."),
            )
          }
        >
          <Check aria-hidden />
          Reopen
        </Button>
      )}
    </div>
  );
}

/** The figures at the top of the drawer, from the case's own metrics. */
function Facts({ found }: { found: RiskCase }) {
  const facts: [string, string][] = [];
  if (found.exposure != null)
    facts.push([
      "Exposure",
      `${format(found.exposure)} ${found.exposure_unit || ""}`.trim(),
    ]);
  if (found.entity) facts.push([LEVEL_LABEL[found.level] ?? "Entity", found.entity]);
  facts.push(["Period", found.prior_period
    ? `${found.prior_period} → ${found.period}`
    : found.period]);
  if (!facts.length) return null;
  return (
    <dl className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs sm:grid-cols-3">
      {facts.map(([label, value]) => (
        <Row key={label} label={label} value={value} />
      ))}
    </dl>
  );
}

/**
 * §39's arithmetic, on screen.
 *
 * Collapsed, because most readers want the band and not the nine components —
 * but present, because the one reader who asks "why is this high" deserves an
 * answer that is not "the model said so".
 */
function Severity({ found }: { found: RiskCase }) {
  const [open, setOpen] = React.useState(false);
  const detail = found.severity_detail;
  if (!detail?.components?.length) return null;

  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={() => setOpen((now) => !now)}
        aria-expanded={open}
        className="text-[11px] text-accent hover:underline"
      >
        {open ? "Hide" : "How"} the {found.severity} severity was calculated
      </button>
      {open && (
        <div className="mt-1.5 rounded-md border border-border bg-surface-sunken p-2.5">
          <p className="text-[11px] text-text-secondary">
            {detail.explanation}
          </p>
          <p className="mt-1 text-[10px] text-text-muted">
            Formula version {detail.version} · score{" "}
            {technical(detail.score)}
          </p>
          <ul className="mt-1.5 space-y-0.5">
            {detail.components.map((component) => (
              <li
                key={component.key}
                className="flex items-baseline justify-between gap-3 text-[11px]"
              >
                <span className="min-w-0 flex-1 truncate text-text-secondary">
                  {component.label}
                </span>
                <span className="mono shrink-0 text-text-muted tabular">
                  {component.value.toFixed(2)} × {component.weight.toFixed(2)} ={" "}
                  {technical(component.contribution)}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <h3 className="meta mb-1.5 text-text-muted">{title}</h3>
      {children}
    </section>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0">
      <dt className="text-[10px] uppercase tracking-[0.08em] text-text-muted">
        {label}
      </dt>
      <dd className="truncate text-text-secondary">{value}</dd>
    </div>
  );
}
