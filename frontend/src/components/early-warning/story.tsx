"use client";

import * as React from "react";

import type { BorrowerStory, StoryFamily, StorySection } from "@/lib/api";
import * as ewFormat from "@/lib/early-warning-format";

/**
 * A borrower's Early Warning position, as a credit story. R2 §5.
 *
 * The instruction is "do not merely list 17 conditions". So this screen does
 * not lead with conditions at all: it leads with why the borrower is in front
 * of you and what the single worst thing is, then what changed, then the eight
 * families in credit-file order, then what is happening outside the bank, what
 * the group adds, what argues the other way and what to go and look at.
 *
 * The wording is not written here. Every sentence comes from the backend
 * beside the evidence that produced it, so the screen, the export and the
 * analyst's tools cannot describe the same position three different ways. What
 * this component decides is emphasis and order of the eye, not content.
 *
 * A section with nothing to say still appears when its silence is a finding —
 * "every covenant test ran and none was met" is a fact about this borrower.
 * A section that could not be built says so rather than showing empty, because
 * "nothing here" and "not checked" are the two answers that must never look
 * alike.
 */

const LEAD = new Set(["why_here", "top_risk"]);

const SEVERITY_TONE: Record<string, string> = {
  SEVERE: "text-danger",
  CONCERN: "text-warning",
  WATCH: "text-text-secondary",
};

function Lead({ section }: { section: StorySection }) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-xs font-medium uppercase tracking-wide text-text-muted">
        {section.heading}
      </h3>
      {section.unavailable ? (
        <p className="text-sm leading-relaxed text-text-muted">{section.unavailable}</p>
      ) : (
        section.body.map((line) => (
          <p key={line} className="text-sm leading-relaxed text-text-secondary">
            {line}
          </p>
        ))
      )}
    </section>
  );
}

function Change({ section }: { section: StorySection }) {
  if (section.empty) return null;
  return (
    <section className="space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {section.heading}
        </h3>
        <span className="text-[11px] text-text-muted">{section.question}</span>
      </div>
      <ul className="space-y-1">
        {section.body.map((line) => (
          <li key={line} className="text-xs leading-relaxed text-text-secondary">
            {line}
          </li>
        ))}
      </ul>
    </section>
  );
}

function Family({ family }: { family: StoryFamily }) {
  const [open, setOpen] = React.useState(false);
  const has = family.fired.length > 0 || family.untested.length > 0;

  return (
    <div className="border-b border-border-subtle py-2 last:border-0">
      <button
        type="button"
        onClick={() => has && setOpen((was) => !was)}
        className={`flex w-full items-baseline justify-between gap-3 text-left ${
          has ? "cursor-pointer" : "cursor-default"
        }`}
        aria-expanded={open}
        disabled={!has}
      >
        <span className="text-xs text-text-secondary">
          <span
            className={`font-medium ${
              SEVERITY_TONE[family.severity] ?? "text-text-primary"
            }`}
          >
            {family.label}
          </span>
          <span className="ml-2 text-text-muted">{family.reading}</span>
        </span>
        {has ? (
          <span className="shrink-0 text-[10px] uppercase tracking-wide text-text-muted">
            {open ? "hide" : "show"}
          </span>
        ) : null}
      </button>
      {open ? (
        <div className="mt-2 space-y-1.5 pl-3">
          <p className="text-[11px] leading-relaxed text-text-muted">{family.means}</p>
          {family.fired.map((observation) => (
            <p key={observation.signal} className="text-xs text-text-secondary">
              <span className="text-text-primary">{observation.label}</span>
              {" — "}
              {ewFormat.showValue(
                observation.value,
                observation.unit,
                observation.currency || "SAR",
              )}
              {observation.means ? `. ${observation.means}` : ""}
            </p>
          ))}
          {family.untested.map((observation) => (
            <p key={observation.signal} className="text-xs text-text-muted">
              <span className="text-text-secondary">{observation.label}:</span>{" "}
              {observation.unavailable}
            </p>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function Context({ section }: { section: StorySection }) {
  return (
    <section className="space-y-1.5">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-text-muted">
          {section.heading}
        </h3>
        <span className="text-[11px] text-text-muted">{section.question}</span>
      </div>
      {section.unavailable ? (
        <p className="text-xs leading-relaxed text-text-muted">{section.unavailable}</p>
      ) : (
        <ul className="space-y-1">
          {section.body.map((line) => (
            <li key={line} className="text-xs leading-relaxed text-text-secondary">
              {line}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Investigate({ section }: { section: StorySection }) {
  return (
    <section className="space-y-1.5 rounded-lg border border-border bg-surface p-3">
      <div className="flex flex-wrap items-baseline gap-2">
        <h3 className="text-xs font-medium uppercase tracking-wide text-text-primary">
          {section.heading}
        </h3>
        <span className="text-[11px] text-text-muted">{section.question}</span>
      </div>
      <ol className="space-y-1.5">
        {section.body.map((line, index) => (
          <li key={line} className="flex gap-2 text-xs leading-relaxed text-text-secondary">
            <span className="shrink-0 tabular-nums text-text-muted">{index + 1}.</span>
            <span>{line}</span>
          </li>
        ))}
      </ol>
    </section>
  );
}

export function CreditStory({ story }: { story: BorrowerStory }) {
  const by = new Map(story.sections.map((section) => [section.key, section]));
  const lead = story.sections.filter((section) => LEAD.has(section.key));
  const changes = ["new", "worsening", "persistent", "cured"]
    .map((key) => by.get(key))
    .filter((section): section is StorySection => Boolean(section));

  return (
    <div className="space-y-5">
      {lead.map((section) => (
        <Lead key={section.key} section={section} />
      ))}

      {changes.some((section) => !section.empty) ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {changes.map((section) => (
            <Change key={section.key} section={section} />
          ))}
        </div>
      ) : null}

      <section className="space-y-1">
        <h3 className="text-xs font-medium uppercase tracking-wide text-text-muted">
          The eight families
        </h3>
        <div>
          {story.families.map((family) => (
            <Family key={family.family} family={family} />
          ))}
        </div>
      </section>

      {by.get("external") ? <Context section={by.get("external") as StorySection} /> : null}
      {by.get("group") ? <Context section={by.get("group") as StorySection} /> : null}
      {by.get("mitigating") ? (
        <Context section={by.get("mitigating") as StorySection} />
      ) : null}
      {by.get("investigate") ? (
        <Investigate section={by.get("investigate") as StorySection} />
      ) : null}
    </div>
  );
}
