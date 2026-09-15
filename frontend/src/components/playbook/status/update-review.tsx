"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { StatusChip } from "@/components/playbook/status/chips";
import type { PbUpdateProposal } from "@/lib/api";

/**
 * What a refresh WOULD do. §16, §23.
 *
 * Every line here is a proposal. Nothing on this screen has been applied and
 * nothing will be until somebody chooses it: **never auto-rewrite the document
 * simply because data changed** is the rule, and a dialog that quietly
 * rewrote on open would be the most direct possible violation of it.
 *
 * "Do nothing" is a real option and is given the same weight as the others,
 * because on a governed pack it is frequently the right one.
 */
export function UpdateReview({
  open,
  proposal,
  loading,
  onClose,
  onReviewChanges,
  onRefreshSections,
  onRereadSources,
}: {
  open: boolean;
  proposal: PbUpdateProposal | null;
  loading: boolean;
  onClose: () => void;
  onReviewChanges: (tab: string) => void;
  onRefreshSections: () => void;
  onRereadSources: () => void;
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Update review"
      description="What has changed since this document was written. Nothing here has been applied."
      size="lg"
    >
      <div className="space-y-4" data-testid="playbook-update-review">
        {loading ? (
          <p className="text-sm text-text-muted">Looking…</p>
        ) : !proposal ? (
          <p className="text-sm text-text-muted">Nothing to report.</p>
        ) : !proposal.anything ? (
          <p className="rounded-md border border-positive/40 bg-positive-muted p-3 text-sm text-text-primary">
            {proposal.message}
          </p>
        ) : (
          <>
            <ul className="space-y-1">
              {proposal.summary.map((line) => (
                <li key={line} className="text-sm text-text-primary">
                  {line}
                </li>
              ))}
            </ul>

            {proposal.metrics.length > 0 && (
              <Group title="Metrics with newer values">
                {proposal.metrics.map((m) => (
                  <Row key={m.binding_id}
                    title={m.label}
                    detail={
                      m.then && m.now
                        ? `${m.then} → ${m.now}${m.change ? ` (${m.change})` : ""}`
                        : m.reason
                    }
                    chip={m.direction === "worse" ? "red" : "amber"}
                    chipLabel={m.direction || m.freshness}
                  />
                ))}
              </Group>
            )}

            {proposal.sections.length > 0 && (
              <Group title="Sections that rest on them">
                {proposal.sections.map((s) => (
                  <Row key={s.section_key} title={s.heading}
                    detail={s.metrics.join(", ")} chip="amber"
                    chipLabel="affected" />
                ))}
              </Group>
            )}

            {proposal.findings.length > 0 && (
              <Group title="Findings that may need reconsidering">
                {proposal.findings.map((f) => (
                  <Row key={f.finding_id}
                    title={`${f.reference ? `${f.reference} ` : ""}${f.title}`}
                    detail={f.reason} chip="amber" chipLabel={f.status} />
                ))}
              </Group>
            )}

            {proposal.decisions.length > 0 && (
              <Group title="Decisions that may need updated wording">
                {proposal.decisions.map((d) => (
                  <Row key={d.decision_id}
                    title={`${d.reference ? `${d.reference} ` : ""}${d.question}`}
                    detail={d.reason} chip="amber" chipLabel={d.status} />
                ))}
              </Group>
            )}

            {proposal.sources.length > 0 && (
              <Group title="Sources that need re-reading">
                {proposal.sources.map((s) => (
                  <Row key={s.source_id} title={s.filename}
                    detail={s.reason_label} chip="amber" chipLabel="stale" />
                ))}
              </Group>
            )}

            {proposal.suggestions.length > 0 && (
              <Group title="Suggested metric links waiting for review">
                {proposal.suggestions.map((s) => (
                  <Row key={s.binding_id} title={s.label}
                    detail={`${s.value} · ${s.source_locator}`}
                    chip="amber" chipLabel="unconfirmed" />
                ))}
              </Group>
            )}

            <p className="rounded-md border border-border bg-surface-sunken p-3 text-[11px] leading-relaxed text-text-muted">
              None of this has changed the document. Refreshing a section
              produces proposed changes for review; it does not rewrite
              anything on its own.
            </p>
          </>
        )}
      </div>

      <div className="mt-4 flex flex-wrap justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={onClose}
          data-testid="playbook-update-do-nothing">
          Do nothing
        </Button>
        {proposal?.sources.length ? (
          <Button variant="outline" size="sm" onClick={onRereadSources}
            data-testid="playbook-update-reread">
            Re-read stale sources
          </Button>
        ) : null}
        {proposal?.anything ? (
          <Button variant="outline" size="sm"
            onClick={() => onReviewChanges("since")}
            data-testid="playbook-update-review-changes">
            Review changes
          </Button>
        ) : null}
        {proposal?.sections.length ? (
          <Button size="sm" onClick={onRefreshSections}
            data-testid="playbook-update-refresh-sections">
            Update affected sections
          </Button>
        ) : null}
      </div>
    </Dialog>
  );
}

function Group({ title, children }: { title: string;
  children: React.ReactNode }) {
  return (
    <section>
      <h3 className="text-[11px] font-semibold uppercase tracking-wide text-text-muted">
        {title}
      </h3>
      <ul className="mt-1.5 space-y-1.5">{children}</ul>
    </section>
  );
}

function Row({
  title,
  detail,
  chip,
  chipLabel,
}: {
  title: string;
  detail: string;
  chip: "amber" | "red";
  chipLabel: string;
}) {
  return (
    <li className="flex items-start gap-2 rounded border border-border bg-surface-sunken px-2 py-1.5">
      <div className="min-w-0 flex-1">
        <p className="text-xs text-text-primary">{title}</p>
        {detail && (
          <p className="text-[11px] leading-relaxed text-text-muted">
            {detail}
          </p>
        )}
      </div>
      <StatusChip tone={chip}>{chipLabel.replace(/_/g, " ")}</StatusChip>
    </li>
  );
}
