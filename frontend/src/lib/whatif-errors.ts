/**
 * What went wrong on a What-If, and whose problem it is.
 *
 * Every failure used to reach the screen as the same red bar carrying whatever
 * sentence the server happened to send. "You are not permitted to run a
 * scenario", "the analytical lake has not been built", "that shock is not one
 * this engine applies" and "the backend is not running" are four different
 * situations with four different next actions, and flattening them meant a
 * person could not tell which of them they were in — so every one of them read
 * as "the product is broken".
 *
 * Four things are said instead: what kind of failure it is, what happened,
 * what to do about it, and whether trying again could possibly help. The last
 * one matters most: a refusal that invites a retry wastes the reader's time on
 * a request that will be refused identically, and a transient failure that
 * does not invite one loses the work they typed.
 *
 * Free of React on purpose, so the reading can be asserted with
 * `node --test` rather than through a rendered component.
 */

export interface WhatIfErrorReading {
  kind: string;
  title: string;
  because: string;
  message: string;
  next: string;
  retryable: boolean;
  severity: "refusal" | "failure";
}

export function readWhatIfError(error: unknown): WhatIfErrorReading {
  const said = error instanceof Error ? error.message : String(error ?? "");
  const status = (error as { status?: number })?.status ?? -1;
  const code = String((error as { code?: string })?.code ?? "");

  if (status === 0 || code === "network_error") {
    return {
      kind: "offline",
      title: "The CreditProbe backend did not answer",
      because: "no response",
      message: said || "The request did not reach the server.",
      next: "Nothing you typed was lost. Try again once the backend is running.",
      retryable: true,
      severity: "failure",
    };
  }
  if (status === 401 || status === 403) {
    return {
      kind: "not_permitted",
      title: "Your role may not run this",
      because: `HTTP ${status}`,
      message: said,
      next: "Running a What-If needs the Analyst permission. Trying again "
            + "will not change that — ask an administrator.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status === 503) {
    return {
      kind: "unavailable",
      title: "Something this needs is not available here",
      because: "HTTP 503",
      message: said,
      next: "This is about the installation rather than about your scenario. "
            + "The message above names what is missing.",
      retryable: false,
      severity: "failure",
    };
  }
  if (status === 422 || status === 400) {
    const outside = /different book|domain|Corporate IFRS 9 domain/i.test(said);
    return {
      kind: outside ? "outside_domain" : "refused",
      title: outside
        ? "That is outside What-If Analysis"
        : "The scenario was understood and refused",
      because: `HTTP ${status}`,
      message: said,
      next: outside
        ? "What-If reads the Corporate IFRS 9 book only. Other portfolios are "
          + "measured on their own scales and staging rules."
        : "Change what you asked for and send it again — the same request "
          + "will be refused the same way.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status === 404) {
    return {
      kind: "not_found",
      title: "That does not exist",
      because: "HTTP 404",
      message: said,
      next: "Check the period, the saved What-If or the model version named "
            + "above.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status >= 500) {
    return {
      kind: "defect",
      title: "The calculation failed",
      because: `HTTP ${status}`,
      message: said,
      next: "This is a defect rather than something you did. The run was not "
            + "saved; retrying the same scenario will probably fail the same "
            + "way, and it is worth reporting.",
      retryable: true,
      severity: "failure",
    };
  }
  return {
    kind: "unknown",
    title: "Something went wrong",
    because: status > 0 ? `HTTP ${status}` : "",
    message: said || "No detail was returned.",
    next: "Nothing was changed. Try again, and report it if it repeats.",
    retryable: true,
    severity: "failure",
  };
}

