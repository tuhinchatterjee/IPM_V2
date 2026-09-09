"use client";

import * as React from "react";

import { api, type PbJob } from "@/lib/api";
import { assemble, type PlaybookStreamEvent } from "@/lib/stream";

/**
 * Watching one generation, from wherever it happens to be.
 *
 * The hook does not own the work. The work is a job on the server, running in
 * a worker; this attaches to it, and can attach to one it did not start — which
 * is what a refresh mid-generation is. Everything that must survive a reload
 * therefore lives in the job and its event log, and nothing that matters lives
 * here.
 *
 * `seq` is the cursor. On a reconnect it is sent as `after`, so the server
 * replays exactly what was missed rather than the whole run again.
 */
export function useGeneration(workspaceId: number, onFinished: () => void) {
  const [jobId, setJobId] = React.useState<number | null>(null);
  const [events, setEvents] = React.useState<PlaybookStreamEvent[]>([]);
  const [connectionError, setConnectionError] = React.useState("");
  const abort = React.useRef<AbortController | null>(null);
  // Held in a ref, and updated in an effect rather than during render, so the
  // stream effect below does not restart every time the page re-renders — a
  // restart mid-generation would replay the answer from the beginning.
  const finished = React.useRef(onFinished);
  React.useEffect(() => {
    finished.current = onFinished;
  }, [onFinished]);

  const view = assemble(events);

  React.useEffect(() => {
    if (jobId === null) return;
    const controller = new AbortController();
    abort.current = controller;
    let cursor = 0;
    let live = true;

    const run = async () => {
      // Reconnects on a dropped connection rather than leaving the user with a
      // half-written answer and no way back to it. Bounded, because a stream
      // that cannot be opened at all should say so rather than retry for ever.
      for (let attempt = 0; attempt < 5 && live; attempt += 1) {
        try {
          await api.playbookStream(workspaceId, jobId, {
            after: cursor,
            signal: controller.signal,
            onEvent: (event) => {
              cursor = event.seq || cursor;
              setEvents((current) => [...current, event]);
              if (event.kind === "done" || event.kind === "error") {
                live = false;
                finished.current();
              }
            },
          });
          if (!live) return;
          // The body ended without a terminal event: reconnect from the
          // cursor. The generation is still going; only the pipe broke.
        } catch (e) {
          if (controller.signal.aborted) return;
          if (attempt === 4) {
            setConnectionError(
              e instanceof Error
                ? e.message
                : "The connection to this generation was lost. Reload to see " +
                  "where it got to.",
            );
            return;
          }
        }
        await new Promise((r) => setTimeout(r, 400 * (attempt + 1)));
      }
    };

    void run();
    return () => {
      live = false;
      controller.abort();
    };
  }, [workspaceId, jobId]);

  /** Attach to a job, whether this browser started it or found it running. */
  const watch = React.useCallback((job: number) => {
    setEvents([]);
    setConnectionError("");
    setJobId(job);
  }, []);

  /** Attach to whatever the workspace says is already running, if anything. */
  const resume = React.useCallback(
    (running: PbJob | null | undefined) => {
      if (!running || running.finished) return;
      setJobId((current) => (current === running.id ? current : running.id));
      setEvents((current) => (current.length ? current : []));
    },
    [],
  );

  const release = React.useCallback(() => {
    abort.current?.abort();
    setJobId(null);
    setEvents([]);
  }, []);

  const stop = React.useCallback(async () => {
    if (jobId === null) return "";
    const result = await api.cancelPlaybookJob(jobId);
    return result.message;
  }, [jobId]);

  return {
    jobId,
    /** True while a generation is attached and has not ended. */
    running: jobId !== null && !view.done,
    text: view.text,
    state: view.state,
    detail: view.detail,
    error: view.error || connectionError,
    cancelled: view.cancelled,
    version: view.version,
    done: view.done,
    watch,
    resume,
    release,
    stop,
  };
}
