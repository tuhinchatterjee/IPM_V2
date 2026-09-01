"use client";

import * as React from "react";

import { api } from "@/lib/api";

/**
 * Demo Mode, read from the backend rather than from a build-time flag.
 *
 * One authority. A `NEXT_PUBLIC_` flag baked into the browser bundle can
 * disagree with the container it is talking to — a front end insisting the
 * data is synthetic when it is not is the worst possible direction for that
 * disagreement to run, so the answer comes from the API that knows.
 *
 * Fail-safe while the answer is in flight: `on` is false until the backend
 * says otherwise, so nothing is ever labelled synthetic on a guess.
 */
export interface DemoPosture {
  on: boolean;
  label: string;
  detail: string;
  dataRelease: string;
  demoSafe: boolean;
  loaded: boolean;
}

const OFF: DemoPosture = {
  on: false,
  label: "",
  detail: "",
  dataRelease: "",
  demoSafe: false,
  loaded: false,
};

const DemoContext = React.createContext<DemoPosture>(OFF);

export function DemoModeProvider({ children }: { children: React.ReactNode }) {
  const [posture, setPosture] = React.useState<DemoPosture>(OFF);

  React.useEffect(() => {
    let live = true;
    api
      .demoPosture()
      .then((body) => {
        if (!live) return;
        setPosture({
          on: Boolean(body.demo_mode),
          label: body.label ?? "",
          detail: body.detail ?? "",
          dataRelease: body.data_release ?? "",
          demoSafe: Boolean(body.demo_safe_mode),
          loaded: true,
        });
      })
      // A backend that cannot be reached is not a demonstration. Staying OFF
      // is the only safe direction to fail in.
      .catch(() => live && setPosture({ ...OFF, loaded: true }));
    return () => {
      live = false;
    };
  }, []);

  return <DemoContext.Provider value={posture}>{children}</DemoContext.Provider>;
}

export function useDemoMode(): DemoPosture {
  return React.useContext(DemoContext);
}

/**
 * The label §4 requires: "clear DEMO / SYNTHETIC DATA label".
 *
 * Rendered in the header, on every screen, for as long as Demo Mode is on.
 * Deliberately not dismissible: a label a client can close is a label they
 * can be shown having closed.
 */
export function DemoBadge() {
  const { on, label, detail, dataRelease } = useDemoMode();
  if (!on) return null;
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-warning/40 bg-warning/10 px-2.5 py-1 text-[11px] font-medium uppercase tracking-wide text-warning"
      title={`${detail} Data release: ${dataRelease}.`}
      data-testid="synthetic-data-badge"
    >
      <span aria-hidden className="size-1.5 rounded-full bg-warning" />
      {label}
    </span>
  );
}
