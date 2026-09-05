"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type {
  ScorecardAssessment,
  ScorecardDashboard,
  ScorecardDiagnosis,
  ScorecardDrift,
  ScorecardEquation,
  ScorecardModels,
  ScorecardMonths,
  ScorecardOdrTrend,
  ScorecardOverview,
  ScorecardPolicy,
  ScorecardReport,
  ScorecardReportLibrary,
  ScorecardType,
  ScorecardVariables,
} from "@/lib/api";
import {
  equationCoefficient,
  tableCoefficient,
} from "@/lib/scorecard-format";
import { cn } from "@/lib/utils";

/**
 * Retail Scorecard Validation. §17-§50.
 *
 * A model-risk workspace rather than a BI page. The distinction shows up in
 * what the screen refuses to do more than in what it draws.
 *
 * Three things it never does
 * ---------------------------
 * **It never shows a metric as green because nothing checked it.** §50: a
 * metric with no approved limit gets NO APPROVED LIMIT, in its own colour,
 * distinct again from NOT MEASURED. Those are two different absences and one
 * grey chip for both would conflate them.
 *
 * **It never shows a predictive number for an immature month.** §7. The
 * backend returns a refusal naming the month the window closes, and the
 * panel renders that sentence rather than a zero.
 *
 * **It never quotes a validation statistic at two decimals.** AUC, Gini, KS,
 * PSI and CSI carry four. The display contract governs money and rates a
 * committee reads as amounts; a discrimination trend is a question about the
 * third decimal, and 0.7179 against 0.7104 is the finding that two decimals
 * would erase. Percentages and populations on this screen follow the
 * contract as everywhere else.
 */

const TABS = [
  ["cockpit", "Cockpit", "The model, the month, and whether its outcomes have matured."],
  ["dashboard", "Dashboard", "Every validation section for the selected model and month."],
  ["discrimination", "Discrimination", "AUC, Gini and KS, with gains and lift by decile."],
  ["calibration", "Calibration", "Predicted PD against observed default rate, by score band."],
  ["stability", "Stability", "Score PSI and per-variable CSI against the development population."],
  ["variables", "Variables", "Univariate power and Information Value for each active variable."],
  ["models", "Models", "The registry: equations, coefficients and the default definition."],
  ["diagnostics", "Diagnostics", "Why discrimination fell, and what changed when accuracy did."],
  ["trends", "Trends", "Observed default rate and score stability over time."],
  ["findings", "Findings", "What breached a limit, with the evidence that raised it."],
  ["governance", "Governance", "The validation policy and where each limit came from."],
  ["data", "Data", "Row counts, missingness, key uniqueness and sample sufficiency."],
  ["reports", "Reports", "Generate and download the CBUAE-aligned validation report and its evidence workbook."],
] as const;

type TabId = (typeof TABS)[number][0];

const MODELS = ["INCUMBENT", "CHALLENGER", "RECALIBRATED"] as const;

/** §81's five statuses, and the colour each is allowed. */
const STATUS_STYLE: Record<string, string> = {
  PASS: "bg-positive/12 text-positive",
  WATCH: "bg-caution/15 text-caution",
  BREACH: "bg-negative/12 text-negative",
  // Deliberately not the pass colour, and deliberately not the same as
  // NOT MEASURED — §50's whole point is that these are different.
  "NO APPROVED LIMIT": "bg-muted text-muted-foreground ring-1 ring-border",
  "NOT MEASURED": "bg-transparent text-muted-foreground ring-1 ring-dashed ring-border",
};

const OPINION_STYLE: Record<string, string> = {
  SATISFACTORY: "text-positive",
  "SATISFACTORY WITH OBSERVATIONS": "text-foreground",
  "REQUIRES REMEDIATION": "text-caution",
  "MATERIAL DEFICIENCIES": "text-negative",
  "INCOMPLETE VALIDATION": "text-muted-foreground",
};

/** Validation statistics keep four decimals. See the file comment. */
function stat(value: number | null | undefined, places = 4): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toFixed(places);
}

/** Percentages and money follow the two-decimal display contract. */
function percent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

function count(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString();
}

export default function ScorecardValidationPage() {
  const [tab, setTab] = React.useState<TabId>("cockpit");
  const [type, setType] = React.useState<ScorecardType>("APPLICATION");
  const [model, setModel] = React.useState<string>("INCUMBENT");
  const [month, setMonth] = React.useState<string>("");
  const [overview, setOverview] = React.useState<ScorecardOverview | null>(null);
  const [months, setMonths] = React.useState<ScorecardMonths | null>(null);

  React.useEffect(() => {
    let live = true;
    api
      .scorecardOverview()
      .then((found) => live && setOverview(found))
      .catch(() => live && setOverview(null));
    return () => {
      live = false;
    };
  }, []);

  React.useEffect(() => {
    let live = true;
    api
      .scorecardMonths(type)
      .then((found) => live && setMonths(found))
      .catch(() => live && setMonths(null));
    return () => {
      live = false;
    };
  }, [type]);

  // Switching scorecard type clears the month here rather than in the
  // effect above. The two scorecards do not share a month list, so a month
  // chosen on one is meaningless on the other — and resetting it inside the
  // effect is a state write during render that React rightly objects to.
  const chooseType = React.useCallback((next: ScorecardType) => {
    setType(next);
    setMonth("");
  }, []);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="Model risk"
        title="Retail Scorecard Validation"
        description={
          "Governed monitoring and validation of the retail application and " +
          "behavioural scorecards: discrimination, calibration, stability, " +
          "variable diagnostics and implementation, against approved limits."
        }
      />

      <Controls
        type={type}
        setType={chooseType}
        model={model}
        setModel={setModel}
        month={month}
        setMonth={setMonth}
        months={months}
      />

      <nav className="flex flex-wrap gap-1 border-b border-border/60 pb-1">
        {TABS.map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            aria-current={tab === id ? "page" : undefined}
            className={cn(
              "rounded px-2 py-1 text-xs transition-colors",
              "focus-visible:outline focus-visible:outline-2",
              "focus-visible:outline-offset-2",
              tab === id
                ? "bg-muted font-medium text-foreground"
                : "text-muted-foreground hover:bg-muted/60",
            )}
          >
            {label}
          </button>
        ))}
      </nav>

      <p className="text-xs text-muted-foreground">
        {TABS.find(([id]) => id === tab)?.[2]}
      </p>

      <Panel
        key={`${tab}:${type}:${model}:${month}`}
        tab={tab}
        type={type}
        model={model}
        month={month}
      />

      {overview && (
        <p className="text-[11px] text-muted-foreground">
          {overview.not_client_data}
        </p>
      )}
    </div>
  );
}

// ------------------------------------------------------------------- §18/§44

function Controls({
  type,
  setType,
  model,
  setModel,
  month,
  setMonth,
  months,
}: {
  type: ScorecardType;
  setType: (value: ScorecardType) => void;
  model: string;
  setModel: (value: string) => void;
  month: string;
  setMonth: (value: string) => void;
  months: ScorecardMonths | null;
}) {
  const selected =
    months?.months.find((one) => one.month === (month || months.latest_matured_performance_month));
  return (
    <Card className="flex flex-wrap items-end gap-4 p-4">
      <Field label="Scorecard type">
        <select
          value={type}
          onChange={(e) => setType(e.target.value as ScorecardType)}
          className="rounded border border-border bg-transparent px-1.5 py-1 text-xs"
        >
          <option value="APPLICATION">Application</option>
          <option value="BEHAVIORAL">Behavioural</option>
        </select>
      </Field>

      <Field label="Model">
        <select
          value={model}
          onChange={(e) => setModel(e.target.value)}
          className="rounded border border-border bg-transparent px-1.5 py-1 text-xs"
        >
          {MODELS.map((one) => (
            <option key={one} value={one}>
              {one.charAt(0) + one.slice(1).toLowerCase()}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Validation month">
        <select
          value={month}
          onChange={(e) => setMonth(e.target.value)}
          className="rounded border border-border bg-transparent px-1.5 py-1 text-xs"
        >
          <option value="">
            Latest matured
            {months?.latest_matured_performance_month
              ? ` (${months.latest_matured_performance_month})`
              : ""}
          </option>
          {months?.months.map((one) => (
            <option key={one.month} value={one.month}>
              {one.month}
              {one.matured ? "" : " — stability only"}
            </option>
          ))}
        </select>
      </Field>

      {months && (
        <div className="ml-auto text-right text-[11px] text-muted-foreground">
          <div>
            Latest data month{" "}
            <span className="text-foreground">{months.latest_data_month}</span>
          </div>
          <div>
            Latest matured performance month{" "}
            <span className="text-foreground">
              {months.latest_matured_performance_month || "none"}
            </span>
          </div>
          <div>
            Performance horizon {months.performance_horizon_months} months
            {selected && !selected.matured && (
              <span className="ml-1 text-caution">
                — this month has no outcome until{" "}
                {selected.outcome_available_from}
              </span>
            )}
          </div>
        </div>
      )}
    </Card>
  );
}

function Field({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
      {label}
      {children}
    </label>
  );
}

// ------------------------------------------------------------------ panels

function Panel({
  tab,
  type,
  model,
  month,
}: {
  tab: TabId;
  type: ScorecardType;
  model: string;
  month: string;
}) {
  const [state, setState] = React.useState<{
    dashboard?: ScorecardDashboard;
    models?: ScorecardModels;
    variables?: ScorecardVariables;
    policy?: ScorecardPolicy;
    odr?: ScorecardOdrTrend;
    drift?: ScorecardDrift;
    lowKs?: ScorecardDiagnosis;
    accuracy?: ScorecardDiagnosis;
    reports?: ScorecardReportLibrary;
  } | null>(null);
  const [failed, setFailed] = React.useState("");

  React.useEffect(() => {
    let live = true;
    const load = async () => {
      switch (tab) {
        case "models":
          return { models: await api.scorecardModels(type) };
        case "variables":
          return {
            variables: await api.scorecardVariables(type),
            dashboard: await api.scorecardDashboard(type, {
              model,
              month,
              curves: false,
            }),
          };
        case "governance":
          return { policy: await api.scorecardPolicy() };
        case "reports":
          return { reports: await api.scorecardReports(type) };
        case "trends":
          return {
            odr: await api.scorecardOdrTrend(type, 20, model),
            drift: await api.scorecardDrift(type, { model, month }),
          };
        case "diagnostics":
          return {
            lowKs: await api.scorecardLowDiscrimination(type, {
              model,
              month,
            }),
            accuracy: await api.scorecardAccuracy(type, { model, month }),
          };
        default:
          return {
            dashboard: await api.scorecardDashboard(type, {
              model,
              month,
              segmentBy:
                type === "APPLICATION" ? "application_channel" : "product",
              curves: tab === "discrimination",
            }),
          };
      }
    };
    load()
      .then((found) => live && setState(found))
      .catch((error: unknown) => {
        if (!live) return;
        setFailed(error instanceof Error ? error.message : "That did not load.");
        setState({});
      });
    return () => {
      live = false;
    };
  }, [tab, type, model, month]);

  if (state === null) return <Skeleton className="h-64 w-full" />;
  if (failed) return <Empty>{failed}</Empty>;

  const dashboard = state.dashboard;
  switch (tab) {
    case "cockpit":
      return dashboard ? <Cockpit data={dashboard} /> : <Empty>No data.</Empty>;
    case "dashboard":
      return dashboard ? <Full data={dashboard} /> : <Empty>No data.</Empty>;
    case "discrimination":
      return dashboard ? (
        <Discrimination data={dashboard} />
      ) : (
        <Empty>No data.</Empty>
      );
    case "calibration":
      return dashboard ? (
        <Calibration data={dashboard} />
      ) : (
        <Empty>No data.</Empty>
      );
    case "stability":
      return dashboard ? <Stability data={dashboard} /> : <Empty>No data.</Empty>;
    case "variables":
      return dashboard ? (
        <Variables data={dashboard} catalogue={state.variables} />
      ) : (
        <Empty>No data.</Empty>
      );
    case "models":
      return state.models ? (
        <Models data={state.models} />
      ) : (
        <Empty>No registry.</Empty>
      );
    case "diagnostics":
      return (
        <Diagnostics lowKs={state.lowKs} accuracy={state.accuracy} />
      );
    case "trends":
      return <Trends odr={state.odr} drift={state.drift} />;
    case "findings":
      return dashboard ? <Findings data={dashboard} /> : <Empty>No data.</Empty>;
    case "governance":
      return state.policy ? (
        <Governance data={state.policy} />
      ) : (
        <Empty>No policy.</Empty>
      );
    case "data":
      return dashboard ? <DataQuality data={dashboard} /> : <Empty>No data.</Empty>;
    case "reports":
      return (
        <Reports
          library={state.reports}
          type={type}
          model={model}
          month={month}
        />
      );
  }
}

function Empty({ children }: { children: React.ReactNode }) {
  return <Card className="p-4 text-xs text-muted-foreground">{children}</Card>;
}

function Unavailable({ why }: { why: string }) {
  return (
    <Card className="p-4">
      <p className="text-xs text-muted-foreground">{why}</p>
    </Card>
  );
}

function Status({ status }: { status: string }) {
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[10px] font-medium",
        STATUS_STYLE[status] ?? "bg-muted text-muted-foreground",
      )}
    >
      {status}
    </span>
  );
}

/** §81's table. Every row has a source, or says it has no limit. */
function Limits({ rows }: { rows: ScorecardAssessment[] }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">
          Every metric, its approved limit, and where that limit came from
        </caption>
        <thead className="text-left text-muted-foreground">
          <tr>
            <th scope="col" className="pb-1 font-normal">Metric</th>
            <th scope="col" className="pb-1 font-normal">Observed</th>
            <th scope="col" className="pb-1 font-normal">Limit</th>
            <th scope="col" className="pb-1 font-normal">Status</th>
            <th scope="col" className="pb-1 font-normal">Source</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.metric} className="border-t border-border/40">
              <td className="py-1">{row.label}</td>
              <td className="py-1 tabular-nums">{stat(row.observed)}</td>
              <td className="py-1 tabular-nums">{stat(row.limit_value)}</td>
              <td className="py-1">
                <Status status={row.status} />
              </td>
              <td className="py-1 text-muted-foreground">
                {row.source ?? "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Kpi({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="rounded border border-border/60 p-3">
      <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
        {label}
      </div>
      <div className="mt-1 text-lg tabular-nums">{value}</div>
      {note && (
        <div className="mt-0.5 text-[10px] text-muted-foreground">{note}</div>
      )}
    </div>
  );
}

// -------------------------------------------------------------- §18 cockpit

function Cockpit({ data }: { data: ScorecardDashboard }) {
  const opinion = data.validation_opinion;
  const discrimination = data.discrimination;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-medium">
            {data.summary.model as string} — {data.context.validation_month}
          </h2>
          <span className="text-[11px] text-muted-foreground">
            {data.context.outcome_maturity_status}
          </span>
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          {data.context.what_this_means}
        </p>
      </Card>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Population" value={count(data.summary.population)} />
        <Kpi
          label="Defaults"
          value={count(data.summary.defaults)}
          note={
            data.summary.observed_default_rate === null
              ? "no realised outcome"
              : `ODR ${percent(data.summary.observed_default_rate)}`
          }
        />
        <Kpi
          label="Average predicted PD"
          value={percent(data.summary.average_predicted_pd)}
        />
        <Kpi
          label="Gini"
          value={
            discrimination.available === false
              ? "—"
              : stat(discrimination.gini)
          }
          note={
            discrimination.available === false
              ? "outcomes not matured"
              : discrimination.evidence
          }
        />
      </div>

      {opinion && (
        <Card className="p-4">
          <div className="text-[10px] uppercase tracking-wide text-muted-foreground">
            Overall validation opinion
          </div>
          <div
            className={cn(
              "mt-1 text-base font-medium",
              OPINION_STYLE[opinion.opinion] ?? "text-foreground",
            )}
          >
            {opinion.opinion}
          </div>
          <ul className="mt-2 space-y-1 text-xs text-muted-foreground">
            {opinion.because.map((one) => (
              <li key={one}>{one}</li>
            ))}
          </ul>
          <p className="mt-3 border-t border-border/40 pt-2 text-[11px] text-muted-foreground">
            {opinion.how_this_was_decided}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {opinion.not_a_certification}
          </p>
        </Card>
      )}

      <Card className="p-4">
        <h2 className="text-sm font-medium">Performance against limits</h2>
        <div className="mt-2">
          <Limits rows={data.performance_limits} />
        </div>
      </Card>
    </div>
  );
}

function Full({ data }: { data: ScorecardDashboard }) {
  return (
    <div className="space-y-4">
      <Cockpit data={data} />
      <Discrimination data={data} />
      <Calibration data={data} />
      <Stability data={data} />
      <Findings data={data} />
    </div>
  );
}

// ------------------------------------------------------------------- §23

function Discrimination({ data }: { data: ScorecardDashboard }) {
  const body = data.discrimination;
  if (body.available === false) return <Unavailable why={body.why} />;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">Discriminatory power</h2>
        <p className="mt-1 text-xs text-muted-foreground">{body.reads_as}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">
          <Kpi
            label="AUC"
            value={stat(body.auc)}
            note={
              body.auc_ci_low === null
                ? undefined
                : `95% CI ${stat(body.auc_ci_low)} – ${stat(body.auc_ci_high)}`
            }
          />
          <Kpi label="Gini / Accuracy Ratio" value={stat(body.gini)} />
          <Kpi
            label="KS"
            value={stat(body.ks)}
            note={`at score ${body.ks_at_score.toFixed(2)}`}
          />
        </div>
        <dl className="mt-3 space-y-0.5 text-[11px] text-muted-foreground">
          {Object.entries(body.definitions).map(([key, value]) => (
            <div key={key}>
              <dt className="inline font-medium">{key}: </dt>
              <dd className="inline">{value}</dd>
            </div>
          ))}
        </dl>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Gains, lift and capture by decile</h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">
              Bad rate, lift and cumulative capture rate by decile of risk
            </caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Decile</th>
                <th scope="col" className="pb-1 font-normal">Accounts</th>
                <th scope="col" className="pb-1 font-normal">Defaults</th>
                <th scope="col" className="pb-1 font-normal">Bad rate</th>
                <th scope="col" className="pb-1 font-normal">Lift</th>
                <th scope="col" className="pb-1 font-normal">Capture</th>
              </tr>
            </thead>
            <tbody>
              {body.gains.map((row) => (
                <tr key={row.decile} className="border-t border-border/40">
                  <td className="py-1">{row.decile}</td>
                  <td className="py-1 tabular-nums">{count(row.observations)}</td>
                  <td className="py-1 tabular-nums">{count(row.events)}</td>
                  <td className="py-1 tabular-nums">{percent(row.bad_rate)}</td>
                  <td className="py-1 tabular-nums">{row.lift.toFixed(2)}×</td>
                  <td className="py-1 tabular-nums">
                    {percent(row.cumulative_capture_rate)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {body.roc_curve && body.roc_curve.length > 1 && (
        <Card className="p-4">
          <h2 className="text-sm font-medium">ROC curve</h2>
          <Roc points={body.roc_curve} auc={body.auc} />
        </Card>
      )}
    </div>
  );
}

function Roc({
  points,
  auc,
}: {
  points: { false_positive_rate: number; true_positive_rate: number }[];
  auc: number;
}) {
  const size = 220;
  const path = points
    .map(
      (p, i) =>
        `${i === 0 ? "M" : "L"} ${(p.false_positive_rate * size).toFixed(1)} ${(
          size -
          p.true_positive_rate * size
        ).toFixed(1)}`,
    )
    .join(" ");
  return (
    <svg
      viewBox={`0 0 ${size} ${size}`}
      className="mt-2 h-56 w-56"
      role="img"
      aria-label={`ROC curve, area under the curve ${stat(auc)}`}
    >
      <line
        x1="0"
        y1={size}
        x2={size}
        y2="0"
        stroke="currentColor"
        strokeDasharray="3 3"
        className="text-border"
      />
      <path
        d={path}
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        className="text-primary"
      />
      <rect
        x="0"
        y="0"
        width={size}
        height={size}
        fill="none"
        stroke="currentColor"
        className="text-border"
      />
    </svg>
  );
}

// ------------------------------------------------------------------- §24

function Calibration({ data }: { data: ScorecardDashboard }) {
  const body = data.calibration;
  if (body.available === false) return <Unavailable why={body.why} />;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">Calibration and accuracy</h2>
        <p className="mt-1 text-xs text-muted-foreground">{body.reads_as}</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Kpi
            label="Observed default rate"
            value={percent(body.observed_default_rate)}
            note={`${count(body.observed_defaults)} defaults`}
          />
          <Kpi
            label="Average predicted PD"
            value={percent(body.average_predicted_pd)}
            note={`${count(Math.round(body.expected_defaults))} expected`}
          />
          <Kpi
            label="Brier score"
            value={stat(body.brier_score, 6)}
            note="account level"
          />
          <Kpi
            label="Calibration RMSE"
            value={stat(body.bucket_rmse, 6)}
            note="by score band"
          />
        </div>
        <p className="mt-3 text-[11px] text-muted-foreground">
          {body.what_rmse_means_here}
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          MAPE {body.mape === null ? "not reported" : `${body.mape.toFixed(2)}%`}
          {" — "}
          {body.mape_status}
        </p>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">
          Observed against predicted, by score band
        </h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">
              Observed default rate against average predicted PD per band
            </caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Band</th>
                <th scope="col" className="pb-1 font-normal">Score range</th>
                <th scope="col" className="pb-1 font-normal">Accounts</th>
                <th scope="col" className="pb-1 font-normal">Observed</th>
                <th scope="col" className="pb-1 font-normal">Predicted</th>
                <th scope="col" className="pb-1 font-normal">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {body.buckets.map((row) => (
                <tr key={row.band} className="border-t border-border/40">
                  <td className="py-1">{row.band}</td>
                  <td className="py-1 tabular-nums">
                    {row.score_from.toFixed(2)} – {row.score_to.toFixed(2)}
                  </td>
                  <td className="py-1 tabular-nums">{count(row.observations)}</td>
                  <td className="py-1 tabular-nums">
                    {percent(row.observed_default_rate)}
                  </td>
                  <td className="py-1 tabular-nums">
                    {percent(row.average_predicted_pd)}
                  </td>
                  <td className="py-1 text-muted-foreground">{row.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- §25/§26

function Stability({ data }: { data: ScorecardDashboard }) {
  const body = data.stability;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="text-sm font-medium">Score stability</h2>
          <Status status={body.score_psi_assessment.status} />
        </div>
        <div className="mt-2 grid gap-3 sm:grid-cols-2">
          <Kpi
            label="Score PSI"
            value={stat(body.score_psi.index)}
            note={`against the ${body.baseline.toLowerCase()} population`}
          />
          <Kpi
            label="Reference / current rows"
            value={`${count(body.score_psi.reference_rows)} / ${count(
              body.score_psi.current_rows,
            )}`}
          />
        </div>
        <p className="mt-2 text-[11px] text-muted-foreground">
          {body.score_psi.thresholds_are_policy}
        </p>
        <p className="mt-1 text-[11px] text-muted-foreground">
          {body.available_without_outcomes}
        </p>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">
          Characteristic stability by active variable
        </h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">
              CSI per active model variable, largest first
            </caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Variable</th>
                <th scope="col" className="pb-1 font-normal">CSI</th>
                <th scope="col" className="pb-1 font-normal">Status</th>
                <th scope="col" className="pb-1 font-normal">Largest move</th>
              </tr>
            </thead>
            <tbody>
              {body.variable_csi.map((row) => (
                <tr key={row.variable} className="border-t border-border/40">
                  <td className="py-1">{row.variable}</td>
                  <td className="py-1 tabular-nums">{stat(row.index)}</td>
                  <td className="py-1">
                    {row.assessment ? (
                      <Status status={row.assessment.status} />
                    ) : (
                      "—"
                    )}
                  </td>
                  <td className="py-1 text-muted-foreground">
                    {row.bins?.[0]
                      ? `${row.bins[0].bin}: ${percent(
                          row.bins[0].reference_share,
                        )} → ${percent(row.bins[0].current_share)}`
                      : (row.why ?? "—")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------- §27

function Variables({
  data,
  catalogue,
}: {
  data: ScorecardDashboard;
  catalogue?: ScorecardVariables;
}) {
  const body = data.variables;
  if (body.available === false) return <Unavailable why={body.why} />;
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">Active model variables</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          {body.candidate_is_not_active}
        </p>
        <div className="mt-3 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">
              Univariate discrimination and Information Value per variable
            </caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Variable</th>
                <th scope="col" className="pb-1 font-normal">Coefficient</th>
                <th scope="col" className="pb-1 font-normal">AUC</th>
                <th scope="col" className="pb-1 font-normal">Gini</th>
                <th scope="col" className="pb-1 font-normal">KS</th>
                <th scope="col" className="pb-1 font-normal">IV</th>
                <th scope="col" className="pb-1 font-normal">Missing</th>
                <th scope="col" className="pb-1 font-normal">Evidence</th>
              </tr>
            </thead>
            <tbody>
              {body.variables.map((row) => (
                <tr key={row.variable} className="border-t border-border/40">
                  <td className="py-1">{row.variable}</td>
                  <td className="py-1 tabular-nums">
                    {tableCoefficient(row.coefficient)}
                  </td>
                  <td className="py-1 tabular-nums">{stat(row.auc)}</td>
                  <td className="py-1 tabular-nums">{stat(row.gini)}</td>
                  <td className="py-1 tabular-nums">{stat(row.ks)}</td>
                  <td className="py-1 tabular-nums">
                    {stat(row.information_value)}
                  </td>
                  <td className="py-1 tabular-nums">
                    {percent(row.missing_rate)}
                  </td>
                  <td className="py-1 text-muted-foreground">{row.evidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {catalogue && (
        <Card className="p-4">
          <h2 className="text-sm font-medium">
            Candidate dictionary ({catalogue.candidate_count} variables)
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Sensitive fields kept for fairness monitoring and excluded from any
            score: {catalogue.sensitive_excluded_from_scoring.join(", ")}
          </p>
        </Card>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- §12/§34

function Models({ data }: { data: ScorecardModels }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">Default definition</h2>
        <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
          {Object.entries(data.default_definition).map(([key, value]) => (
            <div key={key}>
              <dt className="text-muted-foreground">
                {key.replace(/_/g, " ")}
              </dt>
              <dd>{String(value)}</dd>
            </div>
          ))}
        </dl>
      </Card>

      {Object.entries(data.models).map(([kind, entry]) => (
        <EquationCard key={kind} kind={kind} equation={entry.equation} />
      ))}

      <p className="text-[11px] text-muted-foreground">
        {data.answered_from_the_registry}
      </p>
    </div>
  );
}

function EquationCard({
  kind,
  equation,
}: {
  kind: string;
  equation: ScorecardEquation;
}) {
  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="text-sm font-medium">{kind}</h2>
        <span className="text-[11px] text-muted-foreground">
          {equation.binning_spec_version}
        </span>
      </div>
      <pre className="mt-2 overflow-x-auto rounded bg-muted/50 p-2 text-[11px]">
        {equation.reads_as}
      </pre>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <caption className="sr-only">Coefficients of {kind}</caption>
          <thead className="text-left text-muted-foreground">
            <tr>
              <th scope="col" className="pb-1 font-normal">Variable</th>
              <th scope="col" className="pb-1 font-normal">Coefficient</th>
              <th scope="col" className="pb-1 font-normal">Applied to</th>
            </tr>
          </thead>
          <tbody>
            {equation.terms.map((term) => (
              <tr key={term.variable} className="border-t border-border/40">
                <td className="py-1">{term.variable}</td>
                <td className="py-1 tabular-nums">
                  {equationCoefficient(term.coefficient)}
                </td>
                <td className="py-1 text-muted-foreground">{term.column}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {equation.validation.warnings.length > 0 && (
        <ul className="mt-3 space-y-1 border-t border-border/40 pt-2 text-[11px] text-caution">
          {equation.validation.warnings.map((one) => (
            <li key={one.detail}>{one.detail}</li>
          ))}
        </ul>
      )}
    </Card>
  );
}

// ---------------------------------------------------------------- §28/§29

function Diagnostics({
  lowKs,
  accuracy,
}: {
  lowKs?: ScorecardDiagnosis;
  accuracy?: ScorecardDiagnosis;
}) {
  return (
    <div className="space-y-4">
      {lowKs && <DiagnosisCard data={lowKs} />}
      {accuracy && <DiagnosisCard data={accuracy} />}
      {!lowKs && !accuracy && <Empty>No diagnostics ran.</Empty>}
    </div>
  );
}

function DiagnosisCard({ data }: { data: ScorecardDiagnosis }) {
  return (
    <Card className="p-4">
      <h2 className="text-sm font-medium">{data.question_as_asked}</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        Analysed as: {data.question_as_analysed}
      </p>
      <p className="mt-1 text-[11px] text-muted-foreground">
        {data.why_restated}
      </p>

      <ol className="mt-3 space-y-1 text-xs text-muted-foreground">
        {data.steps_run.map((step) => (
          <li key={step}>{step}</li>
        ))}
      </ol>

      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-xs">
          <caption className="sr-only">
            Evidence, ranked by weight
          </caption>
          <thead className="text-left text-muted-foreground">
            <tr>
              <th scope="col" className="pb-1 font-normal">Rank</th>
              <th scope="col" className="pb-1 font-normal">Subject</th>
              <th scope="col" className="pb-1 font-normal">Weight</th>
              <th scope="col" className="pb-1 font-normal">On what</th>
            </tr>
          </thead>
          <tbody>
            {data.ranked.map((row) => (
              <tr
                key={`${row.rank}-${row.subject ?? row.root_cause}`}
                className="border-t border-border/40"
              >
                <td className="py-1">{row.rank}</td>
                <td className="py-1">{row.subject ?? row.root_cause}</td>
                <td className="py-1 tabular-nums">{stat(row.weight)}</td>
                <td className="py-1 text-muted-foreground">
                  {row.because ?? row.measures?.join(", ") ?? "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-3 border-t border-border/40 pt-2 text-[11px]">
        <span className="text-muted-foreground">Claim strength: </span>
        {data.claim_strength}
      </p>
      <ul className="mt-1 space-y-1 text-[11px] text-muted-foreground">
        {data.limitations.map((one) => (
          <li key={one}>{one}</li>
        ))}
      </ul>
    </Card>
  );
}

// ---------------------------------------------------------------- §30/§31

function Trends({
  odr,
  drift,
}: {
  odr?: ScorecardOdrTrend;
  drift?: ScorecardDrift;
}) {
  return (
    <div className="space-y-4">
      {odr && (
        <Card className="p-4">
          <h2 className="text-sm font-medium">
            Observed default rate against predicted PD
          </h2>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {odr.only_matured}
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <caption className="sr-only">
                Monthly observed default rate and average predicted PD
              </caption>
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th scope="col" className="pb-1 font-normal">Month</th>
                  <th scope="col" className="pb-1 font-normal">Accounts</th>
                  <th scope="col" className="pb-1 font-normal">Defaults</th>
                  <th scope="col" className="pb-1 font-normal">ODR</th>
                  <th scope="col" className="pb-1 font-normal">Predicted PD</th>
                </tr>
              </thead>
              <tbody>
                {odr.months.map((row) => (
                  <tr key={row.month} className="border-t border-border/40">
                    <td className="py-1">{row.month}</td>
                    <td className="py-1 tabular-nums">
                      {count(row.observations)}
                    </td>
                    <td className="py-1 tabular-nums">{count(row.defaults)}</td>
                    <td className="py-1 tabular-nums">
                      {percent(row.observed_default_rate)}
                    </td>
                    <td className="py-1 tabular-nums">
                      {percent(row.average_predicted_pd)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {drift && (
        <Card className="p-4">
          <h2 className="text-sm font-medium">
            Variable drift — {drift.scope.toLowerCase()}
          </h2>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-xs">
              <caption className="sr-only">CSI per variable</caption>
              <thead className="text-left text-muted-foreground">
                <tr>
                  <th scope="col" className="pb-1 font-normal">Variable</th>
                  <th scope="col" className="pb-1 font-normal">CSI</th>
                  <th scope="col" className="pb-1 font-normal">In the model</th>
                </tr>
              </thead>
              <tbody>
                {drift.variables.slice(0, 25).map((row) => (
                  <tr key={row.variable} className="border-t border-border/40">
                    <td className="py-1">{row.variable}</td>
                    <td className="py-1 tabular-nums">
                      {row.csi === null ? (row.why ?? "—") : stat(row.csi)}
                    </td>
                    <td className="py-1 text-muted-foreground">
                      {row.in_active_model ? "yes" : "candidate only"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-muted-foreground">
            {drift.why_some_are_absent}
          </p>
        </Card>
      )}
    </div>
  );
}

// ------------------------------------------------------------------- §48

function Findings({ data }: { data: ScorecardDashboard }) {
  const findings = data.findings.findings;
  if (findings.length === 0) {
    return (
      <Empty>
        No limit was breached and nothing is on watch for this model and month.
      </Empty>
    );
  }
  return (
    <div className="space-y-3">
      {findings.map((one) => (
        <Card key={one.finding_id} className="p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium">{one.title}</h3>
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[10px] font-medium",
                one.severity === "HIGH"
                  ? "bg-negative/12 text-negative"
                  : one.severity === "MEDIUM"
                    ? "bg-caution/15 text-caution"
                    : "bg-muted text-muted-foreground",
              )}
            >
              {one.severity}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            {one.description}
          </p>
          <dl className="mt-2 grid gap-1 text-[11px] sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground">Observed</dt>
              <dd className="tabular-nums">{stat(one.observed)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Limit</dt>
              <dd className="tabular-nums">{stat(one.limit_value)}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground">Source</dt>
              <dd>{one.limit_source || "—"}</dd>
            </div>
          </dl>
          <p className="mt-2 text-[11px] text-muted-foreground">
            {one.recommendation}
          </p>
          <p className="mt-1 text-[10px] text-muted-foreground">
            {one.finding_id} · {one.report_section} · {one.status}
          </p>
        </Card>
      ))}
    </div>
  );
}

// ------------------------------------------------------------- §50/§80/§81

function Governance({ data }: { data: ScorecardPolicy }) {
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h2 className="text-sm font-medium">Where these limits come from</h2>
        <p className="mt-1 text-xs text-muted-foreground">{data.why}</p>
        <ul className="mt-2 flex flex-wrap gap-1 text-[11px]">
          {data.provenances.map((one) => (
            <li key={one} className="rounded bg-muted px-1.5 py-0.5">
              {one}
            </li>
          ))}
        </ul>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Validation policy</h2>
        <div className="mt-2 overflow-x-auto">
          <table className="w-full text-xs">
            <caption className="sr-only">
              Every configured limit, its direction and its provenance
            </caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Metric</th>
                <th scope="col" className="pb-1 font-normal">Direction</th>
                <th scope="col" className="pb-1 font-normal">Watch</th>
                <th scope="col" className="pb-1 font-normal">Breach</th>
                <th scope="col" className="pb-1 font-normal">Source</th>
              </tr>
            </thead>
            <tbody>
              {data.limits.map((row) => (
                <tr key={row.metric} className="border-t border-border/40">
                  <td className="py-1">{row.label}</td>
                  <td className="py-1 text-muted-foreground">
                    {row.direction.replace(/_/g, " ").toLowerCase()}
                  </td>
                  <td className="py-1 tabular-nums">{stat(row.watch_at)}</td>
                  <td className="py-1 tabular-nums">{stat(row.breach_at)}</td>
                  <td className="py-1 text-muted-foreground">
                    {row.provenance}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

// ------------------------------------------------------------------- §38

function DataQuality({ data }: { data: ScorecardDashboard }) {
  const body = data.data_quality;
  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi label="Rows" value={count(body.rows)} />
        <Kpi
          label="Duplicate keys"
          value={count(body.duplicate_keys)}
          note={body.duplicate_keys === 0 ? "keys are unique" : undefined}
        />
        <Kpi label="Defaults" value={count(body.defaults)} />
        <Kpi
          label="Score range"
          value={`${body.score_range.min.toFixed(2)} – ${body.score_range.max.toFixed(2)}`}
          note={body.pd_within_zero_and_one ? "PD within [0, 1]" : "PD OUT OF RANGE"}
        />
      </div>

      <Card className="p-4">
        <h2 className="text-sm font-medium">Sample sufficiency</h2>
        <div className="mt-2">
          <Limits rows={body.sample_sufficiency} />
        </div>
      </Card>

      <Card className="p-4">
        <h2 className="text-sm font-medium">
          Missingness on active model variables
        </h2>
        <div className="mt-2">
          <Limits rows={body.missingness_assessments} />
        </div>
      </Card>
    </div>
  );
}

/** One labelled value in a definition list. */
function Pair({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="tabular-nums">{value}</dd>
    </div>
  );
}

/**
 * §51/§82/§83. The report library, and the two downloads.
 *
 * Generating and downloading are separate buttons because they are separate
 * acts. Generating records what was reported and to whom; downloading
 * reproduces it. A single button that did both would leave no record of a
 * report somebody looked at and did not save.
 *
 * The coverage line is not decoration either. §89 lists seventeen topics a
 * validation report has to address, and showing which ones this report
 * covers — before anybody sends it to a committee — is the difference
 * between a checklist that ran and a checklist that was filed.
 */
function Reports({
  library,
  type,
  model,
  month,
}: {
  library?: ScorecardReportLibrary;
  type: ScorecardType;
  model: string;
  month: string;
}) {
  const [built, setBuilt] = React.useState<ScorecardReport | null>(null);
  const [busy, setBusy] = React.useState(false);
  const [failed, setFailed] = React.useState("");

  const generate = React.useCallback(async () => {
    setBusy(true);
    setFailed("");
    try {
      setBuilt(
        await api.scorecardGenerateReport(type, {
          month,
          model_kind: model,
          record: true,
        }),
      );
    } catch (error) {
      setFailed(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }, [type, model, month]);

  const params = { month, model_kind: model };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        <h3 className="text-sm font-medium">Validation report</h3>
        <p className="mt-1 text-xs text-muted-foreground">
          Thirteen sections aligned with the CBUAE Model Management Standards
          and Guidance section list. Every figure is taken from the
          deterministic engine for this model and month — nothing in the
          report is recalculated, and no language model is asked for a
          number. CreditProbe does not provide regulatory certification.
        </p>

        <div className="mt-3 flex flex-wrap gap-2">
          <button
            type="button"
            onClick={generate}
            disabled={busy}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted disabled:opacity-50"
          >
            {busy ? "Generating…" : "Generate validation report"}
          </button>
          <a
            href={api.scorecardReportDownloadUrl(type, "docx", params)}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Download validation report (DOCX)
          </a>
          <a
            href={api.scorecardReportDownloadUrl(type, "xlsx", {
              ...params,
              history_months: 12,
            })}
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium hover:bg-muted"
          >
            Download validation evidence (XLSX)
          </a>
        </div>

        {failed ? (
          <p className="mt-2 text-xs text-destructive">{failed}</p>
        ) : null}
      </Card>

      {built ? (
        <Card className="p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="text-sm font-medium">{built.title}</h3>
            <Status status={built.opinion} />
          </div>
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-1 text-xs sm:grid-cols-4">
            <Pair label="Report" value={built.report_id} />
            <Pair label="Model version" value={built.model_version} />
            <Pair label="Structure" value={built.structure_version} />
            <Pair label="Evidence items" value={String(built.evidence_count)} />
            <Pair label="Generated by" value={built.generated_by} />
            <Pair label="Content hash" value={built.content_hash.slice(0, 16)} />
          </dl>

          <p className="mt-3 text-xs">
            <span className="font-medium">Coverage:</span>{" "}
            {built.coverage.complete
              ? `all ${built.coverage.topics} required topics are addressed.`
              : `${built.coverage.missing.length} of ${built.coverage.topics} topics are not addressed: ${built.coverage.missing.join(", ")}.`}
          </p>

          <table className="mt-3 w-full text-xs">
            <caption className="sr-only">Sections of {built.title}</caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Section</th>
                <th scope="col" className="pb-1 font-normal">Title</th>
                <th scope="col" className="pb-1 font-normal">Reported</th>
              </tr>
            </thead>
            <tbody>
              {built.sections.map((section) => (
                <tr key={section.number} className="border-t border-border/40">
                  <td className="py-1 tabular-nums">{section.number}</td>
                  <td className="py-1">{section.title}</td>
                  <td className="py-1 text-muted-foreground">
                    {section.unavailable ? section.unavailable : "Reported"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-xs text-muted-foreground">
            {built.not_client_data}
          </p>
          <p className="mt-1 text-xs text-muted-foreground">
            {built.disclaimer}
          </p>
        </Card>
      ) : null}

      <Card className="p-4">
        <h3 className="text-sm font-medium">Report library</h3>
        {!library || library.count === 0 ? (
          <p className="mt-1 text-xs text-muted-foreground">
            No report has been generated for this scorecard yet. Generating one
            records what was reported, by whom and with which disclaimer;
            downloading without generating leaves no such record.
          </p>
        ) : (
          <table className="mt-2 w-full text-xs">
            <caption className="sr-only">Generated validation reports</caption>
            <thead className="text-left text-muted-foreground">
              <tr>
                <th scope="col" className="pb-1 font-normal">Report</th>
                <th scope="col" className="pb-1 font-normal">Model</th>
                <th scope="col" className="pb-1 font-normal">Version</th>
                <th scope="col" className="pb-1 font-normal">Period</th>
                <th scope="col" className="pb-1 font-normal">Opinion</th>
                <th scope="col" className="pb-1 font-normal">Generated by</th>
                <th scope="col" className="pb-1 font-normal">Generated at</th>
              </tr>
            </thead>
            <tbody>
              {library.reports.map((entry) => (
                <tr key={entry.report_id} className="border-t border-border/40">
                  <td className="py-1">{entry.report_id}</td>
                  <td className="py-1">{entry.model_id}</td>
                  <td className="py-1">{entry.model_version}</td>
                  <td className="py-1 tabular-nums">{entry.period}</td>
                  <td className="py-1">
                    <Status status={entry.opinion} />
                  </td>
                  <td className="py-1">{entry.generated_by}</td>
                  <td className="py-1 text-muted-foreground">
                    {entry.generated_at.slice(0, 19).replace("T", " ")}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
