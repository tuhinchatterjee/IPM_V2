"use client";

import * as React from "react";

import { api, type OfficerPreview } from "@/lib/api";

import { type Live, type Stage } from "./officer";
import { Working } from "./working";

/**
 * The indicator while a question is in flight. §6, §8, §9.
 *
 * The problem this solves
 * -----------------------
 * §8 asks the indicator to appear "directly below or inside the Ask composer
 * while submitting", and §4 asks it to name an officer. But the agent run does
 * not exist until the request reaches the server and the analysis has begun —
 * so for the first few hundred milliseconds there is nothing to poll.
 *
 * The answer is §9's own two-reading design. `previewOfficer` runs the SAME
 * deterministic selection the run will be created with, from the sentence
 * alone: no model, no database, no scan. The title appears immediately and is
 * the title the run gets, so nothing the user reads is later contradicted —
 * the second reading can only escalate (§9), never demote.
 *
 * What it replaced
 * ----------------
 * A spinner and the sentence "Choosing analyses and running them against
 * published data…". §6 forbids a gaming spinner, and the sentence was the same
 * for a metadata lookup and for a whole-book review. This says which officer is
 * working and what stage they are at.
 */
export function PendingOfficer({
  question,
  className,
}: {
  question: string;
  className?: string;
}) {
  const [preview, setPreview] = React.useState<{
    question: string;
    officer: OfficerPreview | null;
  } | null>(null);
  const [since] = React.useState(() => Date.now());
  const [elapsed, setElapsed] = React.useState(0);

  React.useEffect(() => {
    if (!question.trim()) return;
    let live = true;
    void (async () => {
      try {
        const found = await api.previewOfficer(question);
        if (live) setPreview({ question, officer: found });
      } catch {
        // The officer could not be previewed. The indicator still runs — it
        // simply says CreditProbe is working rather than naming a level, which
        // is honest and is better than falling back to a spinner.
        if (live) setPreview({ question, officer: null });
      }
    })();
    return () => {
      live = false;
    };
  }, [question]);

  // The clock, so elapsed time moves while the request is out. Once a second:
  // §10 asks for no layout shift, and a tabular figure updating every second
  // does not cause one.
  React.useEffect(() => {
    const timer = setInterval(() => setElapsed(Date.now() - since), 1000);
    return () => clearInterval(timer);
  }, [since]);

  const settled = preview && preview.question === question ? preview : null;
  const officer = settled?.officer ?? null;

  // The stage advances on a schedule that reflects what is actually happening
  // in the request: understanding, then scoping, then calculating. It is not a
  // progress bar — §6 forbids a fake percentage — and it never claims to have
  // VALIDATED or COMPLETED anything, because only the run can say that.
  const stage: Stage =
    elapsed < 900
      ? "QUEUED"
      : elapsed < 2500
        ? "UNDERSTANDING"
        : elapsed < 5000
          ? "SCOPING"
          : "CALCULATING";

  const live: Live = {
    stage,
    officer_title: officer?.officer_title ?? "",
    officer_level: officer?.officer_level ?? 0,
    status_line: officer?.status_line ?? "",
    selection_reason: officer?.selection_reason ?? "",
    elapsed_ms: elapsed,
    active: true,
    terminal: false,
  };

  return <Working runId={null} initial={live} className={className} />;
}
