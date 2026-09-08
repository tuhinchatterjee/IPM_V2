"use client";

import * as React from "react";
import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
  Code2,
  Loader2,
  Lock,
  Pencil,
  Sparkles,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  api,
  type CodeDivergence,
  type CodeValidation,
  type FormulaDraft,
  type FormulaIntake,
  type FormulaPreview,
  type MetricCode,
} from "@/lib/api";

/**
 * Writing a metric by typing the formula for it. §4–§13.
 *
 * The sequence on screen is the sequence §57 says the tranche is done only
 * when it works:
 *
 *   type      — the formula, in notation, in words, or in both
 *   flag      — where it reads unconventionally: keep, conventional, or edit
 *   code      — what CreditProbe will compute, and the code that computes it
 *   approve   — a person reads the code and says so
 *   preview   — run it on the real book and show the exact arithmetic
 *   lock      — persist it as a governed metric
 *
 * Three things this screen does that a code box would not
 * --------------------------------------------------------
 * **It says who wrote the code.** A definition written by a model and one
 * assembled by CreditProbe's own reader are different things, and the second
 * happens whenever no AI provider is configured. The badge says which, and
 * where CreditProbe wrote both the program and the SQL it says that the
 * reconciliation check between them proves less.
 *
 * **The approval is bound to what was approved.** The checksum comes back from
 * `approve` and goes into `preview` and `lock`. Editing anything after
 * approving clears it, so the button says "Approve" again rather than
 * silently locking something nobody read.
 *
 * **A refusal is shown, not swallowed.** A definition CreditProbe will not run
 * still renders, with every failure and — where the failure is a missing field
 * — the fields that DO exist. §10 asks a person to review the code; a person
 * cannot review an error toast.
 */

type Stage = "typing" | "flagged" | "code" | "preview" | "locked";

export function FormulaBuilder({
  period = "",
  lensId,
  onLocked,
  onCancel,
}: {
  period?: string;
  lensId?: number;
  /** Called with the new metric's id once it is locked and on the Lens. */
  onLocked: (metric: { metric_id: string; name: string }) => void;
  onCancel?: () => void;
}) {
  const [said, setSaid] = React.useState("");
  const [stage, setStage] = React.useState<Stage>("typing");
  const [intake, setIntake] = React.useState<FormulaIntake | null>(null);
  const [code, setCode] = React.useState<MetricCode | null>(null);
  const [original, setOriginal] = React.useState<MetricCode | null>(null);
  const [validation, setValidation] = React.useState<CodeValidation | null>(null);
  const [divergence, setDivergence] = React.useState<CodeDivergence | null>(null);
  const [preview, setPreview] = React.useState<FormulaPreview | null>(null);
  const [checksum, setChecksum] = React.useState("");
  const [note, setNote] = React.useState("");
  const [busy, setBusy] = React.useState("");
  const [error, setError] = React.useState("");
  const [editing, setEditing] = React.useState(false);
  const [editedSql, setEditedSql] = React.useState("");

  const ready = Boolean(validation?.ok);

  function fail(e: unknown) {
    setError(e instanceof Error ? e.message : String(e));
  }

  function took(body: FormulaDraft) {
    setIntake(body.intake);
    setCode(body.code);
    setOriginal(body.code);
    setValidation(body.validation);
    setChecksum("");
    setPreview(null);
    setDivergence(null);
    setStage("code");
  }

  /** §5. Read first, so an unconventional formula is flagged BEFORE any code
   *  is written for it — writing code and then asking is asking about a
   *  decision already made. */
  async function read() {
    if (!said.trim() || busy) return;
    setBusy("read");
    setError("");
    try {
      const body = await api.readFormula(said.trim(), period);
      setIntake(body);
      if (body.unconventional) {
        setStage("flagged");
        return;
      }
      took(await api.draftFormula(said.trim(), { period, lensId }));
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  async function draft(keepFormula = "") {
    setBusy("draft");
    setError("");
    try {
      took(await api.draftFormula(said.trim(), { period, lensId, keepFormula }));
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  /** §11. An edit goes through the whole validator again, and its meaning is
   *  compared with what it replaced. */
  async function revise() {
    if (!code || busy) return;
    setBusy("revise");
    setError("");
    try {
      const body = await api.reviseFormula(
        { ...code, sql: editedSql },
        { period, previous: original ?? undefined, edited: true },
      );
      setCode(body.code);
      setValidation(body.validation);
      setDivergence(body.divergence ?? null);
      setChecksum("");
      setPreview(null);
      setEditing(false);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  async function approveAndPreview() {
    if (!code || busy) return;
    setBusy("approve");
    setError("");
    try {
      const approved = await api.approveFormula(code, note, period);
      if (!approved.approved) {
        setValidation(approved.validation);
        setCode(approved.code);
        setError(approved.why ?? "CreditProbe will not run this code.");
        return;
      }
      const shown = await api.previewFormula(
        approved.code,
        approved.checksum ?? "",
        period,
      );
      setCode(shown.code);
      setValidation(shown.validation);
      setPreview(shown.preview);
      setChecksum(shown.checksum ?? approved.checksum ?? "");
      setStage("preview");
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  async function lock() {
    if (!code || busy) return;
    setBusy("lock");
    setError("");
    try {
      const body = await api.lockFormula(code, checksum, period);
      if (!body.locked) {
        setValidation(body.validation);
        setError(body.why ?? "CreditProbe would not store this metric.");
        return;
      }
      setStage("locked");
      onLocked({ metric_id: body.metric_id ?? "", name: code.name });
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  }

  // ---------------------------------------------------------------- render

  return (
    <Card className="space-y-4 p-5" data-testid="formula-builder">
      <header className="flex items-center gap-2">
        <Sparkles className="size-4 text-accent" aria-hidden />
        <h3 className="text-sm font-semibold text-text-primary">
          Write a metric by typing its formula
        </h3>
      </header>

      {stage === "typing" && (
        <div className="space-y-2">
          <label
            className="block text-xs text-text-secondary"
            htmlFor="formula-said"
          >
            Type the formula. Notation, business language, or both — for
            example{" "}
            <span className="font-mono text-[11px] text-text-primary">
              (Current Quarter Exposure / Previous Quarter Exposure) - 1
            </span>
          </label>
          <textarea
            id="formula-said"
            data-testid="formula-input"
            className="min-h-20 w-full rounded border border-border bg-surface px-3 py-2 font-mono text-xs text-text-primary"
            value={said}
            onChange={(e) => setSaid(e.target.value)}
            placeholder="Add quarter-on-quarter exposure change: (Current Quarter Exposure / Previous Quarter Exposure) - 1"
          />
          <div className="flex gap-2">
            <Button
              data-testid="formula-write-code"
              onClick={read}
              disabled={!said.trim() || Boolean(busy)}
            >
              {busy ? (
                <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />
              ) : (
                <Code2 className="mr-1.5 size-3.5" aria-hidden />
              )}
              Write the code
            </Button>
            {onCancel && (
              <Button variant="ghost" onClick={onCancel}>
                Cancel
              </Button>
            )}
          </div>
        </div>
      )}

      {/* §5 and §34. Flagged, offered, and nothing applied. */}
      {stage === "flagged" && intake?.unconventional && (
        <div
          className="space-y-3 rounded border border-warning/40 bg-warning/5 p-4"
          data-testid="unconventional-warning"
        >
          <p className="flex items-start gap-2 text-xs text-text-primary">
            <AlertTriangle
              className="mt-0.5 size-3.5 shrink-0 text-warning"
              aria-hidden
            />
            <span>{intake.unconventional.because}</span>
          </p>
          <dl className="grid gap-1 text-[11px]">
            <div className="flex gap-2">
              <dt className="w-28 text-text-muted">You wrote</dt>
              <dd
                className="font-mono text-text-primary"
                data-testid="your-formula"
              >
                {intake.formula}
              </dd>
            </div>
            <div className="flex gap-2">
              <dt className="w-28 text-text-muted">
                {intake.unconventional.convention_name}
              </dt>
              <dd className="font-mono text-text-secondary">
                {intake.unconventional.conventional}
              </dd>
            </div>
          </dl>
          <div className="flex flex-wrap gap-2">
            <Button
              data-testid="keep-my-formula"
              onClick={() => draft(intake.formula)}
              disabled={Boolean(busy)}
            >
              Keep My Formula
            </Button>
            <Button
              variant="outline"
              data-testid="use-conventional-formula"
              onClick={() => draft(intake.unconventional!.conventional)}
              disabled={Boolean(busy)}
            >
              Use Conventional Formula
            </Button>
            <Button
              variant="ghost"
              data-testid="edit-formula"
              onClick={() => setStage("typing")}
              disabled={Boolean(busy)}
            >
              Edit Formula
            </Button>
          </div>
        </div>
      )}

      {(stage === "code" || stage === "preview" || stage === "locked") &&
        code && (
          <DefinitionCard
            code={code}
            validation={validation}
            divergence={divergence}
            preview={preview}
            stage={stage}
            editing={editing}
            editedSql={editedSql}
            onEdit={() => {
              setEditedSql(code.sql);
              setEditing(true);
            }}
            onEditedSql={setEditedSql}
            onRevise={revise}
            onCancelEdit={() => setEditing(false)}
            busy={busy}
          />
        )}

      {stage === "code" && code && (
        <div className="space-y-2">
          <input
            aria-label="What you checked before approving"
            data-testid="approval-note"
            className="w-full rounded border border-border bg-surface px-3 py-1.5 text-xs"
            placeholder="Optional: what you checked before approving"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <div className="flex flex-wrap gap-2">
            <Button
              data-testid="approve-and-preview"
              onClick={approveAndPreview}
              disabled={!ready || Boolean(busy)}
            >
              {busy === "approve" ? (
                <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />
              ) : (
                <Check className="mr-1.5 size-3.5" aria-hidden />
              )}
              Approve Code &amp; Preview
            </Button>
            <Button
              variant="outline"
              data-testid="edit-the-formula"
              onClick={() => setStage("typing")}
              disabled={Boolean(busy)}
            >
              Edit Formula
            </Button>
            <Button
              variant="outline"
              data-testid="ask-to-revise"
              onClick={() => draft()}
              disabled={Boolean(busy)}
            >
              Ask CreditProbe to Revise
            </Button>
          </div>
          {!ready && (
            <p className="text-[11px] text-text-muted">
              CreditProbe will not run this definition, so there is nothing to
              approve yet. Each refusal above says what would fix it.
            </p>
          )}
        </div>
      )}

      {stage === "preview" && preview && (
        <div className="flex flex-wrap gap-2">
          <Button
            data-testid="lock-metric"
            onClick={lock}
            disabled={!preview.available || Boolean(busy)}
          >
            {busy === "lock" ? (
              <Loader2 className="mr-1.5 size-3.5 animate-spin" aria-hidden />
            ) : (
              <Lock className="mr-1.5 size-3.5" aria-hidden />
            )}
            Lock Metric
          </Button>
          <Button
            variant="outline"
            data-testid="edit-again"
            onClick={() => {
              setStage("code");
              setChecksum("");
              setPreview(null);
            }}
            disabled={Boolean(busy)}
          >
            Edit Again
          </Button>
        </div>
      )}

      {stage === "locked" && code && (
        <p
          className="flex items-center gap-1.5 text-xs text-positive"
          data-testid="metric-locked"
        >
          <Lock className="size-3.5" aria-hidden />
          {code.name} is locked and on this Lens.
        </p>
      )}

      {error && (
        <p className="text-xs text-negative" data-testid="formula-error">
          {error}
        </p>
      )}
    </Card>
  );
}

/** §6 and §10: everything a person needs in order to approve the code. */
function DefinitionCard({
  code,
  validation,
  divergence,
  preview,
  stage,
  editing,
  editedSql,
  onEdit,
  onEditedSql,
  onRevise,
  onCancelEdit,
  busy,
}: {
  code: MetricCode;
  validation: CodeValidation | null;
  divergence: CodeDivergence | null;
  preview: FormulaPreview | null;
  stage: Stage;
  editing: boolean;
  editedSql: string;
  onEdit: () => void;
  onEditedSql: (value: string) => void;
  onRevise: () => void;
  onCancelEdit: () => void;
  busy: string;
}) {
  const [showCompiled, setShowCompiled] = React.useState(false);
  const ok = Boolean(validation?.ok);

  return (
    <div className="space-y-3" data-testid="metric-definition-card">
      <div className="flex flex-wrap items-center gap-2">
        <h4
          className="text-sm font-semibold text-text-primary"
          data-testid="metric-name"
        >
          {code.name}
        </h4>
        <Badge variant={ok ? "positive" : "negative"} data-testid="code-stage">
          {ok ? "Validated by CreditProbe" : "Rejected by CreditProbe"}
        </Badge>
        <Badge variant="outline" data-testid="code-author">
          {code.author_label}
        </Badge>
        {code.domains.map((d) => (
          <Badge key={d} variant="outline" data-testid={`domain-${d}`}>
            {d === "ews" ? "Early Warning" : "Cockpit"}
          </Badge>
        ))}
      </div>

      <Field label="Your formula">
        <span className="font-mono" data-testid="user-formula">
          {code.user_formula}
        </span>
      </Field>
      <Field label="Interpreted formula">
        <span className="font-mono" data-testid="interpreted-formula">
          {code.interpreted_formula}
        </span>
      </Field>

      {code.plain_english.length > 0 && (
        <div>
          <p className="text-[10px] uppercase tracking-wide text-text-muted">
            Plain English
          </p>
          <ol
            className="mt-1 list-decimal space-y-0.5 pl-5 text-xs text-text-secondary"
            data-testid="plain-english"
          >
            {code.plain_english.map((step, i) => (
              <li key={i}>{step}</li>
            ))}
          </ol>
        </div>
      )}

      <div>
        <div className="flex items-center justify-between">
          <p className="text-[10px] uppercase tracking-wide text-text-muted">
            {code.language === "python" ? "Python" : "SQL"}
          </p>
          {stage === "code" && !editing && (
            <Button
              variant="ghost"
              size="sm"
              data-testid="advanced-edit-code"
              onClick={onEdit}
            >
              <Pencil className="mr-1 size-3" aria-hidden />
              Advanced: Edit Code
            </Button>
          )}
        </div>
        {editing ? (
          <div className="space-y-2">
            <textarea
              aria-label="Edit the generated code"
              data-testid="code-editor"
              className="min-h-40 w-full rounded border border-border bg-surface p-2 font-mono text-[11px] text-text-primary"
              value={editedSql}
              onChange={(e) => onEditedSql(e.target.value)}
            />
            <div className="flex gap-2">
              <Button
                size="sm"
                data-testid="revalidate-code"
                onClick={onRevise}
                disabled={Boolean(busy)}
              >
                Check my code
              </Button>
              <Button size="sm" variant="ghost" onClick={onCancelEdit}>
                Cancel
              </Button>
            </div>
            <p className="text-[11px] text-text-muted">
              Edited code goes through the same checks. Nothing is trusted for
              having come from this screen.
            </p>
          </div>
        ) : (
          <pre
            className="mt-1 overflow-x-auto rounded border border-border bg-surface-sunken p-2 font-mono text-[11px] leading-relaxed text-text-primary"
            data-testid="generated-sql"
          >
            {code.language === "python" ? code.python : code.sql}
          </pre>
        )}
      </div>

      {code.compiled_sql && (
        <div>
          <button
            type="button"
            className="flex items-center gap-1 text-[11px] text-text-muted hover:text-text-secondary"
            onClick={() => setShowCompiled((v) => !v)}
            data-testid="toggle-compiled-sql"
          >
            {showCompiled ? (
              <ChevronDown className="size-3" aria-hidden />
            ) : (
              <ChevronRight className="size-3" aria-hidden />
            )}
            The statement CreditProbe will run
          </button>
          {showCompiled && (
            <pre
              className="mt-1 overflow-x-auto rounded border border-border bg-surface-sunken p-2 font-mono text-[10px] leading-relaxed text-text-muted"
              data-testid="compiled-sql"
            >
              {code.compiled_sql}
            </pre>
          )}
          {!code.independently_written && (
            <p className="mt-1 text-[11px] text-text-muted">
              CreditProbe wrote both the calculation and the SQL above, because
              no AI provider is configured — so the check that they agree
              proves less here than it would if a model had written them
              separately.
            </p>
          )}
        </div>
      )}

      <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
        <Pair label="Dataset(s)" value={code.datasets.join(", ")} testId="code-datasets" />
        <Pair label="Fields" value={code.fields.join(", ")} />
        <Pair label="Grain" value={code.grain} testId="code-grain" />
        <Pair label="Output grain" value={code.output_grain} />
        <Pair label="Period logic" value={code.period_logic} />
        <Pair label="Aggregation" value={code.aggregation} />
        <Pair label="Unit" value={code.unit} />
        {code.filters.length > 0 && (
          <Pair label="Filters" value={code.filters.join("; ")} />
        )}
        {code.join_logic && <Pair label="Join logic" value={code.join_logic} />}
      </dl>

      {code.why && (
        <p className="text-xs text-text-secondary" data-testid="why-useful">
          {code.why}
        </p>
      )}

      {/* §8 and §9: refusals, with what would fix each one. */}
      {validation && validation.failures.length > 0 && (
        <ul className="space-y-2" data-testid="code-failures">
          {validation.failures.map((failure, i) => (
            <li
              key={i}
              className="rounded border border-negative/40 bg-negative/5 p-2 text-[11px]"
            >
              <p className="font-medium text-negative">{failure.label}</p>
              <p className="text-text-secondary">{failure.message}</p>
              {failure.hints.related_fields &&
                failure.hints.related_fields.length > 0 && (
                  <p className="mt-1 text-text-muted">
                    Fields that do exist:{" "}
                    <span className="font-mono">
                      {failure.hints.related_fields.join(", ")}
                    </span>
                  </p>
                )}
              {failure.hints.periods && failure.hints.periods.length > 0 && (
                <p className="mt-1 text-text-muted">
                  Periods this book has:{" "}
                  {(failure.hints.periods as string[]).slice(-6).join(", ")}
                </p>
              )}
            </li>
          ))}
        </ul>
      )}

      {validation && validation.warnings.length > 0 && (
        <ul className="space-y-1 text-[11px] text-warning" data-testid="code-warnings">
          {validation.warnings.map((w, i) => (
            <li key={i}>{w.message}</li>
          ))}
        </ul>
      )}

      {/* §11: what an edit changed about the metric's meaning. */}
      {divergence?.changed && (
        <div
          className="rounded border border-warning/40 bg-warning/5 p-2 text-[11px]"
          data-testid="code-divergence"
        >
          <p className="font-medium text-warning">{divergence.note}</p>
          <ul className="mt-1 list-disc space-y-0.5 pl-4 text-text-secondary">
            {divergence.changes.map((change, i) => (
              <li key={i}>{change}</li>
            ))}
          </ul>
        </div>
      )}

      {preview && <PreviewPanel preview={preview} />}
    </div>
  );
}

/** §12. The exact calculation, with both sides and both periods. */
function PreviewPanel({ preview }: { preview: FormulaPreview }) {
  if (!preview.available) {
    return (
      <p className="text-xs text-negative" data-testid="preview-unavailable">
        {preview.unavailable || "This produced no figure."}
      </p>
    );
  }
  return (
    <div
      className="space-y-2 rounded border border-accent/30 bg-accent/5 p-3"
      data-testid="metric-preview"
    >
      <div className="flex items-baseline gap-3">
        <span
          className="text-xl font-semibold text-text-primary"
          data-testid="preview-value"
        >
          {preview.formatted}
        </span>
        <span className="text-[11px] text-text-muted">{preview.period}</span>
      </div>
      <dl className="grid gap-1 text-[11px]">
        {preview.numerator?.label && (
          <div className="flex gap-2">
            <dt className="w-44 text-text-muted">
              {preview.numerator.label}
              {preview.numerator.period ? ` · ${preview.numerator.period}` : ""}
            </dt>
            <dd className="font-mono text-text-primary" data-testid="preview-numerator">
              {formatNumber(preview.numerator.value)}
            </dd>
          </div>
        )}
        {preview.denominator?.label && (
          <div className="flex gap-2">
            <dt className="w-44 text-text-muted">
              {preview.denominator.label}
              {preview.denominator.period
                ? ` · ${preview.denominator.period}`
                : ""}
            </dt>
            <dd
              className="font-mono text-text-primary"
              data-testid="preview-denominator"
            >
              {formatNumber(preview.denominator.value)}
            </dd>
          </div>
        )}
      </dl>
      <p className="font-mono text-xs text-text-primary" data-testid="preview-final">
        {preview.final}
      </p>
      <dl className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-[10px] text-text-muted">
        <Pair label="Population" value={`${preview.rows_considered.toLocaleString()} rows`} />
        <Pair label="Dataset(s)" value={preview.datasets.join(", ")} />
        <Pair label="Data version" value={preview.data_version} />
        <Pair label="Code version" value={preview.code_version} />
        {preview.filters.length > 0 && (
          <Pair label="Filters" value={preview.filters.join("; ")} />
        )}
        {preview.join_logic && <Pair label="Join" value={preview.join_logic} />}
      </dl>
      {preview.warnings.length > 0 && (
        <ul className="space-y-0.5 text-[11px] text-warning">
          {preview.warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      )}
    </div>
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
    <div>
      <p className="text-[10px] uppercase tracking-wide text-text-muted">
        {label}
      </p>
      <p className="text-xs text-text-primary">{children}</p>
    </div>
  );
}

function Pair({
  label,
  value,
  testId,
}: {
  label: string;
  value: string;
  testId?: string;
}) {
  if (!value) return null;
  return (
    <div className="flex gap-2">
      <dt className="shrink-0 text-text-muted">{label}</dt>
      <dd className="text-text-secondary" data-testid={testId}>
        {value}
      </dd>
    </div>
  );
}

/**
 * One side of the preview, at the precision the calculation was traced at.
 *
 * A deliberate mirror of `_fmt` in `backend/metrics/execution.py`, which is
 * what writes the sentence directly underneath these two rows:
 *
 *     Current Quarter Exposure · Q2 2026     74,017.555
 *     Previous Quarter Exposure · Q1 2026    74,352.67
 *     (74,017.555 / 74,352.67) − 1 × 100 = −0.4507
 *
 * The two have to agree character for character or the card contradicts
 * itself, and a person asked to approve arithmetic that does not tie is being
 * asked to approve nothing.
 *
 * This is above the two-decimal display contract, and that is the point of
 * this particular screen rather than an oversight — a tile reports a figure,
 * this card shows the working. `scripts/check_decimals.py` carries the
 * exemption, narrowed to this one function.
 */
function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "—";
  }
  if (Math.abs(value) >= 1_000_000 || Math.abs(value - Math.round(value)) < 1e-9) {
    return value.toLocaleString("en-US", { maximumFractionDigits: 0 });
  }
  return value
    .toLocaleString("en-US", {
      minimumFractionDigits: 4,
      maximumFractionDigits: 4,
    })
    .replace(/0+$/, "")
    .replace(/\.$/, "");
}
