"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import {
  ArrowLeftRight,
  ClipboardCheck,
  LayoutDashboard,
  Lightbulb,
  LineChart,
  ListChecks,
  Menu,
  MessageCircle,
  Settings,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/misc";
import { KillSwitch } from "@/components/app/kill-switch";
import { useApi, type Dashboard, type Status } from "@/lib/api";
import { timeAgo } from "@/lib/format";
import { useI18n, type Key } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const NAV: { href: string; key: Key; icon: React.ComponentType<{ className?: string }> }[] = [
  { href: "/", key: "dashboard", icon: LayoutDashboard },
  { href: "/ideas", key: "ideas", icon: Lightbulb },
  { href: "/trades", key: "trades", icon: ArrowLeftRight },
  { href: "/market", key: "market", icon: LineChart },
  { href: "/coach", key: "coach", icon: MessageCircle },
  { href: "/log", key: "log", icon: ListChecks },
  { href: "/review", key: "review", icon: ClipboardCheck },
  { href: "/settings", key: "settings", icon: Settings },
];

export function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="grid size-8 place-items-center rounded-lg bg-gradient-to-br from-emerald-300 to-emerald-600 text-emerald-950 shadow-[0_0_24px_-4px] shadow-emerald-500/50">
        <svg viewBox="0 0 24 24" className="size-4.5" fill="none" stroke="currentColor" strokeWidth={2.6} strokeLinecap="round" strokeLinejoin="round">
          <path d="M4 17l5-5 4 4 7-8" />
          <path d="M15 8h5v5" />
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight">Rahbeh</span>
    </Link>
  );
}

function NavLinks({ onNavigate, pending }: { onNavigate?: () => void; pending: number }) {
  const path = usePathname();
  const { t } = useI18n();
  return (
    <nav className="flex flex-col gap-0.5">
      {NAV.map(({ href, key, icon: Icon }) => {
        const active = href === "/" ? path === "/" : path.startsWith(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            className={cn(
              "group flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors",
              active ? "bg-sidebar-accent text-foreground font-medium" : "text-muted-foreground hover:bg-sidebar-accent/60 hover:text-foreground",
            )}
          >
            <Icon className={cn("size-4", active && "text-primary")} />
            <span className="flex-1">{t(key)}</span>
            {key === "ideas" && pending > 0 && (
              <span className="bg-primary text-primary-foreground grid min-w-5 place-items-center rounded-full px-1.5 text-[11px] font-semibold">
                {pending}
              </span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

function StatusPills({ status }: { status?: Status }) {
  const { t } = useI18n();
  if (!status) return null;
  return (
    <div className="flex items-center gap-2">
      <Tooltip>
        <TooltipTrigger asChild>
          <Badge variant={status.demo ? "warn" : "gain"} className="hidden sm:inline-flex">
            {status.demo ? t("demo") : status.broker.includes("paper") ? t("paper") : t("live")}
          </Badge>
        </TooltipTrigger>
        <TooltipContent>
          Data: {status.market_source} · Broker: {status.broker} · Agents: {status.claude ? status.model : "heuristic (no Claude key)"}
        </TooltipContent>
      </Tooltip>
      <Badge variant="outline" className="gap-1.5">
        <span className={cn("size-1.5 rounded-full", status.market_open ? "bg-gain animate-pulse" : "bg-muted-foreground")} />
        <span className="hidden sm:inline">{status.market_open ? t("marketOpen") : t("marketClosed")}</span>
      </Badge>
      <Badge variant="secondary" className="hidden md:inline-flex">
        {t(`mode_${status.mode}` as Key)}
      </Badge>
      <span className="text-muted-foreground hidden text-xs lg:inline">scan {timeAgo(status.last_cycle)}</span>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const { lang, setLang } = useI18n();
  const { data: status } = useApi<Status>("/status");
  const { data: dash } = useApi<Dashboard>("/dashboard");
  const pending = dash?.pending_proposals ?? 0;

  return (
    <div className="flex min-h-dvh">
      <aside className="bg-sidebar sticky top-0 hidden h-dvh w-60 shrink-0 flex-col gap-6 border-e px-3 py-5 lg:flex">
        <div className="px-2">
          <Logo />
        </div>
        <NavLinks pending={pending} />
        <div className="mt-auto space-y-3 px-1">
          <div className="text-muted-foreground rounded-lg border border-dashed p-3 text-[11px] leading-relaxed">
            Rahbeh never holds your money. Trades go to your own broker, inside the limits you set. Not financial advice.
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="bg-background/80 sticky top-0 z-30 flex h-14 items-center gap-3 border-b px-4 backdrop-blur-md md:px-6">
          <Button variant="ghost" size="icon-sm" className="lg:hidden" onClick={() => setOpen(true)} aria-label="Menu">
            <Menu />
          </Button>
          <div className="lg:hidden">
            <Logo />
          </div>
          <div className="hidden lg:block">
            <StatusPills status={status} />
          </div>
          <div className="ms-auto flex items-center gap-2">
            <div className="lg:hidden">
              <StatusPills status={status} />
            </div>
            <Button variant="ghost" size="sm" onClick={() => setLang(lang === "en" ? "ar" : "en")} className="font-semibold">
              {lang === "en" ? "ع" : "EN"}
            </Button>
            <KillSwitch on={status?.kill_switch ?? false} />
          </div>
        </header>

        {status?.kill_switch && (
          <div className="bg-loss/10 border-loss/30 text-loss border-b px-4 py-2 text-center text-sm font-medium md:px-6">
            Kill switch is ON — all positions closed and no new trades will be placed.
          </div>
        )}

        <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 md:px-6 md:py-8">{children}</main>
      </div>

      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side={lang === "ar" ? "right" : "left"} className="bg-sidebar w-72 px-3 py-5">
          <SheetTitle className="px-2">
            <Logo />
          </SheetTitle>
          <NavLinks pending={pending} onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>
    </div>
  );
}
