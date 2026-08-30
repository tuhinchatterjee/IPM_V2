"use client";

import * as React from "react";

import { api } from "@/lib/api";
import type { ThumbsPrompt, ThumbsReceipt } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * The thumb that follows every answer. §39-§45.
 *
 * Quiet on purpose
 * ----------------
 * Two small text controls under the answer. A prominent button beside an
 * answer nobody checked collects agreement rather than correctness, and a
 * satisfaction score built out of agreement is worse than no score, because
 * it is reported as though it meant something.
 *
 * On every kind of answer
 * -----------------------
 * §39 lists eight, including the awkward ones. An UNSUPPORTED answer with no
 * thumbs collects no capability requests, and the absence reads as nobody
 * wanting the capability. A clarification with no thumbs never hears "you
 * should have known", which is the most useful correction in the system.
 *
 * The dialog asks what you meant, not what the number was
 * -------------------------------------------------------
 * §40's own words to the user: "You do not need to provide the numerical
 * answer." A user asked for the right figure will supply one, it will be
 * wrong about as often as the system was, and it arrives carrying the
 * authority of having been typed by a person. What they know that nobody
 * else does is what they MEANT.
 *
 * And it says what will happen
 * -----------------------------
 * §42 splits presentation from meaning, and the receipt says which half went
 * where. "Thanks, I'll learn from that" is a claim contradicted the next
 * time the user asks the same question and gets the same answer; "your chart
 * preference changed now, the rest is under review" is true and checkable.
 */

export function Thumbs({
  answerId,
  answerKind = "analysis",
  language = "en",
  investigationId,
  planFingerprint,
  className,
}: {
  answerId: string;
  answerKind?: string;
  language?: string;
  investigationId?: string;
  planFingerprint?: string;
  className?: string;
}) {
  const [prompt, setPrompt] = React.useState<ThumbsPrompt | null>(null);
  const [open, setOpen] = React.useState<"" | "UP" | "DOWN">("");
  const [receipt, setReceipt] = React.useState<ThumbsReceipt | null>(null);
  const [failed, setFailed] = React.useState("");
  const [reasons, setReasons] = React.useState<string[]>([]);
  const [correction, setCorrection] = React.useState<Record<string, string>>(
    {},
  );
  const [anchor, setAnchor] = React.useState("");

  React.useEffect(() => {
    let live = true;
    api
      .thumbsPrompt(answerKind, language)
      .then((found) => live && setPrompt(found))
      .catch(() => live && setPrompt(null));
    return () => {
      live = false;
    };
  }, [answerKind, language]);

  if (!answerId || !prompt?.show) return null;

  const send = async (direction: "UP" | "DOWN") => {
    setFailed("");
    try {
      const given = await api.leaveThumbs({
        answer_id: answerId,
        direction,
        answer_kind: answerKind,
        language,
        reasons: direction === "UP" ? reasons : [],
        correction: direction === "DOWN" ? correction : {},
        anchor_kind: direction === "DOWN" ? anchor : "",
        investigation_id: investigationId,
        plan_fingerprint: planFingerprint,
      });
      setReceipt(given);
      setOpen("");
    } catch (error: unknown) {
      setFailed(
        error instanceof Error
          ? error.message
          : "That did not send. Nothing was recorded.",
      );
    }
  };

  if (receipt) {
    return (
      <div className={cn("text-xs text-muted-foreground", className)}>
        <p>{receipt.what_happens_next}</p>
        {Object.keys(receipt.changed_immediately).length > 0 && (
          <p className="mt-1">
            Changed now:{" "}
            {Object.entries(receipt.changed_immediately)
              .map(([name, value]) => `${name.replace(/_/g, " ")} → ${value}`)
              .join(", ")}
            .
          </p>
        )}
        {receipt.under_review.length > 0 && (
          <p className="mt-1">
            Under review: {receipt.under_review.length} item(s). Nothing about
            how answers are computed has changed yet.
          </p>
        )}
      </div>
    );
  }

  return (
    <div className={cn("text-xs", className)}>
      {open === "" && (
        <div className="flex items-center gap-3 text-muted-foreground">
          <button
            type="button"
            onClick={() => setOpen("UP")}
            className="hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {prompt.up.label}
          </button>
          <button
            type="button"
            onClick={() => setOpen("DOWN")}
            className="hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {prompt.down.label}
          </button>
        </div>
      )}

      {open === "UP" && (
        <div className="space-y-2 rounded border border-border/60 p-3">
          <p className="text-muted-foreground">What was good about it?</p>
          <div className="flex flex-wrap gap-1">
            {prompt.up.reasons.map((one) => (
              <button
                key={one.id}
                type="button"
                aria-pressed={reasons.includes(one.id)}
                onClick={() =>
                  setReasons((was) =>
                    was.includes(one.id)
                      ? was.filter((r) => r !== one.id)
                      : [...was, one.id],
                  )
                }
                className={cn(
                  "rounded px-1.5 py-0.5 text-[11px] transition-colors",
                  reasons.includes(one.id)
                    ? "bg-muted font-medium text-foreground"
                    : "text-muted-foreground hover:bg-muted/60",
                )}
              >
                {one.label}
              </button>
            ))}
          </div>
          <Send onSend={() => send("UP")} onCancel={() => setOpen("")} />
        </div>
      )}

      {open === "DOWN" && (
        <div className="space-y-3 rounded border border-border/60 p-3">
          <div>
            <p className="font-medium">{prompt.down.question}</p>
            {/* The sentence that stops a user inventing a number. */}
            <p className="mt-0.5 text-muted-foreground">
              {prompt.down.explain}
            </p>
          </div>

          <div>
            <p className="text-[11px] text-muted-foreground">
              What are you pointing at? (optional)
            </p>
            <div className="mt-1 flex flex-wrap gap-1">
              {prompt.down.anchors.map((one) => (
                <button
                  key={one.id}
                  type="button"
                  title={one.means}
                  aria-pressed={anchor === one.id}
                  onClick={() => setAnchor(anchor === one.id ? "" : one.id)}
                  className={cn(
                    "rounded px-1.5 py-0.5 text-[11px] transition-colors",
                    anchor === one.id
                      ? "bg-muted font-medium text-foreground"
                      : "text-muted-foreground hover:bg-muted/60",
                  )}
                >
                  {one.id.replace(/_/g, " ")}
                </button>
              ))}
            </div>
          </div>

          <div className="space-y-2">
            {prompt.down.fields.map((field) => (
              <label key={field.id} className="block">
                <span className="text-[11px] font-medium">{field.label}</span>
                <span className="ml-1 text-[11px] text-muted-foreground">
                  {field.help}
                </span>
                <input
                  type="text"
                  value={correction[field.id] ?? ""}
                  onChange={(e) =>
                    setCorrection((was) => ({
                      ...was,
                      [field.id]: e.target.value,
                    }))
                  }
                  className="mt-0.5 w-full rounded border border-border bg-transparent px-2 py-1 text-xs focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-1"
                />
              </label>
            ))}
          </div>

          {/* What will actually happen, before they send it. A user who is
              told afterwards that most of what they wrote goes to a review
              queue feels handled; told beforehand, they know which fields
              are worth their time. */}
          <p className="text-[11px] text-muted-foreground">
            {prompt.what_happens_next.note}
          </p>

          <Send onSend={() => send("DOWN")} onCancel={() => setOpen("")} />
        </div>
      )}

      {failed && <p className="mt-1 text-[11px] text-destructive">{failed}</p>}
    </div>
  );
}

function Send({
  onSend,
  onCancel,
}: {
  onSend: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="flex gap-2">
      <button
        type="button"
        onClick={onSend}
        className="rounded bg-muted px-2 py-1 text-[11px] font-medium hover:bg-muted/70 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        Send
      </button>
      <button
        type="button"
        onClick={onCancel}
        className="px-2 py-1 text-[11px] text-muted-foreground hover:text-foreground focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        Cancel
      </button>
    </div>
  );
}
