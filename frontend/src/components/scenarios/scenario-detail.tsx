"use client";

/**
 * One Scenario Definition: what it says, what it would touch on the book
 * today, where it came from, and the verbs that make a NEW version or a NEW
 * scenario -- never an edit in place. Execution is not on this page.
 */

import * as React from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowLeft, Archive, Copy, GitBranch, Link2, Loader2, MessageSquare, Pencil, Send } from "lucide-react";

import { PreviewPanel } from "@/components/scenarios/preview-panel";
import { Badge } from "@/components/ui/badge";
import { SEVERITY_TONE } from "@/lib/workspace/scenario-figures";
import { addComment, listCohorts } from "@/lib/workspace/objects";
import {
  bindScenario,
  cloneScenario,
  previewScenario,
  readScenario,
  resolveOverlaps,
  retireScenario,
  reviseScenario,
  shareScenario,
  type Preview,
  type Resolution,
  type ScenarioDetail as Detail,
} from "@/lib/workspace/scenarios";

export function ScenarioDetail({ scenarioId }: { scenarioId: string }) {
  const router = useRouter();
  const [detail, setDetail] = React.useState<Detail | null>(null);
  const [preview, setPreview] = React.useState<Preview | null>(null);
  const [error, setError] = React.useState("");
  const [note, setNote] = React.useState("");
  const [reload, setReload] = React.useState(0);
  const [panel, setPanel] = React.useState<"" | "rename" | "bind" | "share" | "comment">("");

  React.useEffect(() => {
    let live = true;
    Promise.all([readScenario(scenarioId), previewScenario(scenarioId)])
      .then(([d, p]) => {
        if (!live) return;
        setDetail(d);
        setPreview(p);
      })
      .catch((e: unknown) => live && setError(e instanceof Error ? e.message : String(e)));
    return () => {
      live = false;
    };
  }, [scenarioId, reload]);

  if (error) return <p role="alert" className="text-sm text-negative">{error}</p>;
  if (!detail) {
    return (
      <p className="flex items-center gap-2 text-sm text-text-muted">
        <Loader2 className="h-4 w-4 animate-spin" /> Opening the scenario…
      </p>
    );
  }
  const obj = detail.scenario;
  const b = obj.body;
  const card = detail.card;

  async function act<T>(fn: () => Promise<T>, done: (out: T) => void) {
    setNote("");
    try {
      done(await fn());
    } catch (e) {
      setNote(e instanceof Error ? e.message : String(e));
    }
  }

  async function onResolve(resolutions: Record<string, Resolution>) {
    if (card.can_edit) {
      await act(() => resolveOverlaps(obj.object_id, resolutions), () => setReload((n) => n + 1));
      return;
    }
    // A template or someone else's scenario: the choice is recorded on YOUR
    // copy; the original is not changed.
    await act(
      async () => {
        const copy = await cloneScenario(obj.object_id, `${b.name} (my policies)`);
        await resolveOverlaps(copy.object_id, resolutions);
        return copy;
      },
      (copy) => router.push(`/scenarios/${copy.object_id}`),
    );
  }

  return (
    <div className="space-y-5" data-testid="scenario-detail" data-object-id={obj.object_id} data-version={obj.version}>
      <Link href="/scenarios" className="inline-flex items-center gap-1 text-xs text-accent">
        <ArrowLeft className="h-3 w-3" /> Scenario Library
      </Link>
      <header className="space-y-2">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {b.template_id && <span className="font-mono text-text-muted">{b.template_id}</span>}
          <Badge variant={SEVERITY_TONE[b.severity] ?? "default"}>{b.severity}</Badge>
          <Badge variant="outline">{obj.domain_id}</Badge>
          <Badge variant={card.is_template ? "info" : "accent"} data-testid="scenario-status">
            {card.is_template ? "TEMPLATE" : obj.status}
          </Badge>
          <span className="text-text-muted">
            {obj.object_id} · v{obj.version} · owner {card.is_template ? "CreditProbe library" : obj.owner_id} · defined on {obj.release_id} ({obj.period})
          </span>
        </div>
        <h1 className="text-xl font-semibold text-text-primary" data-testid="scenario-name">
          {b.name}
        </h1>
        <p className="text-sm text-text-secondary">{b.description}</p>
        {b.risk_thesis && (
          <p className="text-sm">
            <span className="font-semibold">Risk thesis.</span> {b.risk_thesis}
          </p>
        )}
        <div className="flex flex-wrap gap-2" data-testid="scenario-actions">
          <Action icon={<Copy className="h-4 w-4" />} testId="scenario-action-clone" onClick={() => act(() => cloneScenario(obj.object_id), (c) => router.push(`/scenarios/${c.object_id}`))}>
            Clone
          </Action>
          <Action icon={<GitBranch className="h-4 w-4" />} testId="scenario-action-branch" onClick={() => act(() => cloneScenario(obj.object_id, "", true), (c) => router.push(`/scenarios/${c.object_id}`))}>
            Branch
          </Action>
          {card.can_edit && (
            <Action icon={<Pencil className="h-4 w-4" />} testId="scenario-action-rename" onClick={() => setPanel(panel === "rename" ? "" : "rename")}>
              Rename
            </Action>
          )}
          <Action icon={<Link2 className="h-4 w-4" />} testId="scenario-action-bind" onClick={() => setPanel(panel === "bind" ? "" : "bind")}>
            Bind to a cohort
          </Action>
          <Action icon={<Send className="h-4 w-4" />} testId="scenario-action-share" onClick={() => setPanel(panel === "share" ? "" : "share")}>
            Share
          </Action>
          <Action icon={<MessageSquare className="h-4 w-4" />} testId="scenario-action-comment" onClick={() => setPanel(panel === "comment" ? "" : "comment")}>
            Comment
          </Action>
          {card.can_edit && obj.status !== "ARCHIVED" && (
            <Action icon={<Archive className="h-4 w-4" />} testId="scenario-action-retire" onClick={() => act(() => retireScenario(obj.object_id), () => setReload((n) => n + 1))}>
              Retire
            </Action>
          )}
          <Link
            href={`/what-if?scenario=${encodeURIComponent(obj.object_id)}`}
            className="inline-flex items-center gap-1 rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-accent-contrast"
            data-testid="scenario-open-whatif"
          >
            Open in What-If
          </Link>
        </div>
        {panel === "rename" && (
          <InlineForm
            label="New name"
            initial={b.name}
            testId="scenario-rename"
            submit="Save as a new version"
            onSubmit={(v) => act(() => reviseScenario(obj.object_id, { name: v }, "renamed"), () => { setPanel(""); setReload((n) => n + 1); })}
          />
        )}
        {panel === "bind" && <BindPanel domain={obj.domain_id} onBind={(id) => act(() => bindScenario(obj.object_id, id), (out) => router.push(`/scenarios/${out.scenario.object_id}`))} />}
        {panel === "share" && (
          <InlineForm
            label="Share with (user ids, comma-separated)"
            initial=""
            testId="scenario-share"
            submit="Share the scenario reference"
            onSubmit={(v) =>
              act(
                () => shareScenario(obj.object_id, v.split(",").map((x) => x.trim()).filter(Boolean), ""),
                (out) => {
                  setPanel("");
                  setNote(`Shared v${obj.version} with ${out.shared.length} recipient(s). They receive the reference, never the data.`);
                  setReload((n) => n + 1);
                },
              )
            }
          />
        )}
        {panel === "comment" && (
          <InlineForm
            label={`Comment on version ${obj.version}`}
            initial=""
            testId="scenario-comment"
            submit="Add comment"
            onSubmit={(v) => act(() => addComment(obj.object_id, v, obj.version), () => { setPanel(""); setReload((n) => n + 1); })}
          />
        )}
        {note && <p className="text-xs text-text-secondary" data-testid="scenario-note">{note}</p>}
      </header>

      {!preview ? (
        <p className="flex items-center gap-2 text-sm text-text-muted">
          <Loader2 className="h-4 w-4 animate-spin" /> Resolving the definition against the book…
        </p>
      ) : (
        <PreviewPanel
          preview={preview}
          definition={b}
          onResolve={onResolve}
          resolveLabel={card.can_edit ? "Record composition policy (new version)" : "Clone and record these policies"}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-lg border border-border bg-surface p-3 text-xs" data-testid="scenario-assumptions">
          <h2 className="mb-1 text-sm font-semibold">Assumptions and limitations</h2>
          <ul className="list-disc space-y-0.5 pl-5">
            {[...b.assumptions, ...b.limitations].map((a, i) => (
              <li key={i}>{a}</li>
            ))}
            {b.composition_policy.note && <li>{b.composition_policy.note}</li>}
            {b.assumptions.length + b.limitations.length === 0 && !b.composition_policy.note && <li>None stated.</li>}
          </ul>
        </section>
        <section className="rounded-lg border border-border bg-surface p-3 text-xs" data-testid="scenario-lineage">
          <h2 className="mb-1 text-sm font-semibold">Lineage and versions</h2>
          {detail.lineage.ancestors.length > 0 && (
            <p>
              From:{" "}
              {detail.lineage.ancestors.map((a) => (
                <Link key={`${a.object_id}-${a.version}`} href={`/scenarios/${a.object_id}`} className="mr-2 text-accent underline">
                  {a.title} v{a.version}
                </Link>
              ))}
            </p>
          )}
          {detail.lineage.descendants.length > 0 && (
            <p>
              Used by:{" "}
              {detail.lineage.descendants.map((d) => (
                <Link key={`${d.object_id}-${d.version}`} href={`/scenarios/${d.object_id}`} className="mr-2 text-accent underline">
                  {d.title} ({d.operation})
                </Link>
              ))}
            </p>
          )}
          <ol className="mt-1 space-y-0.5" data-testid="scenario-versions">
            {detail.lineage.versions.map((v) => (
              <li key={v.version}>
                v{v.version} · {v.status} · {v.reason || "created"} · <span className="font-mono">{v.content_hash.slice(0, 12)}</span>
              </li>
            ))}
          </ol>
          {detail.comments.length > 0 && (
            <div className="mt-2" data-testid="scenario-comments">
              <h3 className="font-semibold">Comments</h3>
              {detail.comments.map((c) => (
                <p key={c.comment_id}>
                  <span className="text-text-muted">
                    {c.author_id} on v{c.version}:
                  </span>{" "}
                  {c.body}
                </p>
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function Action({ icon, children, onClick, testId }: { icon: React.ReactNode; children: React.ReactNode; onClick: () => void; testId: string }) {
  return (
    <button type="button" onClick={onClick} className="inline-flex items-center gap-1 rounded-md border border-border px-3 py-1.5 text-sm" data-testid={testId}>
      {icon} {children}
    </button>
  );
}

function InlineForm({ label, initial, submit, onSubmit, testId }: { label: string; initial: string; submit: string; onSubmit: (v: string) => void; testId: string }) {
  const [value, setValue] = React.useState(initial);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSubmit(value.trim());
      }}
      className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-surface-sunken p-2 text-sm"
      data-testid={testId}
    >
      <label className="text-xs text-text-muted">{label}</label>
      <input value={value} onChange={(e) => setValue(e.target.value)} className="min-w-[18rem] flex-1 rounded border border-border bg-surface px-2 py-1" data-testid={`${testId}-input`} />
      <button type="submit" className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-accent-contrast" data-testid={`${testId}-submit`}>
        {submit}
      </button>
    </form>
  );
}

type CohortRow = { object_id: string; version: number; title: string; counts: { entities: number } };

function BindPanel({ domain, onBind }: { domain: "corporate" | "retail"; onBind: (cohortId: string) => void }) {
  const [cohorts, setCohorts] = React.useState<CohortRow[] | null>(null);
  React.useEffect(() => {
    listCohorts(domain)
      .then((r) => setCohorts(r.cohorts as unknown as CohortRow[]))
      .catch(() => setCohorts([]));
  }, [domain]);
  if (!cohorts) return <p className="text-xs text-text-muted">Loading your saved cohorts…</p>;
  if (!cohorts.length)
    return (
      <p className="rounded-lg border border-border bg-surface-sunken p-2 text-xs" data-testid="scenario-bind-empty">
        No saved {domain} cohorts yet. Save one from the What-If grid, Early Warning or an issue, then bind it here.
      </p>
    );
  return (
    <ul className="space-y-1 rounded-lg border border-border bg-surface-sunken p-2 text-xs" data-testid="scenario-bind">
      {cohorts.map((c) => (
        <li key={c.object_id} className="flex items-center gap-2">
          <span className="flex-1">
            {c.title} · {c.counts.entities} exposures · {c.object_id} v{c.version}
          </span>
          <button type="button" onClick={() => onBind(c.object_id)} className="rounded border border-border px-2 py-0.5" data-testid="scenario-bind-choose">
            Bind
          </button>
        </li>
      ))}
    </ul>
  );
}
