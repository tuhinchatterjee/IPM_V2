/**
 * Playbook's screen logic, with no React in it.
 *
 * This repository's only testable frontend layer is the React-free module, and
 * every rule worth asserting lives here rather than inside a component: the
 * order of the home screen, which quick prompts exist, what a source's parse
 * status actually means, and — the one most easily got wrong — which follow-up
 * suggestions are honest given the state the workspace is really in.
 */

import type {
  PbAnalysisPreview,
  PbArtifact,
  PbCapabilities,
  PbSource,
  PbWorkspace,
} from "./api";

// ---------------------------------------------------------------- home order

/**
 * §3 fixes this order and it is not a matter of taste: the composer is the
 * product, the prompts explain what to type into it, the work already under way
 * comes before the raw material, and the raw material comes last. A component
 * renders this array rather than hard-coding the sequence, so the order is one
 * assertion rather than a code review.
 */
export const HOME_SECTIONS = [
  "composer",
  "quick-prompts",
  "recent-playbooks",
  "recent-exported-analyses",
] as const;

export type HomeSection = (typeof HOME_SECTIONS)[number];

export function homeOrder(): HomeSection[] {
  return [...HOME_SECTIONS];
}

/**
 * The starters §3 lists. They populate the composer and are edited before being
 * sent — clicking one must never spend a generation, because the user has not
 * yet said what to work on.
 */
export const QUICK_PROMPTS: { id: string; label: string; prompt: string }[] = [
  {
    id: "ifrs9-committee",
    label: "Create an IFRS 9 committee report",
    prompt:
      "Create an IFRS 9 committee report for the current quarter from the " +
      "attached results and analyses.",
  },
  {
    id: "ifrs9-corporate-pack",
    label: "Create a corporate IFRS 9 committee pack",
    prompt:
      "Create a corporate IFRS 9 committee pack covering ECL movement, stage " +
      "migration and concentration.",
  },
  {
    id: "application-development",
    label: "Create an application scorecard development report",
    prompt:
      "Create an application scorecard model development report from the " +
      "attached development evidence.",
  },
  {
    id: "behavioural-validation",
    label: "Create a behavioural scorecard validation report",
    prompt:
      "Using only the selected analyses, create a detailed behavioural " +
      "scorecard validation report. Identify any evidence that is missing " +
      "rather than assuming it.",
  },
  {
    id: "update-previous",
    label: "Update a previous committee report",
    prompt:
      "Update the attached previous-period committee report using the new " +
      "results. Keep the prior-period comparison.",
  },
  {
    id: "methodology-coverage",
    label: "Check methodology coverage",
    prompt:
      "Compare the attached methodology against the attached report and give " +
      "me a coverage matrix. Do not edit the report.",
  },
  {
    id: "sharpen-summary",
    label: "Sharpen an executive summary",
    prompt:
      "Sharpen the executive summary: more concise and more direct, in a " +
      "formal committee register. Preserve every figure and conclusion.",
  },
  {
    id: "to-presentation",
    label: "Convert a report to a presentation",
    prompt:
      "Turn the latest version of this report into a committee presentation " +
      "with editable text and tables.",
  },
];

/** A manageable subset for the home screen, without crowding it. */
export function homePrompts(limit = 4): typeof QUICK_PROMPTS {
  return QUICK_PROMPTS.slice(0, limit);
}

// -------------------------------------------------------------------- labels

export const MODULE_LABEL: Record<string, string> = {
  cockpit: "Cockpit",
  early_warning: "Early Warning",
  what_if: "What If",
  scorecard_validation: "Scorecard Validation",
  lenses: "Lenses",
};

export function moduleLabel(module: string): string {
  return MODULE_LABEL[module] ?? module;
}

export const ROLE_LABEL: Record<string, string> = {
  previous_report: "Previous report",
  template: "Template",
  methodology: "Methodology",
  results: "Results",
  supporting: "Supporting document",
};

export function roleLabel(role: string): string {
  return ROLE_LABEL[role] ?? role;
}

export function formatBytes(bytes: number): string {
  if (!bytes) return "0 KB";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/**
 * What a source's state means, in a sentence.
 *
 * `partial` is the one that matters. A file that parsed with a hidden sheet
 * skipped is not "ready" and is not "failed", and a screen that shows it as
 * either is lying about what the answer will be based on.
 */
export function sourceStatus(source: PbSource): {
  tone: "positive" | "warning" | "negative" | "default";
  label: string;
  detail: string;
} {
  const skipped = source.manifest?.skipped ?? [];
  const warnings = source.manifest?.warnings ?? [];
  switch (source.status) {
    case "parsed":
      return { tone: "positive", label: "Read", detail: (source.manifest?.read ?? []).join("; ") };
    case "partial":
      return {
        tone: "warning",
        label: "Partly read",
        detail:
          skipped.length > 0
            ? `${skipped.length} part(s) not read: ${skipped
                .map((s) => s.what)
                .slice(0, 3)
                .join(", ")}`
            : warnings[0] ?? "Some content was not read.",
      };
    case "failed":
      return {
        tone: "negative",
        label: "Could not be read",
        detail: source.failure_reason,
      };
    case "parsing":
      return { tone: "default", label: "Reading…", detail: "" };
    default:
      return { tone: "default", label: "Uploaded", detail: "" };
  }
}

/** True when anything attached was not fully read, so an answer must say so. */
export function hasEvidenceGaps(sources: PbSource[]): boolean {
  return sources.some(
    (s) => s.status === "failed" || s.status === "partial",
  );
}

// -------------------------------------------------------------- next actions

export interface NextStep {
  id: string;
  label: string;
  prompt: string;
}

/**
 * Follow-up suggestions built from what the workspace actually contains.
 *
 * §12's requirement is that these be state-aware: do not offer to convert a
 * report that does not exist, do not offer to build a deck that is already
 * there at this revision, and do not offer to inspect sources that were never
 * attached. Each rule below is one of those.
 */
export function nextSteps(workspace: {
  artifacts: PbArtifact[];
  sources: PbSource[];
}): NextStep[] {
  const steps: NextStep[] = [];
  const reports = workspace.artifacts.filter((a) => a.kind === "report");
  const decks = workspace.artifacts.filter((a) => a.kind === "presentation");
  const latestReport = reports[reports.length - 1];

  if (!latestReport) {
    // Nothing has been written, so every suggestion about "the report" would
    // point at nothing.
    if (workspace.sources.length > 0) {
      steps.push({
        id: "draft",
        label: "Draft the report from these sources",
        prompt: "Draft the report from the attached sources.",
      });
    }
    return steps;
  }

  steps.push({
    id: "sharpen",
    label: "Sharpen the executive summary",
    prompt:
      "Sharpen the executive summary: more concise and more direct, in a " +
      "formal committee register. Preserve every figure, caveat and " +
      "conclusion, and change nothing else.",
  });

  const deckIsCurrent = decks.some(
    (d) => d.derived_from_version_id === latestReport.current_version_id,
  );
  if (!deckIsCurrent) {
    steps.push({
      id: "present",
      label: decks.length
        ? "Update the presentation to this version"
        : "Turn this into a presentation",
      prompt:
        "Turn the latest version of this report into a committee " +
        "presentation with editable text and tables.",
    });
  }

  if (hasEvidenceGaps(workspace.sources)) {
    steps.push({
      id: "gaps",
      label: "Review what could not be read",
      prompt:
        "Which of the attached sources were not fully read, and what does " +
        "that mean for the conclusions in this report?",
    });
  }

  steps.push({
    id: "attach",
    label: "Attach another exported analysis",
    prompt: "",
  });
  return steps;
}

// ------------------------------------------------------------- provider state

/**
 * What the composer should say about generation.
 *
 * With no provider configured the history and its files stay browseable and the
 * composer says configuration is required — §13's rule. It never offers a
 * button that will fail.
 */
export function composerState(caps: PbCapabilities | null): {
  canGenerate: boolean;
  note: string;
} {
  if (!caps) return { canGenerate: false, note: "" };
  if (caps.provider.configured) return { canGenerate: true, note: "" };
  return { canGenerate: false, note: caps.provider.reason };
}

// ----------------------------------------------------------------- selection

/**
 * Keep already-selected entries visible while filtering.
 *
 * Lifted from `matching()` in components/collaboration/share.tsx, where it
 * solves the same problem: a picker that hides what you have already chosen the
 * moment you type looks as though it has forgotten it.
 */
export function matching<T extends { revision_id: number; title: string; insight?: string }>(
  entries: T[],
  filter: string,
  selected: number[],
): T[] {
  const needle = filter.trim().toLowerCase();
  if (!needle) return entries;
  return entries.filter(
    (e) =>
      selected.includes(e.revision_id) ||
      e.title.toLowerCase().includes(needle) ||
      (e.insight ?? "").toLowerCase().includes(needle),
  );
}

/** A one-line summary of a preview, for the selected-items tray. */
export function previewSummary(preview: PbAnalysisPreview): string {
  const bits = [moduleLabel(preview.source_module)];
  if (preview.reporting_period) bits.push(preview.reporting_period);
  if (preview.tables.length) bits.push(`${preview.tables.length} table(s)`);
  return bits.join(" · ");
}

/** Which artifact version is current, for the file pane. */
export function currentVersion(artifact: PbArtifact) {
  return (
    artifact.versions.find((v) => v.id === artifact.current_version_id) ??
    artifact.versions[artifact.versions.length - 1] ??
    null
  );
}

/** Whether a thread is a seeded demonstration rather than live work. */
export function isSeeded(workspace: PbWorkspace): boolean {
  return workspace.demo || workspace.messages.some((m) => m.origin === "seed_fixture");
}
