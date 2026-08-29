import type { LucideIcon } from "lucide-react";
import {
  BarChart3,
  Brain,
  Bot,
  Boxes,
  ClipboardCheck,
  Database,
  FileText,
  FlaskConical,
  GitBranch,
  LayoutGrid,
  Radar,
  Search,
  Settings,
  Sparkles,
  Users,
} from "lucide-react";

/**
 * The CreditProbe AI capability map.
 *
 * One definition of what the product contains — the sidebar, the landing page
 * and every page header read it, so a capability can never appear in one place
 * and not another.
 *
 * The WORK group follows the product hierarchy exactly:
 *
 *     Project        the master workspace
 *       Investigation  a conversational thread
 *         Analysis       one deterministic engine result
 *
 * so Work lists Projects, Investigations, Analyses and Documents in that order.
 * Analysis Studio stays under BUILD because it defines analytical *capabilities*
 * rather than holding executed results. It replaced Engine Builder in the
 * navigation: the registered engine analyses are still there, still certified
 * and still reachable, but they are now one kind of implementation behind a
 * method rather than the whole of what the product can compute. The
 * /engine-builder routes remain for the analyses that link to them.
 *
 * `status` is part of the model rather than a comment. The product rule is that
 * the UI must never present a placeholder as production functionality, and the
 * only reliable way to honour that is to make every screen carry its own honest
 * status and render it.
 */
export type CapabilityStatus =
  /** Working on real engine or Data Builder results, end to end. */
  | "live"
  /** Real, on a deliberately narrow path, or partly demo-seeded. */
  | "partial"
  /** Designed and structurally real, not yet interactive. */
  | "preview"
  /** Not started; the route exists so navigation is complete. */
  | "planned";

export type NavGroup = "Home" | "Work" | "Intelligence" | "Build" | "Govern" | "Admin";

export interface NavItem {
  href: string;
  label: string;
  description: string;
  icon: LucideIcon;
  status: CapabilityStatus;
  phase: string;
  group: NavGroup;
  /**
   * Which roles see this in the sidebar. Absent means everybody.
   *
   * Hiding a link is COURTESY, not security — §28's Agent Operations is
   * enforced by `principals.require_operate` on every endpoint behind it, and
   * a Viewer who types the URL gets a 403 rather than a screen. What this
   * prevents is a sidebar full of things the reader cannot open.
   */
  roles?: string[];
}

export const NAV_GROUPS: NavGroup[] = [
  "Home",
  "Work",
  "Intelligence",
  "Build",
  "Govern",
  "Admin",
];

export const NAV_ITEMS: NavItem[] = [
  {
    href: "/",
    label: "Cockpit",
    description:
      "Ask a question in plain language. CreditProbe AI plans the investigation, runs certified analyses and explains the result.",
    icon: Sparkles,
    status: "live",
    phase: "",
    group: "Home",
  },

  // ---- WORK: the product hierarchy, largest container first ----
  {
    href: "/projects",
    label: "Projects",
    description:
      "The master workspace. A Project holds investigations, saved analyses, documents, people and context.",
    icon: Boxes,
    status: "live",
    phase: "",
    group: "Work",
  },
  {
    href: "/investigations",
    label: "Investigations",
    description:
      "Conversational threads. An Investigation holds every question, answer, analysis and interpretation in one continuing thread.",
    icon: Search,
    status: "live",
    phase: "",
    group: "Work",
  },
  {
    href: "/analyses",
    label: "Analyses",
    description:
      "Executed and saved analytical results, each with the data version, parameters and Trace that produced it.",
    icon: BarChart3,
    status: "live",
    phase: "",
    group: "Work",
  },
  {
    href: "/documents",
    label: "Documents",
    description:
      "Board and committee papers authored with live analytical content. Placeholder for this release.",
    icon: FileText,
    status: "preview",
    phase: "Placeholder by design",
    group: "Work",
  },

  // ---- INTELLIGENCE: standing capability rather than one-off work ----
  {
    href: "/lenses",
    label: "Lenses",
    description:
      "Live dashboards you build by describing them. Each tile is a certified analysis with its own Trace.",
    icon: LayoutGrid,
    status: "live",
    phase: "",
    group: "Intelligence",
  },
  {
    href: "/early-warning",
    label: "Early Warning",
    description:
      "Forward Risk Signal: a transparent, factor-based estimate of the chance a facility moves to a worse IFRS 9 stage next quarter, for three transitions. Every score decomposes exactly into one number per factor.",
    icon: Radar,
    status: "partial",
    phase: "Prototype signal, fitted on synthetic data. Not a validated model.",
    group: "Intelligence",
  },
  {
    href: "/playbooks",
    label: "Playbooks",
    description:
      "A standing instruction: run these certified analyses over this scope, test these thresholds, and act when one is crossed. A run that finds nothing says so.",
    icon: ClipboardCheck,
    status: "partial",
    phase: "Manual and on-publication triggers run; scheduled ones are not yet wired to a scheduler",
    group: "Intelligence",
  },
  {
    href: "/stress",
    label: "Stress Testing",
    description:
      "Named, versioned management scenarios applied to the portfolio, with comparison.",
    icon: FlaskConical,
    status: "live",
    phase: "",
    group: "Intelligence",
  },

  // ---- BUILD: what the product is capable of, and what it may read ----
  {
    href: "/studio",
    label: "Analysis Studio",
    description:
      "Every credit-risk method CreditProbe knows, what each one measures, and — where one exists — the implementation and the test cases that prove it. Build new methods by describing them; certify them only once their validation pack passes.",
    icon: FlaskConical,
    status: "live",
    phase: "",
    group: "Build",
  },
  {
    href: "/data-builder",
    label: "Data Builder",
    description:
      "Domains, dataset families, the data dictionary, relationships, quality and publication.",
    icon: Database,
    status: "live",
    phase: "",
    group: "Build",
  },

  // ---- GOVERN ----
  {
    href: "/trace",
    label: "Trace & Lineage",
    description:
      "How an analysis was created: every step from question to chart, inspectable and modifiable.",
    icon: GitBranch,
    status: "live",
    phase: "",
    group: "Govern",
  },
  {
    href: "/workflow",
    label: "Workflow",
    description:
      "Share, review and approve the things that carry institutional weight, with an append-only decision history.",
    icon: ClipboardCheck,
    status: "live",
    phase: "",
    group: "Govern",
  },

  // ---- ADMIN ----
  {
    href: "/agent-operations",
    label: "Agent Operations",
    description:
      "The governed agentic layer: the twelve specialists and what each may do, every run and what it cost, the schedules, the policies, the approvals waiting for a person, and how the agents score against the evaluation corpus.",
    icon: Bot,
    status: "live",
    phase: "",
    group: "Admin",
    // §64: "Only authorized roles can access it." §28 places it with
    // Administration rather than in the ordinary Cockpit navigation, because
    // an analyst has no use for a worker heartbeat.
    roles: ["ADMIN", "DATA_STEWARD"],
  },
  {
    href: "/ai-studio",
    label: "AI Intelligence Studio",
    description:
      "What CreditProbe has been taught, how it was validated, how it is performing, what has gone stale and which release is running \u2014 for the ontology, the teaching library, the investigation blueprints, the judgment policies, the visualization grammar and the model routing.",
    icon: Brain,
    status: "live",
    phase: "",
    group: "Admin",
    // §119: an ordinary Analyst sees only a compact assurance badge on the
    // answer itself. Reading which cases production retrieves is most of the
    // way to knowing how to phrase a question to get a chosen answer, so the
    // Studio needs the standing to change it — and every endpoint behind it
    // enforces that whatever the sidebar shows.
    roles: ["ADMIN", "DATA_STEWARD"],
  },
  {
    href: "/users",
    label: "Users & Teams",
    description: "Users, teams, roles and permissions at capability, object and data level.",
    icon: Users,
    status: "preview",
    phase: "Demo records",
    group: "Admin",
  },
  {
    href: "/settings",
    label: "Settings",
    description: "Themes, roles, model configuration and administration.",
    icon: Settings,
    status: "partial",
    phase: "",
    group: "Admin",
  },
];

export const STATUS_LABEL: Record<CapabilityStatus, string> = {
  live: "Live",
  partial: "Partial",
  preview: "Preview",
  planned: "Planned",
};

export function itemsInGroup(group: NavGroup, role?: string): NavItem[] {
  return NAV_ITEMS.filter(
    (item) =>
      item.group === group && (!item.roles || !role || item.roles.includes(role)),
  );
}

export function findNavItem(href: string): NavItem | undefined {
  return NAV_ITEMS.find((item) => item.href === href);
}
