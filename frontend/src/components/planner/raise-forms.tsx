"use client";

import * as React from "react";

import { Button } from "@/components/ui/button";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { api } from "@/lib/api";

/**
 * The two things a person adds to a project mid-flight.
 *
 * Both are deliberately small and both are disclosed rather than always
 * open: a project page that greets a reader with two empty forms above the
 * content it exists to show has its priorities backwards. The button is one
 * click and the form remembers nothing, because these are occasional acts.
 *
 * Raising a risk is CONTRIBUTOR work — noticing a problem is not the same as
 * having authority over the plan, and a product that lets only editors raise
 * risks is one where risks go unraised. Adding a milestone is EDITOR work,
 * because a milestone is a commitment.
 */

function Disclosure({
  label,
  children,
}: {
  label: string;
  children: (close: () => void) => React.ReactNode;
}) {
  const [open, setOpen] = React.useState(false);
  if (!open) {
    return (
      <div className="border-b border-border px-4 py-2">
        <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
          {label}
        </Button>
      </div>
    );
  }
  return (
    <div className="border-b border-border bg-surface-sunken px-4 py-3">
      {children(() => setOpen(false))}
    </div>
  );
}

function Error_({ text }: { text: string | null }) {
  if (!text) return null;
  return <p className="mt-2 text-sm text-negative">{text}</p>;
}

export function RaiseRaid({
  projectId,
  onRaised,
}: {
  projectId: number;
  onRaised: () => void;
}) {
  const [kind, setKind] = React.useState("RISK");
  const [title, setTitle] = React.useState("");
  const [description, setDescription] = React.useState("");
  const [severity, setSeverity] = React.useState("MEDIUM");
  const [mitigation, setMitigation] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <Disclosure label="Raise a risk, issue, assumption or decision">
      {(close) => (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="raid-kind">Type</Label>
              <Select id="raid-kind" value={kind}
                      onChange={(e) => setKind(e.target.value)}>
                <option value="RISK">Risk</option>
                <option value="ISSUE">Issue</option>
                <option value="ASSUMPTION">Assumption</option>
                <option value="DECISION">Decision</option>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="raid-title">Title</Label>
              <Input id="raid-title" value={title}
                     placeholder="Key modeller unavailable from November"
                     onChange={(e) => setTitle(e.target.value)} />
            </div>
          </div>
          <div className="mt-3">
            <Label htmlFor="raid-description">What is the concern</Label>
            <Textarea id="raid-description" rows={2} value={description}
                      onChange={(e) => setDescription(e.target.value)} />
          </div>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <div>
              <Label htmlFor="raid-severity">Severity</Label>
              <Select id="raid-severity" value={severity}
                      onChange={(e) => setSeverity(e.target.value)}>
                <option value="LOW">Low</option>
                <option value="MEDIUM">Medium</option>
                <option value="HIGH">High</option>
                <option value="CRITICAL">Critical</option>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="raid-mitigation">
                {kind === "DECISION" ? "What has to be decided" : "Action"}
              </Label>
              <Input id="raid-mitigation" value={mitigation}
                     onChange={(e) => setMitigation(e.target.value)} />
            </div>
          </div>
          <Error_ text={error} />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={close}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={busy || !title.trim()}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await api.planner.createRaid(projectId, {
                    raid_type: kind,
                    title: title.trim(),
                    description,
                    severity,
                    mitigation,
                  });
                  setTitle("");
                  setDescription("");
                  setMitigation("");
                  close();
                  onRaised();
                } catch (e) {
                  setError(
                    e instanceof Error ? e.message : "That could not be saved.");
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Raising…" : "Raise it"}
            </Button>
          </div>
        </>
      )}
    </Disclosure>
  );
}

export function AddMilestone({
  projectId,
  onAdded,
}: {
  projectId: number;
  onAdded: () => void;
}) {
  const [code, setCode] = React.useState("");
  const [name, setName] = React.useState("");
  const [target, setTarget] = React.useState("");
  const [critical, setCritical] = React.useState(false);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);

  return (
    <Disclosure label="Add a milestone">
      {(close) => (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div>
              <Label htmlFor="ms-code">Code</Label>
              <Input id="ms-code" value={code} placeholder="M-6"
                     onChange={(e) => setCode(e.target.value)} />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="ms-name">Milestone</Label>
              <Input id="ms-name" value={name}
                     placeholder="Model Committee approval"
                     onChange={(e) => setName(e.target.value)} />
            </div>
            <div>
              <Label htmlFor="ms-target">Target date</Label>
              <Input id="ms-target" type="date" value={target}
                     onChange={(e) => setTarget(e.target.value)} />
            </div>
          </div>
          <label className="mt-3 flex items-center gap-2 text-sm text-text-primary">
            <input type="checkbox" checked={critical}
                   onChange={(e) => setCritical(e.target.checked)} />
            On the critical path
          </label>
          <Error_ text={error} />
          <div className="mt-3 flex justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={close}>
              Cancel
            </Button>
            <Button
              size="sm"
              disabled={busy || !name.trim()}
              onClick={async () => {
                setBusy(true);
                setError(null);
                try {
                  await api.planner.createMilestone(projectId, {
                    code: code.trim(),
                    name: name.trim(),
                    target_date: target || null,
                    critical,
                  });
                  setCode("");
                  setName("");
                  setTarget("");
                  setCritical(false);
                  close();
                  onAdded();
                } catch (e) {
                  setError(
                    e instanceof Error ? e.message : "That could not be saved.");
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? "Adding…" : "Add it"}
            </Button>
          </div>
        </>
      )}
    </Disclosure>
  );
}
