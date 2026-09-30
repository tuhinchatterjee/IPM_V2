"use client";

/** Share a governed object through Messages: the reference travels, never data. */

import * as React from "react";
import Link from "next/link";
import { Send } from "lucide-react";

import { sendObject } from "@/lib/workspace/messages";

export function ShareButton({ objectId, version, testId = "share" }: { objectId: string; version?: number; testId?: string }) {
  const [open, setOpen] = React.useState(false);
  const [to, setTo] = React.useState("");
  const [message, setMessage] = React.useState("");
  const [done, setDone] = React.useState("");
  const [error, setError] = React.useState("");
  async function send() {
    setError("");
    try {
      const r = await sendObject(objectId, to.split(/[,\s]+/).filter(Boolean), message, version);
      setDone(`Shared with ${to} (${r.shared.length} message${r.shared.length === 1 ? "" : "s"}).`);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }
  return (
    <span className="inline-flex flex-wrap items-center gap-1 text-xs" data-testid={testId}>
      <button type="button" onClick={() => setOpen((v) => !v)} className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1" data-testid={`${testId}-open`}>
        <Send className="h-3.5 w-3.5" /> Share
      </button>
      {open && (
        <>
          <input value={to} onChange={(e) => setTo(e.target.value)} placeholder="recipient id(s)" className="rounded border border-border bg-surface px-2 py-1" data-testid={`${testId}-to`} />
          <input value={message} onChange={(e) => setMessage(e.target.value)} placeholder="message" className="rounded border border-border bg-surface px-2 py-1" data-testid={`${testId}-message`} />
          <button type="button" disabled={!to.trim()} onClick={() => void send()} className="rounded-md bg-accent px-2 py-1 text-accent-contrast disabled:opacity-40" data-testid={`${testId}-send`}>
            Send
          </button>
        </>
      )}
      {done && (
        <span className="text-positive" data-testid={`${testId}-done`}>
          {done}{" "}
          <Link href="/messages?box=sent" className="text-accent underline">
            Sent messages
          </Link>
        </span>
      )}
      {error && (
        <span role="alert" className="text-negative">
          {error}
        </span>
      )}
    </span>
  );
}
