import type { LucideIcon } from "lucide-react";
import {
  Boxes,
  ClipboardCheck,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  LayoutGrid,
  Users,
  Radar,
  Search,
  Settings,
  Siren,
  Sparkles,
  Wrench,
} from "lucide-react";

/**
 * The IPM capability map.
 *
 * This is the single definition of what the product contains — the sidebar, the
 * routing and the landing page all read it, so a capability can never appear in
 * one place and not another.
 *
 * `status` is deliberately part of the model rather than a comment. The rule from
 * docs/PRODUCT_SPEC.md is that the UI must never present a placeholder as
 * production functionality, and the only reliable way to honour that is to make
 * every screen carry its own honest status and render it.
 */
export type CapabilityStatus =
  /** Working on real data, end to end. */
  | "live"
  /** Real, on a deliberately narrow path. */
  | "partial"
  /** Designed and structurally real, not yet interactive. */
  | "preview"
  /** Not started; the route exists so navigation is complete. */
  | "planned";

export interface NavItem {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  status: CapabilityStatus;
  /** Which phase delivers it — shown so expectations are set, not guessed at. */
  phase: string;
  group: NavGroup;
}

export type NavGroup = "Analyse" | "Build" | "Govern";

export const NAV_GROUPS: NavGroup[] = ["Analyse", "Build", "Govern"];

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/cockpit",
    label: "AI Cockpit",
    description:
      "Ask a question in plain language. IPM plans the investigation, runs approved analyses and explains the result.",
    icon: Sparkles,
    status: "planned",
    phase: "Phase 4",
    group: "Analyse",
  },
  {
    href: "/monitor",
    label: "Monitor",
    description:
      "Standing surveillance of exposure, staging, ECL, coverage and concentration, period over period.",
    icon: Radar,
    status: "planned",
    phase: "Phase 6",
    group: "Analyse",
  },
  {
    href: "/detect",
    label: "Detect",
    description:
      "Early-warning signals: SICR triggers, downgrades, covenant erosion, utilisation spikes, DPD entry.",
    icon: Siren,
    status: "planned",
    phase: "Phase 6",
    group: "Analyse",
  },
  {
    href: "/investigate",
    label: "Investigate",
    description:
      "Multi-step root-cause analysis, persisted as a named, shareable investigation.",
    icon: Search,
    status: "planned",
    phase: "Phase 6",
    group: "Analyse",
  },
  {
    href: "/stress",
    label: "Stress Testing",
    description:
      "Named, versioned scenarios applied to the portfolio, with sensitivity and comparison.",
    icon: FlaskConical,
    status: "planned",
    phase: "Phase 6",
    group: "Analyse",
  },
  {
    href: "/lenses",
    label: "Lenses",
    description:
      "Saved executive views — composed tiles with fixed filters, each with its own Trace.",
    icon: LayoutGrid,
    status: "planned",
    phase: "Phase 6",
    group: "Analyse",
  },
  {
    href: "/trace",
    label: "Trace",
    description:
      "How an analysis was created: an inspectable, editable graph of every step from question to chart.",
    icon: GitBranch,
    status: "planned",
    phase: "Phase 4",
    group: "Analyse",
  },
  {
    href: "/projects",
    label: "Projects",
    description:
      "Containers for a body of work — chats, investigations, analyses, traces and scenarios.",
    icon: Boxes,
    status: "planned",
    phase: "Phase 6",
    group: "Build",
  },
  {
    href: "/blueprints",
    label: "Blueprints",
    description:
      "Reusable parameterised templates that turn one analyst's proven work into institutional capability.",
    icon: ClipboardCheck,
    status: "planned",
    phase: "Phase 6",
    group: "Build",
  },
  {
    href: "/engine-builder",
    label: "Engine Builder",
    description:
      "Define, test, version and certify analytical capability. IPM Certified analyses carry a verification tick.",
    icon: Wrench,
    status: "planned",
    phase: "Phase 5",
    group: "Build",
  },
  {
    href: "/data-builder",
    label: "Data Builder",
    description:
      "Domains, datasets, the data dictionary, relationships, lineage and data quality.",
    icon: Database,
    status: "planned",
    phase: "Phase 5",
    group: "Build",
  },
  {
    href: "/documents",
    label: "Documents",
    description:
      "Board and committee papers authored with live analytical content. Placeholder for this demo.",
    icon: FileText,
    status: "planned",
    phase: "Phase 6",
    group: "Build",
  },
  {
    href: "/workflow",
    label: "Workflow",
    description:
      "Review and approval of certifications, dataset publication, scenarios and document sign-off.",
    icon: ClipboardCheck,
    status: "planned",
    phase: "Phase 6",
    group: "Govern",
  },
  {
    href: "/users",
    label: "Users & Teams",
    description:
      "Users, teams, roles and permissions at capability, object and data level.",
    icon: Users,
    status: "planned",
    phase: "Phase 6",
    group: "Govern",
  },
  {
    href: "/settings",
    label: "Settings",
    description:
      "Themes, model configuration, reporting calendar and administration.",
    icon: Settings,
    status: "partial",
    phase: "Phase 1",
    group: "Govern",
  },
];

export const STATUS_LABEL: Record<CapabilityStatus, string> = {
  live: "Live",
  partial: "Partial",
  preview: "Preview",
  planned: "Planned",
};

export function itemsInGroup(group: NavGroup): NavItem[] {
  return NAV_ITEMS.filter((item) => item.group === group);
}

export function findNavItem(href: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.href === href);
}
