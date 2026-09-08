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

  // A timeout is not an unreachable backend, and calling it one is what made
  // this defect so hard to diagnose in UAT: the reader was told the server had
  // not answered while the server was still working on their question and
  // /health was returning 200 throughout. The client's own budget running out
  // is a fact about the client.
  if (code === "timeout") {
    return {
      kind: "timeout",
      title: "That took longer than this page waited",
      because: "the request was still running when the page stopped waiting",
      message: said,
      next: "The backend is running and may well have finished. Nothing you "
            + "typed was lost — send it again, and narrow the population or "
            + "the period if it keeps taking this long.",
      retryable: true,
      severity: "failure",
    };
  }
  // The only reading that may say the backend did not answer: no response at
  // all reached the browser.
  if (status === 0 || code === "network_error") {
    return {
      kind: "offline",
      title: "The CreditProbe backend did not answer",
      because: "no response reached the browser",
      message: said || "The request did not reach the server.",
      next: "Nothing you typed was lost. Try again once the backend is running.",
      retryable: true,
      severity: "failure",
    };
  }
  if (status === 401) {
    return {
      kind: "signed_out",
      title: "You are signed out",
      because: "HTTP 401",
      message: said || "This session is no longer signed in.",
      next: "Please sign in again. Your scenario is held in this page and "
            + "will still be here afterwards.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status === 403) {
    return {
      kind: "not_permitted",
      title: "Your role may not run this",
      because: "HTTP 403",
      message: said,
      next: "Running a What-If needs the Analyst permission. Trying again "
            + "will not change that — ask an administrator.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status === 429) {
    return {
      kind: "limit",
      title: "That request reached a governed limit",
      because: "HTTP 429",
      message: said,
      next: "It stopped rather than spending without a ceiling. Narrowing the "
            + "population or the number of scenarios usually completes.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status === 409) {
    return {
      kind: "conflict",
      title: "Something changed underneath this",
      because: "HTTP 409",
      message: said,
      next: "Reload this What-If so you are working from the current state, "
            + "then send it again.",
      retryable: false,
      severity: "refusal",
    };
  }
  if (status === 503) {
    const model = /ML|XGBoost|model could not be loaded|no active model/i.test(said);
    return {
      kind: model ? "model_unavailable" : "unavailable",
      title: model
        ? "The ML model could not be loaded"
        : "Something this needs is not available here",
      because: "HTTP 503",
      message: said,
      next: model
        ? "The scenario itself is valid. Run it on the Delta Model, or ask an "
          + "administrator to activate an ML model version."
        : "This is about the installation rather than about your scenario. "
          + "The message above names what is missing.",
      retryable: false,
      severity: "failure",
    };
  }
  if (status === 422 || status === 400) {
    const outside = /different book|domain|Corporate IFRS 9 domain/i.test(said);
    const methodology = /methodolog/i.test(said);
    const workbook = /workbook|worksheet|xlsx|export/i.test(said);
    const period = /period|quarter/i.test(said);
    let kind = "refused";
    let title = "The scenario was understood and refused";
    let next = "Change what you asked for and send it again — the same "
               + "request will be refused the same way.";
    if (outside) {
      kind = "outside_domain";
      title = "That is outside What-If Analysis";
      next = "What-If reads the Corporate IFRS 9 book only. Other portfolios "
             + "are measured on their own scales and staging rules.";
    } else if (methodology) {
      kind = "methodology";
      title = "The ECL methodology was not recognised";
      next = "Choose Delta Model or ML Model — XGBoost on this thread and "
             + "send it again. The message above names the governed values.";
    } else if (workbook) {
      kind = "workbook";
      title = "The detailed workbook could not be generated";
      next = "The scenario state this workbook would describe is incomplete. "
             + "Recalculate the scenario and download it again.";
    } else if (period) {
      kind = "period";
      title = "That period could not be read";
      next = "Pick a quarter the Corporate IFRS 9 book publishes — the "
             + "message above names what is available.";
    }
    return {
      kind,
      title,
      because: `HTTP ${status}`,
      message: said,
      next,
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
