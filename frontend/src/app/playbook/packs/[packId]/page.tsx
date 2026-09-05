"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { FindingsPanel } from "@/components/playbook/findings-panel";
import { GovernancePanel } from "@/components/playbook/governance-panel";
import {
  ComparisonPanel,
  HistoryPanel,
  SourcesPanel,
} from "@/components/playbook/history-panel";
import { PackContent } from "@/components/playbook/pack-content";
import {
  PackStatus,
  Problem,
  ReadinessBar,
  ReadinessChecks,
  SectionCard,
  daysUntil,
  formatDay,
} from "@/components/playbook/parts";
import { nextStatuses } from "@/lib/playbook-format";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Tabs } from "@/components/ui/tabs";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import type { PlaybookPack } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * One committee pack.
 *
 * The screen renders from `pack.access` — what THIS reader may do — and the
 * API enforces the same thing independently. Hiding a button is courtesy; the
 * refusal behind it is the security. A reader who somehow reaches an action
 * they may not take gets the API's own refusal, which says what access is
 * needed rather than "something went wrong".
 *
 * Nothing here recalculates on open. An approved pack renders from the
 * snapshots it was approved with, which is what makes a tabled pack the same
 * document every time it is opened.
 */
export default function PackPage() {
  const params = useParams<{ packId: string }>();
  const packId = Number(params.packId);
  const pack = useAsync(() => api.playbook.pack(packId), [packId]);
  const [tab, setTab] = React.useState("pack");

  if (pack.error && !pack.data) {
    return (
      <div className="mx-auto w-full max-w-4xl px-6 py-10">
        <Unavailable state={pack} what="this pack" />
        <p className="mt-4 text-sm text-text-muted">
          <Link href="/playbook" className="text-accent hover:underline">
            Back to Playbook
          </Link>
        </p>
      </div>
    );
  }

  const data = pack.data;
  if (!data) {
    return (
      <div className="mx-auto w-full max-w-6xl px-6 py-10 text-sm text-text-muted">
        Loading the pack…
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-6xl space-y-5 px-6 py-6">
      <PackHeader pack={data} onChanged={pack.reload} />

      <div className="grid gap-5 lg:grid-cols-[1fr_320px]">
        <div className="min-w-0 space-y-4">
          <Tabs
            tabs={[
              { id: "pack", label: "Pack" },
              { id: "findings", label: "Findings" },
              { id: "governance", label: "Decisions & actions" },
              { id: "compare", label: "Since last time" },
              { id: "sources", label: "Documents" },
              { id: "history", label: "History" },
            ]}
            active={tab}
            onChange={setTab}
          />

          {tab === "pack" && (
            <PackContent pack={data} onChanged={pack.reload} />
          )}
          {tab === "findings" && <FindingsPanel pack={data} />}
          {tab === "governance" && (
            <GovernancePanel pack={data} onChanged={pack.reload} />
          )}
          {tab === "compare" && <ComparisonPanel pack={data} />}
          {tab === "sources" && (
            <SourcesPanel pack={data} onChanged={pack.reload} />
          )}
          {tab === "history" && <HistoryPanel pack={data} />}
        </div>

        <aside className="space-y-4">
          <SectionCard title="Readiness">
            <div className="px-4 py-3">
              <ReadinessBar readiness={data.readiness} />
            </div>
            <ReadinessChecks readiness={data.readiness} />
          </SectionCard>

          <SectionCard title="The pack">
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 px-4 py-3 text-xs">
              <dt className="text-text-muted">Committee</dt>
              <dd className="text-text-secondary">
                <Link
                  href={`/playbook/committees/${data.committee_id}`}
                  className="text-accent hover:underline"
                >
                  {data.committee.name}
                </Link>
              </dd>
              <dt className="text-text-muted">Period</dt>
              <dd className="text-text-secondary">{data.period}</dd>
              <dt className="text-text-muted">Compared with</dt>
              <dd className="text-text-secondary">
                {data.comparison_period || "nothing"}
              </dd>
              <dt className="text-text-muted">Meets</dt>
              <dd className="text-text-secondary">
                {formatDay(data.meeting_at)} ({daysUntil(data.meeting_at)})
              </dd>
              <dt className="text-text-muted">Version</dt>
              <dd className="text-text-secondary">{data.version}</dd>
              <dt className="text-text-muted">Your access</dt>
              <dd className="text-text-secondary">
                {data.access.toLowerCase()}
              </dd>
              <dt className="text-text-muted">Confidentiality</dt>
              <dd className="text-text-secondary">
                {data.confidentiality.toLowerCase()}
              </dd>
            </dl>
            {data.demo && (
              <p className="border-t border-border px-4 py-2 text-[11px] text-text-muted">
                This pack runs on synthetic data. It describes no real
                borrower.
              </p>
            )}
          </SectionCard>

          <Downloads pack={data} />
        </aside>
      </div>
    </div>
  );
}

/**
 * The pack's own controls: generate, move it along the workflow, amend it.
 *
 * The transitions offered come from `nextStatuses`, which mirrors the
 * backend's own state machine. A button that leads to a 422 is a button that
 * teaches people the product is unreliable.
 */
function PackHeader({
  pack,
  onChanged,
}: {
  pack: PlaybookPack;
  onChanged: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);
  const [outcome, setOutcome] = React.useState<string>("");
  const [amending, setAmending] = React.useState(false);
  const [reason, setReason] = React.useState("");

  async function run(work: () => Promise<unknown>, said?: string) {
    setBusy(true);
    setError(null);
    setOutcome("");
    try {
      const result = await work();
      if (said) setOutcome(said);
      else if (result && typeof result === "object" && "summary" in result) {
        setOutcome(String((result as { summary: unknown }).summary));
      }
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const transitions = nextStatuses(pack.status);

  return (
    <div className="space-y-3">
      <PageHeader
        title={pack.name}
        description={`${pack.code} · ${pack.committee.name}`}
        actions={
          <div className="flex flex-wrap gap-2">
            {pack.editable && (
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                title="Recalculate every governed figure and re-raise findings."
                onClick={() => run(() => api.playbook.generate(pack.id))}
              >
                {busy ? "Working…" : "Generate"}
              </Button>
            )}
            {transitions.map((next) => (
              <Button
                key={next.status}
                size="sm"
                variant={next.status === "APPROVED" ? "default" : "outline"}
                disabled={busy}
                title={next.hint || undefined}
                onClick={() =>
                  run(
                    () => api.playbook.setPackStatus(pack.id, next.status),
                    `Pack moved to ${next.status.replace(/_/g, " ").toLowerCase()}.`,
                  )
                }
              >
                {next.label}
              </Button>
            ))}
            {pack.locked && (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setAmending((was) => !was)}
              >
                {amending ? "Cancel" : "Raise an amendment"}
              </Button>
            )}
          </div>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <PackStatus status={pack.status} label={pack.status_label} />
        {pack.locked && (
          <Badge
            variant="default"
            title="An approved pack is a historical record. Correcting one raises an amendment, which supersedes it rather than rewriting it."
          >
            read-only
          </Badge>
        )}
        {pack.amends_pack_id && (
          <Badge variant="warning">
            amends pack {pack.amends_pack_id}
          </Badge>
        )}
        {pack.readiness.blocking_count > 0 && (
          <Badge variant="negative">
            {pack.readiness.blocking_count} blocking
          </Badge>
        )}
      </div>

      {pack.amendment_reason && (
        <p className="rounded-md border border-warning/40 bg-warning-muted/40 px-3 py-2 text-xs text-text-secondary">
          <span className="font-medium">Amendment: </span>
          {pack.amendment_reason}
        </p>
      )}

      {amending && (
        <div className="space-y-2 rounded-md border border-border bg-surface-sunken p-3">
          <p className="text-xs text-text-muted">
            An amendment creates a NEW pack that supersedes this one. The
            approved pack stays exactly as it was approved, because a
            historical record that can be edited is not a record.
          </p>
          <Input
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why this pack needs correcting."
          />
          <Button
            size="sm"
            disabled={busy || !reason.trim()}
            onClick={() =>
              run(
                () => api.playbook.amend(pack.id, reason),
                "An amendment pack has been raised. Find it on the committee.",
              )
            }
          >
            Raise the amendment
          </Button>
        </div>
      )}

      {error != null && <Problem error={error} />}
      {outcome && (
        <p className="rounded-md border border-border bg-surface-sunken px-3 py-2 text-xs text-text-secondary">
          {outcome}
        </p>
      )}
    </div>
  );
}

/**
 * The four formats, offered by the backend rather than listed here.
 *
 * A real link the browser follows, not a fetch: the file has to be saved, and
 * the response carries the filename and the checksum in its headers.
 */
function Downloads({ pack }: { pack: PlaybookPack }) {
  const formats = useAsync(() => api.playbook.formats(), []);
  return (
    <SectionCard
      title="Download"
      description={
        pack.status === "APPROVED" || pack.status === "PUBLISHED"
          ? undefined
          : "A draft export is marked as a draft on every page."
      }
    >
      {formats.loading ? (
        <p className="px-4 py-3 text-xs text-text-muted">Loading…</p>
      ) : (
        <ul className="divide-y divide-border">
          {(formats.data?.formats ?? []).map((format) => (
            <li key={format.format}>
              <a
                href={api.playbook.exportUrl(pack.id, format.format)}
                className="block px-4 py-2.5 hover:bg-surface-hover"
              >
                <span className="text-sm font-medium text-text-primary">
                  {format.label}
                </span>
                <p className="text-xs text-text-muted">{format.purpose}</p>
              </a>
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
