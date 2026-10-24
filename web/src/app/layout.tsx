import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "@fontsource/ibm-plex-sans-arabic/400.css";
import "@fontsource/ibm-plex-sans-arabic/500.css";
import "@fontsource/ibm-plex-sans-arabic/600.css";
import { Toaster } from "sonner";

import "./globals.css";
import { AppShell } from "@/components/app/app-shell";
import { TooltipProvider } from "@/components/ui/misc";
import { I18nProvider } from "@/lib/i18n";

export const metadata: Metadata = {
  title: "Rahbeh — AI trading agents",
  description: "A team of AI agents that watches the market, explains every idea, and trades only inside the limits you set.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${GeistSans.variable} ${GeistMono.variable}`} suppressHydrationWarning>
      <body className="min-h-dvh antialiased">
        <I18nProvider>
          <TooltipProvider>
            <AppShell>{children}</AppShell>
            <Toaster theme="dark" richColors position="bottom-right" />
          </TooltipProvider>
        </I18nProvider>
      </body>
    </html>
  );
}
