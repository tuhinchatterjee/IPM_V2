"use client";

import * as React from "react";

import { PageHeader } from "@/components/layout/page-header";
import { useRole } from "@/components/system/role-switcher";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { StudioTabIndex } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The AI Intelligence Studio. Part C.
 *
 * What this screen is for
 * -----------------------
 * Parts A and B built the intelligence and nobody outside the codebase can
 * see any of it. From a Model Risk reviewer's chair, a materiality policy with
 * nine weighted inputs and a model that guesses are indistinguishable: both
 * produce answers, and neither shows its reasoning.
 *
 * So this is one place to see what has been configured, how it was validated,
 * how it is performing, what is stale and which release uses it — for every
 * object the product reasons with.
 *
 * Not a card wall
 * ---------------
 * §117 says so explicitly, and the defence is progressive disclosure: every
 * object shows one sentence saying what it is, and the other six answers open
 * on request. A reader scanning nineteen blueprints reads nineteen sentences,
 * not a hundred and thirty-three.
 *
 * The tab list comes from the backend
 * ------------------------------------
 * Along with which of them this caller may open. A front end holding its own
 * copy of the permission rules is a second set of rules, and the one that
 * matters is always the one on the server — so this asks, and renders what it
 * is told.
 */

const Overview = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.Overview,
  })),
);
const Knowledge = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.Knowledge,
  })),
);
const Blueprints = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.Blueprints,
  })),
);
const Judgment = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.Judgment,
  })),
);
const VisualGrammar = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.VisualGrammar,
  })),
);
const Settings = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.Settings,
  })),
);
const Later = React.lazy(() =>
  import("@/components/ai-studio/panels").then((m) => ({
    default: m.ComingWithLaterWork,
  })),
);

/** What each tab renders. Tabs whose content lands later say so. */
const PANELS: Record<string, React.ReactNode> = {
  OVERVIEW: <Overview />,
  KNOWLEDGE: <Knowledge />,
  INVESTIGATION_BLUEPRINTS: <Blueprints />,
  ANALYTICAL_JUDGMENT: <Judgment />,
  VISUALIZATION_GRAMMAR: <VisualGrammar />,
  SETTINGS: <Settings />,
};

const LATER: Record<string, string> = {
  TEACHING_CASES:
    "Every case CreditProbe learns from, with its status, its family and whether a person has actually reviewed it. The library and its governance report already exist behind /intelligence/cases and /intelligence/governance; this tab is where they get a reader.",
  MODEL_ROUTING:
    "Which model role handles what, why, and what a question would cost. The routing policy and the honest role preflight already exist behind /intelligence/routing.",
  PROMPTS_AND_TEACHING_PACKS:
    "The versioned prompts and the pack policy that governs what reaches a model.",
  EVALUATIONS:
    "What has been measured, over how many cases, and what the evidence supports — kept in four separate suites, because one combined judgment score hides the failure that matters.",
  INVESTIGATION_REVIEWS:
    "How recent investigations performed, turn by turn. Lands with the Investigation assurance work.",
  FEEDBACK_AND_LEARNING:
    "What users told us and what was done about it, under governed review. Lands with the user-feedback learning loop.",
  AGENTIC_HEALTH:
    "Whether the agentic layer is genuinely running. Lands with the agentic reliability work.",
  RELEASES:
    "What is frozen, what is approved, and what has gone stale underneath it. The release manifest and its gate already exist behind /intelligence/releases.",
  LIVE_AI_HEALTH:
    "The provider, the roles and what a live check would cost, with the exact safe local commands.",
};

export default function AiIntelligenceStudioPage() {
  const { role } = useRole();
  const [index, setIndex] = React.useState<StudioTabIndex | null>(null);
  const [error, setError] = React.useState("");
  const [tab, setTab] = React.useState("");

  React.useEffect(() => {
    let live = true;
    api
      .studioTabs()
      .then((data) => {
        if (!live) return;
        setIndex(data);
        setTab((was) => was || data.visible[0] || "");
      })
      .catch((e: unknown) =>
        live &&
        setError(
          e instanceof Error ? e.message : "Could not load the Studio.",
        ),
      );
    return () => {
      live = false;
    };
  }, [role]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="AI Intelligence Studio"
        description="What CreditProbe has been taught, how it was validated, how it is performing, what has gone stale and which release is running. Read-only about everything it does not own — the editors live in Data Builder, Analysis Studio and Agent Operations."
      />

      {error ? (
        <Card className="p-6">
          <p className="text-sm text-text-secondary">{error}</p>
        </Card>
      ) : !index ? (
        <Skeleton className="h-64 w-full" />
      ) : !index.visible.length ? (
        <Card className="space-y-2 p-6">
          <h2 className="text-sm font-medium text-text-primary">
            The Studio is for administrators, stewards and model risk
          </h2>
          <p className="max-w-2xl text-sm leading-relaxed text-text-secondary">
            This screen shows which teaching cases production retrieves, which
            blueprints it works from and where each policy&rsquo;s thresholds
            sit. Reading it is most of the way to knowing how to phrase a
            question to get a chosen answer, so it needs the standing to change
            it — and every endpoint behind it enforces that regardless of what
            the sidebar shows.
          </p>
          <p className="text-sm leading-relaxed text-text-secondary">
            What you can see instead is the assurance badge on every answer: the
            release it was produced under and how far that release has been
            verified.
          </p>
        </Card>
      ) : (
        <>
          <div
            role="tablist"
            aria-label="AI Intelligence Studio"
            className="flex flex-wrap items-center gap-1 border-b border-border pb-2"
          >
            {index.tabs
              .filter((one) => one.visible)
              .map((one) => (
                <button
                  key={one.id}
                  type="button"
                  role="tab"
                  aria-selected={tab === one.id}
                  title={one.purpose}
                  onClick={() => setTab(one.id)}
                  className={cn(
                    "rounded px-3 py-1.5 text-sm transition-colors",
                    tab === one.id
                      ? "bg-surface-raised font-medium text-text-primary"
                      : "text-text-secondary hover:text-text-primary",
                  )}
                >
                  {one.label}
                </button>
              ))}
          </div>

          <p className="text-sm leading-relaxed text-text-secondary">
            {index.tabs.find((one) => one.id === tab)?.purpose ?? ""}
          </p>

          <React.Suspense fallback={<Skeleton className="h-64 w-full" />}>
            {PANELS[tab] ?? (
              <Later
                title={index.tabs.find((one) => one.id === tab)?.label ?? tab}
                what={LATER[tab] ?? ""}
              />
            )}
          </React.Suspense>
        </>
      )}
    </div>
  );
}
