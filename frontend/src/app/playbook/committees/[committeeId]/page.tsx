"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import {
  Empty,
  PackStatus,
  Problem,
  SectionCard,
  daysUntil,
  formatDay,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import type { PlaybookCommitteeDetail } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

const ACCESS = [
  { value: "VIEWER", hint: "Reads packs." },
  { value: "CONTRIBUTOR", hint: "Writes the sections they own." },
  { value: "REVIEWER", hint: "Records that they read a section." },
  { value: "EDITOR", hint: "Edits any section on the pack." },
  { value: "APPROVER", hint: "Signs a pack off." },
  { value: "OWNER", hint: "Runs the committee." },
];

const BUSINESS_ROLES = [
  "CHAIR", "SECRETARY", "PACK_OWNER", "MEMBER", "PRESENTER", "OBSERVER",
];

/**
 * One committee: who is on it, what shape its packs take, and its packs.
 *
 * Access here is the whole permission model of the area. A person's ACCESS
 * role decides what they may do to a pack (`VIEWER` through `OWNER`); their
 * BUSINESS role is what they are called in the room (chair, secretary), which
 * is not the same thing and is deliberately stored separately — a chair who
 * does not sign packs is a real arrangement.
 */
export default function CommitteePage() {
  const params = useParams<{ committeeId: string }>();
  const committeeId = Number(params.committeeId);
  const committee = useAsync(
    () => api.playbook.committee(committeeId), [committeeId]);
  const templates = useAsync(
    () => api.playbook.templates(committeeId), [committeeId]);

  if (committee.error && !committee.data) {
    return (
      <div className="mx-auto w-full max-w-4xl px-6 py-10">
        <Unavailable state={committee} what="this committee" />
        <p className="mt-4 text-sm text-text-muted">
          <Link href="/playbook" className="text-accent hover:underline">
            Back to Playbook
          </Link>
        </p>
      </div>
    );
  }

  const data = committee.data;
  if (!data) {
    return (
      <div className="mx-auto w-full max-w-4xl px-6 py-10 text-sm text-text-muted">
        Loading…
      </div>
    );
  }

  const canAdminister = ["OWNER"].includes(data.access);

  return (
    <div className="mx-auto w-full max-w-5xl space-y-5 px-6 py-6">
      <PageHeader
        title={data.name}
        description={
          data.purpose ||
          `${data.business_area || "No business area recorded"} · meets ${data.cadence.toLowerCase()}`
        }
        actions={
          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/playbook/committees">All committees</Link>
            </Button>
            <Button asChild size="sm">
              <Link href={`/playbook/packs/new?committee=${data.id}`}>
                New pack
              </Link>
            </Button>
          </div>
        }
      />

      <SectionCard
        title="Packs"
        description="Newest meeting first. An approved pack renders from the snapshots it was approved with."
      >
        {data.packs.length === 0 ? (
          <Empty>
            This committee has no packs yet. Start one and it will be laid out
            from the committee&rsquo;s template.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {data.packs.map((pack) => (
              <li key={pack.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/playbook/packs/${pack.id}`}
                    className="text-sm font-medium text-text-primary hover:text-accent"
                  >
                    {pack.name}
                  </Link>
                  <PackStatus status={pack.status} label={pack.status_label} />
                  {pack.amends_pack_id && (
                    <Badge variant="warning">amendment</Badge>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {pack.period} · meets {formatDay(pack.meeting_at)} (
                  {daysUntil(pack.meeting_at)}) · {pack.readiness_percent}%
                  ready
                </p>
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <Members
        committee={data}
        canAdminister={canAdminister}
        onChanged={committee.reload}
      />

      <SectionCard
        title="Pack shape"
        description="The template a new pack is laid out from, and the declared thresholds its findings come from."
      >
        {templates.loading ? (
          <Empty>Loading…</Empty>
        ) : (templates.data?.templates.length ?? 0) === 0 ? (
          <Empty>
            This committee has no template. A pack started without one is empty
            and every page has to be added by hand.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {(templates.data?.templates ?? []).map((template) => (
              <li key={template.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-sm font-medium text-text-primary">
                    {template.name}
                  </span>
                  <Badge variant="outline">v{template.version}</Badge>
                  <Badge
                    variant={
                      template.status === "APPROVED" ? "positive" : "default"
                    }
                  >
                    {template.status.toLowerCase()}
                  </Badge>
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {template.sections.length} section
                  {template.sections.length === 1 ? "" : "s"} ·{" "}
                  {template.materiality.length} materiality rule
                  {template.materiality.length === 1 ? "" : "s"}
                </p>
                {template.description && (
                  <p className="mt-1 text-xs text-text-secondary">
                    {template.description}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>

      <SectionCard title="When things are due">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 px-4 py-3 text-xs">
          {Object.entries(data.offsets).map(([step, days]) => (
            <React.Fragment key={step}>
              <dt className="text-text-muted">
                {step.replace(/_/g, " ")}
              </dt>
              <dd className="text-text-secondary">
                {days} day{days === 1 ? "" : "s"} before the meeting
              </dd>
            </React.Fragment>
          ))}
        </dl>
      </SectionCard>
    </div>
  );
}

function Members({
  committee,
  canAdminister,
  onChanged,
}: {
  committee: PlaybookCommitteeDetail;
  canAdminister: boolean;
  onChanged: () => void;
}) {
  const [adding, setAdding] = React.useState(false);
  const [userId, setUserId] = React.useState("");
  const [access, setAccess] = React.useState("CONTRIBUTOR");
  const [role, setRole] = React.useState("MEMBER");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  async function add() {
    setBusy(true);
    setError(null);
    try {
      await api.playbook.addMember(committee.id, {
        user_id: Number(userId),
        access_role: access,
        business_role: role,
      });
      setAdding(false);
      setUserId("");
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="Who is on it"
      description="Access decides what somebody may do to a pack. Their role is what they are called in the room — a chair who does not sign packs is a real arrangement."
      action={
        canAdminister && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setAdding((was) => !was)}
          >
            {adding ? "Cancel" : "Add somebody"}
          </Button>
        )
      }
    >
      {adding && (
        <div className="space-y-2 border-b border-border px-4 py-3">
          <Input
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="User id"
            inputMode="numeric"
          />
          <div className="flex flex-wrap gap-3">
            <label className="text-xs text-text-secondary">
              Access
              <select
                value={access}
                onChange={(e) => setAccess(e.target.value)}
                className="ml-2 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary"
              >
                {ACCESS.map((option) => (
                  <option
                    key={option.value}
                    value={option.value}
                    title={option.hint}
                  >
                    {option.value.toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
            <label className="text-xs text-text-secondary">
              Role in the room
              <select
                value={role}
                onChange={(e) => setRole(e.target.value)}
                className="ml-2 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary"
              >
                {BUSINESS_ROLES.map((option) => (
                  <option key={option} value={option}>
                    {option.replace(/_/g, " ").toLowerCase()}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <p className="text-[11px] text-text-muted">
            {ACCESS.find((option) => option.value === access)?.hint}
          </p>
          {error != null && <Problem error={error} />}
          <Button size="sm" disabled={busy || !userId.trim()} onClick={add}>
            Add to the committee
          </Button>
        </div>
      )}

      {committee.members.length === 0 ? (
        <Empty>Nobody is on this committee.</Empty>
      ) : (
        <ul className="divide-y divide-border">
          {committee.members.map((member) => (
            <li
              key={member.id}
              className="flex flex-wrap items-center gap-2 px-4 py-2.5"
            >
              <span className="text-sm text-text-primary">
                User {member.user_id}
              </span>
              <Badge variant="accent">
                {member.access_role.toLowerCase()}
              </Badge>
              <Badge variant="outline">
                {member.business_role.replace(/_/g, " ").toLowerCase()}
              </Badge>
              {!member.active && <Badge variant="default">inactive</Badge>}
              {!member.notify && (
                <Badge variant="default" title="Excluded from the committee sweep.">
                  not chased
                </Badge>
              )}
            </li>
          ))}
        </ul>
      )}
    </SectionCard>
  );
}
