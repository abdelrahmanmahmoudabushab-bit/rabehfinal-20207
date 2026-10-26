"use client";

import { useState } from "react";
import { CheckCircle2, ClipboardCheck, Cpu, Lightbulb, Play, ShieldAlert } from "lucide-react";
import { toast } from "sonner";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Empty, PageHeader, Stat } from "@/components/app/bits";
import { api, refreshAll, useApi, type AbResult, type AgentReport, type LiveVsBacktest, type SetupHealth, type Review, type Status, type Usage } from "@/lib/api";
import { pct, signedMoney, timeAgo, tone } from "@/lib/format";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

export default function ReviewPage() {
  const { t } = useI18n();
  const { data } = useApi<Review[]>("/reviews", { refreshInterval: 30000 });
  const [busy, setBusy] = useState(false);

  async function run() {
    setBusy(true);
    try {
      await api.post("/reviews/run");
      toast.success("Review finished");
      refreshAll();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title={t("review")}
        description="After every close the Reviewer grades each trade, writes lessons the agents read tomorrow, and only changes a rule if the change beats the live version on replay."
      >
        <Button onClick={run} disabled={busy}>
          <Play /> {busy ? "Reviewing…" : "Run review now"}
        </Button>
      </PageHeader>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {!data ? (
            <Skeleton className="h-64 rounded-md" />
          ) : !data.length ? (
            <Empty icon={<ClipboardCheck />}>The first review runs automatically at 16:30 ET, or run one now.</Empty>
          ) : (
            data.map((r) => <ReviewCard key={r.id} r={r} />)
          )}
        </div>
        <div className="space-y-4">
          <UsageCard />
          <LiveVsBacktestCard />
          <AbCard />
        </div>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <AgentsValueCard />
        <SetupHealthCard />
      </div>
    </>
  );
}

function ReviewCard({ r }: { r: Review }) {
  const s = r.stats;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{r.day}</CardTitle>
        <CardDescription>{timeAgo(r.at)}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <Stat label="Trades" value={s.trades} sub={`${s.targets_hit} targets · ${s.stopped_out} stops`} />
          <Stat label="Win rate" value={s.trades ? `${Math.round(s.win_rate * 100)}%` : "—"} />
          <Stat label="P&L" value={signedMoney(s.pnl)} valueClass={tone(s.pnl)} />
          <Stat
            label="vs S&P 500"
            value={pct(s.account_return_pct - s.sp500_return_pct)}
            valueClass={tone(s.account_return_pct - s.sp500_return_pct)}
            sub={`S&P ${pct(s.sp500_return_pct)}`}
          />
        </div>
        <p className="text-sm leading-relaxed">{r.summary}</p>
        <div>
          <div className="mb-2 flex items-center gap-2 text-sm font-medium">
            <Lightbulb className="text-warn size-4" /> Lessons sent to the agents
          </div>
          <ul className="space-y-1.5">
            {r.lessons.map((l) => (
              <li key={l} className="flex gap-2 text-sm">
                <CheckCircle2 className="text-primary mt-0.5 size-3.5 shrink-0" /> {l}
              </li>
            ))}
          </ul>
        </div>
        <div className={cn("flex items-start gap-3 rounded-lg border p-3 text-sm", r.change_applied ? "border-gain/30 bg-gain/5" : "bg-muted/30")}>
          <ShieldAlert className={cn("mt-0.5 size-4 shrink-0", r.change_applied ? "text-gain" : "text-muted-foreground")} />
          <div>
            <div className="font-medium">
              {r.change_applied ? "Rule change applied" : "Live rules kept"}{" "}
              <Badge variant="muted" className="ms-1">
                threshold → {r.proposed_change.score_threshold}
              </Badge>
            </div>
            <div className="text-muted-foreground mt-0.5 text-xs">{r.change_verdict}</div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function UsageCard() {
  const { t } = useI18n();
  const { data } = useApi<Usage>("/usage", { refreshInterval: 15000 });
  const { data: status } = useApi<Status>("/status");
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Cpu className="size-4" /> Agent usage (24h)
        </CardTitle>
        <CardDescription>
          {status?.claude ? `Claude · ${status.model}` : "No ANTHROPIC_API_KEY — agents run as transparent heuristics, free."}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Stat label="Calls" value={data?.calls_24h ?? "—"} sub={data?.errors_24h ? `${data.errors_24h} errors` : undefined} />
          <Stat label="Est. cost" value={data ? `$${data.est_cost_24h.toFixed(2)}` : "—"} />
          <Stat label="Tokens in" value={data ? data.input_tokens_24h.toLocaleString() : "—"} sub={data ? `${data.cache_read_tokens_24h.toLocaleString()} cached${data.cache_saved_24h != null ? ` · ${t("cacheSaved")} $${data.cache_saved_24h.toFixed(2)}` : ""}` : undefined} />
          <Stat label="Tokens out" value={data ? data.output_tokens_24h.toLocaleString() : "—"} />
          <Stat label="Cost per trade" value={data?.cost_per_trade != null ? `$${data.cost_per_trade.toFixed(2)}` : "—"} sub={data ? `${data.trades_24h} trades in 24h` : undefined} />
          <Stat
            label="Today vs budget"
            value={data ? `$${data.spend_today.toFixed(2)}` : "—"}
            valueClass={data?.over_budget ? "text-loss" : undefined}
            sub={data ? (data.budget_usd > 0 ? `of $${data.budget_usd.toFixed(0)}${data.over_budget ? " — rules only until tomorrow" : ""}` : "no cap") : undefined}
          />
        </div>
        {!!data?.recent.length && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Agent</TableHead>
                <TableHead className="text-end">ms</TableHead>
                <TableHead className="text-end">When</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.recent.slice(0, 12).map((c, i) => (
                <TableRow key={i}>
                  <TableCell>
                    <span className={cn(!c.ok && "text-loss")}>{c.agent}</span>
                    {c.symbol && <span className="text-muted-foreground"> · {c.symbol}</span>}
                  </TableCell>
                  <TableCell className="tabular text-end">{c.ms}</TableCell>
                  <TableCell className="text-muted-foreground text-end text-xs">{timeAgo(c.at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

function LiveVsBacktestCard() {
  const { data } = useApi<LiveVsBacktest>("/review/live-vs-backtest", { refreshInterval: 30000 });
  const o = data?.overall;
  const gap = o?.expected_r != null && o.realized_r != null ? o.realized_r - o.expected_r : null;
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>Live vs backtest</CardTitle>
        <CardDescription>Do real trades earn what their backtests promised? A big gap means the backtest is too optimistic.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {!o?.trades ? (
          <p className="text-muted-foreground text-xs">No closed trades with a backtest yet.</p>
        ) : (
          <>
            <div className="grid grid-cols-3 gap-2">
              <Stat label="Trades" value={o.trades} />
              <Stat label="Expected" value={`${(o.expected_r ?? 0) >= 0 ? "+" : ""}${(o.expected_r ?? 0).toFixed(2)}R`} />
              <Stat label="Realized" value={`${(o.realized_r ?? 0) >= 0 ? "+" : ""}${(o.realized_r ?? 0).toFixed(2)}R`} valueClass={tone(o.realized_r)} />
            </div>
            {gap != null && (
              <p className={cn("text-xs", gap < -0.2 ? "text-loss" : "text-muted-foreground")}>
                Gap {gap >= 0 ? "+" : ""}{gap.toFixed(2)}R per trade{o.trades < 30 ? " — too few trades to judge yet (aim for 30+)" : gap < -0.2 ? " — live is clearly worse: check slippage and data quality" : ""}.
              </p>
            )}
            <div className="space-y-1 font-mono text-[11px]">
              {Object.entries(data!.by_setup).map(([k, v]) => (
                <div key={k} className="flex justify-between border-b border-dashed pb-1">
                  <span>{k}</span>
                  <span>{v.trades} · exp {v.expected_r.toFixed(2)}R · real <span className={tone(v.realized_r)}>{v.realized_r.toFixed(2)}R</span></span>
                </div>
              ))}
            </div>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function AbCard() {
  const { data } = useApi<AbResult>("/ab", { refreshInterval: 30000 });
  const row = (label: string, d?: AbResult["claude"]) => (
    <div className="grid grid-cols-4 gap-2 border-b border-dashed py-1.5 font-mono text-[11px]">
      <span className="font-sans text-xs font-semibold">{label}</span>
      <span className="text-end">{d?.go ?? 0} go</span>
      <span className="text-end">{d?.hit_rate_go != null ? `${(d.hit_rate_go * 100).toFixed(0)}% up` : "—"}</span>
      <span className={cn("text-end", tone(d?.edge))}>{d?.edge != null ? `${d.edge >= 0 ? "+" : ""}${d.edge.toFixed(2)}%` : "—"}</span>
    </div>
  );
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>Rules vs Claude (A/B)</CardTitle>
        <CardDescription>
          Every time Claude scores a stock, the free rules score it too. 60 minutes later we check who was right. Keep paying for Claude only if it wins.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <div className="text-muted-foreground grid grid-cols-4 gap-2 pb-1 font-mono text-[10px] uppercase">
          <span />
          <span className="text-end">picks</span>
          <span className="text-end">hit rate</span>
          <span className="text-end">go − no, 60m</span>
        </div>
        {row("Claude", data?.claude)}
        {row("Rules", data?.rules)}
        <p className="text-muted-foreground mt-2 text-[11px]">
          {data?.samples ?? 0} scored samples{data?.pending ? ` · ${data.pending} waiting for their 60-minute result` : ""}.{" "}
          {(data?.samples ?? 0) < (data?.min_samples ?? 100) ? `Needs ${data?.min_samples ?? 100}+ before it means anything. ${data?.note ?? ""}` : ""}
        </p>
      </CardContent>
    </Card>
  );
}

const fmtR = (x: number | null | undefined) => (x == null ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}R`);

function Buckets({ title, rows }: { title: string; rows: AgentReport["by_analyst_score"] }) {
  const { t } = useI18n();
  return (
    <div>
      <div className="text-muted-foreground mb-1 font-mono text-[10px] uppercase">{title}</div>
      {rows.map((b) => (
        <div key={b.bucket} className="flex justify-between border-b border-dashed py-1 font-mono text-[11px]">
          <span>{b.bucket}</span>
          <span>
            {b.trades} {t("tradesCol")} · <span className={tone(b.avg_r)}>{fmtR(b.avg_r)}</span>
          </span>
        </div>
      ))}
    </div>
  );
}

function AgentsValueCard() {
  const { t } = useI18n();
  const { data, error } = useApi<AgentReport>("/review/agents", { refreshInterval: 60000 });
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>{t("agentsValue")}</CardTitle>
        <CardDescription>{t("agentsValueDesc")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {error && !data ? (
          <p className="text-loss text-xs">{t("loadFailed")}</p>
        ) : !data ? (
          <Skeleton className="h-40" />
        ) : (
          <>
            {data.agents.length > 0 && (
              <div className="overflow-x-auto">
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>{t("agentCol")}</TableHead>
                      <TableHead className="text-end">{t("callsCol")}</TableHead>
                      <TableHead className="text-end">{t("errorsCol")}</TableHead>
                      <TableHead className="text-end">{t("costCol")}</TableHead>
                      <TableHead className="text-end">{t("avgMsCol")}</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {data.agents.map((a) => (
                      <TableRow key={a.agent}>
                        <TableCell>
                          {a.agent}
                          <div className="text-muted-foreground font-mono text-[10px]">{a.models.join(", ")}</div>
                        </TableCell>
                        <TableCell className="tabular text-end">{a.calls}</TableCell>
                        <TableCell className={cn("tabular text-end", a.errors > 0 && "text-loss")}>{a.errors}</TableCell>
                        <TableCell className="tabular text-end">${a.cost.toFixed(2)}</TableCell>
                        <TableCell className="tabular text-end">{a.avg_ms}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            )}
            {data.blocked_by.length > 0 && (
              <div>
                <div className="text-muted-foreground mb-1 font-mono text-[10px] uppercase">{t("blockedBy")}</div>
                {data.blocked_by.map((b) => (
                  <div key={b.stage} className="flex justify-between border-b border-dashed py-1 font-mono text-[11px]">
                    <span>{b.stage}</span>
                    <span>{b.count}</span>
                  </div>
                ))}
              </div>
            )}
            {data.closed_trades > 0 ? (
              <div className="grid gap-4 sm:grid-cols-2">
                <Buckets title={t("byAnalystScore")} rows={data.by_analyst_score} />
                <Buckets title={t("byDevilSeverity")} rows={data.by_devil_severity} />
              </div>
            ) : (
              <p className="text-muted-foreground text-xs">{t("noClosedTrades")}</p>
            )}
            <p className="text-muted-foreground text-[11px]">{data.note}</p>
          </>
        )}
      </CardContent>
    </Card>
  );
}

function SetupHealthCard() {
  const { t } = useI18n();
  const { data, error } = useApi<SetupHealth>("/review/setups", { refreshInterval: 60000 });
  const rows = data ? Object.entries(data.setups) : [];
  const badge = {
    ok: { v: "gain", k: "statusOk" },
    cut: { v: "warn", k: "statusCut" },
    paused: { v: "loss", k: "statusPaused" },
  } as const;
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle>{t("setupHealth")}</CardTitle>
        <CardDescription>{t("setupHealthDesc")}</CardDescription>
      </CardHeader>
      <CardContent>
        {error && !data ? (
          <p className="text-loss text-xs">{t("loadFailed")}</p>
        ) : !data ? (
          <Skeleton className="h-24" />
        ) : !rows.length ? (
          <p className="text-muted-foreground text-xs">{t("noLiveTrades")}</p>
        ) : (
          rows.map(([name, s]) => {
            const b = badge[s.status] ?? badge.ok;
            return (
              <div key={name} className="flex flex-wrap items-center justify-between gap-2 border-b border-dashed py-2">
                <div>
                  <div className="font-mono text-xs font-semibold">{name}</div>
                  <div className="text-muted-foreground font-mono text-[11px]">
                    {s.trades} {t("tradesCol")} · {t("liveR")} <span className={tone(s.live_r)}>{fmtR(s.live_r)}</span> · {t("expectedR")} {fmtR(s.expected_r)}
                  </div>
                </div>
                <Badge variant={b.v}>{t(b.k)}</Badge>
              </div>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
