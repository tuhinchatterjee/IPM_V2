"use client";

import * as React from "react";
import { Check, Pencil, RotateCcw, X } from "lucide-react";

import { ApiError, api, type Preferences } from "@/lib/api";

/**
 * How the Cockpit greets this reader, and the control that changes it.
 *
 * Presentation only. The greeting name is what the screen prints; the account,
 * its role, its permissions and every line of the audit trail are untouched by
 * it. That separation is the reason this lives in its own provider rather than
 * on the auth context: a name kept beside the identity is a name that will
 * eventually be read as one.
 *
 * The provider holds the value so that saving updates the heading immediately
 * — the Cockpit reads the same state the dialog writes, so there is nothing to
 * reload and no moment where the screen and the stored preference disagree.
 */

interface Personalisation {
  greetingName: string;
  isDefault: boolean;
  defaultName: string;
  maxLength: number;
  save: (name: string) => Promise<void>;
  reset: () => Promise<void>;
}

/** Until the preference has loaded, and if it never does. The default is not
 *  a placeholder: it is what an installation greets people by. */
const FALLBACK: Preferences = {
  greeting_name: "Mr. Sajid",
  greeting_name_is_default: true,
  default_greeting_name: "Mr. Sajid",
  max_length: 48,
};

const PersonalisationContext = React.createContext<Personalisation>({
  greetingName: FALLBACK.greeting_name,
  isDefault: true,
  defaultName: FALLBACK.default_greeting_name,
  maxLength: FALLBACK.max_length,
  save: async () => {},
  reset: async () => {},
});

export function PersonalisationProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [prefs, setPrefs] = React.useState<Preferences>(FALLBACK);

  React.useEffect(() => {
    let live = true;
    api
      .preferences()
      .then((found) => {
        if (live) setPrefs(found);
      })
      // A Cockpit that cannot greet anybody because a preference store is
      // unreachable is a worse product than one that greets them by the
      // default name. Nothing is shown about it.
      .catch(() => {});
    return () => {
      live = false;
    };
  }, []);

  const value = React.useMemo<Personalisation>(
    () => ({
      greetingName: prefs.greeting_name,
      isDefault: prefs.greeting_name_is_default,
      defaultName: prefs.default_greeting_name,
      maxLength: prefs.max_length,
      save: async (name: string) => setPrefs(await api.setGreetingName(name)),
      reset: async () => setPrefs(await api.resetGreetingName()),
    }),
    [prefs],
  );

  return (
    <PersonalisationContext.Provider value={value}>
      {children}
    </PersonalisationContext.Provider>
  );
}

export function usePersonalisation(): Personalisation {
  return React.useContext(PersonalisationContext);
}

/** The name the Cockpit greets this reader by. */
export function useGreetingName(): string {
  return usePersonalisation().greetingName;
}

/** "Good afternoon" — by the reader's clock, not the server's. */
function timeOfDay(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
}

/**
 * The header control.
 *
 * A pencil, not a permanently open form. Personalising a greeting is something
 * a person does once; a settings panel that sits on the header forever costs
 * every reader attention for a choice almost none of them will make twice.
 */
export function PersonaliseControl() {
  const { greetingName, isDefault, defaultName, maxLength, save, reset } =
    usePersonalisation();
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState(greetingName);
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const panel = React.useRef<HTMLDivElement>(null);
  const field = React.useRef<HTMLInputElement>(null);

  // Opening seeds the draft from what is stored, so cancelling really cancels
  // rather than leaving a half-typed name behind for next time. Done in the
  // event that opens the panel rather than in an effect that watches it: the
  // draft is a consequence of the click, and deriving it from state changes
  // would re-seed the field under somebody who is still typing.
  const openPanel = React.useCallback(() => {
    setDraft(greetingName);
    setError(null);
    setOpen(true);
  }, [greetingName]);

  // The effect only touches the DOM, which is what an effect is for.
  React.useEffect(() => {
    if (open) {
      field.current?.focus();
      field.current?.select();
    }
  }, [open]);

  React.useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (panel.current && !panel.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    const escape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const commit = React.useCallback(
    async (run: () => Promise<void>) => {
      setBusy(true);
      setError(null);
      try {
        await run();
        setOpen(false);
      } catch (e) {
        // The server owns what a name may be, and says why in words a person
        // can act on. Repeating the rule here would be a second copy of it.
        setError(
          e instanceof ApiError
            ? e.message
            : "That could not be saved. Try again.",
        );
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  return (
    <div className="relative" ref={panel}>
      <button
        type="button"
        onClick={() => (open ? setOpen(false) : openPanel())}
        aria-label="Personalise the Cockpit"
        aria-expanded={open}
        aria-haspopup="dialog"
        title="Personalise"
        className="flex size-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-hover hover:text-text-primary"
      >
        <Pencil className="size-[15px]" aria-hidden />
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Personalise Cockpit"
          className="absolute right-0 z-50 mt-2 w-[288px] rounded-lg border border-border bg-surface p-4 shadow-lg"
        >
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-muted">
            Personalise Cockpit
          </p>

          <label
            htmlFor="greeting-name"
            className="mt-3 block text-[12px] font-medium text-text-secondary"
          >
            Greeting name
          </label>
          <input
            id="greeting-name"
            ref={field}
            value={draft}
            maxLength={maxLength}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !busy) void commit(() => save(draft));
            }}
            className="mt-1 w-full rounded-md border border-border bg-surface-raised px-2.5 py-1.5 text-[13px] text-text-primary outline-none focus:border-accent"
          />

          {/* The preview is the point of the control: what you will actually
              read tomorrow morning, not a description of it. */}
          <p className="mt-2.5 text-[11px] uppercase tracking-[0.08em] text-text-muted">
            Preview
          </p>
          <p className="mt-1 text-[15px] leading-snug text-text-primary">
            {timeOfDay()}
            {draft.trim() && (
              <>
                ,{" "}
                <em className="font-normal italic text-accent">
                  {draft.trim()}
                </em>
              </>
            )}
          </p>

          {error && (
            <p role="alert" className="mt-2 text-[12px] leading-snug text-danger">
              {error}
            </p>
          )}

          <div className="mt-3.5 flex items-center justify-between gap-2">
            <button
              type="button"
              disabled={busy || isDefault}
              onClick={() => void commit(reset)}
              className="flex items-center gap-1 text-[12px] text-text-muted transition-colors hover:text-text-primary disabled:opacity-40"
              title={`Reset to ${defaultName}`}
            >
              <RotateCcw className="size-3" aria-hidden />
              Reset
            </button>
            <div className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => setOpen(false)}
                className="flex items-center gap-1 rounded-md px-2 py-1 text-[12px] text-text-secondary transition-colors hover:bg-surface-hover"
              >
                <X className="size-3" aria-hidden />
                Cancel
              </button>
              <button
                type="button"
                disabled={busy || !draft.trim()}
                onClick={() => void commit(() => save(draft))}
                className="flex items-center gap-1 rounded-md bg-accent px-2.5 py-1 text-[12px] font-medium text-accent-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
              >
                <Check className="size-3" aria-hidden />
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
