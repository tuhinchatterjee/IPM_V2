/**
 * Building and validating in-product links.
 *
 * Kept free of React and of "use client" so it can be unit-tested directly with
 * `node --test`: the rule about which return URLs are honoured is a security
 * boundary, and a security boundary that is only exercised by clicking around
 * the running product is not tested at all.
 */

export interface ReturnTo {
  /** Where Back goes. */
  href: string;
  /** What the Back action says, e.g. "Contracting review". */
  label: string;
}

/** Add return context to a link. */
export function withReturnTo(href: string, from: string, label: string): string {
  const separator = href.includes("?") ? "&" : "?";
  return (
    `${href}${separator}returnTo=${encodeURIComponent(from)}` +
    `&returnLabel=${encodeURIComponent(label)}`
  );
}

/**
 * A path inside this application: one leading slash, and no scheme or host.
 *
 * `//evil.example` is a protocol-relative URL and `javascript:` is a scheme, so
 * both are refused. Anything that gets past this is a same-origin path, which
 * is the only thing a Back button is ever allowed to be.
 */
export function isInternalPath(value: string): boolean {
  return value.startsWith("/") && !value.startsWith("//") && !value.includes(":");
}
