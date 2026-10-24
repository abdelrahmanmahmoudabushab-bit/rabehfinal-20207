"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { MessageCircle, Moon, Search } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/misc";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Switch } from "@/components/ui/switch";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { PageHeader, Sparkline, Stat } from "@/components/app/bits";
import { PriceChart } from "@/components/app/charts";
import { useApi, type MarketRow, type StockDetail } from "@/lib/api";
import { money, num, pct, timeAgo, tone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

type SortKey = "change_day_pct" | "change_30m_pct" | "volume_ratio" | "momentum";

export default function MarketPage() {
  const { t } = useI18n();
  const { data } = useApi<MarketRow[]>("/market", { refreshInterval: 10000 });
  const [q, setQ] = useState("");
  const [halalOnly, setHalalOnly] = useState(false);
  const [sort, setSort] = useState<SortKey>("momentum");
  const [sel, setSel] = useState<string | null>(null);

  const rows = useMemo(() => {
    const s = q.trim().toLowerCase();
    return (data ?? [])
      .filter((r) => (!halalOnly || r.halal) && (!s || r.symbol.toLowerCase().includes(s) || r.name.toLowerCase().includes(s)))
      .sort((a, b) => b[sort] - a[sort]);
  }, [data, q, halalOnly, sort]);

  const head = (k: SortKey, label: string) => (
    <TableHead className={cn("cursor-pointer text-end select-none", sort === k && "text-foreground")} onClick={() => setSort(k)}>
      {label}
      {sort === k && " ↓"}
    </TableHead>
  );

  return (
    <>
      <PageHeader title={t("market")} description="The stocks the scanner watches, with the same numbers the agents see. Click a row for chart, news and company checks." />
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <div className="relative w-full max-w-xs">
          <Search className="text-muted-foreground absolute start-3 top-1/2 size-4 -translate-y-1/2" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search stocks" className="ps-9" />
        </div>
        <Label className="text-muted-foreground cursor-pointer gap-2 font-normal">
          <Switch checked={halalOnly} onCheckedChange={setHalalOnly} /> Halal only
        </Label>
      </div>
      <Card className="py-2">
        <CardContent className="px-2">
          {!data ? (
            <Skeleton className="m-2 h-96" />
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Stock</TableHead>
                  <TableHead className="hidden md:table-cell">Last hour</TableHead>
                  <TableHead className="text-end">Price</TableHead>
                  {head("change_day_pct", "Today")}
                  {head("change_30m_pct", "30 min")}
                  {head("volume_ratio", "Volume")}
                  <TableHead className="hidden text-end sm:table-cell">RSI</TableHead>
                  {head("momentum", "Momentum")}
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.symbol} className="cursor-pointer" onClick={() => setSel(r.symbol)}>
                    <TableCell>
                      <div className="flex items-center gap-2 font-medium">
                        {r.symbol}
                        {r.halal && <Badge variant="gain" className="px-1.5 py-0 text-[10px]">halal</Badge>}
                        {r.paused && <Badge variant="warn">paused</Badge>}
                      </div>
                      <div className="text-muted-foreground max-w-40 truncate text-xs">{r.name}</div>
                    </TableCell>
                    <TableCell className="hidden md:table-cell">
                      <Sparkline data={r.spark} />
                    </TableCell>
                    <TableCell className="tabular text-end">{money(r.price)}</TableCell>
                    <TableCell className={cn("tabular text-end", tone(r.change_day_pct))}>{pct(r.change_day_pct)}</TableCell>
                    <TableCell className={cn("tabular text-end", tone(r.change_30m_pct))}>{pct(r.change_30m_pct)}</TableCell>
                    <TableCell className={cn("tabular text-end", r.volume_ratio >= 1.8 && "text-warn font-medium")}>{num(r.volume_ratio, 1)}x</TableCell>
                    <TableCell className="tabular hidden text-end sm:table-cell">{num(r.rsi, 0)}</TableCell>
                    <TableCell className="text-end">
                      <MomentumBar v={r.momentum} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
      <StockSheet symbol={sel} onClose={() => setSel(null)} />
    </>
  );
}

function MomentumBar({ v }: { v: number }) {
  const w = Math.min(100, Math.abs(v));
  return (
    <div className="ms-auto flex w-24 items-center gap-2">
      <div className="bg-muted relative h-1.5 flex-1 overflow-hidden rounded-full">
        <div className={cn("absolute inset-y-0 start-0 rounded-full", v >= 0 ? "bg-gain" : "bg-loss")} style={{ width: `${w}%` }} />
      </div>
      <span className="tabular w-7 text-end text-xs">{Math.round(v)}</span>
    </div>
  );
}

function StockSheet({ symbol, onClose }: { symbol: string | null; onClose: () => void }) {
  const { lang } = useI18n();
  const { data } = useApi<StockDetail>(symbol ? `/stock/${symbol}` : null, { refreshInterval: 10000 });
  const f = data?.features;
  const up = f ? Number(f.change_day_pct) >= 0 : true;
  return (
    <Sheet open={!!symbol} onOpenChange={(o) => !o && onClose()}>
      <SheetContent side={lang === "ar" ? "left" : "right"} className="overflow-y-auto">
        <SheetHeader className="border-b p-5">
          <SheetTitle className="text-xl">
            {symbol} <span className="text-muted-foreground text-sm font-normal">{data?.company?.name}</span>
          </SheetTitle>
          <SheetDescription>
            {data?.company ? `${data.company.sector} · ${data.company.industry}` : "Loading…"}
          </SheetDescription>
        </SheetHeader>
        {!data || !f ? (
          <Skeleton className="mx-5 h-64" />
        ) : (
          <div className="space-y-6 px-5 pb-6">
            <div className="flex items-end gap-3">
              <span className="tabular text-3xl font-semibold">{money(Number(f.price))}</span>
              <span className={cn("tabular pb-1 text-sm font-medium", tone(Number(f.change_day_pct)))}>{pct(Number(f.change_day_pct))} today</span>
            </div>
            <div className="h-52">
              <PriceChart data={data.bars} up={up} />
            </div>
            <div className="grid grid-cols-3 gap-3">
              <Stat label="Trend" value={String(f.trend)} />
              <Stat label="RSI (14)" value={num(Number(f.rsi14), 0)} />
              <Stat label="Volume" value={`${num(Number(f.volume_ratio), 1)}x`} />
              <Stat label="VWAP" value={money(Number(f.vwap))} sub={f.above_vwap ? "price above" : "price below"} />
              <Stat label="30 min" value={pct(Number(f.change_30m_pct))} valueClass={tone(Number(f.change_30m_pct))} />
              <Stat label="LAYA" value={data.laya.worth_a_look ? "Look" : "Pass"} valueClass={data.laya.worth_a_look ? "text-gain" : "text-muted-foreground"} />
            </div>

            <div className={cn("rounded-lg border p-4", data.halal.passes ? "border-gain/30 bg-gain/5" : "border-loss/30 bg-loss/5")}>
              <div className="flex items-center gap-2 text-sm font-medium">
                <Moon className="size-4" /> {data.halal.passes ? "Passes the halal screen" : "Fails the halal screen"}
              </div>
              <div className="text-muted-foreground mt-1 text-xs">
                {data.halal.passes
                  ? `Debt ${Math.round((data.halal.debt_ratio ?? 0) * 100)}% and cash ${Math.round((data.halal.cash_ratio ?? 0) * 100)}% of market value, both under 30%.`
                  : data.halal.reasons.join(" · ")}
              </div>
            </div>

            {data.company && (
              <div className="grid grid-cols-3 gap-3">
                <Stat label="Market value" value={`$${num(data.company.market_cap_b, 0)}B`} />
                <Stat label="Revenue" value={`$${num(data.company.revenue_b, 0)}B`} />
                <Stat label="Net margin" value={data.company.net_margin != null ? `${Math.round(data.company.net_margin * 100)}%` : "—"} />
              </div>
            )}

            <div>
              <div className="mb-2 text-sm font-medium">News</div>
              {data.news.length ? (
                <ul className="space-y-2.5">
                  {data.news.map((n) => (
                    <li key={n.headline + n.at} className="text-sm">
                      {n.headline}
                      <div className="text-muted-foreground text-xs">
                        {n.source} · {timeAgo(n.at)}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-muted-foreground text-sm">No recent company news.</p>
              )}
            </div>

            <Button variant="outline" asChild className="w-full">
              <Link href={`/coach?symbol=${symbol}`}>
                <MessageCircle /> Ask the Coach about {symbol}
              </Link>
            </Button>
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
