"use client";

/**
 * Messages: live governed objects between people (§31). A card is a
 * reference to the same object the sender saw -- opening it re-checks the
 * reader's own permissions -- and every action works on that object:
 * Open, Run on my cohort/book, Re-run on the latest data, Compare with my
 * results, Duplicate/Branch, Save a copy, Investigate, Comment.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Inbox, Loader2, Send } from "lucide-react";

import { count, sarDelta } from "@/lib/viz/format";
import { listCohorts } from "@/lib/workspace/objects";
import {
  commentOnMessage,
  compareFromMessage,
  duplicateFromMessage,
  hrefFor,
  investigateFromMessage,
  listMyResults,
  readInbox,
  readMessage,
  runFromMessage,
  saveFromMessage,
  type MessageAction,
  type MessageDetail,
  type MessageItem,
  type ShareCard,
} from "@/lib/workspace/messages";

const KIND_LABEL: Record<string, string> = {
  scenario: "Scenario definition · not executed",
  scenario_result: "Executed scenario result",
  cohort: "Cohort",
  comparison: "Scenario comparison",
  run: "What-If run",
};

function when(ts: number): string {
  return new Date(ts * 1000).toLocaleString();
}

function errorText(e: unknown) {
  return e instanceof Error ? e.message : String(e);
}

export function MessagesCenter() {
  const params = useSearchParams();
  const router = useRouter();
  const [box, setBox] = React.useState<"inbox" | "sent">((params.get("box") as "inbox" | "sent") || "inbox");
  const [items, setItems] = React.useState<MessageItem[] | null>(null);
  const [unread, setUnread] = React.useState(0);
  const [error, setError] = React.useState("");
  const [reload, setReload] = React.useState(0);
  const selected = params.get("m") ?? "";

  React.useEffect(() => {
    let live = true;
    readInbox(box)
      .then((r) => {
        if (!live) return;
        setItems(r.items);
        setUnread(r.unread);
      })
      .catch((e: unknown) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
  }, [box, reload, selected]);

  function pick(id: string) {
    router.replace(`/messages?box=${box}&m=${id}`);
  }

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(20rem,26rem)_1fr]" data-testid="messages-center">
      <section className="space-y-2">
        <header className="flex items-center gap-2">
          <h1 className="text-lg font-semibold">Messages</h1>
          <span className="text-xs text-text-muted" data-testid="messages-unread">
            {unread} unread
          </span>
        </header>
        <div className="flex gap-1 text-xs">
          {(["inbox", "sent"] as const).map((b) => (
            <button
              key={b}
              type="button"
              onClick={() => {
                setBox(b);
                router.replace(`/messages?box=${b}`);
              }}
              aria-pressed={box === b}
              className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 ${box === b ? "border-accent bg-accent text-accent-contrast" : "border-border"}`}
              data-testid={`messages-box-${b}`}
            >
              {b === "inbox" ? <Inbox className="h-3.5 w-3.5" /> : <Send className="h-3.5 w-3.5" />} {b === "inbox" ? "Inbox" : "Sent"}
            </button>
          ))}
        </div>
        {error && (
          <p role="alert" className="text-sm text-negative">
            {error}
          </p>
        )}
        {!items && !error && <p className="text-sm text-text-muted">Loading…</p>}
        {items && !items.length && (
          <p className="rounded border border-border p-3 text-sm text-text-muted" data-testid="messages-empty">
            {box === "inbox" ? "Nothing has been shared with you yet." : "You have not shared anything yet. Use Share on a scenario, result, comparison or cohort."}
          </p>
        )}
        <ul className="space-y-1" data-testid="messages-list">
          {items?.map((m) => (
            <li key={m.share_id}>
              <button
                type="button"
                onClick={() => pick(m.share_id)}
                className={`w-full rounded-lg border p-2 text-left text-xs ${selected === m.share_id ? "border-accent bg-accent/5" : "border-border bg-surface"} ${m.direction === "received" && !m.read_at ? "font-semibold" : ""}`}
                data-testid="message-item"
                data-kind={m.kind}
                data-share-id={m.share_id}
                data-seeded={String(m.seeded)}
              >
                <div className="flex items-center gap-2">
                  <span>{m.direction === "received" ? `From ${m.from_id}` : `To ${m.to_id}`}</span>
                  {m.seeded && <span className="rounded bg-warning/15 px-1 text-[10px] text-warning">SYNTHETIC</span>}
                  <span className="ml-auto text-text-muted">{when(m.created_at)}</span>
                </div>
                <div className="text-text-muted">{KIND_LABEL[m.kind] ?? m.kind}</div>
                <div className="truncate text-sm">{m.card.name ?? m.card.title}</div>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section>{selected ? <MessageView key={selected} shareId={selected} onChanged={() => setReload((n) => n + 1)} /> : <p className="text-sm text-text-muted">Choose a message.</p>}</section>
    </div>
  );
}

function ObjectSummary({ card }: { card: ShareCard }) {
  const k = card.kind;
  return (
    <div className="space-y-1 rounded-lg border border-border bg-surface-sunken p-3 text-xs" data-testid="message-object" data-kind={k} data-object-id={card.object_id} data-version={card.version}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-semibold">{card.name ?? card.title}</span>
        <span className="text-text-muted">
          {KIND_LABEL[k] ?? k} · {card.object_id} v{card.version} · {card.domain_id} {card.period}
        </span>
      </div>
      {k === "scenario" && (
        <>
          <div>Author {card.author} · scope {card.scope_label}</div>
          <ul className="list-disc pl-5">{card.components?.map((c) => <li key={c}>{c}</li>)}</ul>
        </>
      )}
      {k === "scenario_result" && (
        <>
          <div>
            Baseline {card.baseline === "PRIOR_SCENARIO" ? `layered on ${card.chain?.join(" → ")}` : "original reported"} · {card.scope_label}
          </div>
          <div data-testid="message-result-methods">
            Method(s): {card.methods?.join(", ")}
            {card.methods_unavailable && Object.keys(card.methods_unavailable).length > 0 && (
              <span className="text-negative"> · not run: {Object.entries(card.methods_unavailable).map(([m, r]) => `${m} (${r})`).join("; ")}</span>
            )}
          </div>
          <div className="tabular">
            Selected-scope Δ {card.selected_change ? sarDelta(Number(card.selected_change)) : "—"} · total-book Δ {card.total_change ? sarDelta(Number(card.total_change)) : "—"}
          </div>
          {card.top_components && card.top_components.length > 0 && <div>Largest components: {card.top_components.map((c) => `${c.label} ${sarDelta(Number(c.value))}`).join(" · ")}</div>}
          {card.limitations && card.limitations.length > 0 && (
            <ul className="list-disc pl-5 text-text-muted">
              {card.limitations.map((l, i) => (
                <li key={i}>{l}</li>
              ))}
            </ul>
          )}
        </>
      )}
      {k === "cohort" && (
        <div className="tabular">
          {count(card.entities ?? 0)} exposures · {card.description} · membership {card.membership_hash?.slice(0, 16)}
        </div>
      )}
      {k === "comparison" && (
        <div>
          {card.items?.join(" vs ")} · method {card.method}
        </div>
      )}
      {card.attachments && card.attachments.length > 0 && (
        <div className="text-text-muted">Travels with (identity only): {card.attachments.map((a) => `${a.kind} ${a.object_id}`).join(", ")}</div>
      )}
    </div>
  );
}

function MessageView({ shareId, onChanged }: { shareId: string; onChanged: () => void }) {
  const router = useRouter();
  const [d, setD] = React.useState<MessageDetail | null>(null);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [panel, setPanel] = React.useState<"" | "run" | "compare">("");
  const [note, setNote] = React.useState<{ text: string; href: string } | null>(null);
  const [comment, setComment] = React.useState("");
  const [reload, setReload] = React.useState(0);

  React.useEffect(() => {
    let live = true;
    readMessage(shareId)
      .then((r) => {
        if (!live) return;
        setD(r);
        onChanged();
      })
      .catch((e: unknown) => live && setError(errorText(e)));
    return () => {
      live = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [shareId, reload]);

  async function go(fn: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  function perform(a: MessageAction) {
    if (a.href) {
      router.push(a.href);
      return;
    }
    if (a.action === "run") return setPanel(panel === "run" ? "" : "run");
    if (a.action === "compare") return setPanel(panel === "compare" ? "" : "compare");
    if (a.action === "comment") return document.getElementById("message-comment")?.focus();
    void go(async () => {
      if (a.action === "rerun_latest") {
        const run = await runFromMessage(shareId, { latest: true });
        router.push(`/what-if?run=${run.object_id}&from=messages`);
      } else if (a.action === "duplicate") {
        const obj = await duplicateFromMessage(shareId);
        setNote({ text: `Your own copy ${obj.object_id} was created (the original is unchanged).`, href: hrefFor(obj) });
      } else if (a.action === "save") {
        const obj = await saveFromMessage(shareId);
        setNote({ text: `Saved to your workspace as ${obj.object_id}.`, href: hrefFor(obj) });
      } else if (a.action === "investigate") {
        const t = await investigateFromMessage(shareId);
        router.push(`/cockpit/thread/${t.thread_id}`);
      }
    });
  }

  if (error && !d)
    return (
      <p role="alert" className="text-sm text-negative">
        {error}
      </p>
    );
  if (!d) return <p className="text-sm text-text-muted">Loading…</p>;
  const s = d.share;
  return (
    <article className="space-y-3 rounded-xl border border-border bg-surface p-4" data-testid="message-view" data-share-id={s.share_id} data-accessible={String(d.accessible)}>
      <header className="flex flex-wrap items-center gap-2 text-xs">
        <span className="font-semibold">
          {s.from_id} → {s.to_id}
        </span>
        <span className="text-text-muted">{when(s.created_at)}</span>
        {s.seeded && <span className="rounded bg-warning/15 px-1 text-warning">SYNTHETIC DEMO DATA</span>}
      </header>
      {s.message && <p className="whitespace-pre-wrap text-sm" data-testid="message-text">{s.message}</p>}
      {!d.accessible ? (
        <p className="rounded border border-negative p-2 text-sm text-negative" data-testid="message-inaccessible">
          {d.reason}
        </p>
      ) : (
        <>
          <ObjectSummary card={d.card ?? s.card} />
          {d.newer_content && (
            <p className="text-xs text-warning" data-testid="message-newer">
              This message shares v{s.version}; the object is now at v{d.latest_version}. You are looking at the version that was shared.
            </p>
          )}
          <div className="flex flex-wrap gap-2" data-testid="message-actions">
            {d.actions.map((a) => (
              <button
                key={a.action}
                type="button"
                disabled={busy}
                onClick={() => perform(a)}
                className={`rounded-md px-3 py-1.5 text-sm ${a.action === "open" ? "bg-accent text-accent-contrast" : "border border-border"}`}
                data-testid={`message-action-${a.action}`}
              >
                {a.label}
              </button>
            ))}
            {busy && <Loader2 className="h-4 w-4 animate-spin" />}
          </div>
          {note && (
            <p className="text-xs text-positive" data-testid="message-note">
              {note.text}{" "}
              <Link href={note.href} className="text-accent underline" data-testid="message-note-link">
                Open it
              </Link>
            </p>
          )}
          {panel === "run" && d.object && <RunChooser domain={d.object.domain_id} onRun={(cohortId) => go(async () => {
            const run = await runFromMessage(shareId, cohortId ? { cohort_id: cohortId } : {});
            router.push(`/what-if?run=${run.object_id}&from=messages`);
          })} />}
          {panel === "compare" && d.object && <ComparePicker domain={d.object.domain_id} period={d.object.period} exclude={d.object.object_id} onCompare={(ids) => go(async () => {
            const c = await compareFromMessage(shareId, ids);
            router.push(`/what-if/compare/${c.object_id}`);
          })} />}
        </>
      )}
      {error && (
        <p role="alert" className="text-sm text-negative" data-testid="message-error">
          {error}
        </p>
      )}
      <section className="space-y-2 border-t border-border pt-2" data-testid="message-comments">
        <h3 className="text-xs font-semibold">Comments on v{s.version}</h3>
        {d.comments.map((c) => (
          <div key={c.comment_id} className="rounded bg-surface-sunken p-2 text-xs" data-testid="message-comment-item">
            <span className="font-semibold">{c.author_id}</span> <span className="text-text-muted">v{c.version} · {when(c.created_at)}</span>
            <div>{c.body}</div>
          </div>
        ))}
        {d.accessible && (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (!comment.trim()) return;
              void go(async () => {
                await commentOnMessage(shareId, comment.trim());
                setComment("");
                setReload((n) => n + 1);
              });
            }}
          >
            <input id="message-comment" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment on this version…" className="flex-1 rounded border border-border bg-surface px-2 py-1 text-sm" data-testid="message-comment-input" />
            <button type="submit" disabled={busy || !comment.trim()} className="rounded-md border border-border px-3 py-1 text-sm disabled:opacity-40" data-testid="message-comment-send">
              Comment
            </button>
          </form>
        )}
      </section>
    </article>
  );
}

function RunChooser({ domain, onRun }: { domain: string; onRun: (cohortId: string) => void }) {
  const [rows, setRows] = React.useState<{ object_id: string; title: string; counts?: { entities: number } }[] | null>(null);
  const [pick, setPick] = React.useState("");
  React.useEffect(() => {
    listCohorts(domain as "corporate" | "retail")
      .then((r) => setRows(r.cohorts as unknown as { object_id: string; title: string; counts?: { entities: number } }[]))
      .catch(() => setRows([]));
  }, [domain]);
  return (
    <div className="space-y-2 rounded-lg border border-border p-3 text-xs" data-testid="message-run-chooser">
      <p>Run the shared definition as YOUR run. It is previewed first; nothing is calculated until you confirm and choose a method.</p>
      <select value={pick} onChange={(e) => setPick(e.target.value)} className="rounded border border-border bg-surface px-2 py-1" data-testid="message-run-cohort">
        <option value="">The definition&apos;s own scope</option>
        {rows?.map((c) => (
          <option key={c.object_id} value={c.object_id}>
            My cohort: {c.title} {c.counts ? `(${count(c.counts.entities)})` : ""}
          </option>
        ))}
      </select>
      <button type="button" onClick={() => onRun(pick)} className="ml-2 rounded-md bg-accent px-3 py-1 text-accent-contrast" data-testid="message-run-go">
        Start my run
      </button>
    </div>
  );
}

function ComparePicker({ domain, period, exclude, onCompare }: { domain: string; period: string; exclude: string; onCompare: (ids: string[]) => void }) {
  const [rows, setRows] = React.useState<(ShareCard & { created_at: number; mine: boolean })[] | null>(null);
  const [chosen, setChosen] = React.useState<Set<string>>(new Set());
  React.useEffect(() => {
    listMyResults(domain)
      .then((r) => setRows(r.results.filter((x) => x.object_id !== exclude && x.period === period)))
      .catch(() => setRows([]));
  }, [domain, exclude, period]);
  if (!rows) return <p className="text-xs text-text-muted">Loading your results…</p>;
  if (!rows.length)
    return (
      <p className="rounded border border-border p-2 text-xs text-text-muted" data-testid="message-compare-empty">
        You have no executed result on {domain} {period} to compare with yet. Run one in What-If, then compare.
      </p>
    );
  return (
    <div className="space-y-2 rounded-lg border border-border p-3 text-xs" data-testid="message-compare-picker">
      <p>Compare on common KPIs and the decomposition (same book and period, a method both ran).</p>
      <ul className="max-h-48 space-y-1 overflow-auto">
        {rows.map((r) => (
          <li key={r.object_id}>
            <label className="flex items-center gap-2">
              <input
                type="checkbox"
                checked={chosen.has(r.object_id)}
                onChange={() =>
                  setChosen((prev) => {
                    const n = new Set(prev);
                    if (n.has(r.object_id)) n.delete(r.object_id);
                    else n.add(r.object_id);
                    return n;
                  })
                }
                data-testid="message-compare-option"
                data-result-id={r.object_id}
              />
              {r.name} · {r.methods?.join("+")} · Δ {r.selected_change ? sarDelta(Number(r.selected_change)) : "—"} · {r.mine ? "mine" : `from ${r.owner_id}`} · {r.object_id}
            </label>
          </li>
        ))}
      </ul>
      <button type="button" disabled={!chosen.size} onClick={() => onCompare([...chosen])} className="rounded-md bg-accent px-3 py-1 text-accent-contrast disabled:opacity-40" data-testid="message-compare-go">
        Compare
      </button>
    </div>
  );
}
