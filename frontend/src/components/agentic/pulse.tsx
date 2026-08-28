"use client";

import * as React from "react";
import { Check, CircleDot, OctagonAlert, TriangleAlert } from "lucide-react";

import { cn } from "@/lib/utils";

import { type Stage, isTerminal } from "./officer";

/**
 * The activity mark. §6, §10.
 *
 * An ECG trace: five bars, one of which beats. It is 20 pixels wide and sits
 * beside a sentence, which is the whole design — §6 forbids a large loading
 * screen and a fake percentage bar, and the reason both are wrong is the same:
 * they occupy the space where the answer is about to appear.
 *
 * What it is not
 * --------------
 * Not a spinner, not a progress bar, not a heart, and not permanent. It exists
 * only while a request is in flight, which is what makes it mean something.
 *
 * Reduced motion
 * --------------
 * §10 asks for a non-animated status icon under `prefers-reduced-motion`. The
 * bars are replaced by a filled dot — still, still coloured, still positioned
 * where the pulse was, so the layout does not shift when somebody changes the
 * setting.
 */
export function Pulse({
  stage,
  reducedMotion,
  className,
}: {
  stage: Stage;
  reducedMotion: boolean;
  className?: string;
}) {
  if (isTerminal(stage)) return <Settled stage={stage} className={className} />;

  if (reducedMotion) {
    return (
      <CircleDot
        className={cn("size-3.5 shrink-0 text-pulse", className)}
        aria-hidden
      />
    );
  }

  return (
    <span
      className={cn(
        "relative inline-flex h-3.5 w-5 shrink-0 items-center gap-[2px]",
        className,
      )}
      aria-hidden
    >
      {/* The flat line the beat travels along. */}
      <span className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-pulse/25" />
      {[0, 1, 2, 3, 4].map((bar) => (
        <span
          key={bar}
          className="relative h-3 w-[2px] origin-center rounded-full bg-pulse"
          style={{
            animation: "officer-beat 1.8s ease-in-out infinite",
            animationDelay: `${bar * 0.12}s`,
          }}
        />
      ))}
    </span>
  );
}

/**
 * What the mark becomes when the work stops.
 *
 * Four terminal states and four different icons, because §10 asks for text
 * plus icon rather than colour alone: a reader who cannot distinguish the
 * green from the amber still sees a tick, a triangle or an octagon.
 */
function Settled({ stage, className }: { stage: Stage; className?: string }) {
  const size = cn("size-3.5 shrink-0", className);
  if (stage === "COMPLETE")
    return <Check className={cn(size, "text-pulse")} aria-hidden />;
  if (stage === "NEEDS_INPUT")
    return <TriangleAlert className={cn(size, "text-warning")} aria-hidden />;
  if (stage === "FAILED")
    return <OctagonAlert className={cn(size, "text-negative")} aria-hidden />;
  return <CircleDot className={cn(size, "text-text-muted")} aria-hidden />;
}

/**
 * Whether this reader has asked for less motion.
 *
 * `useSyncExternalStore` rather than an effect, because the value is browser
 * state that can change while the page is open — somebody switching the
 * setting mid-request should see the pulse stop, not on the next navigation.
 */
export function usePrefersReducedMotion(): boolean {
  return React.useSyncExternalStore(
    subscribe,
    () => window.matchMedia("(prefers-reduced-motion: reduce)").matches,
    // On the server, assume motion is fine: the alternative renders the static
    // icon and then swaps to the animated one on hydration, which is a flicker
    // for everybody to avoid one for a few.
    () => false,
  );
}

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia("(prefers-reduced-motion: reduce)");
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}
