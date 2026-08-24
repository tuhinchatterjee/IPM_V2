import { CircleDashed } from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { findNavItem } from "@/lib/navigation";

/**
 * The honest "not built yet" page.
 *
 * The product rule is that the UI must never present a placeholder as production
 * functionality. So rather than a fake dashboard with invented numbers, each
 * unbuilt capability states what it will do, which phase delivers it, and what
 * it will be built on.
 *
 * In front of a CRO this is a strength: it shows the plan is real and the team
 * knows the difference between finished and unfinished.
 */
export function CapabilityPlaceholder({
  href,
  willDo,
  builtOn,
}: {
  href: string;
  /** Concrete capabilities this area will provide. */
  willDo: string[];
  /** Foundations already in place that it will be built on. */
  builtOn?: string[];
}) {
  const item = findNavItem(href);
  if (!item) return null;

  return (
    <div className="space-y-6">
      <PageHeader
        title={item.label}
        description={item.description}
        status={item.status}
        phase={item.phase}
      />

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CircleDashed className="size-4 text-text-muted" aria-hidden />
            Not built yet — scheduled for {item.phase}
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div>
            <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
              What this will do
            </p>
            <ul className="space-y-1.5">
              {willDo.map((line) => (
                <li key={line} className="flex gap-2 text-sm text-text-secondary">
                  <span aria-hidden className="text-text-muted">
                    &middot;
                  </span>
                  <span>{line}</span>
                </li>
              ))}
            </ul>
          </div>

          {builtOn && builtOn.length > 0 && (
            <div>
              <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-text-muted">
                Foundations already in place
              </p>
              <ul className="space-y-1.5">
                {builtOn.map((line) => (
                  <li key={line} className="flex gap-2 text-sm text-text-secondary">
                    <span aria-hidden className="text-positive">
                      &check;
                    </span>
                    <span>{line}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="border-t border-border pt-4 text-xs text-text-muted">
            This screen is a deliberate placeholder. CreditProbe does not present unbuilt
            functionality as if it were finished, and never shows invented figures.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
