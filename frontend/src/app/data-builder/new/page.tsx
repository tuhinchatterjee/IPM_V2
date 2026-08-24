"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import * as React from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Check,
  CheckCircle2,
  CloudCog,
  Database,
  FileSpreadsheet,
  Globe,
  HardDrive,
  Loader2,
  Lock,
  Rocket,
  Server,
  Snowflake,
  TriangleAlert,
  Upload,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { ReadOnlyNotice, useCanEditData } from "@/components/system/role-switcher";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, ApiError } from "@/lib/api";
import type {
  DictionaryField,
  FieldMappingRow,
  MappingStatus,
  UploadProfile,
  ValidationReport,
} from "@/lib/api";
import { useAsync } from "@/lib/hooks";
import { domainHref } from "@/lib/links";
import { cn } from "@/lib/utils";

/**
 * The Add Dataset workflow.
 *
 * Eight steps against the real backend: everything except the future connection
 * options actually happens. The uploaded file is written to the raw layer and
 * kept unchanged, the profile is computed by the server, the mapping
 * suggestions come from the backend's own matcher, validation runs the real
 * quality checks, and publishing writes Parquet and makes the dataset visible
 * to the engine.
 *
 * The steps are deliberately linear and gated: a steward cannot publish
 * something they have not validated, which is the same rule the backend
 * enforces.
 */

const STEPS = [
  { id: 1, label: "Dataset details" },
  { id: 2, label: "Upload or connect" },
  { id: 3, label: "Inspect" },
  { id: 4, label: "Map fields" },
  { id: 5, label: "Data dictionary" },
  { id: 6, label: "Relationships" },
  { id: 7, label: "Validate" },
  { id: 8, label: "Publish" },
];

const FUTURE_SOURCES = [
  { icon: Server, label: "Database", note: "Oracle, SQL Server, PostgreSQL" },
  { icon: Globe, label: "API", note: "REST or GraphQL endpoint" },
  { icon: HardDrive, label: "SFTP", note: "Scheduled file drop" },
  { icon: CloudCog, label: "Cloud Storage", note: "S3, ADLS, GCS" },
  { icon: Database, label: "Databricks", note: "Unity Catalog / Delta" },
  { icon: Snowflake, label: "Snowflake", note: "Governed share" },
];

const DOMAIN_OPTIONS = [
  "Core Portfolio / Facility",
  "IFRS 9 / ECL",
  "Corporate Ratings",
  "Retail / SME Scorecards",
  "Documents",
  "Policies / Knowledge",
  "CreditProbe Operational Metadata",
];

export default function AddDatasetPage() {
  const router = useRouter();
  const canEdit = useCanEditData();

  const [step, setStep] = React.useState(1);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  // Step 1
  const [name, setName] = React.useState("");
  const [domain, setDomain] = React.useState(DOMAIN_OPTIONS[1]);
  const [businessName, setBusinessName] = React.useState("");
  const [purpose, setPurpose] = React.useState("");
  const [grain, setGrain] = React.useState("");
  const [owner, setOwner] = React.useState("");
  const [periodField, setPeriodField] = React.useState("period");
  const [primaryKeys, setPrimaryKeys] = React.useState("period, account_id");
  const [created, setCreated] = React.useState(false);

  // Step 2/3
  const [profile, setProfile] = React.useState<UploadProfile | null>(null);
  const [uploadName, setUploadName] = React.useState<string | null>(null);

  // Step 4
  const [mappings, setMappings] = React.useState<FieldMappingRow[]>([]);

  // Step 5
  const [fields, setFields] = React.useState<DictionaryField[]>([]);

  // Step 6
  const existingDatasets = useAsync(() => api.catalog(), []);
  const [relFromField, setRelFromField] = React.useState("");
  const [relToDataset, setRelToDataset] = React.useState("portfolio_facility");
  const [relToField, setRelToField] = React.useState("account_id");
  const [addedRelationships, setAddedRelationships] = React.useState<string[]>([]);

  // Step 7/8
  const [report, setReport] = React.useState<ValidationReport | null>(null);
  const [published, setPublished] = React.useState<{ version: number; periods: string[] } | null>(
    null,
  );

  const mappedCount = mappings.filter(
    (m) => m.status === "mapped" || m.status === "proposed",
  ).length;

  function fail(e: unknown) {
    setError(e instanceof ApiError ? e.message : "Something went wrong.");
  }

  async function run<T>(fn: () => Promise<T>, onSuccess: (result: T) => void) {
    setBusy(true);
    setError(null);
    try {
      onSuccess(await fn());
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------- step actions

  async function createDataset() {
    await run(
      async () => {
        // The domain must exist before a dataset can join it.
        await api.createDomain({ name: domain });
        return api.createDataset({
          name: name.trim(),
          domain,
          business_name: businessName || name,
          purpose,
          grain,
          owner,
          period_field: periodField,
          primary_keys: primaryKeys
            .split(",")
            .map((k) => k.trim())
            .filter(Boolean),
        });
      },
      () => {
        setCreated(true);
        setStep(2);
      },
    );
  }

  async function upload(file: File) {
    await run(
      () => api.uploadFile(name.trim(), file),
      (result) => {
        setProfile(result.profile);
        setUploadName(result.upload.filename);
        setMappings(result.suggested_mappings);
        setStep(3);
      },
    );
  }

  async function saveMappings() {
    await run(
      () =>
        api.setMappings(
          name.trim(),
          mappings.map((m) => ({
            source_column: m.source_column,
            governed_field: m.governed_field,
            status: m.status,
          })),
        ),
      async (result) => {
        setMappings(result.mappings);
        // Seed the dictionary so the steward edits definitions rather than
        // typing every field name a second time.
        await api.seedDictionary(name.trim());
        const detail = await api.dataset(name.trim());
        setFields(detail.fields);
        setStep(5);
      },
    );
  }

  async function saveDictionary() {
    setBusy(true);
    setError(null);
    try {
      for (const f of fields) {
        await api.upsertField(name.trim(), f);
      }
      setStep(6);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function addRelationship() {
    if (!relFromField || !relToField) return;
    await run(
      () =>
        api.addRelationship({
          from_dataset: name.trim(),
          from_field: relFromField,
          to_dataset: relToDataset,
          to_field: relToField,
          cardinality: "many_to_one",
          kind: "key",
        }),
      (r) => setAddedRelationships((prev) => [...prev, r.name]),
    );
  }

  async function validate() {
    await run(
      () => api.validate(name.trim()),
      (r) => {
        setReport(r);
        setStep(7);
      },
    );
  }

  async function publish() {
    await run(
      () => api.publish(name.trim()),
      (r) => {
        setPublished({ version: r.version, periods: r.periods });
        setStep(8);
      },
    );
  }

  if (!canEdit) {
    return (
      <div className="space-y-6">
        <BackLink />
        <PageHeader title="Add Dataset" description="Bring a source file into CreditProbe." />
        <ReadOnlyNotice action="create or publish datasets" />
      </div>
    );
  }

  // Autocomplete for the governed-field boxes: the names already suggested for
  // this file. Reusing an existing name is what makes datasets join.
  const governedFieldOptions = Array.from(
    new Set(mappings.map((m) => m.governed_field).filter((v): v is string => Boolean(v))),
  );

  return (
    <div className="space-y-6">
      <BackLink />
      <PageHeader
        title="Add Dataset"
        description="Bring a source file into CreditProbe: upload it, map it to governed fields, document it, validate it and publish it. The raw file is kept unchanged."
        status="live"
      />

      <Stepper current={step} onJump={(s) => created && s < step && setStep(s)} />

      {error && (
        <Card className="flex items-start gap-2 border-negative/40 p-4 text-sm text-negative">
          <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </Card>
      )}

      {/* ============================================== STEP 1 — details */}
      {step === 1 && (
        <Card className="p-6">
          <StepTitle n={1} title="Dataset details" sub="What is this dataset, and what does one row represent?" />
          <div className="grid gap-4 md:grid-cols-2">
            <Field
              label="Governed name"
              hint="Lower case, underscores. This is the name the engine and every analysis will use."
            >
              <Input
                value={name}
                onChange={(e) => setName(e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_"))}
                placeholder="ecl_extract"
              />
            </Field>
            <Field label="Business name" hint="What people call it.">
              <Input
                value={businessName}
                onChange={(e) => setBusinessName(e.target.value)}
                placeholder="Third-party ECL Extract"
              />
            </Field>
            <Field label="Data domain">
              <Select value={domain} onChange={(e) => setDomain(e.target.value)}>
                {DOMAIN_OPTIONS.map((d) => (
                  <option key={d}>{d}</option>
                ))}
              </Select>
            </Field>
            <Field label="Owner" hint="Accountable team or person.">
              <Input value={owner} onChange={(e) => setOwner(e.target.value)} placeholder="Group Finance" />
            </Field>
            <Field
              label="Grain"
              className="md:col-span-2"
              hint="What exactly one row represents — the most misunderstood property of a table."
            >
              <Input
                value={grain}
                onChange={(e) => setGrain(e.target.value)}
                placeholder="One row per facility per reporting period."
              />
            </Field>
            <Field label="Reporting period field" hint="Used to partition the analytical layer.">
              <Input value={periodField} onChange={(e) => setPeriodField(e.target.value)} />
            </Field>
            <Field label="Primary key" hint="Comma separated. Uniqueness is checked at validation.">
              <Input value={primaryKeys} onChange={(e) => setPrimaryKeys(e.target.value)} />
            </Field>
            <Field label="Purpose" className="md:col-span-2">
              <Textarea
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                placeholder="Why this dataset exists and what it is used for."
              />
            </Field>
          </div>
          <div className="mt-6 flex justify-end">
            <Button onClick={createDataset} disabled={!name.trim() || busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
              Create and continue
            </Button>
          </div>
        </Card>
      )}

      {/* =============================================== STEP 2 — upload */}
      {step === 2 && (
        <div className="space-y-4">
          <Card className="p-6">
            <StepTitle n={2} title="Upload a file" sub="CSV, Excel or Parquet. The file is stored unchanged in the raw layer." />
            <label
              className={cn(
                "flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed border-border px-6 py-12 text-center transition-colors hover:border-accent hover:bg-surface-hover",
                busy && "pointer-events-none opacity-60",
              )}
            >
              {busy ? (
                <Loader2 className="size-7 animate-spin text-accent" aria-hidden />
              ) : (
                <Upload className="size-7 text-text-muted" aria-hidden />
              )}
              <div>
                <p className="text-sm font-medium text-text-primary">
                  {busy ? "Reading and inspecting…" : "Choose a file"}
                </p>
                <p className="mt-1 text-xs text-text-muted">CSV · Excel (.xlsx, .xls) · Parquet</p>
              </div>
              <input
                type="file"
                accept=".csv,.xlsx,.xls,.parquet"
                className="sr-only"
                disabled={busy}
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) void upload(file);
                }}
              />
            </label>
          </Card>

          <Card className="p-6">
            <div className="mb-4 flex items-center gap-2">
              <h3 className="text-sm font-semibold text-text-primary">Connect a source</h3>
              <Badge variant="outline">Preview</Badge>
            </div>
            <p className="mb-4 text-xs text-text-muted">
              Scheduled connections are not built yet. They are shown so the intended shape of
              the workflow is clear; none of them is functional today.
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {FUTURE_SOURCES.map(({ icon: Icon, label, note }) => (
                <div
                  key={label}
                  className="flex cursor-not-allowed items-start gap-3 rounded-lg border border-border bg-surface-sunken p-4 opacity-60"
                  aria-disabled
                >
                  <Icon className="mt-0.5 size-4 shrink-0 text-text-muted" aria-hidden />
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 text-sm font-medium text-text-secondary">
                      {label}
                      <Lock className="size-3 text-text-muted" aria-hidden />
                    </p>
                    <p className="text-xs text-text-muted">{note}</p>
                  </div>
                </div>
              ))}
            </div>
          </Card>
        </div>
      )}

      {/* ============================================== STEP 3 — inspect */}
      {step === 3 && profile && (
        <Card className="p-6">
          <StepTitle
            n={3}
            title="Inspect"
            sub={`${uploadName} — ${profile.row_count.toLocaleString()} rows, ${profile.column_count} columns, inspected automatically.`}
          />
          <div className="mb-4 flex flex-wrap gap-3">
            <Metric label="Rows" value={profile.row_count.toLocaleString()} />
            <Metric label="Columns" value={String(profile.column_count)} />
            <Metric
              label="Period candidates"
              value={profile.period_candidates.join(", ") || "none identified"}
            />
          </div>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Column</TableHead>
                <TableHead>Inferred type</TableHead>
                <TableHead numeric>Null %</TableHead>
                <TableHead numeric>Unique</TableHead>
                <TableHead numeric>Min</TableHead>
                <TableHead numeric>Max</TableHead>
                <TableHead>Sample values</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {profile.columns.map((c) => (
                <TableRow key={c.name}>
                  <TableCell className="font-mono text-xs text-text-primary">{c.name}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{c.inferred_type}</Badge>
                  </TableCell>
                  <TableCell numeric className={c.null_pct > 0 ? "text-warning" : undefined}>
                    {c.null_pct.toFixed(1)}%
                  </TableCell>
                  <TableCell numeric>{c.unique_count.toLocaleString()}</TableCell>
                  <TableCell numeric className="text-xs">
                    {c.min !== undefined ? String(c.min).slice(0, 16) : "—"}
                  </TableCell>
                  <TableCell numeric className="text-xs">
                    {c.max !== undefined ? String(c.max).slice(0, 16) : "—"}
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-xs text-text-muted">
                    {c.sample_values?.slice(0, 4).join(", ") ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <div className="mt-6 flex justify-end">
            <Button onClick={() => setStep(4)}>
              Continue to mapping
              <ArrowRight aria-hidden />
            </Button>
          </div>
        </Card>
      )}

      {/* ================================================== STEP 4 — map */}
      {step === 4 && (
        <Card className="p-6">
          <StepTitle
            n={4}
            title="Map fields"
            sub="Decide what each source column becomes in the governed model. Suggestions come from the backend's matcher and are never applied automatically."
          />
          <div className="mb-3 flex items-center gap-3 text-xs text-text-muted">
            <span>
              <strong className="text-text-primary">{mappedCount}</strong> of {mappings.length}{" "}
              columns mapped
            </span>
          </div>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Source field</TableHead>
                <TableHead>Source type</TableHead>
                <TableHead>CreditProbe governed field</TableHead>
                <TableHead>Business definition</TableHead>
                <TableHead>Status</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {mappings.map((m, index) => {
                const column = profile?.columns.find((c) => c.name === m.source_column);
                return (
                  <TableRow key={m.source_column}>
                    <TableCell className="font-mono text-xs text-text-primary">
                      {m.source_column}
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{column?.inferred_type ?? "—"}</Badge>
                    </TableCell>
                    <TableCell>
                      <Input
                        value={m.governed_field ?? ""}
                        disabled={m.status === "ignored"}
                        list="governed-fields"
                        onChange={(e) => {
                          const next = [...mappings];
                          next[index] = { ...m, governed_field: e.target.value };
                          setMappings(next);
                        }}
                        className="h-8 font-mono text-xs"
                      />
                      {m.confidence !== null && m.status === "unmapped" && (
                        <p className="mt-1 text-[10px] text-text-muted">
                          Suggested · confidence {(m.confidence * 100).toFixed(0)}%
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="max-w-xs text-xs text-text-muted">
                      {column?.is_categorical
                        ? `Categorical, ${column.unique_count} values`
                        : column?.inferred_type === "number"
                          ? "Numeric measure"
                          : "—"}
                    </TableCell>
                    <TableCell>
                      <Select
                        value={m.status}
                        onChange={(e) => {
                          const next = [...mappings];
                          next[index] = { ...m, status: e.target.value as MappingStatus };
                          setMappings(next);
                        }}
                        className="h-8 text-xs"
                      >
                        <option value="mapped">Mapped</option>
                        <option value="unmapped">Unmapped</option>
                        <option value="ignored">Ignored</option>
                        <option value="proposed">Create new governed field</option>
                      </Select>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
          <datalist id="governed-fields">
            {governedFieldOptions.map((f) => (
              <option key={f} value={f} />
            ))}
          </datalist>
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(3)}>
              <ArrowLeft aria-hidden />
              Back
            </Button>
            <Button onClick={saveMappings} disabled={busy || mappedCount === 0}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
              Save mapping and continue
            </Button>
          </div>
        </Card>
      )}

      {/* =========================================== STEP 5 — dictionary */}
      {step === 5 && (
        <Card className="p-6">
          <StepTitle
            n={5}
            title="Data dictionary"
            sub="Define what each governed field means. This is the single definition the engine, Explain and every screen will use."
          />
          <div className="space-y-3">
            {fields.map((f, index) => (
              <div key={f.name} className="rounded-lg border border-border p-4">
                <div className="mb-3 flex items-center gap-2">
                  <code className="rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-xs text-text-primary">
                    {f.name}
                  </code>
                  <span className="text-xs text-text-muted">from {f.source_field || "—"}</span>
                </div>
                <div className="grid gap-3 md:grid-cols-4">
                  <Field label="Business name">
                    <Input
                      value={f.business_name}
                      onChange={(e) => {
                        const next = [...fields];
                        next[index] = { ...f, business_name: e.target.value };
                        setFields(next);
                      }}
                      className="h-8 text-xs"
                    />
                  </Field>
                  <Field label="Type">
                    <Select
                      value={f.data_type}
                      onChange={(e) => {
                        const next = [...fields];
                        next[index] = { ...f, data_type: e.target.value };
                        setFields(next);
                      }}
                      className="h-8 text-xs"
                    >
                      {["string", "number", "integer", "boolean", "date"].map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Unit">
                    <Input
                      value={f.unit ?? ""}
                      placeholder="USD mn, %, days"
                      onChange={(e) => {
                        const next = [...fields];
                        next[index] = { ...f, unit: e.target.value || null };
                        setFields(next);
                      }}
                      className="h-8 text-xs"
                    />
                  </Field>
                  <Field label="Sensitivity">
                    <Select
                      value={f.sensitivity}
                      onChange={(e) => {
                        const next = [...fields];
                        next[index] = { ...f, sensitivity: e.target.value };
                        setFields(next);
                      }}
                      className="h-8 text-xs"
                    >
                      {["public", "internal", "confidential", "restricted"].map((s) => (
                        <option key={s}>{s}</option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Definition" className="md:col-span-4">
                    <Input
                      value={f.definition}
                      onChange={(e) => {
                        const next = [...fields];
                        next[index] = { ...f, definition: e.target.value };
                        setFields(next);
                      }}
                      className="h-8 text-xs"
                    />
                  </Field>
                </div>
              </div>
            ))}
          </div>
          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(4)}>
              <ArrowLeft aria-hidden />
              Back
            </Button>
            <Button onClick={saveDictionary} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
              Save dictionary and continue
            </Button>
          </div>
        </Card>
      )}

      {/* ======================================== STEP 6 — relationships */}
      {step === 6 && (
        <Card className="p-6">
          <StepTitle
            n={6}
            title="Relationships"
            sub="Record how this dataset joins to others. A relationship is checked at validation, so a broken key is found before publication rather than during an analysis."
          />
          <div className="rounded-lg border border-border bg-surface-sunken p-4">
            <div className="grid items-end gap-3 md:grid-cols-[1fr_auto_1fr_1fr_auto]">
              <Field label={`${name}.field`}>
                <Select
                  value={relFromField}
                  onChange={(e) => setRelFromField(e.target.value)}
                  className="h-9 font-mono text-xs"
                >
                  <option value="">Select a field…</option>
                  {fields.map((f) => (
                    <option key={f.name} value={f.name}>
                      {f.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <ArrowRight className="mb-2 size-4 text-text-muted" aria-hidden />
              <Field label="Target dataset">
                <Select
                  value={relToDataset}
                  onChange={(e) => setRelToDataset(e.target.value)}
                  className="h-9 font-mono text-xs"
                >
                  {(existingDatasets.data?.datasets ?? []).map((d) => (
                    <option key={d.name} value={d.name}>
                      {d.name}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Target field">
                <Input
                  value={relToField}
                  onChange={(e) => setRelToField(e.target.value)}
                  className="h-9 font-mono text-xs"
                />
              </Field>
              <Button
                variant="outline"
                onClick={addRelationship}
                disabled={busy || !relFromField || !relToField}
              >
                Add
              </Button>
            </div>
          </div>

          {addedRelationships.length > 0 && (
            <ul className="mt-4 space-y-1.5">
              {addedRelationships.map((r) => (
                <li key={r} className="flex items-center gap-2 font-mono text-xs text-text-secondary">
                  <CheckCircle2 className="size-3.5 text-positive" aria-hidden />
                  {r}
                </li>
              ))}
            </ul>
          )}

          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(5)}>
              <ArrowLeft aria-hidden />
              Back
            </Button>
            <Button onClick={validate} disabled={busy}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <ArrowRight aria-hidden />}
              Run validation
            </Button>
          </div>
        </Card>
      )}

      {/* ============================================= STEP 7 — validate */}
      {step === 7 && report && (
        <Card className="p-6">
          <StepTitle
            n={7}
            title="Validate"
            sub={`${report.row_count.toLocaleString()} rows and ${report.field_count} governed fields checked.`}
          />
          <div className="mb-4 grid gap-3 sm:grid-cols-3">
            <ResultTile
              tone={report.passed ? "positive" : "muted"}
              label="Checks passed"
              value={report.passed ? "All" : `${8 - report.findings.length} of 8`}
            />
            <ResultTile tone="warning" label="Warnings" value={String(report.warning_count)} />
            <ResultTile tone="negative" label="Blocking errors" value={String(report.error_count)} />
          </div>

          {report.findings.length === 0 ? (
            <div className="flex items-center gap-2 rounded-md border border-positive/30 bg-positive-muted px-4 py-3 text-sm text-positive">
              <CheckCircle2 className="size-4" aria-hidden />
              Every quality check passed. This dataset is ready to publish.
            </div>
          ) : (
            <ul className="space-y-2">
              {report.findings.map((f, i) => (
                <li
                  key={i}
                  className={cn(
                    "flex items-start gap-2.5 rounded-md border px-4 py-3 text-sm",
                    f.severity === "error"
                      ? "border-negative/30 bg-negative-muted text-negative"
                      : "border-warning/30 bg-warning-muted text-warning",
                  )}
                >
                  {f.severity === "error" ? (
                    <AlertTriangle className="mt-0.5 size-4 shrink-0" aria-hidden />
                  ) : (
                    <TriangleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  )}
                  <div>
                    <p className="font-medium">{f.rule.replace(/_/g, " ")}</p>
                    <p className="text-xs opacity-90">{f.detail}</p>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-6 flex justify-between">
            <Button variant="ghost" onClick={() => setStep(6)}>
              <ArrowLeft aria-hidden />
              Back
            </Button>
            <Button onClick={publish} disabled={busy || !report.passed}>
              {busy ? <Loader2 className="animate-spin" aria-hidden /> : <Rocket aria-hidden />}
              {report.passed ? "Publish dataset" : "Fix the errors to publish"}
            </Button>
          </div>
        </Card>
      )}

      {/* ============================================== STEP 8 — published */}
      {step === 8 && published && (
        <Card className="p-8 text-center">
          <CheckCircle2 className="mx-auto size-10 text-positive" aria-hidden />
          <h2 className="mt-4 text-lg font-semibold text-text-primary">
            {name} v{published.version} is published
          </h2>
          <p className="mx-auto mt-2 max-w-lg text-sm text-text-secondary">
            The curated and analytical Parquet has been written and an immutable version
            recorded. The raw upload is unchanged.
          </p>
          <div className="mx-auto mt-5 inline-flex items-center gap-2 rounded-full border border-positive/30 bg-positive-muted px-4 py-1.5 text-sm font-medium text-positive">
            <CheckCircle2 className="size-4" aria-hidden />
            Available to CreditProbe Engine
          </div>
          {published.periods.length > 0 && (
            <p className="mt-4 text-xs text-text-muted">
              Partitioned by reporting period: {published.periods.join(", ")}
            </p>
          )}
          <div className="mt-6 flex justify-center gap-2">
            <Button variant="outline" asChild>
              <Link href={domainHref(domain)}>Open domain</Link>
            </Button>
            <Button onClick={() => router.push("/data-builder")}>Done</Button>
          </div>
        </Card>
      )}
    </div>
  );
}

function BackLink() {
  return (
    <Button variant="ghost" size="sm" asChild className="-ml-2">
      <Link href="/data-builder">
        <ArrowLeft aria-hidden />
        Data Builder
      </Link>
    </Button>
  );
}

function Stepper({ current, onJump }: { current: number; onJump: (step: number) => void }) {
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-2">
      {STEPS.map((s, i) => {
        const done = current > s.id;
        const active = current === s.id;
        return (
          <li key={s.id} className="flex items-center">
            <button
              type="button"
              onClick={() => onJump(s.id)}
              disabled={!done}
              className={cn(
                "flex items-center gap-2 rounded-full px-3 py-1.5 text-xs transition-colors",
                active && "bg-accent text-accent-contrast font-medium",
                done && "text-text-secondary hover:bg-surface-hover",
                !active && !done && "text-text-muted",
              )}
            >
              <span
                className={cn(
                  "flex size-4 shrink-0 items-center justify-center rounded-full text-[10px] font-semibold",
                  active && "bg-accent-contrast text-accent",
                  done && "bg-positive text-white",
                  !active && !done && "border border-border-strong",
                )}
              >
                {done ? <Check className="size-2.5" aria-hidden /> : s.id}
              </span>
              <span className="hidden sm:inline">{s.label}</span>
            </button>
            {i < STEPS.length - 1 && (
              <span className="mx-0.5 h-px w-3 bg-border" aria-hidden />
            )}
          </li>
        );
      })}
    </ol>
  );
}

function StepTitle({ n, title, sub }: { n: number; title: string; sub: string }) {
  return (
    <div className="mb-5">
      <p className="text-[11px] font-medium uppercase tracking-wider text-text-muted">Step {n}</p>
      <h2 className="mt-0.5 text-base font-semibold text-text-primary">{title}</h2>
      <p className="mt-1 max-w-3xl text-sm text-text-secondary">{sub}</p>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border bg-surface-sunken px-4 py-2">
      <p className="text-[11px] uppercase tracking-wider text-text-muted">{label}</p>
      <p className="text-sm font-medium text-text-primary">{value}</p>
    </div>
  );
}

function ResultTile({
  tone,
  label,
  value,
}: {
  tone: "positive" | "warning" | "negative" | "muted";
  label: string;
  value: string;
}) {
  return (
    <div
      className={cn(
        "rounded-lg border p-4",
        tone === "positive" && "border-positive/30 bg-positive-muted",
        tone === "warning" && "border-warning/30 bg-warning-muted",
        tone === "negative" && "border-negative/30 bg-negative-muted",
        tone === "muted" && "border-border bg-surface-sunken",
      )}
    >
      <p className="text-[11px] uppercase tracking-wider opacity-80">{label}</p>
      <p
        className={cn(
          "mt-1 text-xl font-semibold tabular",
          tone === "positive" && "text-positive",
          tone === "warning" && "text-warning",
          tone === "negative" && "text-negative",
          tone === "muted" && "text-text-primary",
        )}
      >
        {value}
      </p>
    </div>
  );
}

export { FileSpreadsheet };
