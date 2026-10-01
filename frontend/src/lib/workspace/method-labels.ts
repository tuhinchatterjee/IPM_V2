/**
 * The three methods by their governed names (§6, METH05): one definition
 * for every governed What-If surface -- run panel, result, preview, thread
 * strip. The accepted Cockpit chat narrative keeps its own wording.
 */

export const METHOD_LABEL: Record<string, string> = {
  delta: "Method 1 — Delta",
  ml: "Method 2 — ML emulator",
  user_defined: "Method 3 — User-defined",
};

export const methodLabel = (id: string) => METHOD_LABEL[id] ?? id;
