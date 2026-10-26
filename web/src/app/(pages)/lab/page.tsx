"use client";

import { useState } from "react";
import { FlaskConical, Loader2, Play } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/misc";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { BacktestPanel } from "@/components/app/backtest-panel";
import { PageHeader, Stat } from "@/components/app/bits";
import { api, useApi, type LabJob, type PrecomputeStatus } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { timeAgo } from "@/lib/format";
import { cn } from "@/lib/utils";

const SETUPS: [string, string][] = [
  ["breakout", "Breakout"],
  ["vwap_pullback", "VWAP pullback"],
  ["momentum", "Momentum"],
  ["orb", "Opening-range breakout"],
];

export default function LabPage() {
  const { data: job, mutate } = useApi<LabJob | null>("/backtest/lab/latest", { refreshInterval: 1500 });
  const [setups, setSetups] = useState<string[]>(SETUPS.map(([k]) => k));
  const [days, setDays] = useState("60");
  const [busy, setBusy] = useState(false);
  const running = job?.status === "running";
  const res = job?.result;

  async function run() {
    setBusy(true);
    try {
      await mutate(await api.post<LabJob>("/backtest/lab", { setups, days: Number(days) }), { revalidate: false });
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <PageHeader
        title="Strategy lab"
        description="Test every setup, filter and exit rule on every stock in the watchlist. Variants are chosen on the first 70% of history and judged only on the last 30% they never saw, then resampled 1,000 times. This is where you find out whether there is an edge before risking money."
      >
        <Button size="lg" onClick={run} disabled={busy || running || !setups.length}>
          {running ? <Loader2 className="animate-spin" /> : <Play />} {running ? "Testing…" : "Run backtest"}
        </Button>
      </PageHeader>

      <PrecomputeCard />

      <Card className="mt-4">
        <CardContent className="flex flex-wrap items-center gap-4">
          <div className="flex flex-wrap gap-1.5">
            {SETUPS.map(([k, label]) => {
              const on = setups.includes(k);
              return (
                <button
                  key={k}
                  onClick={() => setSetups(on ? setups.filter((x) => x !== k) : [...setups, k])}
                  className={cn("cursor-pointer rounded-sm border px-2.5 py-1.5 font-mono text-[11px] uppercase", on ? "bg-foreground text-background" : "text-muted-foreground")}
                >
                  {label}
                </button>
              );
            })}
          </div>
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">History</span>
            <Select value={days} onValueChange={setDays}>
              <SelectTrigger size="sm" className="w-28 font-mono">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {["20", "60", "120", "250"].map((d) => (
                  <SelectItem key={d} value={d}>{d} days</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="text-muted-foreground ms-auto font-mono text-[11px]">
            {(setups.length * 9 * 128).toLocaleString()} variants = {setups.length} setups × 9 filters × 128 exit rules
          </div>
        </CardContent>
      </Card>

      {job === undefined ? (
        <Skeleton className="mt-4 h-80" />
      ) : !job ? (
        <Card className="mt-4">
          <CardContent className="flex flex-col items-center gap-3 py-12 text-center">
            <FlaskConical className="size-8" />
            <p className="text-muted-foreground max-w-md text-sm">No backtest yet. Run one to see which setups and exits held up on data they were not tuned on.</p>
          </CardContent>
        </Card>
      ) : running ? (
        <Card className="mt-4">
          <CardContent className="flex items-center gap-3 text-sm">
            <Loader2 className="size-4 animate-spin" /> {job.progress} · started {timeAgo(job.started_at)}
          </CardContent>
        </Card>
      ) : job.status === "failed" ? (
        <Card className="mt-4"><CardContent className="text-loss text-sm">Backtest failed: {job.error}</CardContent></Card>
      ) : res ? (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-2 gap-3 md:grid-cols-5">
            <Stat label="Variants tested" value={res.variants_tested.toLocaleString()} />
            <Stat label="Signals" value={(res.signals ?? 0).toLocaleString()} sub={`${res.symbols?.length} stocks · ${res.days} days`} />
            <Stat label="Profitable out of sample" value={`${((res.share_oos_positive ?? 0) * 100).toFixed(0)}%`} sub="of all variants" />
            <Stat label="Median variant" value={`${(res.median_oos_exp_r ?? 0) >= 0 ? "+" : ""}${(res.median_oos_exp_r ?? 0).toFixed(2)}R`} sub="per trade, out of sample" />
            <Stat label="Run time" value={`${((res.ms ?? 0) / 1000).toFixed(1)}s`} sub={`slippage ${res.slip_bps} bps / side`} />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Verdict</CardTitle>
              <CardDescription>The best in-sample variant across all setups, judged on out-of-sample data.</CardDescription>
            </CardHeader>
            <CardContent>
              <BacktestPanel bt={res} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>By setup</CardTitle>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full font-mono text-xs">
                <thead>
                  <tr className="text-muted-foreground border-b text-[10px] uppercase">
                    <th className="py-1.5 text-start font-medium">Setup</th>
                    <th className="py-1.5 text-end font-medium">Signals</th>
                    <th className="py-1.5 text-end font-medium">Variants profitable OOS</th>
                    <th className="py-1.5 text-end font-medium">Best OOS</th>
                  </tr>
                </thead>
                <tbody>
                  {res.setup_summary?.map((s) => (
                    <tr key={s.setup} className="border-b border-dashed">
                      <td className="py-1.5">
                        <div className="font-bold">{s.setup}</div>
                        <div className="text-muted-foreground font-sans text-[11px]">{s.description}</div>
                      </td>
                      <td className="py-1.5 text-end">{s.signals.toLocaleString()}</td>
                      <td className={cn("py-1.5 text-end", s.share_oos_positive >= 0.5 ? "text-gain" : "text-loss")}>{(s.share_oos_positive * 100).toFixed(0)}%</td>
                      <td className="py-1.5 text-end">{s.best_oos_exp_r >= 0 ? "+" : ""}{s.best_oos_exp_r.toFixed(2)}R</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Leaderboard</CardTitle>
              <CardDescription>Top variants ranked on in-sample results — compare with how they did out of sample. Big drops = overfitting.</CardDescription>
            </CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full font-mono text-[11px]">
                <thead>
                  <tr className="text-muted-foreground border-b text-[10px] uppercase">
                    <th className="py-1.5 text-start font-medium">#</th>
                    <th className="py-1.5 text-start font-medium">Variant</th>
                    <th className="py-1.5 text-end font-medium">IS trades</th>
                    <th className="py-1.5 text-end font-medium">IS R</th>
                    <th className="py-1.5 text-end font-medium">OOS trades</th>
                    <th className="py-1.5 text-end font-medium">OOS R</th>
                    <th className="py-1.5 text-end font-medium">OOS win</th>
                  </tr>
                </thead>
                <tbody>
                  {res.leaderboard?.map((r, i) => (
                    <tr key={r.key} className="border-b border-dashed">
                      <td className="py-1.5">{i + 1}</td>
                      <td className="max-w-[420px] py-1.5 break-words">{r.key}</td>
                      <td className="py-1.5 text-end">{r.is.n}</td>
                      <td className="py-1.5 text-end">{r.is.exp_r >= 0 ? "+" : ""}{r.is.exp_r.toFixed(2)}</td>
                      <td className="py-1.5 text-end">{r.oos.n}</td>
                      <td className={cn("py-1.5 text-end font-bold", r.oos.exp_r > 0 ? "text-gain" : "text-loss")}>
                        {r.oos.exp_r >= 0 ? "+" : ""}{r.oos.exp_r.toFixed(2)}
                      </td>
                      <td className="py-1.5 text-end">{(r.oos.win * 100).toFixed(0)}%</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      ) : null}
    </>
  );
}

function PrecomputeCard() {
  const { t } = useI18n();
  const { data, error, mutate } = useApi<PrecomputeStatus>("/backtest/precompute", { refreshInterval: 5000 });
  const [busy, setBusy] = useState(false);
  const running = data?.status === "running";
  const st = data?.status;

  async function start() {
    setBusy(true);
    try {
      await api.post("/backtest/precompute");
      toast.success(t("precomputeStarted"));
      mutate();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("nightlyPrecompute")}</CardTitle>
        <CardDescription>{t("nightlyPrecomputeDesc")}</CardDescription>
      </CardHeader>
      <CardContent>
        {error && !data ? (
          <p className="text-loss text-xs">{t("loadFailed")}</p>
        ) : !data ? (
          <Skeleton className="h-16" />
        ) : (
          <div className="flex flex-wrap items-end gap-4">
            <div className="grid flex-1 grid-cols-2 gap-3 md:grid-cols-4">
              <Stat
                label={t("statusCol")}
                value={st ? t(st) : t("idle")}
                valueClass={st === "failed" ? "text-loss" : undefined}
                sub={data.scheduled ? t("scheduledNightly") : t("notScheduled")}
              />
              <Stat
                label={t("progressCol")}
                value={data.total ? `${data.done ?? 0}/${data.total}` : "—"}
                sub={data.seconds != null ? `${data.seconds.toFixed(0)}s` : data.error ?? data.note}
              />
              <Stat label={t("cachedVerdicts")} value={data.cached_verdicts.toLocaleString()} />
              <Stat label={t("marketRegime")} value={data.regime ? t(data.regime) : t("regimeUnknown")} />
            </div>
            <Button onClick={start} disabled={busy || running}>
              {running ? <Loader2 className="animate-spin" /> : <Play />} {t("runNow")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
