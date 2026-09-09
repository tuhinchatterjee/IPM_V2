/**
 * Turning what is on a screen into a Playbook export.
 *
 * One builder per source module, all producing the shared payload the backend
 * validates. Keeping them here rather than inside each page means the rule
 * about what counts as a completed analysis is written once, and can be tested
 * without rendering anything.
 *
 * The rule §5 states and this file enforces on the way out: a greeting is not
 * an analysis, and neither is an answer that stopped to ask a question, failed,
 * or matched nothing. `exportability()` says whether the control should be
 * offered at all and why not — the backend refuses these too, but a button that
 * is going to fail should say so before it is pressed rather than after.
 */

import type {
  InvestigationResponse,
  PbExportRequest,
  PbTable,
  Row,
} from "./api";

export interface Exportability {
  can: boolean;
  reason: string;
}

/** Whether an answer is a completed analysis worth exporting. */
export function exportability(run: InvestigationResponse | null): Exportability {
  if (!run) return { can: false, reason: "There is no answer to export yet." };
  if (run.clarification) {
    return {
      can: false,
      reason: "This answer asked a question rather than reaching a result.",
    };
  }
  if (run.unmatched) {
    return { can: false, reason: "This question matched no analysis." };
  }
  if (run.status && run.status !== "succeeded") {
    return {
      can: false,
      reason: `This answer is ${run.status.replace(/_/g, " ")}, so it is not a completed analysis.`,
    };
  }
  const hasResult = run.steps.some((s) => (s.result?.rows?.length ?? 0) > 0);
  const narrative = run.narrative.direct_answer || run.narrative.summary || "";
  if (!hasResult && narrative.trim().length < 80) {
    return {
      can: false,
      reason: "There is no result table and no substantive narrative to carry.",
    };
  }
  return { can: true, reason: "" };
}

function tablesFrom(run: InvestigationResponse): PbTable[] {
  const tables: PbTable[] = [];
  run.steps.forEach((step, i) => {
    const rows = step.result?.rows ?? [];
    if (!rows.length) return;
    const columns = Object.keys(rows[0] ?? {});
    if (!columns.length) return;
    tables.push({
      id: `${step.analysis_id || "step"}_${i}`,
      title: step.title || step.analysis_id,
      columns,
      rows: rows.map((row) => columns.map((c) => (row as Record<string, unknown>)[c])),
      units: step.result?.units ?? {},
      precision: {},
    });
  });
  return tables;
}

function narrativeFrom(run: InvestigationResponse): string {
  const n = run.narrative;
  const parts = [
    n.direct_answer || n.summary,
    ...(n.interpretation ? [n.interpretation] : []),
    ...(n.interpretation_points ?? []),
    ...n.findings.map((f) =>
      typeof f === "string" ? f : ((f as { text?: string }).text ?? ""),
    ),
  ];
  return parts.filter(Boolean).join("\n\n");
}

/**
 * Cockpit and every other surface that renders a governed answer.
 *
 * The provenance carried is the analysis run and its trace, which is what makes
 * a figure in a Playbook report traceable back through CreditProbe's own
 * lineage rather than only to "an analysis, once".
 */
export function fromAnswer(
  run: InvestigationResponse,
  options: { module?: string; threadId?: number; reportFamily?: string } = {},
): PbExportRequest {
  const primary = run.steps.find((s) => s.role === "primary") ?? run.steps[0];
  const period = primary?.period ?? "";
  return {
    source_module: options.module ?? "cockpit",
    title: run.question.slice(0, 200) || primary?.title || "Analysis",
    question: run.question,
    narrative: narrativeFrom(run),
    tables: tablesFrom(run),
    scope: {
      reporting_period: period,
      population: run.narrative.scope ?? "",
      filters: primary?.filters ?? {},
      analysis_id: primary?.analysis_id ?? "",
      analysis_version: primary?.analysis_version ?? "",
    },
    caveats: run.narrative.caveats ?? [],
    limitations: run.notes ?? [],
    source_ref: {
      run_id: run.analysis_run_id,
      thread_id: options.threadId ?? null,
      link: run.analysis_run_id ? `/trace/${run.analysis_run_id}` : "",
    },
    source_revision: String(run.version ?? ""),
    reporting_period: period,
    report_family: options.reportFamily ?? "",
    insight: run.narrative.direct_answer || run.narrative.summary || "",
  };
}

/**
 * One Lens panel.
 *
 * A lens renders panels rather than answers, so this takes the panel's own
 * shape rather than an investigation. The lens name and revision travel with
 * it, because "obligor concentration" means something different on the CRO lens
 * at revision 4 than it did at revision 1.
 */
export function fromLensPanel(
  panel: {
    analysis_id: string;
    title?: string;
    analysis_version?: string;
    analysis_run_id?: number | null;
    filters?: Record<string, unknown>;
    period?: string | null;
    note?: string;
    result?: { rows?: Row[]; units?: Record<string, string> } | null;
  },
  lens: { id: number | string; name: string; revision?: number },
): PbExportRequest {
  const rows = panel.result?.rows ?? [];
  const columns = rows.length ? Object.keys(rows[0] ?? {}) : [];
  const title = panel.title || panel.analysis_id;
  const narrative =
    panel.note ||
    `${title} on the ${lens.name} lens, over ${
      rows.length
    } row(s) of governed results.`;
  return {
    source_module: "lenses",
    title: `${lens.name}: ${title}`.slice(0, 200),
    question: `What does ${title} show on the ${lens.name} lens?`,
    narrative,
    tables: columns.length
      ? [
          {
            id: panel.analysis_id,
            title,
            columns,
            rows: rows.map((r) =>
              columns.map((c) => (r as Record<string, unknown>)[c]),
            ),
            units: panel.result?.units ?? {},
            precision: {},
          },
        ]
      : [],
    scope: {
      reporting_period: panel.period ?? "",
      filters: panel.filters ?? {},
      analysis_id: panel.analysis_id,
      analysis_version: panel.analysis_version ?? "",
      lens: lens.name,
    },
    source_ref: {
      lens_id: lens.id,
      run_id: panel.analysis_run_id ?? null,
      link: `/lenses/${lens.id}`,
    },
    source_revision: String(lens.revision ?? ""),
    reporting_period: panel.period ?? "",
    report_family: "lens_review",
    insight: narrative.split(/(?<=[.!?])\s+/)[0] ?? "",
  };
}

/**
 * One borrower's credit story, as Early Warning tells it.
 *
 * The prototype caveat travels by default and is not optional. `docs/
 * PRODUCT_SPEC.md` §10b is explicit that the Forward Risk Signal is a prototype
 * and that the product never calls it anything else — a figure of it lifted
 * into a committee paper without that sentence would be the one place the
 * product broke its own rule.
 */
export function fromCreditStory(story: {
  borrower_id: string;
  period: string;
  sections: { heading: string; body: string[]; empty: boolean }[];
  families: { label: string; severity: string; reading: string; quiet: boolean }[];
}, borrowerName?: string): PbExportRequest {
  const name = borrowerName || story.borrower_id;
  const narrative = story.sections
    .filter((s) => !s.empty && s.body.length)
    .map((s) => `${s.heading}\n${s.body.join(" ")}`)
    .join("\n\n");
  const rows = story.families
    .filter((f) => !f.quiet)
    .map((f) => [f.label, f.severity, f.reading]);
  return {
    source_module: "early_warning",
    title: `Early Warning: ${name}`.slice(0, 200),
    question: `What is the forward risk signal telling us about ${name}?`,
    narrative,
    tables: rows.length
      ? [
          {
            id: "signal_families",
            title: "Signal families that fired",
            columns: ["Family", "Severity", "Reading"],
            rows,
            units: {},
            precision: {},
          },
        ]
      : [],
    scope: { reporting_period: story.period, borrower: story.borrower_id },
    caveats: [
      "The Forward Risk Signal is a prototype fitted on synthetic data. It is "
      + "not a validated model and must not be described as one.",
    ],
    source_ref: {
      borrower_id: story.borrower_id,
      link: `/early-warning?borrower=${encodeURIComponent(story.borrower_id)}`,
    },
    reporting_period: story.period,
    report_family: "early_warning_review",
    insight: narrative.split(/(?<=[.!?])\s+/)[0] ?? "",
  };
}

/** One borrower's Early Warning reading, from explicit parts. */
export function fromEarlyWarning(input: {
  borrowerId: string;
  borrowerName: string;
  period: string;
  narrative: string;
  columns: string[];
  rows: unknown[][];
  caveats?: string[];
  modelVersion?: string;
}): PbExportRequest {
  return {
    source_module: "early_warning",
    title: `Early Warning: ${input.borrowerName}`.slice(0, 200),
    question: `What is the forward risk signal for ${input.borrowerName}?`,
    narrative: input.narrative,
    tables: input.rows.length
      ? [
          {
            id: "signal_decomposition",
            title: "Signal decomposition",
            columns: input.columns,
            rows: input.rows,
            units: {},
            precision: {},
          },
        ]
      : [],
    scope: { reporting_period: input.period, borrower: input.borrowerId,
      model_version: input.modelVersion ?? "" },
    caveats: input.caveats ?? [
      "The Forward Risk Signal is a prototype fitted on synthetic data and is not a validated model.",
    ],
    source_ref: { borrower_id: input.borrowerId,
      link: `/early-warning?borrower=${encodeURIComponent(input.borrowerId)}` },
    reporting_period: input.period,
    report_family: "early_warning_review",
    insight: input.narrative.split(/(?<=[.!?])\s+/)[0] ?? "",
  };
}

/**
 * A generated scorecard validation report.
 *
 * The report already carries what an export needs — its opinion, its coverage,
 * its evidence items each bound to a validation run — so the snapshot is built
 * from the report rather than from the screen. `coverage` travels because a
 * validation report with two topics unaddressed is a different piece of
 * evidence from one with none, and a committee paper built on it should be able
 * to say which it had.
 */
export function fromScorecardReport(report: {
  report_id: string;
  model_kind: string;
  model_name: string;
  model_version: string;
  period: string;
  title: string;
  opinion: string;
  coverage: { complete: boolean; topics: number; missing: string[] };
  evidence: { section: string; label: string; metric: string;
    value_text: string }[];
  content_hash: string;
}): PbExportRequest {
  const narrative =
    `${report.title} for the ${report.model_name} ${report.model_kind} ` +
    `scorecard, period ${report.period}. The validation opinion is ` +
    `${report.opinion}. ` +
    (report.coverage.complete
      ? `All ${report.coverage.topics} required topics are addressed.`
      : `${report.coverage.missing.length} of ${report.coverage.topics} ` +
        `required topics are not addressed: ` +
        `${report.coverage.missing.join(", ")}.`);
  const rows = report.evidence.map((e) => [
    e.section, e.label, e.metric, e.value_text,
  ]);
  return {
    source_module: "scorecard_validation",
    title: `${report.title} — ${report.model_name}`.slice(0, 200),
    question:
      `What did ${report.period} validation find for the ` +
      `${report.model_name} scorecard?`,
    narrative,
    tables: rows.length
      ? [
          {
            id: "validation_evidence",
            title: "Validation evidence",
            columns: ["Section", "Label", "Metric", "Value"],
            rows,
            units: {},
            precision: {},
          },
        ]
      : [],
    scope: {
      reporting_period: report.period,
      model_kind: report.model_kind,
      model_name: report.model_name,
      model_version: report.model_version,
    },
    limitations: report.coverage.complete
      ? []
      : report.coverage.missing.map(
          (topic) => `${topic} is not addressed in this validation report.`,
        ),
    caveats: [
      "CreditProbe does not provide regulatory certification. This is a "
      + "validation result, not a compliance opinion.",
    ],
    source_ref: { report_id: report.report_id, link: "/scorecard-validation" },
    source_revision: report.content_hash.slice(0, 16),
    reporting_period: report.period,
    report_family: "scorecard_validation_report",
    insight:
      `${report.opinion} for ${report.model_name} at ${report.period}.`,
  };
}

/** A scorecard validation result, from explicit parts. */
export function fromScorecardValidation(input: {
  reportId: string;
  modelKind: string;
  month: string;
  title: string;
  narrative: string;
  columns: string[];
  rows: unknown[][];
  limitations?: string[];
  modelVersion?: string;
}): PbExportRequest {
  return {
    source_module: "scorecard_validation",
    title: input.title.slice(0, 200),
    question: `What did ${input.month} validation find for the ${input.modelKind} scorecard?`,
    narrative: input.narrative,
    tables: input.rows.length
      ? [
          {
            id: "validation_results",
            title: input.title,
            columns: input.columns,
            rows: input.rows,
            units: {},
            precision: {},
          },
        ]
      : [],
    scope: {
      reporting_period: input.month,
      model_kind: input.modelKind,
      model_version: input.modelVersion ?? "",
    },
    limitations: input.limitations ?? [],
    source_ref: { report_id: input.reportId,
      link: "/scorecard-validation" },
    reporting_period: input.month,
    report_family: "scorecard_validation_report",
    insight: input.narrative.split(/(?<=[.!?])\s+/)[0] ?? "",
  };
}
