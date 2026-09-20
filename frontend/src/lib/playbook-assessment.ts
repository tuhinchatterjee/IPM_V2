/**
 * Reading the completion card a delivered message carries.
 *
 * The backend counts it from stored rows (`backend/playbook/assessment.py`);
 * this turns that record into the handful of lines a person reads under their
 * files. React-free on purpose, so what it says can be asserted directly
 * rather than through a rendered component.
 *
 * Two rules hold here as well as in the backend:
 *
 *   * nothing is computed that was not counted. There is no percentage, no
 *     score and no "8 of 10 complete" — a denominator the document never
 *     declared is the invented completion figure chapter 12 forbids;
 *   * the written verdict is labelled as judgement wherever it appears, and
 *     it is never shown without the counts beside it.
 */

export interface PbAssessmentCard {
  available?: boolean;
  reason?: string;
  version?: number;
  title?: string;
  sections?: {
    total?: number;
    written?: number;
    thin?: string[];
    gaps?: string[];
  };
  files?: { delivered?: string[]; failed?: Record<string, string> };
  evidence?: {
    sources?: {
      filename?: string;
      complete?: boolean;
      cited?: number;
      skipped?: { what?: string; why?: string }[];
    }[];
    omissions?: { what?: string; why?: string }[];
  };
  untraceable?: { section?: string; figures?: string[] }[];
  review?: { label?: string; open_items?: number };
  time?: {
    authoring_ms?: number;
    render_ms?: number;
    provider_ms?: number;
    total_ms?: number;
  };
  verdict?: string;
  verdict_state?: string;
}

/** One line of the card: what it measured, and what it found. */
export interface AssessmentLine {
  key: string;
  label: string;
  value: string;
  /** "plain" for a measurement, "attention" for something to look at. */
  tone: "plain" | "attention";
}

/** "4m 12s", or "8s". The same shape the progress clock uses. */
export function duration(ms: number): string {
  const whole = Math.max(0, Math.round(ms / 1000));
  const minutes = Math.floor(whole / 60);
  return minutes ? `${minutes}m ${whole % 60}s` : `${whole}s`;
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/**
 * The card as lines, in the order they matter to somebody who has just been
 * handed a document: what they got, what is not finished, what cannot be
 * traced, what was not read, whether anyone has checked it, and how long it
 * took.
 */
export function assessmentLines(card: PbAssessmentCard): AssessmentLine[] {
  if (!card || card.available !== true) return [];
  const lines: AssessmentLine[] = [];

  const delivered = card.files?.delivered ?? [];
  const failed = Object.entries(card.files?.failed ?? {});
  lines.push({
    key: "files",
    label: "Delivered",
    value: delivered.length
      ? delivered.map((f) => f.toUpperCase()).join(", ")
      : "no file",
    tone: delivered.length ? "plain" : "attention",
  });
  if (failed.length) {
    lines.push({
      key: "failed",
      label: "Not produced",
      value: failed.map(([f, why]) => `${f.toUpperCase()} — ${why}`).join("; "),
      tone: "attention",
    });
  }

  const sections = card.sections ?? {};
  const total = sections.total ?? 0;
  const written = sections.written ?? 0;
  lines.push({
    key: "sections",
    label: "Sections",
    // Written out of the sections that exist — which is a count of what is
    // there, not a share of a plan nobody wrote down.
    value: `${written} of ${plural(total, "section")} written in full`,
    tone: written === total ? "plain" : "attention",
  });

  const gaps = sections.gaps ?? [];
  if (gaps.length) {
    lines.push({
      key: "gaps",
      label: "States a gap",
      value: gaps.join("; "),
      tone: "attention",
    });
  }
  const thin = sections.thin ?? [];
  if (thin.length) {
    lines.push({
      key: "thin",
      label: "Barely written",
      value: thin.join("; "),
      tone: "attention",
    });
  }

  const untraceable = card.untraceable ?? [];
  if (untraceable.length) {
    lines.push({
      key: "untraceable",
      label: "Figures with no source",
      value: untraceable
        .map((f) => `${(f.figures ?? []).join(", ")} (${f.section || "untitled"})`)
        .join("; "),
      tone: "attention",
    });
  }

  for (const source of card.evidence?.sources ?? []) {
    const read = source.complete ? "read in full" : "read in part";
    const used =
      (source.cited ?? 0) > 0
        ? `${plural(source.cited ?? 0, "passage")} used`
        : "nothing from it was used";
    lines.push({
      key: `source:${source.filename}`,
      label: source.filename ?? "Source",
      value: `${read}, ${used}`,
      tone: source.complete && (source.cited ?? 0) > 0 ? "plain" : "attention",
    });
  }

  const omissions = card.evidence?.omissions ?? [];
  if (omissions.length) {
    lines.push({
      key: "omissions",
      label: "Not read",
      value: omissions
        .map((o) => [o.what, o.why].filter(Boolean).join(" — "))
        .join("; "),
      tone: "attention",
    });
  }

  const review = card.review ?? {};
  lines.push({
    key: "review",
    label: "Checked by",
    value:
      review.label && review.label !== "Draft"
        ? `${review.label}${review.open_items ? `, ${plural(review.open_items, "open item")}` : ""}`
        : "nobody yet — this is a draft",
    tone: review.label && review.label !== "Draft" ? "plain" : "attention",
  });

  const time = card.time ?? {};
  if (time.total_ms) {
    lines.push({
      key: "time",
      label: "Time taken",
      value: `${duration(time.total_ms)} — ${duration(
        time.authoring_ms ?? 0,
      )} writing, ${duration(time.render_ms ?? 0)} building the files`,
      tone: "plain",
    });
  }

  return lines;
}

/** Whether there is anything to show at all. */
export function hasAssessment(card: PbAssessmentCard | undefined): boolean {
  return Boolean(card && card.available === true);
}
