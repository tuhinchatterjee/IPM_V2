"use client";

import * as React from "react";

import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { ScvComment } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Add Comment, on every category card and every piece of test evidence. §15.
 *
 * The design decision that shapes this component
 * ------------------------------------------------
 * A comment on a validation result is not a chat message. It is a governance
 * statement, and §15 says what it has to carry: who wrote it and when, what
 * they concluded, how severe THEY think it is, what they attached, what a
 * reviewer said back, whether it is open or resolved — and, crucially, the
 * exact model, run, test and data version it was written against.
 *
 * So the composer is a short form rather than a text box, and every field on
 * it is one §15 names. The alternative — a free-text note — loses the
 * assessment, which is the field a committee reads.
 *
 * What it refuses to do
 * -----------------------
 * It never lets a comment change a result. There is no control here that
 * writes to a value, a state or a limit, and the author's own severity is
 * rendered with the word "author's" attached wherever it appears beside a
 * measured state. §15: a user may disagree, or add a justification, and may
 * not silently change an observed metric or relabel an unrun check as passed.
 *
 * The run marker
 * ----------------
 * A comment written about an earlier run stays visible and says so. Hiding
 * it would be the same mistake as silently re-attaching it: a reader would
 * never learn that somebody had already looked at this test and said
 * something about it.
 */

const KIND_LABEL: Record<string, string> = {
  COMMENT: "Note",
  ANALYST: "Analyst assessment",
  REVIEWER: "Reviewer response",
  APPROVER: "Approver decision",
};

const KIND_TONE: Record<string, string> = {
  COMMENT: "border-border",
  ANALYST: "border-accent/40",
  REVIEWER: "border-border-strong",
  APPROVER: "border-positive/40",
};

const ASSESSMENT_LABEL: Record<string, string> = {
  AGREED: "Agreed",
  DISAGREED: "Disagreed",
  ACCEPTED_WITH_ACTION: "Accepted, with action",
  NEEDS_EVIDENCE: "Needs evidence",
  NOT_ASSESSED: "Not assessed",
};

const SEVERITIES = ["", "CRITICAL", "HIGH", "MEDIUM", "LOW", "OBSERVATION"];

export type CommentTarget = {
  target: "scv_category" | "scv_result" | "scv_finding" | "scv_conclusion";
  category?: string;
  testId?: string;
  findingId?: string;
};

function keyOf(modelId: string, target: CommentTarget): string {
  if (target.target === "scv_category") return `${modelId}:${target.category}`;
  if (target.target === "scv_result") return `${modelId}:${target.testId}`;
  if (target.target === "scv_finding") return `${modelId}:${target.findingId}`;
  return modelId;
}

/** Comments live above this component so one fetch serves the whole page. */
export type CommentBook = {
  all: ScvComment[];
  runKey: string;
  modelId: string;
  reload: () => void;
};

export function useComments(modelId: string, runKey: string): CommentBook {
  const [all, setAll] = React.useState<ScvComment[]>([]);
  const [tick, setTick] = React.useState(0);
  React.useEffect(() => {
    if (!modelId) { setAll([]); return; }
    let alive = true;
    api.scorecardValidation.comments(modelId, { runKey })
      .then((got) => { if (alive) setAll(got.comments); })
      // A commentary that cannot be loaded must not take the numbers down
      // with it. The screen shows the results and no comments, which is
      // visibly different from showing results with none.
      .catch(() => { if (alive) setAll([]); });
    return () => { alive = false; };
  }, [modelId, runKey, tick]);
  return {
    all, runKey, modelId,
    reload: React.useCallback(() => setTick((n) => n + 1), []),
  };
}

export function commentsFor(book: CommentBook,
                            target: CommentTarget): ScvComment[] {
  const key = keyOf(book.modelId, target);
  return book.all.filter((one) => one.object_id === key
    && one.target === target.target);
}

function when(stamp: string): string {
  if (!stamp) return "";
  const at = new Date(stamp);
  return Number.isNaN(at.getTime()) ? stamp : at.toLocaleString();
}

/** One comment, with its provenance and its edit history on request. */
function One({ comment, onChanged }: {
  comment: ScvComment; onChanged: () => void;
}) {
  const [history, setHistory] = React.useState<ScvComment[] | null>(null);
  const [editing, setEditing] = React.useState(false);
  const [draft, setDraft] = React.useState(comment.body);
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState("");

  async function save() {
    if (!draft.trim()) return;
    setBusy(true);
    setFailed("");
    try {
      await api.scorecardValidation.editComment(comment.id, { body: draft });
      setEditing(false);
      onChanged();
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function toggle() {
    setBusy(true);
    try {
      await api.scorecardValidation.resolveComment(
        comment.id, !comment.resolved);
      onChanged();
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function showHistory() {
    if (history) { setHistory(null); return; }
    try {
      const got = await api.scorecardValidation.commentHistory(comment.id);
      setHistory(got.versions);
    } catch (error) {
      setFailed((error as Error).message);
    }
  }

  const foreign = comment.made_against_this_run === false;

  return (
    <div className={cn("rounded-md border-l-2 bg-surface-hover/40 px-3 py-2",
                       KIND_TONE[comment.kind] ?? "border-border",
                       comment.resolved && "opacity-60")}>
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="outline">{KIND_LABEL[comment.kind] ?? comment.kind}</Badge>
        {comment.assessment && (
          <span className="text-[11px] font-semibold uppercase tracking-wider text-text">
            {ASSESSMENT_LABEL[comment.assessment] ?? comment.assessment}
          </span>
        )}
        {comment.severity && (
          // Labelled, every time it appears. A severity on an opinion sitting
          // unlabelled beside a severity on a measurement is the pair a
          // reader merges without noticing.
          <span className="text-[11px] text-warning">
            author&rsquo;s severity {comment.severity}
          </span>
        )}
        {comment.resolved && <Badge variant="outline">resolved</Badge>}
        <span className="ml-auto text-[11px] text-text-muted">
          {comment.author || "unattributed"} · {when(comment.created_at)}
        </span>
      </div>

      {editing ? (
        <div className="mt-2 space-y-2">
          <textarea
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            rows={3}
            className="w-full rounded border border-border bg-surface px-2 py-1.5 text-sm text-text"
          />
          <div className="flex gap-2">
            <button
              type="button" onClick={save} disabled={busy}
              className="rounded border border-border-strong px-2.5 py-1 text-[11px] text-text disabled:opacity-50"
            >
              {busy ? "Saving…" : "Save as a new version"}
            </button>
            <button
              type="button" onClick={() => { setEditing(false); setDraft(comment.body); }}
              className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted"
            >
              Cancel
            </button>
          </div>
          <p className="text-[10px] leading-relaxed text-text-muted">
            An edit writes a new version and keeps this one. A comment is
            evidence; what it said before is part of the record.
          </p>
        </div>
      ) : (
        <p className="mt-1.5 whitespace-pre-wrap text-sm leading-relaxed text-text">
          {comment.body}
        </p>
      )}

      {comment.attachments.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {comment.attachments.map((one, at) => (
            <Badge key={`${one.reference ?? at}`} variant="outline">
              {one.label ?? one.reference ?? "attachment"}
            </Badge>
          ))}
        </div>
      )}

      <p className={cn("mt-2 text-[10px] leading-relaxed",
                       foreign ? "text-warning" : "text-text-muted")}>
        {comment.run_note}
        {comment.context?.test_id ? ` · ${comment.context.test_id}` : ""}
        {comment.context?.model_version
          ? ` · model ${comment.context.model_version}` : ""}
        {comment.context?.dataset_version
          ? ` · data ${String(comment.context.dataset_version).slice(0, 12)}`
          : ""}
      </p>

      <div className="mt-2 flex flex-wrap gap-3">
        {!editing && (
          <button type="button" onClick={() => setEditing(true)}
                  className="text-[11px] text-text-muted hover:text-text">
            Edit
          </button>
        )}
        <button type="button" onClick={toggle} disabled={busy}
                className="text-[11px] text-text-muted hover:text-text">
          {comment.resolved ? "Reopen" : "Resolve"}
        </button>
        {comment.supersedes_id !== null && (
          <button type="button" onClick={showHistory}
                  className="text-[11px] text-text-muted hover:text-text">
            {history ? "Hide history" : "History"}
          </button>
        )}
      </div>

      {failed && <p className="mt-1 text-[11px] text-negative">{failed}</p>}

      {history && (
        <ol className="mt-2 space-y-1.5 border-t border-border pt-2">
          {history.map((version, at) => (
            <li key={version.id} className="text-[11px] text-text-muted">
              <span className="font-mono">v{at + 1}</span>{" "}
              {when(version.created_at)} —{" "}
              {ASSESSMENT_LABEL[version.assessment] ?? version.assessment}
              <p className="mt-0.5 whitespace-pre-wrap text-text-muted">
                {version.body}
              </p>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

/** The composer plus the thread, for one commentable thing. */
export function CommentThread({ book, target, label }: {
  book: CommentBook; target: CommentTarget; label?: string;
}) {
  const mine = commentsFor(book, target);
  const [open, setOpen] = React.useState(false);
  const [body, setBody] = React.useState("");
  const [kind, setKind] = React.useState("ANALYST");
  const [assessment, setAssessment] = React.useState("NOT_ASSESSED");
  const [severity, setSeverity] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState("");

  async function post() {
    if (!body.trim()) return;
    setBusy(true);
    setFailed("");
    try {
      await api.scorecardValidation.addComment(book.modelId, {
        target: target.target,
        category: target.category ?? "",
        test_id: target.testId ?? "",
        finding_id: target.findingId ?? "",
        run_key: book.runKey,
        body, kind, assessment, severity,
      });
      setBody("");
      setSeverity("");
      setAssessment("NOT_ASSESSED");
      setOpen(false);
      book.reload();
    } catch (error) {
      setFailed((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const unresolved = mine.filter((one) => !one.resolved).length;

  return (
    <div className="space-y-2" data-testid="scv-comments">
      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => setOpen((was) => !was)}
          data-testid="scv-add-comment"
          className="rounded border border-border px-2.5 py-1 text-[11px] text-text-muted transition-colors hover:border-border-strong hover:text-text"
        >
          {open ? "Cancel" : "Add comment"}
        </button>
        {mine.length > 0 && (
          <span className="text-[11px] text-text-muted"
                data-testid="scv-comment-count">
            {mine.length} comment{mine.length === 1 ? "" : "s"}
            {unresolved ? `, ${unresolved} open` : ", all resolved"}
            {label ? ` on ${label}` : ""}
          </span>
        )}
      </div>

      {open && (
        <div className="space-y-2 rounded-md border border-border bg-surface p-3">
          <textarea
            value={body}
            onChange={(e) => setBody(e.target.value)}
            rows={3}
            data-testid="scv-comment-body"
            placeholder="What does this result mean, and what would change your mind?"
            className="w-full rounded border border-border bg-surface-hover px-2 py-1.5 text-sm text-text"
          />
          <div className="flex flex-wrap gap-3">
            <label className="text-[11px] text-text-muted">
              Kind{" "}
              <select
                value={kind} onChange={(e) => setKind(e.target.value)}
                data-testid="scv-comment-kind"
                className="rounded border border-border bg-surface px-1.5 py-1 text-[11px] text-text"
              >
                {Object.entries(KIND_LABEL).map(([key, said]) => (
                  <option key={key} value={key}>{said}</option>
                ))}
              </select>
            </label>
            <label className="text-[11px] text-text-muted">
              Assessment{" "}
              <select
                value={assessment} onChange={(e) => setAssessment(e.target.value)}
                data-testid="scv-comment-assessment"
                className="rounded border border-border bg-surface px-1.5 py-1 text-[11px] text-text"
              >
                {Object.entries(ASSESSMENT_LABEL).map(([key, said]) => (
                  <option key={key} value={key}>{said}</option>
                ))}
              </select>
            </label>
            <label className="text-[11px] text-text-muted">
              Your severity{" "}
              <select
                value={severity} onChange={(e) => setSeverity(e.target.value)}
                className="rounded border border-border bg-surface px-1.5 py-1 text-[11px] text-text"
              >
                {SEVERITIES.map((one) => (
                  <option key={one || "none"} value={one}>{one || "none"}</option>
                ))}
              </select>
            </label>
          </div>
          <button
            type="button" onClick={post} disabled={busy || !body.trim()}
            data-testid="scv-comment-save"
            className="rounded border border-border-strong bg-surface-hover px-3 py-1.5 text-[11px] font-medium text-text disabled:opacity-50"
          >
            {busy ? "Saving…" : "Save comment"}
          </button>
          {failed && <p className="text-[11px] text-negative">{failed}</p>}
          <p className="text-[10px] leading-relaxed text-text-muted">
            Recorded against this model, this run and this test, with your
            name and the time. Your severity is yours and is printed beside
            the measured state, never in place of it — a comment cannot
            change a measured value or mark an unrun check as passed.
          </p>
        </div>
      )}

      {mine.length > 0 && (
        <div className="space-y-2">
          {mine.map((one) => (
            <One key={one.id} comment={one} onChanged={book.reload} />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Everything anybody has said about this scorecard, in one place. §15.
 *
 * The drawer exists because the per-card threads answer "what was said about
 * THIS" and a validator signing an opinion has the other question: what is
 * still open anywhere. Those are different views of one set of rows, and the
 * second one cannot be assembled by scrolling.
 */
export function NotesDrawer({ book, findings }: {
  book: CommentBook; findings: number;
}) {
  const [open, setOpen] = React.useState(false);
  const unresolved = book.all.filter((one) => !one.resolved);
  const disagreements = book.all.filter(
    (one) => one.assessment === "DISAGREED");
  // Only when there IS a run on screen to be earlier than. After a reload,
  // before anything has been run, every comment is "not this run" simply
  // because there is no run — and saying "written against an earlier run"
  // there tells the reader something that is not true of the screen they
  // are looking at.
  const elsewhere = book.runKey
    ? book.all.filter((one) => one.made_against_this_run === false
        && one.run_key && one.run_key !== book.runKey)
    : [];

  return (
    <div className="rounded-lg border border-border bg-surface"
         data-testid="scv-notes-drawer">
      <button
        type="button"
        onClick={() => setOpen((was) => !was)}
        className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <span className="text-sm font-semibold text-text">
          Findings and notes
        </span>
        <span className="text-[11px] text-text-muted">
          {findings} system finding{findings === 1 ? "" : "s"} ·{" "}
          {book.all.length} comment{book.all.length === 1 ? "" : "s"}
          {unresolved.length ? `, ${unresolved.length} open` : ""}
          {" "}— {open ? "hide" : "show"}
        </span>
      </button>
      {open && (
        <div className="space-y-3 border-t border-border p-4">
          <p className="max-w-3xl text-[11px] leading-relaxed text-text-muted">
            System-calculated findings are listed with the tests that produced
            them. What is below is what PEOPLE have said: an analyst&rsquo;s
            assessment, a reviewer&rsquo;s response and an approver&rsquo;s
            decision are recorded as different kinds and are never merged into
            one voice.
          </p>
          {disagreements.length > 0 && (
            <p className="text-[11px] text-warning">
              {disagreements.length} recorded disagreement
              {disagreements.length === 1 ? "" : "s"} with the engine. The
              measured values are unchanged and are printed beside them.
            </p>
          )}
          {elsewhere.length > 0 && (
            <p className="text-[11px] text-warning">
              {elsewhere.length} comment{elsewhere.length === 1 ? "" : "s"}{" "}
              {elsewhere.length === 1 ? "was" : "were"} written against an
              earlier run and {elsewhere.length === 1 ? "refers" : "refer"} to
              that run&rsquo;s numbers.
            </p>
          )}
          {book.all.length === 0 ? (
            <p className="text-sm text-text-muted">
              Nobody has commented on this scorecard yet. Add one from any
              category card or piece of evidence.
            </p>
          ) : (
            <div className="space-y-2">
              {book.all.map((one) => (
                <One key={one.id} comment={one} onChanged={book.reload} />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * The overall validation opinion — an APPROVER decision, not a computed one.
 *
 * There is deliberately no engine-written conclusion above this. §21's rule
 * about a single number for "is this scorecard sound" applies to a sentence
 * as much as to a score: it is the thing a committee would quote and the
 * thing no validator would sign, and generating one would make every honest
 * refusal in the run beneath it decorative.
 */
export function Conclusion({ book }: { book: CommentBook }) {
  const mine = commentsFor(book, { target: "scv_conclusion" });
  const latest = mine.filter((one) => one.kind === "APPROVER").slice(-1)[0];
  return (
    <div className="rounded-lg border border-border bg-surface p-4"
         data-testid="scv-conclusion">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-base font-semibold text-text">
          Overall validation conclusion
        </h2>
        {latest && (
          <span className="text-[11px] text-text-muted">
            last recorded by {latest.author || "unattributed"} ·{" "}
            {when(latest.created_at)}
          </span>
        )}
      </div>
      <p className="mt-1 max-w-3xl text-[11px] leading-relaxed text-text-muted">
        CreditProbe does not write this. It computes results, states which
        could not be measured, and raises findings; the opinion on the
        scorecard as a whole is a person&rsquo;s, recorded here with their
        name against this run.
      </p>
      <div className="mt-3">
        <CommentThread book={book} target={{ target: "scv_conclusion" }}
                       label="the overall opinion" />
      </div>
    </div>
  );
}
