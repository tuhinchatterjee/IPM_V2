"use client";

import * as React from "react";
import { Check, Send, Users, X } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type WorkflowAction,
  type WorkflowPriority,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { cn } from "@/lib/utils";

/**
 * Send this to somebody. ONE control, used on every object. §47.
 *
 * A Project, an Investigation, an Analysis run and a saved Analysis are all
 * sent the same way, by the same picker, with the same seven actions — because
 * the alternative is four share dialogs that drift, and a reviewer who learns
 * one of them still has three to discover.
 *
 * What the sender chooses:
 *
 *   WHO      one or more people, one or more teams. A set, not a field.
 *   WHAT     one of §43's seven actions. Review is not the same as sign-off
 *            and neither is the same as "for your information".
 *   HOW      a priority, an optional due date, and something to say.
 *
 * The recipient list comes from the directory endpoint rather than the admin
 * user listing: choosing a reviewer needs a name and a team, and nobody needs
 * an email address or a last-login time to do it.
 */

const ACTIONS: { id: WorkflowAction; label: string; hint: string }[] = [
  { id: "review", label: "Review", hint: "Look at this and tell me what you think" },
  { id: "approve", label: "Approve", hint: "Decide whether this may be relied on" },
  { id: "sign_off", label: "Sign-off", hint: "Put your name to it" },
  { id: "comment", label: "Comment", hint: "Say something; no decision needed" },
  { id: "request_changes", label: "Request changes", hint: "Something here needs fixing" },
  { id: "assign_action", label: "Assign action", hint: "Please do this" },
  { id: "fyi", label: "FYI", hint: "Nothing to do; you should know" },
];

const PRIORITIES: WorkflowPriority[] = ["low", "normal", "high", "urgent"];

export function ShareButton({
  objectType,
  objectId,
  objectVersion,
  title,
  label = "Send",
  className,
}: {
  /** One of the reviewable object types the backend accepts. */
  objectType: string;
  objectId: string;
  /** The version being sent, where the object is versioned. §44. */
  objectVersion?: string | null;
  /** What the recipient will see in their inbox. */
  title: string;
  label?: string;
  className?: string;
}) {
  const [open, setOpen] = React.useState(false);

  return (
    <>
      <Button
        variant="ghost"
        size="sm"
        className={className}
        onClick={() => setOpen(true)}
        title="Send this to somebody for review, approval or comment"
      >
        <Send aria-hidden />
        {label}
      </Button>
      {open && (
        <ShareDialog
          objectType={objectType}
          objectId={objectId}
          objectVersion={objectVersion}
          title={title}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}

function ShareDialog({
  objectType,
  objectId,
  objectVersion,
  title,
  onClose,
}: {
  objectType: string;
  objectId: string;
  objectVersion?: string | null;
  title: string;
  onClose: () => void;
}) {
  const directory = useAsync(() => api.directory(), []);
  const [people, setPeople] = React.useState<number[]>([]);
  const [teams, setTeams] = React.useState<number[]>([]);
  const [action, setAction] = React.useState<WorkflowAction>("review");
  const [priority, setPriority] = React.useState<WorkflowPriority>("normal");
  const [due, setDue] = React.useState("");
  const [note, setNote] = React.useState("");
  // A bank with two hundred accounts renders two hundred chips, which pushes
  // everything else off the dialog and is unusable however correct it is.
  const [filter, setFilter] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [sent, setSent] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  const toggle = (list: number[], id: number) =>
    list.includes(id) ? list.filter((x) => x !== id) : [...list, id];

  async function send() {
    setBusy(true);
    setError(null);
    try {
      await api.submitForReview({
        objectType,
        objectId,
        objectVersion,
        title,
        recipients: people,
        teams,
        action,
        priority,
        dueAt: due ? new Date(due).toISOString() : null,
        note,
      });
      setSent(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : "That could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  const nobody = people.length === 0 && teams.length === 0;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-canvas/70 p-6 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Send ${title}`}
    >
      <Card className="mt-12 w-full max-w-lg overflow-hidden p-0 shadow-xl">
        <header className="flex items-start justify-between gap-3 border-b border-border px-5 py-3.5">
          <div className="min-w-0">
            <p className="meta text-text-muted">Send</p>
            <p className="mt-0.5 truncate text-sm font-medium text-text-primary">
              {title}
            </p>
          </div>
          <Button variant="ghost" size="sm" onClick={onClose} aria-label="Close">
            <X aria-hidden />
          </Button>
        </header>

        {sent ? (
          <div className="flex items-start gap-2.5 px-5 py-6">
            <Check className="mt-0.5 size-4 shrink-0 text-positive" aria-hidden />
            <div>
              <p className="text-sm text-text-primary">
                Sent. It is in their inbox now.
              </p>
              <p className="mt-1 text-xs text-text-muted">
                Nothing was emailed — CreditProbe keeps the conversation against
                the object, where the decision has to live anyway.
              </p>
              <Button size="sm" className="mt-3" onClick={onClose}>
                Done
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-4 px-5 py-4">
            <Field label="To">
              {directory.loading && (
                <p className="text-xs text-text-muted">Loading the directory…</p>
              )}
              {directory.error && (
                <p className="text-xs text-negative">{directory.error}</p>
              )}
              <input
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder="Find a person or a team"
                aria-label="Filter recipients"
                className="mb-2 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <div className="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                {matching(directory.data?.people ?? [], filter, chosen(people)).map((person) => (
                  <Chip
                    key={`u${person.id}`}
                    active={people.includes(person.id)}
                    onClick={() => setPeople((list) => toggle(list, person.id))}
                    title={`${person.role_label}${person.team ? ` · ${person.team}` : ""}`}
                  >
                    {person.name}
                  </Chip>
                ))}
                {matching(directory.data?.teams ?? [], filter, chosen(teams)).map((team) => (
                  <Chip
                    key={`t${team.id}`}
                    active={teams.includes(team.id)}
                    onClick={() => setTeams((list) => toggle(list, team.id))}
                    title={`${team.members} ${team.members === 1 ? "member" : "members"}`}
                  >
                    <Users className="size-3" aria-hidden />
                    {team.name}
                  </Chip>
                ))}
              </div>
            </Field>

            <Field label="Asking for">
              <div className="flex flex-wrap gap-1.5">
                {ACTIONS.map((option) => (
                  <Chip
                    key={option.id}
                    active={action === option.id}
                    onClick={() => setAction(option.id)}
                    title={option.hint}
                  >
                    {option.label}
                  </Chip>
                ))}
              </div>
            </Field>

            <div className="flex flex-wrap gap-4">
              <Field label="Priority">
                <div className="flex gap-1.5">
                  {PRIORITIES.map((option) => (
                    <Chip
                      key={option}
                      active={priority === option}
                      onClick={() => setPriority(option)}
                    >
                      {option}
                    </Chip>
                  ))}
                </div>
              </Field>
              <Field label="Due">
                <input
                  type="date"
                  value={due}
                  onChange={(e) => setDue(e.target.value)}
                  className="rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs text-text-primary focus:border-accent focus:outline-none"
                />
              </Field>
            </div>

            <Field label="Message">
              <textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                placeholder="What do you want them to look at?"
                className="w-full resize-none rounded-md border border-border bg-surface px-3 py-2 text-xs text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
            </Field>

            {error && <p className="text-xs text-negative">{error}</p>}

            <div className="flex items-center justify-end gap-2 border-t border-border pt-3">
              <Button variant="ghost" size="sm" onClick={onClose}>
                Cancel
              </Button>
              <Button size="sm" disabled={busy || nobody} onClick={() => void send()}>
                <Send aria-hidden />
                {nobody ? "Choose somebody" : "Send"}
              </Button>
            </div>
          </div>
        )}
      </Card>
    </div>
  );
}

/**
 * The entries worth showing: those that match what is typed, plus anything
 * already chosen.
 *
 * Keeping the chosen ones visible is the point. Typing a name to find the
 * second recipient must not hide the first — a picker that appears to have
 * forgotten a selection is one people re-click, and then send twice.
 */
function matching<T extends { id: number; name: string }>(
  entries: T[],
  filter: string,
  selected: Set<number>,
): T[] {
  const wanted = filter.trim().toLowerCase();
  if (!wanted) return entries;
  return entries.filter(
    (entry) => selected.has(entry.id) || entry.name.toLowerCase().includes(wanted),
  );
}

function chosen(ids: number[]): Set<number> {
  return new Set(ids);
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <p className="meta mb-1.5 text-text-muted">{label}</p>
      {children}
    </div>
  );
}

function Chip({
  active,
  onClick,
  title,
  children,
}: {
  active: boolean;
  onClick: () => void;
  title?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      title={title}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-[11px] transition-colors",
        "outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        active
          ? "border-accent bg-accent-muted text-accent"
          : "border-border text-text-muted hover:border-border-strong hover:text-text-secondary",
      )}
    >
      {children}
    </button>
  );
}

/** The state of a workflow item, as the badge every list shows. */
export function WorkflowStateBadge({
  state,
  label,
}: {
  state: string;
  label: string;
}) {
  const tone =
    state === "approved" || state === "completed"
      ? "positive"
      : state === "rejected"
        ? "negative"
        : state === "in_review" || state === "commented"
          ? "accent"
          : state === "withdrawn"
            ? "default"
            : "warning";
  return <Badge variant={tone as "positive" | "negative" | "accent" | "default" | "warning"}>{label}</Badge>;
}
