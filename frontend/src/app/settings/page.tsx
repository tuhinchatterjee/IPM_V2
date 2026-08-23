import { PageHeader } from "@/components/layout/page-header";
import { BackendStatusPanel } from "@/components/system/backend-status";
import { ThemeSwitcher } from "@/components/system/theme-switcher";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { API_BASE_URL } from "@/lib/api";

/**
 * Settings / Administration.
 *
 * Partially real in Phase 1: the Theme Gallery works, and the system status is
 * live. Model configuration, the reporting calendar and user administration
 * arrive in Phase 6 and say so rather than showing dead controls.
 */
export default function SettingsPage() {
  return (
    <div className="space-y-6">
      <PageHeader
        title="Settings"
        description="Themes, system status and administration."
        status="partial"
        phase="Phase 1"
      />

      <ThemeSwitcher />

      <BackendStatusPanel />

      <Card>
        <CardHeader>
          <CardTitle>Connection</CardTitle>
          <CardDescription>
            Where this interface expects to find the IPM backend. Change it with the{" "}
            <code className="font-mono text-xs">NEXT_PUBLIC_API_URL</code> setting in
            your <code className="font-mono text-xs">.env</code> file.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <code className="block rounded-md border border-border bg-surface-sunken px-4 py-3 font-mono text-xs text-text-primary">
            {API_BASE_URL}
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
