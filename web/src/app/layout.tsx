import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import { ThemeProvider } from "next-themes";

import "./globals.css";
import { AppShell } from "@/components/app/app-shell";
import { TooltipProvider } from "@/components/ui/misc";
import { AiProvider } from "@/lib/ai";
import { I18nProvider } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "Rahbeh — AI trading terminal",
  description: "A team of AI agents that watches the market, explains every idea, and trades only inside the limits you set.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-dvh antialiased">
        <ThemeProvider attribute="class" defaultTheme="dark" enableSystem={false} disableTransitionOnChange>
          <I18nProvider>
            <AiProvider>
              <TooltipProvider>
                <AppShell>{children}</AppShell>
              </TooltipProvider>
            </AiProvider>
          </I18nProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
