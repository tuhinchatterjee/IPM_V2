import type { Metadata } from "next";
import {
  Geist,
  JetBrains_Mono,
  Plus_Jakarta_Sans,
  Space_Grotesk,
} from "next/font/google";

import { AuthProvider } from "@/components/system/auth";
import { AppShell } from "@/components/layout/app-shell";
import { RoleProvider } from "@/components/system/role-switcher";
import { ThemeProvider, ThemeScript } from "@/components/system/theme-provider";

import "./globals.css";

/**
 * Four typefaces, each with one job.
 *
 * A single family across a product like this flattens a real distinction: what
 * CreditProbe wrote, what you asked, what the machine recorded, and what you can
 * act on are four different kinds of text, and a reader should be able to tell
 * them apart without reading them.
 *
 *   Geist            — CreditProbe's prose. Interpretation, findings, narrative.
 *   Plus Jakarta     — your words. Questions, prompts, what you typed.
 *   JetBrains Mono   — the machine's record. Identifiers, versions, periods,
 *                      field names, hashes. Anything you might copy exactly.
 *   Space Grotesk    — things you act on and figures you read at a glance.
 *
 * All four are open, served from Google Fonts, and subset to latin. Nothing here
 * depends on a font being installed locally.
 */
const geist = Geist({ variable: "--font-prose", subsets: ["latin"] });
const jakarta = Plus_Jakarta_Sans({
  variable: "--font-user",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});
const jetbrains = JetBrains_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
});
const grotesk = Space_Grotesk({
  variable: "--font-display",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "CreditProbe AI — Credit Portfolio Intelligence",
  description:
    "An AI-native credit-risk analytical platform. Every figure is produced by a deterministic, tested engine and is fully traceable.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  // suppressHydrationWarning: ThemeScript sets data-theme on <html> before React
  // hydrates, so the server and client markup differ by that one attribute on
  // purpose. Without the script there would be a visible flash of the wrong theme.
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <ThemeScript />
      </head>
      <body
        className={`${geist.variable} ${jakarta.variable} ${jetbrains.variable} ${grotesk.variable} antialiased`}
      >
        <ThemeProvider>
          <AuthProvider>
            <RoleProvider>
              <AppShell>{children}</AppShell>
            </RoleProvider>
          </AuthProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
