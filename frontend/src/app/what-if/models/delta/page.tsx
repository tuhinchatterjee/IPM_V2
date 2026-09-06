"use client";

/**
 * The Delta Model, explained to the person who has to defend its numbers.
 *
 * Everything here comes from the model itself rather than being written twice.
 * A configuration page that restated the formula in prose would drift from the
 * code the first time somebody changed a cap.
 */

import { PageHeader } from "@/components/layout/page-header";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Unavailable } from "@/components/ui/unavailable";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/hooks";

export default function DeltaModelPage() {
  const model = useAsync(() => api.whatIfDeltaModel(), []);
  const data = model.data;

  return (
    <div className="space-y-5">
      <PageHeader
        eyebrow="What-If Analysis"
        title="Delta Model"
        description="A transparent, deterministic sensitivity. Every figure it produces can be reproduced with a calculator."
      />
      <Unavailable state={model} what="the Delta Model configuration" />

      {data ? (
        <>
          <Card>
            <CardHeader>
              <CardTitle className="text-[14px]">
                {data.name} v{data.version} · {data.owner}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 text-[12px] text-text-secondary">
              <p>{data.purpose}</p>
              <div className="rounded-md border border-border bg-surface-sunken p-3">
                <div className="text-[11px] uppercase tracking-wide text-text-muted">
                  Formula
                </div>
                <code className="mt-1 block text-[13px] text-text-primary">
                  {data.formula}
                </code>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wide text-text-muted">
                  Official ECL anchor
                </div>
                <p className="mt-1">{data.anchor}</p>
              </div>
              <div>
                <div className="text-[11px] uppercase tracking-wide text-text-muted">
                  As built
                </div>
                <p className="mt-1">{data.as_built}</p>
              </div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-[14px]">Mechanics</CardTitle>
            </CardHeader>
            <CardContent className="space-y-2">
              {Object.entries(data.mechanics).map(([name, body]) => (
                <div key={name} className="rounded-md border border-border p-3">
                  <div className="text-[12px] font-medium text-text-primary">{name}</div>
                  <p className="mt-1 text-[12px] text-text-secondary">{body}</p>
                </div>
              ))}
            </CardContent>
          </Card>

          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-[14px]">Caps and floors</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 text-[12px]">
                {Object.entries(data.caps).map(([name, body]) => (
                  <div key={name} className="flex gap-2">
                    <span className="w-28 shrink-0 text-text-muted">{name}</span>
                    <span className="text-text-secondary">{body}</span>
                  </div>
                ))}
                <p className="pt-2 text-[11px] text-text-muted">{data.near_zero_rule}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-[14px]">Worked example</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 text-[12px]">
                {Object.entries(data.worked_example).map(([name, body]) => (
                  <div key={name} className="flex gap-2">
                    <span className="w-20 shrink-0 text-text-muted">{name}</span>
                    <span
                      className={
                        name === "warning" ? "text-warning" : "text-text-secondary"
                      }
                    >
                      {body}
                    </span>
                  </div>
                ))}
              </CardContent>
            </Card>
          </div>

          <Card>
            <CardHeader>
              <CardTitle className="text-[14px]">Limitations</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="space-y-1.5">
                {data.limitations.map((limitation) => (
                  <li key={limitation} className="text-[12px] text-text-secondary">
                    • {limitation}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
