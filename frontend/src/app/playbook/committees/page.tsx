"use client";

import Link from "next/link";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import {
  Empty,
  Problem,
  SectionCard,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

const CADENCES = ["MONTHLY", "QUARTERLY", "SEMI_ANNUAL", "ANNUAL", "AD_HOC"];
const WEEKDAYS = [
  "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
];

/**
 * The committees this reader belongs to, and standing up a new one.
 *
 * Standing up a committee is an administrator or data steward decision — it
 * defines how a part of the bank governs itself — and the creator becomes its
 * first owner, because a committee nobody can administer is one nobody can
 * open. The form is refused by the API for anybody else, and the refusal says
 * what access is needed rather than hiding the form and leaving them guessing.
 */
export default function CommitteesPage() {
  const committees = useAsync(() => api.playbook.committees(), []);
  const [adding, setAdding] = React.useState(false);

  return (
    <div className="mx-auto w-full max-w-4xl space-y-5 px-6 py-6">
      <PageHeader
        title="Committees"
        description="The forums CreditProbe produces packs for: what each one is, how often it meets, and who sits on it."
        actions={
          <div className="flex gap-2">
            <Button asChild variant="outline" size="sm">
              <Link href="/playbook">Back to Playbook</Link>
            </Button>
            <Button size="sm" onClick={() => setAdding((was) => !was)}>
              {adding ? "Cancel" : "New committee"}
            </Button>
          </div>
        }
      />

      {adding && <NewCommittee onDone={() => {
        setAdding(false);
        committees.reload();
      }} />}

      <Unavailable state={committees} what="the committees you belong to" />

      <SectionCard title="Your committees">
        {committees.loading ? (
          <Empty>Loading…</Empty>
        ) : (committees.data?.committees.length ?? 0) === 0 ? (
          <Empty>
            You are not on any committee. Somebody who owns one adds you to it,
            and it appears here.
          </Empty>
        ) : (
          <ul className="divide-y divide-border">
            {(committees.data?.committees ?? []).map((committee) => (
              <li key={committee.id} className="px-4 py-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Link
                    href={`/playbook/committees/${committee.id}`}
                    className="text-sm font-medium text-text-primary hover:text-accent"
                  >
                    {committee.name}
                  </Link>
                  <Badge variant="outline">{committee.code}</Badge>
                  <Badge variant="default">
                    {committee.cadence.replace(/_/g, " ").toLowerCase()}
                  </Badge>
                  {!committee.active && (
                    <Badge variant="warning">inactive</Badge>
                  )}
                  {committee.demo && (
                    <Badge variant="default">synthetic data</Badge>
                  )}
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {committee.business_area || "No business area recorded"}
                  {committee.meeting_weekday !== null &&
                    ` · usually meets on a ${WEEKDAYS[committee.meeting_weekday]}`}
                </p>
                {committee.purpose && (
                  <p className="mt-1 text-xs text-text-secondary">
                    {committee.purpose}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionCard>
    </div>
  );
}

function NewCommittee({ onDone }: { onDone: () => void }) {
  const [name, setName] = React.useState("");
  const [area, setArea] = React.useState("");
  const [purpose, setPurpose] = React.useState("");
  const [cadence, setCadence] = React.useState("MONTHLY");
  const [weekday, setWeekday] = React.useState("2");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      await api.playbook.createCommittee({
        name,
        business_area: area,
        purpose,
        cadence,
        meeting_weekday: Number(weekday),
      });
      onDone();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  return (
    <SectionCard
      title="A new committee"
      description="You become its owner, because a committee nobody can administer is one nobody can open."
    >
      <div className="space-y-3 px-4 py-3">
        <Input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Name — for example, Retail Credit Risk Committee"
        />
        <Input
          value={area}
          onChange={(e) => setArea(e.target.value)}
          placeholder="Business area"
        />
        <Input
          value={purpose}
          onChange={(e) => setPurpose(e.target.value)}
          placeholder="What this committee is for."
        />
        <div className="flex flex-wrap gap-3">
          <label className="text-xs text-text-secondary">
            Cadence
            <select
              value={cadence}
              onChange={(e) => setCadence(e.target.value)}
              className="ml-2 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary"
            >
              {CADENCES.map((option) => (
                <option key={option} value={option}>
                  {option.replace(/_/g, " ").toLowerCase()}
                </option>
              ))}
            </select>
          </label>
          <label className="text-xs text-text-secondary">
            Usually meets on a
            <select
              value={weekday}
              onChange={(e) => setWeekday(e.target.value)}
              className="ml-2 rounded-md border border-border bg-surface px-2 py-1 text-sm text-text-primary"
            >
              {WEEKDAYS.map((day, index) => (
                <option key={day} value={String(index)}>
                  {day}
                </option>
              ))}
            </select>
          </label>
        </div>
        {error != null && <Problem error={error} />}
        <Button size="sm" disabled={busy || !name.trim()} onClick={create}>
          {busy ? "Creating…" : "Create the committee"}
        </Button>
      </div>
    </SectionCard>
  );
}
