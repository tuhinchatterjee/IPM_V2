"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/**
 * The form behind every governance act that needs words from a person.
 *
 * Recording a decision, answering a finding, closing one, assigning an owner,
 * updating an action — each needs something written down, and each records
 * who wrote it. One component, because the fields differ but the discipline
 * does not: **nothing is submitted without the text the act requires**, and
 * the button stays disabled until it is there.
 *
 * The actor is not a field. It is the signed-in caller, taken from the
 * request by the server; a form that let somebody type a name would be a form
 * that let them type somebody else's.
 */
export interface GovernField {
  name: string;
  label: string;
  placeholder?: string;
  multiline?: boolean;
  required?: boolean;
  options?: { value: string; label: string }[];
  value?: string;
}

export function GovernDialog({
  open,
  title,
  description,
  note,
  fields,
  submitLabel,
  busy,
  error,
  onSubmit,
  onClose,
}: {
  open: boolean;
  title: string;
  description?: string;
  note?: string;
  fields: GovernField[];
  submitLabel: string;
  busy: boolean;
  error: string;
  onSubmit: (values: Record<string, string>) => void;
  onClose: () => void;
}) {
  // Initialised once, from the fields this dialog was opened with. The caller
  // mounts a fresh dialog for each act, so there is nothing to synchronise
  // afterwards — and synchronising in an effect would reset the form under
  // the user's fingers every time the parent re-rendered.
  const [values, setValues] = React.useState<Record<string, string>>(() => {
    const initial: Record<string, string> = {};
    for (const field of fields) {
      initial[field.name] = field.value ?? field.options?.[0]?.value ?? "";
    }
    return initial;
  });

  const missing = fields.some(
    (f) => f.required && !(values[f.name] ?? "").trim(),
  );

  return (
    <Dialog open={open} onClose={onClose} title={title}
      description={description} size="md">
      <form
        className="space-y-3"
        data-testid="playbook-govern-dialog"
        onSubmit={(e) => {
          e.preventDefault();
          if (!missing && !busy) onSubmit(values);
        }}
      >
        {fields.map((field) => (
          <label key={field.name} className="block">
            <span className="text-[11px] font-medium text-text-secondary">
              {field.label}
              {field.required && <span className="text-negative"> *</span>}
            </span>
            {field.options ? (
              <select
                value={values[field.name] ?? ""}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                data-testid={`playbook-govern-${field.name}`}
                className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              >
                {field.options.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : field.multiline ? (
              <textarea
                rows={4}
                value={values[field.name] ?? ""}
                placeholder={field.placeholder}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                data-testid={`playbook-govern-${field.name}`}
                className="mt-1 w-full rounded-md border border-border bg-surface px-2 py-1.5 text-sm text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
              />
            ) : (
              <Input
                value={values[field.name] ?? ""}
                placeholder={field.placeholder}
                onChange={(e) =>
                  setValues((v) => ({ ...v, [field.name]: e.target.value }))}
                data-testid={`playbook-govern-${field.name}`}
                className="mt-1"
              />
            )}
          </label>
        ))}

        {note && (
          <p className="rounded-md border border-border bg-surface-sunken p-2 text-[11px] leading-relaxed text-text-muted">
            {note}
          </p>
        )}

        {error && (
          <p className="rounded-md border border-negative/40 bg-negative-muted p-2 text-[11px] text-negative"
            data-testid="playbook-govern-error">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-1">
          <Button type="button" variant="ghost" size="sm" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" size="sm" disabled={missing || busy}
            data-testid="playbook-govern-submit">
            {busy ? "Recording…" : submitLabel}
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
