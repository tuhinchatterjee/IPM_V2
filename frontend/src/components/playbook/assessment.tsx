"use client";

import * as React from "react";

import {
  assessmentLines,
  hasAssessment,
  type PbAssessmentCard,
} from "@/lib/playbook-assessment";

/**
 * What you got, under the files you got.
 *
 * A user waited, received a Word file and a PDF, and was told nothing about
 * either. Everything here was already in the database — which sections say
 * their evidence is missing, which figures nothing supports, which sources
 * were read in part, whether anybody has checked it, and where the minutes
 * went — and none of it was ever shown.
 *
 * The counts come first and the written note comes second, labelled as
 * judgement. That order is the point: a paragraph of prose about a document,
 * with no measurements beside it, is the thing chapter 12 forbids, and one
 * shown ABOVE them invites the reader to stop there.
 */
export function AssessmentCard({ card }: { card: PbAssessmentCard }) {
  if (!hasAssessment(card)) return null;
  const lines = assessmentLines(card);
  const verdict = card.verdict_state === "written" ? card.verdict ?? "" : "";

  return (
    <section
      className="rounded-lg border border-border bg-surface-sunken p-3"
      data-testid="playbook-assessment"
      aria-label="What was delivered"
    >
      <p className="meta mb-2">
        What was delivered
        {card.version ? (
          <span className="text-text-muted"> · version {card.version}</span>
        ) : null}
      </p>

      <dl className="space-y-1">
        {lines.map((line) => (
          <div
            key={line.key}
            className="flex gap-2 text-xs"
            data-testid={`playbook-assessment-${line.key}`}
          >
            <dt className="w-36 shrink-0 text-text-muted">{line.label}</dt>
            <dd
              className={
                line.tone === "attention"
                  ? "flex-1 text-text-primary"
                  : "flex-1 text-text-secondary"
              }
            >
              {line.value}
            </dd>
          </div>
        ))}
      </dl>

      {verdict && (
        <div className="mt-3 border-t border-border pt-2">
          <p className="meta mb-1" data-testid="playbook-assessment-label">
            CreditProbe AI&apos;s reading of the above — judgement, not
            measurement
          </p>
          <p
            className="text-xs text-text-secondary"
            data-testid="playbook-assessment-verdict"
          >
            {verdict}
          </p>
        </div>
      )}
    </section>
  );
}
