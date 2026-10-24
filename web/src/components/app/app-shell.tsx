"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Menu, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Toaster } from "sonner";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/misc";
import { AiButton, AiPanel } from "@/components/app/ai-panel";
import { KillSwitch } from "@/components/app/kill-switch";
import { MoodChip } from "@/components/app/mood-chip";
import { useApi, type Dashboard, type Status } from "@/lib/api";
import { signedMoney, timeAgo, tone } from "@/lib/format";
import { useI18n, type Key } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const NAV: { href: string; key: Key }[] = [
  { href: "/", key: "chart" },
  { href: "/deals", key: "deals" },
  { href: "/lab", key: "lab" },
  { href: "/portfolio", key: "portfolio" },
  { href: "/agents", key: "agents" },
  { href: "/ideas", key: "ideas" },
  { href: "/trades", key: "trades" },
  { href: "/log", key: "log" },
  { href: "/review", key: "review" },
  { href: "/settings", key: "settings" },
];

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2">
      <span className="bg-foreground text-background grid size-7 place-items-center rounded-sm">
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="square">
          <path d="M3 17l6-6 4 4 8-8" />
        </svg>
      </span>
      <span className="text-[15px] font-bold tracking-tight">RAHBEH</span>
    </Link>
  );
}

function NavLinks({ vertical, pending, onNavigate }: { vertical?: boolean; pending: number; onNavigate?: () => void }) {
  const path = usePathname();
  const { t } = useI18n();
  return (
    <nav className={cn("flex", vertical ? "flex-col gap-0.5" : "items-center gap-0.5")}>
      {NAV.map(({ href, key }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "relative flex items-center gap-1.5 rounded-sm px-2.5 py-1.5 text-[13px] font-medium whitespace-nowrap transition-colors",
              active ? "text-foreground" : "text-muted-foreground hover:text-foreground hover:bg-accent",
              active && !vertical && "after:bg-foreground after:absolute after:inset-x-2.5 after:-bottom-[9px] after:h-0.5",
              active && vertical && "bg-accent",
            )}
          >
            {t(key)}
            {key === "ideas" && pending > 0 && (
              <span className="bg-foreground text-background grid min-w-4 place-items-center rounded-sm px-1 font-mono text-[10px] font-bold">{pending}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
      aria-label="Toggle black / white theme"
    >
      <Sun className="hidden dark:block" />
      <Moon className="dark:hidden" />
    </Button>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const { lang, setLang, t } = useI18n();
  const { resolvedTheme } = useTheme();
  const { data: status } = useApi<Status>("/status");
  const { data: dash } = useApi<Dashboard>("/dashboard");
  const pending = dash?.pending_proposals ?? 0;

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="bg-background sticky top-0 z-40 flex h-12 shrink-0 items-center gap-3 border-b px-3">
        <Button variant="ghost" size="icon-sm" className="xl:hidden" onClick={() => setOpen(true)} aria-label="Menu">
          <Menu />
        </Button>
        <Logo />
        <div className="ms-3 hidden xl:block">
          <NavLinks pending={pending} />
        </div>

        <div className="ms-auto flex items-center gap-1.5">
          {status && (
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="hidden items-center gap-2 border-e pe-3 font-mono text-[11px] md:flex">
                  <span className={cn("size-1.5 rounded-full", status.market_open ? "bg-gain animate-pulse" : "bg-muted-foreground")} />
                  <span className="text-muted-foreground uppercase">{status.demo ? "demo" : status.broker.includes("paper") ? "paper" : "live"}</span>
                  {dash && (
                    <>
                      <span className="text-muted-foreground">EQ</span>
                      <span>{dash.account.equity.toLocaleString("en-US", { maximumFractionDigits: 0 })}</span>
                      <span className={tone(dash.account.day_pnl)}>{signedMoney(dash.account.day_pnl)}</span>
                    </>
                  )}
                </div>
              </TooltipTrigger>
              <TooltipContent>
                {status.market_source} data · {status.broker} broker · agents: {status.claude ? status.model : "rule-based (no Claude key)"} · {t(`mode_${status.mode}` as Key)} mode · last scan {timeAgo(status.last_cycle)}
              </TooltipContent>
            </Tooltip>
          )}
          <MoodChip />
          <AiButton />
          <ThemeToggle />
          <Button variant="ghost" size="sm" onClick={() => setLang(lang === "en" ? "ar" : "en")} className="px-2 font-semibold">
            {lang === "en" ? "ع" : "EN"}
          </Button>
          <KillSwitch on={status?.kill_switch ?? false} />
        </div>
      </header>

      {status?.kill_switch && (
        <div className="bg-loss/10 border-loss/40 text-loss border-b px-4 py-1.5 text-center text-xs font-semibold tracking-wide uppercase">
          Kill switch on — all positions closed, no new trades
        </div>
      )}

      <main className="flex min-h-0 flex-1 flex-col">{children}</main>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={lang === "ar" ? "right" : "left"} className="w-64 px-3 py-4">
          <SheetTitle className="px-2">
            <Logo />
          </SheetTitle>
          <NavLinks vertical pending={pending} onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
      <AiPanel />
      <Toaster theme={resolvedTheme === "light" ? "light" : "dark"} position="bottom-left" toastOptions={{ className: "!rounded-md" }} />
    </div>
  );
}
