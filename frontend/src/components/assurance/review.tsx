"use client";

import * as React from "react";

import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type AssuranceReview } from "@/lib/api";

import { AssuranceFigure, DimensionStrip } from "./dimensions";
import { referenceText } from "./present";

/**
 * "HOW CREDITPROBE PERFORMED". §188-§199.
 *
 * The heading that makes this worth building is §197's "Why points were
 * lost". A score without it is a grade; with it, it is a review, and a reader
 * who disagrees can disagree with the named check rather than with the
 * number.
 *
 * Two numbers, never merged
 * --------------------------
 * §184. Operational assurance is what the runtime could prove about a run.
 * Reference match exists only where an approved answer exists, and where it
 * does not, this panel says so in a sentence rather than leaving a gap the
 * reader fills in with an assumption.
 *
 * Six panels, always six
 * -----------------------
 * Including the ones that measured nothing. A dimension dropped for having
 * no data is a dimension the reader concludes was fine.
 */

export function HowCreditProbePerformed({
  investigationId,
  recordId,
}: {
  investigationId: string;
  recordId?: string;
}) {
  const [data, setData] = React.useState<AssuranceReview | null>(null);
  const [error, setError] = React.useState("");

  React.useEffect(() => {
    let live = true;
    const load = recordId
      ? api.assuranceRecord(investigationId, recordId)
      : api.investigationAssurance(investigationId);
    load
      .then((body) => live && setData(body))
      .catch(
        (e: unknown) =>
          live &&
          setError(
            e instanceof Error
              ? e.message
              : "No assurance record is available for this Investigation.",
          ),
      );
    return () => {
      live = false;
    };
  }, [investigationId, recordId]);

  if (error) {
    return (
      <Card className="p-5">
        <p className="text-sm text-text-secondary">{error}</p>
      </Card>
    );
  }
  if (!data) return <Skeleton className="h-64 w-full" />;

  const head = data.header;

  return (
    <div className="space-y-4">
      <Card className="space-y-3 p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="text-sm font-medium text-text-primary">
            {data.button}
          </h3>
          <span className="text-xs font-medium text-text-primary">
            {head.status_now.replaceAll("_", " ")}
          </span>
        </div>
        <p className="text-sm leading-relaxed text-text-secondary">
          {head.status_means}
        </p>

        <dl className="grid gap-3 sm:grid-cols-2">
          <div>
            <dt className="text-xs font-medium text-text-primary">
              {head.operational_assurance_label}
            </dt>
            <dd className="text-sm">
              <AssuranceFigure
                score={head.operational_assurance}
                // The <dt> above already names it; repeating the label
                // here would read as two different figures.
                label=""
                status={head.overall_status}
              />
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-primary">
              Reference match
            </dt>
            <dd className="text-xs leading-relaxed text-text-secondary">
              {referenceText(data)}
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-primary">Coverage</dt>
            <dd className="text-xs text-text-secondary">
              {head.coverage_pct.toFixed(0)}% of applicable checks ran
            </dd>
          </div>
          <div>
            <dt className="text-xs font-medium text-text-primary">
              Critical failures
            </dt>
            <dd className="text-xs text-text-secondary">
              {head.critical_issues || "none"}
            </dd>
          </div>
        </dl>

        {head.stale ? (
          <p className="text-xs text-status-warning">
            This record describes a run on an earlier configuration:{" "}
            {head.stale_reasons.join("; ")}. Its verdict is still true of that
            run and is not re-scored.
          </p>
        ) : null}

        {data.integrity.intact ? null : (
          <p className="text-xs text-status-negative">
            This record no longer matches the checks it was sealed over. It is
            reported rather than repaired.
          </p>
        )}
      </Card>

      {data.dimensions.map((dimension) => (
        <Card key={dimension.dimension} className="space-y-3 p-5">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h4 className="text-sm font-medium text-text-primary">
              {dimension.label}
            </h4>
            <span className="text-xs text-text-tertiary">
              {dimension.measured
                ? `${dimension.status.replaceAll("_", " ")} · ${dimension.coverage_pct.toFixed(0)}% measured`
                : "nothing measured"}
            </span>
          </div>
          <p className="text-xs leading-relaxed text-text-secondary">
            {dimension.answers}
          </p>

          {dimension.applicability &&
          !dimension.applicability.applicable &&
          dimension.applicability.reason ? (
            <p className="text-xs leading-relaxed text-text-tertiary">
              {dimension.applicability.reason}
            </p>
          ) : null}

          {dimension.why_points_were_lost.length ? (
            <div>
              <p className="text-xs font-medium text-text-primary">
                Why points were lost
              </p>
              <ul className="mt-1 space-y-1">
                {dimension.why_points_were_lost.map((lost) => (
                  <li
                    key={lost.subcomponent}
                    className="text-xs leading-relaxed text-text-secondary"
                  >
                    · {lost.subcomponent.replaceAll("_", " ")} — {lost.why}{" "}
                    <span className="text-text-tertiary">
                      (cost: {lost.cost})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-xs text-text-tertiary">
              Nothing in this dimension lost points.
            </p>
          )}

          <details>
            <summary className="cursor-pointer text-xs font-medium text-text-link">
              What this dimension examines ({dimension.examines.length})
            </summary>
            <ul className="mt-2 space-y-0.5">
              {dimension.examines.map((item) => (
                <li key={item} className="text-xs text-text-tertiary">
                  · {item}
                </li>
              ))}
            </ul>
          </details>
        </Card>
      ))}

      <Card className="space-y-3 p-5">
        <h4 className="text-sm font-medium text-text-primary">
          Turn by turn ({data.timeline.length})
        </h4>
        <p className="text-xs leading-relaxed text-text-secondary">
          {data.thread.note}
        </p>
        <ul className="divide-y divide-border">
          {data.timeline.map((turn) => (
            <li key={turn.assurance_record_id} className="py-2.5">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="text-xs font-medium text-text-primary">
                  {turn.turn}. {turn.question || "(no question recorded)"}
                </p>
                <DimensionStrip cells={turn.dimensions} />
              </div>
              <p className="text-xs text-text-tertiary">
                {turn.overall_status.replaceAll("_", " ")} ·{" "}
                {turn.coverage_pct.toFixed(0)}% measured
                {turn.repairs ? ` · ${turn.repairs} repair(s)` : ""}
                {turn.feedback.bad ? ` · ${turn.feedback.bad} bad` : ""}
              </p>
            </li>
          ))}
        </ul>
      </Card>

      <Card className="space-y-3 p-5">
        <h4 className="text-sm font-medium text-text-primary">User feedback</h4>
        <p className="text-xs leading-relaxed text-text-secondary">
          {data.feedback.raw_user_feedback.note}
        </p>
        <p className="text-xs text-text-tertiary">
          {data.feedback.raw_user_feedback.good} good ·{" "}
          {data.feedback.raw_user_feedback.bad} bad ·{" "}
          {data.feedback.adjudicated_findings.length} adjudicated finding(s)
        </p>
        <p className="text-xs leading-relaxed text-text-tertiary">
          {data.feedback.adjudication_note}
        </p>
      </Card>

      {data.recommended_improvements.length ? (
        <Card className="space-y-2 p-5">
          <h4 className="text-sm font-medium text-text-primary">
            Recommended improvements
          </h4>
          <p className="text-xs text-text-tertiary">
            Recommendations, not automatic production changes.
          </p>
          <ul className="space-y-1">
            {data.recommended_improvements.map((step) => (
              <li
                key={`${step.subcomponent}-${step.suggestion}`}
                className="text-xs leading-relaxed text-text-secondary"
              >
                · {step.suggestion}{" "}
                <span className="text-text-tertiary">({step.because})</span>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
