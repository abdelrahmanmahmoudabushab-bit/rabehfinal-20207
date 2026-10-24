"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Check, Palette, Search, Sparkles, X } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ProposalSheet } from "@/components/app/proposal";
import { EarningsBlock, FilingsList, RatingsBlock } from "@/components/app/team";
import { TvChart, type Indicators, type Legend } from "@/components/app/tv-chart";
import { useAi } from "@/lib/ai";
import {
  api,
  refreshAll,
  useApi,
  type AlertItem,
  type CandlesResponse,
  type Dashboard,
  type LogRow,
  type MarketRow,
  type Proposal,
  type StockDetail,
  type Trade,
} from "@/lib/api";
import { money, num, pct, signedMoney, timeAgo, tone } from "@/lib/format";
import { cn } from "@/lib/utils";

const TFS = ["1m", "5m", "15m", "1h", "1D"] as const;
type Tf = (typeof TFS)[number];
const IND_LABELS: [keyof Indicators, string][] = [
  ["ema9", "EMA 9"],
  ["ema21", "EMA 21"],
  ["vwap", "VWAP"],
  ["volume", "VOL"],
  ["rsi", "RSI"],
];

export default function TerminalPage() {
  return (
    <Suspense fallback={<Skeleton className="m-4 h-[70vh]" />}>
      <Terminal />
    </Suspense>
  );
}

function compact(n: number) {
  return Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

function Terminal() {
  const params = useSearchParams();
  const router = useRouter();
  const path = usePathname();
  const symbol = (params.get("s") ?? "NVDA").toUpperCase();
  const [tf, setTf] = useState<Tf>("5m");
  const [ind, setInd] = useState<Indicators>({ ema9: true, ema21: true, vwap: true, volume: true, rsi: true });
  const [colored, setColored] = useState(false);
  const [legend, setLegend] = useState<Legend | null>(null);
  const { resolvedTheme } = useTheme();
  const { openAi, setCtx } = useAi();

  const { data: candles } = useApi<CandlesResponse>(`/candles/${symbol}?tf=${tf}&limit=500`, { refreshInterval: 5000 });
  const { data: market } = useApi<MarketRow[]>("/market", { refreshInterval: 5000 });
  const { data: stock } = useApi<StockDetail>(`/stock/${symbol}`, { refreshInterval: 10000 });
  const { data: dash } = useApi<Dashboard>("/dashboard");
  const { data: ideas } = useApi<Proposal[]>("/proposals?status=open");

  useEffect(() => setCtx({ symbol }), [symbol, setCtx]);

  const select = (s: string) => router.replace(`${path}?s=${s}`, { scroll: false });
  const row = market?.find((m) => m.symbol === symbol);
  const bars = candles?.bars ?? [];
  const last = bars[bars.length - 1];
  const prevBar = bars[bars.length - 2];
  const shown: Legend | null =
    legend ?? (last ? { o: last.open, h: last.high, l: last.low, c: last.close, v: last.volume, chg: prevBar ? ((last.close - prevBar.close) / prevBar.close) * 100 : 0 } : null);
  const position = dash?.positions.find((p) => p.symbol === symbol);
  const idea = ideas?.find((p) => p.symbol === symbol);

  return (
    <div className="grid min-h-0 flex-1 lg:h-[calc(100dvh-3rem)] lg:flex-none lg:grid-cols-[236px_minmax(0,1fr)_304px] lg:grid-rows-[minmax(0,1fr)] lg:overflow-hidden">
      <Watchlist rows={market} selected={symbol} onSelect={select} held={dash?.positions ?? []} ideas={ideas ?? []} />

      <section className="flex min-h-0 min-w-0 flex-col lg:border-x">
        {/* toolbar */}
        <div className="flex h-11 shrink-0 items-center gap-1 overflow-x-auto border-b px-2">
          <div className="lg:hidden">
            <Select value={symbol} onValueChange={select}>
              <SelectTrigger size="sm" className="h-8 w-24 font-mono font-bold">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {market?.map((m) => (
                  <SelectItem key={m.symbol} value={m.symbol} className="font-mono">
                    {m.symbol}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="hidden items-baseline gap-2 pe-2 lg:flex">
            <span className="font-mono text-sm font-bold">{symbol}</span>
            <span className="text-muted-foreground max-w-36 truncate text-xs">{row?.name}</span>
          </div>
          <Divider />
          {TFS.map((x) => (
            <ToolBtn key={x} active={tf === x} onClick={() => setTf(x)}>
              {x}
            </ToolBtn>
          ))}
          <Divider />
          {IND_LABELS.map(([k, label]) => (
            <ToolBtn key={k} active={ind[k]} onClick={() => setInd({ ...ind, [k]: !ind[k] })} className="hidden md:inline-flex">
              {label}
            </ToolBtn>
          ))}
          <ToolBtn active={colored} onClick={() => setColored(!colored)} title="Color candles">
            <Palette className="size-3.5" />
          </ToolBtn>
          <div className="ms-auto flex items-center gap-1.5 ps-2">
            <Button size="sm" variant="outline" className="h-8" onClick={() => openAi({ symbol })}>
              Ask AI
            </Button>
            <Button size="sm" className="h-8 gap-1.5" onClick={() => openAi({ symbol }, { action: "analyze" })}>
              <Sparkles /> <span className="hidden sm:inline">Analyze with AI</span>
            </Button>
          </div>
        </div>

        {/* chart */}
        <div className="relative h-[62vh] min-h-[360px] lg:h-auto lg:flex-1">
          {bars.length ? (
            <TvChart
              key={`${symbol}-${tf}`}
              bars={bars}
              trades={candles?.trades ?? []}
              indicators={ind}
              theme={resolvedTheme === "light" ? "light" : "dark"}
              colored={colored}
              onLegend={setLegend}
            />
          ) : (
            <Skeleton className="absolute inset-3" />
          )}
          {shown && (
            <div className="pointer-events-none absolute top-2 start-3 z-10 space-y-0.5 font-mono text-[11px]">
              <div className="flex flex-wrap items-center gap-x-3">
                <span className="font-bold">
                  {symbol} · {tf}
                </span>
                {(["o", "h", "l", "c"] as const).map((k) => (
                  <span key={k}>
                    <span className="text-muted-foreground uppercase">{k}</span> {shown[k].toFixed(2)}
                  </span>
                ))}
                <span className={tone(shown.chg)}>{pct(shown.chg)}</span>
                <span>
                  <span className="text-muted-foreground">VOL</span> {compact(shown.v)}
                </span>
              </div>
              {stock && (
                <div className="text-muted-foreground flex gap-3">
                  <span>RSI {num(Number(stock.features.rsi14), 1)}</span>
                  <span>VWAP {num(Number(stock.features.vwap))}</span>
                  <span>ATR {num(Number(stock.features.atr14))}</span>
                  <span>RVOL {num(Number(stock.features.volume_ratio), 1)}x</span>
                </div>
              )}
            </div>
          )}
        </div>

        <BottomPanel dash={dash} ideas={ideas ?? []} symbol={symbol} onSelect={select} />
      </section>

      <InfoPanel symbol={symbol} row={row} stock={stock} position={position} idea={idea} />
    </div>
  );
}

function Divider() {
  return <span className="bg-border mx-1 h-5 w-px shrink-0" />;
}

function ToolBtn({ active, className, ...props }: React.ComponentProps<"button"> & { active?: boolean }) {
  return (
    <button
      className={cn(
        "inline-flex h-7 shrink-0 cursor-pointer items-center rounded-sm px-2 font-mono text-[11px] font-medium transition-colors",
        active ? "bg-foreground text-background" : "text-muted-foreground hover:bg-accent hover:text-foreground",
        className,
      )}
      {...props}
    />
  );
}

// ---- watchlist ----------------------------------------------------------------------------
function Watchlist({
  rows,
  selected,
  onSelect,
  held,
  ideas,
}: {
  rows?: MarketRow[];
  selected: string;
  onSelect: (s: string) => void;
  held: Trade[];
  ideas: Proposal[];
}) {
  const [q, setQ] = useState("");
  const [view, setView] = useState<"all" | "movers" | "halal">("all");
  const heldSet = new Set(held.map((h) => h.symbol));
  const ideaSet = new Set(ideas.map((i) => i.symbol));
  const list = useMemo(() => {
    let r = (rows ?? []).filter((x) => !q || x.symbol.includes(q.toUpperCase()) || x.name.toLowerCase().includes(q.toLowerCase()));
    if (view === "halal") r = r.filter((x) => x.halal);
    if (view === "movers") r = [...r].sort((a, b) => Math.abs(b.change_day_pct) - Math.abs(a.change_day_pct));
    return r;
  }, [rows, q, view]);

  return (
    <aside className="hidden min-h-0 flex-col lg:flex">
      <div className="space-y-2 border-b p-2">
        <div className="relative">
          <Search className="text-muted-foreground absolute start-2 top-1/2 size-3.5 -translate-y-1/2" />
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Symbol" className="h-8 rounded-sm ps-7 font-mono text-xs" />
        </div>
        <div className="flex gap-1">
          {(["all", "movers", "halal"] as const).map((v) => (
            <ToolBtn key={v} active={view === v} onClick={() => setView(v)} className="flex-1 justify-center uppercase">
              {v}
            </ToolBtn>
          ))}
        </div>
      </div>
      <div className="text-muted-foreground grid grid-cols-[1fr_auto_auto] gap-2 border-b px-3 py-1.5 font-mono text-[10px] tracking-wide uppercase">
        <span>Symbol</span>
        <span className="w-16 text-end">Last</span>
        <span className="w-14 text-end">Chg%</span>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {!rows
          ? Array.from({ length: 14 }).map((_, i) => <Skeleton key={i} className="m-2 h-7" />)
          : list.map((r) => (
              <button
                key={r.symbol}
                onClick={() => onSelect(r.symbol)}
                className={cn(
                  "grid w-full cursor-pointer grid-cols-[1fr_auto_auto] items-center gap-2 border-b border-transparent px-3 py-1.5 text-start transition-colors",
                  r.symbol === selected ? "bg-accent" : "hover:bg-accent/60",
                )}
              >
                <span className="min-w-0">
                  <span className="flex items-center gap-1.5 font-mono text-xs font-bold">
                    {r.symbol}
                    {heldSet.has(r.symbol) && <span className="bg-foreground size-1.5" title="open position" />}
                    {ideaSet.has(r.symbol) && <span className="border-foreground size-1.5 border" title="trade idea" />}
                    {r.paused && <span className="text-warn text-[9px]">PAUSED</span>}
                  </span>
                  <span className="text-muted-foreground block truncate text-[10px]">{r.name}</span>
                </span>
                <span className="num w-16 text-end text-xs">{r.price.toFixed(2)}</span>
                <span className={cn("num w-14 text-end text-xs", tone(r.change_day_pct))}>{pct(r.change_day_pct)}</span>
              </button>
            ))}
      </div>
    </aside>
  );
}

// ---- right info panel ---------------------------------------------------------------------
function InfoPanel({
  symbol,
  row,
  stock,
  position,
  idea,
}: {
  symbol: string;
  row?: MarketRow;
  stock?: StockDetail;
  position?: Trade;
  idea?: Proposal;
}) {
  const { openAi } = useAi();
  const [sheet, setSheet] = useState(false);
  const f = stock?.features;
  const price = row?.price ?? (f ? Number(f.price) : undefined);
  const chg = row?.change_day_pct ?? (f ? Number(f.change_day_pct) : 0);
  const prevClose = price != null ? price / (1 + chg / 100) : undefined;
  const co = stock?.company;

  const stats: [string, string, string?][] = f
    ? [
        ["Prev close", money(prevClose)],
        ["Range", `${num(Number(f.day_low))} – ${num(Number(f.day_high))}`],
        ["VWAP", num(Number(f.vwap)), f.above_vwap ? "text-gain" : "text-loss"],
        ["RSI 14", num(Number(f.rsi14), 1), Number(f.rsi14) > 70 ? "text-warn" : undefined],
        ["Rel. volume", `${num(Number(f.volume_ratio), 2)}x`, Number(f.volume_ratio) >= 1.8 ? "text-warn" : undefined],
        ["30 min", pct(Number(f.change_30m_pct)), tone(Number(f.change_30m_pct))],
        ["ATR (1m)", num(Number(f.atr14), 3)],
        ["Trend", String(f.trend).toUpperCase()],
        ["20D trend", pct(Number(f.daily_trend_20d_pct)), tone(Number(f.daily_trend_20d_pct))],
        ["20D vol.", `${num(Number(f.volatility_20d_pct), 2)}%`],
        ["Mkt cap", co ? `$${num(co.market_cap_b, 0)}B` : "—"],
        ["Revenue", co ? `$${num(co.revenue_b, 0)}B` : "—"],
        ["Net margin", co?.net_margin != null ? `${(co.net_margin * 100).toFixed(1)}%` : "—"],
        ["Debt / mkt cap", co?.debt_to_mcap != null ? `${(co.debt_to_mcap * 100).toFixed(1)}%` : "—"],
      ]
    : [];

  return (
    <aside className="min-h-0 overflow-y-auto border-t lg:border-t-0">
      <div className="border-b p-4">
        <div className="flex items-baseline justify-between gap-2">
          <span className="font-mono text-lg font-bold">{symbol}</span>
          <span className="text-muted-foreground truncate text-xs">{co?.sector}</span>
        </div>
        <div className="text-muted-foreground truncate text-xs">{co?.name ?? row?.name}</div>
        <div className="mt-3 flex items-baseline gap-2">
          <span className="num text-3xl font-semibold">{price?.toFixed(2) ?? "—"}</span>
          <span className={cn("num text-sm font-medium", tone(chg))}>{pct(chg)}</span>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {stock && (
            <Tag tone={stock.laya.worth_a_look ? "on" : "off"}>{stock.laya.worth_a_look ? "Scanner: worth a look" : "Scanner: pass"}</Tag>
          )}
          {stock && <Tag tone={stock.halal.passes ? "on" : "off"}>{stock.halal.passes ? "Halal ✓" : "Not halal"}</Tag>}
          {row?.paused && <Tag tone="warn">Paused: bad data</Tag>}
        </div>
      </div>

      {/* AI signal */}
      <Section title="AI signal">
        {idea ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs uppercase">{idea.status === "pending" ? "Waiting for your approval" : idea.status}</span>
              <span className="num text-sm font-bold">{idea.score}/100</span>
            </div>
            <p className="line-clamp-3 text-xs leading-relaxed">{idea.thesis}</p>
            <PlanRow entry={idea.entry} stop={idea.stop} target={idea.target} qty={idea.qty} />
            <IdeaActions p={idea} onDetails={() => setSheet(true)} />
            <ProposalSheet p={idea} open={sheet} onOpenChange={setSheet} />
          </div>
        ) : (
          <div className="space-y-3">
            <p className="text-muted-foreground text-xs leading-relaxed">
              No active trade idea for {symbol}. Run the full agent team on it: analyst, devil&apos;s advocate, manager, then the risk engine.
            </p>
            <Button size="sm" className="w-full" onClick={() => openAi({ symbol }, { action: "analyze" })}>
              <Sparkles /> Analyze {symbol} with AI
            </Button>
          </div>
        )}
      </Section>

      {position && (
        <Section title="Your position">
          <div className="space-y-2">
            <div className="flex items-baseline justify-between">
              <span className="num text-sm">
                {position.qty} @ {position.entry_price.toFixed(2)}
              </span>
              <span className={cn("num text-sm font-bold", tone(position.unrealized))}>{signedMoney(position.unrealized)}</span>
            </div>
            <PlanRow entry={position.entry_price} stop={position.stop} target={position.target} />
            {position.keeper_log?.length ? (
              <div className="border p-2 text-xs">
                <span className="font-mono text-[10px] uppercase">Keeper · {position.keeper_log[position.keeper_log.length - 1].action}: </span>
                {position.keeper_log[position.keeper_log.length - 1].reason}
              </div>
            ) : null}
            <ClosePosition t={position} />
          </div>
        </Section>
      )}

      <Section title="Key stats">
        {f ? (
          <dl className="grid grid-cols-2 gap-x-4 gap-y-2">
            {stats.map(([k, v, cls]) => (
              <div key={k} className="flex items-baseline justify-between gap-2 border-b border-dashed pb-1">
                <dt className="text-muted-foreground text-[11px]">{k}</dt>
                <dd className={cn("num text-[11px]", cls)}>{v}</dd>
              </div>
            ))}
          </dl>
        ) : (
          <Skeleton className="h-40" />
        )}
      </Section>

      {stock && (
        <>
          <Section title="Earnings">
            <EarningsBlock e={stock.earnings} />
          </Section>
          <Section title="Analyst ratings">
            <RatingsBlock r={stock.ratings} />
          </Section>
          <Section title="SEC filings">
            <FilingsList items={stock.filings} />
          </Section>
        </>
      )}

      {stock && stock.laya.reasons.length > 0 && (
        <Section title="Why the scanner noticed">
          <ul className="space-y-1 text-xs">
            {stock.laya.reasons.map((r) => (
              <li key={r} className="flex gap-2">
                <span className="text-muted-foreground">—</span>
                {r}
              </li>
            ))}
          </ul>
        </Section>
      )}

      <Section title="News">
        {stock?.news.length ? (
          <ul className="space-y-2.5">
            {stock.news.map((n) => (
              <li key={n.headline + n.at}>
                <div className="text-xs leading-snug">{n.headline}</div>
                <div className="text-muted-foreground font-mono text-[10px]">
                  {n.source} · {timeAgo(n.at)}
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground text-xs">No recent company news.</p>
        )}
      </Section>
    </aside>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b p-4">
      <h3 className="text-muted-foreground mb-3 font-mono text-[10px] font-semibold tracking-widest uppercase">{title}</h3>
      {children}
    </section>
  );
}

function Tag({ tone: t, children }: { tone: "on" | "off" | "warn"; children: React.ReactNode }) {
  return (
    <span
      className={cn(
        "rounded-sm border px-1.5 py-0.5 font-mono text-[10px] uppercase",
        t === "on" && "border-foreground text-foreground",
        t === "off" && "text-muted-foreground",
        t === "warn" && "border-warn text-warn",
      )}
    >
      {children}
    </span>
  );
}

function PlanRow({ entry, stop, target, qty }: { entry: number; stop: number; target: number; qty?: number }) {
  const rr = (target - entry) / Math.max(entry - stop, 1e-9);
  return (
    <div className="grid grid-cols-4 border font-mono text-[11px]">
      {[
        ["Entry", entry.toFixed(2), ""],
        ["Stop", stop.toFixed(2), "text-loss"],
        ["Target", target.toFixed(2), "text-gain"],
        [qty != null ? "Qty" : "R:R", qty != null ? String(qty) : `${rr.toFixed(1)}x`, ""],
      ].map(([k, v, c]) => (
        <div key={k} className="border-e px-2 py-1.5 last:border-e-0">
          <div className="text-muted-foreground text-[9px] uppercase">{k}</div>
          <div className={c}>{v}</div>
        </div>
      ))}
    </div>
  );
}

function IdeaActions({ p, onDetails }: { p: Proposal; onDetails: () => void }) {
  const [busy, setBusy] = useState(false);
  async function act(kind: "approve" | "reject") {
    setBusy(true);
    try {
      await api.post(`/proposals/${p.id}/${kind}`);
      toast.success(kind === "approve" ? `Bought ${p.symbol}` : `Skipped ${p.symbol}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
      refreshAll();
    }
  }
  return (
    <div className="flex gap-1.5">
      <Button size="sm" variant="ghost" onClick={onDetails}>
        Details
      </Button>
      <Button size="sm" variant="outline" className="ms-auto" disabled={busy} onClick={() => act("reject")}>
        <X />
      </Button>
      {p.status === "pending" && (
        <Button size="sm" disabled={busy} onClick={() => act("approve")}>
          <Check /> Buy
        </Button>
      )}
    </div>
  );
}

function ClosePosition({ t }: { t: Trade }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      className="w-full"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try {
          await api.post(`/trades/${t.id}/close`);
          toast.success(`Closed ${t.symbol}`);
        } catch (e) {
          toast.error(String(e));
        } finally {
          setBusy(false);
          refreshAll();
        }
      }}
    >
      Close position at market
    </Button>
  );
}

// ---- bottom panel: account, positions, ideas, history, log ---------------------------------
function BottomPanel({
  dash,
  ideas,
  symbol,
  onSelect,
}: {
  dash?: Dashboard;
  ideas: Proposal[];
  symbol: string;
  onSelect: (s: string) => void;
}) {
  const { data: trades } = useApi<Trade[]>("/trades?status=closed&limit=50", { refreshInterval: 10000 });
  const { data: log } = useApi<LogRow[]>(`/log?limit=60&symbol=${symbol}`, { refreshInterval: 10000 });
  const [sheet, setSheet] = useState<Proposal | null>(null);
  const a = dash?.account;

  return (
    <div className="flex h-72 shrink-0 flex-col border-t lg:h-64">
      <Tabs defaultValue="positions" className="min-h-0 flex-1 gap-0">
        <div className="flex items-center gap-4 overflow-x-auto border-b px-2">
          <TabsList className="h-9 shrink-0 rounded-none bg-transparent p-0">
            {[
              ["positions", `Positions ${dash?.positions.length ?? ""}`],
              ["ideas", `Ideas ${ideas.length || ""}`],
              ["history", "History"],
              ["log", `Log · ${symbol}`],
              ["alerts", "Alerts"],
            ].map(([v, label]) => (
              <TabsTrigger
                key={v}
                value={v}
                className="data-[state=active]:border-b-foreground h-9 flex-none rounded-none border-0 border-b-2 border-transparent px-3 font-mono text-[11px] uppercase data-[state=active]:bg-transparent data-[state=active]:shadow-none dark:data-[state=active]:bg-transparent"
              >
                {label}
              </TabsTrigger>
            ))}
          </TabsList>
          {a && (
            <div className="ms-auto hidden shrink-0 items-center gap-4 font-mono text-[11px] xl:flex">
              <Kv k="Equity" v={money(a.equity, 0)} />
              <Kv k="Cash" v={money(a.cash, 0)} />
              <Kv k="Day P&L" v={signedMoney(a.day_pnl)} cls={tone(a.day_pnl)} />
              {dash && (
                <Kv
                  k="vs S&P"
                  v={pct(dash.scoreboard.you_pct - dash.scoreboard.sp500_pct)}
                  cls={tone(dash.scoreboard.you_pct - dash.scoreboard.sp500_pct)}
                />
              )}
            </div>
          )}
        </div>

        <TabsContent value="positions" className="min-h-0 overflow-auto">
          <Grid
            head={["Symbol", "Qty", "Entry", "Last", "Stop", "Target", "P&L", "R"]}
            rows={(dash?.positions ?? []).map((p) => ({
              key: p.id,
              onClick: () => onSelect(p.symbol),
              cells: [
                p.symbol,
                p.qty,
                p.entry_price.toFixed(2),
                p.price?.toFixed(2) ?? "—",
                <span key="s" className="text-loss">{p.stop.toFixed(2)}</span>,
                <span key="t" className="text-gain">{p.target.toFixed(2)}</span>,
                <span key="p" className={tone(p.unrealized)}>{signedMoney(p.unrealized)}</span>,
                <span key="r" className={tone(p.r_now)}>{num(p.r_now, 2)}</span>,
              ],
            }))}
            empty="No open positions"
          />
        </TabsContent>

        <TabsContent value="ideas" className="min-h-0 overflow-auto">
          <Grid
            head={["Symbol", "Score", "Entry", "Stop", "Target", "Qty", "Status", "Age"]}
            rows={ideas.map((p) => ({
              key: p.id,
              onClick: () => {
                onSelect(p.symbol);
                setSheet(p);
              },
              cells: [
                p.symbol,
                p.score,
                p.entry.toFixed(2),
                <span key="s" className="text-loss">{p.stop.toFixed(2)}</span>,
                <span key="t" className="text-gain">{p.target.toFixed(2)}</span>,
                p.qty,
                p.status === "pending" ? "AWAITING YOU" : p.status.toUpperCase(),
                timeAgo(p.created_at),
              ],
            }))}
            empty="No open trade ideas — the scanner is watching"
          />
          {sheet && <ProposalSheet p={sheet} open={!!sheet} onOpenChange={(o) => !o && setSheet(null)} />}
        </TabsContent>

        <TabsContent value="history" className="min-h-0 overflow-auto">
          <Grid
            head={["Symbol", "Qty", "Entry", "Exit", "Reason", "P&L", "R", "Closed"]}
            rows={(trades ?? [])
              .filter((t) => t.exit_reason !== "demo restart")
              .map((t) => ({
                key: t.id,
                onClick: () => onSelect(t.symbol),
                cells: [
                  t.symbol,
                  t.qty,
                  t.entry_price.toFixed(2),
                  t.exit_price?.toFixed(2) ?? "—",
                  (t.exit_reason ?? "").toUpperCase(),
                  <span key="p" className={tone(t.pnl)}>{signedMoney(t.pnl)}</span>,
                  <span key="r" className={tone(t.r_multiple)}>{num(t.r_multiple, 2)}</span>,
                  timeAgo(t.closed_at),
                ],
              }))}
            empty="No closed trades yet"
          />
        </TabsContent>

        <TabsContent value="log" className="min-h-0 overflow-auto">
          <Grid
            head={["Time", "Step", "Result", "Reason"]}
            rows={(log ?? []).map((r) => ({
              key: r.id,
              cells: [
                timeAgo(r.at),
                r.stage.replace("_", " ").toUpperCase(),
                <span key="o" className={r.outcome === "no" ? "text-loss" : r.outcome === "yes" ? "text-gain" : ""}>
                  {r.outcome.toUpperCase()}
                </span>,
                <span key="r" className="block max-w-[560px] truncate font-sans">
                  {r.reason}
                </span>,
              ],
            }))}
            empty={`Nothing logged for ${symbol} yet`}
          />
        </TabsContent>

        <TabsContent value="alerts" className="min-h-0 overflow-auto">
          <Grid
            head={["Time", "Level", "Alert"]}
            rows={(dash?.alerts ?? []).map((al: AlertItem) => ({
              key: al.id,
              cells: [
                timeAgo(al.at),
                <span key="l" className={al.level === "critical" ? "text-loss" : al.level === "warn" ? "text-warn" : ""}>
                  {al.level.toUpperCase()}
                </span>,
                <span key="t" className="block max-w-[640px] truncate font-sans">
                  {al.title}
                  {al.body && <span className="text-muted-foreground"> — {al.body}</span>}
                </span>,
              ],
            }))}
            empty="No alerts"
          />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Kv({ k, v, cls }: { k: string; v: string; cls?: string }) {
  return (
    <span>
      <span className="text-muted-foreground uppercase">{k}</span> <span className={cls}>{v}</span>
    </span>
  );
}

function Grid({
  head,
  rows,
  empty,
}: {
  head: string[];
  rows: { key: number; cells: React.ReactNode[]; onClick?: () => void }[];
  empty: string;
}) {
  if (!rows.length) return <div className="text-muted-foreground p-4 font-mono text-xs">{empty}</div>;
  return (
    <table className="w-full font-mono text-[11px]">
      <thead className="bg-background sticky top-0">
        <tr className="text-muted-foreground border-b text-[10px] uppercase">
          {head.map((h, i) => (
            <th key={h} className={cn("px-3 py-1.5 font-medium whitespace-nowrap", i === 0 ? "text-start" : "text-end", i === head.length - 1 && "text-end")}>
              {h}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.key} onClick={r.onClick} className={cn("border-b border-dashed", r.onClick && "hover:bg-accent cursor-pointer")}>
            {r.cells.map((c, i) => (
              <td key={i} className={cn("px-3 py-1.5 whitespace-nowrap", i === 0 ? "text-start font-bold" : "text-end")}>
                {c}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
