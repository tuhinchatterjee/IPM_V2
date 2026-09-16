"use client";

import Link from "next/link";
import * as React from "react";
import {
  ArrowRight,
  Check,
  CircleDot,
  Copy,
  RotateCcw,
  TriangleAlert,
} from "lucide-react";

import { PageHeader } from "@/components/layout/page-header";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import type { DemoStory, DemoStoryStep } from "@/lib/api";
import { cn } from "@/lib/utils";

/**
 * Demo Story. §22.
 *
 * What this is
 * -------------
 * A guided navigation aid over the real product. Every step opens a real
 * screen and every prompt is typed into the real composer; nothing here
 * pre-answers anything, and the free-text path is untouched — a presenter
 * who abandons the story mid-act loses nothing but the breadcrumb.
 *
 * Why the ids are fetched rather than written down
 * -------------------------------------------------
 * The story names an investigation, a document, a lens. Those are database
 * sequence values: correct on the machine the guide was written on and wrong
 * on every other one. So the server resolves each of them by seed key on
 * every request and the screen shows what it resolved. A step whose object
 * is missing says so — in grey, with the reason — rather than offering a
 * link that 404s in front of a client.
 *
 * Resume
 * -------
 * Where the presenter got to is kept in this browser, keyed by the story
 * version, so a story that changes shape does not resume into a step that no
 * longer exists. It is deliberately local: it is one person's place in a
 * rehearsal, not shared state.
 */

const PLACE = "creditprobe.demo-story.place";

type Place = { version: string; act: string; step: string; done: string[] };

function readPlace(version: string): Place {
  const blank: Place = { version, act: "", step: "", done: [] };
  if (typeof window === "undefined") return blank;
  try {
    const held = JSON.parse(window.localStorage.getItem(PLACE) ?? "null");
    if (!held || held.version !== version) return blank;
    return { ...blank, ...held, done: Array.isArray(held.done) ? held.done : [] };
  } catch {
    return blank;
  }
}

function writePlace(place: Place) {
  try {
    window.localStorage.setItem(PLACE, JSON.stringify(place));
  } catch {
    /* A presenter in a private window keeps the story, loses the breadcrumb. */
  }
}

function Copyable({ text }: { text: string }) {
  const [took, setTook] = React.useState(false);
  return (
    <button
      type="button"
      data-testid="story-copy-prompt"
      onClick={() => {
        navigator.clipboard?.writeText(text).then(
          () => {
            setTook(true);
            window.setTimeout(() => setTook(false), 1600);
          },
          () => undefined,
        );
      }}
      className="inline-flex shrink-0 items-center gap-1 rounded border border-border px-1.5 py-0.5 text-[10px] text-text-muted hover:text-text"
      title="Copy the prompt so it can be typed into the composer"
    >
      {took ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
      {took ? "copied" : "copy"}
    </button>
  );
}

function StepRow({
  step,
  index,
  current,
  done,
  onOpen,
  onDone,
}: {
  step: DemoStoryStep;
  index: number;
  current: boolean;
  done: boolean;
  onOpen: () => void;
  onDone: () => void;
}) {
  const links = Object.entries(step.links ?? {});
  return (
    <li
      data-testid="story-step"
      data-step-key={step.key}
      data-ready={step.ready ? "yes" : "no"}
      className={cn(
        "rounded-md border px-3 py-2.5",
        current ? "border-accent bg-accent/5" : "border-border",
        !step.ready && "opacity-70",
      )}
    >
      <div className="flex items-start gap-2.5">
        <button
          type="button"
          onClick={onDone}
          aria-label={done ? "Mark step not done" : "Mark step done"}
          className={cn(
            "mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
            done ? "border-positive bg-positive/15 text-positive" : "border-border text-text-muted",
          )}
        >
          {done ? <Check className="h-2.5 w-2.5" /> : <span className="text-[9px]">{index + 1}</span>}
        </button>
        <div className="min-w-0 flex-1">
          <p className="text-[12.5px] leading-snug text-text">{step.narration}</p>

          {step.prompt && (
            <div className="mt-1.5 flex items-start gap-2">
              <code
                data-testid="story-prompt"
                className="min-w-0 flex-1 rounded bg-surface-sunken px-1.5 py-1 text-[11px] leading-snug text-text"
              >
                {step.prompt}
              </code>
              <Copyable text={step.prompt} />
            </div>
          )}

          {step.expect.length > 0 && (
            <ul className="mt-1.5 space-y-0.5">
              {step.expect.map((one) => (
                <li key={one} className="flex gap-1.5 text-[11px] text-text-muted">
                  <CircleDot className="mt-[3px] h-2.5 w-2.5 shrink-0" />
                  <span>{one}</span>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-2 flex flex-wrap items-center gap-2">
            {step.ready && step.route && (
              <Link
                href={step.route}
                onClick={onOpen}
                data-testid="story-open"
                className="inline-flex items-center gap-1 rounded border border-border px-2 py-0.5 text-[11px] text-text hover:border-accent hover:text-accent"
              >
                {step.navigates ? "Open" : "Back to screen"}{" "}
                <ArrowRight className="h-3 w-3" />
              </Link>
            )}
            {step.control && (
              <span className="text-[10px] text-text-muted">
                then press <code className="text-text">{step.control}</code>
              </span>
            )}
            {links.map(([kind, one]) => (
              <span
                key={kind}
                data-testid={`story-link-${kind}`}
                className="text-[10px] text-text-muted"
                title={one.href}
              >
                {kind} #{one.id} — {one.title}
              </span>
            ))}
            {!step.ready && (
              <span className="flex items-center gap-1 text-[10px] text-warning">
                <TriangleAlert className="h-3 w-3" />
                {step.why_not_ready}
              </span>
            )}
          </div>
        </div>
      </div>
    </li>
  );
}

export default function DemoStoryPage() {
  const [story, setStory] = React.useState<DemoStory | null>(null);
  const [failed, setFailed] = React.useState("");
  const [place, setPlace] = React.useState<Place | null>(null);

  React.useEffect(() => {
    let alive = true;
    api
      .retailDemoStory()
      .then((got) => {
        if (!alive) return;
        setStory(got);
        setPlace(readPlace(got.story_version));
      })
      .catch((problem: Error) => alive && setFailed(problem.message));
    return () => {
      alive = false;
    };
  }, []);

  const save = React.useCallback((next: Place) => {
    setPlace(next);
    writePlace(next);
  }, []);

  if (failed) {
    return (
      <div className="p-6">
        <PageHeader title="Demo Story" description="The guided presenter route." />
        <Card className="border-negative/40 p-4 text-[12px] text-negative">{failed}</Card>
      </div>
    );
  }

  if (!story || !place) {
    return (
      <div className="space-y-3 p-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-40 w-full" />
      </div>
    );
  }

  const flat = story.acts.flatMap((act) =>
    act.steps.map((step) => ({ act: act.key, step })),
  );
  const at =
    flat.findIndex((one) => one.act === place.act && one.step.key === place.step);
  const started = at >= 0;
  const resumeTo = started ? flat[at] : flat[0];
  const doneCount = place.done.length;

  return (
    <div className="p-6">
      <PageHeader
        title="Demo Story"
        eyebrow="Work"
        description={story.how_to_use}
        actions={
          <div className="flex items-center gap-2">
            {resumeTo?.step.ready && resumeTo.step.route && (
              <Link
                href={resumeTo.step.route}
                data-testid="story-resume"
                onClick={() =>
                  save({ ...place, act: resumeTo.act, step: resumeTo.step.key })
                }
                className="inline-flex items-center gap-1.5 rounded border border-accent px-2.5 py-1 text-[11.5px] text-accent"
              >
                {started ? "Resume story" : "Start story"} <ArrowRight className="h-3.5 w-3.5" />
              </Link>
            )}
            <button
              type="button"
              data-testid="story-restart"
              onClick={() =>
                save({ version: story.story_version, act: "", step: "", done: [] })
              }
              className="inline-flex items-center gap-1.5 rounded border border-border px-2.5 py-1 text-[11.5px] text-text-muted hover:text-text"
            >
              <RotateCcw className="h-3.5 w-3.5" /> Restart
            </button>
          </div>
        }
      />

      {/* The breadcrumb §22 asks for: where the presenter is, what the story
          is computed against, and whether every artifact it names exists on
          this installation. */}
      <Card className="mb-5 flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-2.5 text-[11px]">
        <span data-testid="story-breadcrumb" className="text-text">
          {started ? (
            <>
              {story.acts.find((a) => a.key === resumeTo.act)?.title}
              <span className="px-1.5 text-text-muted">›</span>
              step {at + 1} of {story.steps}
            </>
          ) : (
            <>Not started — {story.steps} steps across {story.acts.length} acts</>
          )}
        </span>
        <span className="text-text-muted">
          Source month <span data-testid="story-month" className="text-text">{story.month || "—"}</span>
        </span>
        <span className="text-text-muted">
          Book <code data-testid="story-hash" className="text-text">{(story.source_hash || "—").slice(0, 12)}</code>
        </span>
        <span className="text-text-muted">{doneCount} marked done</span>
        <Badge variant={story.ready ? "positive" : "warning"} data-testid="story-ready">
          {story.ready ? "every step resolved" : `${story.missing.length} steps unresolved`}
        </Badge>
        <span className="text-text-muted">{story.story_version}</span>
      </Card>

      <div className="space-y-5">
        {story.acts.map((act, actIndex) => (
          <Card key={act.key} data-testid="story-act" className="p-4">
            <div className="mb-3">
              <p className="text-[10px] uppercase tracking-[0.16em] text-text-muted">
                Act {actIndex + 1}
              </p>
              <h2 className="text-[14px] font-medium text-text">{act.title}</h2>
              <p className="mt-0.5 text-[11.5px] text-text-muted">{act.purpose}</p>
            </div>
            <ol className="space-y-2">
              {act.steps.map((step, i) => {
                const id = `${act.key}/${step.key}`;
                return (
                  <StepRow
                    key={step.key}
                    step={step}
                    index={i}
                    current={place.act === act.key && place.step === step.key}
                    done={place.done.includes(id)}
                    onOpen={() => save({ ...place, act: act.key, step: step.key })}
                    onDone={() =>
                      save({
                        ...place,
                        act: act.key,
                        step: step.key,
                        done: place.done.includes(id)
                          ? place.done.filter((one) => one !== id)
                          : [...place.done, id],
                      })
                    }
                  />
                );
              })}
            </ol>
          </Card>
        ))}
      </div>

      {story.disclosure && (
        <p className="mt-5 text-[10.5px] text-text-muted">{story.disclosure}</p>
      )}
    </div>
  );
}
