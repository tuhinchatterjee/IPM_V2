import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import { AppShell } from "@/components/layout/app-shell";
import { RoleProvider } from "@/components/system/role-switcher";
import { ThemeProvider, ThemeScript } from "@/components/system/theme-provider";

import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: "IPM — Credit Portfolio Intelligence & Monitoring",
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
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        <ThemeProvider>
          <RoleProvider>
            <AppShell>{children}</AppShell>
          </RoleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
