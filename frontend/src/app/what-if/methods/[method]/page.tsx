"use client";

/**
 * A retail What-If methodology, in full. §10.2.
 *
 * Why this route exists, and why it is not `/what-if/models/ml`
 * --------------------------------------------------------------
 * `/what-if/models/delta` and `/what-if/models/ml` are CORPORATE routes. They
 * read the corporate registry, they are retired in a retail installation, and
 * `TestTheCorporateWhatIfRoutesDoNotServeTheirScreen` holds them that way. A
 * corporate route does not become a retail route because retail has acquired
 * a methodology of its own — repointing one at the retail challenger was
 * exactly that mistake, and it broke the boundary.
 *
 * So the retail methodologies live in the retail namespace, beside
 * `/what-if/threads/[threadId]`, and under the word the retail product
 * actually uses. The engine calls them METHODS — "Delta, XGBoost or both" is
 * what the thread asks the reader to choose between — so `methods/[method]`
 * is the retail spelling of the same idea, and one route serves both.
 */

import Link from "next/link";
import { notFound, useParams } from "next/navigation";
import * as React from "react";

import { BackLink } from "@/components/layout/back-link";
import { PageHeader } from "@/components/layout/page-header";
import { RetiredScreen } from "@/components/layout/retired-screen";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RetailChallengerPage } from "@/components/whatif/challenger";
import { api } from "@/lib/api";
import { isRetail } from "@/lib/profile";

/** The methods the retail engine runs, keyed as the API keys them. */
const METHODS: Record<string, { title: string; blurb: string }> = {
  delta: {
    title: "Delta method",
    blurb:
      "Deterministic recalculation of the IFRS 9 identity. Each shock is " +
      "applied to the parameter it names and expected credit loss is " +
      "recomputed facility by facility.",
  },
  xgboost: {
    title: "XGBoost challenger",
    blurb:
      "A gradient-boosted scenario estimator fitted on this book, stored, " +
      "and stamped with the book it was fitted from.",
  },
};

function DeltaMethod() {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-[14px]">The calculation of record</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-[12px] leading-relaxed text-text">
          <p>
            The Delta method does not estimate. It applies each shock to the
            parameter the scenario names and recomputes expected credit loss
            through the same IFRS 9 identity the book was built with —
            facility by facility, over the whole selection.
          </p>
          <p className="text-text-muted">
            That is why it is the figure of record and the challenger is not.
            Every number it produces can be traced to a facility and a
            parameter, and the same scenario run twice gives the same answer.
          </p>
          <p className="text-text-muted">
            Where the challenger disagrees with it, the Delta method stands and
            the disagreement is a reason to look at the challenger.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

export default function RetailMethodPage() {
  const params = useParams<{ method: string }>();
  const key = String(params?.method ?? "");
  const method = METHODS[key];

  // A corporate profile has its own model pages and does not serve this one.
  if (!isRetail()) {
    return (
      <RetiredScreen
        title={"Retail What-If methodology"}
        reason={
          "These pages describe the retail What-If engine's methodologies. " +
          "This installation serves the corporate book, whose model pages " +
          "are under /what-if/models."
        }
        insteadHref={"/what-if/models/delta"}
        insteadLabel={"Delta Model"}
      />
    );
  }
  if (!method) return notFound();

  return <MethodPage methodKey={key} title={method.title} blurb={method.blurb} />;
}

function MethodPage({ methodKey, title, blurb }: {
  methodKey: string; title: string; blurb: string;
}) {
  // The version that actually produced this method's numbers, read from the
  // endpoint that owns it rather than written on the page. A version typed
  // into a screen goes stale the first time the model is refitted — which is
  // exactly what happened to the challenger, where a stale copy in one table
  // disagreed with the artifact on disk.
  const [version, setVersion] = React.useState<string>("");
  React.useEffect(() => {
    let alive = true;
    api.retailMethodologies().then(
      (got) => {
        if (!alive) return;
        const one = (got.methods ?? []).find((m) => m.key === methodKey);
        setVersion(one?.version ?? "");
      },
      () => undefined,
    );
    return () => { alive = false; };
  }, [methodKey]);
  const key = methodKey;
  const method = { title, blurb };

  return (
    <div className="p-6">
      {/* Back to the What-If screen the reader came from. The browser's own
          Back does the same; this is for somebody who arrived by link. */}
      <BackLink href="/what-if" label="What-If Analysis" />
      <PageHeader
        title={method.title}
        eyebrow="What-If"
        description={method.blurb}
      />
      <p className="mb-4 text-[11.5px] text-text-muted">
        Methodology version{" "}
        <code data-testid="retail-method-version">{version || "…"}</code>
        {" "}— the one that produced this method&rsquo;s figures, read from the
        engine rather than written on the page.
      </p>
      {key === "xgboost" ? <RetailChallengerPage /> : <DeltaMethod />}

      <p className="mt-6 text-[11.5px] text-text-muted">
        The other methodology:{" "}
        <Link
          href={`/what-if/methods/${key === "xgboost" ? "delta" : "xgboost"}`}
          className="text-accent underline underline-offset-2"
          data-testid="retail-method-other"
        >
          {key === "xgboost" ? "Delta method" : "XGBoost challenger"}
        </Link>
        .
      </p>
    </div>
  );
}
