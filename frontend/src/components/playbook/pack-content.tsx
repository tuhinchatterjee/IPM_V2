"use client";

import * as React from "react";

import {
  Empty,
  Figure,
  Movement,
  Problem,
  SectionCard,
  Working,
  formatWhen,
} from "@/components/playbook/parts";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";
import type { PlaybookBlock, PlaybookPack, PlaybookSection } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The pack itself: its pages, and what is on them.
 *
 * Two distinctions this component exists to keep visible, because flattening
 * either of them is how a committee ends up trusting the wrong thing:
 *
 *   1. A GOVERNED FIGURE is CreditProbe's own calculation, with a formula hash
 *      and a dataset version behind it. A number lifted out of an uploaded
 *      document is not, and is labelled as theirs until somebody maps it.
 *
 *   2. An AI DRAFT is nobody's words until a person accepts it. It is shown
 *      as a draft, it does not reach the export, and accepting it is an
 *      explicit act by a named person — never a side effect of scrolling past.
 */
export function PackContent({
  pack,
  onChanged,
}: {
  pack: PlaybookPack;
  onChanged: () => void;
}) {
  return (
    <div className="space-y-4">
      {pack.sections.map((section) => (
        <SectionPanel
          key={section.id}
          pack={pack}
          section={section}
          onChanged={onChanged}
        />
      ))}
      {pack.sections.length === 0 && (
        <SectionCard title="No pages yet">
          <Empty>
            This pack has no sections. One built from a template arrives with
            the committee&rsquo;s standard shape already on it.
          </Empty>
        </SectionCard>
      )}
    </div>
  );
}

const SECTION_TONE: Record<string, "default" | "info" | "warning" | "positive"> =
  {
    NOT_STARTED: "default",
    DRAFTING: "info",
    READY: "info",
    IN_REVIEW: "warning",
    CHANGES_REQUESTED: "warning",
    APPROVED: "positive",
  };

function SectionPanel({
  pack,
  section,
  onChanged,
}: {
  pack: PlaybookPack;
  section: PlaybookSection & { blocks: PlaybookBlock[] };
  onChanged: () => void;
}) {
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<unknown>(null);

  async function run(work: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await work();
      onChanged();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  const canEdit = pack.editable;
  const canReview = ["REVIEWER", "EDITOR", "APPROVER", "OWNER"].includes(
    pack.access,
  );

  return (
    <SectionCard
      title={section.title}
      description={section.purpose || undefined}
      action={
        <div className="flex items-center gap-2">
          <Badge variant={SECTION_TONE[section.status] ?? "default"}>
            {section.status_label}
          </Badge>
          {canEdit && section.status !== "IN_REVIEW" && (
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={() =>
                run(() => api.playbook.submitSection(section.id))
              }
            >
              Ready to read
            </Button>
          )}
          {canReview && section.status === "IN_REVIEW" && (
            <>
              <Button
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api.playbook.reviewSection(section.id, {
                      decision: "CHANGES_REQUESTED",
                      note: "Changes requested from the pack.",
                    }),
                  )
                }
              >
                Request changes
              </Button>
              <Button
                size="sm"
                disabled={busy}
                onClick={() =>
                  run(() =>
                    api.playbook.reviewSection(section.id, {
                      decision: "APPROVED",
                      note: "Read and approved.",
                    }),
                  )
                }
              >
                Approve section
              </Button>
            </>
          )}
        </div>
      }
    >
      {error != null && (
        <div className="px-4 pt-3">
          <Problem error={error} />
        </div>
      )}
      {section.blocks.length === 0 ? (
        <Empty>Nothing on this page yet.</Empty>
      ) : (
        <ul className="divide-y divide-border">
          {section.blocks.map((block) => (
            <BlockRow
              key={block.id}
              block={block}
              editable={canEdit}
              busy={busy}
              onRun={run}
            />
          ))}
        </ul>
      )}
    </SectionCard>
  );
}

function BlockRow({
  block,
  editable,
  busy,
  onRun,
}: {
  block: PlaybookBlock;
  editable: boolean;
  busy: boolean;
  onRun: (work: () => Promise<unknown>) => Promise<void>;
}) {
  const [showWorking, setShowWorking] = React.useState(false);
  const prose = ["NARRATIVE", "AI_NARRATIVE", "RISK_CALLOUT"].includes(
    block.block_type,
  );
  const unaccepted = block.source === "AI" && !block.ai_accepted;

  return (
    <li className="px-4 py-3">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-medium text-text-primary">
              {block.title || block.block_type.replace(/_/g, " ").toLowerCase()}
            </span>
            {block.import_class && (
              <Badge variant="outline" title="This came out of an uploaded document, not from CreditProbe.">
                {block.import_class === "UNMAPPED_TABLE"
                  ? "their figures"
                  : block.import_class.replace(/_/g, " ").toLowerCase()}
              </Badge>
            )}
            {unaccepted && (
              <Badge variant="warning" title="A person has not yet put their name to these words. Until somebody does, they stay out of the export.">
                AI draft — not accepted
              </Badge>
            )}
            {block.stale && (
              <Badge variant="warning" title="A figure this text refers to has moved since it was written.">
                figures have moved
              </Badge>
            )}
            {block.statement_kind && prose && (
              <Badge variant="default">
                {block.statement_kind.replace(/_/g, " ").toLowerCase()}
              </Badge>
            )}
          </div>

          {block.calculated ? (
            <div className="mt-1.5 flex items-baseline gap-3">
              <Figure figure={block.figure} size="large" />
              <Movement figure={block.figure} />
            </div>
          ) : (
            block.body && (
              <p
                className={cn(
                  "mt-1.5 whitespace-pre-wrap text-sm leading-relaxed",
                  unaccepted ? "text-text-muted italic" : "text-text-secondary",
                )}
              >
                {block.body}
              </p>
            )
          )}

          {block.import_class === "UNMAPPED_TABLE" && (
            <p className="mt-1.5 text-xs text-text-muted">
              These values came from an uploaded file. CreditProbe did not
              calculate them and is not asserting them. Map this table to a
              governed metric to show the platform&rsquo;s own figure beside
              them.
            </p>
          )}
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {block.figure && block.figure.availability === "OK" && (
            <Button
              size="sm"
              variant="ghost"
              onClick={() => setShowWorking((open) => !open)}
            >
              {showWorking ? "Hide working" : "Working"}
            </Button>
          )}
          {editable && block.calculated && (
            <Button
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => onRun(() => api.playbook.refreshBlock(block.id))}
            >
              Recalculate
            </Button>
          )}
          {editable && unaccepted && (
            <Button
              size="sm"
              disabled={busy}
              title="Accepting means the words are yours now."
              onClick={() =>
                onRun(() =>
                  api.playbook.updateBlock(block.id, { body: block.body }),
                )
              }
            >
              Accept
            </Button>
          )}
        </div>
      </div>

      {showWorking && block.figure && (
        <div className="mt-3 rounded-md border border-border bg-surface-sunken px-3 py-2.5">
          <Working figure={block.figure} />
          {block.figure.calculated_at && (
            <p className="mt-2 text-[11px] text-text-muted">
              Frozen {formatWhen(block.figure.calculated_at)}. The pack shows
              this snapshot rather than recalculating on open, which is what
              makes a tabled pack the same document every time it is opened.
            </p>
          )}
          {block.figure.warnings?.length > 0 && (
            <ul className="mt-2 space-y-0.5">
              {block.figure.warnings.map((warning, index) => (
                <li key={index} className="text-[11px] text-warning">
                  {warning}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}
