"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, CheckCircle2, Eye, Loader2, Radar, RefreshCw, ShoppingCart, Sparkles, Trophy, X, XCircle } from "lucide-react";
import { useTheme } from "next-themes";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton, Slider } from "@/components/ui/misc";
import { PageHeader, ScoreRing } from "@/components/app/bits";
import { TeamReportsView } from "@/components/app/team";
import { TvChart } from "@/components/app/tv-chart";
import { api, refreshAll, useApi, type CandlesResponse, type Hunt, type HuntStep, type KeeperEntry, type Trade } from "@/lib/api";
import { money, num, pct, signedMoney, timeAgo, tone } from "@/lib/format";
import { cn } from "@/lib/utils";

const AGENT_LABEL: Record<string, string> = {
  mood: "Market mood",
  scanner: "Scanner",
  halal: "Halal checker",
  news: "News reader",
  chart: "Chart reader",
  company: "Company checker",
  analyst: "Analyst",
  devil: "Devil's advocate",
  manager: "Manager",
  risk: "Risk engine",
  broker: "Order placer",
  keeper: "Position keeper",
  system: "System",
};

const STAGES = ["Hunt", "Approve", "Watch", "Sold"] as const;

export default function DealsPage() {
  const { data: hunt, mutate } = useApi<Hunt | null>("/hunt/latest", { refreshInterval: 2000 });
  const [starting, setStarting] = useState(false);

  const trade = hunt?.trade;
  const stage = !hunt ? -1 : hunt.status === "running" ? 0 : hunt.status === "found" ? 1 : trade && !trade.closed_at ? 2 : trade?.closed_at ? 3 : 0;

  async function start() {
    setStarting(true);
    try {
      await mutate(await api.post<Hunt>("/hunt"), { revalidate: false });
    } catch (e) {
      toast.error(String(e));
    } finally {
      setStarting(false);
    }
  }

  const running = hunt?.status === "running";
  const canHunt = !running && !(trade && !trade.closed_at);

  return (
    <>
      <PageHeader
        title="Deal finder"
        description="One button: the agent team scans the whole market, argues about the best long trade and checks it against your risk limits. You choose the size and approve; the Position keeper then watches it and sells at the right time."
      >
        <Button size="lg" onClick={start} disabled={!canHunt || starting} className="gap-2">
          {running ? <Loader2 className="animate-spin" /> : hunt ? <RefreshCw /> : <Radar />}
          {running ? "Hunting…" : hunt ? "Hunt again" : "Find the best deal"}
        </Button>
      </PageHeader>

      <Stepper stage={stage} />

      {hunt === undefined ? (
        <Skeleton className="mt-4 h-96" />
      ) : hunt === null ? (
        <EmptyState onStart={start} busy={starting} />
      ) : (
        <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,1fr)_400px]">
          <div className="min-w-0 space-y-4">
            {hunt.status === "found" && hunt.deal && <DealCard key={hunt.id} hunt={hunt} onBought={() => mutate()} />}
            {trade && <WatchCard trade={trade} />}
            {(hunt.status === "no_deal" || hunt.status === "failed") && (
              <Card>
                <CardContent className="flex items-start gap-3">
                  <XCircle className="text-muted-foreground mt-0.5 size-5 shrink-0" />
                  <div>
                    <div className="font-semibold">{hunt.status === "failed" ? "The hunt failed" : "No deal right now"}</div>
                    <p className="text-muted-foreground text-sm">{hunt.message} Waiting is a position too — try again in a few minutes.</p>
                  </div>
                </CardContent>
              </Card>
            )}
            {running && (
              <Card>
                <CardContent className="flex items-center gap-3 text-sm">
                  <Loader2 className="size-4 animate-spin" />
                  The team is working — follow every hand-off live on the right.
                </CardContent>
              </Card>
            )}
            <Leaderboard hunt={hunt} />
          </div>
          <Feed hunt={hunt} />
        </div>
      )}
    </>
  );
}

function Stepper({ stage }: { stage: number }) {
  return (
    <div className="grid grid-cols-4 border">
      {STAGES.map((s, i) => (
        <div
          key={s}
          className={cn(
            "flex items-center gap-2 border-e px-3 py-2.5 font-mono text-[11px] uppercase last:border-e-0",
            i === stage ? "bg-foreground text-background" : i < stage ? "text-foreground" : "text-muted-foreground",
          )}
        >
          <span className={cn("grid size-5 place-items-center rounded-full border text-[10px]", i === stage && "border-background")}>
            {i < stage ? <Check className="size-3" /> : i + 1}
          </span>
          {s}
        </div>
      ))}
    </div>
  );
}

function EmptyState({ onStart, busy }: { onStart: () => void; busy: boolean }) {
  return (
    <Card className="mt-4">
      <CardContent className="flex flex-col items-center gap-4 py-12 text-center">
        <div className="bg-foreground text-background grid size-14 place-items-center rounded-full">
          <Radar className="size-7" />
        </div>
        <div className="max-w-lg space-y-1">
          <div className="text-lg font-semibold">Let the team hunt for you</div>
          <p className="text-muted-foreground text-sm">
            Market mood → Scanner ranks every stock → News reader, Chart reader and Company checker study the top picks → Analyst scores
            them → Devil&apos;s advocate attacks the best → Manager plans it → Risk engine sizes it. Nothing is bought until you approve.
          </p>
        </div>
        <Button size="lg" onClick={onStart} disabled={busy}>
          <Radar /> Find the best deal
        </Button>
      </CardContent>
    </Card>
  );
}

// ---- 2 · approve with a chosen size --------------------------------------------------------------
function DealCard({ hunt, onBought }: { hunt: Hunt; onBought: () => void }) {
  const d = hunt.deal!;
  const [qty, setQty] = useState(Math.max(1, Math.round(d.max_qty / 2)));
  const [busy, setBusy] = useState(false);
  const { resolvedTheme } = useTheme();
  const { data: candles } = useApi<CandlesResponse>(`/candles/${d.symbol}?tf=5m&limit=200`, { refreshInterval: 5000 });
  const levels = useMemo(() => ({ entry: d.entry, stop: d.stop, target: d.target }), [d.entry, d.stop, d.target]);
  const price = candles?.last ?? d.entry;
  const cost = qty * price;
  const riskAmt = qty * d.risk_per_share;
  const reward = qty * d.reward_per_share;

  async function buy() {
    setBusy(true);
    try {
      await api.post(`/hunt/${hunt.id}/buy`, { qty });
      toast.success(`Bought ${qty} ${d.symbol}`, { description: "The Position keeper is watching it now." });
      onBought();
      refreshAll();
    } catch (e) {
      toast.error("Not bought", { description: e instanceof Error ? e.message : String(e) });
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="border-foreground border-2">
      <CardHeader>
        <div className="flex items-center gap-4">
          <ScoreRing score={d.score} size={56} />
          <div className="min-w-0">
            <div className="text-muted-foreground flex items-center gap-1.5 font-mono text-[10px] uppercase">
              <Trophy className="size-3" /> Best deal right now
            </div>
            <div className="text-2xl font-bold tracking-tight">
              {d.symbol} <span className="text-muted-foreground text-base font-normal">{d.name}</span>
            </div>
          </div>
          <div className="ms-auto text-end">
            <div className="num text-2xl font-semibold">{price.toFixed(2)}</div>
            <div className="text-muted-foreground font-mono text-[10px] uppercase">mood: {d.mood}</div>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        <p className="text-sm leading-relaxed">{d.thesis}</p>
        <div className="h-64 border">
          {candles?.bars.length ? (
            <TvChart bars={candles.bars} trades={[]} levels={levels} theme={resolvedTheme === "light" ? "light" : "dark"} colored={false}
              indicators={{ ema9: true, ema21: true, vwap: true, volume: true, rsi: false }} />
          ) : (
            <Skeleton className="h-full" />
          )}
        </div>

        <div className="grid grid-cols-3 border font-mono text-xs">
          {[["Entry", d.entry.toFixed(2), ""], ["Stop", d.stop.toFixed(2), "text-loss"], ["Target", d.target.toFixed(2), "text-gain"]].map(([k, v, c]) => (
            <div key={k} className="border-e p-2.5 last:border-e-0">
              <div className="text-muted-foreground text-[10px] uppercase">{k}</div>
              <div className={cn("text-base", c)}>{v}</div>
            </div>
          ))}
        </div>

        <div className="space-y-3 border p-4">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-semibold">How many shares?</span>
            <span className="text-muted-foreground font-mono text-[11px]">risk engine max: {d.max_qty}</span>
          </div>
          <div className="flex items-center gap-3">
            <Input
              type="number"
              min={1}
              max={d.max_qty}
              value={qty}
              onChange={(e) => setQty(Math.max(1, Math.min(d.max_qty, Number(e.target.value) || 1)))}
              className="num h-10 w-28 text-lg"
            />
            <Slider min={1} max={Math.max(1, d.max_qty)} step={1} value={[qty]} onValueChange={([v]) => setQty(v)} className="flex-1" />
          </div>
          <div className="flex gap-1.5">
            {[0.25, 0.5, 1].map((f) => (
              <Button key={f} size="sm" variant="outline" className="font-mono" onClick={() => setQty(Math.max(1, Math.floor(d.max_qty * f)))}>
                {f === 1 ? "MAX" : `${f * 100}%`}
              </Button>
            ))}
          </div>
          <div className="grid grid-cols-3 gap-3 border-t pt-3 font-mono text-xs">
            <div>
              <div className="text-muted-foreground text-[10px] uppercase">Cost</div>
              {money(cost, 0)}
            </div>
            <div>
              <div className="text-muted-foreground text-[10px] uppercase">If stopped out</div>
              <span className="text-loss">−{money(riskAmt, 0)}</span>
            </div>
            <div>
              <div className="text-muted-foreground text-[10px] uppercase">If target hit</div>
              <span className="text-gain">+{money(reward, 0)}</span>
            </div>
          </div>
          <Button size="lg" className="w-full" disabled={busy} onClick={buy}>
            {busy ? <Loader2 className="animate-spin" /> : <ShoppingCart />} Approve &amp; buy {qty} {d.symbol}
          </Button>
          <p className="text-muted-foreground text-[11px]">
            Bracket order: the stop and target are placed at the broker with the buy. The risk engine re-checks at the live price first.
          </p>
        </div>

        <details className="border px-3">
          <summary className="cursor-pointer py-2 text-sm font-medium">Why — the team&apos;s reports, the objection and the safety checks</summary>
          <div className="space-y-4 pb-3">
            <TeamReportsView team={d.team} />
            <div className="text-sm">
              <span className="font-semibold">Devil&apos;s advocate ({d.devil.severity}/5): </span>
              {d.devil.objection}
            </div>
            <div className="text-sm">
              <span className="font-semibold">Manager: </span>
              {d.manager.rebuttal} <span className="text-muted-foreground">{d.exit_plan}</span>
            </div>
            <ul className="grid gap-1 sm:grid-cols-2">
              {d.risk_checks.map((c) => (
                <li key={c.name} className="flex items-start gap-1.5 text-xs">
                  {c.passed ? <CheckCircle2 className="text-gain mt-px size-3.5 shrink-0" /> : <XCircle className="text-loss mt-px size-3.5 shrink-0" />}
                  {c.detail}
                </li>
              ))}
            </ul>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

// ---- 3 + 4 · watch and sell ----------------------------------------------------------------------
function WatchCard({ trade }: { trade: Trade }) {
  const { resolvedTheme } = useTheme();
  const { data: candles } = useApi<CandlesResponse>(`/candles/${trade.symbol}?tf=1m&limit=240`, { refreshInterval: 3000 });
  const [busy, setBusy] = useState<"keep" | "sell" | null>(null);
  const open = !trade.closed_at;
  const pnl = open ? trade.unrealized ?? 0 : trade.pnl ?? 0;
  const r = open ? trade.r_now : trade.r_multiple;
  const log = [...(trade.keeper_log ?? [])].reverse();
  const peakR = trade.peak_price && trade.entry_price > trade.initial_stop ? (trade.peak_price - trade.entry_price) / (trade.entry_price - trade.initial_stop) : null;

  async function act(kind: "keep" | "sell") {
    setBusy(kind);
    try {
      if (kind === "keep") await api.post(`/trades/${trade.id}/keep`);
      else await api.post(`/trades/${trade.id}/close`);
      if (kind === "sell") toast.success(`Sold ${trade.symbol}`);
      refreshAll();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className={cn(open && "border-foreground border-2")}>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {open ? <Eye className="size-4" /> : <CheckCircle2 className="size-4" />}
          {open ? `Watching ${trade.symbol}` : `Sold ${trade.symbol}`}
        </CardTitle>
        <CardDescription>
          {trade.qty} shares @ {trade.entry_price.toFixed(2)} · opened {timeAgo(trade.opened_at)}
          {!open && ` · closed ${timeAgo(trade.closed_at)} (${trade.exit_reason})`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-px border bg-border font-mono sm:grid-cols-5">
          {[
            [open ? "Live P&L" : "Result", signedMoney(pnl), tone(pnl)],
            ["R", r != null ? `${num(r, 2)}R` : "—", tone(r)],
            [open ? "Price" : "Exit", (open ? trade.price : trade.exit_price)?.toFixed(2) ?? "—", ""],
            ["Stop", trade.stop.toFixed(2), "text-loss"],
            ["Peak", peakR != null ? `${num(peakR, 1)}R` : "—", ""],
          ].map(([k, v, c]) => (
            <div key={k} className="bg-card p-2.5">
              <div className="text-muted-foreground text-[10px] uppercase">{k}</div>
              <div className={cn("text-lg", c)}>{v}</div>
            </div>
          ))}
        </div>
        <div className="h-72 border">
          {candles?.bars.length ? (
            <TvChart key={trade.id} bars={candles.bars} trades={candles.trades} theme={resolvedTheme === "light" ? "light" : "dark"} colored={false}
              indicators={{ ema9: true, ema21: true, vwap: true, volume: true, rsi: false }} />
          ) : (
            <Skeleton className="h-full" />
          )}
        </div>
        {open && (
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" disabled={!!busy} onClick={() => act("keep")}>
              {busy === "keep" ? <Loader2 className="animate-spin" /> : <Sparkles />} Ask the keeper now
            </Button>
            <Button variant="outline" disabled={!!busy} onClick={() => act("sell")} className="border-loss/60 text-loss hover:bg-loss ms-auto hover:text-white">
              <X /> Sell now at market
            </Button>
          </div>
        )}

        <div>
          <div className="text-muted-foreground mb-2 font-mono text-[10px] tracking-widest uppercase">Position keeper</div>
          {log.length === 0 ? (
            <p className="text-muted-foreground text-xs">First check runs on the next market cycle.</p>
          ) : (
            <ol className="space-y-2">
              {log.slice(0, 12).map((k: KeeperEntry, i) => (
                <li key={k.at + i} className="grid grid-cols-[64px_1fr] gap-3 border-b border-dashed pb-2 text-xs last:border-b-0">
                  <span
                    className={cn(
                      "h-fit rounded-sm border px-1 py-0.5 text-center font-mono text-[10px] uppercase",
                      k.action === "sell" && "bg-foreground text-background",
                      k.action === "tighten" && "border-foreground",
                    )}
                  >
                    {k.action}
                  </span>
                  <div className="space-y-1">
                    <div>{k.reason}</div>
                    <div className="text-muted-foreground flex flex-wrap gap-x-2 font-mono text-[10px]">
                      <span>{timeAgo(k.at)}</span>
                      {(k.checks ?? 1) > 1 && <span>{k.checks} checks</span>}
                      <span>{num(k.r, 2)}R</span>
                      <span>{k.by === "claude" ? "Claude" : "rules"}</span>
                      {k.skills.slice(0, 4).map((s, j) => (
                        <span key={j} className="border px-1">{s.skill}</span>
                      ))}
                    </div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

// ---- leaderboard -----------------------------------------------------------------------------------
function Leaderboard({ hunt }: { hunt: Hunt }) {
  if (!hunt.ranking.length) return null;
  const analysed = new Map(hunt.candidates.map((c) => [c.symbol, c]));
  return (
    <Card>
      <CardHeader>
        <CardTitle>What the scanner saw</CardTitle>
        <CardDescription>Whole-market ranking. Stocks with an analyst score got the full specialist review.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto">
        <table className="w-full font-mono text-[11px]">
          <thead>
            <tr className="text-muted-foreground border-b text-[10px] uppercase">
              {["#", "Symbol", "Scan", "Price", "Day", "Vol", "Trend", "Analyst"].map((h, i) => (
                <th key={h} className={cn("px-2 py-1.5 font-medium", i < 2 ? "text-start" : "text-end")}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {hunt.ranking.slice(0, 12).map((r, i) => {
              const c = analysed.get(r.symbol);
              const pick = hunt.deal?.symbol === r.symbol;
              return (
                <tr key={r.symbol} className={cn("border-b border-dashed", pick && "bg-accent font-bold")}>
                  <td className="px-2 py-1.5">{i + 1}</td>
                  <td className="px-2 py-1.5">{r.symbol} {pick && "★"}</td>
                  <td className="px-2 py-1.5 text-end">{r.score.toFixed(0)}</td>
                  <td className="px-2 py-1.5 text-end">{r.price.toFixed(2)}</td>
                  <td className={cn("px-2 py-1.5 text-end", tone(r.change_day_pct))}>{pct(r.change_day_pct)}</td>
                  <td className="px-2 py-1.5 text-end">{r.volume_ratio.toFixed(1)}x</td>
                  <td className="px-2 py-1.5 text-end uppercase">{r.trend}</td>
                  <td className="px-2 py-1.5 text-end">{c ? `${c.score}/100` : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

// ---- live feed ---------------------------------------------------------------------------------------
function Feed({ hunt }: { hunt: Hunt }) {
  const end = useRef<HTMLDivElement>(null);
  const running = hunt.status === "running";
  useEffect(() => {
    if (running) end.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [hunt.steps.length, running]);
  return (
    <Card className="h-fit lg:sticky lg:top-16">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {running && <span className="bg-gain size-2 animate-pulse rounded-full" />} Agent feed
        </CardTitle>
        <CardDescription>Every hand-off, with the skills (tools) each agent used. Started {timeAgo(hunt.started_at)}.</CardDescription>
      </CardHeader>
      <CardContent className="max-h-[70vh] overflow-y-auto">
        <ol className="relative space-y-3 border-s ps-4">
          {hunt.steps.map((s, i) => (
            <FeedStep key={i} s={s} />
          ))}
          {running && (
            <li className="text-muted-foreground flex items-center gap-2 text-xs">
              <Loader2 className="size-3 animate-spin" /> working…
            </li>
          )}
        </ol>
        <div ref={end} />
      </CardContent>
    </Card>
  );
}

function FeedStep({ s }: { s: HuntStep }) {
  return (
    <li>
      <span
        className={cn(
          "absolute -start-[5px] mt-1 size-2.5 rounded-full border",
          s.ok === true ? "bg-foreground border-foreground" : s.ok === false ? "bg-background border-muted-foreground" : "bg-muted",
        )}
      />
      <div className="flex flex-wrap items-baseline gap-x-2">
        <span className="text-xs font-semibold">{AGENT_LABEL[s.agent] ?? s.agent}</span>
        {s.symbol && <span className="font-mono text-[11px] font-bold">{s.symbol}</span>}
        <span className="text-muted-foreground font-mono text-[9px] uppercase">{s.by === "claude" ? "Claude" : s.by === "heuristic" ? "rules" : s.by}</span>
        {s.ok === false && <span className="text-muted-foreground font-mono text-[9px] uppercase">· no</span>}
      </div>
      <p className={cn("text-xs leading-relaxed", s.ok === false && "text-muted-foreground")}>{s.text}</p>
      {s.skills.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1">
          {s.skills.slice(0, 6).map((k, j) => (
            <span key={j} title={k.summary} className="text-muted-foreground border px-1 font-mono text-[9px]">
              {k.skill}
            </span>
          ))}
        </div>
      )}
    </li>
  );
}
