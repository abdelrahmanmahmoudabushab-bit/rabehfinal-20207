"use client";

import { AlertTriangle, CheckCircle2, FlaskConical, XCircle } from "lucide-react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import type { Backtest, BtStats } from "@/lib/api";
import { useI18n } from "@/lib/i18n";
import { cn } from "@/lib/utils";

const VERDICT = {
  edge: { label: "Edge confirmed", cls: "border-gain text-gain", icon: CheckCircle2 },
  no_edge: { label: "No proven edge", cls: "border-loss text-loss", icon: XCircle },
  not_enough_data: { label: "Not enough data", cls: "border-warn text-warn", icon: AlertTriangle },
  error: { label: "Backtest failed", cls: "border-loss text-loss", icon: XCircle },
} as const;

const fmtR = (x?: number) => (x == null || !isFinite(x) ? "—" : `${x >= 0 ? "+" : ""}${x.toFixed(2)}R`);

export function BacktestVerdict({ bt, compact }: { bt: Backtest; compact?: boolean }) {
  const v = VERDICT[bt.verdict] ?? VERDICT.error;
  const Icon = v.icon;
  return (
    <div className={cn("flex items-start gap-3 border-2 p-3", v.cls)}>
      <Icon className="mt-0.5 size-5 shrink-0" />
      <div className="min-w-0 space-y-1">
        <div className="flex flex-wrap items-baseline gap-x-2">
          <span className="font-mono text-sm font-bold uppercase">{v.label}</span>
          <span className="text-muted-foreground font-mono text-[11px]">
            tested {bt.variants_tested.toLocaleString()} ways
            {bt.basket ? ` on ${bt.basket.length} stocks` : bt.symbols ? ` on ${bt.symbols.length} stocks` : ""}
            {bt.days ? ` · ${bt.days} days` : ""}
            {bt.ms != null ? ` · ${(bt.ms / 1000).toFixed(1)}s` : ""}
          </span>
        </div>
        {!compact && bt.setup_description && (
          <div className="text-foreground text-xs">
            Setup: <span className="font-semibold">{bt.setup}</span> — {bt.setup_description}
          </div>
        )}
        <ul className="text-foreground/80 space-y-0.5 text-xs">
          {bt.reasons.map((r) => (
            <li key={r}>— {r}</li>
          ))}
        </ul>
        {bt.note && <div className="text-muted-foreground text-[11px]">{bt.note}</div>}
        {bt.source === "simulated" && (
          <div className="text-muted-foreground text-[11px]">Simulated history (demo market): this shows how the tool works, not whether the strategy works on real stocks.</div>
        )}
      </div>
    </div>
  );
}

function StatRow({ label, s }: { label: string; s?: BtStats }) {
  return (
    <tr className="border-b border-dashed last:border-b-0">
      <td className="py-1.5 pe-2 text-[11px] uppercase">{label}</td>
      <td className="py-1.5 text-end">{s ? s.n.toFixed(0) : "—"}</td>
      <td className="py-1.5 text-end">{s ? `${(s.win * 100).toFixed(0)}%` : "—"}</td>
      <td className={cn("py-1.5 text-end font-semibold", s && (s.exp_r > 0 ? "text-gain" : "text-loss"))}>{fmtR(s?.exp_r)}</td>
      <td className="py-1.5 text-end">{s && isFinite(s.pf) ? s.pf.toFixed(2) : "—"}</td>
      <td className="py-1.5 text-end">{s ? `${s.mdd_r.toFixed(1)}R` : "—"}</td>
    </tr>
  );
}

export function BacktestPanel({ bt, managerLevels }: { bt: Backtest; managerLevels?: { stop: number; target: number } }) {
  const best = bt.best;
  const mc = bt.monte_carlo;
  return (
    <div className="space-y-4">
      <BacktestVerdict bt={bt} />
      {best && (
        <>
          <div>
            <div className="text-muted-foreground mb-1 font-mono text-[10px] uppercase">Best variant (chosen on in-sample data only)</div>
            <div className="border px-2 py-1.5 font-mono text-[11px] break-words">{best.key}</div>
          </div>
          <table className="w-full font-mono text-xs">
            <thead>
              <tr className="text-muted-foreground border-b text-[10px] uppercase">
                <th className="py-1 text-start font-medium" />
                <th className="py-1 text-end font-medium">Trades</th>
                <th className="py-1 text-end font-medium">Win</th>
                <th className="py-1 text-end font-medium">Per trade</th>
                <th className="py-1 text-end font-medium">P. factor</th>
                <th className="py-1 text-end font-medium">Max DD</th>
              </tr>
            </thead>
            <tbody>
              <StatRow label="In-sample" s={best.is} />
              <StatRow label="Out-of-sample" s={best.oos} />
            </tbody>
          </table>
        </>
      )}

      <RegimeSelection bt={bt} />

      <div className="grid gap-4 md:grid-cols-2">
        {bt.equity && bt.equity.length > 1 && <EquityCurve data={bt.equity} />}
        {bt.heatmap && bt.heatmap.cells.length > 0 && <Heatmap h={bt.heatmap} />}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        {mc && mc.runs > 0 && mc.hist && mc.hist_edges && <MonteCarlo mc={mc} />}
        <div className="space-y-2 font-mono text-xs">
          <div className="text-muted-foreground text-[10px] uppercase">Robustness</div>
          <Kv k="Variants profitable out of sample" v={bt.share_oos_positive != null ? `${(bt.share_oos_positive * 100).toFixed(0)}%` : "—"} />
          <Kv k="Median variant, out of sample" v={fmtR(bt.median_oos_exp_r)} />
          <Kv k="In-sample → out-of-sample rank match" v={bt.is_oos_rank_corr != null ? bt.is_oos_rank_corr.toFixed(2) : "—"} />
          <p className="text-muted-foreground font-sans text-[11px] leading-relaxed">
            A rank match near 0 means the variants that looked best on old data did no better on new data — the classic sign of overfitting.
          </p>
          {bt.tuned_plan && (
            <div className="border p-2">
              <div className="text-muted-foreground text-[10px] uppercase">Tested exits for this trade</div>
              <div>
                stop {bt.tuned_plan.stop.toFixed(2)} · target {bt.tuned_plan.target.toFixed(2)} ·{" "}
                {bt.tuned_plan.max_hold_min ? `sell after ${bt.tuned_plan.max_hold_min} min` : "hold up to 15:50"} · trail {bt.tuned_plan.trail}
              </div>
              {managerLevels && (
                <div className="text-muted-foreground">
                  Manager had stop {managerLevels.stop.toFixed(2)} · target {managerLevels.target.toFixed(2)}
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RegimeSelection({ bt }: { bt: Backtest }) {
  const { t } = useI18n();
  const rg = bt.regime;
  const sel = bt.selection;
  const rows = rg ? Object.entries(rg.by_regime ?? {}) : [];
  const hasSel = sel?.candidates != null && sel.oos_t != null && sel.t_bar != null;
  if (!rg && !hasSel) return null;
  const cur = rg?.current;
  return (
    <div className="space-y-2 font-mono text-xs">
      {rg && (
        <div className="border p-2">
          <div className="text-muted-foreground mb-1 flex justify-between text-[10px] uppercase">
            <span>{t("marketRegime")}</span>
            <span className="text-foreground">
              {t("regimeNow")}: {cur ? t(cur) : t("regimeUnknown")}
            </span>
          </div>
          {rows.map(([name, r]) => (
            <div key={name} className={cn("flex justify-between border-b border-dashed py-1 last:border-b-0", name === cur && "font-bold")}>
              <span>{name === "trending" || name === "choppy" ? t(name) : name}</span>
              <span>
                {r.n} · {(r.win * 100).toFixed(0)}% · <span className={r.exp_r > 0 ? "text-gain" : "text-loss"}>{fmtR(r.exp_r)}</span>
              </span>
            </div>
          ))}
        </div>
      )}
      {hasSel && (
        <div className="text-muted-foreground text-[11px]">
          <span className="text-foreground uppercase">{t("selectionBar")}</span>:{" "}
          {t("selectionLine")
            .replace("{n}", sel!.candidates!.toLocaleString())
            .replace("{t}", sel!.oos_t!.toFixed(2))
            .replace("{bar}", sel!.t_bar!.toFixed(2))}
        </div>
      )}
    </div>
  );
}

function Kv({ k, v }: { k: string; v: string }) {
  return (
    <div className="flex justify-between gap-3 border-b border-dashed pb-1">
      <span className="text-muted-foreground font-sans">{k}</span>
      <span>{v}</span>
    </div>
  );
}

function EquityCurve({ data }: { data: NonNullable<Backtest["equity"]> }) {
  const rows = data.map((d, i) => ({ i, is: d.oos ? null : d.cum_r, oos: d.oos ? d.cum_r : null, all: d.cum_r }));
  const firstOos = rows.findIndex((r) => r.oos != null);
  if (firstOos > 0) rows[firstOos - 1].oos = rows[firstOos - 1].all; // join the two lines
  return (
    <div>
      <div className="text-muted-foreground mb-1 flex justify-between font-mono text-[10px] uppercase">
        <span>Cumulative R, best variant</span>
        <span>
          <span className="text-foreground">━</span> in-sample <span className="text-gain">━</span> out-of-sample
        </span>
      </div>
      <div className="h-40 border">
        <ResponsiveContainer width="100%" height="100%">
          <ComposedChart data={rows} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
            <CartesianGrid vertical={false} stroke="var(--color-border)" />
            <XAxis dataKey="i" hide />
            <YAxis tick={{ fill: "var(--color-muted-foreground)", fontSize: 10 }} tickLine={false} axisLine={false} />
            <Tooltip formatter={(v) => `${Number(v).toFixed(2)}R`} labelFormatter={(l) => `trade ${l}`}
              contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", fontSize: 11 }} />
            <Area dataKey="all" stroke="none" fill="var(--color-foreground)" fillOpacity={0.05} isAnimationActive={false} />
            <Line dataKey="is" stroke="var(--color-foreground)" dot={false} strokeWidth={1.5} isAnimationActive={false} connectNulls={false} />
            <Line dataKey="oos" stroke="var(--color-gain)" dot={false} strokeWidth={2} isAnimationActive={false} connectNulls={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

function Heatmap({ h }: { h: NonNullable<Backtest["heatmap"]> }) {
  const max = Math.max(0.01, ...h.cells.flat().map(Math.abs));
  return (
    <div>
      <div className="text-muted-foreground mb-1 font-mono text-[10px] uppercase">Out-of-sample R per trade: stop size × target</div>
      <div className="grid grid-cols-[52px_repeat(4,1fr)] border font-mono text-[11px]">
        <div className="text-muted-foreground border-e border-b p-1 text-[9px]">stop ↓ tgt →</div>
        {h.targets.map((t) => (
          <div key={t} className="text-muted-foreground border-b p-1 text-center text-[10px]">{t}R</div>
        ))}
        {h.stops.map((s, i) => (
          <div key={s} className="contents">
            <div className="text-muted-foreground border-e p-1 text-[10px]">{s}×ATR</div>
            {h.cells[i].map((v, j) => (
              <div
                key={j}
                className="p-1.5 text-center"
                style={{
                  background: v >= 0 ? `color-mix(in oklch, var(--color-gain) ${Math.round((v / max) * 55)}%, transparent)`
                    : `color-mix(in oklch, var(--color-loss) ${Math.round((-v / max) * 55)}%, transparent)`,
                }}
              >
                {v >= 0 ? "+" : ""}
                {v.toFixed(2)}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function MonteCarlo({ mc }: { mc: NonNullable<Backtest["monte_carlo"]> }) {
  const edges = mc.hist_edges!;
  const data = mc.hist!.map((n, i) => ({ x: (edges[i] + edges[i + 1]) / 2, n }));
  return (
    <div>
      <div className="text-muted-foreground mb-1 flex justify-between font-mono text-[10px] uppercase">
        <span>Monte Carlo: {mc.runs.toLocaleString()} reshuffles</span>
        <span className={cn((mc.p_loss ?? 0) > 0.3 ? "text-loss" : "text-gain")}>P(loss) {((mc.p_loss ?? 0) * 100).toFixed(0)}%</span>
      </div>
      <div className="h-32 border">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 6, right: 6, left: -18, bottom: 0 }}>
            <XAxis dataKey="x" tickFormatter={(v) => `${Number(v).toFixed(0)}R`} tick={{ fill: "var(--color-muted-foreground)", fontSize: 9 }} tickLine={false} axisLine={false} minTickGap={24} />
            <YAxis hide />
            <Tooltip formatter={(v) => [`${v} runs`, ""]} labelFormatter={(l) => `total ≈ ${Number(l).toFixed(1)}R`}
              contentStyle={{ background: "var(--color-popover)", border: "1px solid var(--color-border)", fontSize: 11 }} />
            <Bar dataKey="n" isAnimationActive={false} fill="var(--color-foreground)" fillOpacity={0.7} />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <div className="text-muted-foreground mt-1 grid grid-cols-3 font-mono text-[10px]">
        <span>5%: {mc.p5_total_r?.toFixed(1)}R</span>
        <span className="text-center">median: {mc.median_total_r?.toFixed(1)}R</span>
        <span className="text-end">95% DD: {mc.p95_mdd_r?.toFixed(1)}R</span>
      </div>
    </div>
  );
}

export function BacktestBadge({ bt }: { bt?: Backtest }) {
  if (!bt?.verdict) return null;
  const v = VERDICT[bt.verdict] ?? VERDICT.error;
  return (
    <span className={cn("inline-flex items-center gap-1 rounded-sm border px-1 font-mono text-[9px] uppercase", v.cls)}>
      <FlaskConical className="size-2.5" /> {bt.verdict === "edge" ? `edge ${fmtR(bt.best?.oos.exp_r)}` : v.label}
    </span>
  );
}
