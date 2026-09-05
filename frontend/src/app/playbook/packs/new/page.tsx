"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Problem, SectionCard } from "@/components/playbook/parts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Starting a pack.
 *
 * Four things decide what the pack is, and all four are asked for here rather
 * than defaulted quietly:
 *
 *   the COMMITTEE     which forum reads it, and therefore who may see it
 *   the TEMPLATE      the shape the committee agreed its packs have
 *   the PERIOD        which reporting period every figure is measured at
 *   the COMPARISON    what "since last time" means on this pack
 *
 * A pack created with a guessed period is a pack whose every figure is
 * measured at a date nobody chose, which is the kind of mistake that survives
 * all the way to a meeting.
 */
function NewPackForm() {
  const router = useRouter();
  const search = useSearchParams();
  const committees = useAsync(() => api.playbook.committees(), []);

  const [committeeId, setCommitteeId] = React.useState(
    search.get("committee") ?? "");
  const templates = useAsync(
    () =>
      committeeId
        ? api.playbook.templates(Number(committeeId))
        : Promise.resolve({ templates: [] }),
    [committeeId],
  );

  // Null until the person picks one, and then their choice. The default is
  // DERIVED below rather than synced into state in an effect: syncing it
  // means the screen renders once with the wrong template selected and then
  // corrects itself, and a form that changes under somebody mid-keystroke is
  // a form they stop trusting.
  const [chosenTemplate, setChosenTemplate] = React.useState<string | null>(
    null);
  const [period, setPeriod] = React.useState("");
  const [comparison, setComparison] = React.useState("");
  const [meeting, setMeeting] = React.useState("");
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  // The committee's own APPROVED template is the default — but it is shown
  // rather than applied silently, so somebody starting a pack sees which
  // shape they are about to get.
  const available = templates.data?.templates ?? [];
  const suggested =
    available.find((t) => t.status === "PUBLISHED") ?? available[0];
  const templateId = chosenTemplate ?? (suggested ? String(suggested.id) : "");
  const setTemplateId = setChosenTemplate;

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const made = await api.playbook.createPack({
        committee_id: Number(committeeId),
        template_id: templateId ? Number(templateId) : null,
        period,
        comparison_period: comparison,
        meeting_at: meeting ? new Date(meeting).toISOString() : null,
        name: name || "",
      });
      router.push(`/playbook/packs/${made.id}`);
    } catch (e) {
      setError(e);
      setBusy(false);
    }
  }

  const chosen = available.find((t) => String(t.id) === templateId);

  return (
    <div className="mx-auto w-full max-w-2xl space-y-5 px-6 py-6">
      <PageHeader
        title="A new committee pack"
        description="It is laid out from the committee's template, and nothing is calculated until you generate it."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href="/playbook">Cancel</Link>
          </Button>
        }
      />

      <Unavailable state={committees} what="the committees you belong to" />

      <SectionCard title="What this pack is">
        <div className="space-y-4 px-4 py-4">
          <label className="block text-xs font-medium text-text-secondary">
            Committee
            <select
              value={committeeId}
              onChange={(e) => setCommitteeId(e.target.value)}
              className="mt-1 block w-full rounded-md border border-border bg-surface px-2 py-2 text-sm text-text-primary"
            >
              <option value="">Choose a committee…</option>
              {(committees.data?.committees ?? []).map((committee) => (
                <option key={committee.id} value={String(committee.id)}>
                  {committee.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block text-xs font-medium text-text-secondary">
            Shape
            <select
              value={templateId}
              onChange={(e) => setTemplateId(e.target.value)}
              disabled={!committeeId}
              className="mt-1 block w-full rounded-md border border-border bg-surface px-2 py-2 text-sm text-text-primary"
            >
              <option value="">
                No template — every page added by hand
              </option>
              {available.map((template) => (
                <option key={template.id} value={String(template.id)}>
                  {template.name} (v{template.version},{" "}
                  {template.status.toLowerCase()})
                </option>
              ))}
            </select>
            {chosen && (
              <span className="mt-1 block text-[11px] font-normal text-text-muted">
                {chosen.sections.length} section
                {chosen.sections.length === 1 ? "" : "s"} and{" "}
                {chosen.materiality.length} materiality rule
                {chosen.materiality.length === 1 ? "" : "s"} will come with it.
                The pack keeps this version even if the template moves on.
              </span>
            )}
          </label>

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block text-xs font-medium text-text-secondary">
              Reporting period
              <Input
                value={period}
                onChange={(e) => setPeriod(e.target.value)}
                placeholder="2025-01"
                className="mt-1"
              />
              <span className="mt-1 block text-[11px] font-normal text-text-muted">
                Every figure on the pack is measured at this period.
              </span>
            </label>
            <label className="block text-xs font-medium text-text-secondary">
              Compared with
              <Input
                value={comparison}
                onChange={(e) => setComparison(e.target.value)}
                placeholder="2024-12"
                className="mt-1"
              />
              <span className="mt-1 block text-[11px] font-normal text-text-muted">
                What &ldquo;since last time&rdquo; means here.
              </span>
            </label>
          </div>

          <label className="block text-xs font-medium text-text-secondary">
            Meeting date
            <Input
              type="datetime-local"
              value={meeting}
              onChange={(e) => setMeeting(e.target.value)}
              className="mt-1"
            />
            <span className="mt-1 block text-[11px] font-normal text-text-muted">
              Everything the committee sweep chases is counted back from here.
            </span>
          </label>

          <label className="block text-xs font-medium text-text-secondary">
            Name (optional)
            <Input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Left blank, it is named from the committee and the period."
              className="mt-1"
            />
          </label>

          {error != null && <Problem error={error} />}

          <Button
            disabled={busy || !committeeId || !period.trim()}
            onClick={create}
          >
            {busy ? "Creating…" : "Create the pack"}
          </Button>
        </div>
      </SectionCard>
    </div>
  );
}

export default function NewPackPage() {
  return (
    <React.Suspense
      fallback={
        <div className="mx-auto w-full max-w-2xl px-6 py-10 text-sm text-text-muted">
          Loading…
        </div>
      }
    >
      <NewPackForm />
    </React.Suspense>
  );
}
