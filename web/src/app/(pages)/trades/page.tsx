"use client";

import { useState } from "react";
import { ArrowLeftRight } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Empty, PageHeader, RangeBar, Stat } from "@/components/app/bits";
import { useApi, type Trade } from "@/lib/api";
import { dateTime, money, num, signedMoney, timeAgo, tone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const REASON_VARIANT: Record<string, "gain" | "loss" | "warn" | "muted"> = {
  target: "gain",
  stop: "loss",
  "kill switch": "loss",
  "15:50 close": "warn",
  "time stop": "warn",
};

export default function TradesPage() {
  const { t, lang } = useI18n();
  const [filter, setFilter] = useState<"all" | "open" | "closed">("all");
  const { data } = useApi<Trade[]>(`/trades?status=${filter}`);
  const [sel, setSel] = useState<Trade | null>(null);
  const closed = data?.filter((d) => d.pnl != null && d.exit_reason !== "demo restart") ?? [];
  const total = closed.reduce((s, d) => s + (d.pnl ?? 0), 0);
  const wins = closed.filter((d) => (d.pnl ?? 0) > 0).length;
  const avgR = closed.length ? closed.reduce((s, d) => s + (d.r_multiple ?? 0), 0) / closed.length : 0;

  return (
    <>
      <PageHeader title={t("trades")} description="Every trade, its reason, and how it ended. Click a row for the full story." />
      <div className="mb-4 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Closed trades" value={closed.length} />
        <Stat label="Total P&L" value={signedMoney(total)} valueClass={tone(total)} />
        <Stat label={t("winRate")} value={closed.length ? `${Math.round((wins / closed.length) * 100)}%` : "—"} />
        <Stat label="Average R" value={closed.length ? `${num(avgR, 2)}R` : "—"} valueClass={tone(avgR)} />
      </div>
      <Tabs value={filter} onValueChange={(v) => setFilter(v as typeof filter)} className="mb-3">
        <TabsList>
          <TabsTrigger value="all">All</TabsTrigger>
          <TabsTrigger value="open">Open</TabsTrigger>
          <TabsTrigger value="closed">Closed</TabsTrigger>
        </TabsList>
      </Tabs>
      <Card className="py-2">
        <CardContent className="px-2">
          {!data ? (
            <Skeleton className="m-2 h-40" />
          ) : !data.length ? (
            <div className="p-4">
              <Empty icon={<ArrowLeftRight />}>No trades yet. Approve an idea to place your first trade.</Empty>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Stock</TableHead>
                  <TableHead>Opened</TableHead>
                  <TableHead className="text-end">Qty</TableHead>
                  <TableHead className="text-end">Entry</TableHead>
                  <TableHead className="text-end">Exit</TableHead>
                  <TableHead>Result</TableHead>
                  <TableHead className="text-end">P&amp;L</TableHead>
                  <TableHead className="text-end">R</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.map((r) => {
                  const pnl = r.pnl ?? r.unrealized ?? null;
                  return (
                    <TableRow key={r.id} className="cursor-pointer" onClick={() => setSel(r)}>
                      <TableCell>
                        <div className="font-medium">{r.symbol}</div>
                        <div className="text-muted-foreground text-xs">{r.sector}</div>
                      </TableCell>
                      <TableCell className="text-muted-foreground text-xs">{dateTime(r.opened_at)}</TableCell>
                      <TableCell className="tabular text-end">{r.qty}</TableCell>
                      <TableCell className="tabular text-end">{money(r.entry_price)}</TableCell>
                      <TableCell className="tabular text-end">{r.exit_price ? money(r.exit_price) : money(r.price)}</TableCell>
                      <TableCell>
                        {r.closed_at ? (
                          <Badge variant={REASON_VARIANT[r.exit_reason ?? ""] ?? "muted"}>{r.exit_reason}</Badge>
                        ) : (
                          <Badge variant="secondary" className="gap-1.5">
                            <span className="bg-gain size-1.5 animate-pulse rounded-full" /> open
                          </Badge>
                        )}
                      </TableCell>
                      <TableCell className={cn("tabular text-end font-medium", tone(pnl))}>{signedMoney(pnl)}</TableCell>
                      <TableCell className={cn("tabular text-end", tone(r.r_multiple ?? r.r_now))}>{num(r.r_multiple ?? r.r_now, 1)}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <Sheet open={!!sel} onOpenChange={(o) => !o && setSel(null)}>
        <SheetContent side={lang === "ar" ? "left" : "right"} className="overflow-y-auto">
          {sel && (
            <>
              <SheetHeader className="border-b p-5">
                <SheetTitle className="text-xl">
                  {sel.symbol} · {sel.qty} shares
                </SheetTitle>
                <SheetDescription>
                  Opened {dateTime(sel.opened_at)} in {sel.mode} mode
                  {sel.closed_at && ` · closed ${dateTime(sel.closed_at)} (${sel.exit_reason})`}
                </SheetDescription>
              </SheetHeader>
              <div className="space-y-6 px-5 pb-6">
                <div className="grid grid-cols-3 gap-3">
                  <Stat label="Entry" value={money(sel.entry_price)} />
                  <Stat label={sel.closed_at ? "Exit" : "Now"} value={money(sel.exit_price ?? sel.price)} />
                  <Stat label="P&L" value={signedMoney(sel.pnl ?? sel.unrealized)} valueClass={tone(sel.pnl ?? sel.unrealized)} />
                </div>
                <div className="space-y-2">
                  <div className="text-sm font-medium">Stop → target</div>
                  <RangeBar stop={sel.initial_stop} entry={sel.entry_price} target={sel.target} price={sel.exit_price ?? sel.price} />
                  <div className="tabular text-muted-foreground flex justify-between text-xs">
                    <span>initial stop {money(sel.initial_stop)}</span>
                    <span>target {money(sel.target)}</span>
                  </div>
                </div>
                {sel.thesis && (
                  <div>
                    <div className="mb-1 text-sm font-medium">Why we bought it</div>
                    <p className="text-muted-foreground text-sm leading-relaxed">{sel.thesis}</p>
                  </div>
                )}
                <div>
                  <div className="mb-2 text-sm font-medium">Timeline</div>
                  <ol className="space-y-3 border-s ps-4 text-sm">
                    <li>
                      <span className="text-muted-foreground text-xs">{timeAgo(sel.opened_at)}</span>
                      <div>
                        Bought {sel.qty} @ {money(sel.entry_price)} with stop {money(sel.initial_stop)}
                      </div>
                    </li>
                    {sel.notes.map((n) => (
                      <li key={n.at + n.note}>
                        <span className="text-muted-foreground text-xs">{timeAgo(n.at)}</span>
                        <div>{n.note}</div>
                      </li>
                    ))}
                    {sel.closed_at && (
                      <li>
                        <span className="text-muted-foreground text-xs">{timeAgo(sel.closed_at)}</span>
                        <div>
                          Closed @ {money(sel.exit_price)} — {sel.exit_reason}, {signedMoney(sel.pnl)}
                        </div>
                      </li>
                    )}
                  </ol>
                </div>
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </>
  );
}
