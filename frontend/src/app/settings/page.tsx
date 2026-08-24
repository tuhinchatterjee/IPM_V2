"use client";

import { PageHeader } from "@/components/layout/page-header";
import { BackendStatusPanel } from "@/components/system/backend-status";
import { ROLES, RoleSwitcher, useRole } from "@/components/system/role-switcher";
import { ThemeSwitcher } from "@/components/system/theme-switcher";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_DISPLAY_URL } from "@/lib/api";

/**
 * Settings / Administration.
 *
 * Partially real in Phase 1: the Theme Gallery works, and the system status is
 * live. Model configuration, the reporting calendar and user administration
 * arrive in Phase 6 and say so rather than showing dead controls.
 */
export default function SettingsPage() {
  const { role } = useRole();

  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Themes, system status and administration."
        status="partial"
        phase="Phase 1"
      />

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
              "Model provider configuration — and the model actually in use, displayed accurately",
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
