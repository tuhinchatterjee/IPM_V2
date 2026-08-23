import {
  Binary,
  Braces,
  Calculator,
  Database,
  Filter,
  FunctionSquare,
  Layers,
  ListChecks,
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
 * "Governed data", "Filters applied", "IPM Engine" — never "DATASET" or
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
    label: "Reading",
    icon: PenLine,
    governed: false,
    blurb: "How IPM understood the question. Interpretation — no figures.",
  },
  PLAN: {
    label: "Plan",
    icon: ListChecks,
    governed: false,
    blurb: "Which registered analyses were selected, and why.",
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
    label: "IPM Engine",
    icon: FunctionSquare,
    governed: true,
    blurb: "The registered analysis, at the version recorded here.",
  },
  RESULT: {
    label: "Result",
    icon: Table2,
    governed: true,
    blurb: "The structured output, with its declared units.",
  },
  LLM_EXPLANATION: {
    label: "Findings",
    icon: PenLine,
    governed: false,
    blurb: "The written findings. Every figure quoted came from a result above.",
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
