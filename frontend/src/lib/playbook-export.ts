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

/**
 * A completed What-If result, as a Playbook export.
 *
 * The one thing this builder is careful about: a What-If result is a
 * COMPARISON, and an export carrying only the stressed figure would be
 * indistinguishable in a committee pack from a reported one. So every amount
 * goes out as a labelled pair — baseline beside scenario beside the movement —
 * the narrative says which is which in words, and the limitation saying it is
 * conditional is not optional and not removable.
 *
 * The scenario definition travels with it for the same reason. "ECL rises to
 * SAR 1.2bn" without what was assumed is a figure nobody can check, so the
 * shocks, the population they were applied to, the staging criteria, the ECL
 * methodology and the model version are all part of the claim rather than
 * decoration around it.
 */
export function fromWhatIfResult(input: {
  result: {
    state?: { scenario?: string; methodology?: string | null;
      // `interpreted` is the phrase the product showed the user for this
      // step, which is what a pack should carry — not the raw instruction
      // they typed and not the machine `kind`.
      steps?: { label?: string; kind?: string; interpreted?: string;
        enabled?: boolean }[] };
    context?: {
      period?: string; currency?: string; scenario?: string;
      population?: string; population_count?: number; dataset?: string;
      grain?: string; staging_version?: string; staging_note?: string;
    };
    summary?: Record<string, number | string>;
    steps?: { step: string; detail: string; affected: number }[];
    // The attribution BRIDGE: which driver moved the ECL and by how much,
    // plus the part the drivers do not explain. Carried whole, because a
    // bridge missing its residual does not add up and a pack reader will try.
    attribution?: {
      available?: boolean; why?: string; method?: string; currency?: string;
      drivers?: { key: string; label: string; effect: number;
        share_pct: number; borrowers_moved: number }[];
      model_adjustment?: { label: string; effect: number; note?: string;
        material?: boolean };
    } | null;
    by_rating?: Record<string, unknown>[];
    rating_movement?: { moved: number; note: string } | null;
    stage_movement?: { moved: number; deteriorated: number;
      cured: number } | null;
    interpretation?: { headline?: string; statement?: string;
      paragraphs?: string[]; findings?: string[];
      written_by?: string; verified?: boolean } | null;
    ml?: { model_version?: string } | null;
    warnings?: string[];
    notes?: string[];
    run_id?: string;
    run_version?: string;
  };
  excelUrl?: string;
}): PbExportRequest {
  const r = input.result;
  const s = r.summary ?? {};
  const context = r.context ?? {};
  const currency = String(context.currency || s.currency || "SAR");
  const period = String(context.period || s.period || "");
  const scenario = String(context.scenario || s.scenario
    || r.state?.scenario || "Scenario");
  const methodology = r.state?.methodology === "ml"
    ? "ML model (XGBoost)" : "Delta model";

  const num = (key: string): number => {
    const value = s[key];
    return typeof value === "number" ? value : Number(value ?? 0);
  };
  const money = (n: number) =>
    `${currency} ${n.toLocaleString(undefined, { maximumFractionDigits: 2 })}`;

  const baseline = num("baseline_ecl");
  const stressed = num("stressed_ecl");
  const delta = num("incremental_ecl");
  const deltaPct = num("incremental_ecl_pct");

  const shocks = (r.state?.steps ?? [])
    .filter((x) => x.enabled !== false)
    .map((x) => x.interpreted || x.label || x.kind || "")
    .filter(Boolean);

  const reading = r.interpretation;
  const narrative = [
    `${scenario} applied to ${context.population || "the whole book"} at `
    + `${period}, over `
    + `${Number(context.population_count ?? num("borrowers")).toLocaleString()}`
    + ` borrower(s), measured with the ${methodology}.`,
    `ECL moves from ${money(baseline)} baseline to ${money(stressed)} under `
    + `the scenario — ${delta >= 0 ? "an increase" : "a decrease"} of `
    + `${money(Math.abs(delta))}, ${deltaPct.toFixed(2)}%. Coverage moves `
    + `from ${num("baseline_coverage_pct").toFixed(2)}% to `
    + `${num("stressed_coverage_pct").toFixed(2)}%.`,
    `${num("stage_2_migrations").toLocaleString()} borrower(s) migrate into `
    + `Stage 2 and ${num("stage_3_migrations").toLocaleString()} into Stage 3; `
    + `${num("downgraded").toLocaleString()} are downgraded.`,
    shocks.length ? `Shocks applied: ${shocks.join("; ")}.` : "",
    reading?.headline ?? "",
    ...(reading?.paragraphs ?? []),
    reading?.statement ?? "",
    // The sentence that stops a scenario being read as a reported figure.
    "This is a What-If measurement against a stated scenario. The baseline is "
    + "the reported book; every other figure here is conditional on the "
    + "assumptions above and is not a reported IFRS 9 outcome.",
  ].filter(Boolean).join("\n\n");

  const tables: PbTable[] = [
    {
      id: "whatif_movement",
      title: "Baseline against scenario",
      columns: ["Measure", "Baseline", "Scenario", "Change"],
      rows: [
        ["ECL", baseline, stressed, delta],
        ["EAD", num("baseline_ead"), num("stressed_ead"),
          num("stressed_ead") - num("baseline_ead")],
        ["Coverage %", num("baseline_coverage_pct"),
          num("stressed_coverage_pct"),
          num("stressed_coverage_pct") - num("baseline_coverage_pct")],
      ],
      units: { Baseline: currency, Scenario: currency, Change: currency },
      precision: {},
    },
    {
      id: "whatif_impacts",
      title: "Stage, rating and exposure impacts",
      columns: ["Impact", "Borrowers"],
      rows: [
        ["Migrated to Stage 2", num("stage_2_migrations")],
        ["Migrated to Stage 3", num("stage_3_migrations")],
        ["Downgraded", num("downgraded")],
        ["Higher ECL", num("borrowers_with_higher_ecl")],
        ["Collateral shortfalls", num("collateral_shortfalls")],
        ["Covenant breaches", num("covenant_breaches")],
      ],
      units: {},
      precision: {},
    },
  ];

  const drivers = r.attribution?.drivers ?? [];
  if (r.attribution?.available && drivers.length) {
    const rows: unknown[][] = drivers.map((d) =>
      [d.label, d.effect, d.share_pct, d.borrowers_moved]);
    // The residual belongs in the same table as the drivers or the bridge
    // does not reconcile on the page it is read on.
    const residual = r.attribution.model_adjustment;
    if (residual) {
      rows.push([residual.label, residual.effect, null, null]);
    }
    tables.push({
      id: "whatif_attribution",
      title: "What the movement is made of",
      columns: ["Driver", "Effect", "Share %", "Borrowers moved"],
      rows,
      units: { Effect: r.attribution.currency || currency },
      precision: {},
    });
  }
  if (r.steps?.length) {
    tables.push({
      id: "whatif_steps",
      title: "How the scenario was applied",
      columns: ["Step", "Detail", "Affected"],
      rows: r.steps.map((x) => [x.step, x.detail, x.affected]),
      units: {},
      precision: {},
    });
  }

  return {
    source_module: "what_if",
    title: `What-If: ${scenario} — ${period}`.slice(0, 200),
    question: `What happens to ECL under ${scenario} at ${period}?`,
    narrative,
    tables,
    scope: {
      reporting_period: period,
      scenario,
      shocks,
      population: context.population ?? "",
      population_count: Number(context.population_count ?? num("borrowers")),
      dataset: context.dataset ?? "",
      grain: context.grain ?? "",
      staging_version: context.staging_version ?? "",
      methodology,
      model_version: r.ml?.model_version ?? "",
      run_version: r.run_version ?? "",
      currency,
      baseline_ecl: baseline,
      scenario_ecl: stressed,
      incremental_ecl: delta,
      incremental_ecl_pct: deltaPct,
      stage_2_migrations: num("stage_2_migrations"),
      stage_3_migrations: num("stage_3_migrations"),
      downgraded: num("downgraded"),
      interpretation_written_by: reading?.written_by ?? "",
      interpretation_verified: Boolean(reading?.verified),
    },
    limitations: [
      "A What-If result is conditional on its scenario. It is not a reported "
      + "IFRS 9 outcome and must not be presented as one.",
      ...(context.staging_note ? [String(context.staging_note)] : []),
      ...(r.warnings ?? []),
      ...(r.notes ?? []),
    ],
    source_ref: {
      run_id: r.run_id ?? "",
      run_version: r.run_version ?? "",
      scenario,
      methodology,
      model_version: r.ml?.model_version ?? "",
      link: "/what-if/thread",
      ...(input.excelUrl ? { detailed_excel: input.excelUrl } : {}),
    },
    reporting_period: period,
    report_family: "what_if_scenario",
    insight:
      `${scenario}: ECL ${delta >= 0 ? "up" : "down"} `
      + `${money(Math.abs(delta))} (${deltaPct.toFixed(2)}%) at ${period}.`,
  };
}
