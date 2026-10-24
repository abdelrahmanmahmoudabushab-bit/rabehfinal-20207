"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRight, Bell, Radar, RefreshCw, Sparkles, X } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty, PageHeader, RangeBar, Stat } from "@/components/app/bits";
import { PerformanceChart } from "@/components/app/charts";
import { ProposalCard } from "@/components/app/proposal";
import { api, refreshAll, useApi, type Dashboard, type Proposal, type Trade } from "@/lib/api";
import { money, num, pct, signedMoney, timeAgo, tone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function PortfolioPage() {
  const { t } = useI18n();
  const { data } = useApi<Dashboard>("/dashboard");
  const { data: ideas } = useApi<Proposal[]>("/proposals?status=open");
  const [scanning, setScanning] = useState(false);

  async function scan() {
    setScanning(true);
    try {
      const r = await api.post<Record<string, unknown>>("/scan");
      toast.success("Scan finished", {
        description: r.skipped ? String(r.skipped) : `${r.checked} checked · ${r.laya_yes} worth a look · ${r.proposals} new idea(s)`,
      });
      refreshAll();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setScanning(false);
    }
  }

  return (
    <>
      <PageHeader title={t("portfolio")} description="What your agents see, what they hold, and how they're doing against simply holding the S&P 500.">
        <Button variant="outline" onClick={scan} disabled={scanning}>
          <RefreshCw className={cn(scanning && "animate-spin")} /> {t("scanNow")}
        </Button>
      </PageHeader>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {data ? (
          <>
            <Stat label={t("equity")} value={money(data.account.equity)} sub={`Cash ${money(data.account.cash, 0)}`} />
            <Stat
              label={t("today")}
              value={signedMoney(data.account.day_pnl)}
              valueClass={tone(data.account.day_pnl)}
              sub={pct(data.account.day_pnl_pct)}
            />
            <Stat
              label={t("vsSp500")}
              value={pct(data.scoreboard.you_pct - data.scoreboard.sp500_pct)}
              valueClass={tone(data.scoreboard.you_pct - data.scoreboard.sp500_pct)}
              sub={`You ${pct(data.scoreboard.you_pct)} · S&P ${pct(data.scoreboard.sp500_pct)}`}
            />
            <Stat
              label={t("winRate")}
              value={data.scoreboard.trades ? `${Math.round(data.scoreboard.win_rate * 100)}%` : "—"}
              sub={`${data.scoreboard.trades} trades · ${signedMoney(data.scoreboard.total_pnl)}`}
            />
          </>
        ) : (
          Array.from({ length: 4 }).map((_, i) => <Skeleton key={i} className="h-[106px] rounded-md" />)
        )}
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>{t("performance")}</CardTitle>
            <CardDescription>Including every losing trade. No cherry-picking.</CardDescription>
            <CardAction className="flex items-center gap-3 text-xs">
              <span className="flex items-center gap-1.5">
                <span className="bg-chart-1 size-2 rounded-full" /> You
              </span>
              <span className="text-muted-foreground flex items-center gap-1.5">
                <span className="bg-chart-2 size-2 rounded-full" /> S&amp;P 500
              </span>
            </CardAction>
          </CardHeader>
          <CardContent className="h-64">
            {data && data.curve.length > 1 ? (
              <PerformanceChart data={data.curve} />
            ) : (
              <Skeleton className="h-full w-full" />
            )}
          </CardContent>
        </Card>
        <BriefingCard />
      </div>

      <Card className="mt-4">
        <CardHeader>
          <CardTitle>{t("openPositions")}</CardTitle>
          <CardDescription>Stops and targets are held at the broker. Stops rise as trades work; everything closes by 15:50 ET.</CardDescription>
        </CardHeader>
        <CardContent>
          {data?.positions.length ? <PositionsTable rows={data.positions} /> : <Empty icon={<Radar />}>{t("noPositions")}</Empty>}
        </CardContent>
      </Card>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <div className="space-y-3 lg:col-span-2">
          <div className="flex items-center justify-between">
            <h2 className="font-semibold">{t("ideas")}</h2>
            <Button variant="ghost" size="sm" asChild>
              <Link href="/ideas">
                All <ArrowRight className="rtl:rotate-180" />
              </Link>
            </Button>
          </div>
          {ideas?.length ? (
            <div className="grid gap-3 md:grid-cols-2">
              {ideas.slice(0, 2).map((p) => (
                <ProposalCard key={p.id} p={p} />
              ))}
            </div>
          ) : (
            <Empty icon={<Sparkles />}>{t("noIdeas")}</Empty>
          )}
        </div>
        <AlertsCard data={data} />
      </div>
    </>
  );
}

function PositionsTable({ rows }: { rows: Trade[] }) {
  const [busy, setBusy] = useState<number | null>(null);
  async function close(id: number, sym: string) {
    setBusy(id);
    try {
      await api.post(`/trades/${id}/close`);
      toast.success(`Closed ${sym}`);
      refreshAll();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  }
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Stock</TableHead>
          <TableHead className="text-end">Qty</TableHead>
          <TableHead className="text-end">Entry</TableHead>
          <TableHead className="text-end">Price</TableHead>
          <TableHead className="text-end">P&amp;L</TableHead>
          <TableHead className="min-w-40">Stop → Target</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((r) => (
          <TableRow key={r.id}>
            <TableCell>
              <div className="font-medium">{r.symbol}</div>
              <div className="text-muted-foreground text-xs">{timeAgo(r.opened_at)}</div>
            </TableCell>
            <TableCell className="tabular text-end">{r.qty}</TableCell>
            <TableCell className="tabular text-end">{money(r.entry_price)}</TableCell>
            <TableCell className="tabular text-end">{money(r.price)}</TableCell>
            <TableCell className={cn("tabular text-end font-medium", tone(r.unrealized))}>
              {signedMoney(r.unrealized)}
              <div className="text-xs font-normal">{r.r_now != null ? `${num(r.r_now, 1)}R` : ""}</div>
            </TableCell>
            <TableCell>
              <RangeBar stop={r.stop} entry={r.entry_price} target={r.target} price={r.price} />
              <div className="tabular text-muted-foreground mt-1.5 flex justify-between text-[11px]">
                <span className="text-loss">{money(r.stop)}</span>
                <span className="text-gain">{money(r.target)}</span>
              </div>
            </TableCell>
            <TableCell className="text-end">
              <Button variant="ghost" size="icon-sm" disabled={busy === r.id} onClick={() => close(r.id, r.symbol)} aria-label="Close position">
                <X />
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function BriefingCard() {
  const { t, lang } = useI18n();
  const { data, mutate, isLoading } = useApi<{ body: string; at: string; source: string }>(`/briefing?lang=${lang}`, { refreshInterval: 0 });
  const [busy, setBusy] = useState(false);
  async function regenerate() {
    setBusy(true);
    try {
      await mutate(await api.get(`/briefing?lang=${lang}&force=true`), { revalidate: false });
    } finally {
      setBusy(false);
    }
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Sparkles className="size-4" /> {t("briefing")}
        </CardTitle>
        <CardDescription>{data ? `${data.source === "claude" ? "Coach agent" : "Template"} · ${timeAgo(data.at)}` : "…"}</CardDescription>
        <CardAction>
          <Button variant="ghost" size="icon-sm" onClick={regenerate} disabled={busy} aria-label="Refresh briefing">
            <RefreshCw className={cn(busy && "animate-spin")} />
          </Button>
        </CardAction>
      </CardHeader>
      <CardContent>
        {isLoading || !data ? (
          <div className="space-y-2">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-4/6" />
          </div>
        ) : (
          <div className="space-y-3 text-sm leading-relaxed whitespace-pre-line">{data.body}</div>
        )}
      </CardContent>
    </Card>
  );
}

function AlertsCard({ data }: { data?: Dashboard }) {
  const { t } = useI18n();
  return (
    <Card className="gap-3">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Bell className="size-4" /> {t("alerts")}
          {!!data?.unread_alerts && <Badge variant="warn">{data.unread_alerts}</Badge>}
        </CardTitle>
        <CardAction>
          {!!data?.unread_alerts && (
            <Button
              variant="ghost"
              size="sm"
              onClick={async () => {
                await api.post("/alerts/read");
                refreshAll();
              }}
            >
              Mark read
            </Button>
          )}
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-1">
        {data?.alerts.length ? (
          data.alerts.map((a) => (
            <div key={a.id} className="flex gap-3 rounded-lg px-2 py-2">
              <span
                className={cn(
                  "mt-1.5 size-2 shrink-0 rounded-full",
                  a.level === "critical" ? "bg-loss" : a.level === "warn" ? "bg-warn" : "bg-primary",
                  a.read && "opacity-30",
                )}
              />
              <div className="min-w-0">
                <div className="truncate text-sm font-medium">{a.title}</div>
                {a.body && <div className="text-muted-foreground line-clamp-2 text-xs">{a.body}</div>}
                <div className="text-muted-foreground mt-0.5 text-[11px]">{timeAgo(a.at)}</div>
              </div>
            </div>
          ))
        ) : (
          <p className="text-muted-foreground text-sm">Nothing yet.</p>
        )}
      </CardContent>
    </Card>
  );
}
