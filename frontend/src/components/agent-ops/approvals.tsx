"use client";

import Link from "next/link";
import * as React from "react";
import { Check, FileText, GitBranch, MessageSquareWarning, X } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AgentApproval } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The APPROVALS tab. §22.
 *
 * Every gate shows what §22 lists: the proposed action, the reason, the
 * evidence, the agent, the scope, the objects affected, the risk, the
 * reversibility, the approver role and the status. All of it, because an
 * approver asked to trust a one-line summary is an approver rubber-stamping.
 *
 * The gate exists BEFORE the action
 * ----------------------------------
 * That is the property the whole design rests on. Approving is what CAUSES the
 * action; it is not a receipt for one that already happened. So a queue that
 * is empty means nothing material is pending — not that nothing material has
 * occurred unrecorded.
 *
 * A decision cannot be taken twice. The backend refuses a second one, because
 * an approval that could be flipped afterwards leaves no record of which
 * decision the action was taken under.
 */
export function Approvals() {
  const [reload, setReload] = React.useState(0);
  const [loaded, setLoaded] = React.useState<{
    key: number;
    approvals: AgentApproval[];
    role: string;
    error: string;
  } | null>(null);
  const [busy, setBusy] = React.useState<number | null>(null);
  const [note, setNote] = React.useState("");
  const [message, setMessage] = React.useState("");

  React.useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const found = await api.agentApprovals();
        if (live)
          setLoaded({
            key: reload,
            approvals: found.approvals,
            role: found.role,
            error: "",
          });
      } catch (error) {
        if (live)
          setLoaded({
            key: reload,
            approvals: [],
            role: "",
            error:
              error instanceof Error
                ? error.message
                : "Approvals could not be read.",
          });
      }
    })();
    return () => {
      live = false;
    };
  }, [reload]);

  const settled = loaded && loaded.key === reload ? loaded : null;
  if (settled === null) return <Skeleton className="h-64 w-full" />;
  if (settled.error)
    return <p className="text-sm text-negative">{settled.error}</p>;

  const decide = async (id: number, decision: string) => {
    setBusy(id);
    try {
      await api.decideApproval(id, decision, note);
      setMessage(`Recorded: ${decision.replace(/_/g, " ")}.`);
      setNote("");
      setReload((n) => n + 1);
    } catch (error) {
      setMessage(
        error instanceof Error ? error.message : "That could not be recorded.",
      );
    } finally {
      setBusy(null);
    }
  };

  if (settled.approvals.length === 0) {
    return (
      <Card className="p-6 text-center text-sm text-text-secondary">
        Nothing is waiting for a decision.
        <span className="mt-1 block text-xs text-text-muted">
          A gate appears here before an agent performs anything material — a
          workflow item being sent, a case being closed, data being published.
          Until somebody approves it, the action has not happened.
        </span>
      </Card>
    );
  }

  return (
    <div className="space-y-3">
      {message && <p className="text-xs text-text-secondary">{message}</p>}

      {settled.approvals.map((approval) => (
        <Card key={approval.id} className="p-4" data-testid="agent-approval">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium text-text-primary">
                  {approval.title}
                </span>
                <Risk risk={approval.risk} />
                <span className="rounded bg-surface-sunken px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-muted">
                  {approval.reversibility.replace(/_/g, " ")}
                </span>
              </div>

              <p className="mt-1 text-xs leading-relaxed text-text-secondary">
                {approval.reason}
              </p>
              {approval.consequence && (
                <p className="mt-1 text-xs text-text-primary">
                  <MessageSquareWarning
                    className="mr-1 inline size-3 text-warning"
                    aria-hidden
                  />
                  {approval.consequence}
                </p>
              )}

              <p className="mt-1 flex flex-wrap items-center gap-x-3 text-[11px] text-text-muted">
                <span>Proposed by {approval.agent_name}</span>
                <span>Needs {approval.approver_role}</span>
                {approval.scope && <span>{approval.scope}</span>}
                {approval.created_at && (
                  <span>{approval.created_at.slice(0, 16).replace("T", " ")}</span>
                )}
              </p>

              <div className="mt-1.5 flex flex-wrap gap-2">
                {approval.run_id && (
                  <Link
                    href={`/agent-operations?run=${approval.run_id}`}
                    className="inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
                  >
                    <GitBranch className="size-3" aria-hidden />
                    Open trace
                  </Link>
                )}
                {Object.keys(approval.evidence ?? {}).length > 0 && (
                  <span className="inline-flex items-center gap-1 text-[11px] text-text-muted">
                    <FileText className="size-3" aria-hidden />
                    {Object.keys(approval.evidence).length} pieces of evidence
                  </span>
                )}
              </div>
            </div>
          </div>

          <textarea
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={2}
            placeholder="A note for the record — required for a rejection or a change request."
            className="mt-3 w-full rounded-md border border-border bg-surface-sunken px-2 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:outline-none focus:ring-2 focus:ring-accent/40"
          />

          <div className="mt-2 flex flex-wrap gap-1.5">
            <Button
              size="sm"
              disabled={busy === approval.id}
              onClick={() => void decide(approval.id, "approved")}
            >
              <Check aria-hidden />
              Approve
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={busy === approval.id || !note.trim()}
              title={note.trim() ? "" : "A rejection needs a reason"}
              onClick={() => void decide(approval.id, "rejected")}
            >
              <X aria-hidden />
              Reject
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={busy === approval.id || !note.trim()}
              title={note.trim() ? "" : "Say what should change"}
              onClick={() => void decide(approval.id, "changes_requested")}
            >
              Request change
            </Button>
          </div>
        </Card>
      ))}
    </div>
  );
}

function Risk({ risk }: { risk: string }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-[0.08em]",
        risk === "high" && "bg-negative-muted text-negative",
        risk === "medium" && "bg-warning-muted text-warning",
        risk === "low" && "bg-surface-sunken text-text-muted",
      )}
    >
      {risk} risk
    </span>
  );
}
