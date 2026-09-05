"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import {
  Empty,
  PackStatus,
  SectionCard,
  Stat,
  daysUntil,
  formatDay,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * The Playbook landing screen.
 *
 * The reader is a pack owner or a committee chair. Their questions, in this
 * order: which pack is next, is it ready, and who am I waiting on. So the
 * open packs come first with their readiness beside them, the chase list is
 * on the same screen rather than a click away, and the committees themselves
 * — which change once a year — are last.
 *
 * The chase list is a DRY RUN. Opening this screen must not notify everybody
 * it names; the backend's `chase` route reads what is outstanding and delivers
 * nothing, and the wording here says so.
 */
export default function PlaybookPage() {
  const committees = useAsync(() => api.playbook.committees(), []);
  const packs = useAsync(() => api.playbook.packs({}), []);
  const chase = useAsync(() => api.playbook.chase(), []);

  const rows = packs.data?.packs ?? [];
  const open = rows.filter(
    (p) => !["APPROVED", "PUBLISHED", "SUPERSEDED", "ARCHIVED"].includes(
      p.status),
  );
  const upcoming = [...open].sort((a, b) => {
    if (!a.meeting_at) return 1;
    if (!b.meeting_at) return -1;
    return a.meeting_at.localeCompare(b.meeting_at);
  });
  const blocked = open.filter((p) => p.readiness_state === "RED");
  const outstanding = chase.data?.outstanding ?? [];

  return (
    <div className="mx-auto w-full max-w-6xl space-y-6 px-6 py-6">
      <PageHeader
        title="Playbook"
        description="Committee packs: what the committee is, when it meets, what goes in the pack, who reviewed it, what was decided and what follows."
        actions={
          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/playbook/committees">Committees</Link>
            </Button>
            <Button asChild size="sm">
              <Link href="/playbook/packs/new">New pack</Link>
            </Button>
          </div>
        }
      />

      <Unavailable state={packs} what="the packs you can see" />

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Committees" value={committees.data?.committees.length ?? 0} />
        <Stat label="Packs open" value={open.length} />
        <Stat
          label="Blocked"
          value={blocked.length}
          tone={blocked.length ? "negative" : undefined}
          hint="Something must be resolved before approval"
        />
        <Stat
          label="Waiting on somebody"
          value={outstanding.length}
          tone={outstanding.length ? "warning" : undefined}
        />
      </div>

      <SectionCard
        title="Next up"
        description="Open packs, soonest meeting first."
      >
        {packs.loading ? (
          <Empty>Loading…</Empty>
        ) : upcoming.length === 0 ? (
          <Empty>
            No pack is open. Start one from a committee, and it will be laid
            out from that committee&rsquo;s template.
          </Empty>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-text-muted">
                <th className="px-4 py-2 font-medium">Pack</th>
                <th className="px-4 py-2 font-medium">Period</th>
                <th className="px-4 py-2 font-medium">Meets</th>
                <th className="px-4 py-2 font-medium">Status</th>
                <th className="px-4 py-2 text-right font-medium">Ready</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {upcoming.map((pack) => (
                <tr key={pack.id} className="hover:bg-surface-hover">
                  <td className="px-4 py-2.5">
                    <Link
                      href={`/playbook/packs/${pack.id}`}
                      className="font-medium text-text-primary hover:text-accent"
                    >
                      {pack.name}
                    </Link>
                    <p className="text-xs text-text-muted">{pack.code}</p>
                  </td>
                  <td className="px-4 py-2.5 text-text-secondary">
                    {pack.period}
                  </td>
                  <td className="px-4 py-2.5 text-text-secondary">
                    {formatDay(pack.meeting_at)}
                    <span className="ml-1.5 text-xs text-text-muted">
                      {daysUntil(pack.meeting_at)}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    <PackStatus status={pack.status} label={pack.status_label} />
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    <span className="tabular-nums">
                      {pack.readiness_percent}%
                    </span>
                    <Badge
                      className="ml-2"
                      variant={
                        pack.readiness_state === "GREEN"
                          ? "positive"
                          : pack.readiness_state === "AMBER"
                            ? "warning"
                            : "negative"
                      }
                    >
                      {pack.readiness_state}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </SectionCard>

      <SectionCard
        title="Who you are waiting on"
        description="What the committee sweep would send if it ran now. Opening this screen sends nothing."
      >
        {chase.error ? (
          <div className="p-4">
            <Unavailable state={chase} what="the chase list" />
          </div>
        ) : outstanding.length === 0 ? (
          <Empty>
            Nothing outstanding. No pack is close enough to its meeting to
            chase anybody about.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {outstanding.map((message) => (
              <li key={message.fingerprint} className="px-4 py-3">
                <div className="flex items-baseline justify-between gap-3">
                  <span className="text-sm font-medium text-text-primary">
                    {message.title}
                  </span>
                  <Badge variant="outline">
                    {message.trigger.replace(/_/g, " ").toLowerCase()}
                  </Badge>
                </div>
                <p className="mt-1 text-xs text-text-secondary">
                  {message.body}
                </p>
                {message.pack_id && (
                  <Link
                    href={`/playbook/packs/${message.pack_id}`}
                    className="mt-1 inline-block text-xs text-accent hover:underline"
                  >
                    Open the pack
                  </Link>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard
        title="Committees"
        action={
          <Button asChild variant="ghost" size="sm">
            <Link href="/playbook/committees">Manage</Link>
          </Button>
        }
      >
        {committees.data?.committees.length === 0 ? (
          <Empty>
            No committee is set up yet. A data steward creates one, and becomes
            its first owner.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {(committees.data?.committees ?? []).map((committee) => (
              <li key={committee.id} className="px-4 py-3">
                <Link
                  href={`/playbook/committees/${committee.id}`}
                  className="text-sm font-medium text-text-primary hover:text-accent"
                >
                  {committee.name}
                </Link>
                <p className="mt-0.5 text-xs text-text-muted">
                  {committee.business_area || "No business area recorded"} ·{" "}
                  {committee.cadence.toLowerCase()}
                  {committee.demo && " · synthetic data"}
                </p>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}
