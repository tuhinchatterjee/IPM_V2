"use client";

import * as React from "react";

/**
 * How wide the content column is allowed to be.
 *
 * The shell's default of 1200px is right for a form or a document: a wide
 * screen is not a reason to stretch a paragraph across it. It is wrong for a
 * page whose content IS the width -- a Cockpit with two dashboards, wide
 * tables and a chat column was rendering as a 1128px ribbon on a 1728px
 * display with two empty thirds.
 *
 * So a page asks, rather than the shell guessing from the route: the root
 * route serves whichever Cockpit generation is enabled, and only one of them
 * wants the extra width. `useWideContent()` requests it on mount and gives it
 * back on unmount, so every other page keeps the default untouched.
 */

type ContentWidth = { wide: boolean; request: (wide: boolean) => void };

const ContentWidthContext = React.createContext<ContentWidth>({
  wide: false,
  request: () => {},
});

export function ContentWidthProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const [wide, setWide] = React.useState(false);
  const value = React.useMemo(
    () => ({ wide, request: setWide }),
    [wide],
  );
  return (
    <ContentWidthContext.Provider value={value}>
      {children}
    </ContentWidthContext.Provider>
  );
}

export function useContentWidth(): ContentWidth {
  return React.useContext(ContentWidthContext);
}

/** Ask for the wide column for as long as this component is mounted. */
export function useWideContent(): void {
  const { request } = useContentWidth();
  React.useEffect(() => {
    request(true);
    return () => request(false);
  }, [request]);
}
