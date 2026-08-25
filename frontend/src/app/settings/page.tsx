"use client";

import { CircleAlert, CircleCheck, Cpu } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { BackendStatusPanel } from "@/components/system/backend-status";
import { ROLES, RoleSwitcher, useRole } from "@/components/system/role-switcher";
import { ThemeSwitcher } from "@/components/system/theme-switcher";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_DISPLAY_URL, api, type PlannerMode } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

/**
 * Settings / Administration.
 *
 * Partially real in Phase 1: the Theme Gallery works, and the system status is
 * live. Model configuration, the reporting calendar and user administration
 * arrive in Phase 6 and say so rather than showing dead controls.
 */
export default function SettingsPage() {
  const { role } = useRole();
  const mode = useAsync(() => api.askMode(), []);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Themes, system status and administration."
        status="partial"
        phase="Phase 1"
      />

      <AiProviderCard mode={mode.data} />

      <ThemeSwitcher />

      <Card>
        <CardHeader>
          <CardTitle>Acting role</CardTitle>
          <CardDescription>
            CreditProbe has no login yet, so the role is chosen here and sent to the API on every request.
            The backend genuinely enforces it — a Viewer cannot publish a dataset. This
            demonstrates the permission model; it is not authentication.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-3">
            <RoleSwitcher />
            <Badge variant="accent">{role}</Badge>
          </div>
          <ul className="space-y-1.5">
            {ROLES.map((r) => (
              <li key={r.id} className="flex items-start gap-2 text-xs">
                <code className="shrink-0 rounded bg-surface-sunken px-1.5 py-0.5 font-mono text-[11px] text-text-secondary">
                  {r.id}
                </code>
                <span className="text-text-muted">{r.note}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      <BackendStatusPanel />

      <Card>
        <CardHeader>
          <CardTitle>Connection</CardTitle>
          <CardDescription>
            Where this interface expects to find the CreditProbe backend. Change it with the{" "}
            <code className="font-mono text-xs">NEXT_PUBLIC_API_URL</code> setting in
            your <code className="font-mono text-xs">.env</code> file.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <code className="block rounded-md border border-border bg-surface-sunken px-4 py-3 font-mono text-xs text-text-primary">
            {API_DISPLAY_URL}
          </code>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Not built yet</CardTitle>
          <CardDescription>Scheduled for Phase 6.</CardDescription>
        </CardHeader>
        <CardContent>
          <ul className="space-y-1.5 text-sm text-text-secondary">
            {[
              "Reporting calendar and default analytical period",
              "Real authentication, replacing the acting-role selector above",
              "Usage and cost reporting",
              "Retention policy and the system-wide audit view",
            ].map((line) => (
              <li key={line} className="flex gap-2">
                <span aria-hidden className="text-text-muted">
                  &middot;
                </span>
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Which model is answering, said accurately.
 *
 * The key is never shown, and neither is a reassuring green light when there
 * is no provider: an administrator looking at this screen is deciding whether
 * to trust what users are being told, and the honest answer when nothing is
 * configured is that natural-language understanding is constrained.
 */
function AiProviderCard({ mode }: { mode: PlannerMode | null | undefined }) {
  const connected = mode?.configured ?? false;
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="size-4 text-text-muted" aria-hidden />
          AI provider
        </CardTitle>
        <CardDescription>
          Which model orchestrates Ask CreditProbe. Set{" "}
          <code className="font-mono text-xs">AI_PROVIDER</code>,{" "}
          <code className="font-mono text-xs">AI_MODEL</code> and the provider&apos;s
          API key in your <code className="font-mono text-xs">.env</code> file. The
          key is never displayed here.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Provider" value={mode?.provider || "—"} />
          <Field label="Model" value={mode?.model_name || "—"} />
          <div className="rounded-md border border-border px-3 py-2">
            <p className="text-[11px] text-text-muted">Status</p>
            <p
              className={`mt-1 flex items-center gap-1.5 text-sm font-medium ${
                connected ? "text-positive" : "text-warning"
              }`}
            >
              {connected ? (
                <CircleCheck className="size-3.5" aria-hidden />
              ) : (
                <CircleAlert className="size-3.5" aria-hidden />
              )}
              {mode?.state_label ?? "—"}
            </p>
          </div>
        </div>
        <p className="text-xs leading-relaxed text-text-secondary">
          {mode?.description}
        </p>
        {(mode?.limitations.length ?? 0) > 0 && (
          <div>
            <p className="meta mb-1 text-text-muted">What is constrained</p>
            <ul className="space-y-1">
              {mode?.limitations.map((line) => (
                <li key={line} className="flex gap-2 text-xs text-text-muted">
                  <span aria-hidden>&middot;</span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </div>
        )}
        <p className="text-[11px] leading-relaxed text-text-muted">
          Whatever is configured, the model never calculates a figure. It emits a
          structured plan; the governed runtime validates it and computes every
          number.
        </p>
      </CardContent>
    </Card>
  );
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <p className="text-[11px] text-text-muted">{label}</p>
      <p className="mt-1 font-mono text-sm text-text-primary">{value}</p>
    </div>
  );
}
