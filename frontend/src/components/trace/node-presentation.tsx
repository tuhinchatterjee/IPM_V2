import {
  Binary,
  GitCompareArrows,
  History,
  Braces,
  Fingerprint,
  Compass,
  Library,
  Sigma as SigmaIcon,
  Waypoints,
  Calculator,
  Database,
  Filter,
  FunctionSquare,
  Layers,
  LibraryBig,
  ListChecks,
  Scale,
  MessageSquareQuote,
  PenLine,
  Sigma,
  Table2,
  Variable,
} from "lucide-react";

/**
 * How each kind of step is presented on the reasoning map.
 *
 * The wording is deliberately the bank's, not the codebase's. A reader sees
 * "Governed data", "Filters applied", "CreditProbe Engine" — never "DATASET" or
 * "ENGINE_FUNCTION". The node type is an implementation detail; what the box
 * says is the product.
 */

export interface NodePresentation {
  label: string;
  icon: typeof Database;
  /** Governed nodes carry numbers the bank must defend. */
  governed: boolean;
  blurb: string;
}

export const NODE_PRESENTATION: Record<string, NodePresentation> = {
  USER_PROMPT: {
    label: "Question",
    icon: MessageSquareQuote,
    governed: false,
    blurb: "What was asked, in the user's own words.",
  },
  LLM_INTENT: {
    label: "Reading of the question",
    icon: PenLine,
    governed: false,
    blurb:
      "How CreditProbe understood what was asked, before anything was computed. " +
      "Interpretation — no figures.",
  },
  PLAN: {
    label: "Plan",
    icon: ListChecks,
    governed: false,
    blurb: "Which registered analyses were selected, and why.",
  },
  DATA_DOMAIN: {
    label: "Data domain",
    icon: LibraryBig,
    governed: true,
    blurb:
      "The governed purpose the data was drawn for, and whether the dataset " +
      "serving it is client data or CreditProbe's demonstration data.",
  },
  DATASET: {
    label: "Governed data",
    icon: Database,
    governed: true,
    blurb: "A published dataset, read through the governed access layer.",
  },
  VARIABLE: {
    label: "Variables",
    icon: Variable,
    governed: true,
    blurb: "The governed fields taken from the dataset, with their definitions.",
  },
  FILTER: {
    label: "Filters",
    icon: Filter,
    governed: true,
    blurb: "The period and filters applied, and the rows that survived them.",
  },
  TRANSFORMATION: {
    label: "Transformation",
    icon: Braces,
    governed: true,
    blurb: "A deterministic reshaping of the data.",
  },
  AGGREGATION: {
    label: "Aggregation",
    icon: Sigma,
    governed: true,
    blurb: "Rows combined into groups by the engine.",
  },
  CALCULATION: {
    label: "Calculation",
    icon: Calculator,
    governed: true,
    blurb: "Arithmetic performed by tested engine code.",
  },
  ENGINE_FUNCTION: {
    label: "CreditProbe Engine",
    icon: FunctionSquare,
    governed: true,
    blurb: "The registered analysis, at the version recorded here.",
  },
  CAPABILITY: {
    label: "How the request was read",
    icon: Compass,
    governed: true,
    blurb:
      "What KIND of request this is, which governed concepts and entities it " +
      "names, and how sure the router was. It contains no figures — only " +
      "ANALYSIS requests reach the engine at all.",
  },
  PRIOR_CONTEXT: {
    label: "Carried from the conversation",
    icon: History,
    governed: true,
    blurb:
      "What the investigation had already established when this question was " +
      "asked. Governed, because a reference like \u201cthese\u201d resolves " +
      "to identities the previous run returned rather than to a re-derivation.",
  },
  PLAN_CHANGE: {
    label: "Change to the previous analysis",
    icon: GitCompareArrows,
    governed: true,
    blurb:
      "What this turn altered about the analysis before it — a cut, an order, " +
      "a measure, a filter.",
  },
  GOVERNED_METADATA: {
    label: "Governed catalogue",
    icon: Library,
    governed: true,
    blurb:
      "Answered from Data Builder rather than from the data. No analysis ran " +
      "and no figure was computed.",
  },
  RELATIONSHIP: {
    label: "Governed relationship",
    icon: Waypoints,
    governed: true,
    blurb:
      "A join a steward declared, as consulted: its keys, cardinality, period " +
      "rule and measured coverage.",
  },
  MATHEMATICAL_QUERY: {
    label: "Mathematical query",
    icon: SigmaIcon,
    governed: true,
    blurb:
      "The whole calculation in one place: the analytical plan, the SQL that " +
      "ran, the formula behind every derived column, and the bound parameters.",
  },
  RECONCILIATION: {
    label: "Population reconciled",
    icon: Scale,
    governed: true,
    blurb:
      "How many rows each step kept, counted against the same query that " +
      "produced the answer. A join that lost half the book says so here.",
  },
  FINGERPRINT: {
    label: "Run fingerprint",
    icon: Fingerprint,
    governed: true,
    blurb:
      "What identifies this run: the plan, the dataset versions, the " +
      "relationship versions and the bound parameters, hashed separately so " +
      "two runs that disagree can say which of the four moved.",
  },
  RESULT: {
    label: "Result",
    icon: Table2,
    governed: true,
    blurb: "The structured output, with its declared units.",
  },
  LLM_EXPLANATION: {
    label: "Reading of the result",
    icon: PenLine,
    governed: false,
    blurb:
      "The answer and CreditProbe's reading of it, written after the engine ran. " +
      "Every figure quoted came from a result above.",
  },
  VISUALIZATION: {
    label: "Visualisation",
    icon: Layers,
    governed: true,
    blurb: "How the result was drawn.",
  },
};

export function presentationFor(type: string): NodePresentation {
  return (
    NODE_PRESENTATION[type] ?? {
      label: type,
      icon: Binary,
      governed: true,
      blurb: "",
    }
  );
}

/**
 * What this particular step IS, rather than what kind of step it is.
 *
 * A node labelled "DERIVED_VARIABLE" tells a reader nothing they did not
 * already know from its position on the map. "Stage 2 EAD share" tells them
 * what the analysis actually did, and it was stamped on the node by the run —
 * the label was there all along, and the map was showing the type instead.
 */
export function nodeTitle(node: {
  type: string;
  label?: string | null;
}): string {
  const label = (node.label ?? "").trim();
  if (label && label.toUpperCase() !== node.type) return label;
  return presentationFor(node.type).label;
}

/**
 * The line underneath: how the step was computed, or what kind it is.
 *
 * A formula where one was recorded — "Stage 2 EAD ÷ total sector EAD" is the
 * single most useful thing a Trace can say about a derived column. Otherwise
 * the kind, so the title is free to be specific without leaving a reader
 * guessing what sort of thing they are looking at.
 */
export function nodeSubtitle(node: {
  type: string;
  label?: string | null;
  config?: Record<string, unknown> | null;
  dataset?: string | null;
}): string {
  const config = node.config ?? {};
  for (const key of ["formula", "expression", "definition", "rule", "sql_preview"]) {
    const found = config[key];
    if (typeof found === "string" && found.trim() && found.length < 160) {
      return found.trim();
    }
  }
  const kind = presentationFor(node.type).label;
  const dataset = (node.dataset ?? "").trim();
  if (dataset && dataset !== nodeTitle(node)) return `${kind} · ${dataset}`;
  return kind === nodeTitle(node) ? "" : kind;
}
